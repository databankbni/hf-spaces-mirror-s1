"""
Heaven on Earth CMS Backend — Chatbot Startup

Initialises the SentenceTransformer embedding model, KnowledgeBaseService,
and SessionManager during FastAPI application startup.

The model is loaded in a thread-pool executor to avoid blocking the asyncio
event loop during startup.

References
----------
- Req §13 (Main App Integration), acceptance criteria 13.1–13.4
- Arch §13 "Deployment Architecture" → "Integration with Existing Backend"
"""

from __future__ import annotations

import asyncio

import structlog
from sentence_transformers import SentenceTransformer

from app.chatbot.knowledge_base import KnowledgeBaseService
from app.chatbot.session import SessionManager
from app.config import settings

logger = structlog.get_logger(__name__)


async def init_chatbot() -> tuple[KnowledgeBaseService, SessionManager]:
    """
    Initialise and return the core chatbot services.

    Loads the SentenceTransformer model off the event loop thread so startup
    does not block incoming requests.

    Returns
    -------
    tuple[KnowledgeBaseService, SessionManager]
        A ready-to-use knowledge base service and session manager.
    """
    logger.info("chatbot_startup_begin", model=settings.embedding_model)

    loop = asyncio.get_event_loop()
    model: SentenceTransformer = await loop.run_in_executor(
        None,
        lambda: SentenceTransformer(settings.embedding_model),
    )

    knowledge_base = KnowledgeBaseService(model)
    session_manager = SessionManager(ttl_minutes=settings.chat_session_ttl_minutes)

    logger.info("chatbot_startup_complete")
    return knowledge_base, session_manager
