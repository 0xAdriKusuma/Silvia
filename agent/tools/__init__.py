"""
agent/tools/__init__.py - Import semua modul alat agar terdaftar ke registry

Urutan import penting: setiap modul mendaftarkan alatnya via dekorator @tool
saat diimport. File ini diimport oleh agent/core.py sebelum schemas() dipanggil.
"""
# Import semua modul alat — jangan hapus baris ini
from agent.tools import files  # noqa: F401
from agent.tools import apps   # noqa: F401
