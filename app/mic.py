import queue
from collections import deque
import numpy as np
import torch
from silero_vad import load_silero_vad
from app.config import (
    SAMPLE_RATE,
    CHUNK_MS,
    VAD_THRESHOLD,
    END_SILENCE_MS,
    MIN_SPEECH_MS,
    MAX_SPEECH_S,
    PREROLL_CHUNKS,
)


class Mic:
    def __init__(self):
        self.q = queue.Queue()
        self.muted = False  # True saat memproses/berbicara agar suara karakter tidak masuk lagi

    def callback(self, indata, frames, _t, status):
        if self.muted:
            return
        self.q.put(indata[:, 0].copy())

    def drain(self):
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except queue.Empty:
                break


def init_vad():
    return load_silero_vad()


def listen_utterance(mic: Mic, vad) -> np.ndarray:
    """Blok sampai satu ucapan selesai, kembalikan audio float32 16 kHz."""
    preroll = deque(maxlen=PREROLL_CHUNKS)
    buf, in_speech, silence_ms = [], False, 0
    vad.reset_states()

    while True:
        chunk = mic.q.get()
        prob = vad(torch.from_numpy(chunk), SAMPLE_RATE).item()
        is_speech = prob >= VAD_THRESHOLD

        if not in_speech:
            if is_speech:
                in_speech = True
                buf = list(preroll) + [chunk]
                silence_ms = 0
            else:
                preroll.append(chunk)
            continue

        buf.append(chunk)
        silence_ms = 0 if is_speech else silence_ms + CHUNK_MS
        dur_ms = len(buf) * CHUNK_MS

        if silence_ms >= END_SILENCE_MS or dur_ms >= MAX_SPEECH_S * 1000:
            if dur_ms - silence_ms >= MIN_SPEECH_MS:
                return np.concatenate(buf)
            # Terlalu pendek -> anggap noise, mulai ulang
            in_speech, buf, silence_ms = False, [], 0
            preroll.clear()
            vad.reset_states()
