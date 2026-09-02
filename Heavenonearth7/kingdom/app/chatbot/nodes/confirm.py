"""
Heaven on Earth CMS Backend — Confirmation Node

Presents a bilingual summary of all collected slot values and asks the user
to confirm (Yes) or cancel (No) before the submission node posts to the API.

Also provides ``confirm_decision_router``, the conditional edge function used
by the LangGraph graph to decide whether to proceed to submission, cancel, or
keep waiting.

References
----------
- Req §8 (Conversational Action Flows), acceptance criteria 8.3–8.7
- Design § "Conversational Action Flows" → confirmation message templates
- Design § "Correctness Properties" → Property 13
"""

from __future__ import annotations

import structlog
from langchain_core.messages import AIMessage, HumanMessage

from app.chatbot.session import AgentState

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Confirmation prompts
# ---------------------------------------------------------------------------

_SUMMARY_HEADER: dict[str, str] = {
    "en": "📋 Here's a summary of your submission:",
    "am": "📋 የርስዎ መረጃ ማጠቃለያ:",
}

_CONFIRM_PROMPT: dict[str, str] = {
    "en": "Please reply **Yes** to submit or **No** to cancel.",
    "am": "እባክዎ **አዎ** ብለው ሊልኩ ወይም **አይ** ብለው ሊሰርዙ ይችላሉ።",
}

# ---------------------------------------------------------------------------
# Affirmative / negative keyword sets used by confirm_decision_router
# ---------------------------------------------------------------------------

_YES_WORDS: frozenset[str] = frozenset({
    "yes", "yeah", "yep", "ok", "okay", "sure", "confirm", "submit",
    "አዎ", "አዎ።", "aha",
})

_NO_WORDS: frozenset[str] = frozenset({
    "no", "nope", "cancel", "stop", "quit", "abort", "አይ", "አይ።",
})


# ---------------------------------------------------------------------------
# confirmation_node
# ---------------------------------------------------------------------------


async def confirmation_node(state: AgentState) -> AgentState:
    """
    Format a bilingual key-value summary from ``state["collected_fields"]``
    and append it as an ``AIMessage`` asking the user to confirm or cancel.

    Sets ``state["flow_step"] = "awaiting_confirm"`` before returning so
    subsequent calls to :func:`confirm_decision_router` can inspect the last
    user reply.

    If ``flow_step`` is already ``"awaiting_confirm"``, the user has replied
    to a previous summary — skip re-printing it and pass through unchanged so
    ``confirm_decision_router`` can dispatch to submission or cancellation.

    Parameters
    ----------
    state:
        Current LangGraph agent state.

    Returns
    -------
    AgentState
        State with updated ``messages`` and ``flow_step``.
    """
    # Already waiting for a confirm/cancel reply — don't re-print the summary.
    # confirm_decision_router will handle the routing based on the user's reply.
    if state.get("flow_step") == "awaiting_confirm":
        logger.debug(
            "confirmation_node: already awaiting_confirm — passing through",
            flow=state.get("flow"),
        )
        return state

    language: str = state.get("language", "en")
    collected_fields: dict = state.get("collected_fields") or {}
    messages = list(state.get("messages") or [])

    # Build the summary text
    header = _SUMMARY_HEADER.get(language, _SUMMARY_HEADER["en"])
    lines = [header, ""]

    for key, value in collected_fields.items():
        # Prettify the field name (e.g. "partnership_type" → "Partnership type")
        pretty_key = key.replace("_", " ").capitalize()
        lines.append(f"• **{pretty_key}**: {value}")

    lines.append("")
    lines.append(_CONFIRM_PROMPT.get(language, _CONFIRM_PROMPT["en"]))

    summary_text = "\n".join(lines)
    messages.append(AIMessage(content=summary_text))

    logger.debug(
        "confirmation_node: summary sent",
        flow=state.get("flow"),
        fields=list(collected_fields.keys()),
    )

    return {
        **state,
        "flow_step": "awaiting_confirm",
        "messages": messages,
    }


# ---------------------------------------------------------------------------
# confirm_decision_router
# ---------------------------------------------------------------------------


def confirm_decision_router(state: AgentState) -> str:
    """
    Conditional edge function: inspect the last user message and decide
    whether the user confirmed, cancelled, or gave an unclear answer.

    Returns
    -------
    str
        ``"confirmed"``, ``"cancelled"``, or ``"awaiting"``.
    """
    # Only route once we're in the awaiting_confirm step
    flow_step = state.get("flow_step", "")
    if flow_step != "awaiting_confirm":
        return "awaiting"

    # Find the last human message
    last_human: str | None = None
    for msg in reversed(state.get("messages") or []):
        if isinstance(msg, HumanMessage):
            last_human = msg.content
            break

    if last_human is None:
        return "awaiting"

    normalised = last_human.strip().lower()

    # Check word-by-word to handle sentences like "yes, please submit"
    words = set(normalised.replace(",", " ").replace(".", " ").split())

    if words & _YES_WORDS:
        return "confirmed"
    if words & _NO_WORDS:
        return "cancelled"
    return "awaiting"
