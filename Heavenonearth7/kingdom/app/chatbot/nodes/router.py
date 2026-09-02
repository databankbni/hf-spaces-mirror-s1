"""
Heaven on Earth CMS Backend — Intent Router Node

Classifies the user's intent via Groq LLM when the conversation is idle or
when the user signals they want to exit an active flow.

References
----------
- Req §7 (LangGraph Agent Graph), acceptance criteria 7.1–7.3
- Design § "LangGraph Agent Graph" → Node Responsibilities table
"""

from __future__ import annotations

import re

from langchain_core.messages import HumanMessage
from langchain_groq import ChatGroq

from app.chatbot.session import AgentState
from app.config import settings

# ---------------------------------------------------------------------------
# Exit keywords — any of these in the user message ends an active flow
# ---------------------------------------------------------------------------
_EXIT_PATTERN = re.compile(r"\b(cancel|stop|exit|quit)\b", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Keyword-based pre-classification — catches obvious intents without LLM call
# ---------------------------------------------------------------------------
_TESTIMONY_PATTERN = re.compile(
    r"\b(testimony|testify|testimon|share\s+(my\s+)?(story|experience|testimony)|"
    r"ምስክርነት|ምስክርነቴን)\b",
    re.IGNORECASE,
)
_PRAYER_PATTERN = re.compile(
    r"\b(pray(er)?(\s+request)?|prayer\s+request|submit\s+a?\s+pray|"
    r"ጸሎት|ጸሎቴን|ጸሎት\s+ጥያቄ)\b",
    re.IGNORECASE,
)
_PARTNERSHIP_PATTERN = re.compile(
    r"\b(partner(ship)?|volunteer|donate|donat(e|ion)|give\s+financ|financial(ly)?|"
    r"material\s+support|አጋርነት|ድጋፍ)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Intent classification prompt
# ---------------------------------------------------------------------------
_CLASSIFICATION_PROMPT = """You are an intent classifier for a church chatbot.
Classify the user message into exactly ONE of these intents:
- testimony (user wants to share a personal testimony or story of faith)
- prayer (user wants to submit a prayer request)
- partnership (user wants to explore partnership, volunteer, or give financially)
- qa (user is asking a question about the church or ministry)
- unknown (unclear or off-topic)

IMPORTANT: Respond with ONLY one lowercase word from the list above. No punctuation, no explanation, nothing else.

User message: {message}
Intent:"""


def _keyword_classify(text: str) -> str | None:
    """
    Fast keyword-based pre-classification before calling the LLM.

    Returns the intent string if a confident match is found, else None.
    """
    if _TESTIMONY_PATTERN.search(text):
        return "testimony"
    if _PRAYER_PATTERN.search(text):
        return "prayer"
    if _PARTNERSHIP_PATTERN.search(text):
        return "partnership"
    return None


def intent_router_node(state: AgentState) -> AgentState:
    """
    LangGraph node: route the conversation based on detected user intent.

    First tries fast keyword matching, then falls back to Groq LLM
    classification if no keyword match is found.

    If an action flow is currently active (``state["flow"] != "idle"``) and
    the user has NOT typed an exit keyword, the intent is kept equal to the
    active flow name (continuing slot-filling).

    Parameters
    ----------
    state:
        Current agent state.

    Returns
    -------
    AgentState
        Updated state with ``intent`` set.
    """
    # Find the last human message
    last_user_content = ""
    for message in reversed(state["messages"]):
        if isinstance(message, HumanMessage):
            last_user_content = str(message.content)
            break

    current_flow = state.get("flow", "idle") or "idle"

    # If in an active flow and no exit keyword → continue the flow
    if current_flow != "idle" and not _EXIT_PATTERN.search(last_user_content):
        return {**state, "intent": current_flow}

    # Try keyword classification first (no LLM needed)
    keyword_intent = _keyword_classify(last_user_content)
    if keyword_intent:
        new_flow = "idle" if _EXIT_PATTERN.search(last_user_content) else current_flow
        return {**state, "intent": keyword_intent, "flow": new_flow}

    # Fall back to Groq LLM classification
    llm = ChatGroq(
        model="groq/compound-mini",
        api_key=settings.groq_api_key,
        temperature=0,
    )

    prompt = _CLASSIFICATION_PROMPT.format(message=last_user_content)
    response = llm.invoke(prompt)
    raw_intent = str(response.content).strip().lower()

    # Extract just the first word in case the model returns extra text
    first_word = raw_intent.split()[0].rstrip(".,!?") if raw_intent.split() else ""

    # Normalise to one of the valid intents
    valid_intents = {"testimony", "prayer", "partnership", "qa", "unknown"}
    intent = first_word if first_word in valid_intents else "unknown"

    # If user typed an exit keyword, reset the flow to idle
    new_flow = "idle" if _EXIT_PATTERN.search(last_user_content) else current_flow

    return {**state, "intent": intent, "flow": new_flow}
