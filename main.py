"""
Avatar AI Suara - Titik Masuk Utama

Mode konsol  : python main.py
Mode web     : python main.py --web   -> buka http://127.0.0.1:8000

Alur konsol:
  Mic -> Silero VAD -> faster-whisper (STT)
      -> LLM streaming -> Edge-TTS -> speaker (pygame)

Alur web:
  Mic -> Silero VAD -> faster-whisper (STT)
      -> LLM streaming -> Edge-TTS -> WebSocket -> browser (Web Audio API)
"""
import argparse
import sys

from app.cuda_setup import setup_cuda_dll_dirs

# Inisialisasi CUDA path sebelum import faster_whisper
setup_cuda_dll_dirs()


def run_console():
    """Mode konsol: perilaku lama, tidak ada perubahan."""
    import asyncio
    import time
    import pygame
    import sounddevice as sd

    from app.config import SAMPLE_RATE, CHUNK, LLM_API_KEY
    from app.mic import Mic, init_vad, listen_utterance
    from app.stt import load_whisper, transcribe
    from app.llm import get_llm_client
    from app.pipeline import respond
    from app.sinks import ConsoleSink
    from app.tts import init_player, quit_player

    if not LLM_API_KEY:
        raise SystemExit("LLM_API_KEY belum diisi. Salin env.example menjadi .env lalu isi kuncinya.")

    init_player()
    print("[VAD] memuat Silero VAD...")
    vad = init_vad()
    whisper = load_whisper()
    client = get_llm_client()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    mic = Mic()
    history: list = []
    sink = ConsoleSink(loop=loop)

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
                mic.muted = True  # jangan dengarkan selama memproses & berbicara
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