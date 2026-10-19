"""
agent/tests/test_safety.py - Unit test untuk modul keamanan

Menguji:
- safe_path(): tolak ../ path absolut, drive letter, UNC, nama perangkat Windows,
  ekstensi terlarang, folder sebagai target delete, workspace itu sendiri
- resolve_name(): cocok persis, cocok unik, ambigu, tidak ditemukan
- validate_url(): tolak file:, javascript:, URL dengan kredensial, URL terlalu panjang
- is_trigger(): mode keyword
"""
import sys
from pathlib import Path

import pytest

# Pastikan root proyek ada di sys.path
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.safety import SafePathError, safe_path, resolve_name, validate_url, is_trigger
from agent.config import WORKSPACE_DIR


# ======================== TEST SAFE_PATH ========================

class TestSafePath:
    """Pengujian safe_path() dengan berbagai input berbahaya."""

    def test_valid_simple_file(self, tmp_path, monkeypatch):
        """Nama file sederhana yang valid harus lolos."""
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        result = safe_path("catatan.txt")
        assert result.name == "catatan.txt"
        assert result.parent.resolve() == tmp_path.resolve()

    def test_rejects_dotdot(self, tmp_path, monkeypatch):
        """Traversal .. harus ditolak."""
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        with pytest.raises(SafePathError, match="keluar dari workspace"):
            safe_path("../rahasia.txt")

    def test_rejects_dotdot_deeper(self, tmp_path, monkeypatch):
        """Traversal lebih dalam juga ditolak."""
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        with pytest.raises(SafePathError):
            safe_path("subdir/../../.env")

    def test_rejects_absolute_path_windows(self, tmp_path, monkeypatch):
        """Path dengan drive letter Windows harus ditolak."""
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        with pytest.raises(SafePathError, match="drive letter"):
            safe_path("C:\\Windows\\System32\\cmd.exe")

    def test_rejects_unc_path(self, tmp_path, monkeypatch):
        """UNC path harus ditolak."""
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        with pytest.raises(SafePathError, match="UNC"):
            safe_path("\\\\server\\share\\file.txt")

    def test_rejects_unix_absolute(self, tmp_path, monkeypatch):
        """Path absolut Unix harus ditolak."""
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        with pytest.raises(SafePathError, match="Path absolut"):
            safe_path("/etc/passwd")

    def test_rejects_empty_name(self, tmp_path, monkeypatch):
        """Nama kosong harus ditolak."""
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        with pytest.raises(SafePathError, match="kosong"):
            safe_path("")

    def test_rejects_whitespace_name(self, tmp_path, monkeypatch):
        """Nama hanya whitespace harus ditolak."""
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        with pytest.raises(SafePathError, match="kosong"):
            safe_path("   ")

    def test_rejects_windows_device_con(self, tmp_path, monkeypatch):
        """Nama perangkat Windows CON harus ditolak."""
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        with pytest.raises(SafePathError, match="perangkat Windows"):
            safe_path("CON.txt")

    def test_rejects_windows_device_nul(self, tmp_path, monkeypatch):
        """Nama perangkat Windows NUL harus ditolak."""
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        with pytest.raises(SafePathError, match="perangkat Windows"):
            safe_path("NUL.txt")

    def test_rejects_windows_device_com1(self, tmp_path, monkeypatch):
        """Nama perangkat Windows COM1 harus ditolak."""
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        with pytest.raises(SafePathError, match="perangkat Windows"):
            safe_path("COM1.txt")

    def test_rejects_forbidden_extension_exe(self, tmp_path, monkeypatch):
        """Ekstensi .exe harus ditolak."""
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        with pytest.raises(SafePathError, match="Ekstensi"):
            safe_path("malware.exe")

    def test_rejects_forbidden_extension_bat(self, tmp_path, monkeypatch):
        """Ekstensi .bat harus ditolak."""
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        with pytest.raises(SafePathError, match="Ekstensi"):
            safe_path("run.bat")

    def test_rejects_forbidden_extension_ps1(self, tmp_path, monkeypatch):
        """Ekstensi .ps1 harus ditolak."""
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        with pytest.raises(SafePathError, match="Ekstensi"):
            safe_path("script.ps1")

    def test_rejects_forbidden_extension_lnk(self, tmp_path, monkeypatch):
        """Ekstensi .lnk harus ditolak."""
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        with pytest.raises(SafePathError, match="Ekstensi"):
            safe_path("shortcut.lnk")

    def test_rejects_workspace_itself(self, tmp_path, monkeypatch):
        """Workspace itu sendiri sebagai target harus ditolak."""
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        with pytest.raises(SafePathError, match="workspace itu sendiri"):
            safe_path(".")

    def test_rejects_forbidden_char_colon(self, tmp_path, monkeypatch):
        """Karakter titik dua dalam nama file harus ditolak."""
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        with pytest.raises(SafePathError):
            safe_path("file:name.txt")

    def test_valid_extensions(self, tmp_path, monkeypatch):
        """Semua ekstensi yang diizinkan harus lolos."""
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        for ext in [".txt", ".md", ".json", ".csv", ".log", ".py", ".html", ".css", ".js"]:
            result = safe_path(f"test{ext}")
            assert result.suffix == ext

    def test_valid_subfolder(self, tmp_path, monkeypatch):
        """Path dengan subfolder yang sah harus lolos."""
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        result = safe_path("subfolder/data.json")
        assert result.parent.name == "subfolder"
        assert result.name == "data.json"


