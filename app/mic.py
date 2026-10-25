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


# Batasi PyTorch ke 1 thread CPU untuk Silero VAD agar hemat CPU dan tidak ada thread contention
torch.set_num_threads(1)


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
    torch.set_num_threads(1)
    return load_silero_vad()


def listen_utterance(mic: Mic, vad) -> np.ndarray:
    """Blok sampai satu ucapan selesai (blocking I/O tanpa busy-wait), kembalikan audio float32 16 kHz."""
    preroll = deque(maxlen=PREROLL_CHUNKS)
    buf, in_speech, silence_ms = [], False, 0
    vad.reset_states()

    while True:
        # Blocking call (block=True) - thread tertidur di condition variable sampai ada audio baru
        chunk = mic.q.get(block=True)
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
