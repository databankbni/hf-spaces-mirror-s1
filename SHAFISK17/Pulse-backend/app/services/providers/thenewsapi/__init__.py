# providers/thenewsapi/__init__.py
# ─────────────────────────────────────────────────────────────────────────────
# This file marks the 'thenewsapi' folder as a Python package.
# To use TheNewsAPI provider, import it like this:
#
#   from app.services.providers.thenewsapi.client import TheNewsAPIProvider
#
# This is a PAID provider — it requires the THENEWSAPI_API_KEY environment
# variable to be set. It has a daily_limit of 100 requests (free tier).
# It lives in the PAID_CHAIN, meaning it only fires if all providers above
# it in the chain (GNews, NewsAPI, NewsData) have already failed.
