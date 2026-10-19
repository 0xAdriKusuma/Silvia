"""
agent/pending.py - Manajemen aksi yang menunggu konfirmasi pengguna

Hanya boleh ada satu PendingAction aktif dalam satu waktu.
Semua operasi bersifat thread-safe (asyncio single-threaded).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from agent import config as cfg

# Konstanta kadaluarsa (dapat di-monkeypatch via agent.pending atau agent.config)
CONFIRM_EXPIRY_SECONDS: int = getattr(cfg, "CONFIRM_EXPIRY_SECONDS", 60)


def _get_expiry() -> int:
    """Ambil batas kadaluarsa, mendeteksi monkeypatch di pending atau config."""
    global CONFIRM_EXPIRY_SECONDS
    if CONFIRM_EXPIRY_SECONDS != 60:
        return CONFIRM_EXPIRY_SECONDS
    return getattr(cfg, "CONFIRM_EXPIRY_SECONDS", 60)


# ----------------------------- STRUKTUR DATA ------------------------------- #

@dataclass
class PendingAction:
    """Satu aksi yang sedang menunggu konfirmasi pengguna."""
    tool_name: str              # Nama alat yang akan dieksekusi
    args: dict                  # Argumen PERSIS yang akan dikirim (tidak diubah)
    human_description: str      # Kalimat konfirmasi untuk pengguna (bahasa Indonesia)
    created_at: float = field(default_factory=time.time)
    ambiguous_count: int = 0    # Berapa kali jawaban ambigu sudah diterima


# ----------------------------- STORE --------------------------------------- #

# Pending action aktif saat ini (None = tidak ada)
_current: PendingAction | None = None


def set_pending(action: PendingAction) -> None:
    """Simpan pending action baru. Akan menggantikan yang lama jika ada."""
    global _current
    _current = action


def get_pending() -> PendingAction | None:
    """Ambil pending action aktif. Kembalikan None jika tidak ada atau sudah kadaluarsa."""
    global _current
    if _current is None:
        return None

    # Cek kadaluarsa
    if time.time() - _current.created_at > _get_expiry():
        _current = None
        return None

    return _current


def pop_expired_pending() -> PendingAction | None:
    """
    Ambil dan bersihkan pending action jika sudah kadaluarsa.
    Kembalikan PendingAction jika kadaluarsa, atau None jika masih valid / tidak ada.
    """
    global _current
    if _current is None:
        return None

    if time.time() - _current.created_at > _get_expiry():
        expired = _current
        _current = None
        return expired

    return None


def clear_pending() -> None:
    """Hapus pending action (dibatalkan atau sudah dieksekusi)."""
    global _current
    _current = None


def is_expired(action: PendingAction) -> bool:
    """Cek apakah action sudah kadaluarsa."""
    return (time.time() - action.created_at) > _get_expiry()


