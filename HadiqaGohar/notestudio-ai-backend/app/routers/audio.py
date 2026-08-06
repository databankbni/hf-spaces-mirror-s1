from fastapi import APIRouter, HTTPException
from app.models import AudioRequest, AudioResponse
from app.services.gemini_client import generate_narration_script
from app.services.tts_service import text_to_speech
from app.config import settings
import httpx
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/audio", response_model=AudioResponse)
async def audio_overview(req: AudioRequest):
    if not settings.openrouter_api_key:
        raise HTTPException(
            status_code=500,
            detail="OPENROUTER_API_KEY is not configured.",
        )

    if not req.source_text.strip():
        raise HTTPException(status_code=400, detail="Source text cannot be empty.")

    try:
        script = await generate_narration_script(req.source_text)
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        if status == 401:
            raise HTTPException(status_code=500, detail="Invalid API key.")
        if status == 429:
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again shortly.")
        logger.exception("OpenRouter API error during script generation")
        raise HTTPException(status_code=502, detail=f"Script generation failed ({status}).")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Script generation timed out.")
    except Exception:
        logger.exception("Unexpected error during script generation")
        raise HTTPException(status_code=500, detail="Failed to generate narration script.")

    try:
        filename = await text_to_speech(script)
    except Exception:
        logger.exception("TTS generation failed")
        raise HTTPException(status_code=500, detail="Failed to generate audio from script.")

    audio_url = f"/audio/{filename}"
    return AudioResponse(audio_url=audio_url, script=script)
