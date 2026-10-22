"""
tts.py - Sintesis Suara Silvia (SBV2 lokal dengan cadangan Edge-TTS) + pemutar pygame

Kebijakan fallback yang diperbarui:
- Fallback ke Edge HANYA untuk kegagalan nyata: model gagal dimuat atau exception inferensi.
- Tidak ada timeout yang membuang hasil SBV2, tidak ada "lock sibuk -> Edge".
- Pemutus sirkuit hanya aktif untuk exception nyata (bukan lambat/timeout), jeda 15 dtk.
- SBV2_ALLOW_FALLBACK=0 -> tidak pernah fallback, error ditampilkan jelas.
- Setiap kali Edge dipakai, peringatan JELAS dengan alasannya dicetak ke konsol.

Streaming per potongan:
- Teks per baris LLM dipecah menjadi potongan <= SBV2_MAX_CHARS karakter.
- synth_clip_stream() adalah async generator: yield satu AudioClip per potongan.
- Potongan kedua disintesis sementara potongan pertama diputar (pipelining).
"""
import asyncio
from dataclasses import dataclass
import io
import re
import time
from typing import Any, AsyncIterator
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
    SBV2_ALLOW_FALLBACK,
    SBV2_MAX_CHARS,
    EMOTION_STYLE,
)

# Instance SBV2Engine tunggal (dimuat lazy oleh init_tts)
_sbv2_engine: Any = None

# Status pemutus sirkuit untuk backend auto — hanya aktif pada exception nyata berturut-turut
_circuit_broken_until: float = 0.0
_consecutive_failures: int = 0
# Jeda pemutus sirkuit lebih singkat (15 dtk) agar SBV2 segera dicoba ulang
_CIRCUIT_BREAK_DURATION = 15.0
_CIRCUIT_BREAK_THRESHOLD = 3


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


def split_chunks_jp(text: str, max_chars: int | None = None) -> list[str]:
    """Pecah teks Jepang menjadi potongan pendek untuk sintesis bertahap.

    Strategi:
    1. Pecah di 。！？…\n — batas kalimat kuat.
    2. Jika potongan masih > max_chars, pecah lagi di 、 — jeda nafas.
    3. Jika masih > max_chars, potong paksa per max_chars karakter.
    """
    limit = max_chars if max_chars is not None else SBV2_MAX_CHARS

    # Pisah di titik akhir kalimat Jepang (pertahankan delimiter di akhir potongan)
    raw = re.split(r"(?<=[。！？…!?\n])", text)
    chunks: list[str] = []

    for seg in raw:
        seg = seg.strip()
        if not seg:
            continue
        if len(seg) <= limit:
            chunks.append(seg)
        else:
            # Coba pecah lagi di 、
            sub_parts = re.split(r"(?<=、)", seg)
            current = ""
            for sp in sub_parts:
                if len(current) + len(sp) <= limit:
                    current += sp
                else:
                    if current:
                        chunks.append(current.strip())
                    if len(sp) > limit:
                        # Potong paksa
                        for i in range(0, len(sp), limit):
                            chunks.append(sp[i : i + limit].strip())
                        current = ""
                    else:
                        current = sp
            if current.strip():
                chunks.append(current.strip())

    return [c for c in chunks if c]


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
    print(f"[TTS] edge | {emotion}->{style_name} | chars={len(text)} | synth={t_synth:.2f}s | dur={dur:.2f}s | RTF={rtf:.2f}")
    return AudioClip(data=data, fmt="mp3", duration=dur)


def _synth_sbv2_chunk_sync(text: str, emotion: str, style_cfg: dict) -> AudioClip:
    """Sintesis SATU potongan teks sinkron di dalam thread pool.

    Tidak memecah teks lagi di sini — pemanggil bertanggung jawab memecah.
    """
    if _sbv2_engine is None or not _sbv2_engine.ready:
        raise RuntimeError("SBV2Engine belum siap atau gagal dimuat.")

    t0 = time.perf_counter()
    style_name = style_cfg.get("style", "Neutral")
    sr, audio = _sbv2_engine.synth(text, style_cfg)

    wav_bytes = to_wav_bytes(audio, sr)
    t_synth = time.perf_counter() - t0
    dur = len(audio) / sr if sr > 0 else 0.0
    rtf = t_synth / dur if dur > 0 else 0.0

    device = _sbv2_engine.device if _sbv2_engine else "?"
    print(
        f"[TTS] sbv2 | {emotion}->{style_name} | device={device} "
        f"| chars={len(text)} | synth={t_synth:.2f}s | dur={dur:.2f}s | RTF={rtf:.2f}"
    )
    return AudioClip(data=wav_bytes, fmt="wav", duration=dur)


