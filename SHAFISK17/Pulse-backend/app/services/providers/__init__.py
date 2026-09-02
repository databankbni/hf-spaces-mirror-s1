# =============================================================================
# providers/__init__.py
# ─────────────────────────────────────────────────────────────────────────────
# This file marks the 'providers' folder as a Python package so that
# Python knows it can import code from inside it.
#
# ── HOW TO ADD A NEW PROVIDER ──────────────────────────────────────────────
# 1. Create a new folder under providers/  (e.g., providers/hackernews/)
# 2. Inside that folder, create __init__.py  (empty) and client.py
# 3. In client.py, write a class that inherits from base.NewsProvider
# 4. Add the import line below so the aggregator can find it easily:
#    from app.services.providers.hackernews.client import HackerNewsProvider
#
# ── ROUTING RULE (CRITICAL) ────────────────────────────────────────────────
# Every provider MUST set a 'category' on each Article it returns.
# If a provider cannot determine a category, it MUST leave category as ""
# or "magazines". DO NOT LEAVE IT AS None.
#
# When category is empty or unrecognized, appwrite_db.get_collection_id()
# automatically routes the article to the DEFAULT 'News Articles' collection.
# This is intentional and safe. Never invent a category name that doesn't
# exist in config.py CATEGORIES — it will silently break routing.
# =============================================================================
