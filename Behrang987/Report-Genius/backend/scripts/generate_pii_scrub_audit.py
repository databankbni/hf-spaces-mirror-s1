"""Backfill the PII scrub audit for ALREADY-ingested reference documents.

The stored FAISS chunks are already scrubbed (originals are gone), so this reads the
raw uploads still in each tenant's ``reference_uploads/`` and re-runs the scrubber —
WITHOUT touching the FAISS index — to produce, per document:

    <data_dir>/pii_scrub_audit/<tenant>/<document>/pii_mapping.json
    <data_dir>/pii_scrub_audit/<tenant>/<document>/redacted_content.txt  (if verbose dump on)
    <data_dir>/pii_scrub_audit/<tenant>/<document>/redactions.json       (if verbose dump on)

plus the global ``whitelist_catalog.json``.

It mirrors ``ingest.ingest_reference`` exactly (same extractor, same
``build_reference_chunks``, same per-document ``ScrubSession``) so chunk ids match
what was stored, but it embeds/stores nothing.

Usage (from repo root):
    python -m backend.scripts.generate_pii_scrub_audit                 # all tenants w/ uploads
    python -m backend.scripts.generate_pii_scrub_audit 12345 123456    # specific tenants
"""

from __future__ import annotations

import sys
from pathlib import Path

from backend.utils.runtime_paths import ensure_data_drive_runtime_dirs

ensure_data_drive_runtime_dirs()

from backend.config import settings  # noqa: E402
from backend.domain import template_discoverer  # noqa: E402
from backend.ingest import doc_extractor  # noqa: E402
from backend.pii import audit as pii_scrub_audit  # noqa: E402
from backend.pii.scrubber import (  # noqa: E402
    ScrubSession,
    scrub_reference_for_ingest,
)
from backend.rag.reference_chunker import build_reference_chunks  # noqa: E402
from backend.storage import tenant_store  # noqa: E402
from backend.storage.report_session import list_documents  # noqa: E402

_UPLOAD_GLOBS = ("*.pdf", "*.docx", "*.doc", "*.docm")


def _tenants_with_uploads() -> list[str]:
    root = settings.data_dir_path / "tenants"
    if not root.is_dir():
        return []
    out: list[str] = []
    for tenant_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        uploads = tenant_dir / "reference_uploads"
        if uploads.is_dir() and any(f for g in _UPLOAD_GLOBS for f in uploads.glob(g)):
            out.append(tenant_dir.name)
    return out


def _original_names(tenant_id: str) -> dict[str, str]:
    """Map stored upload filename (``<document_id><suffix>``) -> original filename."""
    mapping: dict[str, str] = {}
    try:
        for doc in list_documents(tenant_id).values():
            storage = getattr(doc, "storage_path", "") or ""
            if storage:
                mapping[Path(storage).name] = getattr(doc, "filename", "") or ""
    except Exception:  # noqa: BLE001 - library is best-effort enrichment only
        pass
    return mapping


def _audit_one(
    tenant_id: str, path: Path, original_filename: str
) -> tuple[int, int, int]:
    """Return (chunks, redactions, dropped) for one document."""
    text = doc_extractor.extract_text(path)
    schema = template_discoverer.load_schema(tenant_id)
    valid = set(schema.section_ids()) if schema else None
    chunks = build_reference_chunks(
        text, source_filename=path.name, valid_section_ids=valid
    )

    doc_audit = pii_scrub_audit.start_document(
        tenant_id=tenant_id,
        doc_id=f"reference:{path.name}",
        source_filename=path.name,
        original_filename=original_filename,
    )
    if doc_audit is None:  # audit disabled — shouldn't happen (forced on in main)
        return (len(chunks), 0, 0)

    session = ScrubSession()
    n_red = 0
    n_drop = 0
    for c in chunks:
        outcome = scrub_reference_for_ingest(c.text or "", session=session)
        doc_audit.add_chunk(
            section_id=c.section_id or "",
            paragraph_index=int(c.paragraph_index or 0),
            chunk_id=c.chunk_id or "",
            redacted_text=outcome.cleaned_text,
            redactions=outcome.redactions,
            whitelisted=outcome.whitelisted,
            dropped=outcome.dropped,
            residual_leaks=outcome.residual_leaks,
        )
        n_red += len(outcome.redactions)
        n_drop += 1 if outcome.dropped else 0
    doc_audit.write()
    return (len(chunks), n_red, n_drop)


def main(argv: list[str]) -> int:
    # Force the audit on for the backfill regardless of the .env flag.
    settings.pii_scrub_audit_dump = True

    tenants = argv or _tenants_with_uploads()
    if not tenants:
        print("No tenants with reference_uploads found.")
        return 0

    pii_scrub_audit.ensure_whitelist_catalog()
    out_root = settings.data_dir_path / "pii_scrub_audit"
    print(f"Writing PII scrub audit under: {out_root}")

    grand_docs = grand_chunks = grand_red = grand_drop = 0
    for tenant_id in tenants:
        uploads = tenant_store.reference_uploads_dir(tenant_id)
        files = sorted({f for g in _UPLOAD_GLOBS for f in uploads.glob(g)})
        if not files:
            print(f"[{tenant_id}] no uploads — skipped")
            continue
        names = _original_names(tenant_id)
        print(f"\n[{tenant_id}] {len(files)} document(s)")
        for path in files:
            original = names.get(path.name, "")
            try:
                n_chunks, n_red, n_drop = _audit_one(tenant_id, path, original)
            except Exception as exc:  # noqa: BLE001 - report and continue
                print(f"  ! {path.name}: FAILED ({type(exc).__name__}: {exc})")
                continue
            label = original or path.name
            print(
                f"  - {label}: {n_chunks} chunks, {n_red} redactions, {n_drop} dropped"
            )
            grand_docs += 1
            grand_chunks += n_chunks
            grand_red += n_red
            grand_drop += n_drop

    print(
        f"\nDone. {grand_docs} document(s), {grand_chunks} chunks, "
        f"{grand_red} redactions, {grand_drop} dropped."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
