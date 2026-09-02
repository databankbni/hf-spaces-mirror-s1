"""Unified per-generate run folders under each tenant.

One Generate produces one stamped directory:

``{DATA_DIR}/tenants/<tenant_id>/generate-runs/{UTC_YYYYMMDD-HHMMSS}_{draft_id}/``

That folder holds both the machine ``retrieval_manifest.json`` (written as
sections complete) and human-readable section bundles (written at export).
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from backend.storage import tenant_store

logger = logging.getLogger(__name__)

# One run directory per (tenant, draft) for the life of an in-flight generate.
_active_run_dirs: dict[tuple[str, str], Path] = {}
_active_lock = threading.Lock()

RETRIEVAL_MANIFEST_NAME = "retrieval_manifest.json"
RUN_SUMMARY_NAME = "run_summary.json"


def generate_runs_dir(tenant_id: str) -> Path:
    """``{tenant_root}/generate-runs/``."""
    d = tenant_store.tenant_root(tenant_id) / "generate-runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def utc_run_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def safe_draft_id(draft_id: str) -> str:
    return tenant_store.path_safe_segment(draft_id, fallback="report")


def _is_stamped_run_folder(name: str, safe: str) -> bool:
    """``YYYYMMDD-HHMMSS_{id}`` or ``YYYYMMDD-HHMMSS_{id}_{n}``."""
    if len(name) < 16 or name[8] != "-" or name[15] != "_":
        return False
    return name.endswith(f"_{safe}") or f"_{safe}_" in name


def list_run_dirs(tenant_id: str, draft_id: str) -> list[Path]:
    """Existing generate-run folders for this draft, oldest → newest."""
    safe = safe_draft_id(draft_id)
    root = generate_runs_dir(tenant_id)
    out = [p for p in root.iterdir() if p.is_dir() and _is_stamped_run_folder(p.name, safe)]
    return sorted(out, key=lambda p: p.name)


def allocate_run_dir(tenant_id: str, draft_id: str) -> Path:
    """Allocate (once per in-flight generate) ``{stamp}_{draft_id}/``."""
    safe = safe_draft_id(draft_id)
    key = (tenant_id, safe)
    with _active_lock:
        existing = _active_run_dirs.get(key)
        if existing is not None:
            return existing
        root = generate_runs_dir(tenant_id)
        stamp = utc_run_stamp()
        path = root / f"{stamp}_{safe}"
        n = 2
        while path.exists():
            path = root / f"{stamp}_{safe}_{n}"
            n += 1
        path.mkdir(parents=True, exist_ok=True)
        _active_run_dirs[key] = path
        return path


def peek_active_run_dir(tenant_id: str, draft_id: str) -> Path | None:
    """In-flight run dir for this draft, if any."""
    safe = safe_draft_id(draft_id)
    with _active_lock:
        return _active_run_dirs.get((tenant_id, safe))


def resolve_run_dir(
    tenant_id: str,
    draft_id: str,
    *,
    for_write: bool = False,
) -> Path | None:
    """Active run dir, else newest on disk; ``for_write`` allocates if missing."""
    active = peek_active_run_dir(tenant_id, draft_id)
    if active is not None:
        return active
    existing = list_run_dirs(tenant_id, draft_id)
    if existing:
        return existing[-1]
    if for_write:
        return allocate_run_dir(tenant_id, draft_id)
    return None


def release_active_run(tenant_id: str, draft_id: str) -> None:
    """Drop in-process lock so the next Generate gets a new stamped folder."""
    safe = safe_draft_id(draft_id)
    with _active_lock:
        _active_run_dirs.pop((tenant_id, safe), None)


def clear_active_runs() -> None:
    """Test helper — reset in-process active run map."""
    with _active_lock:
        _active_run_dirs.clear()


def retrieval_manifest_file(run_dir: Path) -> Path:
    return run_dir / RETRIEVAL_MANIFEST_NAME


def run_summary_file(run_dir: Path) -> Path:
    return run_dir / RUN_SUMMARY_NAME
