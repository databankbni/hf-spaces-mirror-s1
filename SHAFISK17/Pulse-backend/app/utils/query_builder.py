"""
Query Builder Utility  (Phase 20 — Dynamic Round-Robin Query Builder)
=====================================================================

PURPOSE
-------
When we ask a news API for articles, we send a "query string" — a list of
keywords that tells the API what topics we want. Our Phase 19 taxonomy can
have up to 28 keywords per category. Stuffing all 28 into one API call would:
  1. Crash the API with an HTTP 400 "query too long" error.
  2. Return the same broad results every single hour — wasting our paid quota.

SOLUTION: The Anchor + Round-Robin Strategy
-------------------------------------------
For every category we split the keyword list into two parts:

  ANCHORS  — The first 3 keywords. These are the most important, core terms
             (e.g. "artificial intelligence", "machine learning", "openai").
             They are ALWAYS included in every query, every hour.
             This guarantees we never miss breaking news on a core topic.

  ROTATORS — The remaining keywords (e.g. "anthropic", "mistral", "llama"...).
             These are divided into chunks of 4.
             Each hour of the day, one chunk is added to the anchors.
             So over 24 hours, we cycle through all chunks, covering every
             niche keyword without ever exceeding the URL character limit.

CLOCK MATH (Stateless & Restart-Safe)
--------------------------------------
  chunk_index = datetime.now(UTC).hour  %  number_of_chunks

  - Uses UTC so the rotation is identical everywhere — Hugging Face, local,
    AWS — regardless of which timezone the server is in.
  - No Redis, no database, no file. Just Python's clock. If the server
    restarts, the correct chunk for the current hour is immediately selected.

SINGLE SOURCE OF TRUTH
-----------------------
We IMPORT CATEGORY_KEYWORDS from data_validation.py. We never copy it here.
One dict, one place. Phase 21 expansions will automatically be picked up.

SUPPORTED API TYPES
-------------------
  "newsapi"   →  Multi-word phrases quoted, terms joined with " OR "
                 Example: '"artificial intelligence" OR openai OR llm'
  "gnews"     →  All terms joined with a single space
                 Example: 'artificial intelligence openai llm'
  "newsdata"  →  All terms joined with a comma
                 Example: 'artificial intelligence,openai,llm'
"""

from datetime import datetime, timezone
from typing import List

# ── Single Source of Truth ────────────────────────────────────────────────────
# We import from data_validation.py rather than duplicating the dictionary here.
# This means any keyword added in a future phase is automatically picked up
# by all API queries with zero additional work.
from app.utils.data_validation import CATEGORY_KEYWORDS

# ── Tuning Constants ──────────────────────────────────────────────────────────
_ANCHOR_COUNT   = 3   # How many keywords are always included (anchors)
_CHUNK_SIZE     = 4   # How many rotator keywords are added per hour


def _chunk_list(items: List[str], size: int) -> List[List[str]]:
    """
    Splits a flat list into groups of `size`.

    Example:
        _chunk_list(['a','b','c','d','e','f'], 3)
        → [['a','b','c'], ['d','e','f']]

    If the list divides unevenly, the last chunk is shorter — that is fine.
    """
    return [items[i : i + size] for i in range(0, len(items), size)]


def _format_for_api(keywords: List[str], api_type: str) -> str:
    """
    Converts a list of keywords into the query string format a specific API expects.

    Rules by api_type:
      "newsapi"  — Wrap any keyword that contains a space in double-quotes so
                   the API treats it as an exact phrase. Then join with " OR ".
                   Example output: '"artificial intelligence" OR openai OR llm'

      "gnews"    — Just join everything with spaces. GNews search is tolerant
                   of natural language.
                   Example output: 'artificial intelligence openai llm'

      "newsdata" — Join with commas. NewsData.io uses comma-separated terms.
                   Example output: 'artificial intelligence,openai,llm'

    Any unknown api_type falls back to the newsapi format (safest default).
    """
    if not keywords:
        return ""

    if api_type == "newsapi":
        # Phrases with spaces need quotes so the API treats them as a unit.
        # Single words can go bare (no quotes needed, saves character budget).
        formatted = [
            f'"{kw}"' if ' ' in kw else kw
            for kw in keywords
        ]
        return " OR ".join(formatted)

    elif api_type == "gnews":
        # GNews accepts plain space-separated words.
        return " ".join(keywords)

    elif api_type == "newsdata":
        # NewsData.io accepts comma-separated keywords.
        return ",".join(keywords)

    else:
        # Unknown API type — fall back to NewsAPI format (most common).
        formatted = [f'"{kw}"' if ' ' in kw else kw for kw in keywords]
        return " OR ".join(formatted)


def build_dynamic_query(category: str, api_type: str = "newsapi") -> str:
    """
    Build a query string for the given category using the Anchor + Round-Robin
    strategy driven by the current UTC hour.

    Args:
        category  — e.g. "ai", "cloud-aws", "data-engineering"
        api_type  — one of "newsapi", "gnews", "newsdata"
    """
    # ── Step 1: Get the keyword list for this category ────────────────────────
    all_keywords = CATEGORY_KEYWORDS.get(category)

    if not all_keywords:
        return category

    # ── Tune Constants based on API type limits ─────────────────────────────
    # NewsData has strict OR limits (max 5 keywords).
    anchor_count = 2 if api_type == "newsdata" else _ANCHOR_COUNT
    chunk_size   = 2 if api_type == "newsdata" else _CHUNK_SIZE

    # ── Step 2: Anchor split ──────────────────────────────────────────────────
    anchors  = all_keywords[:anchor_count]
    rotators = all_keywords[anchor_count:]

    # ── Step 3: Chunk the rotators ────────────────────────────────────────────
    chunks = _chunk_list(rotators, chunk_size)

    # ── Step 4: Pick the active chunk using the UTC clock ─────────────────────
    current_hour = datetime.now(timezone.utc).hour

    if chunks:
        active_index = current_hour % len(chunks)
        active_chunk = chunks[active_index]
    else:
        active_chunk = []

    # ── Step 5: Combine anchors + active chunk ────────────────────────────────
    final_keywords = anchors + active_chunk

    # ── Step 6: Format and return ─────────────────────────────────────────────
    return _format_for_api(final_keywords, api_type)
