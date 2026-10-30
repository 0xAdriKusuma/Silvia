"""
server.py - Server FastAPI + WebSocket untuk mode --web

State machine percakapan (thread-safe via threading.Event / threading.Lock):
  idle -> listening -> transcribing -> thinking -> speaking -> idle

Protokol WebSocket baru (kompatibel mundur):
  Klien -> server: {"type":"listen","action":"start"|"stop"|"cancel"}
  Server -> klien: {"type":"status","state":"idle"|"listening"|"transcribing"|"thinking"|"speaking"}
  /api/config kini menyertakan listen_mode dan listen_hotkey.

Fail-safe: bila semua klien WebSocket terputus saat mendengarkan -> batalkan dan tutup mic.
"""
import asyncio
import json
import sys
import threading
import time
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional, Set

import psutil
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import (
    ASSETS_DIR,
    ANIMATIONS,
    EMOTIONS,
    EMOTION_EXPRESSION,
    VRM_FILE,
    IDLE_FILE,
    LLM_API_KEY,
    LISTEN_MODE,
    LISTEN_TIMEOUT_S,
    LISTEN_HOTKEY,
    LISTEN_AUTO_ARM_ON_CONFIRM,
)
from app.sinks import WebSink
from app.pipeline import respond


# ------------------------------------------------------------------ #
# Pencarian file rekursif di ASSETS_DIR                               #
# ------------------------------------------------------------------ #

def find_vrm() -> Optional[Path]:
    """Cari file .vrm secara rekursif. Prioritaskan VRM_FILE jika diisi."""
    if VRM_FILE:
        for p in ASSETS_DIR.rglob("*"):
            if p.name.lower() == VRM_FILE.lower():
                return p
    for p in ASSETS_DIR.rglob("*.vrm"):
        return p
    return None


def find_animation(filename: str) -> Optional[Path]:
    """Cari file animasi secara rekursif di ASSETS_DIR (case-insensitive)."""
    fn_lower = filename.lower()
    for p in ASSETS_DIR.rglob("*"):
        if p.name.lower() == fn_lower:
            return p
    return None


def build_config_data() -> dict:
    """Bangun dict konfigurasi yang akan dikirim ke browser via /api/config."""
    vrm_path = find_vrm()
    vrm_url = f"/assets/{vrm_path.relative_to(ASSETS_DIR).as_posix()}" if vrm_path else None

    animations_urls = {}
    missing_animations = []
    for name, info in ANIMATIONS.items():
        found = find_animation(info["file"])
        if found:
            animations_urls[name] = f"/assets/{found.relative_to(ASSETS_DIR).as_posix()}"
        else:
            missing_animations.append(name)

    idle_path = find_animation(IDLE_FILE) if IDLE_FILE else None
    idle_url = f"/assets/{idle_path.relative_to(ASSETS_DIR).as_posix()}" if idle_path else None
    if not idle_url:
        print(f"[CONFIG] Peringatan: IDLE_FILE='{IDLE_FILE}' tidak ditemukan di assets/")

    return {
        "vrm_url": vrm_url,
        "idle_url": idle_url,
        "animations": animations_urls,
        "missing_animations": missing_animations,
        "emotions": EMOTIONS,
        "emotion_expression": EMOTION_EXPRESSION,
        # Informasi push-to-talk untuk frontend
        "listen_mode": LISTEN_MODE,
        "listen_hotkey": LISTEN_HOTKEY,
    }


# ------------------------------------------------------------------ #
# State machine percakapan                                            #
# ------------------------------------------------------------------ #

class ConversationState:
    """State machine thread-safe: idle / listening / transcribing / thinking / speaking."""

    VALID_STATES = {"idle", "listening", "transcribing", "thinking", "speaking"}

    def __init__(self):
        self._state = "idle"
        self._lock = threading.Lock()
        # Event untuk memberi sinyal ke voice_loop dari luar (WebSocket / disconnect)
        self.listen_start_event = threading.Event()  # klien meminta mulai mendengarkan
        self.listen_stop_event  = threading.Event()  # klien meminta berhenti (hold release / cancel)
        self.listen_cancel_event = threading.Event() # batal (tidak dikirim ke STT)

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def set(self, new_state: str):
        assert new_state in self.VALID_STATES, f"State tidak valid: {new_state}"
        with self._lock:
            self._state = new_state

    def is_busy(self) -> bool:
        """True bila sedang memproses – permintaan mendengarkan harus diabaikan."""
        with self._lock:
            return self._state in {"transcribing", "thinking", "speaking"}


conv_state = ConversationState()


# ------------------------------------------------------------------ #
# State WebSocket terpusat                                            #
# ------------------------------------------------------------------ #

class ConnectionManager:
    """Mengelola semua koneksi WebSocket aktif."""

    def __init__(self):
        self.active: Set[WebSocket] = set()
        self._playback_event: Optional[asyncio.Event] = None

    def set_playback_event(self, event: asyncio.Event):
        self._playback_event = event

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket):
        self.active.discard(ws)
        # Fail-safe: bila tidak ada klien tersisa saat sedang mendengarkan, batalkan
        if not self.active and conv_state.state == "listening":
            print("[WS] Semua klien terputus saat mendengarkan – membatalkan mic.")
            conv_state.listen_cancel_event.set()
            conv_state.listen_stop_event.set()

    async def broadcast(self, msg: dict):
        data = json.dumps(msg, ensure_ascii=False)
        dead = set()
        for ws in self.active:
            try:
                await ws.send_text(data)
            except Exception:
                dead.add(ws)
        self.active -= dead

    async def wait_playback_done(self):
        """Tunggu sampai browser mengirim playback_done."""
        if self._playback_event:
            self._playback_event.clear()
            await self._playback_event.wait()

    def notify_playback_done(self):
        if self._playback_event:
            self._playback_event.set()


# Inisialisasi hitungan CPU awal
psutil.cpu_percent(interval=None)


def get_system_stats() -> dict[str, Any]:
    """Mengambil metrik performa CPU, RAM, dan GPU/VRAM secara aman."""
    try:
        vm = psutil.virtual_memory()
        cpu_usage = psutil.cpu_percent(interval=None)
        stats: dict[str, Any] = {
            "type": "stats",
            "cpu": {
                "percent": cpu_usage,
                "count": psutil.cpu_count(logical=True),
            },
            "ram": {
                "percent": vm.percent,
                "used_gb": round(vm.used / (1024**3), 2),
                "total_gb": round(vm.total / (1024**3), 2),
            },
            "gpu": None,
        }

        if shutil.which("nvidia-smi"):
            try:
                flags = 0x08000000 if sys.platform == "win32" else 0
                res = subprocess.check_output(
                    [
                        "nvidia-smi",
                        "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                        "--format=csv,noheader,nounits",
                    ],
                    creationflags=flags,
                    timeout=3.0,
                ).decode("utf-8", errors="ignore").strip()

                if res:
                    first_line = res.splitlines()[0]
                    parts = [p.strip() for p in first_line.split(",")]
                    if len(parts) >= 5:
                        used_mb = float(parts[2])
                        total_mb = float(parts[3])
                        pct = round((used_mb / total_mb * 100), 1) if total_mb > 0 else 0.0
                        stats["gpu"] = {
                            "name": parts[0],
                            "load": float(parts[1]),
                            "vram_used_mb": used_mb,
                            "vram_total_mb": total_mb,
                            "vram_percent": pct,
                            "temp": float(parts[4]),
                        }
            except Exception:
                pass

        return stats
    except Exception as e:
        return {"type": "stats", "error": str(e)}


manager = ConnectionManager()


# ------------------------------------------------------------------ #
# FastAPI app                                                         #
# ------------------------------------------------------------------ #

app = FastAPI(title="Silvia Avatar API")
WEB_DIR = Path(__file__).resolve().parent.parent / "web"

@app.get("/api/config")
async def api_config():
    return JSONResponse(build_config_data())

@app.get("/api/stats")
async def api_stats():
    return JSONResponse(get_system_stats())

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    print(f"[WS] Klien terhubung: {ws.client}")

    # Kirim state saat ini ke klien yang baru terhubung
    asyncio.create_task(manager.broadcast({
        "type": "status",
        "state": conv_state.state,
    }))

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            msg_type = msg.get("type")

            if msg_type == "playback_done":
                manager.notify_playback_done()

            elif msg_type == "user_text":
                # Input teks dari browser (alternatif mic, selalu diproses)
                text = msg.get("text", "").strip()
                if text and voice_loop_state.get("running") and text_input_queue:
                    text_input_queue.put_nowait(text)

            elif msg_type == "listen":
                # Protokol push-to-talk dari klien
                action = msg.get("action", "")
                _handle_listen_action(action)

    except WebSocketDisconnect:
        print(f"[WS] Klien terputus: {ws.client}")
    finally:
        manager.disconnect(ws)


def _handle_listen_action(action: str):
    """Tangani aksi listen dari klien WebSocket (dipanggil dari coroutine WebSocket)."""
    if action == "start":
        if conv_state.is_busy():
            # Sedang memproses – tolak dan beri tahu UI
            asyncio.create_task(manager.broadcast({
                "type": "status",
                "state": conv_state.state,
                "hint": "busy",
            }))
            return
        # Beri sinyal ke voice_loop agar mulai mendengarkan
        conv_state.listen_cancel_event.clear()
        conv_state.listen_stop_event.clear()
        conv_state.listen_start_event.set()

    elif action == "stop":
        # Mode hold: tombol dilepas → kirim sinyal berhenti rekam (audio dikirim ke STT)
        conv_state.listen_stop_event.set()

    elif action == "cancel":
        # Batalkan sesi mendengarkan tanpa mengirim audio ke STT
        conv_state.listen_cancel_event.set()
        conv_state.listen_stop_event.set()


# Mount folder statis setelah rute /api
app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


# ------------------------------------------------------------------ #
# Loop suara di thread terpisah                                       #
# ------------------------------------------------------------------ #

text_input_queue: Optional[asyncio.Queue] = None  # Diinisialisasi di run_web()
voice_loop_state = {"running": False}


def _broadcast_sync(loop: asyncio.AbstractEventLoop, msg: dict):
    """Kirim broadcast dari thread non-asyncio secara blocking."""
    asyncio.run_coroutine_threadsafe(manager.broadcast(msg), loop).result()


def voice_loop(loop: asyncio.AbstractEventLoop, mic, vad, whisper, client, history):
    """Loop suara berjalan di thread terpisah (blocking I/O aman di sini).

    State machine:
      idle -> (listen_start_event) -> listening -> transcribing -> (think/speak via _process) -> idle
    Mode 'always': lewati idle, langsung mulai mendengarkan seperti sebelumnya.
    """
    from app.mic import listen_utterance
    from app.stt import transcribe

    voice_loop_state["running"] = True

    async def _process(user_text: str, *, auto_arm: bool = False) -> bool:
        """Proses satu giliran percakapan; kembalikan True bila perlu auto-arm."""
        event = asyncio.Event()
        manager.set_playback_event(event)

        sink = WebSink(
            broadcast_fn=manager.broadcast,
            wait_for_done_fn=manager.wait_playback_done,
            timeout=60.0,
        )
        await manager.broadcast({"type": "user_text", "text": user_text})
        # respond() memanggil sink.set_status("thinking") secara internal
        needs_confirm = await respond(client, history, user_text, sink=sink)
        await sink.set_status("idle")
        return bool(needs_confirm) and bool(LISTEN_AUTO_ARM_ON_CONFIRM)

    # ── Mode always: buka mic sekali dan loop seperti sebelumnya ─────────────
    if LISTEN_MODE == "always":
        mic.start()
        _broadcast_sync(loop, {"type": "status", "state": "listening"})
        conv_state.set("listening")

        try:
            while voice_loop_state["running"]:
                # Cek input teks
                try:
                    text = text_input_queue.get_nowait() if text_input_queue else None
                except Exception:
                    text = None

                if text:
                    _handle_text_input(loop, mic, whisper, client, history, text, _process)
                    continue

                # Dengarkan mic
                audio = listen_utterance(mic, vad)
                if audio is None:
                    continue

                _handle_audio(loop, mic, whisper, client, history, audio, _process)
        finally:
            mic.stop()
            voice_loop_state["running"] = False
            print("[Voice] Thread suara berhenti.")
        return

    # ── Mode toggle / hold ────────────────────────────────────────────────────
    try:
        while voice_loop_state["running"]:
            # ── State: idle → tunggu sinyal start atau input teks ────────────
            conv_state.set("idle")
            _broadcast_sync(loop, {"type": "status", "state": "idle"})

            # Bila tidak ada klien web terhubung, jangan buka mic
            if not manager.active:
                time.sleep(0.2)
                continue

            # Cek input teks (selalu tersedia)
            try:
                text = text_input_queue.get_nowait() if text_input_queue else None
            except Exception:
                text = None

            if text:
                conv_state.set("transcribing")
                _broadcast_sync(loop, {"type": "status", "state": "transcribing"})
                auto_arm = asyncio.run_coroutine_threadsafe(
                    _process(text), loop
                ).result()
                if auto_arm:
                    # Setelah konfirmasi: auto-arm tanpa tunggu tombol
                    _broadcast_sync(loop, {"type": "status", "state": "listening"})
                    conv_state.listen_start_event.set()
                continue

            # Tunggu sinyal start dari klien WebSocket
            conv_state.listen_start_event.clear()
            got_signal = conv_state.listen_start_event.wait(timeout=0.5)
            if not got_signal:
                continue

            # ── State: listening ──────────────────────────────────────────────
            conv_state.set("listening")
            _broadcast_sync(loop, {"type": "status", "state": "listening"})

            # Buka stream mikrofon
            mic.start()

            audio = None
            try:
                if LISTEN_MODE == "hold":
                    # Rekam sampai tombol dilepas (hold_stop_event)
                    audio = listen_utterance(
                        mic, vad,
                        cancel_event=conv_state.listen_cancel_event,
                        hold_stop_event=conv_state.listen_stop_event,
                    )
                else:
                    # Mode toggle: VAD menentukan akhir ucapan, timeout setelah LISTEN_TIMEOUT_S
                    audio = listen_utterance(
                        mic, vad,
                        cancel_event=conv_state.listen_cancel_event,
                        timeout_s=LISTEN_TIMEOUT_S,
                    )
            finally:
                mic.stop()

            # Bersihkan event untuk sesi berikutnya
            conv_state.listen_start_event.clear()
            conv_state.listen_stop_event.clear()
            conv_state.listen_cancel_event.clear()

            if audio is None or len(audio) == 0:
                # Timeout atau dibatalkan
                hint = "cancelled" if conv_state.listen_cancel_event.is_set() else "timeout"
                _broadcast_sync(loop, {
                    "type": "status", "state": "idle", "hint": hint
                })
                continue

            # ── State: transcribing ───────────────────────────────────────────
            conv_state.set("transcribing")
            _broadcast_sync(loop, {"type": "status", "state": "transcribing"})

            mic.drain()
            t = time.perf_counter()
            user_text = transcribe(whisper, audio)
            if not user_text:
                continue
            print(f"\n[Kamu] ({time.perf_counter() - t:.2f} dtk STT) {user_text}")

            auto_arm = asyncio.run_coroutine_threadsafe(
                _process(user_text), loop
            ).result()

            if auto_arm:
                # Auto-arm: langsung mulai mendengarkan berikutnya
                conv_state.listen_cancel_event.clear()
                conv_state.listen_stop_event.clear()
                conv_state.listen_start_event.set()

    except Exception as e:
        print(f"[Voice] Error tidak tertangani: {type(e).__name__}: {e}")
    finally:
        try:
            mic.stop()
        except Exception:
            pass
        voice_loop_state["running"] = False
        print("[Voice] Thread suara berhenti.")


