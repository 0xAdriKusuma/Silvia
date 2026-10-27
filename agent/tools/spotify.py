from __future__ import annotations

import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv

from agent.registry import tool

load_dotenv()

_CACHE_PATH = Path(__file__).resolve().parent.parent / ".spotify_cache"
_SCOPES = "user-modify-playback-state user-read-playback-state user-read-currently-playing"


def _get_spotify_client():
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
    except ImportError:
        return None, "Pustaka 'spotipy' belum terpasang. Jalankan: pip install spotipy"

    raw_id = os.getenv("SPOTIPY_CLIENT_ID") or os.getenv("SPOTIFY_CLIENT_ID")
    raw_secret = os.getenv("SPOTIPY_CLIENT_SECRET") or os.getenv("SPOTIFY_CLIENT_SECRET")
    raw_uri = (
        os.getenv("SPOTIPY_REDIRECT_URI")
        or os.getenv("SPOTIFY_REDIRECT_URI")
        or "http://127.0.0.1:8888/callback"
    )

    client_id = raw_id.strip() if raw_id else None
    client_secret = raw_secret.strip() if raw_secret else None
    redirect_uri = raw_uri.strip() if raw_uri else "http://127.0.0.1:8888/callback"

    if not client_id or not client_secret:
        return None, (
            "Kredensial Spotify belum dikonfigurasi di file .env. "
            "Harap tambahkan:\n"
            "SPOTIPY_CLIENT_ID=...\n"
            "SPOTIPY_CLIENT_SECRET=...\n"
            "SPOTIPY_REDIRECT_URI=http://127.0.0.1:8888/callback"
        )

    try:
        auth_manager = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=_SCOPES,
            cache_path=str(_CACHE_PATH),
            open_browser=True,
        )
        sp = spotipy.Spotify(auth_manager=auth_manager)
        return sp, None
    except Exception as e:
        return None, f"Gagal menginisialisasi Spotify OAuth: {e}"


def _ensure_active_device(sp) -> tuple[str | None, str | None]:
    try:
        devices = sp.devices().get("devices", [])
    except Exception as e:
        return None, f"Gagal mengambil daftar perangkat Spotify: {e}"

    if not devices:
        try:
            from agent.tools.apps import _launch_app
            _launch_app("spotify")
        except Exception:
            pass
        return None, (
            "Tidak ada perangkat Spotify yang aktif atau terbuka. "
            "Silakan buka aplikasi Spotify atau Web Player (open.spotify.com) terlebih dahulu."
        )

    for d in devices:
        if d.get("is_active"):
            return d.get("id"), None

    dev_id = devices[0].get("id")
    try:
        sp.transfer_playback(device_id=dev_id, force_play=False)
    except Exception:
        pass
    return dev_id, None


def _sync_play_spotify(query: str) -> str:
    from spotipy.exceptions import SpotifyException

    sp, err = _get_spotify_client()
    if err:
        return f"ERROR: {err}"

    dev_id, dev_err = _ensure_active_device(sp)
    if dev_err:
        return f"ERROR: {dev_err}"

    try:
        clean_query = query.strip()
        if clean_query:
            results = sp.search(q=clean_query, type="track", limit=1)
            tracks = results.get("tracks", {}).get("items", [])
            if not tracks:
                return f"ERROR: Lagu dengan pencarian '{clean_query}' tidak ditemukan di Spotify."

            track = tracks[0]
            track_name = track.get("name", "Unknown")
            artists = ", ".join(a.get("name", "") for a in track.get("artists", []))
            track_uri = track.get("uri")

            sp.start_playback(device_id=dev_id, uris=[track_uri])
            return f"OK: Memutar '{track_name}' oleh {artists} di Spotify."
        else:
            sp.start_playback(device_id=dev_id)
            return "OK: Melanjutkan pemutaran musik di Spotify."

    except SpotifyException as se:
        if se.http_status == 403:
            return (
                "ERROR: Pembatasan API Spotify (403). "
                "Fitur kontrol pemutaran API membutuhkan akun Spotify Premium."
            )
        elif se.http_status == 404:
            return (
                "ERROR: Perangkat Spotify tidak ditemukan atau sedang offline. "
                "Pastikan Spotify sedang terbuka dan aktif."
            )
        return f"ERROR: Spotify error ({se.http_status}): {se.msg}"
    except Exception as e:
        return f"ERROR: Gagal memutar lagu di Spotify: {e}"


def _sync_pause_spotify() -> str:
    from spotipy.exceptions import SpotifyException

    sp, err = _get_spotify_client()
    if err:
        return f"ERROR: {err}"

    dev_id, dev_err = _ensure_active_device(sp)
    if dev_err:
        return f"ERROR: {dev_err}"

    try:
        sp.pause_playback(device_id=dev_id)
        return "OK: Pemutaran musik di Spotify telah dijeda."
    except SpotifyException as se:
        if se.http_status == 403:
            return "ERROR: Kontrol pemutaran Spotify membutuhkan akun Spotify Premium."
        return f"ERROR: Spotify error ({se.http_status}): {se.msg}"
    except Exception as e:
        return f"ERROR: Gagal menjeda Spotify: {e}"


def _sync_next_spotify() -> str:
    from spotipy.exceptions import SpotifyException

    sp, err = _get_spotify_client()
    if err:
        return f"ERROR: {err}"

    dev_id, dev_err = _ensure_active_device(sp)
    if dev_err:
        return f"ERROR: {dev_err}"

    try:
        sp.next_track(device_id=dev_id)
        return "OK: Berpindah ke lagu berikutnya di Spotify."
    except SpotifyException as se:
        return f"ERROR: Spotify error ({se.http_status}): {se.msg}"
    except Exception as e:
        return f"ERROR: Gagal berpindah lagu di Spotify: {e}"


@tool(
    name="play_spotify",
    description=(
        "Mencari dan memutar lagu, musik, atau artis langsung di Spotify. "
        "Gunakan alat ini jika pengguna meminta memutar lagu spesifik (misal 'putar Hikaru Nara Goose House') "
        "atau meminta memutar musik di Spotify. "
        "Jika query kosong, alat ini akan melanjutkan (resume) pemutaran yang dijeda."
    ),
    params={
        "properties": {
            "query": {
                "type": "string",
                "description": "Judul lagu, artis, atau kata kunci musik yang ingin diputar (misal: 'Hikaru Nara Goose House'). Biarkan string kosong jika ingin resume pemutaran.",
            },
        },
        "required": [],
    },
    risk="low",
)
async def play_spotify(query: str = "") -> str:
    return await asyncio.to_thread(_sync_play_spotify, query)


@tool(
    name="pause_spotify",
    description="Menjeda (pause) pemutaran musik yang sedang berputar di Spotify.",
    params={
        "properties": {},
        "required": [],
    },
    risk="low",
)
async def pause_spotify() -> str:
    return await asyncio.to_thread(_sync_pause_spotify)


@tool(
    name="next_spotify",
    description="Memutar lagu berikutnya (next track) di antrean Spotify.",
    params={
        "properties": {},
        "required": [],
    },
    risk="low",
)
async def next_spotify() -> str:
    return await asyncio.to_thread(_sync_next_spotify)
