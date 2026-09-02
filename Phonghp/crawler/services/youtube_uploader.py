import os
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv

env_path = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=env_path, override=False)

YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()
YOUTUBE_REDIRECT_URI = os.getenv("YOUTUBE_REDIRECT_URI", "").strip()
YOUTUBE_SCOPES = "https://www.googleapis.com/auth/youtube.upload"


def build_oauth_authorization_url(state: Optional[str] = None) -> str:
    if not YOUTUBE_CLIENT_ID or not YOUTUBE_REDIRECT_URI:
        raise ValueError("Missing YouTube OAuth config")

    params = {
        "client_id": YOUTUBE_CLIENT_ID,
        "redirect_uri": YOUTUBE_REDIRECT_URI,
        "response_type": "code",
        "scope": YOUTUBE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
    }
    if state:
        params["state"] = state

    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


def exchange_code_for_tokens(code: str) -> dict[str, Any]:
    if not YOUTUBE_CLIENT_ID or not YOUTUBE_CLIENT_SECRET or not YOUTUBE_REDIRECT_URI:
        raise ValueError("Missing YouTube OAuth config")

    response = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": YOUTUBE_CLIENT_ID,
            "client_secret": YOUTUBE_CLIENT_SECRET,
            "redirect_uri": YOUTUBE_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    if not YOUTUBE_CLIENT_ID or not YOUTUBE_CLIENT_SECRET:
        raise ValueError("Missing YouTube OAuth config")

    response = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": YOUTUBE_CLIENT_ID,
            "client_secret": YOUTUBE_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()
