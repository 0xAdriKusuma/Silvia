"""
mic.py - Pengelolaan mikrofon, Silero VAD, dan pengambilan ucapan.

Perubahan push-to-talk:
- Kelas Mic kini mendukung start()/stop() yang membuka/menutup InputStream secara nyata.
- listen_utterance menerima cancel_event dan timeout; mengembalikan None bila dibatalkan/timeout.
- Mode 'hold': kumpulkan frame sampai hold_stop_event diset, lalu kembalikan langsung (tanpa VAD end).
- MIC_KEEP_OPEN=1: stream tetap terbuka saat idle, tapi frame dibuang (discard_frames=True).
"""
import queue
import threading
import time
from collections import deque

import numpy as np
import torch
from silero_vad import load_silero_vad

from app.config import (
    SAMPLE_RATE,
    CHUNK,
    CHUNK_MS,
    VAD_THRESHOLD,
    END_SILENCE_MS,
    MIN_SPEECH_MS,
    MAX_SPEECH_S,
    PREROLL_CHUNKS,
    MIC_KEEP_OPEN,
)

# Batasi PyTorch ke 1 thread CPU untuk Silero VAD agar hemat CPU dan tidak ada thread contention
torch.set_num_threads(1)


class Mic:
    """Abstraksi mikrofon dengan dukungan start/stop stream dan discard frame saat idle."""

    def __init__(self):
        self.q = queue.Queue()
        self.muted = False           # True saat memproses/berbicara agar suara karakter tidak masuk
        self.discard_frames = False  # True saat MIC_KEEP_OPEN=1 dan status idle
        self._stream = None          # sounddevice.InputStream aktif
        self._stream_lock = threading.Lock()

    # ── Callback sounddevice ──────────────────────────────────────────────────

    def callback(self, indata, frames, _t, status):
        """Dipanggil oleh sounddevice di setiap chunk audio masuk."""
        if self.muted or self.discard_frames:
            return
        self.q.put(indata[:, 0].copy())

    # ── Buka / tutup stream ───────────────────────────────────────────────────

    def start(self) -> float:
        """Buka InputStream; kembalikan latensi pembukaan (detik).

        Bila MIC_KEEP_OPEN=1 dan stream sudah terbuka, cukup hentikan discard.
        Ukur latensi: jika >0.3 dtk, suku kata pertama berisiko terpotong;
        gunakan MIC_KEEP_OPEN=1 sebagai workaround (indikator mic OS tetap menyala).
        """
        import sounddevice as sd

        t0 = time.perf_counter()
        with self._stream_lock:
            if self._stream is not None and self._stream.active:
                # Stream sudah terbuka (MIC_KEEP_OPEN=1): hentikan pembuangan frame
                self.discard_frames = False
                latency = time.perf_counter() - t0
                return latency

            # Buka stream baru
            self.drain()
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=CHUNK,
                callback=self.callback,
            )
            self._stream.start()

        latency = time.perf_counter() - t0
        print(f"[Mic] Stream dibuka, latensi={latency*1000:.1f} ms"
              + (" ⚠ >300ms, suku kata pertama mungkin terpotong – coba MIC_KEEP_OPEN=1" if latency > 0.3 else ""))
        return latency

    def stop(self):
        """Tutup InputStream (MIC_KEEP_OPEN=0) atau aktifkan discard frame (MIC_KEEP_OPEN=1)."""
        with self._stream_lock:
            if self._stream is None:
                return
            if MIC_KEEP_OPEN:
                # Jaga stream tetap terbuka tapi buang semua frame; indikator OS tetap menyala
                self.discard_frames = True
            else:
                # Tutup stream sepenuhnya; indikator mic OS akan mati
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
        self.drain()

    def drain(self):
        """Kosongkan antrian audio yang tersisa."""
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except queue.Empty:
                break


# ── Inisialisasi VAD ──────────────────────────────────────────────────────────

def init_vad():
    torch.set_num_threads(1)
    return load_silero_vad()


# ── Pengambilan ucapan ────────────────────────────────────────────────────────

def listen_utterance(
    mic: "Mic",
    vad,
    *,
    cancel_event: threading.Event | None = None,
    timeout_s: float | None = None,
    hold_stop_event: threading.Event | None = None,
) -> np.ndarray | None:
    """Blok sampai satu ucapan selesai; kembalikan audio float32 16 kHz atau None.

    Parameter:
        cancel_event   : Event – bila diset, fungsi berhenti dan mengembalikan None.
        timeout_s      : Batas waktu (dtk) menunggu awal ucapan; None = tidak ada batas.
        hold_stop_event: Event untuk mode 'hold' – rekam sampai event ini diset, lalu kembalikan.
    """
    # Reset state VAD setiap sesi mendengarkan baru
    vad.reset_states()

    # ── Mode hold: kumpulkan frame sampai tombol dilepas ─────────────────────
    if hold_stop_event is not None:
        buf = []
        max_samples = int(MAX_SPEECH_S * SAMPLE_RATE)
        while not hold_stop_event.is_set():
            if cancel_event and cancel_event.is_set():
                return None
            try:
                chunk = mic.q.get(timeout=0.05)
                buf.append(chunk)
                if sum(len(c) for c in buf) >= max_samples:
                    break
            except queue.Empty:
                continue
        # Kumpulkan sisa frame yang masih ada di antrian (debounce)
        while not mic.q.empty():
            try:
                buf.append(mic.q.get_nowait())
            except queue.Empty:
                break
        return np.concatenate(buf) if buf else None

    # ── Mode VAD normal (toggle / always) ─────────────────────────────────────
    preroll = deque(maxlen=PREROLL_CHUNKS)
    buf, in_speech, silence_ms = [], False, 0
    t_start = time.monotonic()

    while True:
        # Cek batal
        if cancel_event and cancel_event.is_set():
            return None

        # Cek timeout (hanya sebelum awal bicara terdeteksi)
        if timeout_s is not None and not in_speech:
            if time.monotonic() - t_start >= timeout_s:
                return None  # timeout tanpa ada suara

        # Ambil chunk dengan timeout singkat agar loop cek event secara berkala
        try:
            chunk = mic.q.get(timeout=0.05)
        except queue.Empty:
            continue

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
            # Terlalu pendek → anggap noise, mulai ulang
            in_speech, buf, silence_ms = False, [], 0
            preroll.clear()
            vad.reset_states()
