"""NghiTTS Engine - Vietnamese Text-to-Speech with Piper ONNX models."""

import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Optional

import numpy as np
import onnxruntime as ort
from piper import PiperVoice, SynthesisConfig
from vietnormalizer import VietnameseNormalizer

NGHITTS_MODELS_DIR = Path(__file__).parent / ".nghitts-models"


class NghiTTSEngine:
    """Load a NghiTTS/Piper model and generate Vietnamese speech."""

    def __init__(self, model_name: str = "ngochuyennew"):
        self.model_name = model_name
        self.model_path = NGHITTS_MODELS_DIR / f"{model_name}.onnx"
        self.config_path = NGHITTS_MODELS_DIR / f"{model_name}.onnx.json"

        if not self.model_path.exists():
            raise FileNotFoundError(f"NghiTTS model not found: {self.model_path}")
        if not self.config_path.exists():
            raise FileNotFoundError(f"NghiTTS config not found: {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)

        self.voice = PiperVoice.load(self.model_path, config_path=self.config_path)
        self.config = self.voice.config
        self.num_speakers = self.config.num_speakers
        self.sample_rate = self.config.sample_rate

        self.default_scales = np.array(
            [
                float(self.config.noise_scale),
                float(self.config.length_scale),
                float(self.config.noise_w_scale),
            ],
            dtype=np.float32,
        )

        self.normalizer = VietnameseNormalizer()

    def normalize_text(self, text: str) -> str:
        try:
            normalized = self.normalizer.normalize(text)
        except Exception:
            normalized = text

        if not normalized:
            return ""

        normalized = normalized.strip()
        normalized = normalized.replace("“", '"').replace("”", '"').replace("’", "'")
        normalized = normalized.replace("—", " - ").replace("–", " - ")
        normalized = normalized.replace("…", "...")
        normalized = re.sub(r"\s+", " ", normalized)
        normalized = re.sub(r"\s+([,.;:!?])", r"\1", normalized)
        normalized = normalized.strip()
        return normalized

    def generate_audio(self, text: str, speaker_id: int = 0, scales: Optional[list[float]] = None) -> np.ndarray:
        normalized = self.normalize_text(text)
        if not normalized or not normalized.strip():
            raise RuntimeError("NghiTTS generated no audio from empty text")

        if scales is None:
            scales = self.default_scales

        syn_config = SynthesisConfig(
            speaker_id=speaker_id if self.num_speakers > 1 else None,
            noise_scale=float(scales[0]),
            length_scale=float(scales[1]),
            noise_w_scale=float(scales[2]),
            normalize_audio=True,
        )

        audio_arrays = [chunk.audio_float_array for chunk in self.voice.synthesize(normalized, syn_config=syn_config)]
        if not audio_arrays:
            raise RuntimeError("NghiTTS generated no audio from text")

        return np.concatenate(audio_arrays)

    @staticmethod
    def audio_to_wav_bytes(audio_data: np.ndarray, sample_rate: int) -> bytes:
        import wave
        import tempfile

        audio_data = np.clip(audio_data, -1.0, 1.0)
        audio_int16 = (audio_data * 32767).astype(np.int16)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        with wave.open(tmp_path, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(audio_int16.tobytes())

        with open(tmp_path, "rb") as f:
            wav_bytes = f.read()

        Path(tmp_path).unlink(missing_ok=True)
        return wav_bytes
