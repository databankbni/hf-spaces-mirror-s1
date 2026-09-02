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


# Raw extraction is deterministic per file, so it may be memoized. The
# smart cascade re-analyzes the same request under a second model when the
# first is uncertain, and without this the forty-second melody extraction
# would run twice; with it the second model pays only for its own
# classification. Keyed by modification time as well as path because the
# app writes each upload to a fresh temporary file, and capped so a long
# session cannot hold every recording it ever saw.
_MEMO: dict = {}
_MEMO_MAX = 8


def _memo_key(path):
    import os

    return (str(path), os.path.getmtime(path))


def _memo_get(kind, path):
    return _MEMO.get((kind,) + _memo_key(path))


def _memo_put(kind, path, value):
    if len(_MEMO) >= 2 * _MEMO_MAX:
        for k in list(_MEMO)[:_MEMO_MAX]:
            del _MEMO[k]
    _MEMO[(kind,) + _memo_key(path)] = value
    return value


def _extract_pitch_uncached(audio_path: str) -> tuple[np.ndarray, float]:
    assert_available()
    audio = _load_audio(audio_path)
    melodia = estd.PredominantPitchMelodia(
        frameSize=FRAME_SIZE, hopSize=HOP_SIZE, sampleRate=SAMPLE_RATE
    )
    f0, _confidence = melodia(audio)
    return np.asarray(f0, dtype=np.float32), HOP_SIZE / SAMPLE_RATE


def _extract_tonic_uncached(audio_path: str) -> float:
    assert_available()
    audio = _load_audio(audio_path)
    return float(estd.TonicIndianArtMusic(sampleRate=SAMPLE_RATE)(audio))


def extract_pitch(audio_path: str) -> "tuple[np.ndarray, float]":
    hit = _memo_get("pitch", audio_path)
    if hit is not None:
        return hit
    return _memo_put("pitch", audio_path, _extract_pitch_uncached(audio_path))


def extract_tonic(audio_path: str) -> float:
    hit = _memo_get("tonic", audio_path)
    if hit is not None:
        return hit
    return _memo_put("tonic", audio_path, _extract_tonic_uncached(audio_path))
