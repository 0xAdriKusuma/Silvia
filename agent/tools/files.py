"""
agent/tools/files.py - Alat operasi file di workspace

Semua operasi dikunci ke agent/workspace/ lewat safe_path().
Setiap alat didaftarkan dengan @tool dari registry.
"""
from __future__ import annotations

from pathlib import Path
from agent import config as cfg
from agent.config import (
    WORKSPACE_DIR,
    MAX_CREATE_SIZE_BYTES,
    MAX_READ_SIZE_BYTES,
    ALLOWED_EXTENSIONS,
)
from agent.registry import tool
from agent.safety import safe_path, SafePathError, resolve_name


def _get_workspace_dir() -> Path:
    """Ambil WORKSPACE_DIR dengan mendeteksi monkeypatch di modul ini atau agent.config."""
    global WORKSPACE_DIR
    cfg_dir = getattr(cfg, "WORKSPACE_DIR", None)
    if cfg_dir and cfg_dir != Path(__file__).resolve().parent.parent / "workspace":
        return cfg_dir
    return WORKSPACE_DIR



# ----------------------------- CREATE FILE --------------------------------- #

@tool(
    name="create_file",
    description=(
        "Membuat file baru di workspace Silvia. "
        "Gagal jika file sudah ada (tidak menimpa). "
        "Ekstensi yang diizinkan: .txt .md .json .csv .log .py .html .css .js. "
        "Batas ukuran 100 KB."
    ),
    params={
        "properties": {
            "path": {
                "type": "string",
                "description": "Nama file relatif (mis. 'catatan.txt' atau 'subfolder/data.json')",
            },
            "content": {
                "type": "string",
                "description": "Isi file (opsional, default kosong)",
                "maxLength": 102400,  # 100 KB
            },
        },
        "required": ["path"],
    },
    risk="low",
)
async def create_file(path: str, content: str = "") -> str:
    """Buat file baru di workspace; gagal jika sudah ada."""
    try:
        resolved = safe_path(path)
    except SafePathError as e:
        return f"ERROR: {e}"

    # Cek ukuran konten
    content_bytes = content.encode("utf-8")
    if len(content_bytes) > MAX_CREATE_SIZE_BYTES:
        return (
            f"ERROR: Konten terlalu besar "
            f"({len(content_bytes)} bytes, maks {MAX_CREATE_SIZE_BYTES} bytes / 100 KB)."
        )

    # Gagal jika file sudah ada (tidak menimpa)
    if resolved.exists():
        return f"ERROR: File '{resolved.name}' sudah ada. Tidak menimpa file yang ada."

    # Buat subfolder jika perlu (tetap di dalam workspace)
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
    except OSError as e:
        return f"ERROR: Gagal membuat file: {e}"

    return f"OK: File '{resolved.name}' berhasil dibuat ({len(content_bytes)} bytes)."


# ----------------------------- READ FILE ----------------------------------- #

@tool(
    name="read_file",
    description=(
        "Membaca isi file teks dari workspace Silvia. "
        "Hanya bisa membaca file teks; dipotong maksimal ~20 KB. "
        "Nama file bisa tanpa ekstensi (akan dicari otomatis jika unik)."
    ),
    params={
        "properties": {
            "path": {
                "type": "string",
                "description": "Nama file (mis. 'catatan.txt' atau 'catatan')",
            },
        },
        "required": ["path"],
    },
    risk="low",
)
async def read_file(path: str) -> str:
    """Baca isi file dari workspace; nama bisa tanpa ekstensi jika unik."""
    # Coba resolve_name terlebih dahulu (untuk input suara/teks yang tidak lengkap)
    try:
        resolved = resolve_name(path)
    except SafePathError:
        # Jika resolve_name gagal, coba safe_path langsung (nama mungkin sudah lengkap)
        try:
            resolved = safe_path(path)
        except SafePathError as e:
            return f"ERROR: {e}"

    if not resolved.exists():
        return f"ERROR: File '{path}' tidak ditemukan di workspace."

    if not resolved.is_file():
        return f"ERROR: '{path}' bukan file."

    try:
        raw = resolved.read_bytes()
    except OSError as e:
        return f"ERROR: Gagal membaca file: {e}"

    # Potong jika terlalu besar
    truncated = False
    if len(raw) > MAX_READ_SIZE_BYTES:
        raw = raw[:MAX_READ_SIZE_BYTES]
        truncated = True

    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception as e:
        return f"ERROR: Gagal mendekode file sebagai teks UTF-8: {e}"

    size_info = f"{resolved.stat().st_size} bytes"
    trunc_note = f"\n[TERPOTONG: hanya {MAX_READ_SIZE_BYTES} bytes pertama ditampilkan]" if truncated else ""

    # Bungkus dengan pembatas agar diperlakukan sebagai DATA, bukan perintah
    return (
        f"Isi file '{resolved.name}' ({size_info}):\n"
        f"<isi_file>\n{text}\n</isi_file>"
        f"{trunc_note}"
    )


