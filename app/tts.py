"""
tts.py - Sintesis Suara Silvia (SBV2 lokal dengan cadangan Edge-TTS) + pemutar pygame
"""
import asyncio
from dataclasses import dataclass
import io
import re
import time
from typing import Any
import wave
import numpy as np
import edge_tts
import pygame

from app.config import (
    TTS_VOICE,
    EMOTION_PROSODY,
    EMOTIONS,
    ANIMATIONS,
    TTS_BACKEND,
    SBV2_TIMEOUT_S,
    EMOTION_STYLE,
)

# Instance SBV2Engine tunggal (dimuat lazy oleh init_tts)
_sbv2_engine: Any = None

# Status pemutus sirkuit (circuit breaker) untuk backend auto
_circuit_broken_until: float = 0.0
_consecutive_failures: int = 0


@dataclass
class AudioClip:
    """Representasi klip audio hasil sintesis TTS."""
    data: bytes
    fmt: str  # "wav" atau "mp3"
    duration: float | None = None


def to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    """Konversi numpy array audio PCM ke bytes format WAV mono 16-bit."""
    if audio.dtype != np.int16:
        if audio.dtype in (np.float16, np.float32, np.float64):
            max_val = float(np.max(np.abs(audio))) if len(audio) > 0 else 1.0
            if max_val > 0:
                audio = audio / max_val
            audio = (audio * 32767.0).clip(-32768, 32767).astype(np.int16)
        else:
            audio = audio.astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)      # mono
        wf.setsampwidth(2)      # 16-bit = 2 bytes
        wf.setframerate(sample_rate)
        wf.writeframes(audio.tobytes())
    return buf.getvalue()


def normalize_for_tts(text: str) -> str:
    """Membersihkan teks sebelum disintesis: hapus emoji, markup, kontrol, dan rapikan spasi."""
    if not text:
        return ""

    # Ubah gelombang suara 〜 atau ～ menjadi perpanjangan nada Jepang ー
    text = text.replace("〜", "ー").replace("～", "ー").replace("~", "ー")

    # Buang markup HTML / XML
    text = re.sub(r"<[^>]+>", "", text)

    # Buang format Markdown (*, _, `, #)
    text = re.sub(r"[*_`#]", "", text)

    # Buang emoji umum
    emoji_pattern = re.compile(
        r"[\U00010000-\U0010ffff"
        r"\u2600-\u27bf"
        r"\u2300-\u23ff"
        r"\u2b50-\u2b55"
        r"\u200d\ufe0f"
        r"]+",
        flags=re.UNICODE,
    )
    text = emoji_pattern.sub("", text)

    # Buang karakter kontrol (pertahankan spasi dan enter)
    text = "".join(ch for ch in text if ch.isprintable() or ch in " \t\n")

    # Rapikan spasi berlebih
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text


def _split_sentences(text: str, max_len: int = 150) -> list[str]:
    """Pecah teks panjang per kalimat dengan batas panjang karakter tertentu."""
    raw_parts = re.split(r"([。！？!?\n]+)", text)
    sentences = []
    curr = ""
    for i in range(0, len(raw_parts), 2):
        part = raw_parts[i]
        delim = raw_parts[i + 1] if i + 1 < len(raw_parts) else ""
        seg = part + delim
        if not seg.strip():
            continue
        if len(curr) + len(seg) <= max_len:
            curr += seg
        else:
            if curr:
                sentences.append(curr.strip())
            if len(seg) > max_len:
                for s in range(0, len(seg), max_len):
                    sentences.append(seg[s : s + max_len].strip())
                curr = ""
            else:
                curr = seg
    if curr.strip():
        sentences.append(curr.strip())
    return [s for s in sentences if s]


