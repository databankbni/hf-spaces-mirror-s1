from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.models import ImageRequest
from app.services.gemini_client import generate_image_prompt
from app.services.image_client import generate_image
from app.config import settings
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


class ImageResponse(BaseModel):
    image_url: str
    prompt: str


@router.post("/image", response_model=ImageResponse)
async def generate_image_endpoint(req: ImageRequest):
    if not req.source_text.strip():
        raise HTTPException(status_code=400, detail="Source text cannot be empty.")

    try:
        prompt = await generate_image_prompt(req.source_text)
    except Exception:
        logger.exception("Failed to generate image prompt")
        raise HTTPException(status_code=500, detail="Failed to generate image prompt.")

    try:
        filename = await generate_image(prompt)
    except Exception:
        logger.exception("Image generation failed")
        raise HTTPException(status_code=500, detail="Image generation failed. Please try again.")

    image_url = f"/images/{filename}"
    return ImageResponse(image_url=image_url, prompt=prompt)
