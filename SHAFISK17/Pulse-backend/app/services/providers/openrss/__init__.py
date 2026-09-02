# providers/openrss/__init__.py
# ─────────────────────────────────────────────────────────────────────────────
# This file marks the 'openrss' folder as a Python package.
# To use this provider, import it like this:
#
#   from app.services.providers.openrss.client import OpenRSSProvider
#
# OpenRSS is FREE — no API key needed. It generates XML feeds on-the-fly
# for any website, even sites that don't publish an RSS feed themselves.
#
# ── CRITICAL RULE: RESPECT THE COOLDOWN ──────────────────────────────────
# OpenRSS explicitly says "aggregator use is not officially supported".
# If you fetch too frequently, they WILL ban your server's IP address.
# The OpenRSSProvider enforces a strict 60-minute internal cooldown timer.
# DO NOT reduce COOLDOWN_SECONDS below 3600. Breaking this causes IP bans.
