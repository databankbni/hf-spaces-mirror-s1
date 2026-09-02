"""Public dataset operations for MyShub API.

Stores shop content as individual JSON files in a public HF dataset.
This allows unlimited scaling and free public access.
"""
import os
import json
import threading
from datetime import datetime, timezone
from io import BytesIO

from huggingface_hub import HfApi, hf_hub_download
from huggingface_hub.utils import EntryNotFoundError

HF_TOKEN = os.getenv("HF_TOKEN")
REPO_ID = os.getenv("DATASET_PUBLIC", "emltechstudio/myshub-db-public")

api = HfApi(token=HF_TOKEN)
_lock = threading.Lock()

# Local disk cache path
LOCAL_CACHE_DIR = "/data/shops"
os.makedirs(LOCAL_CACHE_DIR, exist_ok=True)

# Track dirty files for batch sync
_dirty_files = set()
_analytics_dirty = set()  # Track shops with analytics changes
_sync_timer = None
SYNC_DELAY = 30.0  # Sync to public dataset every 30 seconds


def _get_local_path(slug: str) -> str:
    return os.path.join(LOCAL_CACHE_DIR, f"{slug.lower().strip()}.json")


def _sync_to_public():
    """Sync dirty local files to public dataset."""
    global _dirty_files, _analytics_dirty, _sync_timer
    with _lock:
        files_to_sync = list(_dirty_files)
        _dirty_files.clear()
        _analytics_dirty.clear()
        _sync_timer = None

    for slug in files_to_sync:
        local_path = _get_local_path(slug)
        if os.path.exists(local_path):
            try:
                with open(local_path, "r") as f:
                    content = f.read()
                api.upload_file(
                    path_or_fileobj=content.encode("utf-8"),
                    path_in_repo=f"shops/{slug.lower().strip()}.json",
                    repo_id=REPO_ID,
                    repo_type="dataset",
                    token=HF_TOKEN
                )
                print(f"[Public Sync] {slug}")
            except Exception as e:
                print(f"[Public Sync Error {slug}] {e}")
                # Re-add to dirty if failed
                with _lock:
                    _dirty_files.add(slug)


def _schedule_sync():
    global _sync_timer
    if _sync_timer is not None:
        _sync_timer.cancel()
    _sync_timer = threading.Timer(SYNC_DELAY, _sync_to_public)
    _sync_timer.daemon = True
    _sync_timer.start()


def restore_from_public():
    """Download all shop files from public dataset to local disk on startup."""
    try:
        # List files in shops/ directory
        files = api.list_repo_files(
            repo_id=REPO_ID,
            repo_type="dataset",
            token=HF_TOKEN
        )
        shop_files = [f for f in files if f.startswith("shops/") and f.endswith(".json")]

        for file_path in shop_files:
            slug = file_path.replace("shops/", "").replace(".json", "")
            try:
                downloaded = hf_hub_download(
                    repo_id=REPO_ID,
                    filename=file_path,
                    repo_type="dataset",
                    token=HF_TOKEN,
                    local_dir=LOCAL_CACHE_DIR,
                    local_dir_use_symlinks=False
                )
                # Move to correct location if needed
                target = _get_local_path(slug)
                if downloaded != target and os.path.exists(downloaded):
                    os.rename(downloaded, target)
                print(f"[Restore] {slug}")
            except Exception as e:
                print(f"[Restore Error {slug}] {e}")

        print(f"[Restore] Restored {len(shop_files)} shops")
    except Exception as e:
        print(f"[Restore Error] {e}")


def get_shop_content(slug: str) -> dict | None:
    """Get shop content from local disk (fast). Falls back to public dataset."""
    slug = slug.lower().strip()
    local_path = _get_local_path(slug)

    # Try local first
    if os.path.exists(local_path):
        try:
            with open(local_path, "r") as f:
                return json.load(f)
        except Exception:
            pass

    # Fallback to public dataset
    try:
        downloaded = hf_hub_download(
            repo_id=REPO_ID,
            filename=f"shops/{slug}.json",
            repo_type="dataset",
            token=HF_TOKEN,
            local_dir=LOCAL_CACHE_DIR,
            local_dir_use_symlinks=False
        )
        target = _get_local_path(slug)
        if downloaded != target and os.path.exists(downloaded):
            os.rename(downloaded, target)
        with open(target, "r") as f:
            return json.load(f)
    except Exception:
        return None


def save_shop_content(slug: str, data: dict, sync: bool = True):
    """Save shop content to local disk and queue for public sync.

    Args:
        slug: Shop slug
        data: Shop content data
        sync: If False, don't sync to public dataset (for analytics only)
    """
    slug = slug.lower().strip()
    data["updated_at"] = datetime.now(timezone.utc).isoformat()

    local_path = _get_local_path(slug)
    with open(local_path, "w") as f:
        json.dump(data, f, indent=2)

    if sync:
        with _lock:
            _dirty_files.add(slug)
            _schedule_sync()


def log_analytics_only(slug: str, analytics_data: dict):
    """Log analytics without triggering full public sync.
    Writes to local disk only, syncs with next batch."""
    slug = slug.lower().strip()
    local_path = _get_local_path(slug)

    # Read current content
    content = {}
    if os.path.exists(local_path):
        try:
            with open(local_path, "r") as f:
                content = json.load(f)
        except Exception:
            pass

    # Update analytics
    content["analytics"] = analytics_data
    content["updated_at"] = datetime.now(timezone.utc).isoformat()

    # Write to local disk only (no sync)
    with open(local_path, "w") as f:
        json.dump(content, f, indent=2)

    # Mark for batch sync (but don't trigger immediate sync)
    with _lock:
        _analytics_dirty.add(slug)
        if slug not in _dirty_files:
            _dirty_files.add(slug)
        if _sync_timer is None:
            _schedule_sync()


def delete_shop_content(slug: str):
    """Delete shop content from local and public dataset."""
    slug = slug.lower().strip()
    local_path = _get_local_path(slug)
    if os.path.exists(local_path):
        os.remove(local_path)

    try:
        api.delete_file(
            path_in_repo=f"shops/{slug}.json",
            repo_id=REPO_ID,
            repo_type="dataset",
            token=HF_TOKEN
        )
    except Exception:
        pass


def list_all_shops_content() -> list[dict]:
    """List all shop content from local disk."""
    shops = []
    if os.path.exists(LOCAL_CACHE_DIR):
        for filename in os.listdir(LOCAL_CACHE_DIR):
            if filename.endswith(".json"):
                try:
                    with open(os.path.join(LOCAL_CACHE_DIR, filename), "r") as f:
                        shops.append(json.load(f))
                except Exception:
                    pass
    return shops


def force_sync():
    """Force immediate sync to public dataset."""
    _sync_to_public()


import atexit
atexit.register(force_sync)
