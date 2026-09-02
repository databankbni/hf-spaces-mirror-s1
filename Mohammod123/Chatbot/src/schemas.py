"""Pydantic message schemas shared by the API and the RAG pipeline."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """A single message in a conversation."""

    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    """Incoming chat request from the frontend."""

    query: str = Field(..., min_length=1, max_length=4000, description="The user question.")
    session_id: str | None = Field(
        default=None,
        max_length=64,
        description="Conversation session ID. Omit on first message; reuse the returned one after.",
    )


class SourceInfo(BaseModel):
    """A retrieved source document reference."""

    source: str
    score: float


class LeadState(BaseModel):
    """Current AllOfTech request draft for the chat session."""

    session_id: str
    status: Literal["collecting", "awaiting_confirmation", "submitted"]
    request_type: Literal["", "service", "meeting", "support", "general_contact"] = ""
    service: str = ""
    project_details: str = ""
    meeting_purpose: str = ""
    preferred_date: str = ""
    preferred_time: str = ""
    timezone_or_location: str = ""
    support_details: str = ""
    company_name: str = ""
    industry: str = ""
    website_url: str = ""
    main_goal: str = ""
    urgency: str = ""
    name: str = ""
    email: str = ""
    phone: str = ""
    budget: str = ""
    timeline: str = ""
    preferred_contact: str = ""
    submitted_at: float | None = None
    missing_fields: list[str] = []
    confirmation_required: bool = False


class EmailJSPayload(BaseModel):
    """Browser EmailJS payload for the frontend confirmation button."""

    public_key: str
    service_id: str
    template_id: str
    template_params: dict[str, str]


class ChatResponse(BaseModel):
    """Full (non-streaming) chat response."""

    answer: str
    session_id: str
    sources: list[SourceInfo] = []
    blocked: bool = False
    lead: LeadState | None = None
    emailjs: EmailJSPayload | None = None
