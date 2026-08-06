"""Backend-agnostic pitch/tonic extraction interfaces.

A backend module must provide:
    extract_pitch(audio_path: str) -> tuple[np.ndarray, float]
        Returns (f0_hz, hop_s). Unvoiced frames are <= 0.
    extract_tonic(audio_path: str) -> float
        Returns tonic frequency in Hz.

`get_backend()` picks the best available backend at runtime: essentia on
Linux (production/WSL), rmvpe+histogram fallback elsewhere if installed.
"""

from types import ModuleType


def get_backend() -> ModuleType:
    try:
        from raagafinder.pitch import essentia_backend

        essentia_backend.assert_available()
        return essentia_backend
    except ImportError:
        pass
    try:
        from raagafinder.pitch import rmvpe_backend

        rmvpe_backend.assert_available()
        return rmvpe_backend
    except ImportError as exc:
        raise ImportError(
            "No pitch backend available. On Linux/WSL: pip install essentia. "
            "On native Windows: pip install rmvpe-onnx onnxruntime."
        ) from exc
