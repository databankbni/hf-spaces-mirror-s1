from contextlib import asynccontextmanager
import logging
import re

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import os
from difflib import get_close_matches
import uvicorn


logger = logging.getLogger(__name__)


def _sanitize_for_log(value: object, limit: int = 1000) -> str:
    text = str(value)
    text = re.sub(r"(?i)(bearer\s+|gsk_|grok_|api[_-]?key\s*[=:]\s*)\S+", r"\1[REDACTED]", text)
    return text[:limit]


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    top_k: int = Field(default=4, ge=1, le=10)


class ChatResponse(BaseModel):
    answer: str
    sources_used: int
    confidence: str  # "high", "medium", "low", "no_data"
    uses_cv_data: bool  # Explicit flag: is this based on CV or a refusal?


pipeline = None
pipeline_startup_error: str | None = None


GREETING_PATTERN = re.compile(
    r"^(hi|hey|hello|hiya|good\s+(morning|afternoon|evening)|morning|evening|yo|greetings)([.!?\s]*)$",
    re.IGNORECASE,
)

GREETING_WORDS = {
    "hi",
    "hey",
    "hello",
    "hiya",
    "yo",
    "greetings",
    "morning",
    "evening",
}


def normalize_greeting_token(token: str) -> str:
    """Normalize a token for greeting matching."""
    cleaned = re.sub(r"[^a-z]", "", token.lower())
    if not cleaned:
        return ""

    # Collapse repeated letters so elongated greetings like "heyyy" still match.
    return re.sub(r"(.)\1+", r"\1", cleaned)


def token_looks_like_greeting(token: str) -> bool:
    normalized = normalize_greeting_token(token)
    if not normalized:
        return False

    if normalized in GREETING_WORDS:
        return True

    if len(normalized) <= 5:
        return bool(get_close_matches(normalized, GREETING_WORDS, n=1, cutoff=0.8))

    return False


def is_greeting_message(question: str) -> bool:
    """Return True for short salutations that should not hit CV retrieval."""
    normalized = re.sub(r"\s+", " ", question.strip())
    if GREETING_PATTERN.match(normalized):
        return True

    words = normalized.split()
    if not words or len(words) > 4:
        return False

    if token_looks_like_greeting(words[0]):
        return True

    return len(words) == 1 and token_looks_like_greeting(words[0])


def build_greeting_response(question: str) -> ChatResponse:
    """Return a friendly, local response for greetings."""
    name = "Noor's AI assistant"
    lowered = re.sub(r"\s+", " ", question.strip()).lower()

    if lowered.startswith("good morning"):
        message = f"Good morning! I'm {name}. Ask me anything about her projects, publications, experience, or skills."
    elif lowered.startswith("good afternoon"):
        message = f"Good afternoon! I'm {name}. Ask me anything about her projects, publications, experience, or skills."
    elif lowered.startswith("good evening"):
        message = f"Good evening! I'm {name}. Ask me anything about her projects, publications, experience, or skills."
    else:
        message = f"Hi! I'm {name}. Ask me anything about her projects, publications, experience, or skills."

    return ChatResponse(
        answer=message,
        sources_used=0,
        confidence="low",
        uses_cv_data=False,
    )

def initialize_pipeline() -> None:
    global pipeline, pipeline_startup_error

    try:
        # Import inside guarded block so missing deps/import errors don't crash app startup.
        from rag_pipeline import CVRAGPipeline

        pipeline = CVRAGPipeline()
        pipeline_startup_error = pipeline.readiness_issue
    except Exception as exc:
        pipeline = None
        pipeline_startup_error = f"{exc.__class__.__name__}: {exc}"


def ensure_pipeline_initialized() -> None:
    global pipeline

    if pipeline is None and pipeline_startup_error is None:
        initialize_pipeline()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    print("✅ API is starting up...")
    initialize_pipeline()

    if pipeline is None:
        print("⚠️ CV Pipeline failed to initialize.")
        print(f"⚠️ Startup error: {pipeline_startup_error}")
    else:
        print(f"✅ CV Pipeline Ready: {pipeline.is_ready}")
        print(f"✅ Chunks Loaded: {pipeline.chunk_count}")
        if pipeline_startup_error:
            print(f"⚠️ Readiness issue: {pipeline_startup_error}")

    yield


