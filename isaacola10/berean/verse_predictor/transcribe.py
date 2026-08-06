"""Speech-to-text wrapper using faster-whisper (runs locally, no API key).

Accepts a 16 kHz mono float32 numpy array (what record.py produces) so we
never need ffmpeg for live mic input. Pass a file path to transcribe an
audio file instead (ffmpeg needed for compressed formats like mp3).

Tuned for accent robustness: a larger multilingual model, voice-activity
filtering to strip noise/silence, temperature fallback so hard audio still
decodes, and a biblical initial prompt to bias toward scripture wording.
"""
import os

import numpy as np

# "small" handles diverse accents far better than "base"; override with
# ASR_MODEL (e.g. "medium" for best accuracy, "base"/"tiny" for speed).
DEFAULT_MODEL = os.environ.get("ASR_MODEL", "small")
SAMPLE_RATE = 16000

# Bias decoding toward scripture so verse wording is recognised more reliably.
INITIAL_PROMPT = (
    "A spoken Bible verse, scripture passage, or reference such as "
    "John 3:16, Psalm 23, or Romans 8:28."
)

# Robust decode options: VAD removes non-speech, temperature fallback retries
# hard audio, larger beam improves accuracy across accents.
DECODE_OPTS = dict(
    beam_size=5,
    best_of=5,
    temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
    condition_on_previous_text=False,
    vad_filter=True,
    vad_parameters=dict(min_silence_duration_ms=300),
    initial_prompt=INITIAL_PROMPT,
)

_model_cache = {}


def get_model(name: str = DEFAULT_MODEL):
    if name not in _model_cache:
        from faster_whisper import WhisperModel

        print(f"Loading Whisper model '{name}' (first time downloads it)...")
        # int8 keeps it light and fast on CPU.
        _model_cache[name] = WhisperModel(name, device="cpu", compute_type="int8")
    return _model_cache[name]


def _join(segments) -> str:
    return " ".join(seg.text.strip() for seg in segments).strip()


def _lang(language: str | None):
    # "auto" (or None) lets Whisper detect the spoken language.
    return None if not language or language == "auto" else language


def transcribe_array(
    audio: np.ndarray, model_name: str = DEFAULT_MODEL, language: str | None = "en"
) -> str:
    """audio: float32 mono samples at 16 kHz, range roughly [-1, 1]."""
    model = get_model(model_name)
    audio = np.asarray(audio, dtype=np.float32).flatten()
    segments, _ = model.transcribe(audio, language=_lang(language), **DECODE_OPTS)
    return _join(segments)


def transcribe_file(
    path: str, model_name: str = DEFAULT_MODEL, language: str | None = "en"
) -> str:
    """Transcribe an audio file (ffmpeg needed for mp3 and similar)."""
    model = get_model(model_name)
    segments, _ = model.transcribe(path, language=_lang(language), **DECODE_OPTS)
    return _join(segments)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="audio file to transcribe")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()
    print(transcribe_file(args.file, args.model))
