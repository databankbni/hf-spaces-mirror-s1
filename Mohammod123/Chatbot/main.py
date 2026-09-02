"""API-first entry point for the multi-format RAG chatbot (FastAPI)."""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from src.data_loader import DataLoader
from src.embedding import EmbeddingPipeline
from src.guardrails import Guardrails
from src.hooks import HookManager
from src.memory import ConversationMemory
from src.metrics import RagMetrics
from src.middleware import RateLimitMiddleware
from src.schemas import ChatRequest, ChatResponse, SourceInfo
from src.search import RagBot
from src.tools import build_tools
from src.vector_store import VectorStoreManager

load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", PROJECT_ROOT / "data"))
CHROMA_DIR = Path(os.getenv("CHROMA_DIR", PROJECT_ROOT / "chroma_db"))
SCORE_THRESHOLD = float(os.getenv("RAG_SCORE_THRESHOLD", "0.0"))
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "20"))

# Comma-separated list of allowed browser origins for the chatbot frontend.
DEFAULT_CORS_ORIGINS = ",".join(
    [
        "http://127.0.0.1:5501",
        "https://demo.alloftech.site",
        
    ]
)
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",")
    if origin.strip()
]

hooks = HookManager()
metrics = RagMetrics()
metrics.bind(hooks)
guardrails = Guardrails()
memory = ConversationMemory()


def initialize_rag() -> RagBot:
    """Initialize embeddings, Chroma, tools, and index files on startup."""
    started_at = time.perf_counter()
    logger.info("Starting RAG initialization.")

    embedding_pipeline = EmbeddingPipeline()
    vector_store = VectorStoreManager(
        embeddings=embedding_pipeline.embeddings,
        persist_directory=CHROMA_DIR,
    )

    documents = DataLoader(DATA_DIR).load()
    chunks = embedding_pipeline.split_documents(documents)
    vector_store.add_documents(chunks)

    logger.info("RAG initialization completed in %.3fs.", time.perf_counter() - started_at)
    return RagBot(
        vector_store=vector_store,
        score_threshold=SCORE_THRESHOLD,
        tools=build_tools(vector_store),
        hooks=hooks,
    )


rag_bot = initialize_rag()


def chat(query: str, session_id: str | None = None) -> Iterator[str]:
    """Streaming chat function: guardrails, memory, RAG, and output sanitization."""
    session_id = session_id or uuid.uuid4().hex

    verdict = guardrails.check_input(query)
    if not verdict.allowed:
        hooks.emit("query_blocked", {"reason": verdict.reason})
        yield verdict.user_message
        return

    answer_parts: list[str] = []
    for token in rag_bot.answer(query, history=memory.get_history(session_id)):
        answer_parts.append(token)
        yield guardrails.sanitize_output(token)

    answer = guardrails.sanitize_output("".join(answer_parts)).strip()
    if answer:
        memory.append_exchange(session_id, query, answer)


app = FastAPI(
    title="AllOfTech Multi-Format Vector RAG Chatbot API",
    description=(
        "API-first RAG chatbot. Answers are grounded in the indexed PDF, CSV, "
        "and TXT documents."
    ),
    version="2.0.0",
)

app.add_middleware(RateLimitMiddleware, requests_per_minute=RATE_LIMIT_PER_MINUTE)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Session-Id"],
)


@app.api_route("/", methods=["GET", "HEAD"])
def root() -> dict[str, str]:
    return {
        "service": "AllOfTech RAG Chatbot API",
        "docs": "/docs",
        "chat_stream": "POST /chat/stream",
        "chat": "POST /chat",
        "metrics": "GET /metrics",
    }


@app.api_route("/health", methods=["GET", "HEAD"])
def health() -> dict[str, Any]:
    return {"status": "ok", "active_sessions": memory.active_sessions()}


@app.post("/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Stream the answer as plain text chunks.

    The session ID is returned in the `X-Session-Id` response header; send it back
    in the next request body to keep the conversation context.
    """
    session_id = request.session_id or uuid.uuid4().hex
    return StreamingResponse(
        chat(request.query, session_id),
        media_type="text/plain; charset=utf-8",
        headers={
            "X-Session-Id": session_id,
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
        },
    )


@app.post("/chat")
def chat_complete(request: ChatRequest) -> ChatResponse:
    """Return the full answer as JSON, including the retrieved sources."""
    session_id = request.session_id or uuid.uuid4().hex

    verdict = guardrails.check_input(request.query)
    if not verdict.allowed:
        hooks.emit("query_blocked", {"reason": verdict.reason})
        return ChatResponse(
            answer=verdict.user_message,
            session_id=session_id,
            blocked=True,
        )

    collector: dict[str, Any] = {}
    answer = "".join(
        rag_bot.answer(
            request.query,
            history=memory.get_history(session_id),
            collector=collector,
        )
    )
    answer = guardrails.sanitize_output(answer).strip()
    if answer:
        memory.append_exchange(session_id, request.query, answer)

    return ChatResponse(
        answer=answer,
        session_id=session_id,
        sources=[SourceInfo(**source) for source in collector.get("sources", [])],
    )


@app.delete("/sessions/{session_id}")
def clear_session(session_id: str) -> dict[str, Any]:
    """Forget a conversation (e.g. when the user clicks 'New chat')."""
    return {"cleared": memory.clear(session_id)}


@app.get("/metrics")
def get_metrics() -> dict[str, Any]:
    """RAG metrics: query counts, latencies, retrieval quality, guardrail blocks."""
    return metrics.snapshot()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "7860")),
    )
