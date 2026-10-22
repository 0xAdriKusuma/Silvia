"""
tts_sbv2.py - Engine TTS Style-Bert-VITS2 (SBV2) lokal
"""
import inspect
import json
import threading
import time
from pathlib import Path
from typing import Any
import numpy as np

from app.config import (
    BASE_DIR,
    SBV2_MODEL_DIR,
    SBV2_REPO,
    SBV2_MODEL_NAME,
    SBV2_FILES,
    SBV2_BERT,
    SBV2_DEVICE,
    EMOTION_STYLE,
)


class SBV2Engine:
    """Engine inferensi Style-Bert-VITS2 dengan dukungan pengunduhan otomatis dan isolasi thread."""

    def __init__(
        self,
        model_dir: Path | str | None = None,
        repo: str | None = None,
        model_name: str | None = None,
        files: tuple[str, ...] | list[str] | None = None,
        bert_model: str | None = None,
        device: str | None = None,
    ):
        self.model_dir = Path(model_dir or SBV2_MODEL_DIR)
        self.repo = repo or SBV2_REPO
        self.model_name = model_name or SBV2_MODEL_NAME
        self.files = tuple(files or SBV2_FILES)
        self.bert_model = bert_model or SBV2_BERT
        self._device_cfg = (device or SBV2_DEVICE).lower()
        self._device: str = "cpu"
        self._lock = threading.Lock()
        self._ready: bool = False
        self._model: Any = None
        self._style2id: dict[str, int] = {}
        self._spk2id: dict[str, int] = {}
        self._default_speaker_id: int = 0

    def ensure_files(self) -> None:
        """Memastikan tiga file model SBV2 tersedia di direktori lokal, mengunduh dari Hugging Face bila belum ada."""
        from huggingface_hub import hf_hub_download

        self.model_dir.mkdir(parents=True, exist_ok=True)
        for rel_file in self.files:
            target_path = self.model_dir / rel_file
            if not target_path.exists() or target_path.stat().st_size == 0:
                print(f"[SBV2] Mengunduh '{rel_file}' dari Hugging Face repo '{self.repo}'...")
                hf_hub_download(
                    repo_id=self.repo,
                    filename=rel_file,
                    local_dir=str(self.model_dir),
                )
                if not target_path.exists():
                    raise FileNotFoundError(f"Gagal mengunduh atau menyimpan file: {target_path}")

    def load(self) -> None:
        """Memuat BERT, model SBV2, validasi style emosi, dan pemanasan awal (warm-up)."""
        import sys
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except Exception:
                pass
        if hasattr(sys.stderr, "reconfigure"):
            try:
                sys.stderr.reconfigure(encoding="utf-8")
            except Exception:
                pass

        t_start = time.perf_counter()

        # 1. Pastikan file model lokal sudah ada
        self.ensure_files()

        # 2. Impor lazy torch dan style_bert_vits2 agar mode edge bebas dependensi torch
        import torch
        from style_bert_vits2.nlp import bert_models
        from style_bert_vits2.constants import Languages
        from style_bert_vits2.tts_model import TTSModel

        # Konfigurasi sink loguru agar tidak error encoding di Windows cp1252
        try:
            from loguru import logger
            logger.remove()
            logger.add(sys.stderr, encoding="utf-8", level="INFO")
        except Exception:
            pass


        # Tentukan perangkat inferensi
        if self._device_cfg == "auto":
            self._device = "cuda" if torch.cuda.is_available() else "cpu"
        elif self._device_cfg == "cuda":
            if not torch.cuda.is_available():
                print("[SBV2] Peringatan: CUDA tidak tersedia pada sistem ini, beralih ke CPU.")
                self._device = "cpu"
            else:
                self._device = "cuda"
        else:
            self._device = "cpu"

        # 3. Muat model BERT dan tokenizernya
        print(f"[SBV2] Memuat BERT model '{self.bert_model}' pada device={self._device} (unduhan otomatis ke cache HF bila belum ada)...")
        loaded_bert = bert_models.load_model(Languages.JP, pretrained_model_name_or_path=self.bert_model)
        bert_models.load_tokenizer(Languages.JP, pretrained_model_name_or_path=self.bert_model)
        # Pindahkan BERT ke device yang sama dengan model TTS dan pastikan dtype float32
        # agar cocok dengan bobot model TTS (mencegah error Half vs float bias di F.conv1d)
        if hasattr(loaded_bert, "to"):
            loaded_bert.to(self._device)
            actual_bert_device = next(loaded_bert.parameters()).device if hasattr(loaded_bert, "parameters") else self._device
            print(f"[SBV2] BERT berjalan di device: {actual_bert_device}")
        if hasattr(loaded_bert, "float"):
            loaded_bert.float()


        # 4. Baca metadata konfigurasi config.json
        config_path = self.model_dir / f"{self.model_name}/config.json"
        if not config_path.exists():
            raise FileNotFoundError(f"File konfigurasi SBV2 tidak ditemukan: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            cfg_data = json.load(f)

        self._style2id = cfg_data.get("data", {}).get("style2id", {})
        self._spk2id = cfg_data.get("data", {}).get("spk2id", {})

        # Speaker diambil dari id pertama (jangan di-hardcode)
        if self._spk2id:
            self._default_speaker_id = next(iter(self._spk2id.values()))
        else:
            self._default_speaker_id = 0

        # Validasi style di EMOTION_STYLE terhadap style2id
        for em, val in EMOTION_STYLE.items():
            req_style = val.get("style", "Neutral")
            if req_style not in self._style2id:
                print(
                    f"[SBV2] Peringatan: style '{req_style}' untuk emosi '{em}' tidak ada di daftar model ({list(self._style2id.keys())}). Menggunakan 'Neutral'."
                )

        # 5. Inisialisasi model TTS
        model_path = self.model_dir / f"{self.model_name}/jvnv-F2_e166_s20000.safetensors"
        style_vec_path = self.model_dir / f"{self.model_name}/style_vectors.npy"

        if not model_path.exists():
            raise FileNotFoundError(f"File bobot model tidak ditemukan: {model_path}")
        if not style_vec_path.exists():
            raise FileNotFoundError(f"File vektor style tidak ditemukan: {style_vec_path}")

        print(f"[SBV2] Menginisialisasi TTSModel pada perangkat: {self._device}...")
        self._model = TTSModel(
            model_path=model_path,
            config_path=config_path,
            style_vec_path=style_vec_path,
            device=self._device,
        )

        if hasattr(self._model, "load") and callable(self._model.load):
            self._model.load()

        load_duration = time.perf_counter() - t_start
        self._ready = True

        # 6. Warm-up dua kalimat: pendek dan panjang (~40 karakter) agar inisialisasi lazy GPU
        #    tidak mengenai jawaban pertama pengguna
        warmup_style = {"style": "Neutral", "style_weight": 1.0, "length": 1.0}

        t_wu_short = time.perf_counter()
        self.synth("こんにちは", warmup_style)
        dur_wu_short = time.perf_counter() - t_wu_short

        t_wu_long = time.perf_counter()
        self.synth("バーチャルメモリとは、ハードディスクをRAMとして使う技術だよ。", warmup_style)
        dur_wu_long = time.perf_counter() - t_wu_long

        print(
            f"[SBV2] Model siap digunakan (device={self._device}). "
            f"Waktu muat: {load_duration:.2f}s, "
            f"Warm-up pendek: {dur_wu_short:.2f}s, "
            f"Warm-up panjang: {dur_wu_long:.2f}s"
        )

    def synth(self, text: str, params: dict | None = None) -> tuple[int, np.ndarray]:
        """Sintesis teks menjadi audio (sample_rate, audio_array) dengan proteksi thread lock."""
        if not self._ready or self._model is None:
            raise RuntimeError("SBV2Engine belum siap atau gagal dimuat.")

        from style_bert_vits2.constants import Languages

        p = params or {}
        # Validasi style
        style = p.get("style", "Neutral")
        if style not in self._style2id:
            print(f"[SBV2] Peringatan: style '{style}' tidak valid, fallback ke 'Neutral'.")
            style = "Neutral"

        raw_args = {
            "text": text,
            "language": Languages.JP,
            "speaker_id": self._default_speaker_id,
            "style": style,
            "style_weight": float(p.get("style_weight", 1.0)),
            "length": float(p.get("length", 1.0)),
            "sdp_ratio": float(p.get("sdp_ratio", 0.2)),
            "noise": float(p.get("noise", 0.6)),
            "noise_w": float(p.get("noise_w", 0.8)),
        }

        # Filter argumen infer menggunakan inspect.signature (parameter tak didukung dilewati + log)
        sig = inspect.signature(self._model.infer)
        filtered_args = {}
        for k, v in raw_args.items():
            if k in sig.parameters:
                filtered_args[k] = v
            else:
                print(f"[SBV2] Parameter '{k}' tidak didukung oleh infer(), dilewati.")

        with self._lock:
            sr, audio = self._model.infer(**filtered_args)

        return sr, audio

    @property
    def ready(self) -> bool:
        """Status kesiapan engine."""
        return self._ready

    @property
    def styles(self) -> list[str]:
        """Daftar style suara yang didukung model."""
        return list(self._style2id.keys())

    @property
    def device(self) -> str:
        """Perangkat inferensi aktif (cuda atau cpu)."""
        return self._device

    @property
    def lock(self) -> threading.Lock:
        """Lock inferensi sinkron."""
        return self._lock
