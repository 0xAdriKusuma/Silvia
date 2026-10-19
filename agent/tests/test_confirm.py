"""
agent/tests/test_confirm.py - Unit test untuk alur konfirmasi pending action

Menguji:
- delete_file tidak langsung dieksekusi (harus pending dulu)
- "ya" mengeksekusi args PERSIS yang tersimpan
- "tidak" membatalkan
- Ucapan panjang/ambigu tidak mengonfirmasi
- Kadaluarsa otomatis setelah CONFIRM_EXPIRY_SECONDS
- Permintaan baru saat ada pending -> batalkan pending lama
- Tabel lengkap kata ya/tidak (termasuk "Ya." dengan tanda baca)
"""
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import agent.pending as pending_module
from agent.pending import PendingAction, set_pending, get_pending, clear_pending
from agent.core import _classify_answer, _normalize_answer


# ======================== TEST NORMALIZE & CLASSIFY ========================

class TestClassifyAnswer:
    """Uji klasifikasi jawaban konfirmasi oleh kode (bukan LLM)."""

    @pytest.mark.parametrize("text,expected", [
        # Afirmatif
        ("ya", "affirmative"),
        ("Ya", "affirmative"),
        ("YA", "affirmative"),
        ("Ya.", "affirmative"),         # tanda baca di ujung
        ("iya", "affirmative"),
        ("yes", "affirmative"),
        ("oke", "affirmative"),
        ("ok", "affirmative"),
        ("lanjut", "affirmative"),
        ("boleh", "affirmative"),
        ("silakan", "affirmative"),
        ("hapus baru.txt", "ambiguous"),   # perintah aksi, bukan konfirmasi
        # Negatif
        ("tidak", "negative"),
        ("Tidak", "negative"),
        ("nggak", "negative"),
        ("gak", "negative"),
        ("enggak", "negative"),
        ("jangan", "negative"),
        ("batal", "negative"),
        ("cancel", "negative"),
        ("no", "negative"),
        ("stop", "negative"),
        ("batalkan", "negative"),
        # Ambigu
        ("mungkin", "ambiguous"),
        ("nanti dulu", "ambiguous"),
        ("apa itu benar sekali", "ambiguous"),  # 4 kata
    ])
    def test_classify(self, text, expected):
        """Klasifikasi kata afirmatif, negatif, ambigu."""
        assert _classify_answer(text) == expected

    def test_too_many_words_is_ambiguous(self):
        """Lebih dari 4 kata = ambigu."""
        assert _classify_answer("ya saya setuju sekali dong") == "ambiguous"

    def test_yes_with_punctuation(self):
        """'Ya.' dengan tanda baca harus diklasifikasi afirmatif."""
        assert _classify_answer("Ya.") == "affirmative"

    def test_no_with_punctuation(self):
        """'Tidak!' dengan tanda baca harus diklasifikasi negatif."""
        assert _classify_answer("Tidak!") == "negative"


# ======================== TEST PENDING STORE ========================

class TestPendingStore:
    """Uji manajemen pending action store."""

    def setup_method(self):
        """Reset pending sebelum setiap test."""
        clear_pending()

    def test_set_and_get_pending(self):
        """set_pending dan get_pending berfungsi."""
        action = PendingAction(
            tool_name="delete_file",
            args={"path": "catatan.txt"},
            human_description="Hapus 'catatan.txt'?",
        )
        set_pending(action)
        got = get_pending()
        assert got is not None
        assert got.tool_name == "delete_file"
        assert got.args == {"path": "catatan.txt"}

    def test_get_pending_returns_none_when_empty(self):
        """Tidak ada pending -> get_pending() None."""
        assert get_pending() is None

    def test_pending_expires(self, monkeypatch):
        """Pending kadaluarsa setelah batas waktu."""
        monkeypatch.setattr("agent.config.CONFIRM_EXPIRY_SECONDS", 1)
        monkeypatch.setattr("agent.pending.CONFIRM_EXPIRY_SECONDS", 1)
        action = PendingAction(
            tool_name="delete_file",
            args={"path": "test.txt"},
            human_description="Hapus?",
            created_at=time.time() - 2,  # 2 detik yang lalu
        )
        set_pending(action)
        got = get_pending()
        assert got is None  # Sudah kadaluarsa

    def test_new_request_cancels_old_pending(self):
        """set_pending baru menggantikan pending lama."""
        action1 = PendingAction("delete_file", {"path": "a.txt"}, "Hapus a?")
        action2 = PendingAction("delete_file", {"path": "b.txt"}, "Hapus b?")
        set_pending(action1)
        set_pending(action2)
        got = get_pending()
        assert got.args["path"] == "b.txt"

    def test_clear_pending(self):
        """clear_pending() menghapus pending."""
        action = PendingAction("delete_file", {"path": "x.txt"}, "Hapus?")
        set_pending(action)
        clear_pending()
        assert get_pending() is None


