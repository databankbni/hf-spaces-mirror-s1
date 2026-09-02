"""
Heaven on Earth CMS Backend — Language Detection Node

Detects whether a user message is in English (en) or Amharic (am) based on
the ratio of Ethiopic Unicode characters (U+1200–U+137F) in the text.

References
----------
- Req §6 (Language Detection), acceptance criteria 6.1–6.2
- Design § "Bilingual Design (Amharic + English)" → Language Detection
"""

from __future__ import annotations

import re
from typing import Literal

from langchain_core.messages import HumanMessage

from app.chatbot.session import AgentState


def detect_language(text: str) -> Literal["en", "am"]:
    """
    Detect the language of *text* based on Ethiopic Unicode character ratio.

    Returns ``"am"`` if more than 15% of the characters in *text* fall in the
    Ethiopic Unicode block (U+1200–U+137F), otherwise returns ``"en"``.

    Parameters
    ----------
    text:
        Input text to analyse.

    Returns
    -------
    Literal["en", "am"]
        ``"am"`` for Amharic, ``"en"`` for English (default).
    """
    return (
        "am"
        if len(re.findall(r"[\u1200-\u137F]", text)) / max(len(text), 1) > 0.15
        else "en"
    )


def language_detection_node(state: AgentState) -> AgentState:
    """
    LangGraph node: detect the language of the last user message.

    If ``language_override`` is present in *state*, that value is used as the
    language and the key is removed from the returned state.  Otherwise
    ``detect_language`` is called on the last ``HumanMessage`` content.

    Parameters
    ----------
    state:
        The current agent state.

    Returns
    -------
    AgentState
        Updated state with ``language`` set.
    """
    # Check for an explicit language override (e.g. from the UI toggle)
    override = state.get("language_override")  # type: ignore[call-overload]
    if override:
        updates: dict = {"language": override}
        # Remove the override key so it doesn't persist across turns
        new_state = dict(state)
        new_state.pop("language_override", None)
        new_state["language"] = override
        return new_state  # type: ignore[return-value]

    # Find the last human message in the conversation history
    last_user_content = ""
    for message in reversed(state["messages"]):
        if isinstance(message, HumanMessage):
            last_user_content = message.content
            break

    detected = detect_language(str(last_user_content))
    return {**state, "language": detected}
