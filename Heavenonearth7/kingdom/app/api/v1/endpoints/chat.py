"""
Heaven on Earth CMS Backend — Chat API Endpoint

Provides WebSocket (primary) and HTTP POST (fallback) endpoints for the
AI chatbot, plus an admin endpoint to trigger a manual knowledge-base refresh.

References
----------
- Req §12 (Chat API Endpoint), acceptance criteria 12.1–12.6
- Req §13 (Main App Integration), acceptance criteria 13.4
- Design § "Components and Interfaces" → "Component 2: Chat API Endpoint"
- Design § "Security & Rate Limiting"
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.chatbot.agent import chatbot_graph
from app.chatbot.sanitizer import sanitize_input
from app.chatbot.session import AgentState
from app.config import settings
from app.dependencies import get_current_admin, get_db
from app.models.admin import Admin
from app.schemas.chat import ChatRequest, ChatResponse

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])

# ---------------------------------------------------------------------------
# Shared per-IP sliding-window rate limiter (WebSocket + HTTP)
# Maps IP → list of message timestamps (float, monotonic seconds)
# ---------------------------------------------------------------------------
_ip_message_timestamps: dict[str, list[float]] = defaultdict(list)
_WINDOW_SECONDS = 60


def _check_rate_limit(ip: str) -> bool:
    """Return True if the IP has exceeded the rate limit. Records the request."""
    now = time.monotonic()
    cutoff = now - _WINDOW_SECONDS
    _ip_message_timestamps[ip] = [
        t for t in _ip_message_timestamps[ip] if t > cutoff
    ]
    if len(_ip_message_timestamps[ip]) >= settings.chatbot_rate_limit:
        return True
    _ip_message_timestamps[ip].append(now)
    return False


# ---------------------------------------------------------------------------
# Helper: build AgentState from session + new user message
# ---------------------------------------------------------------------------

def _build_state(session, message: str, language_override: str | None = None) -> AgentState:
    """Construct a fresh AgentState from the current ConversationSession."""
    new_messages = list(session.messages) + [HumanMessage(content=message)]
    state: AgentState = {
        "session_id": session.session_id,
        "messages": new_messages,
        "language": session.language,
        "intent": None,
        "flow": session.flow,
        "flow_step": session.flow_step,
        "collected_fields": dict(session.collected_fields),
        "missing_fields": list(session.missing_fields),
        "retrieved_context": None,
        "api_response": None,
        "error": None,
    }
    if language_override:
        state["language_override"] = language_override  # type: ignore[assignment]
    return state


# ---------------------------------------------------------------------------
# Helper: sync session back from final AgentState
# ---------------------------------------------------------------------------

def _sync_session(session_manager, session_id: str, final_state: AgentState) -> None:
    """Persist relevant fields from the final agent state back into the session."""
    session_manager.update(
        session_id,
        messages=list(final_state.get("messages", [])),
        language=final_state.get("language", "en"),
        flow=final_state.get("flow", "idle"),
        flow_step=final_state.get("flow_step", ""),
        collected_fields=dict(final_state.get("collected_fields") or {}),
        missing_fields=list(final_state.get("missing_fields") or []),
    )


# ---------------------------------------------------------------------------
# 9.4 + 9.5  WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/ws/{session_id}")
async def websocket_chat(websocket: WebSocket, session_id: str) -> None:
    """
    Primary WebSocket chat endpoint.

    Streams token-by-token responses from the LangGraph agent.
    Enforces per-IP rate limiting (settings.chatbot_rate_limit msgs / 60 s).
    """
    await websocket.accept()
    client_ip: str = websocket.client.host if websocket.client else "unknown"

    logger.info("ws_connected", session_id=session_id, ip=client_ip)

    try:
        while True:
            # Read JSON frame
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                logger.info("ws_disconnected", session_id=session_id)
                return

            # Rate limiting
            if _check_rate_limit(client_ip):
                logger.warning("ws_rate_limit_exceeded", ip=client_ip)
                await websocket.close(code=1008)
                return

            raw_message: str = data.get("message", "")
            language_override: str | None = data.get("language")

            # Sanitize
            clean_message = sanitize_input(raw_message)
            if not clean_message:
                continue

            # Get or create session
            session_manager = websocket.app.state.session_manager
            session = session_manager.get_or_create(session_id)

            # Build state
            state = _build_state(session, clean_message, language_override)

            # Stream through the graph
            full_response = ""
            final_state: AgentState = state

            try:
                # Use ainvoke to get correct final merged state, then stream
                # the response text character by character from the last AIMessage.
                # astream gives partial node states which can lose flow_step/flow
                # fields when confirmation_node runs before response_formatter.
                final_state = await chatbot_graph.ainvoke(state)

                # Extract the last AIMessage as the response
                from langchain_core.messages import AIMessage as _AIMsg
                all_msgs = final_state.get("messages", [])
                for msg in reversed(all_msgs):
                    if isinstance(msg, _AIMsg):
                        full_response = str(msg.content)
                        # Send as a single non-streaming frame
                        await websocket.send_json({
                            "message": full_response,
                            "is_final": False,
                        })
                        break

            except Exception as exc:
                logger.error("ws_agent_error", error=str(exc), session_id=session_id)
                await websocket.send_json({
                    "message": "An error occurred. Please try again.",
                    "is_final": True,
                    "session_id": session_id,
                    "language": session.language,
                    "flow_state": None,
                })
                continue

            # Sync session state
            _sync_session(session_manager, session_id, final_state)

            # Send final frame
            flow_state = {
                "flow": final_state.get("flow", "idle"),
                "step": final_state.get("flow_step", ""),
                "collected_fields": final_state.get("collected_fields") or {},
                "missing_fields": final_state.get("missing_fields") or [],
            }
            await websocket.send_json({
                "session_id": session_id,
                "message": full_response,
                "language": final_state.get("language", "en"),
                "flow_state": flow_state,
                "is_final": True,
            })

    except WebSocketDisconnect:
        logger.info("ws_disconnected", session_id=session_id)
    except Exception as exc:
        logger.error("ws_unexpected_error", error=str(exc), session_id=session_id)


# ---------------------------------------------------------------------------
# 9.6  HTTP POST fallback
# ---------------------------------------------------------------------------

@router.post("/message", response_model=ChatResponse)
async def http_chat(
    request: Request,
    body: ChatRequest,
) -> ChatResponse:
    """
    HTTP POST fallback for clients that cannot use WebSockets.
    Rate limited to settings.chatbot_rate_limit requests per minute per IP.
    """
    # Manual rate limiting (same sliding window as WebSocket)
    client_ip = request.client.host if request.client else "unknown"
    if _check_rate_limit(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please slow down.",
        )
    clean_message = sanitize_input(body.message)

    session_manager = request.app.state.session_manager
    session = session_manager.get_or_create(body.session_id)

    state = _build_state(session, clean_message, body.language)

    try:
        final_state: AgentState = await chatbot_graph.ainvoke(state)
    except Exception as exc:
        logger.error("http_chat_agent_error", error=str(exc), exc_info=True)
        return ChatResponse(
            session_id=body.session_id,
            message="An error occurred. Please try again.",
            language=session.language,
            flow_state=None,
            is_final=True,
        )

    _sync_session(session_manager, body.session_id, final_state)

    # Extract last assistant message
    response_text = ""
    all_messages = final_state.get("messages", [])
    logger.debug("http_chat_messages", count=len(all_messages),
                 types=[type(m).__name__ for m in all_messages])

    for msg in reversed(all_messages):
        content = getattr(msg, "content", None)
        if content and not isinstance(msg, HumanMessage):
            response_text = str(content)
            break

    logger.debug("http_chat_response", response_text=response_text[:100] if response_text else "(empty)")

    flow_state = {
        "flow": final_state.get("flow", "idle"),
        "step": final_state.get("flow_step", ""),
        "collected_fields": final_state.get("collected_fields") or {},
        "missing_fields": final_state.get("missing_fields") or [],
    }

    return ChatResponse(
        session_id=body.session_id,
        message=response_text,
        language=final_state.get("language", "en"),
        flow_state=flow_state,
        is_final=True,
    )


# ---------------------------------------------------------------------------
# Task 4.6  Admin refresh endpoint
# ---------------------------------------------------------------------------

@router.post("/admin/refresh")
async def admin_refresh(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    _admin: Annotated[Admin, Depends(get_current_admin)],
) -> dict:
    """
    Trigger an immediate knowledge-base refresh (admin only).
    Returns the refresh summary dict.
    """
    knowledge_base = request.app.state.knowledge_base
    summary = await knowledge_base.refresh_dynamic_content(db)
    logger.info("admin_refresh_triggered", **summary)
    return summary
