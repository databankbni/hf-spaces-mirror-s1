"""Authentication for the Aegra / LangGraph server via ``langgraph_sdk.Auth``.

The ``@auth.authenticate`` handler verifies the HS256 JWT issued by the
``/auth/login`` route (see ``web/login.py``) and returns the authenticated
user's data. Aegra injects that dict into
``config["configurable"]["langgraph_auth_user"]`` before graph execution, so
nodes and tools can read the user's identity, role, etc. The Hugging Face
token used to build agents comes from the server-wide ``HF_TOKEN`` env var
(see ``web/login.py``), not from the user record.

Wire it up in ``langgraph.json``::

    "auth": { "path": "./src/web/auth.py:auth" }

Requires the ``JWT_SECRET`` environment variable.
"""

from __future__ import annotations

import os
from typing import Any

import jwt
from langgraph_sdk import Auth

auth = Auth()

JWT_SECRET = os.environ.get("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET environment variable is required")

JWT_ALGORITHM = "HS256"

# Per-user monthly token allowance (prompt + completion tokens). A run that
# would start after the user has reached this limit is rejected with 403.
# Usage resets on the first day of every month (see web/db.py).
MONTHLY_TOKEN_LIMIT = int(os.environ.get("MONTHLY_TOKEN_LIMIT", "100000"))


def create_access_token(user: dict[str, Any]) -> str:
    """Sign a stateless access token for the given user row."""
    payload = {
        "sub": str(user["id"]),
        "username": user["username"],
        "display_name": user.get("display_name") or user["username"],
        "role": user.get("role", "user"),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


@auth.authenticate
async def authenticate(headers: dict) -> dict:
    """Verify the bearer JWT and return the authenticated user's data.

    Everything returned here is available server-side as
    ``config["configurable"]["langgraph_auth_user"]`` in graph nodes/tools and
    as ``ctx.user`` in authorization handlers. Raising any exception denies
    the request with 401.
    """
    authorization = headers.get("Authorization") or headers.get("authorization") or ""
    token = authorization.replace("Bearer ", "").strip()
    if not token:
        # Clean 401 (no traceback) for requests without a bearer token.
        raise Auth.exceptions.HTTPException(status_code=401, detail="Missing Authorization header")

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise Auth.exceptions.HTTPException(status_code=401, detail="Invalid or expired token") from exc

    # Look up the user so token data can't go stale (role changes,
    # deactivated accounts).
    from web import db  # local import to avoid a cycle at module load time

    user = await db.get_user_by_id(payload["sub"])
    if not user or not user.get("is_active", True):
        raise Auth.exceptions.HTTPException(status_code=401, detail="Account not found or deactivated")

    return {
        "identity": str(user["id"]),
        "display_name": user.get("display_name") or user["username"],
        "permissions": [user.get("role", "user")],
        "is_authenticated": True,
        # Custom fields — preserved on ctx.user and in langgraph_auth_user.
        "username": user["username"],
        "role": user.get("role", "user"),
    }


# ---------------------------------------------------------------------------
# Authorization handlers (additive: they only restrict, never grant)
# ---------------------------------------------------------------------------

@auth.on.threads.create
async def stamp_thread_owner(ctx, value):
    """Tag every new thread with the owner's identity as metadata."""
    metadata = value.setdefault("metadata", {})
    metadata["owner_id"] = ctx.user.identity
    return value


@auth.on.threads.search
async def filter_threads_by_owner(ctx, value):
    """Users only see their own threads in search/list results."""
    return {"metadata": {"owner_id": ctx.user.identity}}


@auth.on.threads.read
async def filter_thread_reads_by_owner(ctx, value):
    """Apply the same owner filter to by-id reads, state, and history."""
    return {"metadata": {"owner_id": ctx.user.identity}}


@auth.on.threads.create_run
async def enforce_monthly_token_limit(ctx, value):
    """Reject run creation once the user's monthly token limit is reached.

    Runs are created on a thread (``POST /threads/{id}/runs``), so this
    handler fires for every new run — including streamed ones. Raising
    ``HTTPException`` here aborts the request before any model tokens are
    spent; the client surfaces the detail message to the user.
    """
    from web import db  # local import to avoid a cycle at module load time

    used = await db.get_token_usage(ctx.user.identity)
    if used >= MONTHLY_TOKEN_LIMIT:
        raise Auth.exceptions.HTTPException(
            status_code=403,
            detail=(
                f"Monthly token limit reached ({used}/{MONTHLY_TOKEN_LIMIT} "
                "tokens used). Your allowance refreshes on the first day of "
                "next month."
            ),
        )
    # Accept the request (no filter needed for run creation).
    return None
