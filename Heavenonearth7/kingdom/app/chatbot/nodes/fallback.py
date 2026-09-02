"""
Heaven on Earth CMS Backend — Fallback Node

Appends a language-appropriate clarification message when the agent cannot
determine the user's intent.

References
----------
- Req §7 (LangGraph Agent Graph), acceptance criteria 7.5
- Design § "LangGraph Agent Graph" → Node Responsibilities table → Fallback
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from app.chatbot.session import AgentState

_FALLBACK_EN = (
    "I'm here to help! You can:\n"
    "• Share a Testimony\n"
    "• Submit a Prayer Request\n"
    "• Explore Partnership\n"
    "• Ask a question about Heaven on Earth Kingdom Family Ministries\n\n"
    "What would you like to do?"
)

_FALLBACK_AM = (
    "ልረዳዎ ዝግጁ ነኝ! መምረጥ የሚፈልጉት፡\n"
    "• ምስክርነት ለማካፈል\n"
    "• ጸሎት ለማቅረብ\n"
    "• አጋርነት ለማሰስ\n"
    "• ስለ ሰማይ ላይ ምድር መንግሥት ቤተሰብ አገልግሎቶች ጥያቄ ለመጠየቅ\n\n"
    "ምን ማድረግ ይፈልጋሉ?"
)


def fallback_node(state: AgentState) -> AgentState:
    """
    LangGraph node: append a clarification message when intent is unknown.

    Parameters
    ----------
    state:
        Current agent state.

    Returns
    -------
    AgentState
        Updated state with the clarification ``AIMessage`` appended to
        ``messages``.
    """
    language = state.get("language", "en")
    message_text = _FALLBACK_AM if language == "am" else _FALLBACK_EN

    new_messages = list(state["messages"]) + [AIMessage(content=message_text)]
    return {**state, "messages": new_messages}
