"""
Xác thực Google Drive — hỗ trợ 2 cơ chế:

  1. OAuth user (Gmail cá nhân) — index files sẽ thuộc về user, dùng quota 15GB
     - Cần GDRIVE_OAUTH_CLIENT (đường dẫn file OAuth client JSON từ GCP console)
     - Token được lưu vào GDRIVE_OAUTH_TOKEN (mặc định backend/oauth_token.json)
     - Lần đầu: tự mở browser để authorize, lưu refresh_token vào disk

  2. Service Account — fallback, dùng được với Shared Drive (Workspace).
     KHÔNG dùng được với folder thường trong My Drive vì service account 0 quota.

Hàm `get_drive_service(scopes)` tự ưu tiên OAuth nếu có client config.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from config import BASE_DIR, GDRIVE_CREDENTIALS_PATH

logger = logging.getLogger(__name__)


# ── Env / paths ───────────────────────────────────────────────────────────────

OAUTH_CLIENT_PATH = os.getenv(
    "GDRIVE_OAUTH_CLIENT", str(BASE_DIR / "oauth_client.json")
)
OAUTH_TOKEN_PATH = os.getenv(
    "GDRIVE_OAUTH_TOKEN", str(BASE_DIR / "oauth_token.json")
)

# Cho phép paste nội dung JSON qua env (tiện deploy HF Spaces)
OAUTH_CLIENT_JSON_ENV = os.getenv("GDRIVE_OAUTH_CLIENT_JSON", "")
OAUTH_TOKEN_JSON_ENV = os.getenv("GDRIVE_OAUTH_TOKEN_JSON", "")


def _resolve_oauth_client_path() -> str | None:
    """Trả về đường dẫn file OAuth client JSON nếu tồn tại; nếu env có JSON thì ghi tạm."""
    if OAUTH_CLIENT_JSON_ENV:
        # Ghi nội dung JSON từ env ra file tạm để dùng với InstalledAppFlow
        import tempfile
        tmp = tempfile.NamedTemporaryFile(
            delete=False, suffix=".json", mode="w", encoding="utf-8"
        )
        tmp.write(OAUTH_CLIENT_JSON_ENV)
        tmp.close()
        return tmp.name
    if Path(OAUTH_CLIENT_PATH).exists():
        return OAUTH_CLIENT_PATH
    return None


def _load_token_from_env_or_disk(scopes: list[str]):
    """Trả về Credentials đã load từ token JSON, hoặc None nếu chưa có."""
    from google.oauth2.credentials import Credentials

    if OAUTH_TOKEN_JSON_ENV:
        info = json.loads(OAUTH_TOKEN_JSON_ENV)
        return Credentials.from_authorized_user_info(info, scopes)
    if Path(OAUTH_TOKEN_PATH).exists():
        return Credentials.from_authorized_user_file(OAUTH_TOKEN_PATH, scopes)
    return None


def _save_token(creds) -> None:
    """Lưu token (gồm refresh_token) ra disk để lần sau không cần authorize nữa."""
    Path(OAUTH_TOKEN_PATH).write_text(creds.to_json(), encoding="utf-8")
    logger.info("OAuth token đã lưu vào %s", OAUTH_TOKEN_PATH)


def authorize_oauth(scopes: list[str], headless: bool = False):
    """Chạy luồng OAuth lần đầu (mở browser) và lưu token.
    headless=True: in URL cho user mở thủ công + paste code (server không có browser).
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    client_path = _resolve_oauth_client_path()
    if not client_path:
        raise RuntimeError(
            f"Không tìm thấy OAuth client JSON tại {OAUTH_CLIENT_PATH}. "
            "Tải về từ GCP Console (APIs & Services → Credentials → OAuth client ID, type=Desktop)."
        )

    flow = InstalledAppFlow.from_client_secrets_file(client_path, scopes)
    if headless:
        creds = flow.run_console()  # nhập code thủ công
    else:
        creds = flow.run_local_server(port=0)
    _save_token(creds)
    return creds


def get_oauth_credentials(scopes: list[str]):
    """Lấy OAuth user credentials. Nếu chưa có token → chạy authorize flow."""
    creds = _load_token_from_env_or_disk(scopes)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
        _save_token(creds)
        return creds
    # Chưa có token hoặc token hỏng → cần authorize lần đầu
    return authorize_oauth(scopes, headless=False)


def get_drive_service(scopes: list[str]):
    """Build googleapi service. Ưu tiên OAuth user, fallback service account."""
    from googleapiclient.discovery import build

    # Ưu tiên 1: OAuth user nếu có client config hoặc token đã lưu
    has_oauth = (
        OAUTH_CLIENT_JSON_ENV
        or OAUTH_TOKEN_JSON_ENV
        or Path(OAUTH_CLIENT_PATH).exists()
        or Path(OAUTH_TOKEN_PATH).exists()
    )
    if has_oauth:
        logger.info("Drive auth: dùng OAuth user")
        creds = get_oauth_credentials(scopes)
        return build("drive", "v3", credentials=creds)

    # Ưu tiên 2: Service Account (fallback — chỉ dùng được với Shared Drive)
    logger.info("Drive auth: dùng Service Account (fallback)")
    from google.oauth2.service_account import Credentials as SACredentials
    creds = SACredentials.from_service_account_file(GDRIVE_CREDENTIALS_PATH, scopes=scopes)
    return build("drive", "v3", credentials=creds)
