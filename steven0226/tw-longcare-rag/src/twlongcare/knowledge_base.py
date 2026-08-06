"""Versioned, idempotent law publication and index activation primitives."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import DATA_DIR

LAW_VERSIONS_DIR = DATA_DIR / "versions" / "laws"
LAW_MANIFEST_PATH = DATA_DIR / "law_version_manifest.json"
INDEX_MANIFEST_PATH = DATA_DIR / "index_manifest.json"


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def active_laws_path(
    *,
    current_path: Path = DATA_DIR / "laws.json",
    versions_dir: Path = LAW_VERSIONS_DIR,
    index_manifest_path: Path = INDEX_MANIFEST_PATH,
) -> Path:
    """Return the immutable law snapshot paired with the active index.

    A newly fetched law snapshot becomes the build candidate immediately, but
    serving must keep the prior law text until the candidate index passes
    retrieval regression and its manifest is atomically activated.
    """
    if not index_manifest_path.exists():
        return current_path
    try:
        manifest = json.loads(index_manifest_path.read_text(encoding="utf-8"))
        law_version = str(manifest.get("law_version") or "").strip()
        snapshot = versions_dir / law_version / "laws.json"
        if law_version and snapshot.exists():
            return snapshot
    except (OSError, ValueError, TypeError):
        pass
    return current_path


def article_content_hash(article: dict) -> str:
    """Hash content-bearing fields; fetch timestamps never cause a false change."""
    return sha256_json({
        "pcode": article["pcode"],
        "article_no": article["article_no"],
        "chapter": article.get("chapter"),
        "content": article["content"],
        "law_modified_date": article.get("law_modified_date", ""),
    })


def build_law_manifest(data: dict) -> dict:
    article_hashes = {
        f"{article['pcode']}-{article['article_no']}": article_content_hash(article)
        for article in data["articles"]
    }
    documents: dict[str, list[tuple[str, str]]] = {}
    for article in data["articles"]:
        article_id = f"{article['pcode']}-{article['article_no']}"
        documents.setdefault(article["pcode"], []).append(
            (article_id, article_hashes[article_id])
        )
    document_hashes = {
        pcode: sha256_json(sorted(items))
        for pcode, items in documents.items()
    }
    corpus_hash = sha256_json(sorted(article_hashes.items()))
    source_version = str(
        data.get("meta", {}).get("source_update_date") or "unversioned"
    )
    version = f"{source_version}-{corpus_hash[:12]}"
    return {
        "schema_version": "law-manifest-v1",
        "version": version,
        "source": data.get("meta", {}).get("source", "unknown"),
        "source_update_date": source_version,
        "corpus_hash": corpus_hash,
        "article_count": len(article_hashes),
        "document_count": len(document_hashes),
        "article_hashes": article_hashes,
        "document_hashes": document_hashes,
    }


def diff_law_manifests(previous: dict | None, current: dict) -> dict:
    before = (previous or {}).get("article_hashes", {})
    after = current.get("article_hashes", {})
    before_ids, after_ids = set(before), set(after)
    return {
        "schema_version": "law-diff-v1",
        "from_version": (previous or {}).get("version"),
        "to_version": current["version"],
        "new": sorted(after_ids - before_ids),
        "deleted": sorted(before_ids - after_ids),
        "changed": sorted(
            article_id
            for article_id in before_ids & after_ids
            if before[article_id] != after[article_id]
        ),
        "unchanged_count": sum(
            before[article_id] == after[article_id]
            for article_id in before_ids & after_ids
        ),
    }


def atomic_write_json(path: Path, value: Any) -> None:
    """Write and fsync a sibling temp file before one atomic replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


@dataclass(frozen=True)
class LawPublishResult:
    changed: bool
    version: str
    snapshot_path: Path
    manifest_path: Path
    diff: dict


def publish_law_version(
    data: dict,
    *,
    out_path: Path = DATA_DIR / "laws.json",
    versions_dir: Path = LAW_VERSIONS_DIR,
    manifest_path: Path = LAW_MANIFEST_PATH,
) -> LawPublishResult:
    """Persist an immutable source snapshot, then atomically publish current data."""
    current = build_law_manifest(data)
    previous = None
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
    diff = diff_law_manifests(previous, current)
    snapshot_dir = versions_dir / current["version"]
    snapshot_path = snapshot_dir / "laws.json"
    snapshot_manifest = snapshot_dir / "manifest.json"
    diff_path = snapshot_dir / "diff.json"

    if not snapshot_path.exists():
        atomic_write_json(snapshot_path, data)
    if not snapshot_manifest.exists():
        atomic_write_json(snapshot_manifest, current)
    if not diff_path.exists():
        atomic_write_json(diff_path, diff)

    changed = previous is None or previous.get("corpus_hash") != current["corpus_hash"]
    metadata_changed = (
        previous is not None
        and previous.get("version") != current["version"]
        and previous.get("corpus_hash") == current["corpus_hash"]
    )
    if changed or metadata_changed or not out_path.exists():
        # Snapshot is durable before either active pointer is replaced.
        atomic_write_json(out_path, data)
    if changed or metadata_changed:
        published = {
            **current,
            "published_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "snapshot_path": (
                snapshot_path.relative_to(DATA_DIR.parent).as_posix()
                if snapshot_path.is_relative_to(DATA_DIR.parent)
                else str(snapshot_path)
            ),
            "previous_version": (previous or {}).get("version"),
            "last_diff": diff,
            "content_changed": changed,
            "metadata_only_refresh": metadata_changed,
        }
        atomic_write_json(manifest_path, published)
    return LawPublishResult(
        changed=changed,
        version=current["version"],
        snapshot_path=snapshot_path,
        manifest_path=manifest_path,
        diff=diff,
    )


def activate_index_manifest(
    candidate: dict,
    *,
    manifest_path: Path = INDEX_MANIFEST_PATH,
) -> dict:
    """Atomically switch the active index only after build/regression success."""
    if candidate.get("state") != "ready":
        raise ValueError("only a ready index may become active")
    if not candidate.get("regression", {}).get("passed", False):
        raise ValueError("retrieval regression must pass before activation")
    previous = None
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
    activated = {
        **candidate,
        "schema_version": "index-manifest-v1",
        "active_version": candidate["version"],
        "previous_active_version": (
            (previous or {}).get("active_version")
            or (previous or {}).get("version")
        ),
        "activated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    atomic_write_json(manifest_path, activated)
    return activated
