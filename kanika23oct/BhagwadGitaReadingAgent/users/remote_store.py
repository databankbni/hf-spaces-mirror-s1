# ---------------------------------------------------------------------------
# users/remote_store.py — durable mirror of users.sqlite to a HF dataset repo.
#
# HF free Spaces have an ephemeral filesystem: profiles and bookmarks written
# at runtime are wiped on every restart/rebuild. To make them persist we mirror
# the local users.sqlite to a PRIVATE Hugging Face *dataset* repo:
#   • pull_users_db()  — on startup, download the durable copy into data/.
#   • push_users_db()  — after a profile/bookmark change, upload it back.
#
# Sync is active only in production (SPACE_ID set by HF) or when a developer
# opts in locally with GITA_USERDATA_SYNC=1, so ordinary local runs stay
# isolated from the live user data.
# ---------------------------------------------------------------------------

from __future__ import annotations

import os
import shutil

from config import (
    REFLECTIONS_DB_PATH,
    REFLECTIONS_FILE,
    ROOT,
    USERDATA_FILE,
    USERDATA_REPO_ID,
    USERS_DB_PATH,
)


def _read_token() -> str | None:
    """Resolve the HF token: HF_TOKEN secret on a Space, AccessToken.txt locally."""
    on_space = bool(os.environ.get("SPACE_ID"))
    fallback = ROOT.parent / "AccessToken.txt"

    def _from_env() -> str | None:
        tok = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
        if tok and tok.strip():
            return tok.strip()
        try:
            from huggingface_hub import get_token

            tok = get_token()
        except Exception:  # noqa: BLE001
            tok = None
        return tok.strip() if tok else None

    def _from_file() -> str | None:
        if fallback.exists():
            tok = fallback.read_text(encoding="utf-8").strip()
            return tok or None
        return None

    return _from_env() if on_space else (_from_file() or _from_env())


def sync_enabled() -> bool:
    """Mirror user data only in prod (on a Space) or when explicitly opted in."""
    return bool(os.environ.get("SPACE_ID") or os.environ.get("GITA_USERDATA_SYNC"))


def ensure_repo(token: str) -> None:
    """Create the private dataset repo if it does not exist yet (idempotent)."""
    from huggingface_hub import HfApi

    HfApi(token=token).create_repo(
        repo_id=USERDATA_REPO_ID,
        repo_type="dataset",
        private=True,
        exist_ok=True,
    )


def pull_users_db() -> bool:
    """Download users.sqlite from the dataset into data/ so the Space resumes
    with the durable copy. Best-effort; returns True only if a copy was pulled."""
    if not sync_enabled():
        return False
    token = _read_token()
    if not token:
        print("[userdata] no token available; skipping pull")
        return False
    try:
        from huggingface_hub import hf_hub_download
        from huggingface_hub.utils import EntryNotFoundError, RepositoryNotFoundError

        try:
            path = hf_hub_download(
                repo_id=USERDATA_REPO_ID,
                repo_type="dataset",
                filename=USERDATA_FILE,
                token=token,
            )
        except (EntryNotFoundError, RepositoryNotFoundError):
            print("[userdata] no remote users.sqlite yet (first run)")
            return False

        USERS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, USERS_DB_PATH)
        print("[userdata] pulled users.sqlite from dataset")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[userdata] pull skipped: {exc}")
        return False


def push_users_db() -> bool:
    """Upload the local users.sqlite back to the dataset so the change survives
    the next restart. Best-effort; never raises."""
    if not sync_enabled():
        return False
    if not USERS_DB_PATH.exists():
        return False
    token = _read_token()
    if not token:
        return False
    try:
        from huggingface_hub import HfApi

        ensure_repo(token)
        HfApi(token=token).upload_file(
            path_or_fileobj=str(USERS_DB_PATH),
            path_in_repo=USERDATA_FILE,
            repo_id=USERDATA_REPO_ID,
            repo_type="dataset",
            commit_message="Update user profiles/bookmarks",
        )
        print("[userdata] pushed users.sqlite to dataset")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[userdata] push skipped: {exc}")
        return False


def pull_reflections_db() -> bool:
    """Download reflections.sqlite from the dataset so previously-generated AI
    reflections survive a restart and are never regenerated. Best-effort."""
    if not sync_enabled():
        return False
    token = _read_token()
    if not token:
        return False
    try:
        from huggingface_hub import hf_hub_download
        from huggingface_hub.utils import EntryNotFoundError, RepositoryNotFoundError

        try:
            path = hf_hub_download(
                repo_id=USERDATA_REPO_ID,
                repo_type="dataset",
                filename=REFLECTIONS_FILE,
                token=token,
            )
        except (EntryNotFoundError, RepositoryNotFoundError):
            print("[reflections] no remote reflections.sqlite yet (first run)")
            return False

        REFLECTIONS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, REFLECTIONS_DB_PATH)
        print("[reflections] pulled reflections.sqlite from dataset")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[reflections] pull skipped: {exc}")
        return False


def push_reflections_db() -> bool:
    """Upload reflections.sqlite back to the dataset so a newly-generated AI
    reflection is reused forever (no regeneration on restart). Best-effort."""
    if not sync_enabled():
        return False
    if not REFLECTIONS_DB_PATH.exists():
        return False
    token = _read_token()
    if not token:
        return False
    try:
        from huggingface_hub import HfApi

        ensure_repo(token)
        HfApi(token=token).upload_file(
            path_or_fileobj=str(REFLECTIONS_DB_PATH),
            path_in_repo=REFLECTIONS_FILE,
            repo_id=USERDATA_REPO_ID,
            repo_type="dataset",
            commit_message="Update cached AI reflections",
        )
        print("[reflections] pushed reflections.sqlite to dataset")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[reflections] push skipped: {exc}")
        return False
