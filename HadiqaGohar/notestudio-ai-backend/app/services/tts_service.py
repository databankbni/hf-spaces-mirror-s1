import edge_tts
import uuid
import os
from app.config import settings

AUDIO_DIR = os.path.join(settings.temp_dir, "audio")


def _ensure_dir():
    os.makedirs(AUDIO_DIR, exist_ok=True)


async def text_to_speech(text: str) -> str:
    """Convert text to an MP3 file. Returns the filename (UUID-based)."""
    _ensure_dir()
    filename = f"{uuid.uuid4().hex}.mp3"
    output_path = os.path.join(AUDIO_DIR, filename)
    communicate = edge_tts.Communicate(text, settings.tts_voice)
    await communicate.save(output_path)
    return filename