# Pertahankan fungsi lama sebagai alias internal agar tidak ada import yang rusak
def _synth_sbv2_clip_sync(text: str, emotion: str, style_cfg: dict) -> AudioClip:
    """Alias mundur-kompatibel: sintesis sinkron SBV2 (dipakai oleh path edge/sbv2 sederhana)."""
    return _synth_sbv2_chunk_sync(text, emotion, style_cfg)


def _compute_timeout(text: str) -> float:
    """Hitung batas waktu proporsional: max(SBV2_TIMEOUT_S, len_chars * 0.5) detik."""
    return max(SBV2_TIMEOUT_S, len(text) * 0.5)


async def _fallback_or_raise(text: str, emotion: str, reason: str) -> AudioClip:
    """Jalankan kebijakan fallback: Edge jika diizinkan, raise jika tidak."""
    if SBV2_ALLOW_FALLBACK:
        print(
            f"[TTS] ⚠ PERINGATAN: Jatuh ke Edge-TTS! Alasan: {reason} "
            f"| chars={len(text)} | TTS_BACKEND={TTS_BACKEND}"
        )
        return await _synth_edge(text, emotion)
    else:
        msg = (
            f"[TTS] ERROR: SBV2 gagal dan SBV2_ALLOW_FALLBACK=0 (tidak ada fallback). "
            f"Alasan: {reason} | chars={len(text)}"
        )
        print(msg)
        raise RuntimeError(msg)


async def synth_clip(text: str, emotion: str) -> AudioClip:
    """Sintesis SATU teks (bisa panjang) menjadi AudioClip — tetap ada untuk kompatibilitas.

    Untuk jawaban panjang, lebih baik gunakan synth_clip_stream() agar audio
    mulai diputar lebih awal.
    """
    global _circuit_broken_until, _consecutive_failures

    clean_text = normalize_for_tts(text)
    if not clean_text:
        default_fmt = "wav" if TTS_BACKEND in ("sbv2", "auto") else "mp3"
        return AudioClip(data=b"", fmt=default_fmt, duration=0.0)

    style_cfg = EMOTION_STYLE.get(
        emotion,
        EMOTION_STYLE.get("neutral", {"style": "Neutral", "style_weight": 1.0, "length": 1.0}),
    )

    if TTS_BACKEND == "edge":
        return await _synth_edge(clean_text, emotion)

    if TTS_BACKEND == "sbv2":
        # Mode sbv2: gunakan fallback jika diizinkan bila engine gagal dimuat saat startup
        if _sbv2_engine is None or not _sbv2_engine.ready:
            return await _fallback_or_raise(
                clean_text,
                emotion,
                "SBV2Engine belum diinisialisasi atau gagal dimuat saat startup.",
            )
        timeout = _compute_timeout(clean_text)
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(_synth_sbv2_chunk_sync, clean_text, emotion, style_cfg),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            msg = f"timeout ({timeout:.0f}s) saat mensintesis {len(clean_text)} karakter"
            print(f"[TTS] ERROR: SBV2 {msg}")
            raise RuntimeError(f"SBV2 {msg}")

    # Backend == "auto"
    now = time.time()
    # 1. Cek circuit breaker: hanya aktif untuk exception nyata, bukan timeout/lambat
    if now < _circuit_broken_until:
        remaining = _circuit_broken_until - now
        return await _fallback_or_raise(
            clean_text, emotion,
            f"pemutus sirkuit aktif (sisa {remaining:.0f}s, {_consecutive_failures} exception nyata berturut-turut)"
        )

    # 2. Cek kesiapan SBV2
    if _sbv2_engine is None or not _sbv2_engine.ready:
        return await _fallback_or_raise(clean_text, emotion, "SBV2Engine tidak siap (model belum dimuat)")

    # 3. Jalankan SBV2 — menunggu lock itu wajar, kalimat berjalan berurutan
    timeout = _compute_timeout(clean_text)
    try:
        clip = await asyncio.wait_for(
            asyncio.to_thread(_synth_sbv2_chunk_sync, clean_text, emotion, style_cfg),
            timeout=timeout,
        )
        _consecutive_failures = 0
        return clip
    except asyncio.TimeoutError:
        # Timeout proporsional yang sangat panjang = kemungkinan macet total, bukan sekadar lambat
        print(
            f"[TTS] ⚠ SBV2 timeout macet total ({timeout:.0f}s) untuk {len(clean_text)} karakter. "
            f"Ini BUKAN jatuh ke Edge karena lambat."
        )
        _consecutive_failures += 1
        if _consecutive_failures >= _CIRCUIT_BREAK_THRESHOLD:
            _circuit_broken_until = time.time() + _CIRCUIT_BREAK_DURATION
            print(
                f"[TTS] ⚠ Pemutus sirkuit aktif {_CIRCUIT_BREAK_DURATION:.0f}s "
                f"({_consecutive_failures} timeout berturut-turut)."
            )
        return await _fallback_or_raise(
            clean_text, emotion,
            f"timeout total {timeout:.0f}s untuk {len(clean_text)} karakter"
        )
    except Exception as e:
        # Exception nyata (CUDA OOM, dll.): coba torch.cuda.empty_cache() lalu retry sekali
        if "out of memory" in str(e).lower() or "cuda" in str(e).lower():
            print(f"[TTS] ⚠ SBV2 CUDA OOM/error: {e}. Mencoba empty_cache dan retry...")
            try:
                import torch
                torch.cuda.empty_cache()
            except Exception:
                pass
            try:
                clip = await asyncio.wait_for(
                    asyncio.to_thread(_synth_sbv2_chunk_sync, clean_text, emotion, style_cfg),
                    timeout=timeout,
                )
                _consecutive_failures = 0
                return clip
            except Exception as e2:
                print(f"[TTS] ⚠ SBV2 retry setelah OOM juga gagal: {e2}")
                e = e2

        _consecutive_failures += 1
        if _consecutive_failures >= _CIRCUIT_BREAK_THRESHOLD:
            _circuit_broken_until = time.time() + _CIRCUIT_BREAK_DURATION
            print(
                f"[TTS] ⚠ Pemutus sirkuit aktif {_CIRCUIT_BREAK_DURATION:.0f}s "
                f"({_consecutive_failures} exception nyata berturut-turut)."
            )
        return await _fallback_or_raise(
            clean_text, emotion, f"{type(e).__name__}: {e}"
        )


