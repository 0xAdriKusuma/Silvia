from __future__ import annotations

import asyncio
import re
import urllib.parse
import urllib.request
import webbrowser
from typing import Optional

from agent.registry import tool

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _search_youtube_first_video(query: str) -> tuple[Optional[str], Optional[str]]:
    clean_query = query.strip()
    if not clean_query:
        return None, None

    search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(clean_query)}"
    req = urllib.request.Request(
        search_url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=6) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except Exception:
        return None, None

    vids = list(dict.fromkeys(re.findall(r'watch\?v=([a-zA-Z0-9_-]{11})', html)))
    if not vids:
        return None, None

    first_vid = vids[0]
    title = clean_query
    pattern = rf'videoId":"{re.escape(first_vid)}".*?"title":\{{.*?"text":"([^"]+)"'
    match = re.search(pattern, html)
    if match:
        extracted = match.group(1).encode("utf-8").decode("unicode_escape", errors="ignore")
        if extracted.strip():
            title = extracted.strip()

    return first_vid, title


def _sync_play_youtube(query: str, platform: str = "youtube") -> str:
    clean_query = query.strip()
    if not clean_query:
        home_url = "https://music.youtube.com" if platform == "music" else "https://www.youtube.com"
        webbrowser.open(home_url)
        return f"OK: Membuka {home_url} di browser."

    video_id, title = _search_youtube_first_video(clean_query)

    if video_id:
        if platform == "music":
            play_url = f"https://music.youtube.com/watch?v={video_id}"
            platform_name = "YouTube Music"
        else:
            play_url = f"https://www.youtube.com/watch?v={video_id}&autoplay=1"
            platform_name = "YouTube"

        try:
            webbrowser.open(play_url)
            return f"OK: Memutar '{title}' di {platform_name} (URL: {play_url})."
        except Exception as e:
            return f"ERROR: Gagal membuka browser untuk {play_url}: {e}"

    encoded = urllib.parse.quote(clean_query)
    if platform == "music":
        fallback_url = f"https://music.youtube.com/search?q={encoded}"
        platform_name = "YouTube Music"
    else:
        fallback_url = f"https://www.youtube.com/results?search_query={encoded}"
        platform_name = "YouTube"

    try:
        webbrowser.open(fallback_url)
        return f"OK: Membuka pencarian '{clean_query}' di {platform_name} (URL: {fallback_url})."
    except Exception as e:
        return f"ERROR: Gagal membuka browser: {e}"


@tool(
    name="play_youtube",
    description=(
        "Mencari dan memutar lagu, musik, atau video secara otomatis (autoplay) di YouTube. "
        "Gunakan alat ini jika pengguna meminta memutar lagu atau musik secara gratis tanpa login/akun "
        "(misal: 'putar lagu Hikaru Nara Goose House', 'putar musik lofi di youtube', 'setel lagu di youtube'). "
        "Lagu akan langsung berputar otomatis di browser."
    ),
    params={
        "properties": {
            "query": {
                "type": "string",
                "description": "Judul lagu, artis, atau kata kunci video yang ingin diputar (misal: 'Hikaru Nara Goose House').",
            },
            "platform": {
                "type": "string",
                "description": "Pilih 'youtube' (default, autoplay langsung) atau 'music' (YouTube Music web player).",
                "enum": ["youtube", "music"],
            },
        },
        "required": ["query"],
    },
    risk="low",
)
async def play_youtube(query: str, platform: str = "youtube") -> str:
    return await asyncio.to_thread(_sync_play_youtube, query, platform)