def parse_line(line: str):
    """'[happy|greetings] 日本語|||Indonesia' -> (emotion, animation_or_None, jp, idn).
    
    Emosi tak dikenal -> 'neutral'. Animasi tak dikenal/'none' -> None.
    """
    emotion = "neutral"
    animation = None

    m = re.match(r"\s*\[([^\]]+)\]\s*(.*)", line)
    if m:
        tag_raw = m.group(1).lower()
        line = m.group(2)
        # Tag bisa berformat "emosi" atau "emosi|animasi"
        parts = [p.strip() for p in tag_raw.split("|")]
        raw_emotion = parts[0]
        raw_anim = parts[1] if len(parts) > 1 else None

        if raw_emotion in EMOTIONS:
            emotion = raw_emotion

        if raw_anim and raw_anim not in ("none", "", "null"):
            # Validasi: animasi harus ada di daftar ANIMATIONS
            if raw_anim in ANIMATIONS:
                animation = raw_anim
            else:
                # Log ke konsol tapi tidak crash
                print(f"[TTS] Animasi '{raw_anim}' tidak ada di daftar, dilewati.")

    jp, _, idn = line.partition("|||")
    return emotion, animation, jp.strip(), idn.strip()


async def _synth_edge(text: str, emotion: str) -> AudioClip:
    """Sintesis teks via Edge-TTS menghasilkan AudioClip dengan format mp3."""
    t0 = time.perf_counter()
    p = EMOTION_PROSODY.get(emotion, EMOTION_PROSODY["neutral"])
    comm = edge_tts.Communicate(text, TTS_VOICE, rate=p["rate"], pitch=p["pitch"])
    buf = bytearray()
    dur = 0.0

    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            buf.extend(chunk["data"])
        elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
            offset = chunk.get("offset", 0)
            duration = chunk.get("duration", 0)
            dur = max(dur, (offset + duration) / 10_000_000)

    t_synth = time.perf_counter() - t0
    data = bytes(buf)
    if dur <= 0.0 and len(data) > 0:
        dur = len(data) / 16000.0  # Estimasi jika durasi boundary tidak tersedia

    rtf = t_synth / dur if dur > 0 else 0.0
    style_name = EMOTION_STYLE.get(emotion, {}).get("style", emotion)
    print(f"[TTS] edge | {emotion}->{style_name} | synth={t_synth:.2f}s | dur={dur:.2f}s | RTF={rtf:.2f}")
    return AudioClip(data=data, fmt="mp3", duration=dur)


def _synth_sbv2_clip_sync(text: str, emotion: str, style_cfg: dict) -> AudioClip:
    """Sintesis sinkron SBV2 yang dijalankan di dalam thread pool."""
    if _sbv2_engine is None or not _sbv2_engine.ready:
        raise RuntimeError("SBV2Engine belum siap atau gagal dimuat.")

    t0 = time.perf_counter()
    style_name = style_cfg.get("style", "Neutral")

    if len(text) <= 150:
        sr, audio = _sbv2_engine.synth(text, style_cfg)
    else:
        # Teks > 150 karakter dipecah per kalimat lalu digabung jeda hening ~0.15 dtk
        sentences = _split_sentences(text, max_len=150)
        chunks = []
        sr = 44100
        for s in sentences:
            sr, chunk = _sbv2_engine.synth(s, style_cfg)
            chunks.append(chunk)

        silence = np.zeros(int(sr * 0.15), dtype=np.int16)
        merged = []
        for i, c in enumerate(chunks):
            if i > 0:
                merged.append(silence)
            merged.append(c)
        audio = np.concatenate(merged) if merged else np.zeros(0, dtype=np.int16)

    wav_bytes = to_wav_bytes(audio, sr)
    t_synth = time.perf_counter() - t0
    dur = len(audio) / sr if sr > 0 else 0.0
    rtf = t_synth / dur if dur > 0 else 0.0

    print(f"[TTS] sbv2 | {emotion}->{style_name} | synth={t_synth:.2f}s | dur={dur:.2f}s | RTF={rtf:.2f}")
    return AudioClip(data=wav_bytes, fmt="wav", duration=dur)


