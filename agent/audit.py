"""
agent/audit.py - Audit log JSON Lines untuk semua aksi agent

Format setiap entri: satu baris JSON dengan field:
  timestamp, tool, args_summary, risk, decision, result_or_error

Keputusan yang dicatat:
  executed   - alat dieksekusi langsung (risk=low)
  pending    - menunggu konfirmasi pengguna
  confirmed  - dikonfirmasi pengguna, lalu dieksekusi
  cancelled  - dibatalkan pengguna
  blocked    - ditolak karena keamanan
  expired    - kadaluarsa sebelum dikonfirmasi
  error      - terjadi exception saat eksekusi
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from agent.config import LOGS_DIR


# ----------------------------- SETUP LOG ----------------------------------- #

# Buat folder logs jika belum ada
LOGS_DIR.mkdir(parents=True, exist_ok=True)

AUDIT_LOG_PATH = LOGS_DIR / "audit.log"

# Gunakan logger Python standar agar mudah dialihkan, tapi tulis manual ke file
# agar bisa JSON Lines
_logger = logging.getLogger("agent.audit")


def _truncate(value: Any, max_len: int = 200) -> Any:
    """Potong string panjang agar tidak memenuhi log; tidak pernah menulis isi file."""
    if isinstance(value, str) and len(value) > max_len:
        return value[:max_len] + f"...[terpotong, {len(value)} karakter]"
    if isinstance(value, dict):
        return {k: _truncate(v, max_len) for k, v in value.items()}
    return value


def log_action(
    tool: str,
    args: dict,
    risk: str,
    decision: str,
    result: str | None = None,
    error: str | None = None,
) -> None:
    """
    Tulis satu entri ke audit.log dalam format JSON Lines.

    Args:
        tool     : nama alat (mis. "delete_file")
        args     : argumen alat (akan diringkas agar tidak bocor isi file)
        risk     : "low" atau "confirm"
        decision : "executed" | "pending" | "confirmed" | "cancelled" |
                   "blocked" | "expired" | "error"
        result   : ringkasan hasil sukses (opsional)
        error    : pesan error (opsional)
    """
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "tool": tool,
        "args_summary": _truncate(args, 200),
        "risk": risk,
        "decision": decision,
    }
    if result is not None:
        entry["result"] = _truncate(result, 300)
    if error is not None:
        entry["error"] = _truncate(error, 300)

    try:
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        # Jangan biarkan kegagalan log menghentikan alur utama
        _logger.warning("Gagal menulis audit log: %s", exc)
