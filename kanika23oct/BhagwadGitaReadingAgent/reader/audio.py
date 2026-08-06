# ---------------------------------------------------------------------------
# reader/audio.py — Phase B.
#
# Resolve the on-disk mp3 paths for a verse. The durations themselves live
# in SQLite (written by build_audio.py); this module just maps a verse_id
# to its two audio files and reports whether they exist.
# ---------------------------------------------------------------------------

from pathlib import Path

from config import AUDIO_ENGLISH_DIR, AUDIO_SANSKRIT_DIR, AUDIO_HINDI_DIR


def sanskrit_audio_path(verse_id: str) -> Path:
    return AUDIO_SANSKRIT_DIR / f"{verse_id}.mp3"


def english_audio_path(verse_id: str) -> Path:
    return AUDIO_ENGLISH_DIR / f"{verse_id}.mp3"


def hindi_audio_path(verse_id: str) -> Path:
    return AUDIO_HINDI_DIR / f"{verse_id}.mp3"


def audio_exists(verse_id: str) -> bool:
    return sanskrit_audio_path(verse_id).exists() and english_audio_path(
        verse_id
    ).exists()
