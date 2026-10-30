import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# ----------------------------- KONFIGURASI -----------------------------
CHARACTER_NAME = "Silvia"  # Ganti sesuai nama karakter Anda

# Direktori aset VRM/VRMA milik pengguna (cari rekursif)
ASSETS_DIR = BASE_DIR / "assets"

# File animasi idle – diputar terus-menerus sebagai lapisan dasar (bukan pilihan LLM)
IDLE_FILE = "Idle.vrma"

# Nama file VRM spesifik (kosongkan = ambil .vrm pertama yang ditemukan di ASSETS_DIR)
VRM_FILE = "assets/silvia.vrm"

# Audio / VAD
SAMPLE_RATE = 16000
CHUNK = 512                             # Silero VAD wajib 512 sampel pada 16 kHz
CHUNK_MS = CHUNK * 1000 // SAMPLE_RATE  # 32 ms
VAD_THRESHOLD = 0.5
END_SILENCE_MS = 300                    # Diam selama ini = ucapan selesai
MIN_SPEECH_MS = 400                     # Ucapan lebih pendek diabaikan (noise)
MAX_SPEECH_S = 30
PREROLL_CHUNKS = 10                     # Simpan ~320 ms sebelum bicara terdeteksi

# Push-to-Talk / Listen Mode
# LISTEN_MODE: 'toggle' (default) = satu klik satu ucapan + VAD end
#              'hold'             = dengarkan selama tombol ditahan
#              'always'           = perilaku lama (mic selalu terbuka)
LISTEN_MODE = os.getenv("LISTEN_MODE", "toggle").lower()

# LISTEN_TIMEOUT_S: waktu (dtk) menunggu awal ucapan di mode toggle sebelum berhenti sendiri
LISTEN_TIMEOUT_S = float(os.getenv("LISTEN_TIMEOUT_S", "8"))

# LISTEN_HOTKEY: hotkey keyboard untuk mulai/berhenti mendengarkan (default: Space)
LISTEN_HOTKEY = os.getenv("LISTEN_HOTKEY", "Space")

# MIC_KEEP_OPEN: 0 = tutup stream saat idle (indikator OS mati, lebih privat, default)
#               1 = stream tetap terbuka tapi frame dibuang (kurangi latensi buka stream)
MIC_KEEP_OPEN = int(os.getenv("MIC_KEEP_OPEN", "0"))

# LISTEN_AUTO_ARM_ON_CONFIRM: 1 = setelah agent menghasilkan needs_confirmation,
#   otomatis mulai mendengarkan satu ucapan (jawaban ya/tidak) tanpa tekan tombol
#   0 = selalu perlu tombol
LISTEN_AUTO_ARM_ON_CONFIRM = int(os.getenv("LISTEN_AUTO_ARM_ON_CONFIRM", "1"))

# STT
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "turbo")       # Alternatif: large-v3, medium, small
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8_float16")  # Gunakan float16 jika VRAM longgar
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

# Konfigurasi backend TTS: "edge", "sbv2", atau "auto" (default "sbv2")
# Mode "sbv2"  = SBV2 selalu dipakai, tidak ada fallback ke Edge
# Mode "auto"  = SBV2 utama, fallback ke Edge hanya untuk kegagalan nyata (exception/OOM)
# Mode "edge"  = Edge-TTS saja (seperti semula)
TTS_BACKEND = os.getenv("TTS_BACKEND", "sbv2").lower()

# Izinkan fallback ke Edge-TTS saat SBV2 gagal nyata (exception/OOM)
# "1" = boleh fallback (default), "0" = tidak pernah fallback (tampilkan error jelas)
SBV2_ALLOW_FALLBACK = os.getenv("SBV2_ALLOW_FALLBACK", "1").strip() == "1"

SBV2_DEVICE = os.getenv("SBV2_DEVICE", "auto").lower()

# Batas waktu sintesis pengaman macet total: max(SBV2_TIMEOUT_S, len_chars * 0.5) detik
# Bukan alasan jatuh ke Edge secara diam-diam; hanya trigger error/peringatan
SBV2_TIMEOUT_S = float(os.getenv("SBV2_TIMEOUT_S", "30.0"))

# Panjang maksimum potongan teks per sintesis (karakter Jepang)
# Baris LLM dipecah di 。！？… (lalu 、 jika masih panjang) sebelum disintesis
SBV2_MAX_CHARS = int(os.getenv("SBV2_MAX_CHARS", "40"))
SBV2_MODEL_DIR = BASE_DIR / "models" / "sbv2"
SBV2_REPO = os.getenv("SBV2_REPO", "litagin/style_bert_vits2_jvnv")
SBV2_MODEL_NAME = os.getenv("SBV2_MODEL_NAME", "jvnv-F2-jp")
SBV2_FILES = (
    f"{SBV2_MODEL_NAME}/config.json",
    f"{SBV2_MODEL_NAME}/jvnv-F2_e166_s20000.safetensors",
    f"{SBV2_MODEL_NAME}/style_vectors.npy",
)
SBV2_BERT = os.getenv("SBV2_BERT", "ku-nlp/deberta-v2-large-japanese-char-wwm")

# Pemetaan emosi ke parameter gaya SBV2
EMOTION_STYLE = {   # nilai awal; pengguna akan menalanya dengan telinga
    "happy": {"style": "Happy", "style_weight": 2.0, "length": 0.95},
    "neutral": {"style": "Neutral", "style_weight": 1.0, "length": 1.0},
    "shy": {"style": "Neutral", "style_weight": 1.0, "length": 1.10},
    "sad": {"style": "Sad", "style_weight": 2.0, "length": 1.10},
    "angry": {"style": "Angry", "style_weight": 2.0, "length": 0.95},
    "surprised": {"style": "Surprise", "style_weight": 2.0, "length": 0.90},
    "sleepy": {"style": "Sad", "style_weight": 0.7, "length": 1.25},
}

# Validasi saat start: kunci EMOTION_STYLE harus persis sama dengan EMOTIONS
if set(EMOTION_STYLE.keys()) != set(EMOTIONS):
    raise ValueError(f"EMOTION_STYLE keys do not match EMOTIONS: {set(EMOTION_STYLE.keys())} != {set(EMOTIONS)}")


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
# CATATAN: idle TIDAK dimasukkan di sini – dikelola terpisah via IDLE_FILE.
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
