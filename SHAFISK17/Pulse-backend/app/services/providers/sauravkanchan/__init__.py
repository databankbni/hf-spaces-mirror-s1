# providers/sauravkanchan/__init__.py
# ─────────────────────────────────────────────────────────────────────────────
# This file marks the 'sauravkanchan' folder as a Python package.
# To use this provider, import it like this:
#
#   from app.services.providers.sauravkanchan.client import SauravKanchanProvider
#
# This is a FREE, zero-rate-limit provider — it reads static JSON files
# hosted on GitHub Pages by developer Saurav Kanchan. No API key needed.
# It fetches tech headlines from both India (in.json) and the US (us.json)
# simultaneously, doubling volume with a single aggregator call.
# Gated behind GENERAL_TECH_CATEGORIES (same as Hacker News & Inshorts).
