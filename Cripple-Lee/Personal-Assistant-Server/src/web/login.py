"""Custom FastAPI app for the LangGraph server.

Provides the `/login` endpoint which stores the Hugging Face token and lazily
instantiates (and caches) the supervisor, navigate, and search agents so they
can be referenced from any other Python module without re-creating them on
every request.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from utils import shared_state

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def get_or_create_agent(name: str) -> Any:
    """Return the cached agent instance, creating it on first use.

    Args:
        name: One of "supervisor", "navigate", or "search".

    Raises:
        ValueError: If no HF token has been provided via /login yet, or an
            unknown agent name is requested.
    """
    if name in shared_state.agents:
        return shared_state.agents[name]

    # Per-agent lock so concurrent requests don't build the same agent twice.
    lock = shared_state.locks.setdefault(name, asyncio.Lock())
    async with lock:
        if name in shared_state.agents:  # double-checked after acquiring the lock
            return shared_state.agents[name]

        if not shared_state.hf_token:
            raise ValueError(
                "Hugging Face token is not set. Call the /login endpoint first."
            )

        logger.info(f"Instantiating '{name}' agent with the logged-in HF token.")

        # Imported lazily to avoid circular imports between agent modules.
        if name == "supervisor":
            from agent.supervisor_agent import init_supervisor_agent

            agent = await init_supervisor_agent(shared_state.hf_token)
        elif name == "navigate":
            from agent.navigate_agent import init_navigate_agent

            agent = await init_navigate_agent(shared_state.hf_token)
        elif name == "search":
            from agent.search_agent import init_search_agent

            agent = await init_search_agent(shared_state.hf_token)
        else:
            raise ValueError(f"Unknown agent name: {name!r}")

        shared_state.agents[name] = agent
        return agent


app = FastAPI()

class LoginRequest(BaseModel):
    hf_token: str

@app.post("/login")
def login(request: LoginRequest):
    """Store the HF token from login and reset cached agents.

    If the token changes, previously created agents (which were built with the
    old token) are discarded so the next access re-instantiates them with the
    new token.
    """
    if request.hf_token != shared_state.hf_token:
        logger.info("HF token updated; clearing cached agent instances.")
        shared_state.agents.clear()

    shared_state.hf_token = request.hf_token

    return {"status": "ok"} 