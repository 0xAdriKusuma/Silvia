"""
agent/tools/apps.py - Alat untuk membuka aplikasi dan URL

Keamanan:
- open_app: hanya membuka aplikasi dari allowlist hardcoded; tidak menerima path bebas
- open_url: hanya skema http/https; validasi ketat via safety.validate_url()
- Tidak pernah shell=True atau os.system()
"""
from __future__ import annotations

import sys
import webbrowser

from agent.config import APP_ALLOWLIST
from agent.registry import tool
from agent.safety import validate_url


# ----------------------------- HELPER LAUNCH ------------------------------- #

def _build_app_enum() -> list[str]:
    """Buat daftar nama kanonik untuk enum skema alat."""
    return list(APP_ALLOWLIST.keys())


def _build_app_description() -> str:
    """Buat deskripsi alat yang menyebut semua alias agar LLM bisa memetakan."""
    lines = [
        "Membuka aplikasi dari daftar yang diizinkan. "
        "Gunakan nama kanonik berikut untuk parameter 'name':"
    ]
    for canonical, info in APP_ALLOWLIST.items():
        aliases = ", ".join(f"'{a}'" for a in info["aliases"])
        lines.append(f"  - '{canonical}': alias yang dipetakan = {aliases}")
    return "\n".join(lines)


def _launch_app(canonical_name: str) -> str:
    """
    Luncurkan aplikasi dari allowlist menggunakan metode yang aman.

    - "uri"   -> os.startfile(uri)  [Windows]
    - "exe"   -> subprocess.Popen([exe_name], tanpa shell=True)
    - "start" -> subprocess.Popen(["cmd", "/c", "start", ...], untuk kasus khusus)

    Di OS non-Windows, kembalikan error tanpa crash.
    """
    if sys.platform != "win32":
        return f"ERROR: Peluncuran aplikasi hanya didukung di Windows."

    info = APP_ALLOWLIST.get(canonical_name)
    if info is None:
        return f"ERROR: Aplikasi '{canonical_name}' tidak ada di allowlist."

    launch_type, launch_value = info["launch"]

    try:
        if launch_type == "uri":
            # Buka URI (mis. spotify:) via os.startfile
            import os
            os.startfile(launch_value)  # type: ignore[attr-defined]

        elif launch_type == "exe":
            # Jalankan executable langsung tanpa shell
            import subprocess
            subprocess.Popen(
                [launch_value],
                shell=False,              # TIDAK BOLEH shell=True
                creationflags=0x00000008, # DETACHED_PROCESS
            )

        elif launch_type == "start":
            # Kasus khusus: pakai cmd /c start (untuk URI yang tidak didukung startfile)
            import subprocess
            subprocess.Popen(
                ["cmd", "/c", "start", "", launch_value],
                shell=False,
            )

        else:
            return f"ERROR: Tipe launch '{launch_type}' tidak dikenal (bug konfigurasi)."

    except FileNotFoundError:
        return (
            f"ERROR: Aplikasi '{canonical_name}' ({launch_value}) tidak ditemukan. "
            "Pastikan aplikasi terinstal."
        )
    except OSError as e:
        return f"ERROR: Gagal membuka '{canonical_name}': {e}"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"

    return f"OK: Aplikasi '{canonical_name}' berhasil dibuka."


# ----------------------------- DAFTARKAN ALAT ------------------------------ #

@tool(
    name="open_app",
    description=_build_app_description(),
    params={
        "properties": {
            "name": {
                "type": "string",
                "description": "Nama kanonik aplikasi yang akan dibuka",
                "enum": _build_app_enum(),
            },
        },
        "required": ["name"],
    },
    risk="low",
)
async def open_app(name: str) -> str:
    """Buka aplikasi dari allowlist; tolak nama di luar allowlist."""
    # Validasi enum: nama harus persis salah satu kunci allowlist
    if name not in APP_ALLOWLIST:
        allowed = ", ".join(f"'{k}'" for k in APP_ALLOWLIST.keys())
        return (
            f"ERROR: Aplikasi '{name}' tidak ada dalam allowlist. "
            f"Aplikasi yang diizinkan: {allowed}"
        )

    return _launch_app(name)


@tool(
    name="open_url",
    description=(
        "Membuka URL di browser default pengguna. "
        "Hanya skema http:// dan https:// yang diizinkan. "
        "Tolak file:, javascript:, URL dengan kredensial, atau URL terlalu panjang."
    ),
    params={
        "properties": {
            "url": {
                "type": "string",
                "description": "URL yang akan dibuka (harus dimulai dengan http:// atau https://)",
                "maxLength": 2000,
            },
        },
        "required": ["url"],
    },
    risk="low",
)
async def open_url(url: str) -> str:
    """Buka URL di browser default setelah validasi ketat."""
    try:
        safe_url = validate_url(url)
    except ValueError as e:
        return f"ERROR: {e}"

    try:
        webbrowser.open(safe_url)
    except Exception as e:
        return f"ERROR: Gagal membuka URL: {e}"

    return f"OK: URL '{safe_url}' dibuka di browser default."