# ======================== TEST RESOLVE_NAME ========================

class TestResolveName:
    """Pengujian resolve_name() untuk input suara/teks."""

    def test_exact_match(self, tmp_path):
        """Cocok persis dengan nama lengkap."""
        f = tmp_path / "catatan.txt"
        f.write_text("isi")
        result = resolve_name("catatan.txt", workspace=tmp_path)
        assert result == f

    def test_case_insensitive_match(self, tmp_path):
        """Cocok case-insensitive."""
        f = tmp_path / "Catatan.txt"
        f.write_text("isi")
        result = resolve_name("catatan.txt", workspace=tmp_path)
        assert result == f

    def test_match_without_extension(self, tmp_path):
        """Cocok tanpa ekstensi jika unik."""
        f = tmp_path / "laporan.md"
        f.write_text("laporan")
        result = resolve_name("laporan", workspace=tmp_path)
        assert result == f

    def test_ambiguous_raises_error(self, tmp_path):
        """Ambigu (lebih dari satu kandidat) harus mengembalikan error."""
        (tmp_path / "data.txt").write_text("a")
        (tmp_path / "data.json").write_text("b")
        with pytest.raises(SafePathError, match="ambigu"):
            resolve_name("data", workspace=tmp_path)

    def test_not_found_raises_error(self, tmp_path):
        """File tidak ditemukan harus mengembalikan error."""
        (tmp_path / "ada.txt").write_text("a")
        with pytest.raises(SafePathError, match="tidak ditemukan"):
            resolve_name("tidakada.txt", workspace=tmp_path)

    def test_empty_workspace_raises_error(self, tmp_path):
        """Workspace kosong harus mengembalikan error informatif."""
        with pytest.raises(SafePathError, match="kosong"):
            resolve_name("apapun.txt", workspace=tmp_path)


# ======================== TEST VALIDATE_URL ========================

class TestValidateUrl:
    """Pengujian validate_url() untuk berbagai input URL."""

    def test_valid_https(self):
        """URL https:// yang valid harus lolos."""
        url = validate_url("https://example.com")
        assert url == "https://example.com"

    def test_valid_http(self):
        """URL http:// yang valid harus lolos."""
        url = validate_url("http://example.com/path?q=1")
        assert url == "http://example.com/path?q=1"

    def test_rejects_file_scheme(self):
        """Skema file:// harus ditolak."""
        with pytest.raises(ValueError, match="file:"):
            validate_url("file:///C:/Users")

    def test_rejects_javascript_scheme(self):
        """Skema javascript: harus ditolak."""
        with pytest.raises(ValueError, match="javascript:"):
            validate_url("javascript:alert(1)")

    def test_rejects_ftp_scheme(self):
        """Skema ftp: harus ditolak."""
        with pytest.raises(ValueError):
            validate_url("ftp://files.example.com")

    def test_rejects_credentials_in_url(self):
        """URL dengan kredensial user:pass@host harus ditolak."""
        with pytest.raises(ValueError, match="kredensial"):
            validate_url("https://user:password@example.com")

    def test_rejects_too_long_url(self):
        """URL terlalu panjang harus ditolak."""
        long_url = "https://example.com/" + "a" * 2000
        with pytest.raises(ValueError, match="terlalu panjang"):
            validate_url(long_url)

    def test_trims_whitespace(self):
        """URL dengan whitespace di tepi harus di-trim."""
        url = validate_url("  https://example.com  ")
        assert url == "https://example.com"


# ======================== TEST IS_TRIGGER ========================

class TestIsTrigger:
    """Pengujian is_trigger() untuk mode keyword."""

    def test_trigger_on_buka(self, monkeypatch):
        """Kata 'buka' harus memicu agent."""
        monkeypatch.setattr("agent.safety.TRIGGER_MODE", "keyword")
        assert is_trigger("buka spotify") is True

    def test_trigger_on_hapus(self, monkeypatch):
        """Kata 'hapus' harus memicu agent."""
        monkeypatch.setattr("agent.safety.TRIGGER_MODE", "keyword")
        assert is_trigger("hapus file catatan") is True

    def test_no_trigger_casual(self, monkeypatch):
        """Obrolan biasa tidak boleh memicu agent."""
        monkeypatch.setattr("agent.safety.TRIGGER_MODE", "keyword")
        assert is_trigger("halo apa kabar kamu?") is False

    def test_always_mode(self, monkeypatch):
        """Mode 'always' selalu memicu agent."""
        monkeypatch.setattr("agent.safety.TRIGGER_MODE", "always")
        assert is_trigger("halo apa kabar?") is True
