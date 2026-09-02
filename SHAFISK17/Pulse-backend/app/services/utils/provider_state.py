"""
app/services/utils/provider_state.py
─────────────────────────────────────────────────────────────────────────────
Phase 15: Unified Redis State Architecture

What this does:
    Saves and restores provider "state" — things like "when did we last call
    OpenRSS?" and "how many times have we called Webz today?" — to our
    Upstash Redis instance.

Why we need this:
    Our backend runs on Hugging Face Spaces, which can restart at any time.
    When a restart happens, all Python RAM is wiped. Without this utility:
        - OpenRSS's 60-minute cooldown resets to 0, so we hammer them on
          every restart and eventually get an IP ban.
        - Webz's monthly budget counter resets, so we can burn our entire
          month's calls in a single bad restart day.

    With this utility:
        - Even if the server restarts 10 times in an hour, Redis remembers
          the exact timestamp of the last OpenRSS call and the exact number
          of Webz calls made today. Provider quotas are now restart-proof.

How it works:
    Two pairs of async functions:
        1. Timestamps (for cooldown timers like OpenRSS):
               get_provider_timestamp("openrss") → float (Unix timestamp)
               set_provider_timestamp("openrss", time.time())

        2. Counters (for daily/monthly budgets like Webz, WorldNewsAI):
               get_provider_counter("webz", "2026-03-03") → int
               increment_provider_counter("webz", "2026-03-03")

Redis key format:
    Timestamps: provider:state:{provider_name}:last_fetch
    Counters:   provider:state:{provider_name}:calls:{date_key}

Mirrored directly from circuit_breaker.py's approach:
    - Same get_upstash_cache() import
    - Same _execute_command([...]) API
    - Same fail-safe try/except pattern

Fail-open vs Fail-safe design:
    - get_provider_timestamp:  returns 0.0  on Redis failure
        → Provider assumes "never fetched before" → allowed to run
        → This is CORRECT for free providers (OpenRSS). Missing one cooldown
          check is less dangerous than permanently blocking the provider.

    - get_provider_counter:    returns 999999 on Redis failure
        → Provider assumes "budget exhausted" → safely skips the run
        → This is CORRECT for paid providers (Webz, WorldNewsAI). We would
          rather miss one run than accidentally overspend our API budget.

Thread safety:
    asyncio is single-threaded. All functions below use `await`. Only one
    coroutine runs at a time, so there are no race conditions to worry about
    within a single Python process. No locks needed.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ── Key Builders ─────────────────────────────────────────────────────────────
# Centralizing the key format here means if we ever need to change it,
# we change it in one place and every provider picks up the fix automatically.

def _timestamp_key(provider_name: str) -> str:
    """
    Build the Redis key string for a provider's last-fetch timestamp.

    Example:
        provider_name = "openrss"
        → "provider:state:openrss:last_fetch"
    """
    return f"provider:state:{provider_name}:last_fetch"


def _counter_key(provider_name: str, date_key: str) -> str:
    """
    Build the Redis key string for a provider's daily call counter.

    date_key is normally a date string like "2026-03-03" so the key
    automatically changes every day without needing a manual reset.

    Example:
        provider_name = "webz", date_key = "2026-03-03"
        → "provider:state:webz:calls:2026-03-03"
    """
    return f"provider:state:{provider_name}:calls:{date_key}"


# ── Timestamp Functions (for cooldown timers) ─────────────────────────────────

async def get_provider_timestamp(provider_name: str) -> float:
    """
    Read the last-fetch timestamp for a provider from Redis.

    Returns a Unix timestamp (seconds since 1970). If Redis is unavailable
    or the key doesn't exist yet, returns 0.0 so the provider treats it as
    "never fetched before" and is allowed to run immediately.

    This is the FAIL-OPEN design — when in doubt, let the provider run.
    Suitable for free providers with cooldown timers (OpenRSS).

    Args:
        provider_name (str): Short name like "openrss".

    Returns:
        float: Unix timestamp of the last fetch, or 0.0 if not found.
    """
    try:
        from app.services.upstash_cache import get_upstash_cache
        cache = get_upstash_cache()

        key = _timestamp_key(provider_name)
        # Redis GET returns a string like "1740000000.123" or None if missing.
        raw_value = await cache._execute_command(["GET", key])

        if raw_value is None:
            # Key doesn't exist yet — provider has never fetched before.
            return 0.0

        # Parse the string back to a float.
        return float(raw_value)

    except Exception as e:
        # Redis is down, unreachable, or returned something unexpected.
        # Fail open: return 0.0 so the provider is allowed to run.
        # This is the safe direction for free providers — one extra call
        # is far less dangerous than permanently blocking the provider.
        logger.warning(
            "[provider_state] get_provider_timestamp('%s') failed (%s) "
            "— returning 0.0 (fail-open: provider will be allowed to run).",
            provider_name, e
        )
        return 0.0


async def set_provider_timestamp(
    provider_name: str,
    timestamp: float,
    expire_seconds: int = 7200,   # Default TTL: 2 hours
) -> None:
    """
    Save a provider's last-fetch timestamp to Redis.

    Always call this BEFORE you start the actual network request, not after.
    If you save it AFTER and the request crashes halfway through, the provider
    will think "I was never blocked" and fire again immediately on the next
    scheduler cycle — the exact opposite of what the cooldown is supposed to do.

    The TTL (expire_seconds) is a safety net. If the key is never explicitly
    deleted, Redis will remove it automatically after 2 hours so it doesn't
    sit in memory forever. 2 hours is safely above the 60-minute cooldown.

    Args:
        provider_name (str):  Short name like "openrss".
        timestamp (float):    Unix timestamp (use time.time() to get the current one).
        expire_seconds (int): How long to keep this key in Redis. Default: 7200s (2h).
    """
    try:
        from app.services.upstash_cache import get_upstash_cache
        cache = get_upstash_cache()

        key = _timestamp_key(provider_name)
        # Store the float as a string. Redis stores all values as strings anyway.
        # "SET key value EX seconds" — sets both the value and the TTL in one call.
        await cache._execute_command(["SET", key, str(timestamp), "EX", expire_seconds])

        logger.debug(
            "[provider_state] Saved last_fetch timestamp for '%s' to Redis (TTL=%ds).",
            provider_name, expire_seconds
        )

    except Exception as e:
        # Redis write failed. This is recoverable — the cooldown will just
        # fall back to RAM-based tracking for this run. Log it and move on.
        logger.warning(
            "[provider_state] set_provider_timestamp('%s') failed (%s) "
            "— cooldown state will not survive a server restart for this run.",
            provider_name, e
        )


# ── Counter Functions (for daily/monthly API budgets) ─────────────────────────

async def get_provider_counter(provider_name: str, date_key: str) -> int:
    """
    Read a provider's call counter for a specific date from Redis.

    If Redis is unavailable or the key doesn't exist, returns 999999.
    This is the FAIL-SAFE design — when in doubt, assume the budget is
    exhausted and skip the call. Much better than accidentally burning
    a month's worth of Webz or WorldNewsAI credits on a bad restart day.

    Args:
        provider_name (str): Short name like "webz" or "worldnewsai".
        date_key (str):      Date string like "2026-03-03" (use UTC date).
                             Using today's UTC date as the key means the
                             counter automatically resets each morning without
                             any manual cleanup — yesterday's key just expires.

    Returns:
        int: Number of API calls made today, or 999999 if Redis is down.
    """
    try:
        from app.services.upstash_cache import get_upstash_cache
        cache = get_upstash_cache()

        key = _counter_key(provider_name, date_key)
        raw_value = await cache._execute_command(["GET", key])

        if raw_value is None:
            # No calls made today yet — counter starts at 0.
            return 0

        return int(raw_value)

    except Exception as e:
        # Redis is down. Fail SAFE: return a huge number so the provider
        # thinks its budget is exhausted and skips this run.
        # One missed run costs us nothing. One overspent budget could cost us money.
        logger.warning(
            "[provider_state] get_provider_counter('%s', '%s') failed (%s) "
            "— returning 999999 (fail-safe: provider will be skipped this run).",
            provider_name, date_key, e
        )
        return 999999


async def increment_provider_counter(
    provider_name: str,
    date_key: str,
    amount: int = 1,
    expire_seconds: int = 86400,  # Default TTL: 24 hours (one full day)
) -> None:
    """
    Increment a provider's daily call counter in Redis by `amount`.

    Uses Redis INCR (atomic increment) which is safe to call concurrently
    from multiple requests — though since we run single-process asyncio,
    this is mostly a good practice rather than a strict requirement here.

    After incrementing, we always refresh the TTL with EXPIRE. This means
    even if the key was created yesterday and is still sitting around, it
    gets a fresh 24-hour life from the moment we update it.

    Args:
        provider_name (str):  Short name like "webz" or "worldnewsai".
        date_key (str):       Date string like "2026-03-03" (use UTC date).
        amount (int):         How much to add to the counter. Default: 1.
        expire_seconds (int): Key TTL. Default: 86400s (24 hours).
    """
    try:
        from app.services.upstash_cache import get_upstash_cache
        cache = get_upstash_cache()

        key = _counter_key(provider_name, date_key)

        # INCRBY key amount — atomically adds `amount` to the counter.
        # If the key doesn't exist yet, Redis creates it at 0 and then adds amount.
        await cache._execute_command(["INCRBY", key, str(amount)])

        # Refresh the TTL so the key doesn't expire mid-day.
        # EXPIRE key seconds — resets the countdown timer on the key.
        await cache._execute_command(["EXPIRE", key, str(expire_seconds)])

        logger.debug(
            "[provider_state] Incremented call counter for '%s' on '%s' by %d.",
            provider_name, date_key, amount
        )

    except Exception as e:
        # Redis write failed. The counter won't reflect this call in Redis,
        # but in-memory tracking (request_count) still works. Log and continue.
        logger.warning(
            "[provider_state] increment_provider_counter('%s', '%s') failed (%s) "
            "— this call will not be counted in Redis. In-memory limit still applies.",
            provider_name, date_key, e
        )
