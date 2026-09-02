"""
Redis URL Deduplication Bouncer
================================

This is the 48-hour memory for the ingestion pipeline.

How it works (simple version):
  Imagine a nightclub bouncer who keeps a list of everyone who came in
  today and yesterday. If you try to enter again while still on the list,
  you are turned away. After 48 hours, your name falls off the list and
  you are welcome back.

That is exactly what this module does for article URLs.

Each article URL is:
  1. Cleaned and normalized (canonicalized).
  2. Converted to a short SHA-256 fingerprint (so we store 16 chars not full URLs).
  3. Checked against Upstash Redis with the command: SET key 1 EX 172800 NX
       - EX 172800 = expire after 172800 seconds = 48 hours
       - NX         = only set if Not eXists

Redis response:
  - "OK"  → key did NOT exist → article is NEW → return False (not seen before)
  - null  → key already existed → article is DUPLICATE → return True (seen before)

Fallback:
  If Upstash is not configured or Redis is unreachable, this function
  safely returns False (treats every article as new). The Appwrite
  database constraint is still the final safety net in that case.
"""

import logging
from app.utils.url_canonicalization import canonicalize_url, get_url_hash
from app.services.upstash_cache import get_upstash_cache

logger = logging.getLogger(__name__)

# Redis key prefix for URL deduplication keys.
# Keeps our keys clearly separate from the article-cache keys.
_KEY_PREFIX = "seen_url:"

# 48 hours expressed in seconds.
# This matches the cleanup janitor in scheduler.py which also deletes
# articles older than 48 hours. When an article is deleted from the
# database, its Redis key will also expire around the same time,
# allowing the article to be re-ingested if it genuinely resurfaces.
_TTL_SECONDS = 172_800  # 48 * 60 * 60


async def is_url_seen_or_mark(raw_url: str) -> bool:
    """
    Check if we have seen this article URL in the last 48 hours.
    If we have NOT seen it, mark it as seen so future checks catch it.

    Args:
        raw_url: The article URL (any format — we normalize it internally).

    Returns:
        True  → We have seen this URL before. It is a duplicate. Skip it.
        False → This URL is brand new. The article was also marked in Redis
                so the next run will correctly identify it as a duplicate.
    """
    if not raw_url:
        # No URL means we cannot deduplicate. Let it through.
        return False

    try:
        # Step 1: Normalize the URL so different versions of the same link
        # (http vs https, trailing slash, utm_ params) all produce the same key.
        canonical = canonicalize_url(str(raw_url))

        # Step 2: Convert to a short hash so our Redis keys are tiny and uniform.
        url_hash = get_url_hash(canonical)
        redis_key = f"{_KEY_PREFIX}{url_hash}"

        # Step 3: Get the Upstash client (shared singleton — already used by cache).
        cache = get_upstash_cache()

        # Step 4: Try to set the key WITH NX (only if it does not already exist).
        # This is an atomic check-and-set: no race condition possible.
        # Command: SET seen_url:{hash} 1 EX 172800 NX
        result = await cache._execute_command(
            ["SET", redis_key, "1", "EX", _TTL_SECONDS, "NX"]
        )

        if result == "OK":
            # Redis successfully created the key → this URL is NEW.
            return False  # Not a duplicate — let the article through.
        else:
            # Redis returned null → key already existed → DUPLICATE.
            logger.debug("[REDIS DEDUP] Duplicate detected: %s", redis_key)
            return True   # It's a duplicate — skip this article.

    except Exception as e:
        # Something went wrong with Redis (network error, timeout, etc.).
        # We NEVER block an article because of a Redis failure.
        # The Appwrite database will still catch true duplicates as a safety net.
        logger.warning(
            "[REDIS DEDUP] Redis check failed (%s) — letting article through as safe fallback.",
            e
        )
        return False  # Safe fallback: treat as new article.
