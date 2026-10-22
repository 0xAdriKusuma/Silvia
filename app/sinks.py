"""
sinks.py - Abstraksi output pipeline

ConsoleSink: perilaku lama (cetak + play via pygame di Python)
WebSink    : kirim tiap baris ke browser via WebSocket sebagai JSON+base64 MP3
"""
import asyncio
import base64
import json
import time
from abc import ABC, abstractmethod
from typing import Optional, Union

from app.tts import play, AudioClip


class BaseSink(ABC):
    """Interface sink untuk pipeline output."""

    @abstractmethod
    async def set_status(self, state: str):
        """Kirim status ke klien: listening | transcribing | thinking | speaking."""

    @abstractmethod
    async def emit_line(
        self,
        emotion: str,
        animation: Optional[str],
        jp: str,
        idn: str,
        audio: Union[bytes, AudioClip],
    ):
        """Kirim/putar satu baris balasan."""

    @abstractmethod
    async def end_turn(self):
        """Tandai akhir giliran; tunggu konfirmasi pemutaran selesai bila perlu."""


class ConsoleSink(BaseSink):
    """Sink konsol: cetak ke terminal dan putar audio via pygame (perilaku asli)."""

    def __init__(self, loop: asyncio.AbstractEventLoop = None):
        self._loop = loop or asyncio.get_event_loop()
        self._t0 = time.perf_counter()
        self._first = True

    def reset_timer(self):
        self._t0 = time.perf_counter()
        self._first = True

    async def set_status(self, state: str):
        # Mode konsol: status hanya dicetak jika state penting
        if state in ("transcribing", "thinking"):
            print(f"[STATUS] {state}...")

    async def emit_line(
        self,
        emotion: str,
        animation: Optional[str],
        jp: str,
        idn: str,
        audio: Union[bytes, AudioClip],
    ):
        if self._first:
            print(
                f"[TOTAL] suara pertama keluar setelah {time.perf_counter() - self._t0:.2f} dtk"
            )
            self._first = False

        anim_str = f" +{animation}" if animation else ""
        print(f"  [{emotion}{anim_str}] {jp}\n     -> {idn}")

        # Putar audio secara blocking di thread executor agar tidak memblokir event loop
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, play, audio)

    async def end_turn(self):
        # Mode konsol: tidak perlu menunggu konfirmasi dari mana pun
        pass


class WebSink(BaseSink):
    """Sink web: kirim audio+metadata ke semua klien WebSocket yang terhubung.
    
    Menunggu pesan 'playback_done' dari browser sebelum end_turn() kembali,
    sehingga mic tetap muted sampai semua audio selesai diputar di browser.
    """

    def __init__(self, broadcast_fn, wait_for_done_fn, timeout: float = 60.0):
        """
        broadcast_fn     : async callable(msg_dict) -> kirim JSON ke semua klien
        wait_for_done_fn : async callable(timeout) -> tunggu event playback_done
        timeout          : batas waktu tunggu (detik)
        """
        self._broadcast = broadcast_fn
        self._wait_done = wait_for_done_fn
        self._timeout = timeout

    async def set_status(self, state: str):
        await self._broadcast({"type": "status", "state": state})

    async def emit_line(
        self,
        emotion: str,
        animation: Optional[str],
        jp: str,
        idn: str,
        audio: Union[bytes, AudioClip],
    ):
        if isinstance(audio, AudioClip):
            raw_bytes = audio.data
            audio_fmt = audio.fmt
        else:
            raw_bytes = audio
            audio_fmt = "mp3"

        audio_b64 = base64.b64encode(raw_bytes).decode("ascii") if raw_bytes else ""
        await self._broadcast(
            {
                "type": "line",
                "emotion": emotion,
                "animation": animation,
                "jp": jp,
                "id": idn,
                "audio": audio_b64,
                "audio_format": audio_fmt,
            }
        )

    async def end_turn(self):
        await self._broadcast({"type": "turn_end"})
        try:
            await asyncio.wait_for(self._wait_done(), timeout=self._timeout)
        except asyncio.TimeoutError:
            print("[WebSink] Timeout menunggu playback_done dari browser.")
