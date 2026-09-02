"""
Heaven on Earth CMS Backend — Knowledge Retrieval Node

Performs a pgvector similarity search for the last user message and stores
the top-k chunk contents in ``state["retrieved_context"]``.

References
----------
- Req §7 (LangGraph Agent Graph), acceptance criteria 7.4
- Design § "LangGraph Agent Graph" → Node Responsibilities table → Knowledge Retrieval
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from langchain_core.messages import HumanMessage

from app.chatbot.session import AgentState

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.chatbot.knowledge_base import KnowledgeBaseService

# ---------------------------------------------------------------------------
# Module-level references — set once at application startup via the setter
# ---------------------------------------------------------------------------
_knowledge_base: Optional["KnowledgeBaseService"] = None
_db_factory = None  # session factory (callable → AsyncSession)


def setup_knowledge_retrieval_node(
    kb: "KnowledgeBaseService",
    session_factory,
) -> None:
    """
    Inject the ``KnowledgeBaseService`` instance and the DB session factory.

    This must be called once during application startup before the graph is
    used.

    Parameters
    ----------
    kb:
        The initialised ``KnowledgeBaseService`` instance.
    session_factory:
        A callable that returns an ``AsyncSession`` (e.g. the app's
        ``async_session_factory``).
    """
    global _knowledge_base, _db_factory
    _knowledge_base = kb
    _db_factory = session_factory


async def knowledge_retrieval_node(state: AgentState) -> AgentState:
    """
    LangGraph node: retrieve the top-4 knowledge chunks most relevant to the
    last user message and store them as a single string in
    ``state["retrieved_context"]``.

    Parameters
    ----------
    state:
        Current agent state.

    Returns
    -------
    AgentState
        Updated state with ``retrieved_context`` set.
    """
    # Extract last human message
    last_user_content = ""
    for message in reversed(state["messages"]):
        if isinstance(message, HumanMessage):
            last_user_content = str(message.content)
            break

    if not last_user_content or _knowledge_base is None or _db_factory is None:
        return {**state, "retrieved_context": ""}

    async with _db_factory() as db:
        chunks = await _knowledge_base.query(last_user_content, db, k=4)

    context = "\n\n".join(chunk.content for chunk in chunks)
    return {**state, "retrieved_context": context}
