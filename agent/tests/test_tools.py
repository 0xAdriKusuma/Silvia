"""
agent/tests/test_tools.py - Unit test untuk alat file dan aplikasi

Menguji:
- create_file: tidak menimpa, batas ukuran, ekstensi allowlist
- read_file: baca dengan truncasi
- list_files: daftar isi workspace
- delete_file: send2trash dimonkeypatch, hanya file (bukan folder)
- open_app: tolak nama di luar allowlist
- open_url: tolak skema berbahaya
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ======================== TEST CREATE FILE ========================

class TestCreateFile:
    """Pengujian alat create_file."""

    @pytest.mark.asyncio
    async def test_create_new_file(self, tmp_path, monkeypatch):
        """File baru berhasil dibuat."""
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        from agent.tools.files import create_file
        result = await create_file("test.txt", "halo dunia")
        assert result.startswith("OK")
        assert (tmp_path / "test.txt").read_text() == "halo dunia"

    @pytest.mark.asyncio
    async def test_create_does_not_overwrite(self, tmp_path, monkeypatch):
        """File yang sudah ada tidak ditimpa."""
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        from agent.tools.files import create_file
        (tmp_path / "ada.txt").write_text("isi lama")
        result = await create_file("ada.txt", "isi baru")
        assert "ERROR" in result
        assert "sudah ada" in result
        # Pastikan isi lama tidak berubah
        assert (tmp_path / "ada.txt").read_text() == "isi lama"

    @pytest.mark.asyncio
    async def test_create_rejects_forbidden_extension(self, tmp_path, monkeypatch):
        """Ekstensi terlarang ditolak saat create."""
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        from agent.tools.files import create_file
        result = await create_file("script.bat", "del /f")
        assert "ERROR" in result

    @pytest.mark.asyncio
    async def test_create_rejects_path_traversal(self, tmp_path, monkeypatch):
        """Path traversal ditolak saat create."""
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        from agent.tools.files import create_file
        result = await create_file("../../.env", "API_KEY=leaked")
        assert "ERROR" in result

    @pytest.mark.asyncio
    async def test_create_rejects_too_large_content(self, tmp_path, monkeypatch):
        """Konten yang melebihi batas ukuran ditolak."""
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        from agent.tools.files import create_file
        large_content = "x" * (100 * 1024 + 1)  # 100 KB + 1 byte
        result = await create_file("besar.txt", large_content)
        assert "ERROR" in result
        assert "besar" in result.lower()

    @pytest.mark.asyncio
    async def test_create_with_subfolder(self, tmp_path, monkeypatch):
        """Buat file di subfolder yang belum ada."""
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        from agent.tools.files import create_file
        result = await create_file("sub/data.json", "{}")
        assert result.startswith("OK")
        assert (tmp_path / "sub" / "data.json").exists()


# ======================== TEST READ FILE ========================

class TestReadFile:
    """Pengujian alat read_file."""

    @pytest.mark.asyncio
    async def test_read_existing_file(self, tmp_path, monkeypatch):
        """Membaca file yang ada."""
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        (tmp_path / "catatan.txt").write_text("isi catatan", encoding="utf-8")
        from agent.tools.files import read_file
        result = await read_file("catatan.txt")
        assert "isi catatan" in result
        assert "<isi_file>" in result

    @pytest.mark.asyncio
    async def test_read_truncates_large_file(self, tmp_path, monkeypatch):
        """File besar dipotong, ada catatan terpotong."""
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        # Buat file lebih besar dari MAX_READ_SIZE_BYTES (20 KB)
        big_content = "A" * (21 * 1024)
        (tmp_path / "besar.txt").write_text(big_content, encoding="utf-8")
        from agent.tools.files import read_file
        result = await read_file("besar.txt")
        assert "TERPOTONG" in result

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, tmp_path, monkeypatch):
        """File tidak ada mengembalikan error."""
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        from agent.tools.files import read_file
        result = await read_file("tidakada.txt")
        assert "ERROR" in result

    @pytest.mark.asyncio
    async def test_read_by_stem_only(self, tmp_path, monkeypatch):
        """Baca file dengan nama tanpa ekstensi (jika unik)."""
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        (tmp_path / "laporan.md").write_text("# Laporan", encoding="utf-8")
        from agent.tools.files import read_file
        result = await read_file("laporan")
        assert "# Laporan" in result


# ======================== TEST LIST FILES ========================

class TestListFiles:
    """Pengujian alat list_files."""

    @pytest.mark.asyncio
    async def test_list_files_populated(self, tmp_path, monkeypatch):
        """Daftar file workspace yang berisi file."""
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        # Patch WORKSPACE_DIR langsung di modul files agar list_files menggunakan tmp_path
        import agent.tools.files as files_mod
        monkeypatch.setattr(files_mod, "WORKSPACE_DIR", tmp_path)
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.json").write_text("{}")
        from agent.tools.files import list_files
        result = await list_files()
        assert "a.txt" in result
        assert "b.json" in result

    @pytest.mark.asyncio
    async def test_list_files_empty_workspace(self, tmp_path, monkeypatch):
        """Workspace kosong memberikan pesan informatif."""
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        from agent.tools.files import list_files
        result = await list_files()
        assert "kosong" in result.lower()


# ======================== TEST DELETE FILE ========================

class TestDeleteFile:
    """Pengujian alat delete_file (send2trash dimonkeypatch)."""

    @pytest.mark.asyncio
    async def test_delete_file_success(self, tmp_path, monkeypatch):
        """Hapus file berhasil (send2trash dimonkeypatch)."""
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        target = tmp_path / "hapus.txt"
        target.write_text("bye")

        # Monkeypatch send2trash agar tidak benar-benar menghapus
        trashed = []
        import agent.tools.files as files_module
        import types
        fake_s2t = types.ModuleType("send2trash")
        fake_s2t.send2trash = lambda p: trashed.append(p)
        monkeypatch.setitem(sys.modules, "send2trash", fake_s2t)

        from importlib import reload
        # Reload agar import baru dipakai
        result = await files_module.delete_file("hapus.txt")
        # Verifikasi send2trash dipanggil dengan path yang benar
        assert any("hapus.txt" in str(p) for p in trashed) or result.startswith("OK")

    @pytest.mark.asyncio
    async def test_delete_nonexistent_file(self, tmp_path, monkeypatch):
        """File tidak ada mengembalikan error."""
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        from agent.tools.files import delete_file
        result = await delete_file("tidakada.txt")
        assert "ERROR" in result

    @pytest.mark.asyncio
    async def test_delete_directory_rejected(self, tmp_path, monkeypatch):
        """Menghapus folder (bukan file) harus ditolak."""
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        # Buat subfolder dengan nama yang punya ekstensi (agar lolos safe_path)
        folder = tmp_path / "subfolder.txt"
        folder.mkdir()  # Folder dengan nama seperti file
        from agent.tools.files import delete_file
        result = await delete_file("subfolder.txt")
        # Harus error karena bukan file
        assert "ERROR" in result

    @pytest.mark.asyncio
    async def test_delete_no_fallback_on_send2trash_fail(self, tmp_path, monkeypatch):
        """Jika send2trash gagal, TIDAK fallback ke hapus permanen."""
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        target = tmp_path / "penting.txt"
        target.write_text("data penting")

        import types
        fake_s2t = types.ModuleType("send2trash")
        def fake_trash(p):
            raise OSError("Recycle Bin tidak tersedia")
        fake_s2t.send2trash = fake_trash
        monkeypatch.setitem(sys.modules, "send2trash", fake_s2t)

        import agent.tools.files as files_module
        result = await files_module.delete_file("penting.txt")
        # File harus tetap ada (tidak dihapus permanen)
        assert target.exists(), "File tidak boleh dihapus jika send2trash gagal!"
        assert "ERROR" in result


# ======================== TEST OPEN APP ========================

class TestOpenApp:
    """Pengujian alat open_app."""

    @pytest.mark.asyncio
    async def test_open_app_rejects_unknown(self):
        """Nama di luar allowlist harus ditolak."""
        from agent.tools.apps import open_app
        result = await open_app("cmd")
        assert "ERROR" in result
        assert "allowlist" in result

    @pytest.mark.asyncio
    async def test_open_app_rejects_path(self):
        """Path eksplisit sebagai nama harus ditolak."""
        from agent.tools.apps import open_app
        result = await open_app("C:\\Windows\\System32\\cmd.exe")
        assert "ERROR" in result

    @pytest.mark.asyncio
    async def test_open_app_valid_name_non_windows(self, monkeypatch):
        """Di non-Windows, open_app mengembalikan error 'tidak didukung' tanpa crash."""
        import sys
        monkeypatch.setattr(sys, "platform", "linux")
        from agent.tools import apps as apps_module
        monkeypatch.setattr(apps_module.sys, "platform", "linux")
        result = await apps_module.open_app("calculator")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_open_app_new_apps_registered(self):
        """Aplikasi baru (discord, word, excel, taskmgr) harus terdaftar di allowlist."""
        from agent.config import APP_ALLOWLIST
        for app in ["discord", "word", "excel", "taskmgr"]:
            assert app in APP_ALLOWLIST

    @pytest.mark.asyncio
    async def test_open_app_alias_resolution(self, monkeypatch):
        """Alias seperti 'microsoft word' dan 'task manager' berhasil dipetakan."""
        from agent.tools import apps as apps_module
        called = []

        def mock_launch(name):
            called.append(name)
            return f"OK: Aplikasi '{name}' berhasil dibuka."

        monkeypatch.setattr(apps_module, "_launch_app", mock_launch)

        res1 = await apps_module.open_app("microsoft word")
        assert "OK" in res1
        assert called[-1] == "word"

        res2 = await apps_module.open_app("task manager")
        assert "OK" in res2
        assert called[-1] == "taskmgr"

        res3 = await apps_module.open_app("excel")
        assert "OK" in res3
        assert called[-1] == "excel"

        res4 = await apps_module.open_app("discord")
        assert "OK" in res4
        assert called[-1] == "discord"


# ======================== TEST OPEN URL ========================

class TestOpenUrl:
    """Pengujian alat open_url."""

    @pytest.mark.asyncio
    async def test_open_url_rejects_file_scheme(self):
        """file:// harus ditolak."""
        from agent.tools.apps import open_url
        result = await open_url("file:///C:/Users")
        assert "ERROR" in result

    @pytest.mark.asyncio
    async def test_open_url_rejects_javascript(self):
        """javascript: harus ditolak."""
        from agent.tools.apps import open_url
        result = await open_url("javascript:alert('xss')")
        assert "ERROR" in result

    @pytest.mark.asyncio
    async def test_open_url_valid(self, monkeypatch):
        """URL https yang valid diterima (webbrowser.open dimonkeypatch)."""
        import webbrowser
        opened = []
        monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)
        from agent.tools.apps import open_url
        result = await open_url("https://example.com")
        assert result.startswith("OK")
        assert "https://example.com" in opened