# ======================== TEST HANDLE_TURN KONFIRMASI ========================

class TestConfirmationFlow:
    """Uji alur konfirmasi melalui handle_turn dengan klien palsu."""

    def setup_method(self):
        """Reset pending dan workspace sebelum tiap test."""
        clear_pending()

    def _make_fake_client(self, responses):
        """
        Buat klien LLM palsu yang mengembalikan urutan respons.
        responses: list dari dict {"content": str, "tool_calls": list | None}
        """
        import types

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
                # Default: tidak ada tool call
                return FakeResponse("selesai", tool_calls=None)

        class FakeChat:
            def __init__(self, resp_list):
                self.completions = FakeCompletions(resp_list)

        class FakeClient:
            def __init__(self, resp_list):
                self.chat = FakeChat(resp_list)

        return FakeClient, FakeResponse, FakeToolCall

    @pytest.mark.asyncio
    async def test_delete_file_creates_pending(self, tmp_path, monkeypatch):
        """delete_file (risk=confirm) harus membuat pending, bukan langsung dieksekusi."""
        import json as _json
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.config.AGENT_ENABLED", True)
        monkeypatch.setattr("agent.config.TRIGGER_MODE", "always")
        monkeypatch.setattr("agent.safety.TRIGGER_MODE", "always")

        # Buat file target di workspace
        target = tmp_path / "catatan.txt"
        target.write_text("isi")

        FakeClient, FakeResponse, FakeToolCall = self._make_fake_client([])

        # Respons LLM: minta delete_file
        tc = FakeToolCall("delete_file", _json.dumps({"path": "catatan.txt"}))
        resp1 = FakeResponse("", tool_calls=[tc])

        client = FakeClient([resp1])

        from agent.core import handle_turn
        result = await handle_turn(
            user_text="hapus catatan",
            history=[],
            client=client,
            model="fake-model",
        )

        # Harus mengembalikan needs_confirmation=True, bukan langsung execute
        assert result.handled is True
        assert result.needs_confirmation is True
        assert "catatan.txt" in result.message

        # File harus masih ada (belum dihapus)
        assert target.exists()

        # Pending harus terset
        pending = get_pending()
        assert pending is not None
        assert pending.tool_name == "delete_file"

    @pytest.mark.asyncio
    async def test_yes_executes_pending(self, tmp_path, monkeypatch):
        """Jawaban 'ya' mengeksekusi args yang tersimpan PERSIS."""
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.config.AGENT_ENABLED", True)
        monkeypatch.setattr("agent.config.TRIGGER_MODE", "always")
        monkeypatch.setattr("agent.safety.TRIGGER_MODE", "always")

        target = tmp_path / "hapus_ini.txt"
        target.write_text("data")

        # Setup pending langsung
        action = PendingAction(
            tool_name="delete_file",
            args={"path": "hapus_ini.txt"},
            human_description="Hapus 'hapus_ini.txt'?",
        )
        set_pending(action)

        # Mock send2trash
        trashed = []
        import types
        fake_s2t = types.ModuleType("send2trash")
        fake_s2t.send2trash = lambda p: trashed.append(p)
        monkeypatch.setitem(sys.modules, "send2trash", fake_s2t)

        FakeClient, FakeResponse, FakeToolCall = self._make_fake_client([])
        client = FakeClient([FakeResponse("ok")])

        from agent.core import handle_turn
        result = await handle_turn(
            user_text="ya",
            history=[],
            client=client,
            model="fake-model",
        )

        assert result.handled is True
        assert result.needs_confirmation is False
        # Pending harus dibersihkan
        assert get_pending() is None

    @pytest.mark.asyncio
    async def test_no_cancels_pending(self, tmp_path, monkeypatch):
        """Jawaban 'tidak' membatalkan pending."""
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.config.AGENT_ENABLED", True)

        target = tmp_path / "aman.txt"
        target.write_text("tetap ada")

        action = PendingAction(
            tool_name="delete_file",
            args={"path": "aman.txt"},
            human_description="Hapus 'aman.txt'?",
        )
        set_pending(action)

        FakeClient, FakeResponse, FakeToolCall = self._make_fake_client([])
        client = FakeClient([FakeResponse("ok")])

        from agent.core import handle_turn
        result = await handle_turn(
            user_text="tidak",
            history=[],
            client=client,
            model="fake-model",
        )

        assert result.handled is True
        assert result.needs_confirmation is False
        assert "batal" in result.message.lower() or "tidak jadi" in result.message.lower()
        # Pending harus dibersihkan
        assert get_pending() is None
        # File tetap ada
        assert target.exists()

    @pytest.mark.asyncio
    async def test_ambiguous_asks_again(self, tmp_path, monkeypatch):
        """Jawaban ambigu meminta konfirmasi ulang."""
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.config.AGENT_ENABLED", True)
        monkeypatch.setattr("agent.config.MAX_AMBIGUOUS_RETRIES", 2)

        action = PendingAction(
            tool_name="delete_file",
            args={"path": "x.txt"},
            human_description="Hapus 'x.txt'?",
        )
        set_pending(action)

        FakeClient, FakeResponse, FakeToolCall = self._make_fake_client([])
        client = FakeClient([FakeResponse("ok")])

        from agent.core import handle_turn
        result = await handle_turn(
            user_text="mungkin saja",
            history=[],
            client=client,
            model="fake-model",
        )

        assert result.handled is True
        assert result.needs_confirmation is True
        # Pending masih ada (belum dibatalkan)
        assert get_pending() is not None

    @pytest.mark.asyncio
    async def test_expired_pending_auto_cancelled(self, tmp_path, monkeypatch):
        """Pending kadaluarsa dibatalkan otomatis saat ada giliran baru."""
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.config.AGENT_ENABLED", True)
        monkeypatch.setattr("agent.config.TRIGGER_MODE", "always")
        monkeypatch.setattr("agent.safety.TRIGGER_MODE", "always")
        monkeypatch.setattr("agent.pending.CONFIRM_EXPIRY_SECONDS", 1)
        monkeypatch.setattr("agent.config.CONFIRM_EXPIRY_SECONDS", 1)

        action = PendingAction(
            tool_name="delete_file",
            args={"path": "x.txt"},
            human_description="Hapus?",
            created_at=time.time() - 2,  # sudah kadaluarsa
        )
        set_pending(action)

        FakeClient, FakeResponse, FakeToolCall = self._make_fake_client([])
        client = FakeClient([FakeResponse("ok")])

        from agent.core import handle_turn
        result = await handle_turn(
            user_text="ya",
            history=[],
            client=client,
            model="fake-model",
        )

        assert result.handled is True
        assert "kadaluarsa" in result.message.lower()
        assert get_pending() is None

    @pytest.mark.asyncio
    async def test_new_request_cancels_old_pending(self, tmp_path, monkeypatch):
        """Permintaan baru saat ada pending lama -> batalkan pending lama."""
        import json as _json
        monkeypatch.setattr("agent.config.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.safety.WORKSPACE_DIR", tmp_path)
        monkeypatch.setattr("agent.config.AGENT_ENABLED", True)
        monkeypatch.setattr("agent.config.TRIGGER_MODE", "always")
        monkeypatch.setattr("agent.safety.TRIGGER_MODE", "always")

        # Hanya buat file target baru (bukan lama) agar pending lama tidak bisa dieksekusi
        (tmp_path / "baru.txt").write_text("baru")
        # TIDAK membuat lama.txt -> pending lama tidak bisa di-confirm

        # Ada pending lama untuk file yang TIDAK ada
        old_action = PendingAction(
            tool_name="delete_file",
            args={"path": "lama.txt"},
            human_description="Hapus 'lama.txt'?",
        )
        set_pending(old_action)

        FakeClient, FakeResponse, FakeToolCall = self._make_fake_client([])

        # Respons LLM: minta delete file baru (memicu pending baru)
        tc = FakeToolCall("delete_file", _json.dumps({"path": "baru.txt"}))
        resp1 = FakeResponse("", tool_calls=[tc])
        client = FakeClient([resp1])

        from agent.core import handle_turn
        result = await handle_turn(
            user_text="hapus baru.txt",
            history=[],
            client=client,
            model="fake-model",
        )

        assert result.handled is True
        assert result.needs_confirmation is True

        # Pending baru seharusnya untuk baru.txt
        current = get_pending()
        assert current is not None
        assert current.args["path"] == "baru.txt"
