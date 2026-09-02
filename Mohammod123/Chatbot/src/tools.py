"""Internal helpers for the RAG chatbot (no user-facing tool names)."""

from __future__ import annotations

import os

from langchain_core.tools import BaseTool

_DEFAULT_CONTACT_INFO = (
    "To order your own custom RAG chatbot or any other AllOfTech service, contact AllOfTech:\n"
    "- Website: www.alloftech.site\n"
    "- Email: contact@alloftech.site\n"
    "- Facebook: https://www.facebook.com/AllOfTech.official\n"
    "The team will get back to you with a tailored proposal."
)


def get_contact_info() -> str:
    """Return AllOfTech contact and ordering details (configurable via env)."""
    return os.getenv("COMPANY_CONTACT_INFO", _DEFAULT_CONTACT_INFO)


def build_tools(_vector_store=None) -> list[BaseTool]:
    """Return an empty tool list.

    Tools were removed from the customer-facing demo because small models often leak
    internal function names into replies. Contact info lives in the system persona;
    service topics come from retrieval + persona.
    """
    return []
