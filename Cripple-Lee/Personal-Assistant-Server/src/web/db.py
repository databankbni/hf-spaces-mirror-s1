"""Async Postgres access layer.

Provides a lazily-created ``asyncpg`` connection pool plus the small set of
queries needed by the auth routes (``/auth/signup``, ``/auth/login``), the
``langgraph_sdk.Auth`` authenticate handler, and per-user monthly token
usage tracking.

Requires the ``DATABASE_URL`` environment variable, e.g.::

    postgresql://user:password@localhost:5432/personal_assistant

The schema is in ``db/schema.sql``.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any, Optional

import asyncpg

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    """Return the shared connection pool, creating it on first use."""
    global _pool
    if _pool is None:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError(
                "DATABASE_URL environment variable is required for auth. "
                "Example: postgresql://user:password@localhost:5432/personal_assistant"
            )
        _pool = await asyncpg.create_pool(dsn=database_url, min_size=1, max_size=10)
    return _pool


async def close_pool() -> None:
    """Close the connection pool (called on app shutdown)."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def create_user(
    username: str,
    password_hash: str,
    display_name: Optional[str] = None,
    email: Optional[str] = None,
) -> dict[str, Any]:
    """Insert a new user and return the created row as a dict.

    Raises ``asyncpg.UniqueViolationError`` if the username (case-insensitive)
    or email is already taken.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO users (username, password_hash, display_name, email)
            VALUES ($1, $2, $3, $4)
            RETURNING id, username, display_name, email, role, created_at
            """,
            username,
            password_hash,
            display_name or username,
            email,
        )
    return dict(row)


async def get_user_by_username(username: str) -> Optional[dict[str, Any]]:
    """Fetch a user (including password hash) by case-insensitive username."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, username, display_name, email, role,
                   password_hash, is_active
            FROM users
            WHERE lower(username) = lower($1)
            """,
            username,
        )
    return dict(row) if row else None


async def get_user_by_id(user_id: str) -> Optional[dict[str, Any]]:
    """Fetch a user (without password hash) by primary key."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, username, display_name, email, role, is_active
            FROM users
            WHERE id = $1
            """,
            user_id,
        )
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Monthly token usage
# ---------------------------------------------------------------------------

def _current_period_start() -> date:
    """First day of the current calendar month (UTC date)."""
    today = date.today()
    return today.replace(day=1)


async def get_token_usage(user_id: str) -> int:
    """Tokens used by the user in the current month (0 if no row yet).

    Because usage is keyed by ``period_start`` (first of the month), the
    allowance automatically refreshes on the first day of every month — a
    new month simply has no row yet and reads as zero.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT tokens_used
            FROM token_usage
            WHERE user_id = $1 AND period_start = $2
            """,
            user_id,
            _current_period_start(),
        )
    return int(row["tokens_used"]) if row else 0


async def add_token_usage(user_id: str, tokens: int) -> int:
    """Add ``tokens`` to the user's current-month usage; return the new total."""
    if tokens <= 0:
        return await get_token_usage(user_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO token_usage (user_id, period_start, tokens_used)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id, period_start)
            DO UPDATE SET tokens_used = token_usage.tokens_used + EXCLUDED.tokens_used
            RETURNING tokens_used
            """,
            user_id,
            _current_period_start(),
            tokens,
        )
    return int(row["tokens_used"])
