from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.models import VideoRequest
from app.services.gemini_client import generate_narration_script, generate_image_prompt
from app.services.tts_service import text_to_speech
from app.services.image_client import generate_image
from app.services.video_builder import build_video
from app.config import settings
import httpx
import logging
import os

logger = logging.getLogger(__name__)
router = APIRouter()


class VideoResponse(BaseModel):
    video_url: str
    script: str


async def _generate_image_prompts(source_text: str) -> list[str]:
    """Generate 1-2 image prompts representing key moments in the source text."""
    prompts = []
    
    prompt1 = await generate_image_prompt(source_text)
    prompts.append(prompt1)
    
    if len(source_text) > 200:
        second_text = source_text[len(source_text)//3:2*len(source_text)//3]
        prompt2 = await generate_image_prompt(second_text)
        if prompt2 != prompt1:
            prompts.append(prompt2)
    
    return prompts[:2]


@router.post("/video", response_model=VideoResponse)
async def generate_video(req: VideoRequest):
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
        audio_filename = await text_to_speech(script)
    except Exception:
        logger.exception("TTS generation failed")
        raise HTTPException(status_code=500, detail="Failed to generate audio from script.")
    
    audio_path = os.path.join(settings.temp_dir, "audio", audio_filename)
    
    try:
        image_prompts = await _generate_image_prompts(req.source_text)
    except Exception:
        logger.exception("Image prompt generation failed")
        raise HTTPException(status_code=500, detail="Failed to generate image prompts.")
    
    image_paths = []
    for prompt in image_prompts:
        try:
            img_filename = await generate_image(prompt)
            img_path = os.path.join(settings.temp_dir, "images", img_filename)
            image_paths.append(img_path)
        except Exception:
            logger.exception(f"Image generation failed for prompt: {prompt}")
            continue
    
    if not image_paths:
        raise HTTPException(status_code=500, detail="Failed to generate any images for the video.")
    
    try:
        video_filename = build_video(image_paths, audio_path)
    except Exception:
        logger.exception("Video build failed")
        raise HTTPException(status_code=500, detail="Failed to assemble the video.")
    
    video_url = f"/videos/{video_filename}"
    return VideoResponse(video_url=video_url, script=script)
