"""
agent/config.py - Konfigurasi modul agent Silvia

Berisi allowlist aplikasi, pengaturan keamanan, batas-batas,
dan mode trigger yang mudah diedit.
Tidak boleh mengimpor dari app/.
"""
import os
from pathlib import Path

# ----------------------------- DIREKTORI AGENT ----------------------------- #
AGENT_DIR = Path(__file__).resolve().parent

# Satu-satunya folder yang boleh disentuh alat file
WORKSPACE_DIR = AGENT_DIR / "workspace"

# Folder log audit
LOGS_DIR = AGENT_DIR / "logs"

# File prompt aturan agent
AGENT_RULES_PATH = AGENT_DIR / "prompts" / "agent_rules.txt"

# ----------------------------- TOGGLE UTAMA -------------------------------- #
# Baca dari .env: AGENT_ENABLED=1 untuk aktif, 0 untuk nonaktif
AGENT_ENABLED: bool = os.getenv("AGENT_ENABLED", "1") == "1"

# ----------------------------- MODE TRIGGER -------------------------------- #
# "keyword" = agent hanya dipanggil jika ucapan mengandung kata kunci aksi
# "always"  = agent selalu dipanggil (lebih lambat)
TRIGGER_MODE: str = os.getenv("AGENT_TRIGGER_MODE", "keyword")

# Daftar kata kunci yang memicu agent (mode "keyword")
# Mudah diedit; cocokkan dengan bahasa Indonesia kasual
TRIGGER_KEYWORDS: list[str] = [
    # Membuka aplikasi/URL
    "buka", "jalankan", "putar", "launch", "start", "open",
    # Musik & Media (YouTube / Spotify)
    "play", "lagu", "musik", "spotify", "youtube", "yt", "pause", "jeda", "lanjutkan", "stop", "next",
    # Operasi file
    "buat", "tulis", "simpan", "create", "write", "save",
    "hapus", "delete", "remove",
    "baca", "read", "tampilkan",
    "daftar", "list", "lihat file",
    # Website
    "website", "url", "http", "https",
]

# ----------------------------- LOOP AGENT ---------------------------------- #
# Maksimum langkah tool-calling dalam satu giliran
MAX_STEPS: int = 4

# Suhu LLM untuk mode agent (rendah = lebih deterministik)
AGENT_TEMPERATURE: float = 0.1

# Panjang maksimum hasil alat yang dikirim balik ke LLM (karakter)
TOOL_RESULT_MAX_CHARS: int = 2000

# Jumlah riwayat percakapan yang disertakan ke konteks agent (pesan)
AGENT_HISTORY_WINDOW: int = 6

# ----------------------------- KONFIRMASI ---------------------------------- #
# Waktu kadaluarsa pending action (detik)
CONFIRM_EXPIRY_SECONDS: int = 60

# Maksimum tanya ulang saat jawaban ambigu sebelum batalkan
MAX_AMBIGUOUS_RETRIES: int = 2

# Kata-kata afirmatif (normalisasi: huruf kecil, tanpa tanda baca)
AFFIRMATIVE_WORDS: set[str] = {
    "ya", "iya", "yes", "oke", "ok", "lanjut", "boleh", "silakan",
}

# Kata-kata negatif
NEGATIVE_WORDS: set[str] = {
    "tidak", "nggak", "gak", "enggak", "jangan", "batal",
    "cancel", "no", "stop", "batalkan",
}

# ----------------------------- KEAMANAN FILE ------------------------------- #
# Ekstensi file yang diizinkan dibuat/dibaca
ALLOWED_EXTENSIONS: set[str] = {
    ".txt", ".md", ".json", ".csv", ".log", ".py", ".html", ".css", ".js",
}

# Ukuran maksimum file yang dibuat (bytes) = 100 KB
MAX_CREATE_SIZE_BYTES: int = 100 * 1024

# Ukuran maksimum yang dibaca kembali ke LLM (bytes) = 20 KB
MAX_READ_SIZE_BYTES: int = 20 * 1024

# Nama perangkat Windows yang dilarang sebagai nama file
WINDOWS_DEVICE_NAMES: set[str] = {
    "CON", "PRN", "AUX", "NUL",
    "COM0", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT0", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}

# Karakter yang dilarang dalam nama file (selain yang sudah ditolak pathlib)
FORBIDDEN_FILENAME_CHARS: set[str] = set('<>:"|?*\x00')

# ----------------------------- ALLOWLIST APLIKASI -------------------------- #
# Format tiap entri:
#   "nama_kanonik": {
#       "launch": ("uri"|"exe"|"start", "<nilai tetap>"),
#       "aliases": [...]   <- alias yang dikenali LLM
#   }
# TIDAK BOLEH menerima nilai dinamis dari LLM; nilai "launch" hardcoded di sini.
APP_ALLOWLIST: dict[str, dict] = {
    "spotify": {
        "launch": ("uri", "spotify:"),
        "aliases": ["spotify", "musik spotify", "putar spotify"],
    },
    "chrome": {
        "launch": ("exe", "chrome.exe"),
        "aliases": ["chrome", "google chrome", "browser", "google"],
    },
    "notepad": {
        "launch": ("exe", "notepad.exe"),
        "aliases": ["notepad", "catatan", "text editor", "editor teks"],
    },
    "calculator": {
        "launch": ("exe", "calc.exe"),
        "aliases": ["calculator", "kalkulator", "calc", "hitung"],
    },
    "explorer": {
        "launch": ("exe", "explorer.exe"),
        "aliases": ["explorer", "file explorer", "windows explorer", "penjelajah file"],
    },
    "discord": {
        "launch": ("uri", "discord:"),
        "aliases": ["discord", "discord app"],
    },
    "word": {
        "launch": ("start", "winword.exe"),
        "aliases": ["word", "microsoft word", "ms word", "dokumen word"],
    },
    "excel": {
        "launch": ("start", "excel.exe"),
        "aliases": ["excel", "microsoft excel", "ms excel", "spreadsheet"],
    },
    "taskmgr": {
        "launch": ("exe", "taskmgr.exe"),
        "aliases": ["task manager", "taskmanager", "taskmgr", "task", "pengelola tugas"],
    },
}

# Batas panjang URL yang diizinkan
MAX_URL_LENGTH: int = 2000
