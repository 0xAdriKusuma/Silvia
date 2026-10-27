import time
import numpy as np
from faster_whisper import WhisperModel
from app.config import WHISPER_MODEL, WHISPER_COMPUTE_TYPE, STT_LANG, SAMPLE_RATE
from app.cuda_setup import setup_cuda_dll_dirs

setup_cuda_dll_dirs()

# Repo HuggingFace cadangan jika nama "turbo" belum dikenal versi faster-whisper terpasang
_TURBO_FALLBACK_REPO = "deepdml/faster-whisper-large-v3-turbo-ct2"


def _try_load_gpu(model_id: str, compute_type: str) -> WhisperModel:
    """Muat model di GPU; lempar exception jika gagal (CUDA/cuBLAS/OOM/nama tak dikenal)."""
    print(f"[STT] Mencoba GPU | model={model_id} | compute_type={compute_type}")
    model = WhisperModel(model_id, device="cuda", compute_type=compute_type)
    # Pemanasan: error CUDA (mis. cuDNN/cuBLAS/OOM) biasanya baru muncul saat transkripsi pertama
    print("[STT] Pemanasan GPU...")
    t_wu = time.perf_counter()
    segs, _ = model.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), language=STT_LANG)
    list(segs)
    print(f"[STT] Pemanasan selesai ({time.perf_counter() - t_wu:.2f} dtk)")
    return model


def load_whisper() -> WhisperModel:
    """
    Urutan percobaan (log jelas di tiap langkah):
      a. GPU + WHISPER_MODEL + WHISPER_COMPUTE_TYPE
      b. Jika nama model tidak dikenal (turbo belum didukung versi ini):
         GPU + repo HuggingFace cadangan + WHISPER_COMPUTE_TYPE yang sama
      c. Jika GPU tetap gagal (CUDA/OOM/cuBLAS):
         CPU + model yang SAMA + int8 (tidak turun ke model lebih kecil)
    """
    t_start = time.perf_counter()

    # --- Langkah a: GPU + model utama ---
    try:
        model = _try_load_gpu(WHISPER_MODEL, WHISPER_COMPUTE_TYPE)
        elapsed = time.perf_counter() - t_start
        print(
            f"[STT] ✓ Model aktif: {WHISPER_MODEL} | device=cuda "
            f"| compute_type={WHISPER_COMPUTE_TYPE} | muat={elapsed:.2f} dtk"
        )
        return model
    except Exception as e_main:
        print(f"[STT] ✗ Langkah a gagal ({type(e_main).__name__}: {e_main})")

    # --- Langkah b: Nama model tidak dikenal → coba repo HuggingFace cadangan ---
    # Hanya dicoba jika model utama adalah "turbo" (versi faster-whisper lama mungkin belum kenal)
    if WHISPER_MODEL.lower() == "turbo":
        try:
            print(f"[STT] Mencoba repo cadangan: {_TURBO_FALLBACK_REPO}")
            model = _try_load_gpu(_TURBO_FALLBACK_REPO, WHISPER_COMPUTE_TYPE)
            elapsed = time.perf_counter() - t_start
            print(
                f"[STT] ✓ Model aktif: {_TURBO_FALLBACK_REPO} | device=cuda "
                f"| compute_type={WHISPER_COMPUTE_TYPE} | muat={elapsed:.2f} dtk"
            )
            return model
        except Exception as e_repo:
            print(f"[STT] ✗ Langkah b gagal ({type(e_repo).__name__}: {e_repo})")
            print(
                "[STT] SARAN: Jalankan: pip install -U faster-whisper  "
                "agar model 'turbo' dikenali secara native."
            )
    else:
        print(f"[STT] Langkah b dilewati (model bukan 'turbo': {WHISPER_MODEL})")

    # --- Langkah c: Fallback CPU + model yang SAMA ---
    print(
        f"[STT] ⚠ PERINGATAN: GPU tidak tersedia. Memuat {WHISPER_MODEL} di CPU (int8). "
        "STT akan lebih lambat dari biasanya."
    )
    t_cpu = time.perf_counter()
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    # Pemanasan CPU
    segs, _ = model.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), language=STT_LANG)
    list(segs)
    elapsed = time.perf_counter() - t_start
    print(
        f"[STT] ✓ Model aktif: {WHISPER_MODEL} | device=cpu | compute_type=int8 "
        f"| muat={elapsed:.2f} dtk (termasuk pemanasan CPU)"
    )
    return model


def transcribe(model: WhisperModel, audio: np.ndarray) -> str:
    segments, _ = model.transcribe(
        audio,
        language=STT_LANG,
        beam_size=1,
        vad_filter=False,
        condition_on_previous_text=False,
    )
    return " ".join(s.text.strip() for s in segments).strip()
