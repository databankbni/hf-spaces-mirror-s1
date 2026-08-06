#!/usr/bin/env python3
"""Read-only DB access + resolution for the Georgian-financials MCP server.

This module is the single place the MCP server resolves the SQLite database and
opens connections. Two hard rules, both inherited from the dashboard's painful
history (a past in-place rebuild via hardlink corrupted data):

1. **Every connection is opened READ-ONLY** via the SQLite URI ``mode=ro`` so a
   bug in a tool can never mutate the production DB.
2. **DB resolution mirrors ``app.py::_resolve_db_path``** — a local file wins;
   otherwise we download ``georgian-financials-v2.db`` from the Hugging Face
   Dataset ``DMDaudio/findashboard-data`` (with a head-SHA sidecar check + local
   cache) so the server stays in sync with what the Space serves.

The ``FINDASH_DB_PATH`` environment variable overrides everything: point it at a
local DB (e.g. the dev copy at the repo root) and no network call is made. This
is the recommended setup for local development and the test suite.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import time
from pathlib import Path

# Dataset coordinates — identical to app.py so the MCP server caches the same DB
# the Space downloads.
_DATASET_REPO = "DMDaudio/findashboard-data"
_DB_FILENAME = "georgian-financials-v2.db"

# Repo root = parent of this file's parent (mcp/ lives at the repo root).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Memoize the resolved path, but re-check periodically: resolution can do a
# network round-trip (HfApi().dataset_info) and we never want that on every tool
# call — but a long-running remote server that NEVER re-checks serves a stale DB
# forever after the Dataset head moves (the old behaviour; required a manual
# Space restart after every DB upload). The interval is tunable via
# FINDASH_DB_RECHECK_S (seconds; 0 disables re-checking entirely).
_RESOLVED_DB_PATH: str | None = None
_RESOLVED_AT: float = 0.0
_RECHECK_INTERVAL_S = float(os.environ.get("FINDASH_DB_RECHECK_S", "3600"))


def _resolve_db_path() -> str:
    """Return an absolute path to the financials DB, downloading it if needed.

    Resolution order:
      1. ``FINDASH_DB_PATH`` env var, if set and the file exists (dev/test).
      2. A ``georgian-financials-v2.db`` sitting next to the repo root (the dev
         copy — gitignored, present only in the full dev checkout).
      3. Download from the HF Dataset into a local cache (``~/.cache`` style via
         ``hf_hub_download``, copied next to the repo root), re-downloading only
         when the Dataset head SHA differs from the cached sidecar — exactly the
         behaviour of ``app.py::_resolve_db_path``.

    Raises:
        FileNotFoundError: if ``FINDASH_DB_PATH`` is set but points nowhere.
    """
    # 1. Explicit override (preferred for local dev / tests).
    env_path = os.environ.get("FINDASH_DB_PATH")
    if env_path:
        p = Path(env_path).expanduser()
        if not p.exists():
            raise FileNotFoundError(
                f"FINDASH_DB_PATH is set to '{env_path}' but no file exists there. "
                "Point it at a local georgian-financials-v2.db or unset it to "
                "download from the HF Dataset."
            )
        return str(p)

    # 2. Local dev copy next to the repo root.
    local_db = _PROJECT_ROOT / _DB_FILENAME
    if local_db.exists():
        return str(local_db)

    # 3. Download from the HF Dataset with a head-SHA cache check.
    cache_dir = _PROJECT_ROOT
    target = cache_dir / _DB_FILENAME
    sha_sidecar = cache_dir / f"{_DB_FILENAME}.sha"

    from huggingface_hub import HfApi, hf_hub_download

    try:
        remote_sha = HfApi().dataset_info(_DATASET_REPO).sha
    except Exception:
        remote_sha = None

    cached_sha = sha_sidecar.read_text().strip() if sha_sidecar.exists() else None
    if target.exists() and remote_sha is not None and cached_sha == remote_sha:
        return str(target)
    if target.exists() and remote_sha is None:
        # Offline / API down — trust the cache rather than crash.
        return str(target)

    downloaded = hf_hub_download(
        repo_id=_DATASET_REPO,
        filename=_DB_FILENAME,
        repo_type="dataset",
        # token=None → uses HF_TOKEN env var if the Dataset is private.
    )
    # Copy to a temp file then atomically swap, so a concurrent tool call
    # holding a read connection never sees a half-copied DB (matters now that
    # the periodic re-check can re-download mid-serve).
    tmp = target.with_suffix(target.suffix + ".tmp")
    shutil.copy2(downloaded, tmp)
    os.replace(tmp, target)
    if remote_sha:
        sha_sidecar.write_text(remote_sha)
    return str(target)


def resolve_db_path() -> str:
    """Memoized public accessor for the resolved DB path (see ``_resolve_db_path``).

    Re-resolves after ``_RECHECK_INTERVAL_S`` (default 1h) so a long-running
    server picks up a newly-published Dataset DB without a process restart.
    Dev/test paths (env var / local file) short-circuit inside
    ``_resolve_db_path`` with no network cost, so the periodic re-check is
    effectively free outside the download branch. If the re-check itself
    fails (e.g. transient network error), we keep serving the last good path.
    """
    global _RESOLVED_DB_PATH, _RESOLVED_AT
    now = time.monotonic()
    stale = (
        _RECHECK_INTERVAL_S > 0
        and _RESOLVED_DB_PATH is not None
        and (now - _RESOLVED_AT) >= _RECHECK_INTERVAL_S
    )
    if _RESOLVED_DB_PATH is None or stale:
        try:
            _RESOLVED_DB_PATH = _resolve_db_path()
            _RESOLVED_AT = now
        except Exception:
            if _RESOLVED_DB_PATH is None:
                raise
            # Keep the last good path; retry on the next call after interval.
            _RESOLVED_AT = now
    return _RESOLVED_DB_PATH


def connect_ro(db_path: str | None = None) -> sqlite3.Connection:
    """Open a READ-ONLY SQLite connection to the financials DB.

    Uses the ``file:...?mode=ro`` URI so the connection physically cannot write.
    Sets ``row_factory`` to ``sqlite3.Row`` for dict-style access. Callers own
    the connection lifecycle and must ``close()`` it (use ``with closing(...)``).

    Args:
        db_path: explicit path; defaults to :func:`resolve_db_path`.

    Returns:
        sqlite3.Connection: a read-only connection.
    """
    path = db_path or resolve_db_path()
    # as_uri() handles Windows drive letters / spaces correctly.
    uri = f"{Path(path).resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn
