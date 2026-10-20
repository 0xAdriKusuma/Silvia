"""
server.py - Server FastAPI + WebSocket untuk mode --web

Menjalankan loop suara (blocking: VAD/STT) di thread terpisah.
Server asyncio FastAPI berjalan di thread utama.
Komunikasi antar-thread: asyncio.run_coroutine_threadsafe + threading.Event.
"""
import asyncio
import base64
import json
import sys
import threading
import time
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Set

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
    SAMPLE_RATE,
    CHUNK,
    LLM_API_KEY,
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
    # Ambil .vrm pertama yang ditemukan
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

    # Cari URL Idle.vrma secara terpisah (tidak masuk ke animations)
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
    }


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


def get_system_stats() -> dict:
    """Mengambil metrik performa CPU, RAM, dan GPU/VRAM secara aman."""
    try:
        vm = psutil.virtual_memory()
        cpu_usage = psutil.cpu_percent(interval=None)
        stats = {
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

        # Cek NVIDIA GPU / VRAM via nvidia-smi
        if shutil.which("nvidia-smi"):
            try:
                # 0x08000000 = CREATE_NO_WINDOW agar tidak muncul cmd pop-up di Windows
                flags = 0x08000000 if sys.platform == "win32" else 0
                res = subprocess.check_output(
                    [
                        "nvidia-smi",
                        "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                        "--format=csv,noheader,nounits",
                    ],
                    creationflags=flags,
                    timeout=1.0,
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
                # Input teks dari browser (alternatif mic)
                text = msg.get("text", "").strip()
                if text and voice_loop_state.get("running"):
                    # Masukkan ke antrian input teks
                    text_input_queue.put_nowait(text)

    except WebSocketDisconnect:
        print(f"[WS] Klien terputus: {ws.client}")
    finally:
        manager.disconnect(ws)


# Mount folder statis setelah rute /api/config dan /ws agar tidak mencegat rute API
app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


# ------------------------------------------------------------------ #
# Loop suara di thread terpisah                                       #
# ------------------------------------------------------------------ #

text_input_queue: asyncio.Queue = None  # Diinisialisasi di run_web()
voice_loop_state = {"running": False}


def voice_loop(loop: asyncio.AbstractEventLoop, mic, vad, whisper, client, history):
    """Loop suara berjalan di thread terpisah (blocking I/O aman di sini)."""
    import sounddevice as sd
    from app.mic import listen_utterance

    voice_loop_state["running"] = True

    async def _process(user_text: str):
        """Proses satu giliran percakapan di event loop utama."""
        event = asyncio.Event()
        manager.set_playback_event(event)

        sink = WebSink(
            broadcast_fn=manager.broadcast,
            wait_for_done_fn=manager.wait_playback_done,
            timeout=60.0,
        )
        await manager.broadcast({"type": "user_text", "text": user_text})
        await sink.set_status("speaking")
        await respond(client, history, user_text, sink=sink)
        await sink.set_status("listening")

    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=CHUNK,
            callback=mic.callback,
        ):
            asyncio.run_coroutine_threadsafe(
                manager.broadcast({"type": "status", "state": "listening"}), loop
            ).result()

            while voice_loop_state["running"]:
                # Cek juga apakah ada input teks dari browser
                try:
                    text = text_input_queue.get_nowait() if text_input_queue else None
                except Exception:
                    text = None

                if text:
                    mic.muted = True
                    try:
                        asyncio.run_coroutine_threadsafe(
                            manager.broadcast({"type": "status", "state": "transcribing"}), loop
                        ).result()
                        asyncio.run_coroutine_threadsafe(_process(text), loop).result()
                    except Exception as e:
                        print(f"[ERROR] {type(e).__name__}: {e}")
                        asyncio.run_coroutine_threadsafe(
                            manager.broadcast({"type": "error", "message": str(e)}), loop
                        ).result()
                    finally:
                        mic.drain()
                        mic.muted = False
                    continue

                # Dengarkan mikrofon
                try:
                    audio = listen_utterance(mic, vad)
                except Exception:
                    break

                mic.muted = True
                try:
                    asyncio.run_coroutine_threadsafe(
                        manager.broadcast({"type": "status", "state": "transcribing"}), loop
                    ).result()
                    from app.stt import transcribe
                    t = time.perf_counter()
                    user_text = transcribe(whisper, audio)
                    if not user_text:
                        continue
                    print(f"\n[Kamu] ({time.perf_counter() - t:.2f} dtk STT) {user_text}")
                    asyncio.run_coroutine_threadsafe(_process(user_text), loop).result()
                except Exception as e:
                    print(f"[ERROR] {type(e).__name__}: {e}")
                    asyncio.run_coroutine_threadsafe(
                        manager.broadcast({"type": "error", "message": str(e)}), loop
                    ).result()
                finally:
                    mic.drain()
                    mic.muted = False
    finally:
        voice_loop_state["running"] = False
        print("[Voice] Thread suara berhenti.")


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

    # Event loop utama (untuk asyncio FastAPI)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    text_input_queue = asyncio.Queue()

    # Thread suara (blocking)
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
        loop="none",  # gunakan loop kita sendiri
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

    async def serve():
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
