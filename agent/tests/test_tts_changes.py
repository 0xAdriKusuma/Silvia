"""
agent/tests/test_tts_changes.py - Tes untuk perubahan TTS: kebijakan fallback baru,
pemecahan potongan Jepang (split_chunks_jp), dan field continuation.

Tidak memerlukan torch atau SBV2Engine yang sungguhan -- semua di-mock.
"""
import sys
import asyncio
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ======================== SPLIT_CHUNKS_JP ========================

class TestSplitChunksJp:
    """Tes pemecahan teks Jepang menjadi potongan pendek."""

    def test_pendek_tidak_dipecah(self):
        """Teks <= max_chars dikembalikan sebagai satu potongan."""
        from app.tts import split_chunks_jp
        result = split_chunks_jp("こんにちは！", max_chars=40)
        assert len(result) == 1
        assert result[0] == "こんにちは！"

    def test_pecah_di_titik_kalimat(self):
        """Teks panjang dipecah di tanda akhir kalimat Jepang."""
        from app.tts import split_chunks_jp
        text = "バーチャルメモリとは何ですか。ハードディスクをRAMとして使う技術だよ。便利でしょう。"
        result = split_chunks_jp(text, max_chars=20)
        assert len(result) >= 2
        # Setiap potongan tidak boleh lebih dari 20 karakter
        for chunk in result:
            assert len(chunk) <= 20, f"Potongan terlalu panjang: {chunk!r}"

    def test_pecah_di_koma_jepang(self):
        """Jika masih terlalu panjang setelah titik, dipecah di tanda koma Jepang."""
        from app.tts import split_chunks_jp
        text = "これは長い文で、まだまだ続いて、どんどん長くなるよ"
        result = split_chunks_jp(text, max_chars=12)
        assert len(result) >= 2
        for chunk in result:
            assert len(chunk) <= 12, f"Potongan terlalu panjang: {chunk!r}"

    def test_tidak_ada_potongan_kosong(self):
        """Tidak boleh ada potongan kosong dalam hasil."""
        from app.tts import split_chunks_jp
        text = "あいうえお。かきくけこ。さしすせそ。"
        result = split_chunks_jp(text, max_chars=10)
        assert all(c.strip() for c in result), "Ada potongan kosong"

    def test_teks_kosong_menghasilkan_list_kosong(self):
        """Teks kosong harus menghasilkan list kosong."""
        from app.tts import split_chunks_jp
        assert split_chunks_jp("", max_chars=40) == []
        assert split_chunks_jp("   ", max_chars=40) == []


# ======================== FALLBACK POLICY ========================

