#!/usr/bin/env python3
"""Change-gated, read-after-write synchronization to the HF Dataset.

This module distributes compact local artifacts only. It never fetches Titan007,
invokes a model, produces a pick, or writes bankroll data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = ROOT / "hf_sync_state"


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def artifact_target(artifact: dict[str, Any]) -> tuple[str, str] | None:
    """Return Dataset path and state key for a dated compact artifact."""
    kind = str(artifact.get("artifact_type", "packet")).strip()
    pool_date = str(artifact.get("pool_date") or artifact.get("source_date") or "").strip()
    match_id = str(artifact.get("match_id", "")).strip()
    if not pool_date:
        return None
    if kind == "packet" and match_id:
        return f"data/compact_packets/{pool_date}/{match_id}.json", f"packet:{pool_date}:{match_id}"
    if kind == "hot_pool":
        return f"data/hot_match_pool/{pool_date}.json", f"hot_pool:{pool_date}"
    if kind == "source_status":
        return f"data/source_status/{pool_date}.json", f"source_status:{pool_date}"
    if kind == "crow_screener" and match_id:
        return f"data/crow_screener/{pool_date}/{match_id}.json", f"crow_screener:{pool_date}:{match_id}"
    return None


def sync_if_changed(api: Any, repo_id: str, artifact: dict[str, Any], state_dir: Path, *, dry_run: bool = False) -> dict[str, Any]:
    # A market packet is a freshness-bearing artifact. The distribution state
    # therefore includes captured_at and its full freshness contract: unchanged
    # odds still need a cadence heartbeat so HF cannot serve an expired packet.
    # canonical_sha256 remains the separate price/identity change fingerprint.
    canonical_digest = str(artifact.get("canonical_sha256") or "").strip()
    digest = _digest(artifact)
    target = artifact_target(artifact)
    if target is None:
        return {"status": "INVALID_ARTIFACT", "uploaded": False, "reason": "dated_supported_artifact_required"}
    path_in_repo, state_key = target
    manifest_path = state_dir / "hf_sync_manifest.json"
    manifest = _read(manifest_path, {})
    if manifest.get(state_key) == digest:
        return {"status": "UNCHANGED", "uploaded": False, "state_key": state_key, "canonical_sha256": canonical_digest or digest, "artifact_sha256": digest, "path_in_repo": path_in_repo}
    if dry_run:
        return {"status": "DRY_RUN_CHANGED", "uploaded": False, "state_key": state_key, "canonical_sha256": canonical_digest or digest, "artifact_sha256": digest, "path_in_repo": path_in_repo}
    outgoing = state_dir / "outgoing" / path_in_repo
    _write(outgoing, artifact)
    try:
        api.upload_file(
            path_or_fileobj=str(outgoing), path_in_repo=path_in_repo, repo_id=repo_id,
            repo_type="dataset", commit_message=f"data-only:{state_key}:{digest[:12]}",
        )
        readback = api.hf_hub_download(repo_id=repo_id, repo_type="dataset", filename=path_in_repo, force_download=True)
        remote = _read(Path(readback), None)
        if not isinstance(remote, dict) or _digest(remote) != _digest(artifact):
            return {"status": "READBACK_MISMATCH", "uploaded": False, "state_key": state_key, "path_in_repo": path_in_repo}
    except Exception as exc:
        return {"status": "UPLOAD_OR_READBACK_FAILED", "uploaded": False, "state_key": state_key, "path_in_repo": path_in_repo, "error_type": type(exc).__name__, "reason": str(exc)[:300]}
    manifest[state_key] = digest
    _write(manifest_path, manifest)
    return {"status": "UPLOADED_VERIFIED", "uploaded": True, "state_key": state_key, "canonical_sha256": canonical_digest or digest, "artifact_sha256": digest, "path_in_repo": path_in_repo}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--state-dir", default=str(DEFAULT_STATE))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    artifact = _read(Path(args.artifact), None)
    if not isinstance(artifact, dict):
        print(json.dumps({"status": "INVALID_ARTIFACT", "uploaded": False, "reason": "artifact_json_invalid"}, ensure_ascii=False))
        return 20
    try:
        from huggingface_hub import HfApi
    except ImportError:
        print(json.dumps({"status": "HF_CLIENT_UNAVAILABLE", "uploaded": False}, ensure_ascii=False))
        return 20
    result = sync_if_changed(HfApi(), args.repo_id, artifact, Path(args.state_dir), dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"UPLOADED_VERIFIED", "UNCHANGED", "DRY_RUN_CHANGED"} else 20


if __name__ == "__main__":
    sys.exit(main())
