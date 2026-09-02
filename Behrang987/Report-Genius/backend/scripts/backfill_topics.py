"""Backfill content-taxonomy topics and theme tags onto already-ingested chunks.

Classifies every stored past-report and standard-paragraph chunk into the content
taxonomy (topic_id / subtopic_id / theme_tags) in place, reusing the stored vectors
— no re-embedding and no re-upload. Run it so existing tenants become usable in the
content-based topic report mode, and again after any taxonomy change: notes are
classified under the live taxonomy, so chunks tagged under an older one stop
matching and content mode quietly retrieves nothing.

Usage::

    python -m backend.scripts.backfill_topics [tenant_id ...]
    python -m backend.scripts.backfill_topics --check [tenant_id ...]

With no tenant ids, all tenants under ``DATA_DIR/tenants/`` are processed.
``--check`` reports what would be re-tagged and writes nothing.
"""

from __future__ import annotations

import sys

from backend.content_based.taxonomy import CONTENT_TAXONOMY_VERSION
from backend.rag.store import get_rag_store
from backend.rag.types import TIER_REFERENCE, TIER_STANDARD_PARAGRAPHS
from backend.storage import tenant_store

_TIERS = (TIER_REFERENCE, TIER_STANDARD_PARAGRAPHS)


def backfill_tenant(tenant_id: str) -> dict:
    store = get_rag_store()
    out: dict[str, dict] = {}
    for tier in _TIERS:
        if store.count(tenant_id, tier) == 0:
            continue
        out[tier] = store.retag_topics(tenant_id, tier)
    return {"tenant": tenant_id, "coverage": out}


def check_tenant(tenant_id: str) -> dict:
    """Read-only: how this tenant's stored tags line up with the live taxonomy."""
    store = get_rag_store()
    out: dict[str, dict] = {}
    for tier in _TIERS:
        if store.count(tenant_id, tier) == 0:
            continue
        out[tier] = store.taxonomy_version_status(tenant_id, tier)
    return {"tenant": tenant_id, "status": out}


def _all_tenant_ids() -> list[str]:
    root = tenant_store.tenant_root("").parent
    return [p.name for p in root.iterdir() if p.is_dir()] if root.is_dir() else []


def main(argv: list[str]) -> int:
    args = argv[1:]
    check_only = "--check" in args
    tenants = [a for a in args if not a.startswith("-")] or _all_tenant_ids()
    print(f"live taxonomy: {CONTENT_TAXONOMY_VERSION}")
    for tenant_id in tenants:
        res = check_tenant(tenant_id) if check_only else backfill_tenant(tenant_id)
        if res.get("status") or res.get("coverage"):
            print(res)
    print("checked (nothing written)" if check_only else "done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
