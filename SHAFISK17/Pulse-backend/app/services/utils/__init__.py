# app/services/utils/__init__.py
# ─────────────────────────────────────────────────────────────────────────────
# This folder contains shared helper utilities that are used by multiple
# providers. They are NOT providers themselves — they are small tools that
# providers can import to do common jobs.
#
# Current utilities:
#   image_enricher.py — Extracts the main image from any article URL
