"""
Avatar AI Suara - Titik Masuk Utama

Mode konsol  : python main.py
Mode web     : python main.py --web   -> buka http://127.0.0.1:8000

Alur konsol (mode toggle/hold/always):
  Mode toggle/hold: tekan Enter -> Mic -> VAD/rekam -> faster-whisper (STT)
                    -> LLM streaming -> Edge-TTS -> speaker (pygame)
  Mode always     : seperti semula, mic selalu mendengarkan.

Alur web:
  Tombol UI / hotkey -> Mic -> Silero VAD -> faster-whisper (STT)
      -> LLM streaming -> Edge-TTS -> WebSocket -> browser (Web Audio API)
"""
import argparse

from app.cuda_setup import setup_cuda_dll_dirs

# Inisialisasi CUDA path sebelum import faster_whisper
setup_cuda_dll_dirs()


def run_console():
    """Mode konsol dengan dukungan push-to-talk."""
    import asyncio
    import time
    import threading

    from app.config import SAMPLE_RATE, CHUNK, LLM_API_KEY, LISTEN_MODE
    from app.mic import Mic, init_vad, listen_utterance
    from app.stt import load_whisper, transcribe
    from app.llm import get_llm_client
    from app.pipeline import respond
    from app.sinks import ConsoleSink
    from app.tts import init_player, quit_player, init_tts

    if not LLM_API_KEY:
        raise SystemExit("LLM_API_KEY belum diisi. Salin env.example menjadi .env lalu isi kuncinya.")

    # Mode hold tidak didukung di konsol: log peringatan, perlakukan sebagai toggle
    effective_mode = LISTEN_MODE
    if LISTEN_MODE == "hold":
        print("[PERINGATAN] LISTEN_MODE=hold tidak didukung di mode konsol; "
              "menggunakan 'toggle' sebagai gantinya.")
        effective_mode = "toggle"

    init_player()
    print("[VAD] memuat Silero VAD...")
    vad = init_vad()
    whisper = load_whisper()
    client = get_llm_client()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    print("[TTS] Menginisialisasi sistem TTS...")
    init_tts()

    mic = Mic()
    history: list = []
    sink = ConsoleSink(loop=loop)

    if effective_mode == "always":
        # ── Mode always: perilaku lama ────────────────────────────────────────
        import sounddevice as sd
        print("\nSiap! Bicara ke mikrofon (Ctrl+C untuk keluar). Pakai headset agar tidak ada gema.\n")
        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=CHUNK,
                callback=mic.callback,
            ):
                while True:
                    audio = listen_utterance(mic, vad)
                    if audio is None:
                        continue
                    mic.muted = True
                    try:
                        t = time.perf_counter()
                        text = transcribe(whisper, audio)
                        if not text:
                            continue
                        print(f"\n[Kamu] ({time.perf_counter() - t:.2f} dtk STT) {text}")
                        sink.reset_timer()
                        loop.run_until_complete(respond(client, history, text, sink=sink))
                    except Exception as e:
                        print(f"[ERROR] {type(e).__name__}: {e}")
                    finally:
                        mic.drain()
                        mic.muted = False
        except KeyboardInterrupt:
            print("\nSampai jumpa!")
        finally:
            quit_player()
        return

    # ── Mode toggle: tekan Enter untuk satu ucapan ───────────────────────────
    print("\nSiap! Tekan Enter untuk bicara, Ctrl+C untuk keluar.\n")
    try:
        while True:
            try:
                input("[ Enter = mulai bicara ] ")
            except EOFError:
                break

            cancel_event = threading.Event()

            # Buka stream mikrofon
            mic.start()
            print("  🎤 Mendengarkan... (Enter lagi = batal)")

            # Thread pemantau Enter untuk batal
            def _wait_cancel(evt=cancel_event):
                try:
                    input()
                    evt.set()
                except EOFError:
                    pass
            cancel_thread = threading.Thread(target=_wait_cancel, daemon=True)
            cancel_thread.start()

            from app.config import LISTEN_TIMEOUT_S
            audio = listen_utterance(
                mic, vad,
                cancel_event=cancel_event,
                timeout_s=LISTEN_TIMEOUT_S,
            )
            mic.stop()

            if audio is None:
                if cancel_event.is_set():
                    print("  ✖ Dibatalkan.")
                else:
                    print("  ⏱ Tidak ada suara – kembali idle.")
                continue

            mic.muted = True
            try:
                t = time.perf_counter()
                text = transcribe(whisper, audio)
                if not text:
                    continue
                print(f"\n[Kamu] ({time.perf_counter() - t:.2f} dtk STT) {text}")
                sink.reset_timer()
                loop.run_until_complete(respond(client, history, text, sink=sink))
            except Exception as e:
                print(f"[ERROR] {type(e).__name__}: {e}")
            finally:
                mic.drain()
                mic.muted = False

    except KeyboardInterrupt:
        print("\nSampai jumpa!")
    finally:
        quit_player()


def main():
    parser = argparse.ArgumentParser(description="Silvia Avatar AI Suara")
    parser.add_argument(
        "--web",
        action="store_true",
        help="Jalankan mode web (FastAPI server + avatar browser)",
    )
    args = parser.parse_args()

    if args.web:
        from app.server import run_web
        run_web()
    else:
        run_console()


if __name__ == "__main__":
    main()
