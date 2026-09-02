"""Reference document persistence, delete, and re-ingest."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from backend.config import settings
from backend.domain.style_profile import invalidate_style_profile
from backend.ingest import pipeline as ingest
from backend.rag.store import get_rag_store
from backend.rag.types import TIER_REFERENCE
from backend.storage import tenant_store
from backend.storage.report_session import (
    UploadedDocument,
    delete_document,
    get_document,
    list_documents,
    save_document,
)

logger = logging.getLogger(__name__)

_REFERENCE_SUFFIXES = {".pdf", ".docx", ".docm", ".doc"}
_reingest_lock = threading.Lock()
_reingest_running: set[str] = set()


def is_reingest_running(tenant_id: str) -> bool:
    with _reingest_lock:
        return tenant_id in _reingest_running


def recover_stale_processing_documents(tenant_id: str) -> int:
    """Reset orphaned ``processing`` rows when no re-ingest worker is active."""
    if is_reingest_running(tenant_id):
        return 0
    recovered = 0
    for _doc_id, doc in list_documents(tenant_id).items():
        if doc.status == "processing":
            doc.status = "complete"
            doc.error = None
            save_document(tenant_id, doc)
            recovered += 1
    if recovered:
        logger.info(
            "Recovered %d stale processing document(s) for tenant=%s",
            recovered,
            tenant_id,
        )
    return recovered


def recover_all_tenants_stale_processing() -> int:
    """On startup, clear processing flags left by a killed background worker."""
    tenants_root = settings.data_dir_path / "tenants"
    if not tenants_root.is_dir():
        return 0
    total = 0
    for tenant_dir in sorted(tenants_root.iterdir()):
        if not tenant_dir.is_dir():
            continue
        if not (tenant_dir / "compat_documents.json").is_file():
            continue
        total += recover_stale_processing_documents(tenant_dir.name)
    return total


def reingest_progress(tenant_id: str) -> dict:
    docs = list_documents(tenant_id)
    counts = {
        "complete": 0,
        "chunked": 0,
        "processing": 0,
        "failed": 0,
        "pending": 0,
    }
    for doc in docs.values():
        key = doc.status if doc.status in counts else "pending"
        counts[key] = counts.get(key, 0) + 1
    return {
        "total": len(docs),
        "running": is_reingest_running(tenant_id),
        **counts,
    }


def document_created_at_iso(doc: UploadedDocument) -> str:
    """Serialize ``created_at`` for API responses (ISO-8601 UTC)."""
    ts = doc.created_at
    if isinstance(ts, (int, float)) and ts > 0:
        return datetime.fromtimestamp(ts, tz=UTC).isoformat()
    if isinstance(ts, str) and ts.strip():
        return ts.strip()
    return datetime.now(tz=UTC).isoformat()


def persist_reference_file(
    tenant_id: str,
    document_id: str,
    source_path: Path,
    *,
    original_filename: str,
) -> Path:
    """Copy an uploaded file into tenant storage for later re-ingest."""
    suffix = source_path.suffix.lower() or Path(original_filename).suffix.lower()
    dest = tenant_store.reference_upload_path(tenant_id, document_id, suffix)
    shutil.copy2(source_path, dest)
    return dest


def _file_content_hash(path: Path) -> str:
    """SHA-256 of file bytes (streamed) for duplicate-upload detection."""
    try:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for block in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(block)
        return h.hexdigest()
    except OSError:
        return ""


def _indexed_storage_paths(tenant_id: str) -> set[str]:
    paths: set[str] = set()
    for doc in list_documents(tenant_id).values():
        if not doc.storage_path:
            continue
        try:
            paths.add(str(Path(doc.storage_path).resolve()))
        except OSError:
            paths.add(doc.storage_path)
    return paths


def _list_reference_upload_files(tenant_id: str) -> list[Path]:
    uploads_dir = tenant_store.reference_uploads_dir(tenant_id)
    if not uploads_dir.is_dir():
        return []
    files = [
        path
        for path in sorted(uploads_dir.iterdir())
        if path.is_file() and path.suffix.lower() in _REFERENCE_SUFFIXES
    ]
    return files


def _is_uuid_stem(stem: str) -> bool:
    compact = stem.replace("-", "")
    return len(compact) == 32 and all(c in "0123456789abcdef" for c in compact.lower())


def _document_survivor_rank(doc: UploadedDocument) -> tuple[int, int, int, float]:
    path = Path(doc.storage_path) if doc.storage_path else None
    on_disk = 1 if path and path.is_file() else 0
    human_name = 0 if path and _is_uuid_stem(path.stem) else 1
    return (
        on_disk,
        human_name,
        int(doc.ingested_chunks or 0),
        -float(doc.created_at or 0.0),
    )


def _disk_file_survivor_rank(
    path: Path, keeper_doc: UploadedDocument | None
) -> tuple[int, int, float]:
    resolved = str(path.resolve())
    linked = 0
    if keeper_doc and keeper_doc.storage_path:
        try:
            linked = (
                1 if resolved == str(Path(keeper_doc.storage_path).resolve()) else 0
            )
        except OSError:
            linked = 0
    human_name = 0 if _is_uuid_stem(path.stem) else 1
    return (linked, human_name, -path.stat().st_mtime)


def _ensure_document_hash(tenant_id: str, doc: UploadedDocument) -> str:
    if doc.content_hash:
        return doc.content_hash
    if not doc.storage_path:
        return ""
    path = Path(doc.storage_path)
    if not path.is_file():
        return ""
    doc.content_hash = _file_content_hash(path)
    save_document(tenant_id, doc)
    return doc.content_hash


def dedupe_tenant_storage(tenant_id: str) -> dict:
    """Keep one library row and one on-disk file per unique document content.

    Duplicate byte-identical uploads are collapsed: extra ``compat_documents``
    rows are removed (metadata only — shared FAISS chunks are untouched) and
    surplus files under ``reference_uploads/`` are deleted from disk.
    """
    docs_before = len(list_documents(tenant_id))
    files_before = len(_list_reference_upload_files(tenant_id))
    records_removed = 0
    files_removed = 0

    by_hash: dict[str, list[UploadedDocument]] = {}
    for doc in list(list_documents(tenant_id).values()):
        content_hash = _ensure_document_hash(tenant_id, doc)
        key = f"h:{content_hash}" if content_hash else f"n:{doc.document_id}"
        by_hash.setdefault(key, []).append(doc)

    for key, members in by_hash.items():
        if key.startswith("n:") or len(members) <= 1:
            continue
        members.sort(key=_document_survivor_rank, reverse=True)
        for extra in members[1:]:
            delete_document(tenant_id, extra.document_id)
            records_removed += 1

    disk_by_hash: dict[str, list[Path]] = {}
    for path in _list_reference_upload_files(tenant_id):
        content_hash = _file_content_hash(path)
        if content_hash:
            disk_by_hash.setdefault(content_hash, []).append(path)

    for content_hash, paths in disk_by_hash.items():
        if len(paths) <= 1:
            continue
        keeper_doc = _find_duplicate_document(tenant_id, content_hash)
        ranked = sorted(
            paths,
            key=lambda p: _disk_file_survivor_rank(p, keeper_doc),
            reverse=True,
        )
        for duplicate in ranked[1:]:
            resolved = str(duplicate.resolve())
            duplicate.unlink(missing_ok=True)
            files_removed += 1
            for doc in list(list_documents(tenant_id).values()):
                if not doc.storage_path:
                    continue
                try:
                    if str(Path(doc.storage_path).resolve()) == resolved:
                        delete_document(tenant_id, doc.document_id)
                        records_removed += 1
                except OSError:
                    continue

    for doc_id, doc in list(list_documents(tenant_id).items()):
        if doc.storage_path and not Path(doc.storage_path).is_file():
            delete_document(tenant_id, doc_id)
            records_removed += 1

    docs_after = len(list_documents(tenant_id))
    files_after = len(_list_reference_upload_files(tenant_id))
    if records_removed or files_removed:
        logger.info(
            "Deduped tenant=%s: records %d→%d (-%d), files %d→%d (-%d)",
            tenant_id,
            docs_before,
            docs_after,
            records_removed,
            files_before,
            files_after,
            files_removed,
        )
    return {
        "records_removed": records_removed,
        "files_removed": files_removed,
        "docs_before": docs_before,
        "docs_after": docs_after,
        "files_before": files_before,
        "files_after": files_after,
    }


def sync_disk_to_document_library(tenant_id: str) -> int:
    """Register on-disk ``reference_uploads/`` files missing from the library.

    Skips byte-identical duplicates (one content hash per tenant) and deletes
    surplus duplicate files from disk.
    """
    from backend.storage.report_session import new_document_id

    known_paths = _indexed_storage_paths(tenant_id)
    registered = 0

    for path in _list_reference_upload_files(tenant_id):
        resolved = str(path.resolve())
        if resolved in known_paths:
            continue

        content_hash = _file_content_hash(path)
        existing = _find_duplicate_document(tenant_id, content_hash)
        if existing is not None:
            logger.info(
                "Removing duplicate upload %s for tenant=%s (matches %s).",
                path.name,
                tenant_id,
                existing.filename,
            )
            path.unlink(missing_ok=True)
            continue

        doc_id = path.stem
        if get_document(tenant_id, doc_id) is not None:
            doc_id = new_document_id()

        doc = UploadedDocument(
            document_id=doc_id,
            filename=path.name,
            status="pending",
            storage_path=resolved,
            file_size=path.stat().st_size,
            created_at=path.stat().st_mtime,
            content_hash=content_hash,
        )
        save_document(tenant_id, doc)
        known_paths.add(resolved)
        registered += 1
        logger.info(
            "Registered reference upload %s as document %s for tenant=%s",
            path.name,
            doc_id,
            tenant_id,
        )

    return registered


def _purge_reference_vectors_for_document(
    tenant_id: str, doc: UploadedDocument, path: Path
) -> int:
    """Remove REFERENCE chunks for a library row (handles legacy filename keys)."""
    store = get_rag_store()
    removed = 0
    keys: set[tuple[str | None, str | None]] = set()
    for name in {path.name, doc.filename}:
        if not name:
            continue
        keys.add((name, f"reference:{name}"))
    for source_filename, doc_id in keys:
        removed += store.remove_document(
            tenant_id,
            TIER_REFERENCE,
            source_filename=source_filename,
            doc_id=doc_id,
        )
    return removed


def chunks_manifest_path(tenant_id: str) -> Path:
    """Per-tenant JSON of uploaded files -> {metadata, extracted chunks}."""
    return tenant_store.tenant_root(tenant_id) / "extracted_chunks.json"


def rebuild_chunks_manifest(tenant_id: str) -> Path:
    """Write ``extracted_chunks.json`` keyed by filename, valued by metadata + chunks.

    Rebuilt from the REFERENCE index plus any chunk-only sidecars
    (``INGEST_EMBED_ENABLED=false``) so it mirrors what was extracted after
    ingest / re-ingest / delete — whether or not vectors were written.
    """
    store = get_rag_store()
    chunks_by_source = store.export_chunks_by_source(tenant_id, TIER_REFERENCE)

    docs_by_name: dict[str, UploadedDocument] = {}
    for doc in list_documents(tenant_id).values():
        if doc.filename:
            docs_by_name[doc.filename] = doc

    manifest: dict[str, dict] = {}
    # Map UUID storage names -> library original filenames so the JSON is human-readable
    # even if a legacy row still carries the hashed source_filename.
    uuid_to_original: dict[str, UploadedDocument] = {}
    for doc in list_documents(tenant_id).values():
        if doc.storage_path:
            uuid_to_original[Path(doc.storage_path).name] = doc
        if doc.document_id:
            for suf in (".pdf", ".docx", ".docm", ".doc"):
                uuid_to_original[f"{doc.document_id}{suf}"] = doc

    for filename, chunks in sorted(chunks_by_source.items()):
        doc = docs_by_name.get(filename) or uuid_to_original.get(filename)
        display_name = (doc.filename if doc and doc.filename else filename)
        sections = sorted({c["section_id"] for c in chunks if c.get("section_id")})
        parent_intros = sorted(
            {
                c["parent_id"]
                for c in chunks
                if c.get("content_role") == "parent_intro" and c.get("parent_id")
            }
        )
        # Prefer original name as the top-level key (never the UUID storage id).
        entry = {
            "document_id": doc.document_id if doc else "",
            "status": doc.status if doc else "indexed",
            "file_size": doc.file_size if doc else 0,
            "content_hash": doc.content_hash if doc else "",
            "created_at": document_created_at_iso(doc) if doc else "",
            "chunk_count": len(chunks),
            "sections": sections,
            "parent_intro_sections": parent_intros,
            "chunks": chunks,
        }
        if display_name in manifest and display_name != filename:
            # Same original already present — keep the richer entry.
            if len(chunks) <= manifest[display_name]["chunk_count"]:
                continue
        manifest[display_name] = entry

    path = chunks_manifest_path(tenant_id)
    path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info(
        "Wrote extracted-chunks manifest for tenant=%s (%d file(s), %d chunk(s)).",
        tenant_id,
        len(manifest),
        sum(len(c) for c in chunks_by_source.values()),
    )
    return path


def _safe_rebuild_chunks_manifest(tenant_id: str) -> None:
    """Rebuild the manifest without letting a write failure break the caller."""
    try:
        rebuild_chunks_manifest(tenant_id)
    except Exception:  # noqa: BLE001 - manifest is a non-critical side artifact
        logger.warning(
            "Failed to rebuild extracted-chunks manifest for tenant=%s.",
            tenant_id,
            exc_info=True,
        )


def _reingest_target_ids(
    tenant_id: str,
    *,
    skip_document_ids: set[str] | None = None,
) -> list[str]:
    """Document ids eligible for a full re-ingest (one row per content hash)."""
    skip = skip_document_ids or set()
    targets: list[str] = []
    seen_hashes: set[str] = set()
    for doc_id, doc in list_documents(tenant_id).items():
        if doc_id in skip:
            continue
        path = Path(doc.storage_path) if doc.storage_path else None
        if path is None or not path.is_file():
            continue
        content_hash = doc.content_hash or _file_content_hash(path)
        if content_hash:
            if content_hash in seen_hashes:
                continue
            seen_hashes.add(content_hash)
        targets.append(doc_id)
    return targets


def _find_duplicate_document(
    tenant_id: str, content_hash: str
) -> UploadedDocument | None:
    """Return an existing non-failed document with the same content hash, if any."""
    if not content_hash:
        return None
    for doc in list_documents(tenant_id).values():
        if doc.content_hash == content_hash and doc.status != "failed":
            return doc
    return None


def _retag_reference_vectors_property_type(
    tenant_id: str, doc: UploadedDocument, property_type: str
) -> int:
    """Stamp property_type onto REFERENCE chunks for a library row (no re-embed)."""
    store = get_rag_store()
    changed = 0
    keys: set[tuple[str | None, str | None]] = set()
    path_name = Path(doc.storage_path).name if doc.storage_path else ""
    for name in {path_name, doc.filename}:
        if not name:
            continue
        keys.add((name, f"reference:{name}"))
    for source_filename, doc_id in keys:
        changed += store.update_document_property_type(
            tenant_id,
            TIER_REFERENCE,
            property_type=property_type,
            source_filename=source_filename,
            doc_id=doc_id,
        )
    return changed


@dataclass
class IngestRegisterResult:
    """Outcome of :func:`ingest_and_register` (create vs metadata retag)."""

    document: UploadedDocument
    action: Literal["created", "retagged", "unchanged"] = "created"
    chunks_retagged: int = 0


def ingest_and_register(
    tenant_id: str,
    source_path: Path,
    *,
    original_filename: str,
    document_id: str | None = None,
    property_type: str = "",
) -> IngestRegisterResult:
    """Ingest a reference file and record it in the document library.

    A re-upload of byte-identical content is not re-extracted or re-embedded.
    When ``property_type`` is provided and differs from the existing library
    tag, chunk + library metadata are retagged in place so the report becomes
    eligible for House/Flat retrieval filters.
    """
    from backend.domain.property_type import try_canonical_property_type
    from backend.storage.report_session import new_document_id

    canonical_pt = try_canonical_property_type(property_type) or ""
    content_hash = _file_content_hash(source_path)
    existing = _find_duplicate_document(tenant_id, content_hash)
    if existing is not None:
        if not canonical_pt:
            logger.info(
                "Duplicate upload '%s' matches existing document %s (%s); "
                "skipping ingest (no property_type to apply).",
                original_filename,
                existing.document_id,
                existing.filename,
            )
            return IngestRegisterResult(document=existing, action="unchanged")

        prev = (existing.property_type or "").strip().lower()
        if prev == canonical_pt:
            logger.info(
                "Duplicate upload '%s' matches existing document %s (%s); "
                "already tagged property_type=%s.",
                original_filename,
                existing.document_id,
                existing.filename,
                canonical_pt,
            )
            return IngestRegisterResult(document=existing, action="unchanged")

        chunks_retagged = _retag_reference_vectors_property_type(
            tenant_id, existing, canonical_pt
        )
        existing.property_type = canonical_pt
        save_document(tenant_id, existing)
        _safe_rebuild_chunks_manifest(tenant_id)
        logger.info(
            "Duplicate upload '%s' matches existing document %s (%s); "
            "retagged %d chunk(s) %s → %s (no re-embed).",
            original_filename,
            existing.document_id,
            existing.filename,
            chunks_retagged,
            prev or "(untagged)",
            canonical_pt,
        )
        return IngestRegisterResult(
            document=existing,
            action="retagged",
            chunks_retagged=chunks_retagged,
        )

    doc_id = document_id or new_document_id()
    stored = persist_reference_file(
        tenant_id, doc_id, source_path, original_filename=original_filename
    )
    ingest_result = ingest.ingest_reference_report(
        tenant_id,
        stored,
        source_filename=original_filename or stored.name,
        property_type=canonical_pt,
    )
    embedded = bool(ingest_result.get("embedded", True))
    doc = UploadedDocument(
        document_id=doc_id,
        filename=original_filename or stored.name,
        status="complete" if embedded else "chunked",
        ingested_chunks=ingest_result["chunks"],
        storage_path=str(stored),
        file_size=stored.stat().st_size if stored.is_file() else 0,
        created_at=time.time(),
        content_hash=content_hash,
        ingest_verification=ingest_result["verification"],
        property_type=canonical_pt or str(ingest_result.get("property_type") or ""),
    )
    save_document(tenant_id, doc)
    invalidate_style_profile(tenant_id)
    _safe_rebuild_chunks_manifest(tenant_id)
    return IngestRegisterResult(document=doc, action="created")


def remove_reference_document(tenant_id: str, document_id: str) -> int:
    """Remove chunks, stored file, and library record. Returns chunks removed."""
    doc = get_document(tenant_id, document_id)
    if doc is None:
        raise KeyError("Document not found")

    removed = 0
    if doc.storage_path:
        path = Path(doc.storage_path)
        if path.is_file():
            removed = _purge_reference_vectors_for_document(tenant_id, doc, path)
            path.unlink(missing_ok=True)
    else:
        removed = get_rag_store().remove_document(
            tenant_id,
            TIER_REFERENCE,
            source_filename=doc.filename,
            doc_id=f"reference:{doc.filename}",
        )
    delete_document(tenant_id, document_id)
    extract_md = tenant_store.reference_extract_md_path(
        tenant_id, doc.filename or document_id
    )
    extract_md.unlink(missing_ok=True)
    invalidate_style_profile(tenant_id)
    _safe_rebuild_chunks_manifest(tenant_id)
    return removed


def remove_reference_documents(
    tenant_id: str,
    document_ids: list[str],
    *,
    skip_document_ids: set[str] | frozenset[str] | None = None,
) -> dict:
    """Delete many past-report library rows. Returns per-id results summary."""
    skip = {str(x) for x in (skip_document_ids or set()) if str(x).strip()}
    deleted: list[dict] = []
    skipped: list[dict] = []
    missing: list[str] = []
    errors: list[dict] = []
    total_chunks = 0

    seen: set[str] = set()
    for raw in document_ids:
        doc_id = str(raw or "").strip()
        if not doc_id or doc_id in seen:
            continue
        seen.add(doc_id)
        if doc_id in skip:
            skipped.append(
                {
                    "document_id": doc_id,
                    "reason": "report_generating",
                }
            )
            continue
        try:
            removed = remove_reference_document(tenant_id, doc_id)
        except KeyError:
            missing.append(doc_id)
            continue
        except Exception as exc:  # noqa: BLE001
            errors.append({"document_id": doc_id, "error": str(exc)})
            continue
        total_chunks += int(removed or 0)
        deleted.append({"document_id": doc_id, "chunks_removed": int(removed or 0)})

    return {
        "deleted": deleted,
        "deleted_count": len(deleted),
        "skipped": skipped,
        "skipped_count": len(skipped),
        "missing": missing,
        "missing_count": len(missing),
        "errors": errors,
        "error_count": len(errors),
        "chunks_removed": total_chunks,
    }


def reingest_reference_document(
    tenant_id: str,
    document_id: str,
    *,
    write_manifest: bool = True,
) -> UploadedDocument:
    """Re-process one stored reference file through the current pipeline.

    ``write_manifest`` is disabled by the full-library batch, which rebuilds the
    per-tenant chunk manifest once at the end instead of after every document.
    """
    doc = get_document(tenant_id, document_id)
    if doc is None:
        raise KeyError("Document not found")

    path = Path(doc.storage_path) if doc.storage_path else None
    if path is None or not path.is_file():
        raise FileNotFoundError("Source file is no longer on disk; cannot re-ingest.")

    doc.status = "processing"
    doc.error = None
    save_document(tenant_id, doc)

    _purge_reference_vectors_for_document(tenant_id, doc, path)
    ingest_result = ingest.ingest_reference_report(
        tenant_id,
        path,
        source_filename=doc.filename or path.name,
        property_type=doc.property_type or "",
    )
    embedded = bool(ingest_result.get("embedded", True))
    doc.status = "complete" if embedded else "chunked"
    doc.error = None
    doc.ingested_chunks = ingest_result["chunks"]
    doc.ingest_verification = ingest_result["verification"]
    if ingest_result.get("property_type"):
        doc.property_type = str(ingest_result["property_type"])
    doc.file_size = path.stat().st_size
    if not doc.content_hash:
        doc.content_hash = _file_content_hash(path)
    save_document(tenant_id, doc)
    invalidate_style_profile(tenant_id)
    if write_manifest:
        _safe_rebuild_chunks_manifest(tenant_id)
    return doc


def reingest_all_documents(
    tenant_id: str,
    *,
    skip_document_ids: set[str] | None = None,
) -> dict:
    skip = skip_document_ids or set()
    dedupe_stats = dedupe_tenant_storage(tenant_id)
    registered = sync_disk_to_document_library(tenant_id)
    if registered:
        logger.info(
            "Synced %d orphan reference upload(s) into library for tenant=%s",
            registered,
            tenant_id,
        )

    queued: list[str] = []
    skipped_missing = 0
    skipped_active = len(skip)

    for doc_id in _reingest_target_ids(tenant_id, skip_document_ids=skip):
        doc = get_document(tenant_id, doc_id)
        if doc is None:
            skipped_missing += 1
            continue
        try:
            logger.info("Re-ingesting %s for tenant=%s", doc.filename, tenant_id)
            updated = reingest_reference_document(
                tenant_id, doc_id, write_manifest=False
            )
            queued.append(doc_id)
            logger.info(
                "Re-ingested %s (%d chunks)",
                updated.filename,
                updated.ingested_chunks,
            )
        except FileNotFoundError:
            skipped_missing += 1
        except Exception as exc:  # noqa: BLE001
            doc.status = "failed"
            doc.error = str(exc)
            save_document(tenant_id, doc)

    _safe_rebuild_chunks_manifest(tenant_id)

    disk_files = len(_list_reference_upload_files(tenant_id))
    dedupe_note = ""
    if dedupe_stats["files_removed"] or dedupe_stats["records_removed"]:
        dedupe_note = (
            f"; removed {dedupe_stats['files_removed']} duplicate file(s) and "
            f"{dedupe_stats['records_removed']} duplicate record(s)"
        )

    return {
        "queued": len(queued),
        "document_ids": queued,
        "disk_files": disk_files,
        "registered_from_disk": registered,
        "dedupe": dedupe_stats,
        "skipped_active": skipped_active,
        "skipped_missing_file": skipped_missing,
        "detail": (
            f"Re-ingested {len(queued)} unique document(s)"
            + dedupe_note
            + (f" ({registered} newly registered from disk)" if registered else "")
            + f"; skipped {skipped_active} blocked and {skipped_missing} missing-file."
        ),
    }


def schedule_reingest_all_documents(
    tenant_id: str,
    *,
    skip_document_ids: set[str] | None = None,
) -> dict:
    """Queue a full-library re-ingest on a background thread (non-blocking HTTP).

    Only the document currently being embedded is marked ``processing`` so a
    server restart cannot strand the whole library in that state.
    """
    skip = skip_document_ids or set()
    dedupe_stats = dedupe_tenant_storage(tenant_id)
    registered = sync_disk_to_document_library(tenant_id)
    to_queue = _reingest_target_ids(tenant_id, skip_document_ids=skip)

    with _reingest_lock:
        if tenant_id in _reingest_running:
            progress = reingest_progress(tenant_id)
            return {
                "queued": 0,
                "document_ids": [],
                "skipped_active": len(skip),
                "skipped_missing_file": 0,
                "reingest_running": True,
                "progress": progress,
                "detail": (
                    f"Re-ingest already running "
                    f"({progress['processing']} processing, "
                    f"{progress['complete']} ready)."
                ),
            }
        _reingest_running.add(tenant_id)

    # Clear orphaned processing flags from a prior killed worker.
    recover_stale_processing_documents(tenant_id)

    def _worker() -> None:
        try:
            logger.info(
                "Background re-ingest started for tenant=%s (%d documents)",
                tenant_id,
                len(to_queue),
            )
            reingest_all_documents(tenant_id, skip_document_ids=skip)
        except Exception:  # noqa: BLE001
            logger.exception("Background re-ingest failed for tenant=%s", tenant_id)
            recover_stale_processing_documents(tenant_id)
        finally:
            with _reingest_lock:
                _reingest_running.discard(tenant_id)
            logger.info("Background re-ingest finished for tenant=%s", tenant_id)

    threading.Thread(
        target=_worker,
        name=f"reingest-{tenant_id}",
        daemon=True,
    ).start()

    disk_files = len(_list_reference_upload_files(tenant_id))
    progress = reingest_progress(tenant_id)
    registered_note = (
        f" ({registered} newly registered from disk)" if registered else ""
    )
    dedupe_note = ""
    if dedupe_stats["files_removed"] or dedupe_stats["records_removed"]:
        dedupe_note = (
            f"; removed {dedupe_stats['files_removed']} duplicate file(s) and "
            f"{dedupe_stats['records_removed']} duplicate record(s)"
        )
    return {
        "queued": len(to_queue),
        "document_ids": to_queue,
        "disk_files": disk_files,
        "registered_from_disk": registered,
        "dedupe": dedupe_stats,
        "skipped_active": len(skip),
        "skipped_missing_file": 0,
        "reingest_running": True,
        "progress": progress,
        "detail": (
            f"Re-ingest started in the background for {len(to_queue)} unique "
            f"document(s){dedupe_note}{registered_note}. "
            "Status updates every few seconds as each file completes."
        ),
    }


def schedule_reingest_reference_document(tenant_id: str, document_id: str) -> dict:
    """Queue a single-document re-ingest on a background thread."""
    doc = get_document(tenant_id, document_id)
    if doc is None:
        raise KeyError("Document not found")

    path = Path(doc.storage_path) if doc.storage_path else None
    if path is None or not path.is_file():
        raise FileNotFoundError("Source file is no longer on disk; cannot re-ingest.")

    doc.status = "processing"
    doc.error = None
    save_document(tenant_id, doc)

    def _worker() -> None:
        try:
            reingest_reference_document(tenant_id, document_id)
        except Exception as exc:  # noqa: BLE001
            failed = get_document(tenant_id, document_id)
            if failed is not None:
                failed.status = "failed"
                failed.error = str(exc)
                save_document(tenant_id, failed)

    threading.Thread(
        target=_worker,
        name=f"reingest-{tenant_id}-{document_id[:8]}",
        daemon=True,
    ).start()

    return {
        "queued": 1,
        "document_ids": [document_id],
        "detail": f"Re-ingest started in the background for {doc.filename}.",
    }
