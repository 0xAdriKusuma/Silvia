import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# ----------------------------- KONFIGURASI -----------------------------
CHARACTER_NAME = "Silvia"  # Ganti sesuai nama karakter Anda

# Direktori aset VRM/VRMA milik pengguna (cari rekursif)
ASSETS_DIR = BASE_DIR / "assets"

# Nama file VRM spesifik (kosongkan = ambil .vrm pertama yang ditemukan di ASSETS_DIR)
VRM_FILE = ""

# Audio / VAD
SAMPLE_RATE = 16000
CHUNK = 512                             # Silero VAD wajib 512 sampel pada 16 kHz
CHUNK_MS = CHUNK * 1000 // SAMPLE_RATE  # 32 ms
VAD_THRESHOLD = 0.5
END_SILENCE_MS = 300                    # Diam selama ini = ucapan selesai
MIN_SPEECH_MS = 400                     # Ucapan lebih pendek diabaikan (noise)
MAX_SPEECH_S = 30
PREROLL_CHUNKS = 10                     # Simpan ~320 ms sebelum bicara terdeteksi

# STT
WHISPER_MODEL = "small"
STT_LANG = "id"                         # Ganti "ja" jika ingin bicara bahasa Jepang

# LLM (OpenAI-compatible: Groq, Gemini, OpenRouter, Ollama, dll.)
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "")
MAX_HISTORY_MESSAGES = 12

# TTS
TTS_VOICE = "ja-JP-NanamiNeural"

# Prosodi TTS per emosi
EMOTION_PROSODY = {
    "happy":     {"rate": "+20%", "pitch": "+4Hz"},
    "neutral":   {"rate": "+8%",  "pitch": "+0Hz"},
    "shy":       {"rate": "-5%",  "pitch": "+2Hz"},
    "sad":       {"rate": "-10%", "pitch": "-4Hz"},
    "angry":     {"rate": "+12%", "pitch": "+2Hz"},
    "surprised": {"rate": "+15%", "pitch": "+6Hz"},
    "sleepy":    {"rate": "-15%", "pitch": "-3Hz"},
}

# Daftar emosi yang valid (disinkronkan dengan kunci EMOTION_PROSODY)
EMOTIONS = list(EMOTION_PROSODY.keys())

# Pemetaan emosi -> bobot blendshape (sumber tunggal, dikirim ke browser via /api/config)
# Key = nama ekspresi VRM (expressionManager), value = bobot 0.0-1.0
EMOTION_EXPRESSION = {
    "happy":     {"happy": 1.0},
    "neutral":   {},
    "shy":       {"relaxed": 0.6, "happy": 0.35},
    "sad":       {"sad": 1.0},
    "angry":     {"angry": 0.8},
    "surprised": {"surprised": 1.0},
    "sleepy":    {"relaxed": 0.8},
}

# Daftar animasi VRMA: nama -> file dan kapan dipakai
# Format tag di LLM: [emosi|nama_animasi] atau [emosi]
ANIMATIONS = {
    "greetings":   {"file": "greetings.vrma",   "when": "saat menyapa di awal percakapan"},
    "goodbye":     {"file": "Goodbye.vrma",      "when": "saat mengucapkan selamat tinggal"},
    "clapping":    {"file": "Clapping.vrma",     "when": "saat memuji atau senang sekali"},
    "peace-sign":  {"file": "peace-sign.vrma",   "when": "saat pose lucu atau ceria"},
    "blush":       {"file": "Blush.vrma",        "when": "saat malu atau dipuji"},
    "thinking":    {"file": "Thinking.vrma",     "when": "saat berpikir atau ragu"},
    "surprised":   {"file": "Surprised.vrma",    "when": "saat terkejut"},
    "angry":       {"file": "Angry.vrma",        "when": "saat marah"},
    "sad":         {"file": "Sad.vrma",          "when": "saat sedih"},
    "sleepy":      {"file": "Sleepy.vrma",       "when": "saat mengantuk"},
    "lookaround":  {"file": "LookAround.vrma",   "when": "saat penasaran atau melihat sekeliling"},
}

# Persona file
PERSONA_PATH = BASE_DIR / "prompts" / "persona.txt"
