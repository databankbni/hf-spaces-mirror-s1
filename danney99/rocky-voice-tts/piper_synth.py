"""Piper TTS synth for the Rocky Voice Space. Text -> 16 kHz int16 mono WAV bytes."""
from __future__ import annotations
import io, wave, functools

SAMPLE_RATE = 16000
_VOICE_REPO = "rhasspy/piper-voices"
_VOICE_PATH = "en/en_US/lessac/low/en_US-lessac-low"

def get_sample_rate() -> int:
    return SAMPLE_RATE

@functools.lru_cache(maxsize=1)
def _voice():
    # Fetch the voice files directly from the HF hub (stable across piper-tts
    # versions; piper.download's API changed between 1.2 and 1.3).
    from piper import PiperVoice
    from huggingface_hub import hf_hub_download
    onnx_path = hf_hub_download(_VOICE_REPO, f"{_VOICE_PATH}.onnx")
    hf_hub_download(_VOICE_REPO, f"{_VOICE_PATH}.onnx.json")  # config lands next to the model
    return PiperVoice.load(onnx_path)

def synth(text: str) -> bytes:
    """Synthesize text to a complete WAV file (int16 mono 16 kHz)."""
    text = (text or "").strip()
    if not text:
        text = "..."
    voice = _voice()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        if hasattr(voice, "synthesize_wav"):  # piper-tts >= 1.3
            voice.synthesize_wav(text, wav)
        else:  # piper-tts 1.2 API
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            voice.synthesize(text, wav)
    return buf.getvalue()
