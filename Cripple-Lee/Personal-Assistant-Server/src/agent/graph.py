"""LangGraph single-node graph template.

Returns a predefined response. Replace logic and configuration as needed.
"""

from __future__ import annotations

from typing import Any, Dict

from utils.state import State
from utils.context import Context
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph
from langgraph.runtime import Runtime

import logging

from web.login import get_or_create_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def call_model(
    state: State,
    runtime: Runtime[Context],
    config: RunnableConfig,
) -> Dict[str, Any]:
    """Process input and returns output.

    The supervisor agent is a shared singleton built with the server-wide
    ``HF_TOKEN`` env var (see ``web/login.py``).
    """
    # Reuse the shared supervisor instance.
    supervisor_agent = await get_or_create_agent("supervisor")

    logger.info(f"State:{state}")

    messages = state["messages"]
    content = ""

    # Depth of nested tool execution. While > 0 we are inside a subagent
    # (navigate/search) tool call, and any chat-model chunks belong to the
    # subagent — NOT to the supervisor's own answer. Tracking this prevents
    # subagent output from being interleaved/duplicated into the final text.
    tool_depth = 0

    # Token accounting: sum usage_metadata from EVERY chat-model chunk —
    # including subagent chunks — so the user is billed for all model calls
    # their run triggers (supervisor + navigate/search subagents).
    tokens_used = 0

    async for stream in supervisor_agent.astream_events(
        {"messages": messages},
        version="v2",
    ):
        logger.debug(f"Stream:{stream}")
        event = stream['event']

        if event == 'on_tool_start':
            tool_depth += 1
            continue
        if event == 'on_tool_end':
            tool_depth = max(0, tool_depth - 1)
            continue

        if event != 'on_chat_model_stream':
            continue

        chunk = stream['data']['chunk']

        # Accumulate token usage before any filtering so subagent and
        # tool-call chunks are billed too.
        usage = getattr(chunk, "usage_metadata", None)
        if usage:
            tokens_used += usage.get("total_tokens") or (
                (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)
            )

        # Ignore chunks produced by subagents running inside a tool call.
        if tool_depth > 0:
            continue

        # Skip chunks that are part of a tool call. Qwen emits raw tool-call
        # markup (e.g. `<function=...>` / `</function>`) as content tokens;
        # these carry tool-call metadata and must not be treated as
        # user-facing text.
        if getattr(chunk, "additional_kwargs", {}).get("tool_calls"):
            continue

        text = chunk.content
        if not text:
            continue

        # Defensive filter: drop any residual tool-markup fragments that
        # leaked into plain content (the source of the `se}</function>`
        # artifacts).
        if any(tok in text for tok in ("<function", "</function", "<tool", "</tool")):
            continue

        content += text

    logger.info(f"Response:{content}")

    # Bill the run's tokens to the authenticated user. The auth handler
    # (web/auth.py) injects the user into configurable before execution.
    # Aegra passes it as a User object (attribute access), while LangGraph
    # Platform passes a plain dict — handle both.
    if tokens_used > 0:
        user = (config.get("configurable") or {}).get("langgraph_auth_user")
        if user is not None and not isinstance(user, dict):
            user_id = getattr(user, "identity", None)
        else:
            user_id = (user or {}).get("identity")        
        # Skip billing for unauthenticated/anonymous runs (no DB user row).
        if user_id and user_id != "anonymous":
            try:
                from web import db  # local import to avoid a cycle at module load

                total = await db.add_token_usage(user_id, tokens_used)
                logger.info(
                    f"Recorded {tokens_used} tokens for user {user_id} "
                    f"(monthly total: {total})"
                )
            except Exception:
                # Never fail a completed run because accounting failed.
                logger.exception("Failed to record token usage")

    # Return only the new assistant message; the add_messages reducer appends
    # it to the persisted thread history.
    return {"messages": [{"role": "assistant", "content": content}]}

# Define the graph
graph = (
    StateGraph(State, context_schema=Context)
    .add_node(call_model)
    .add_edge("__start__", "call_model")
    .compile(name="New Graph")
)
