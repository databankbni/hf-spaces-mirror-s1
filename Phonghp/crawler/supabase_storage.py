import logging
import mimetypes
import os
import urllib.error
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def _load_env() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)
    else:
        load_dotenv(override=False)


_load_env()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "").strip()
SUPABASE_STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "videos").strip()

SUPABASE_KEY = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY


def _get_headers(content_type: Optional[str] = None) -> dict[str, str]:
    headers: dict[str, str] = {
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "apikey": SUPABASE_KEY,
    }
    if content_type:
        headers["Content-Type"] = content_type
    # x-upsert only relevant for upload operations; include by default for compatibility
    headers["x-upsert"] = "true"
    return headers


def _is_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY and SUPABASE_STORAGE_BUCKET)


def _build_upload_url(object_name: str) -> str:
    object_path = object_name.lstrip("/")
    # If caller accidentally included the bucket prefix (e.g. "videos/...") remove it
    bucket_prefix = f"{SUPABASE_STORAGE_BUCKET}/"
    if object_path.startswith(bucket_prefix):
        object_path = object_path[len(bucket_prefix) :]
    # Percent-encode the object path (preserve path separators) to avoid HTTP 400
    encoded_path = urllib.parse.quote(object_path, safe="/")
    return f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/{SUPABASE_STORAGE_BUCKET}/{encoded_path}?upsert=true"


def _build_public_url(object_name: str) -> str:
    object_path = object_name.lstrip("/")
    bucket_prefix = f"{SUPABASE_STORAGE_BUCKET}/"
    if object_path.startswith(bucket_prefix):
        object_path = object_path[len(bucket_prefix) :]
    encoded_path = urllib.parse.quote(object_path, safe="/")
    return f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/public/{SUPABASE_STORAGE_BUCKET}/{encoded_path}"


def upload_file_to_supabase_storage(local_path: Path, object_name: str, fallback_url: str) -> str:
    if not local_path.exists():
        logger.warning("Supabase upload skipped because local file does not exist: %s", local_path)
        return fallback_url

    if not _is_configured():
        logger.warning(
            "Supabase upload skipped because configuration is incomplete. url=%s bucket=%s key_present=%s",
            bool(SUPABASE_URL),
            SUPABASE_STORAGE_BUCKET,
            bool(SUPABASE_KEY),
        )
        return fallback_url

    content_type, _ = mimetypes.guess_type(local_path.name)
    content_type = content_type or "application/octet-stream"
    upload_url = _build_upload_url(object_name)
    headers = _get_headers(content_type)

    try:
        with local_path.open("rb") as fh:
            body = fh.read()

        request = urllib.request.Request(upload_url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=60) as resp:
            status = getattr(resp, "status", None) or getattr(resp, "getcode", lambda: None)()
            if status and status >= 400:
                logger.warning("Supabase upload returned HTTP error status=%s url=%s", status, upload_url)
                return fallback_url

        public_url = _build_public_url(object_name)
        logger.info("Supabase upload succeeded for %s -> %s", object_name, public_url)
        return public_url
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
        logger.exception("Supabase upload failed for %s: %s", object_name, exc)
        return fallback_url


async def upload_video_to_supabase_storage(local_path: Path, object_name: str, fallback_url: str) -> str:
    return await __import__("asyncio").to_thread(upload_file_to_supabase_storage, local_path, object_name, fallback_url)


# ---------------------------
# Delete helpers
# ---------------------------
def _build_delete_url(object_name: str) -> str:
    object_path = object_name.lstrip("/")
    bucket_prefix = f"{SUPABASE_STORAGE_BUCKET}/"
    if object_path.startswith(bucket_prefix):
        object_path = object_path[len(bucket_prefix) :]
    encoded_path = urllib.parse.quote(object_path, safe="/")
    return f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/{SUPABASE_STORAGE_BUCKET}/{encoded_path}"


def delete_file_from_supabase_storage(object_name: str) -> bool:
    """
    Delete a single object from Supabase Storage.
    Returns True on success and False on failure.
    """
    if not _is_configured():
        logger.warning("Supabase delete skipped because configuration is incomplete.")
        return False

    delete_url = _build_delete_url(object_name)
    # Do not set Content-Type for DELETE (Supabase expects no body)
    headers = _get_headers(None)

    try:
        logger.debug("Supabase delete request: url=%s headers=%s object_name=%s", delete_url, headers, object_name)
        request = urllib.request.Request(delete_url, headers=headers, method="DELETE")
        with urllib.request.urlopen(request, timeout=30) as resp:
            status = getattr(resp, "status", None) or getattr(resp, "getcode", lambda: None)()
            if status and status >= 400:
                logger.warning("Supabase delete returned HTTP error status=%s url=%s", status, delete_url)
                return False
        logger.info("Supabase delete succeeded for %s", object_name)
        return True
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
        # If it's an HTTPError, try to capture the response body for debugging
        if isinstance(exc, urllib.error.HTTPError):
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                body = "<could not read body>"
            logger.error(
                "Supabase delete HTTPError for %s: code=%s url=%s body=%s",
                object_name,
                getattr(exc, "code", None),
                getattr(exc, "url", delete_url),
                body,
            )
        logger.exception("Supabase delete failed for %s: %s", object_name, exc)
        return False


async def delete_file_from_supabase_storage_async(object_name: str) -> bool:
    return await __import__("asyncio").to_thread(delete_file_from_supabase_storage, object_name)