app = FastAPI(
    title="Portfolio CV RAG API",
    version="2.0.0",
    description="High-accuracy RAG API that answers questions about the portfolio owner using CV context. "
                "Prioritizes factual correctness over speculative answers.",
    lifespan=lifespan,
)


@app.get("/")
def root() -> dict:
    """Root endpoint - confirms API is running."""
    return {
        "message": "Portfolio CV RAG API is running",
        "docs_url": "/docs",
        "health_url": "/health",
        "chat_url": "/chat"
    }


@app.get("/health")
def health() -> dict:
    """Health check endpoint for deployment platforms."""
    ensure_pipeline_initialized()
    is_ready = bool(pipeline and pipeline.is_ready)
    return {
        "status": "ok" if is_ready else "degraded",
        "cv_loaded": is_ready,
        "chunks": pipeline.chunk_count if pipeline else 0,
        "model": pipeline.model_name if pipeline else None,
        "mode": "strict_accuracy",
        "min_relevance_threshold": 0.05,
        "startup_error": pipeline_startup_error or (None if is_ready else "Pipeline has not been initialized yet."),
    }


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty or whitespace only.")

    if is_greeting_message(request.question):
        return build_greeting_response(request.question)

    ensure_pipeline_initialized()

    if not pipeline or not pipeline.is_ready:
        details = "CV knowledge base is not ready. Check CV_PATH, GROQ_API_KEY, and restart the API."
        if pipeline_startup_error:
            details = f"{details} Startup error: {pipeline_startup_error}"
        raise HTTPException(
            status_code=503,
            detail=details,
        )

    try:
        answer, source_count = pipeline.answer_question(request.question, top_k=request.top_k)
    except RuntimeError as exc:
        status_code = getattr(exc, "status_code", None)
        upstream_url = getattr(exc, "upstream_url", "https://api.groq.com/openai/v1")
        response_body = getattr(exc, "response_body", None)
        logger.exception(
            "Chat upstream failure service=Groq url=%s status=%s body=%s",
            upstream_url,
            status_code or "unknown",
            _sanitize_for_log(response_body or str(exc)),
        )
        if str(exc).startswith("Missing GROQ_API_KEY"):
            raise HTTPException(
                status_code=503,
                detail=str(exc),
            ) from exc
        if status_code == 413:
            raise HTTPException(
                status_code=413,
                detail="Question and CV context exceed the upstream model request limit.",
            ) from exc
        if status_code == 429:
            raise HTTPException(
                status_code=429,
                detail="The AI service rate limit was reached. Please try again later.",
            ) from exc
        if status_code in {401, 403}:
            raise HTTPException(
                status_code=503,
                detail="The AI service rejected the configured credentials or model access.",
            ) from exc
        if getattr(exc, "is_timeout", False):
            raise HTTPException(
                status_code=504,
                detail="The AI service timed out while generating a response.",
            ) from exc
        raise HTTPException(
            status_code=502,
            detail="The AI service failed while generating a response.",
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected /chat failure: %s", _sanitize_for_log(str(exc)))
        raise HTTPException(
            status_code=502,
            detail="Unexpected failure while generating a response.",
        ) from exc
    
    # Determine confidence and whether this is CV-based data
    # Refusal patterns indicate low/no confidence
    refusal_patterns = [
        "i don't have",
        "not mentioned in the cv",
        "this isn't mentioned",
        "information is not available",
        "i couldn't find",
        "no information",
        "would you like to ask",
    ]
    
    is_refusal = any(pattern in answer.lower() for pattern in refusal_patterns)
    
    if is_refusal:
        confidence = "no_data" if "i don't have" in answer.lower() else "low"
        uses_cv = False
    elif source_count >= 2:
        confidence = "high"
        uses_cv = True
    elif source_count == 1:
        confidence = "medium"
        uses_cv = True
    else:
        confidence = "low"
        uses_cv = False
    
    return ChatResponse(
        answer=answer,
        sources_used=source_count,
        confidence=confidence,
        uses_cv_data=uses_cv,
    )


# Production entry point - respects PORT environment variable
if __name__ == "__main__":
    port = int(os.getenv("PORT", 7860))
    host = os.getenv("HOST", "0.0.0.0")
    
    print(f"🚀 Starting API server on {host}:{port}")
    uvicorn.run(
        "app:app",
        host=host,
        port=port,
        reload=os.getenv("RELOAD", "false").lower() == "true",
        log_level="info"
    )