# ----------------------------- LIST FILES ---------------------------------- #

@tool(
    name="list_files",
    description=(
        "Menampilkan daftar file di workspace Silvia (non-rekursif). "
        "Bisa diberi subdirektori opsional."
    ),
    params={
        "properties": {
            "subdir": {
                "type": "string",
                "description": "Subdirektori opsional di dalam workspace (default: root workspace)",
            },
        },
        "required": [],
    },
    risk="low",
)
async def list_files(subdir: str = "") -> str:
    """Daftar isi workspace (non-rekursif), dengan ukuran tiap file."""
    base_ws = _get_workspace_dir()
    # Pastikan workspace ada
    base_ws.mkdir(parents=True, exist_ok=True)

    if subdir:
        # Validasi subdir tetap di dalam workspace
        try:
            target_dir = safe_path(subdir + "/.placeholder")
            target_dir = target_dir.parent
        except SafePathError as e:
            return f"ERROR: {e}"
    else:
        target_dir = base_ws.resolve()

    if not target_dir.exists():
        return f"ERROR: Subdirektori '{subdir}' tidak ditemukan di workspace."

    if not target_dir.is_dir():
        return f"ERROR: '{subdir}' bukan direktori."

    try:
        # Saring file tersembunyi / metadata sistem (seperti .gitkeep)
        entries = sorted(
            [p for p in target_dir.iterdir() if not p.name.startswith(".")],
            key=lambda p: (p.is_file(), p.name)
        )
    except OSError as e:
        return f"ERROR: Gagal membaca direktori: {e}"

    if not entries:
        loc = f"workspace/{subdir}" if subdir else "workspace"
        return f"Workspace kosong ({loc} tidak berisi file)."

    lines = []
    for entry in entries:
        if entry.is_dir():
            lines.append(f"  [dir]  {entry.name}/")
        elif entry.is_file():
            size = entry.stat().st_size
            lines.append(f"  [file] {entry.name}  ({size} bytes)")

    loc = f"workspace/{subdir}" if subdir else "workspace"
    header = f"Daftar file di {loc} ({len([e for e in entries if e.is_file()])} file):"
    return header + "\n" + "\n".join(lines)


# ----------------------------- DELETE FILE --------------------------------- #

@tool(
    name="delete_file",
    description=(
        "Menghapus file dari workspace Silvia ke Recycle Bin (aman, bisa di-restore). "
        "HANYA file, bukan folder. Memerlukan konfirmasi pengguna sebelum dihapus. "
        "Nama file bisa tanpa ekstensi jika unik."
    ),
    params={
        "properties": {
            "path": {
                "type": "string",
                "description": "Nama file yang akan dihapus (mis. 'catatan.txt' atau 'catatan')",
            },
        },
        "required": ["path"],
    },
    risk="confirm",  # WAJIB konfirmasi sebelum dieksekusi
)
async def delete_file(path: str) -> str:
    """Hapus file ke Recycle Bin; memerlukan konfirmasi (ditangani di core.py)."""
    # Coba resolve_name terlebih dahulu (untuk nama tanpa ekstensi)
    try:
        resolved = resolve_name(path)
    except SafePathError:
        try:
            resolved = safe_path(path)
        except SafePathError as e:
            return f"ERROR: {e}"

    if not resolved.exists():
        return f"ERROR: File '{path}' tidak ditemukan di workspace."

    if not resolved.is_file():
        return f"ERROR: '{path}' bukan file. Hanya file yang bisa dihapus, bukan folder."

    try:
        import send2trash
        send2trash.send2trash(str(resolved))
    except ImportError:
        return "ERROR: Modul send2trash tidak tersedia. Tidak bisa menghapus ke Recycle Bin."
    except Exception as e:
        # JANGAN fallback ke penghapusan permanen
        return f"ERROR: Gagal memindahkan '{resolved.name}' ke Recycle Bin: {e}"

    return f"OK: File '{resolved.name}' berhasil dipindahkan ke Recycle Bin."
