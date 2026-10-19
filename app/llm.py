from openai import AsyncOpenAI
from app.config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    CHARACTER_NAME,
    PERSONA_PATH,
)


import datetime
import json
import time
import urllib.request
from typing import Optional

# Cache lokasi agar tidak membebani API publik dan respon instan
_location_cache: Optional[str] = None
_last_location_fetch: float = 0


def get_current_location() -> str:
    """Mengambil perkiraan lokasi kota/negara pengguna via IP Geolocation publik (cache 1 jam)."""
    global _location_cache, _last_location_fetch
    now = time.time()
    if _location_cache and (now - _last_location_fetch < 3600):
        return _location_cache

    try:
        req = urllib.request.Request(
            "http://ip-api.com/json/?fields=status,country,regionName,city,timezone",
            headers={"User-Agent": "SilviaAssistant/1.0"},
        )
        with urllib.request.urlopen(req, timeout=1.5) as r:
            data = json.loads(r.read().decode("utf-8"))
            if data.get("status") == "success":
                city = data.get("city", "")
                region = data.get("regionName", "")
                country = data.get("country", "")
                tz = data.get("timezone", "")
                loc_str = f"{city}, {region}, {country} (Zona: {tz})"
                _location_cache = loc_str
                _last_location_fetch = now
                return loc_str
    except Exception:
        pass

    if _location_cache:
        return _location_cache
    return "Indonesia (Lokasi default)"


def load_system_prompt() -> str:
    """Muat persona karakter dari file prompts/persona.txt lengkap dengan konteks waktu & lokasi aktual."""
    # Data waktu laptop/PC saat ini
    now = datetime.datetime.now().astimezone()
    # Format hari dan tanggal yang mudah dipahami LLM
    time_str = now.strftime("%A, %d %B %Y - Pukul %H:%M:%S (%Z, UTC%z)")
    loc_str = get_current_location()

    context_info = (
        f"\n[Konteks Sistem Pengguna Saat Ini]\n"
        f"- Waktu Lokal Laptop: {time_str}\n"
        f"- Perkiraan Lokasi: {loc_str}\n"
        f"- Peranmu: AI Personal Assistant pribadi untuk pengguna\n"
    )

    if PERSONA_PATH.exists():
        text = PERSONA_PATH.read_text(encoding="utf-8")
        base_prompt = text.format(CHARACTER_NAME=CHARACTER_NAME)
        return base_prompt + "\n" + context_info
    
    # Fallback default prompt
    return (
        f"Kamu adalah {CHARACTER_NAME}, AI Personal Assistant perempuan anime yang ceria, manja, dan agak posesif terhadap pengguna.\n"
        "Pengguna berbicara bahasa Indonesia, tetapi kamu SELALU membalas dalam bahasa Jepang lisan yang santai.\n"
        "Format tiap baris: [emosi] kalimat Jepang|||terjemahan Indonesia\n"
        "Emosi yang boleh dipakai: happy, neutral, sad, angry, shy\n"
        + context_info
    )


def get_llm_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