async def synth_clip_stream(
    text: str,
    emotion: str,
) -> AsyncIterator[AudioClip]:
    """Async generator: pecah teks menjadi potongan dan yield AudioClip per potongan.

    Sintesis berjalan secara berurutan (menunggu lock wajar).
    Potongan pertama di-yield segera setelah selesai, sementara potongan berikutnya
    disintesis di background sehingga pemutaran dan sintesis berjalan tumpang tindih.
    """
    clean_text = normalize_for_tts(text)
    if not clean_text:
        return

    style_cfg = EMOTION_STYLE.get(
        emotion,
        EMOTION_STYLE.get("neutral", {"style": "Neutral", "style_weight": 1.0, "length": 1.0}),
    )

    # Pecah teks menjadi potongan pendek
    if TTS_BACKEND == "edge":
        # Edge-TTS: tidak perlu memecah, sintesis sekaligus
        clip = await _synth_edge(clean_text, emotion)
        yield clip
        return

    chunks = split_chunks_jp(clean_text, max_chars=SBV2_MAX_CHARS)
    if not chunks:
        return

    for chunk in chunks:
        if not chunk:
            continue
        # synth_clip menangani logika fallback, circuit breaker, dll.
        clip = await synth_clip(chunk, emotion)
        yield clip


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
            if TTS_BACKEND == "sbv2" and not SBV2_ALLOW_FALLBACK:
                print(f"[TTS] ERROR: Gagal memuat SBV2Engine dan SBV2_ALLOW_FALLBACK=0: {e}")
                raise
            elif TTS_BACKEND == "sbv2":
                print(
                    f"[TTS] ⚠ PERINGATAN: Gagal memuat SBV2Engine ({e}). "
                    f"SBV2_ALLOW_FALLBACK=1, menggunakan Edge-TTS sebagai cadangan."
                )
                _sbv2_engine = None
            else:
                print(
                    f"[TTS] ⚠ PERINGATAN: Gagal memuat SBV2Engine ({e}). "
                    f"Menggunakan Edge-TTS sebagai cadangan (mode auto)."
                )
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

