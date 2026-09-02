# providers/webz/__init__.py
# ─────────────────────────────────────────────────────────────────────────────
# This file marks the 'webz' folder as a Python package.
# To use this provider, import it like this:
#
#   from app.services.providers.webz.client import WebzProvider
#
# This is a PAID provider — requires WEBZ_API_KEY in your .env file.
# Position 6 in the PAID_CHAIN (deepest paid failover).
#
# ── CRITICAL BUDGET WARNING ───────────────────────────────────────────────
# Webz.io free tier: 1,000 calls per MONTH (not per day).
# daily_limit is set to 30 inside WebzProvider to pace usage to ~900/month.
# DO NOT increase daily_limit above 33 — doing so will exhaust the
# monthly budget before the month ends.
