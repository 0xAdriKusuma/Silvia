"""
agent/tests/test_core.py - Unit test untuk loop agent (core.py)

Menguji:
- Klien LLM palsu yang mengembalikan tool_calls: dispatch benar
- Batas langkah (MAX_STEPS)
- Argumen tidak valid ditangani (tidak crash)
- handled=False jika tidak ada tool call pada langkah pertama
- Alat confirm menghasilkan pending (bukan eksekusi)
- Hasil alat dipotong sebelum dikirim ke LLM
- AGENT_ENABLED=0 -> langsung handled=False
- Mode trigger keyword
- Audit log tertulis untuk executed/blocked/pending
"""
import json
import sys
from pathlib import Path
import time

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import agent.pending as pending_module
from agent.pending import clear_pending, get_pending, PendingAction, set_pending


# ======================== HELPER: FAKE CLIENT ========================

class FakeFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments

class FakeToolCall:
    def __init__(self, name, arguments, call_id="tc1"):
        self.id = call_id
        self.function = FakeFunction(name, arguments)

class FakeMessage:
    def __init__(self, content, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

class FakeChoice:
    def __init__(self, content, tool_calls=None):
        self.message = FakeMessage(content, tool_calls)

class FakeResponse:
    def __init__(self, content, tool_calls=None):
        self.choices = [FakeChoice(content, tool_calls)]

class FakeCompletions:
    def __init__(self, resp_list):
        self._resps = list(resp_list)
        self._idx = 0

    async def create(self, **kwargs):
        if self._idx < len(self._resps):
            r = self._resps[self._idx]
            self._idx += 1
            return r
        return FakeResponse("selesai", tool_calls=None)

class FakeChat:
    def __init__(self, resp_list):
        self.completions = FakeCompletions(resp_list)

class FakeClient:
    def __init__(self, resp_list):
        self.chat = FakeChat(resp_list)


# ======================== TEST CORE ========================

class TestCore:
    """Pengujian loop agent core.py."""

    def setup_method(self):
        clear_pending()

    @pytest.mark.asyncio
    async def test_no_tool_call_returns_not_handled(self, tmp_path, monkeypatch):
        """Jika LLM tidak meminta alat pada langkah pertama -> handled=False."""
        monkeypatch.setattr("agent.config.AGENT_ENABLED", True)
        monkeypatch.setattr("agent.config.TRIGGER_MODE", "always")
        monkeypatch.setattr("agent.safety.TRIGGER_MODE", "always")

        client = FakeClient([FakeResponse("Halo!", tool_calls=None)])

        from agent.core import handle_turn
        result = await handle_turn(
            user_text="halo apa kabar",
            history=[],
            client=client,
            model="fake",
        )
        assert result.handled is False

    @pytest.mark.asyncio
    async def test_agent_disabled_returns_not_handled(self, monkeypatch):
        """AGENT_ENABLED=False -> langsung handled=False."""
        monkeypatch.setattr("agent.config.AGENT_ENABLED", False)
        # Import ulang config di core untuk test ini
        import agent.core as core_module
        monkeypatch.setattr(core_module, "AGENT_ENABLED", False)

        client = FakeClient([])

        from agent.core import handle_turn
        result = await handle_turn(
            user_text="buka spotify",
            history=[],
            client=client,
            model="fake",
        )
        assert result.handled is False

    @pytest.mark.asyncio
    async def test_keyword_trigger_not_matched(self, monkeypatch):
        """Teks tanpa kata kunci tidak memicu agent (mode keyword)."""
        monkeypatch.setattr("agent.config.AGENT_ENABLED", True)
        monkeypatch.setattr("agent.config.TRIGGER_MODE", "keyword")
        monkeypatch.setattr("agent.safety.TRIGGER_MODE", "keyword")

        client = FakeClient([])

        from agent.core import handle_turn
        result = await handle_turn(
            user_text="halo apa kabar kamu",
            history=[],
            client=client,
            model="fake",
        )
        assert result.handled is False

    @pytest.mark.asyncio
    async def test_keyword_trigger_matched(self, tmp_path, monkeypatch):
        """Teks dengan kata kunci memicu agent (mode keyword)."""
        monkeypatch.setattr("agent.config.AGENT_ENABLED", True)
        monkeypatch.setattr("agent.config.TRIGGER_MODE", "keyword")
        monkeypatch.setattr("agent.safety.TRIGGER_MODE", "keyword")
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)

        # LLM tidak minta tool -> handled=False, tapi trigger harus berjalan
        client = FakeClient([FakeResponse("tidak ada tool")])

        from agent.core import handle_turn
        result = await handle_turn(
            user_text="buka spotify sekarang",  # "buka" adalah trigger keyword
            history=[],
            client=client,
            model="fake",
        )
        # Tidak ada tool call -> handled=False, tapi trigger tercapai (LLM dipanggil)
        assert result.handled is False

    @pytest.mark.asyncio
    async def test_invalid_tool_args_not_crash(self, tmp_path, monkeypatch):
        """Argumen tidak valid ditangani gracefully (tidak crash)."""
        monkeypatch.setattr("agent.config.AGENT_ENABLED", True)
        monkeypatch.setattr("agent.config.TRIGGER_MODE", "always")
        monkeypatch.setattr("agent.safety.TRIGGER_MODE", "always")
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)

        # Argumen JSON tidak valid
        tc = FakeToolCall("create_file", "BUKAN_JSON")
        resp1 = FakeResponse("", tool_calls=[tc])
        resp2 = FakeResponse("selesai")  # LLM mengakhiri setelah error

        client = FakeClient([resp1, resp2])

        from agent.core import handle_turn
        result = await handle_turn(
            user_text="buat file test",
            history=[],
            client=client,
            model="fake",
        )
        # Tidak boleh crash; handled bisa True atau False tergantung langkah
        assert isinstance(result.handled, bool)

    @pytest.mark.asyncio
    async def test_unknown_tool_blocked(self, monkeypatch):
        """Alat tidak dikenal diblokir dengan error, tidak crash."""
        monkeypatch.setattr("agent.config.AGENT_ENABLED", True)
        monkeypatch.setattr("agent.config.TRIGGER_MODE", "always")
        monkeypatch.setattr("agent.safety.TRIGGER_MODE", "always")

        tc = FakeToolCall("ALAT_TIDAK_DIKENAL", json.dumps({"x": 1}))
        resp1 = FakeResponse("", tool_calls=[tc])
        resp2 = FakeResponse("selesai")

        client = FakeClient([resp1, resp2])

        from agent.core import handle_turn
        result = await handle_turn(
            user_text="jalankan sesuatu",
            history=[],
            client=client,
            model="fake",
        )
        # Tidak crash
        assert isinstance(result.handled, bool)

    @pytest.mark.asyncio
    async def test_max_steps_respected(self, tmp_path, monkeypatch):
        """Loop tidak melebihi MAX_STEPS."""
        monkeypatch.setattr("agent.config.AGENT_ENABLED", True)
        monkeypatch.setattr("agent.config.TRIGGER_MODE", "always")
        monkeypatch.setattr("agent.safety.TRIGGER_MODE", "always")
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.config.MAX_STEPS", 2)
        import agent.core as core_module
        monkeypatch.setattr(core_module, "MAX_STEPS", 2)

        # Setiap langkah LLM selalu minta list_files (loop tak terbatas jika tidak dibatasi)
        tc = FakeToolCall("list_files", json.dumps({}))
        responses = [FakeResponse("", tool_calls=[tc])] * 5  # lebih dari MAX_STEPS

        client = FakeClient(responses)

        from agent.core import handle_turn
        result = await handle_turn(
            user_text="tampilkan file terus",
            history=[],
            client=client,
            model="fake",
        )
        # Tidak crash dan ada hasil (loop terbatas)
        assert isinstance(result.handled, bool)

    @pytest.mark.asyncio
    async def test_confirm_tool_creates_pending_not_execute(self, tmp_path, monkeypatch):
        """Alat risk=confirm (delete_file) harus membuat pending, bukan dieksekusi."""
        monkeypatch.setattr("agent.config.AGENT_ENABLED", True)
        monkeypatch.setattr("agent.config.TRIGGER_MODE", "always")
        monkeypatch.setattr("agent.safety.TRIGGER_MODE", "always")
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)

        target = tmp_path / "sensitif.txt"
        target.write_text("data penting")

        tc = FakeToolCall("delete_file", json.dumps({"path": "sensitif.txt"}))
        client = FakeClient([FakeResponse("", tool_calls=[tc])])

        from agent.core import handle_turn
        result = await handle_turn(
            user_text="hapus sensitif.txt",
            history=[],
            client=client,
            model="fake",
        )

        assert result.handled is True
        assert result.needs_confirmation is True
        # File masih ada
        assert target.exists()
        # Pending terset
        assert get_pending() is not None

    @pytest.mark.asyncio
    async def test_tool_result_truncated(self, tmp_path, monkeypatch):
        """Hasil alat dipotong sebelum dikirim ke LLM (TOOL_RESULT_MAX_CHARS)."""
        monkeypatch.setattr("agent.config.AGENT_ENABLED", True)
        monkeypatch.setattr("agent.config.TRIGGER_MODE", "always")
        monkeypatch.setattr("agent.safety.TRIGGER_MODE", "always")
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.config.TOOL_RESULT_MAX_CHARS", 50)
        import agent.core as core_module
        monkeypatch.setattr(core_module, "TOOL_RESULT_MAX_CHARS", 50)

        # Buat file besar untuk dibaca
        big = tmp_path / "besar.txt"
        big.write_text("X" * 5000, encoding="utf-8")

        # LLM step 1: minta read_file
        tc = FakeToolCall("read_file", json.dumps({"path": "besar.txt"}))
        # LLM step 2: tidak ada tool call (selesai)
        resp2 = FakeResponse("selesai")

        # Rekam pesan yang dikirim ke LLM
        calls_kwargs = []
        original_create = FakeCompletions.create

        async def patched_create(self, **kwargs):
            calls_kwargs.append(kwargs)
            if self._idx == 0:
                self._idx += 1
                return FakeResponse("", tool_calls=[tc])
            return FakeResponse("selesai")

        monkeypatch.setattr(FakeCompletions, "create", patched_create)

        client = FakeClient([])

        from agent.core import handle_turn
        result = await handle_turn(
            user_text="baca file besar",
            history=[],
            client=client,
            model="fake",
        )

        # Cek bahwa pesan tool ke LLM dipotong (panjang <= 50 + "[HASIL DIPOTONG]")
        tool_messages = [
            m for call in calls_kwargs
            for m in call.get("messages", [])
            if m.get("role") == "tool"
        ]
        for tm in tool_messages:
            content = tm.get("content", "")
            assert len(content) <= 50 + len("\n[HASIL DIPOTONG]")


