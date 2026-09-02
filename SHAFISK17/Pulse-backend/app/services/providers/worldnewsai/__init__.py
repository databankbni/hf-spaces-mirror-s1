# providers/worldnewsai/__init__.py
# ─────────────────────────────────────────────────────────────────────────────
# This file marks the 'worldnewsai' folder as a Python package.
# To use this provider, import it like this:
#
#   from app.services.providers.worldnewsai.client import WorldNewsAIProvider
#
# This is a PAID provider (point-based quota) — it requires the
# WORLDNEWS_API_KEY environment variable to be set.
#
# It sits at position 5 in the PAID_CHAIN — the last line of defence
# before the paid chain gives up. Only fires after GNews, NewsAPI,
# NewsData, and TheNewsAPI have all failed or exhausted their budgets.
#
# ── CRITICAL QUOTA WARNING ────────────────────────────────────────────────
# WorldNewsAI uses a point system, NOT a simple request counter.
# Each API call costs points + each returned article costs additional points.
# The client has a conservative daily_limit = 50 calls to protect the budget.
# If you see HTTP 402, the daily point budget is fully exhausted.
