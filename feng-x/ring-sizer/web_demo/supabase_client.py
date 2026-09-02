"""Supabase persistence layer for ring-size-cv web demo.

Graceful degradation: if SUPABASE_URL or SUPABASE_SERVICE_KEY env vars
are missing, all functions return None/empty and the app works without
persistence.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_client = None
_initialized = False


def _get_client():
    """Lazy-init Supabase client. Returns None if persistence is disabled.

    Persistence is disabled when either:
    - SUPABASE_URL / SUPABASE_SERVICE_KEY is missing, or
    - RING_DISABLE_SUPABASE is set to a truthy value (explicit opt-out, so
      local dev sessions don't upload photos + result PNGs to the real
      bucket on every request).
    """
    global _client, _initialized
    if _initialized:
        return _client
    _initialized = True

    disable = os.environ.get("RING_DISABLE_SUPABASE", "").strip().lower()
    if disable in ("1", "true", "yes", "on"):
        logger.info("RING_DISABLE_SUPABASE set — persistence disabled")
        return None

    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    if not url or not key:
        logger.warning("SUPABASE_URL or SUPABASE_SERVICE_KEY not set — persistence disabled")
        return None

    try:
        from supabase import create_client
        _client = create_client(url, key)
        logger.info("Supabase client initialized (%s)", url)
    except Exception as e:
        logger.error("Failed to initialize Supabase client: %s", e)
        _client = None
    return _client


def persistence_enabled() -> bool:
    """True when Supabase persistence is active (env configured and not
    opted out via RING_DISABLE_SUPABASE). Lets an endpoint distinguish
    'disabled in this env' (still report success to the user) from a real
    write failure (surface an error)."""
    return _get_client() is not None


BUCKET = "ring-measurements"


def upload_bytes(data: bytes, storage_path: str, content_type: str) -> Optional[str]:
    """Upload raw bytes to Supabase Storage. Returns public URL or None.

    Used by the web demo to upload an in-memory downscaled JPEG (v7 storage
    diet) without first writing it to a temp file. content_type is explicit
    because the stored object name may keep a legacy extension (e.g. a
    `_result.png` object that now carries JPEG bytes)."""
    client = _get_client()
    if client is None:
        return None
    try:
        client.storage.from_(BUCKET).upload(
            storage_path,
            data,
            file_options={"content-type": content_type},
        )
        logger.info("Storage upload %s: %s bytes", storage_path, len(data))
        return client.storage.from_(BUCKET).get_public_url(storage_path)
    except Exception as e:
        logger.error("Failed to upload %s (%s bytes): %s", storage_path, len(data), e)
        return None


def upload_file(local_path: str, storage_path: str) -> Optional[str]:
    """Upload a file to Supabase Storage. Returns public URL or None."""
    client = _get_client()
    if client is None:
        return None
    try:
        with open(local_path, "rb") as f:
            data = f.read()
        # Determine content type
        suffix = Path(local_path).suffix.lower()
        content_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
        }.get(suffix, "application/octet-stream")

        resp = client.storage.from_(BUCKET).upload(
            storage_path,
            data,
            file_options={"content-type": content_type},
        )
        logger.info("Storage upload %s: %s bytes, response=%s", storage_path, len(data), resp)
        public_url = client.storage.from_(BUCKET).get_public_url(storage_path)
        return public_url
    except Exception as e:
        logger.error("Failed to upload %s (%s bytes): %s", storage_path,
                     os.path.getsize(local_path) if os.path.exists(local_path) else "missing", e)
        return None


def _storage_path_from_public_url(public_url: str) -> Optional[str]:
    """Extract the in-bucket object path from a Supabase public URL.

    Public URLs look like
    `<base>/storage/v1/object/public/ring-measurements/<path>`; newer
    supabase-py may append a `?` query (cache-buster) which we strip.
    Returns the bucket-relative `<path>` (e.g. `photos/f_x.jpg`) or None
    when the URL isn't a public-object URL for our bucket (e.g. a null
    photo_url on a demo run).
    """
    if not public_url:
        return None
    marker = f"/storage/v1/object/public/{BUCKET}/"
    idx = public_url.find(marker)
    if idx == -1:
        return None
    from urllib.parse import unquote
    path = public_url[idx + len(marker):].split("?", 1)[0]
    return unquote(path) or None


def _remove_storage_objects(public_urls: List[str]) -> None:
    """Best-effort delete of storage objects behind a list of public URLs.

    Called after a row delete to avoid orphaning the uploaded photo/result
    objects. Never raises: the row is already gone, and a leftover object
    is not worth failing the request over (failures are logged).
    """
    client = _get_client()
    if client is None:
        return
    paths = [p for p in (_storage_path_from_public_url(u) for u in public_urls) if p]
    if not paths:
        return
    try:
        client.storage.from_(BUCKET).remove(paths)
        logger.info("Removed %d storage object(s): %s", len(paths), paths)
    except Exception as e:
        logger.error("Failed to remove storage objects %s: %s", paths, e)


def save_measurement(record: Dict[str, Any]) -> Optional[str]:
    """Insert a measurement record. Returns row UUID or None."""
    client = _get_client()
    if client is None:
        return None
    try:
        resp = client.table("measurements").insert(record).execute()
        if resp.data and len(resp.data) > 0:
            return resp.data[0].get("id")
        return None
    except Exception as e:
        logger.error("Failed to save measurement: %s", e)
        return None


def save_feedback(record: Dict[str, Any]) -> Optional[str]:
    """Insert a post-shipment fit-feedback row into the `feedback` table.

    Intentionally decoupled from `measurements` (no run_id, no FK) — the
    only link between the two is the normalized `kol_email`, joined at
    analysis time. See doc/v8/PRD.md. Returns row UUID or None (None also
    when persistence is disabled, which the caller treats as success).
    """
    client = _get_client()
    if client is None:
        return None
    try:
        resp = client.table("feedback").insert(record).execute()
        if resp.data and len(resp.data) > 0:
            return resp.data[0].get("id")
        return None
    except Exception as e:
        logger.error("Failed to save feedback: %s", e)
        return None


def list_feedback(limit: int = 500, offset: int = 0) -> List[Dict[str, Any]]:
    """Fetch post-shipment feedback rows for the admin page, newest first."""
    client = _get_client()
    if client is None:
        return []
    try:
        resp = (
            client.table("feedback")
            .select("*")
            .order("submitted_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        logger.error("Failed to list feedback: %s", e)
        return []


def count_feedback() -> Optional[int]:
    """Total feedback rows, ignoring the list limit. None if persistence is
    disabled (lets the admin label distinguish 'unknown' from a real 0)."""
    client = _get_client()
    if client is None:
        return None
    try:
        resp = client.table("feedback").select("id", count="exact", head=True).execute()
        return resp.count
    except Exception as e:
        logger.error("Failed to count feedback: %s", e)
        return None


def _list_prefix_objects(storage, prefix: str) -> List[Dict[str, Any]]:
    """Paginate storage.list(prefix) and return every real object (skips the
    folder placeholder row that has no size metadata)."""
    out: List[Dict[str, Any]] = []
    offset = 0
    page = 100
    while True:
        resp = storage.list(prefix, {"limit": page, "offset": offset})
        if not resp:
            break
        for o in resp:
            md = o.get("metadata") or {}
            if md.get("size") is not None:
                out.append(o)
        if len(resp) < page:
            break
        offset += page
    return out


# Free-tier storage quota; used only to compute a headroom % for the admin
# panel. Supabase enforces 1 GB; we surface headroom against a slightly
# conservative 1.0 GB so the number nudges before the hard wall.
STORAGE_QUOTA_BYTES = 1024 * 1024 * 1024


def storage_usage() -> Optional[Dict[str, Any]]:
    """Summarize bucket usage for the admin dashboard: per-prefix object count
    + bytes, grand total, and headroom vs the free-tier quota. Returns None
    when persistence is disabled so the UI can show 'unknown' rather than 0.

    Walks the storage list API (the bucket has no size column); a few hundred
    objects across three prefixes is one quick paginated sweep per prefix.
    """
    client = _get_client()
    if client is None:
        return None
    try:
        storage = client.storage.from_(BUCKET)
        prefixes = {}
        total = 0
        for prefix in ("photos", "results", "feedback"):
            objs = _list_prefix_objects(storage, prefix)
            size = sum((o.get("metadata") or {}).get("size", 0) for o in objs)
            prefixes[prefix] = {"objects": len(objs), "bytes": size}
            total += size
        return {
            "prefixes": prefixes,
            "total_bytes": total,
            "quota_bytes": STORAGE_QUOTA_BYTES,
            "used_fraction": (total / STORAGE_QUOTA_BYTES
                              if STORAGE_QUOTA_BYTES else None),
        }
    except Exception as e:
        logger.error("Failed to compute storage usage: %s", e)
        return None


def list_measurements(limit: int = 200, offset: int = 0) -> List[Dict[str, Any]]:
    """Fetch measurements for admin page, newest first."""
    client = _get_client()
    if client is None:
        return []
    try:
        resp = (
            client.table("measurements")
            .select("*")
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        logger.error("Failed to list measurements: %s", e)
        return []


def count_measurements() -> Optional[int]:
    """Total measurement rows, ignoring the list limit. None if persistence
    is disabled (lets the admin label distinguish 'unknown' from a real 0)."""
    client = _get_client()
    if client is None:
        return None
    try:
        resp = client.table("measurements").select("id", count="exact", head=True).execute()
        return resp.count
    except Exception as e:
        logger.error("Failed to count measurements: %s", e)
        return None


STATS_COLUMNS = (
    "id,created_at,kol_name,kol_email,mode,ring_model,confidence,fail_reason,"
    "overall_best_size,ring_fit,gt_index_size,gt_middle_size,gt_ring_size,"
    "finger_index,photo_url,per_finger,feedback_rating,feedback_message"
)


def list_measurements_for_stats(limit: int = 5000) -> List[Dict[str, Any]]:
    """Lightweight projection used by the admin stats endpoint.

    Skips `result_json` (the heaviest blob). `per_finger` is included so the
    size-distribution chart can use the index-finger size and detect demo
    runs (`photo_url` is null when the user clicks "try with sample").
    """
    client = _get_client()
    if client is None:
        return []
    try:
        resp = (
            client.table("measurements")
            .select(STATS_COLUMNS)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        logger.error("Failed to list measurements for stats: %s", e)
        return []


FEEDBACK_ALLOWED_FIELDS = {"feedback_rating", "feedback_message"}

# Return values for update_measurement_feedback. Stringly-typed because the
# caller (the /api/feedback endpoint) needs to distinguish "persistence is
# turned off in this env" (still report success to the user) from "the row
# really doesn't exist" (surface a real error).
FEEDBACK_OK = "ok"
FEEDBACK_NO_ROW = "no_row"
FEEDBACK_DISABLED = "disabled"
FEEDBACK_ERROR = "error"


def update_measurement_feedback(run_id: str, updates: Dict[str, Any]) -> str:
    """Attach feedback (rating + message) to an existing measurement row.

    Looks up the row by `run_id` (stamped at measure-time by app.py) and
    patches only the whitelisted feedback columns. Pass only the columns
    you actually want to change — keys not present are left untouched.
    Returns one of FEEDBACK_OK / FEEDBACK_NO_ROW / FEEDBACK_DISABLED /
    FEEDBACK_ERROR so the caller can decide whether to surface a failure.
    """
    client = _get_client()
    if client is None:
        return FEEDBACK_DISABLED
    safe = {k: v for k, v in updates.items() if k in FEEDBACK_ALLOWED_FIELDS}
    if not safe or not run_id:
        return FEEDBACK_NO_ROW
    try:
        resp = client.table("measurements").update(safe).eq("run_id", run_id).execute()
        return FEEDBACK_OK if resp.data else FEEDBACK_NO_ROW
    except Exception as e:
        logger.error("Failed to update feedback for run %s: %s", run_id, e)
        return FEEDBACK_ERROR


def delete_measurement(measurement_id: str) -> bool:
    """Delete a measurement record by ID, sweeping its photo + result
    objects from storage too (best-effort — the row delete is authoritative;
    demo runs with null photo_url simply have nothing to sweep)."""
    client = _get_client()
    if client is None:
        return False
    try:
        resp = (
            client.table("measurements")
            .select("photo_url,result_url")
            .eq("id", measurement_id)
            .execute()
        )
        rows = resp.data or []
        client.table("measurements").delete().eq("id", measurement_id).execute()
        urls = [r.get("photo_url") for r in rows] + [r.get("result_url") for r in rows]
        _remove_storage_objects(urls)
        return True
    except Exception as e:
        logger.error("Failed to delete %s: %s", measurement_id, e)
        return False


def delete_feedback(feedback_id: str) -> bool:
    """Delete a post-shipment fit-feedback row by ID, sweeping its photo
    object from storage too (best-effort — the row delete is authoritative)."""
    client = _get_client()
    if client is None:
        return False
    try:
        resp = client.table("feedback").select("photo_url").eq("id", feedback_id).execute()
        rows = resp.data or []
        client.table("feedback").delete().eq("id", feedback_id).execute()
        _remove_storage_objects([r.get("photo_url") for r in rows])
        return True
    except Exception as e:
        logger.error("Failed to delete feedback %s: %s", feedback_id, e)
        return False


GT_ALLOWED_FIELDS = {"gt_index_size", "gt_middle_size", "gt_ring_size", "ring_fit", "gt_best_finger", "gt_notes"}


def update_ground_truth(measurement_id: str, updates: Dict[str, Any]) -> bool:
    """Update only ground-truth columns for a measurement."""
    client = _get_client()
    if client is None:
        return False
    # Whitelist filter
    safe = {k: v for k, v in updates.items() if k in GT_ALLOWED_FIELDS}
    if not safe:
        return False
    try:
        client.table("measurements").update(safe).eq("id", measurement_id).execute()
        return True
    except Exception as e:
        logger.error("Failed to update GT for %s: %s", measurement_id, e)
        return False
