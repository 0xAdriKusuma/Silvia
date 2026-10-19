"""
agent/safety.py - Pengaman operasi file dan validasi

Fungsi utama:
- safe_path(): resolusi dan validasi path ke dalam workspace
- resolve_name(): pencocokan nama file untuk input suara/teks
- validate_url(): validasi URL sebelum dibuka
- is_trigger(): apakah teks pengguna memicu mode agent
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from agent.config import (
    WORKSPACE_DIR,
    ALLOWED_EXTENSIONS,
    WINDOWS_DEVICE_NAMES,
    FORBIDDEN_FILENAME_CHARS,
    TRIGGER_KEYWORDS,
    TRIGGER_MODE,
    MAX_URL_LENGTH,
)


# ----------------------------- SAFE PATH ----------------------------------- #

class SafePathError(ValueError):
    """Kesalahan keamanan path: selalu aman untuk ditampilkan ke pengguna."""
    pass


def safe_path(name: str) -> Path:
    """
    Resolusi dan validasi nama file ke dalam WORKSPACE_DIR.

    Menerima: nama file relatif sederhana (mis. "catatan.txt")
    Menolak: path absolut, drive letter, UNC, '..', nama kosong,
             workspace itu sendiri, nama perangkat Windows, karakter terlarang,
             ekstensi di luar allowlist.

    Kembalikan: Path absolut yang sudah tervalidasi di dalam workspace.
    Lempar: SafePathError jika tidak valid.
    """
    if not name or not name.strip():
        raise SafePathError("Nama file tidak boleh kosong.")

    name = name.strip()

    # Tolak path absolut Windows (drive letter)
    if len(name) >= 2 and name[1] == ":":
        raise SafePathError(f"Path absolut dengan drive letter tidak diizinkan: '{name}'")

    # Tolak UNC path (\\server\share)
    if name.startswith("\\\\") or name.startswith("//"):
        raise SafePathError(f"UNC path tidak diizinkan: '{name}'")

    # Tolak path absolut Unix-style
    if name.startswith("/"):
        raise SafePathError(f"Path absolut tidak diizinkan: '{name}'")

    # Tolak karakter terlarang
    for ch in FORBIDDEN_FILENAME_CHARS:
        if ch in name:
            raise SafePathError(f"Nama file mengandung karakter terlarang '{ch}': '{name}'")

    # Resolusi ke dalam workspace
    # Buat workspace jika belum ada
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    resolved = (WORKSPACE_DIR / name).resolve()

    # Cek apakah hasil resolusi benar-benar di dalam workspace
    try:
        resolved.relative_to(WORKSPACE_DIR.resolve())
    except ValueError:
        raise SafePathError(
            f"Path '{name}' keluar dari workspace setelah resolusi. "
            "Traversal direktori tidak diizinkan."
        )

    # Tolak workspace itu sendiri sebagai target
    if resolved == WORKSPACE_DIR.resolve():
        raise SafePathError("Tidak bisa menarget folder workspace itu sendiri.")

    # Tolak nama perangkat Windows (CON, NUL, dst.)
    # Cek setiap komponen path
    for part in resolved.parts:
        part_upper = part.upper().split(".")[0]  # hapus ekstensi jika ada
        if part_upper in WINDOWS_DEVICE_NAMES:
            raise SafePathError(f"Nama perangkat Windows tidak diizinkan: '{part}'")

    # Validasi ekstensi
    suffix = resolved.suffix.lower()
    if not suffix:
        raise SafePathError(
            f"File harus memiliki ekstensi. "
            f"Ekstensi yang diizinkan: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
    if suffix not in ALLOWED_EXTENSIONS:
        raise SafePathError(
            f"Ekstensi '{suffix}' tidak diizinkan. "
            f"Ekstensi yang diizinkan: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    return resolved


# ----------------------------- RESOLVE NAME -------------------------------- #

def resolve_name(name: str, workspace: Path | None = None) -> Path:
    """
    Resolusi nama file dari input suara/teks yang mungkin tidak lengkap.

    Strategi (berurutan):
    1. Cocok persis (case-sensitive) dengan nama lengkap
    2. Cocok unik tanpa memperhatikan huruf besar/kecil (case-insensitive) + ekstensi opsional
    3. Jika lebih dari satu kandidat atau tidak ditemukan -> SafePathError dengan daftar kandidat

    Kembalikan: Path absolut ke file yang ditemukan.
    Lempar: SafePathError jika ambigu atau tidak ditemukan.
    """
    ws = (workspace or WORKSPACE_DIR).resolve()
    ws.mkdir(parents=True, exist_ok=True)

    # Daftar semua file di workspace (non-rekursif)
    files = [f for f in ws.iterdir() if f.is_file()]

    if not files:
        raise SafePathError(f"Workspace kosong; tidak ada file bernama '{name}'.")

    name_stripped = name.strip()

    # 1. Cocok persis
    for f in files:
        if f.name == name_stripped:
            return f

    # 2. Cocok case-insensitive (dengan atau tanpa ekstensi)
    name_lower = name_stripped.lower()
    name_no_ext = Path(name_stripped).stem.lower()

    candidates = []
    for f in files:
        f_lower = f.name.lower()
        f_stem = f.stem.lower()
        if f_lower == name_lower or f_stem == name_no_ext:
            candidates.append(f)

    if len(candidates) == 1:
        return candidates[0]

    if len(candidates) > 1:
        names = ", ".join(f"'{f.name}'" for f in candidates)
        raise SafePathError(
            f"Nama '{name}' ambigu; ada beberapa kandidat: {names}. "
            "Sebutkan nama lengkap dengan ekstensi."
        )

    # Tidak ditemukan sama sekali
    all_names = ", ".join(f"'{f.name}'" for f in files)
    raise SafePathError(
        f"File '{name}' tidak ditemukan di workspace. "
        f"File yang ada: {all_names}"
    )


# ----------------------------- VALIDATE URL -------------------------------- #

def validate_url(url: str) -> str:
    """
    Validasi URL sebelum dibuka di browser.

    Aturan:
    - Hanya skema http:// atau https://
    - Tolak file:, javascript:, ftp:, dan skema lain
    - Tolak URL yang mengandung kredensial (@)
    - Tolak URL terlalu panjang (> MAX_URL_LENGTH)

    Kembalikan: url yang sudah divalidasi (stripped)
    Lempar: ValueError jika tidak valid
    """
    url = url.strip()

    if len(url) > MAX_URL_LENGTH:
        raise ValueError(
            f"URL terlalu panjang ({len(url)} karakter, maks {MAX_URL_LENGTH})."
        )

    url_lower = url.lower()

    # Cek skema yang diizinkan
    if not (url_lower.startswith("http://") or url_lower.startswith("https://")):
        # Deteksi skema berbahaya secara eksplisit untuk pesan error yang jelas
        for bad_scheme in ("file:", "javascript:", "ftp:", "data:", "vbscript:"):
            if url_lower.startswith(bad_scheme):
                raise ValueError(
                    f"Skema URL '{bad_scheme}' tidak diizinkan. "
                    "Hanya http:// dan https:// yang diperbolehkan."
                )
        raise ValueError(
            "URL harus dimulai dengan http:// atau https://."
        )

    # Tolak URL dengan kredensial (mis. http://user:pass@host)
    # Cek karakter @ setelah skema
    after_scheme = url[url.index("://") + 3:]
    host_part = after_scheme.split("/")[0]
    if "@" in host_part:
        raise ValueError(
            "URL dengan kredensial (user:password@host) tidak diizinkan."
        )

    return url


# ----------------------------- IS TRIGGER ---------------------------------- #

def is_trigger(text: str) -> bool:
    """
    Tentukan apakah teks pengguna harus memicu mode agent.

    Mode "always": selalu True.
    Mode "keyword": True jika mengandung kata kunci aksi.
    """
    if TRIGGER_MODE == "always":
        return True

    text_lower = text.lower()
    for kw in TRIGGER_KEYWORDS:
        # Cek kemunculan kata kunci sebagai kata utuh (basic)
        if kw in text_lower:
            return True
    return False
