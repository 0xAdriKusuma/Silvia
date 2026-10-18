import numpy as np
from faster_whisper import WhisperModel
from app.config import WHISPER_MODEL, STT_LANG, SAMPLE_RATE
from app.cuda_setup import setup_cuda_dll_dirs

setup_cuda_dll_dirs()


def load_whisper() -> WhisperModel:
    try:
        model = WhisperModel(WHISPER_MODEL, device="cuda", compute_type="float16")
        # Pemanasan: error CUDA (mis. cuDNN/cuBLAS hilang) baru muncul saat transkripsi
        segs, _ = model.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), language=STT_LANG)
        list(segs)
        print("[STT] Whisper berjalan di GPU")
        return model
    except Exception as e:
        print(f"[STT] GPU gagal ({type(e).__name__}: {e}) -> pakai CPU int8")
        return WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")


def transcribe(model: WhisperModel, audio: np.ndarray) -> str:
    segments, _ = model.transcribe(
        audio,
        language=STT_LANG,
        beam_size=1,
        vad_filter=False,
        condition_on_previous_text=False,
    )
    return " ".join(s.text.strip() for s in segments).strip()
