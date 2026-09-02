import json
import os
import re
from pathlib import Path
from typing import Any, Optional

import requests
from dotenv import load_dotenv

env_path = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=env_path, override=False)

YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()
YOUTUBE_REDIRECT_URI = os.getenv("YOUTUBE_REDIRECT_URI", "").strip()

YOUTUBE_UPLOAD_ENDPOINT = "https://www.googleapis.com/upload/youtube/v3/videos"


def _sanitize_youtube_tags(raw_tags: Optional[str]) -> list[str]:
    if raw_tags is None:
        return []

    candidates = re.split(r"[,;|\n]+", str(raw_tags))
    cleaned: list[str] = []
    seen: set[str] = set()

    for candidate in candidates:
        tag = re.sub(r"\s+", " ", candidate).strip()
        tag = re.sub(r"[#@/\\]+", "", tag)
        tag = re.sub(r"[\u200B-\u200D\uFEFF]", "", tag)
        tag = tag.strip("-_. ")
        if not tag:
            continue

        tag = tag[:30].strip()
        if len(tag) < 2:
            continue

        key = tag.lower()
        if key in seen:
            continue

        seen.add(key)
        cleaned.append(tag)

    return cleaned[:50]


def upload_video_to_youtube(
    access_token: str,
    title: str,
    description: str,
    tags: str,
    video_file_path: str,
    privacy_status: str = "private",
) -> dict[str, Any]:
    if not access_token:
        raise ValueError("Missing access token")
    if not Path(video_file_path).exists():
        raise ValueError("Video file not found")

    valid_tags = _sanitize_youtube_tags(tags)
    snippet = {
        "title": (title or "Video truyện")[:100],
        "description": (description or "Video tự động")[:5000],
    }
    if valid_tags:
        snippet["tags"] = valid_tags

    status = {"privacyStatus": privacy_status}
    metadata = json.dumps({"snippet": snippet, "status": status})

    boundary = "----youtube-upload-boundary"
    with open(video_file_path, "rb") as video_file:
        media_bytes = video_file.read()

    payload = (
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{metadata}\r\n"
        f"--{boundary}\r\n"
        "Content-Type: video/mp4\r\n\r\n"
    ).encode("utf-8") + media_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": f"multipart/related; boundary={boundary}",
    }

    response = requests.post(
        YOUTUBE_UPLOAD_ENDPOINT,
        params={"part": "snippet,status"},
        headers=headers,
        data=payload,
        timeout=300,
    )

    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail = response.text
        raise requests.HTTPError(f"YouTube upload failed: {detail}", response=response) from exc

    return response.json()
