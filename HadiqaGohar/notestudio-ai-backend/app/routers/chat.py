from fastapi import APIRouter, HTTPException
from app.models import ChatRequest, ChatResponse
from app.services.gemini_client import chat_completion
from app.config import settings
import httpx
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if not settings.openrouter_api_key:
        raise HTTPException(
            status_code=500,
            detail="OPENROUTER_API_KEY is not configured. Please set it in your .env file.",
        )

    if not req.source_text.strip():
        raise HTTPException(status_code=400, detail="Source text cannot be empty.")

    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    try:
        answer = await chat_completion(req.source_text, req.question)
        return ChatResponse(answer=answer)
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        if status == 401:
            raise HTTPException(
                status_code=500,
                detail="Invalid API key. Please check your OPENROUTER_API_KEY.",
            )
        if status == 429:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Please try again in a moment.",
            )
        logger.exception("OpenRouter API error")
        raise HTTPException(
            status_code=502,
            detail=f"Upstream API error ({status}). Please try again later.",
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="The AI took too long to respond. Please try again.",
        )
    except Exception:
        logger.exception("Unexpected error in chat endpoint")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred. Please try again later.",
        )