class TestFallbackPolicy:
    """Tes kebijakan fallback SBV2_ALLOW_FALLBACK."""

    @pytest.mark.asyncio
    async def test_allow_fallback_false_raises_on_sbv2_failure(self, monkeypatch):
        """Dengan SBV2_ALLOW_FALLBACK=False dan SBV2 tidak siap: harus raise, bukan Edge."""
        import app.tts as tts_mod
        monkeypatch.setattr(tts_mod, "_sbv2_engine", None)
        monkeypatch.setattr("app.tts.TTS_BACKEND", "sbv2")
        monkeypatch.setattr("app.tts.SBV2_ALLOW_FALLBACK", False)

        with pytest.raises(RuntimeError, match="SBV2Engine"):
            await tts_mod.synth_clip("こんにちは", "neutral")

    @pytest.mark.asyncio
    async def test_allow_fallback_true_calls_edge_on_sbv2_failure(self, monkeypatch):
        """Dengan SBV2_ALLOW_FALLBACK=True dan mode auto + SBV2 tidak siap: Edge dipanggil."""
        import app.tts as tts_mod

        edge_called = []

        async def fake_edge(text, emotion):
            edge_called.append(text)
            from app.tts import AudioClip
            return AudioClip(data=b"mp3data", fmt="mp3", duration=1.0)

        monkeypatch.setattr(tts_mod, "_sbv2_engine", None)
        monkeypatch.setattr("app.tts.TTS_BACKEND", "auto")
        monkeypatch.setattr("app.tts.SBV2_ALLOW_FALLBACK", True)
        monkeypatch.setattr(tts_mod, "_synth_edge", fake_edge)

        clip = await tts_mod.synth_clip("こんにちは", "neutral")
        assert len(edge_called) == 1
        assert clip.fmt == "mp3"

    @pytest.mark.asyncio
    async def test_sbv2_mode_no_lock_bypass(self, monkeypatch):
        """Pada mode sbv2, tidak ada pengecekan lock -- sintesis dijalankan langsung."""
        import app.tts as tts_mod
        import threading

        class FakeEngine:
            ready = True
            device = "cpu"
            _lock = threading.Lock()

            @property
            def lock(self):
                return self._lock

            def synth(self, text, params):
                import numpy as np
                return 44100, np.zeros(100, dtype=np.int16)

        monkeypatch.setattr(tts_mod, "_sbv2_engine", FakeEngine())
        monkeypatch.setattr("app.tts.TTS_BACKEND", "sbv2")
        monkeypatch.setattr("app.tts.SBV2_ALLOW_FALLBACK", False)
        monkeypatch.setattr("app.tts.SBV2_TIMEOUT_S", 30.0)

        clip = await tts_mod.synth_clip("こんにちは", "neutral")
        assert clip.fmt == "wav"
        assert len(clip.data) > 0


# ======================== CONTINUATION FIELD ========================

class TestContinuationField:
    """Tes bahwa WebSink mengirim field continuation=True pada potongan lanjutan."""

    @pytest.mark.asyncio
    async def test_first_chunk_no_continuation(self):
        """Potongan pertama tidak memiliki field continuation."""
        from app.tts import AudioClip
        from app.sinks import WebSink

        sent = []

        async def broadcast(msg):
            sent.append(msg)

        async def wait_done():
            pass

        sink = WebSink(broadcast, wait_done)
        clip = AudioClip(data=b"wav", fmt="wav", duration=0.5)
        await sink.emit_line("neutral", None, "こんにちは", "Halo", clip, is_first_chunk=True)

        assert len(sent) == 1
        assert "continuation" not in sent[0]

    @pytest.mark.asyncio
    async def test_subsequent_chunk_has_continuation_true(self):
        """Potongan lanjutan memiliki field continuation=True."""
        from app.tts import AudioClip
        from app.sinks import WebSink

        sent = []

        async def broadcast(msg):
            sent.append(msg)

        async def wait_done():
            pass

        sink = WebSink(broadcast, wait_done)
        clip = AudioClip(data=b"wav", fmt="wav", duration=0.5)
        await sink.emit_line("neutral", None, "こんにちは", "Halo", clip, is_first_chunk=False)

        assert len(sent) == 1
        assert sent[0].get("continuation") is True

    @pytest.mark.asyncio
    async def test_turn_end_after_chunks(self):
        """turn_end dikirim setelah semua potongan selesai."""
        from app.tts import AudioClip
        from app.sinks import WebSink

        sent = []
        done_event = asyncio.Event()

        async def broadcast(msg):
            sent.append(msg)
            if msg.get("type") == "turn_end":
                done_event.set()

        async def wait_done():
            await done_event.wait()

        sink = WebSink(broadcast, wait_done, timeout=2.0)
        clip = AudioClip(data=b"", fmt="wav", duration=0.0)

        await sink.emit_line("neutral", None, "test", "test", clip, is_first_chunk=True)
        await sink.emit_line("neutral", None, "test", "test", clip, is_first_chunk=False)
        await sink.end_turn()

        types = [m.get("type") for m in sent]
        assert "turn_end" in types
        # turn_end adalah pesan terakhir
        assert types[-1] == "turn_end"