async def synth_clip(text: str, emotion: str) -> AudioClip:
    """Sintesis teks menjadi AudioClip dengan pemilihan backend (edge, sbv2, atau auto)."""
    global _circuit_broken_until, _consecutive_failures

    clean_text = normalize_for_tts(text)
    if not clean_text:
        default_fmt = "wav" if TTS_BACKEND == "sbv2" else "mp3"
        return AudioClip(data=b"", fmt=default_fmt, duration=0.0)

    style_cfg = EMOTION_STYLE.get(
        emotion,
        EMOTION_STYLE.get("neutral", {"style": "Neutral", "style_weight": 1.0, "length": 1.0}),
    )

    if TTS_BACKEND == "edge":
        return await _synth_edge(clean_text, emotion)

    if TTS_BACKEND == "sbv2":
        if _sbv2_engine is None or not _sbv2_engine.ready:
            raise RuntimeError("SBV2Engine belum diinisialisasi atau gagal dimuat.")
        return await asyncio.to_thread(_synth_sbv2_clip_sync, clean_text, emotion, style_cfg)

    # Backend == "auto"
    now = time.time()
    # 1. Cek circuit breaker (3 kegagalan berturut-turut -> 60s fallback Edge)
    if now < _circuit_broken_until:
        return await _synth_edge(clean_text, emotion)

    # 2. Cek kesiapan SBV2
    if _sbv2_engine is None or not _sbv2_engine.ready:
        print("[TTS] Peringatan: SBV2Engine tidak siap, beralih ke Edge-TTS.")
        return await _synth_edge(clean_text, emotion)

    # 3. Cek apakah inferensi sebelumnya masih jalan (lock terkunci)
    if _sbv2_engine.lock.locked():
        print("[TTS] SBV2 sedang sibuk (inferensi sebelumnya masih berjalan), langsung beralih ke Edge.")
        return await _synth_edge(clean_text, emotion)

    # 4. Jalankan SBV2 dengan batas waktu (timeout)
    try:
        clip = await asyncio.wait_for(
            asyncio.to_thread(_synth_sbv2_clip_sync, clean_text, emotion, style_cfg),
            timeout=SBV2_TIMEOUT_S,
        )
        _consecutive_failures = 0
        return clip
    except Exception as e:
        _consecutive_failures += 1
        if _consecutive_failures >= 3:
            _circuit_broken_until = time.time() + 60.0
            print(f"[TTS] Peringatan: SBV2 gagal 3x berturut-turut ({type(e).__name__}: {e}). Pemutus sirkuit aktif: menggunakan Edge-TTS selama 60 detik.")
        else:
            print(f"[TTS] Peringatan: SBV2 gagal/timeout ({type(e).__name__}: {e}), beralih ke Edge-TTS untuk baris ini.")
        return await _synth_edge(clean_text, emotion)


async def synth(text: str, emotion: str) -> bytes:
    """Pembungkus kompatibilitas lama: mengembalikan bytes audio."""
    clip = await synth_clip(text, emotion)
    return clip.data


def init_tts():
    """Inisialisasi sistem TTS. Memuat SBV2Engine bila TTS_BACKEND adalah 'sbv2' atau 'auto'."""
    global _sbv2_engine
    if TTS_BACKEND in ("sbv2", "auto"):
        try:
            from app.tts_sbv2 import SBV2Engine
            engine = SBV2Engine()
            engine.load()
            _sbv2_engine = engine
        except Exception as e:
            if TTS_BACKEND == "sbv2":
                print(f"[TTS] Gagal memuat SBV2Engine pada backend sbv2: {e}")
                raise
            else:
                print(f"[TTS] Peringatan: Gagal memuat SBV2Engine ({e}). Menggunakan Edge-TTS sebagai cadangan.")
                _sbv2_engine = None


def init_player():
    """Inisialisasi pygame mixer untuk pemutaran audio."""
    if not pygame.mixer.get_init():
        pygame.mixer.init()


def quit_player():
    """Tutup pygame mixer."""
    if pygame.mixer.get_init():
        pygame.mixer.quit()


def play(data_or_clip: bytes | AudioClip):
    """Putar audio via pygame (BLOCKING sampai selesai). Menerima bytes (MP3) atau AudioClip."""
    if isinstance(data_or_clip, AudioClip):
        fmt = data_or_clip.fmt
        raw_data = data_or_clip.data
    else:
        fmt = "mp3"
        raw_data = data_or_clip

    if not raw_data:
        return

    init_player()
    pygame.mixer.music.load(io.BytesIO(raw_data), namehint=fmt)
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        pygame.time.Clock().tick(30)
