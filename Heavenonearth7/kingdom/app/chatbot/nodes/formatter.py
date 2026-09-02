"""
Heaven on Earth CMS Backend — Response Formatter Node

Builds the final LLM response by combining the language-specific system
prompt, conversation history, and optional RAG context, then calls Groq
``groq/compound`` and appends the result to ``state["messages"]``.

For action flows (testimony/prayer/partnership), when the last message is
already an AIMessage prompt from the flow/confirmation/submission nodes,
the LLM call is skipped entirely so the bot reliably asks the next slot
question without the LLM overriding it.

References
----------
- Req §7 (LangGraph Agent Graph), acceptance criteria 7.6
- Design § "LangGraph Agent Graph" → Node Responsibilities table → Response Formatter
- Design § "Response Speed Architecture" → Groq model selection
"""

from __future__ import annotations

import asyncio
import logging

from groq import RateLimitError
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from app.chatbot.prompts import load_system_prompt
from app.chatbot.session import AgentState
from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Groq client — groq/compound with retry on 429 rate-limit errors
# ---------------------------------------------------------------------------

_llm = ChatGroq(
    model="groq/compound",
    api_key=settings.groq_api_key,
    temperature=0.7,
)

# Retry settings: waits 5s → 10s → 20s → 40s before giving up
_MAX_RETRIES = 4
_BASE_BACKOFF = 5.0  # seconds


def _trim_trailing_ai_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    """
    Remove any trailing AIMessages from *messages* so the list always ends
    with a HumanMessage before being sent to the LLM.
    """
    trimmed = list(messages)
    while trimmed and isinstance(trimmed[-1], AIMessage):
        trimmed.pop()
    return trimmed


def _last_message_is_flow_prompt(messages: list[BaseMessage]) -> bool:
    """
    Return True if the last message in *messages* is an AIMessage that was
    appended by a flow/confirmation/submission node (not by the formatter).

    When this is True the formatter should skip the LLM call and return the
    message as-is, so slot questions and confirmation prompts are delivered
    exactly as written rather than being overridden by the LLM.
    """
    if not messages:
        return False
    last = messages[-1]
    # If the last message is already an AI message (appended by flow/confirm/
    # submission/fallback nodes), there is no need to call the LLM again.
    return isinstance(last, AIMessage)


async def _invoke_with_retry(llm_messages: list[BaseMessage]) -> str:
    """
    Invoke the LLM, retrying with exponential backoff on 429 rate-limit errors.
    """
    last_exc: Exception | None = None

    for attempt in range(_MAX_RETRIES):
        try:
            response = await _llm.ainvoke(llm_messages)
            return str(response.content)
        except RateLimitError as exc:
            last_exc = exc
            wait = _BASE_BACKOFF * (2 ** attempt)
            logger.warning(
                "Groq rate limit hit (attempt %d/%d), retrying in %.0fs",
                attempt + 1, _MAX_RETRIES, wait,
            )
            await asyncio.sleep(wait)

    raise last_exc  # type: ignore[misc]


async def response_formatter_node(state: AgentState) -> AgentState:
    """
    LangGraph node: deliver the final assistant response.

    **For action flows** (testimony / prayer / partnership):
    If the last message is already an AIMessage (slot prompt, confirmation
    summary, or submission result appended by another node), the LLM call is
    skipped and that message is returned directly.  This ensures the bot asks
    slot questions reliably without the LLM overriding them.

    **For QA / fallback / post-confirmation**:
    Calls Groq with the full conversation history (system prompt + messages)
    and appends the response as a new AIMessage.

    Parameters
    ----------
    state:
        Current agent state.

    Returns
    -------
    AgentState
        Updated state with the assistant response in ``messages``.
    """
    messages = list(state.get("messages", []))

    # ------------------------------------------------------------------
    # Fast path: flow/confirmation/submission already appended a prompt.
    # Skip the LLM and return it directly.
    # ------------------------------------------------------------------
    if _last_message_is_flow_prompt(messages):
        logger.debug("response_formatter: skipping LLM — flow prompt already present")
        return {**state, "messages": messages}

    # ------------------------------------------------------------------
    # Slow path: need LLM response (QA, fallback, post-submit thanks, etc.)
    # ------------------------------------------------------------------
    language = state.get("language", "en")
    system_prompt_text = load_system_prompt(language)  # type: ignore[arg-type]

    retrieved_context = state.get("retrieved_context") or ""
    if retrieved_context:
        system_content = (
            f"{system_prompt_text}\n\n"
            f"[Relevant Context]\n{retrieved_context}"
        )
    else:
        system_content = system_prompt_text

    system_message = SystemMessage(content=system_content)

    # Strip trailing AIMessages so the LLM receives a conversation ending
    # with a user message (API requirement).
    history_for_llm = _trim_trailing_ai_messages(messages)

    llm_messages = [system_message] + history_for_llm

    content = await _invoke_with_retry(llm_messages)

    new_messages = messages + [AIMessage(content=content)]
    return {**state, "messages": new_messages}
