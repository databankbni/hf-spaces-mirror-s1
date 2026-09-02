import json
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

TOKEN_STORE_PATH = Path(__file__).resolve().parent.parent / "youtube_tokens.json"


def get_refresh_token() -> Optional[str]:
    token = None
    if TOKEN_STORE_PATH.exists():
        try:
            data = json.loads(TOKEN_STORE_PATH.read_text(encoding="utf-8"))
            token = data.get("refresh_token")
        except Exception:
            token = None
    return token


def save_refresh_token(refresh_token: str) -> None:
    data = {"refresh_token": refresh_token}
    TOKEN_STORE_PATH.write_text(json.dumps(data), encoding="utf-8")


def clear_refresh_token() -> None:
    if TOKEN_STORE_PATH.exists():
        TOKEN_STORE_PATH.unlink(missing_ok=True)