def _handle_audio(loop, mic, whisper, client, history, audio, _process_fn):
    """Bantu proses audio di mode always."""
    mic.muted = True
    conv_state.set("transcribing")
    asyncio.run_coroutine_threadsafe(
        manager.broadcast({"type": "status", "state": "transcribing"}), loop
    ).result()
    try:
        from app.stt import transcribe
        t = time.perf_counter()
        user_text = transcribe(whisper, audio)
        if not user_text:
            return
        print(f"\n[Kamu] ({time.perf_counter() - t:.2f} dtk STT) {user_text}")
        asyncio.run_coroutine_threadsafe(_process_fn(user_text), loop).result()
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}")
        asyncio.run_coroutine_threadsafe(
            manager.broadcast({"type": "error", "message": str(e)}), loop
        ).result()
    finally:
        mic.drain()
        mic.muted = False
        conv_state.set("listening")
        asyncio.run_coroutine_threadsafe(
            manager.broadcast({"type": "status", "state": "listening"}), loop
        ).result()


def _handle_text_input(loop, mic, whisper, client, history, text, _process_fn):
    """Bantu proses input teks (semua mode)."""
    mic.muted = True
    conv_state.set("transcribing")
    asyncio.run_coroutine_threadsafe(
        manager.broadcast({"type": "status", "state": "transcribing"}), loop
    ).result()
    try:
        asyncio.run_coroutine_threadsafe(_process_fn(text), loop).result()
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}")
        asyncio.run_coroutine_threadsafe(
            manager.broadcast({"type": "error", "message": str(e)}), loop
        ).result()
    finally:
        mic.drain()
        mic.muted = False
        if LISTEN_MODE == "always":
            conv_state.set("listening")
            asyncio.run_coroutine_threadsafe(
                manager.broadcast({"type": "status", "state": "listening"}), loop
            ).result()
        else:
            conv_state.set("idle")
            asyncio.run_coroutine_threadsafe(
                manager.broadcast({"type": "status", "state": "idle"}), loop
            ).result()


def run_web():
    """Jalankan mode web: FastAPI server + voice loop di thread terpisah."""
    global text_input_queue

    if not LLM_API_KEY:
        raise SystemExit("LLM_API_KEY belum diisi. Salin env.example menjadi .env lalu isi kuncinya.")

    from app.mic import Mic, init_vad
    from app.stt import load_whisper
    from app.llm import get_llm_client

    print("[VAD] memuat Silero VAD...")
    vad = init_vad()
    whisper = load_whisper()
    client = get_llm_client()
    mic = Mic()
    history: list = []

    # Bila MIC_KEEP_OPEN=1, buka stream sekarang agar latensi nol saat pertama kali dipakai
    if LISTEN_MODE != "always":
        from app.config import MIC_KEEP_OPEN
        if MIC_KEEP_OPEN:
            mic.start()
            mic.discard_frames = True  # buang frame sampai ada sinyal start
            print("[Mic] MIC_KEEP_OPEN=1: stream terbuka, frame dibuang sampai ada sinyal start.")

    # Event loop utama (untuk asyncio FastAPI)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    text_input_queue = asyncio.Queue()

    voice_thread = threading.Thread(
        target=voice_loop,
        args=(loop, mic, vad, whisper, client, history),
        daemon=True,
        name="voice-loop",
    )

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=8000,
        loop="none",
        log_level="warning",
    )
    server = uvicorn.Server(config)

    async def system_stats_task():
        """Mengirim data live stats CPU, RAM, GPU/VRAM ke semua klien web tiap 1 detik."""
        while voice_loop_state.get("running", True):
            if manager.active:
                stats = await asyncio.to_thread(get_system_stats)
                await manager.broadcast(stats)
            await asyncio.sleep(1.0)

    from app.tts import init_tts

    async def serve():
        print("[TTS] Menginisialisasi sistem TTS (unduhan model pertama kali bisa memakan waktu)...")
        await asyncio.to_thread(init_tts)
        print("[TTS] Siap!")

        voice_thread.start()
        stats_bg_task = asyncio.create_task(system_stats_task())
        print("\n[WEB] Server berjalan di http://127.0.0.1:8000")
        print("[WEB] Buka browser, lalu tekan Ctrl+C untuk keluar.\n")
        try:
            await server.serve()
        finally:
            stats_bg_task.cancel()

    try:
        loop.run_until_complete(serve())
    except KeyboardInterrupt:
        print("\nSampai jumpa!")
    finally:
        voice_loop_state["running"] = False
        server.should_exit = True
