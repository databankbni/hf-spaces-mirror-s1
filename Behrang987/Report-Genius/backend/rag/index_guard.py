"""Startup guard: purge polluted FAISS indices and rebuild from canonical sources.

Legacy deployments indexed chunks against a fluid ~439-section layout. After the
canonical 14-parent / 54-leaf RICS L3 matrix is installed, reference-tier indices
must contain only chunks tagged with valid leaf section IDs.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from backend.config import settings
from backend.domain.rics_level3_schema import valid_leaf_section_ids
from backend.ingest import pipeline as ingest
from backend.rag.store import get_rag_store, reset_rag_store
from backend.rag.types import TIER_REFERENCE
from backend.storage import document_library, tenant_store

logger = logging.getLogger(__name__)

# Bump when index layout, canonical section matrix, or the embedding model /
# dimension changes (forces a one-time purge + rebuild of both tiers). Bumped to
# v5 for the MiniLM 384-dim → jina-embeddings-v3 1024-dim migration.
REFERENCE_VECTOR_EPOCH = "v5_jina_v3_1024"


def _epoch_marker_path() -> Path:
    return settings.data_dir_path / ".reference_vector_epoch"


def _list_tenant_ids() -> list[str]:
    root = settings.data_dir_path / "tenants"
    if not root.is_dir():
        return []
    return sorted(
        p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")
    )


def _tier_paths(tenant_id: str, tier: str) -> tuple[Path, Path]:
    d = tenant_store.faiss_dir(tenant_id, tier)
    return d / "index.faiss", d / "meta.json"


def _load_meta(meta_path: Path) -> list[dict]:
    if not meta_path.is_file():
        return []
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001
        return []


def meta_has_polluted_section_ids(meta: list[dict]) -> bool:
    """True when any chunk carries a section id outside the canonical 54-leaf set."""
    valid = valid_leaf_section_ids()
    for row in meta:
        sid = str(row.get("section_id") or "").strip().upper()
        if sid and sid not in valid:
            return True
    return False


def schema_recently_repaired(tenant_id: str) -> bool:
    """True when canonical schema was reinstalled and reference index must rebuild."""
    from backend.domain.template_discoverer import _schema_repair_marker

    marker = _schema_repair_marker(tenant_id)
    return marker.is_file()


def _consume_schema_repair_marker(tenant_id: str) -> None:
    from backend.domain.template_discoverer import _schema_repair_marker

    _schema_repair_marker(tenant_id).unlink(missing_ok=True)


def purge_tier_from_disk(tenant_id: str, tier: str) -> bool:
    """Delete persisted FAISS artifacts and evict the in-memory cache entry."""
    idx_path, meta_path = _tier_paths(tenant_id, tier)
    get_rag_store().evict_tier_cache(tenant_id, tier)
    removed = False
    for path in (idx_path, meta_path):
        if path.is_file():
            path.unlink(missing_ok=True)
            removed = True
    for pattern in ("*.write.faiss", "*.write.json", "*.bad"):
        for stale in idx_path.parent.glob(pattern):
            stale.unlink(missing_ok=True)
    return removed


def _rebuild_reference_index(tenant_id: str) -> dict:
    """Clear reference tier and re-ingest from persisted uploads + auto-ingest dir."""
    store = get_rag_store()
    store.clear_tier(tenant_id, TIER_REFERENCE)
    purge_tier_from_disk(tenant_id, TIER_REFERENCE)

    library = document_library.reingest_all_documents(tenant_id)
    known_filenames = set(store.list_source_filenames(tenant_id, TIER_REFERENCE))

    auto_docs = 0
    auto_chunks = 0
    if settings.reference_auto_ingest_enabled:
        folder = settings.reference_dir_path
        if folder.is_dir():
            from backend.ingest.pipeline import _operator_filenames_lower

            skip = _operator_filenames_lower()
            globs = [
                g.strip()
                for g in settings.reference_auto_ingest_globs.split(",")
                if g.strip()
            ]
            seen: set[Path] = set()
            for pattern in globs:
                for path in sorted(folder.glob(pattern)):
                    if path.name.lower() in skip or path in seen:
                        continue
                    seen.add(path)
                    if path.name in known_filenames:
                        continue
                    try:
                        auto_chunks += ingest.ingest_reference(tenant_id, path)
                        auto_docs += 1
                        known_filenames.add(path.name)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "Reference auto-ingest failed during rebuild for %s (%s).",
                            path.name,
                            exc,
                        )

    chunk_count = store.count(tenant_id, TIER_REFERENCE)
    return {
        "tenant_id": tenant_id,
        "library_reingested": library.get("queued", 0),
        "auto_ingest_docs": auto_docs,
        "auto_ingest_chunks": auto_chunks,
        "reference_chunks": chunk_count,
    }


def ensure_reference_indices_clean(
    *,
    tenant_ids: list[str] | None = None,
    force: bool = False,
) -> dict:
    """Purge polluted reference indices and rebuild from canonical-mapped sources."""
    ensure_data = settings.data_dir_path
    ensure_data.mkdir(parents=True, exist_ok=True)

    epoch_path = _epoch_marker_path()
    stored_epoch = (
        epoch_path.read_text(encoding="utf-8").strip() if epoch_path.is_file() else ""
    )
    epoch_changed = stored_epoch != REFERENCE_VECTOR_EPOCH

    targets = tenant_ids if tenant_ids is not None else _list_tenant_ids()
    if not targets:
        targets = [settings.default_tenant_id]

    purged: list[str] = []
    rebuilt: list[dict] = []

    for tenant_id in targets:
        _, ref_meta_path = _tier_paths(tenant_id, TIER_REFERENCE)
        ref_meta = _load_meta(ref_meta_path)
        polluted = bool(ref_meta) and meta_has_polluted_section_ids(ref_meta)
        repaired = schema_recently_repaired(tenant_id)
        should_purge = force or epoch_changed or polluted or repaired

        if should_purge:
            logger.warning(
                "Purging reference FAISS for tenant=%s (epoch=%s polluted=%s repaired=%s force=%s)",
                tenant_id,
                epoch_changed,
                polluted,
                repaired,
                force,
            )
            purge_tier_from_disk(tenant_id, TIER_REFERENCE)
            purged.append(tenant_id)
            rebuilt.append(_rebuild_reference_index(tenant_id))
            if repaired:
                _consume_schema_repair_marker(tenant_id)

    if epoch_changed or purged:
        epoch_path.write_text(REFERENCE_VECTOR_EPOCH, encoding="utf-8")

    reset_rag_store()

    summary = {
        "epoch": REFERENCE_VECTOR_EPOCH,
        "epoch_changed": epoch_changed,
        "purged_tenants": purged,
        "rebuilt": rebuilt,
        "master_rebuilt": [],
    }
    if purged:
        logger.info(
            "Vector index guard: purged=%d epoch=%s",
            len(purged),
            REFERENCE_VECTOR_EPOCH,
        )
    return summary
