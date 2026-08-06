"""Essentia-based pitch/tonic extraction (Linux / WSL / HF Spaces).

Uses the same algorithm family that produced the training dataset's pitch
tracks: MELODIA predominant melody + TonicIndianArtMusic.
"""

import numpy as np

try:
    import essentia.standard as estd

    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

SAMPLE_RATE = 44100
FRAME_SIZE = 2048
HOP_SIZE = 128  # 128/44100 ~= 2.9 ms, Melodia default


def assert_available() -> None:
    if not _AVAILABLE:
        raise ImportError("essentia is not installed (Linux/WSL only)")


def _load_audio(audio_path: str) -> np.ndarray:
    loader = estd.MonoLoader(filename=str(audio_path), sampleRate=SAMPLE_RATE)
    return estd.EqualLoudness()(loader())


def extract_pitch(audio_path: str) -> tuple[np.ndarray, float]:
    assert_available()
    audio = _load_audio(audio_path)
    melodia = estd.PredominantPitchMelodia(
        frameSize=FRAME_SIZE, hopSize=HOP_SIZE, sampleRate=SAMPLE_RATE
    )
    f0, _confidence = melodia(audio)
    return np.asarray(f0, dtype=np.float32), HOP_SIZE / SAMPLE_RATE


def extract_tonic(audio_path: str) -> float:
    assert_available()
    audio = _load_audio(audio_path)
    return float(estd.TonicIndianArtMusic(sampleRate=SAMPLE_RATE)(audio))
