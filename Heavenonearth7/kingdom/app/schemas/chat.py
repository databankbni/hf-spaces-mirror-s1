"""
Heaven on Earth CMS Backend — Chat Schemas

Pydantic request/response models for the chatbot API endpoint.

References
----------
- Req §12 (Chat API Endpoint), acceptance criteria 12.1–12.3
- Design § "Components and Interfaces" → "Component 2: Chat API Endpoint"
"""

from __future__ import annotations

import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    """Incoming chat message from the frontend."""

    session_id: str = Field(
        description="UUID v4 session identifier (client-generated)."
    )
    message: str = Field(
        description="The user's text message.",
        min_length=1,
        max_length=2000,
    )
    language: Optional[Literal["en", "am"]] = Field(
        default=None,
        description="Explicit language override; None means auto-detect.",
    )

    @field_validator("session_id")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        try:
            parsed = uuid.UUID(v, version=4)
            if str(parsed) != v.lower():
                raise ValueError
        except (ValueError, AttributeError):
            raise ValueError("session_id must be a valid UUID v4 string.")
        return v


class ChatResponse(BaseModel):
    """Outgoing chat response to the frontend."""

    session_id: str = Field(description="The session UUID echoed back.")
    message: str = Field(description="The assistant's response text.")
    language: str = Field(description="Language used in the response: 'en' or 'am'.")
    flow_state: Optional[dict] = Field(
        default=None,
        description="Current action flow state (flow name, step, collected fields).",
    )
    is_final: bool = Field(
        description="True for the final response frame; False for streaming chunks.",
    )
