"""LangGraph single-node graph template.

Returns a predefined response. Replace logic and configuration as needed.
"""

from __future__ import annotations

from typing import Any, Dict

from utils.state import State
from utils.context import Context
from langgraph.graph import StateGraph
from langgraph.runtime import Runtime

import logging

from web.login import get_or_create_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def call_model(state: State, runtime: Runtime[Context]) -> Dict[str, Any]:
    """Process input and returns output.

    Can use runtime context to alter behavior.
    """
    # Reuse the shared supervisor instance (created from the login token).
    supervisor_agent = await get_or_create_agent("supervisor")

    logger.info(f"State:{state}")

    messages = state["messages"]
    content = ""

    async for stream in supervisor_agent.astream_events(
        {"messages": messages},
        version="v2"
    ):
        logger.debug(f"Stream:{stream}")
        if stream['event']=='on_chat_model_stream':
            chunk = stream['data']['chunk']
            chunk_content = chunk.content
            content += chunk_content           

    logger.info(f"Response:{content}")

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
