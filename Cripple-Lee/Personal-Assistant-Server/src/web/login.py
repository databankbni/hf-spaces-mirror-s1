"""Custom FastAPI app for the LangGraph server.

Provides the ``/auth/signup`` and ``/auth/login`` endpoints. Signup creates a
row in the Postgres ``users`` table (see ``db/schema.sql``); login verifies
the bcrypt password hash and returns an HS256 JWT that the
``langgraph_sdk.Auth`` handler in ``web/auth.py`` validates on every request.

Also lazily instantiates (and caches) the supervisor, navigate, and search
agents **per user**, keyed by the authenticated user's id, so each user's
agents are built with their own Hugging Face token.
"""

from __future__ import annotations

import asyncio
import importlib
import os
from contextlib import asynccontextmanager
from typing import Any, Optional

import bcrypt
import jwt
from asyncpg import UniqueViolationError
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from utils import shared_state
from web import db
from web.auth import JWT_ALGORITHM, JWT_SECRET, MONTHLY_TOKEN_LIMIT, create_access_token

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Server-wide Hugging Face token, read once from the environment. All agents
# are built with this shared token.
HF_TOKEN = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACEHUB_API_TOKEN")
if not HF_TOKEN:
    raise RuntimeError(
        "HF_TOKEN (or HUGGINGFACEHUB_API_TOKEN) environment variable is required"
    )

async def _async_import(module_path: str) -> Any:
    """Import a module in a worker thread so it doesn't block the event loop."""
    return await asyncio.to_thread(importlib.import_module, module_path)

async def get_or_create_agent(name: str) -> Any:
    """Return the cached agent instance, creating it on first use.

    Agents are shared singletons built with the server-wide ``HF_TOKEN`` env
    var, so they are keyed by agent name only.

    Args:
        name: One of "supervisor", "navigate", or "search".

    Raises:
        ValueError: If an unknown agent name is requested.
    """
    if name in shared_state.agents:
        return shared_state.agents[name]

    # Per-agent lock so concurrent requests don't build the same agent twice.
    lock = shared_state.locks.setdefault(name, asyncio.Lock())
    async with lock:
        if name in shared_state.agents:  # double-checked after acquiring the lock
            return shared_state.agents[name]

        logger.info(f"Instantiating '{name}' agent with the server HF token.")

        # Imported lazily (and off the event loop) to avoid circular imports
        # between agent modules.
        if name == "supervisor":
            module = await _async_import("agent.supervisor_agent")
            agent = await module.init_supervisor_agent(HF_TOKEN)
        elif name == "navigate":
            module = await _async_import("agent.navigate_agent")
            agent = await module.init_navigate_agent(HF_TOKEN)
        elif name == "search":
            module = await _async_import("agent.search_agent")
            agent = await module.init_search_agent(HF_TOKEN)
        else:
            raise ValueError(f"Unknown agent name: {name!r}")

        shared_state.agents[name] = agent
        return agent


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Close the DB pool on shutdown.

    Aegra's route merger cannot merge ``on_startup``/``on_shutdown`` handlers,
    so cleanup must live in a lifespan context manager instead.
    """
    yield
    await db.close_pool()


app = FastAPI(lifespan=lifespan)


class SignupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    display_name: Optional[str] = None
    email: Optional[str] = None

SignupRequest.model_rebuild()

class LoginRequest(BaseModel):
    username: str
    password: str

LoginRequest.model_rebuild()

def _public_user(user: dict[str, Any]) -> dict[str, Any]:
    """Shape of the user object returned to the client (never the hash)."""
    return {
        "id": str(user["id"]),
        "username": user["username"],
        "display_name": user.get("display_name") or user["username"],
        "role": user.get("role", "user"),
    }


@app.post("/auth/signup", status_code=201)
async def signup(request: SignupRequest):
    """Create a new account and return an access token."""
    password_hash = await asyncio.to_thread(
        bcrypt.hashpw, request.password.encode(), bcrypt.gensalt()
    )
    try:
        user = await db.create_user(
            username=request.username,
            password_hash=password_hash.decode(),
            display_name=request.display_name,
            email=request.email,
        )
    except UniqueViolationError:
        raise HTTPException(status_code=409, detail="Username or email already taken")

    token = create_access_token(user)
    return {"access_token": token, "token_type": "bearer", "user": _public_user(user)}


@app.post("/auth/login")
async def login(request: LoginRequest):
    """Verify credentials and return an access token."""
    user = await db.get_user_by_username(request.username)
    if not user or not user.get("is_active", True):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    ok = await asyncio.to_thread(
        bcrypt.checkpw,
        request.password.encode(),
        user["password_hash"].encode(),
    )
    if not ok:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_access_token(user)
    return {"access_token": token, "token_type": "bearer", "user": _public_user(user)}


def _user_id_from_authorization(authorization: Optional[str]) -> str:
    """Extract the user id (``sub``) from a bearer JWT, or raise 401."""
    token = (authorization or "").replace("Bearer ", "").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
    return payload["sub"]


@app.get("/usage")
async def get_usage(authorization: Optional[str] = Header(default=None)):
    """Return the caller's current-month token usage and limit.

    The client uses this to display remaining allowance and to disable the
    composer when the limit is reached.
    """
    user_id = _user_id_from_authorization(authorization)
    used = await db.get_token_usage(user_id)
    return {
        "tokens_used": used,
        "token_limit": MONTHLY_TOKEN_LIMIT,
        "remaining": max(0, MONTHLY_TOKEN_LIMIT - used),
        "limit_reached": used >= MONTHLY_TOKEN_LIMIT,
    }