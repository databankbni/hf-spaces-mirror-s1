"""Startup: canonical schema + optional reference auto-ingest.

Each tenant supplies its own past reports and standard paragraphs. The operator
Word/PDF master is never seeded into FAISS at boot.
"""

from __future__ import annotations

import logging

from backend.config import settings
from backend.domain import template_discoverer
from backend.domain.notes import parser as notes_parser
from backend.domain.rics_level3_schema import PARENT_SECTION_COUNT
from backend.ingest import pipeline as ingest
from backend.rag.index_guard import ensure_reference_indices_clean
from backend.rag.store import get_rag_store
from backend.rag.types import TIER_MASTER, TIER_REFERENCE
from backend.storage import tenant_store
from backend.utils.runtime_paths import ensure_data_drive_runtime_dirs

logger = logging.getLogger(__name__)


def _scrub_stale_faiss_write_artifacts() -> None:
    """Remove half-written FAISS/meta files left by interrupted persists."""
    tenants_root = settings.data_dir_path / "tenants"
    if not tenants_root.is_dir():
        return
    for pattern in (
        "*.write.faiss",
        "*.write.json",
        "index.faiss.bad",
        "meta.json.bad",
    ):
        for path in tenants_root.rglob(pattern):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                logger.debug("Could not remove stale artifact %s: %s", path, exc)


def run_startup_ingest() -> dict:
    """Install canonical schema and scan optional reference auto-ingest."""
    ensure_data_drive_runtime_dirs()
    _scrub_stale_faiss_write_artifacts()

    tenant = settings.default_tenant_id
    summary: dict = {
        "master_loaded": False,
        "sections": 0,
        "paragraph_chunks": 0,
        "report_template": settings.report_template_filename,
        "standard_paragraphs": settings.standard_paragraphs_filename,
        "reference_documents": 0,
    }

    logger.info(
        "Skipping operator standard-paragraph seed for tenant=%s "
        "(user memory in faiss/standard_paragraphs is preserved).",
        tenant,
    )
    tenant_store.migrate_legacy_master_faiss_dir(tenant)
    template_discoverer.ensure_canonical_schema(tenant)
    # Do NOT clear_tier — user Add-to-Memory / uploads live in this index.
    index_guard = ensure_reference_indices_clean()
    summary["reference_index_guard"] = index_guard
    summary["master_loaded"] = True  # schema (canonical) is present
    summary["sections"] = PARENT_SECTION_COUNT
    summary["section_anchor_vectors"] = notes_parser.initialize_section_anchors()
    summary["standard_paragraphs_faiss_count"] = get_rag_store().count(
        tenant, TIER_MASTER
    )
    if settings.reference_auto_ingest_enabled and not index_guard.get("rebuilt"):
        try:
            ref = ingest.auto_ingest_reference_dir(tenant)
            summary["reference_documents"] = ref["documents"]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Reference auto-ingest failed: %s", exc)
    elif index_guard.get("rebuilt"):
        summary["reference_documents"] = sum(
            row.get("auto_ingest_docs", 0) + row.get("library_reingested", 0)
            for row in index_guard.get("rebuilt", [])
        )

    store = get_rag_store()
    logger.info(
        "Startup complete: loaded=%s sections=%d paragraph_chunks=%d "
        "reference_chunks=%d anchors=%d",
        summary["master_loaded"],
        summary["sections"],
        store.count(tenant, TIER_MASTER),
        store.count(tenant, TIER_REFERENCE),
        summary["section_anchor_vectors"],
    )
    return summary
