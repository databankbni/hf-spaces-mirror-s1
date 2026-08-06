"""RMVPE vocal-pitch backend (onnxruntime, CPU, works on Windows and Linux).

RMVPE extracts the VOCAL F0 directly from polyphonic mixtures (Interspeech
2023), making it a better fit than MELODIA for film songs / dense mixes where
MELODIA hops between voice, violin and flute. Tonic comes from the pure-numpy
pitch-histogram estimator (no drone assumption).
"""

import numpy as np

try:
    import soundfile as sf
    from rmvpe_onnx import RMVPE

    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

CONFIDENCE_THRESHOLD = 0.40
_model = None


def assert_available() -> None:
    if not _AVAILABLE:
        raise ImportError("rmvpe-onnx / soundfile not installed")


def _get_model():
    global _model
    if _model is None:
        _model = RMVPE()
    return _model


def extract_pitch(audio_path: str) -> tuple[np.ndarray, float]:
    assert_available()
    audio, sr = sf.read(str(audio_path), always_2d=False)
    t, freq, conf, _ = _get_model().predict(audio, sr)
    f0 = np.where(conf >= CONFIDENCE_THRESHOLD, freq, 0.0).astype(np.float32)
    hop = float(np.median(np.diff(t[: min(len(t), 5000)]))) if len(t) > 1 else 0.01
    return f0, hop


def extract_tonic(audio_path: str) -> float:
    """Histogram tonic from the vocal F0 track (no drone assumption)."""
    from raagafinder.pitch.tonic_hist import tonic_candidates

    f0, _ = extract_pitch(audio_path)
    cands = tonic_candidates(f0, top_k=1)
    if not cands:
        raise ValueError("no voiced content for tonic estimation")
    return cands[0]