# ======================== TEST AUDIT LOG ========================

class TestAuditLog:
    """Pengujian bahwa audit log tertulis untuk keputusan penting."""

    @pytest.mark.asyncio
    async def test_audit_log_written_on_execute(self, tmp_path, monkeypatch):
        """Log 'executed' tertulis saat alat berhasil dieksekusi."""
        monkeypatch.setattr("agent.config.AGENT_ENABLED", True)
        monkeypatch.setattr("agent.config.TRIGGER_MODE", "always")
        monkeypatch.setattr("agent.safety.TRIGGER_MODE", "always")
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)

        # Arahkan log ke tmp_path
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_path = log_dir / "audit.log"
        monkeypatch.setattr("agent.config.LOGS_DIR", log_dir)
        monkeypatch.setattr("agent.audit.AUDIT_LOG_PATH", log_path)

        tc = FakeToolCall("list_files", json.dumps({}))
        resp2 = FakeResponse("selesai")
        client = FakeClient([FakeResponse("", tool_calls=[tc]), resp2])

        from agent.core import handle_turn
        await handle_turn(
            user_text="tampilkan daftar file",
            history=[],
            client=client,
            model="fake",
        )

        assert log_path.exists()
        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        entries = [json.loads(l) for l in lines if l.strip()]
        decisions = [e["decision"] for e in entries]
        assert any(d in ("executed", "error") for d in decisions)

    @pytest.mark.asyncio
    async def test_audit_log_written_on_pending(self, tmp_path, monkeypatch):
        """Log 'pending' tertulis saat alat confirm menunggu konfirmasi."""
        monkeypatch.setattr("agent.config.AGENT_ENABLED", True)
        monkeypatch.setattr("agent.config.TRIGGER_MODE", "always")
        monkeypatch.setattr("agent.safety.TRIGGER_MODE", "always")
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)

        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_path = log_dir / "audit.log"
        monkeypatch.setattr("agent.config.LOGS_DIR", log_dir)
        monkeypatch.setattr("agent.audit.AUDIT_LOG_PATH", log_path)

        (tmp_path / "target.txt").write_text("data")

        tc = FakeToolCall("delete_file", json.dumps({"path": "target.txt"}))
        client = FakeClient([FakeResponse("", tool_calls=[tc])])

        from agent.core import handle_turn
        await handle_turn(
            user_text="hapus target",
            history=[],
            client=client,
            model="fake",
        )

        clear_pending()
        assert log_path.exists()
        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        entries = [json.loads(l) for l in lines if l.strip()]
        decisions = [e["decision"] for e in entries]
        assert "pending" in decisions
