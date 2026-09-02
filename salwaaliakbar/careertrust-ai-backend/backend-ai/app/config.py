"""Central configuration for the AI services app.

Loaded once at import time so every router shares the same values instead of
each module calling `load_dotenv()` and re-reading `os.getenv` independently.
"""

import os

from dotenv import load_dotenv
from fastapi import Header, HTTPException

load_dotenv()

API_KEY = os.getenv("API_KEY")
if not API_KEY:
    raise RuntimeError(
        "API_KEY environment variable is required. Set it in your .env file "
        "(local dev) or in your hosting platform's environment settings (prod)."
    )

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

DEV_BYPASS_FACE = os.getenv("DEV_BYPASS_FACE", "false").strip().lower() in (
    "1",
    "true",
    "yes",
)


def require_api_key(x_api_key: str | None = Header(None)) -> None:
    """FastAPI dependency: raises 401 unless the caller sent the correct X-API-Key."""
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
