"""
tts.py - Sintesis Edge-TTS + pemutar audio pygame

parse_line sekarang mengembalikan 4 nilai: (emotion, animation|None, jp, idn)
Format tag LLM: [emosi|animasi] atau [emosi]
"""
import io
import re
import edge_tts
import pygame
from app.config import TTS_VOICE, EMOTION_PROSODY, EMOTIONS, ANIMATIONS


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


async def synth(text: str, emotion: str) -> bytes:
    """Sintesis teks Jepang -> bytes MP3 via Edge-TTS."""
    p = EMOTION_PROSODY.get(emotion, EMOTION_PROSODY["neutral"])
    comm = edge_tts.Communicate(text, TTS_VOICE, rate=p["rate"], pitch=p["pitch"])
    buf = bytearray()
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            buf.extend(chunk["data"])
    return bytes(buf)


def init_player():
    """Inisialisasi pygame mixer untuk pemutaran audio."""
    if not pygame.mixer.get_init():
        pygame.mixer.init()


def quit_player():
    """Tutup pygame mixer."""
    if pygame.mixer.get_init():
        pygame.mixer.quit()


def play(data: bytes):
    """Putar audio MP3 via pygame (BLOCKING sampai selesai)."""
    pygame.mixer.music.load(io.BytesIO(data), "mp3")
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        pygame.time.Clock().tick(30)
