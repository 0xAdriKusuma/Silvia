"""
agent/registry.py - Dekorator @tool dan registry skema JSON

Setiap alat didaftarkan dengan @tool(...) yang menyimpan metadata
dan menghasilkan skema tool-calling format OpenAI.
"""
from __future__ import annotations

import functools
from dataclasses import dataclass, field
from typing import Any, Callable

# ----------------------------- STRUKTUR DATA ------------------------------- #

@dataclass
class ToolMeta:
    """Metadata satu alat yang terdaftar."""
    name: str
    description: str
    params: dict          # JSON Schema "properties" + "required"
    risk: str             # "low" atau "confirm"
    fn: Callable


# Registry global: nama_alat -> ToolMeta
_REGISTRY: dict[str, ToolMeta] = {}


# ----------------------------- DEKORATOR ----------------------------------- #

def tool(name: str, description: str, params: dict, risk: str = "low"):
    """
    Dekorator pendaftaran alat.

    Contoh pemakaian:
        @tool(
            name="create_file",
            description="Membuat file baru di workspace.",
            params={
                "properties": {
                    "path": {"type": "string", "description": "Nama file"},
                    "content": {"type": "string", "description": "Isi file"},
                },
                "required": ["path"],
            },
            risk="low",
        )
        async def create_file(path: str, content: str = "") -> str:
            ...
    """
    if risk not in ("low", "confirm"):
        raise ValueError(f"risk harus 'low' atau 'confirm', bukan '{risk}'")

    def decorator(fn: Callable) -> Callable:
        meta = ToolMeta(name=name, description=description, params=params, risk=risk, fn=fn)
        _REGISTRY[name] = meta

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            return await fn(*args, **kwargs)

        # Lampirkan metadata ke fungsi agar bisa dibaca langsung
        wrapper._tool_meta = meta  # type: ignore[attr-defined]
        return wrapper

    return decorator


# ----------------------------- AKSES REGISTRY ------------------------------ #

def get_tool(name: str) -> ToolMeta | None:
    """Kembalikan metadata alat berdasarkan nama, atau None jika tidak ditemukan."""
    return _REGISTRY.get(name)


def all_tools() -> list[ToolMeta]:
    """Kembalikan semua alat yang terdaftar."""
    return list(_REGISTRY.values())


def schemas() -> list[dict]:
    """
    Hasilkan daftar skema tool-calling format OpenAI untuk semua alat terdaftar.
    Siap dikirim sebagai parameter `tools=` ke chat.completions.create().
    """
    result = []
    for meta in _REGISTRY.values():
        schema = {
            "type": "function",
            "function": {
                "name": meta.name,
                "description": meta.description,
                "parameters": {
                    "type": "object",
                    "properties": meta.params.get("properties", {}),
                    "required": meta.params.get("required", []),
                },
            },
        }
        result.append(schema)
    return result


def validate_args(name: str, args: dict) -> tuple[bool, str]:
    """
    Validasi argumen terhadap skema alat.

    Mengembalikan (True, "") jika valid,
    atau (False, pesan_error) jika tidak valid.
    """
    meta = get_tool(name)
    if meta is None:
        return False, f"Alat '{name}' tidak dikenal."

    props = meta.params.get("properties", {})
    required = meta.params.get("required", [])

    # Cek field wajib
    for req_field in required:
        if req_field not in args:
            return False, f"Field wajib '{req_field}' tidak ada."

    # Cek tipe dan enum untuk field yang ada
    for key, val in args.items():
        if key not in props:
            # Field tidak dikenal — tolak untuk keamanan ketat
            return False, f"Field '{key}' tidak dikenal dalam skema alat '{name}'."

        prop_schema = props[key]
        expected_type = prop_schema.get("type")

        # Validasi tipe dasar
        type_map = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
        }
        if expected_type in type_map:
            expected_py_type = type_map[expected_type]
            if not isinstance(val, expected_py_type):
                return False, f"Field '{key}' harus bertipe {expected_type}, bukan {type(val).__name__}."

        # Validasi enum
        if "enum" in prop_schema and val not in prop_schema["enum"]:
            allowed = ", ".join(repr(e) for e in prop_schema["enum"])
            return False, f"Field '{key}' harus salah satu dari: {allowed}."

        # Validasi panjang string
        if expected_type == "string" and "maxLength" in prop_schema:
            if len(val) > prop_schema["maxLength"]:
                return False, (
                    f"Field '{key}' terlalu panjang "
                    f"(maks {prop_schema['maxLength']} karakter)."
                )

    return True, ""
