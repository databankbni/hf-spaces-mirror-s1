"""One-off: collapse duplicate reference uploads (metadata + disk files).

Keeps one library row and one physical file per unique document content. Shared
FAISS chunks are untouched — only ``compat_documents`` rows and surplus files
under ``reference_uploads/`` are removed.

Usage::

    python -m backend.scripts.dedupe_document_records [tenant_id ...]

With no tenant ids, all tenants under ``DATA_DIR/tenants/`` are processed.
"""

from __future__ import annotations

import sys

from backend.rag.store import get_rag_store
from backend.rag.types import TIER_REFERENCE
from backend.storage import tenant_store
from backend.storage.document_library import dedupe_tenant_storage
from backend.storage.report_session import list_documents


def dedupe_tenant(tenant_id: str) -> dict:
    store = get_rag_store()
    before_chunks = store.count(tenant_id, TIER_REFERENCE)
    stats = dedupe_tenant_storage(tenant_id)
    after_chunks = store.count(tenant_id, TIER_REFERENCE)
    return {
        "tenant": tenant_id,
        "docs_before": stats["docs_before"],
        "docs_after": stats["docs_after"],
        "records_removed": stats["records_removed"],
        "files_removed": stats["files_removed"],
        "ref_chunks_before": before_chunks,
        "ref_chunks_after": after_chunks,
    }


def main(argv: list[str]) -> int:
    tenants = argv[1:]
    if not tenants:
        root = tenant_store.tenant_root("").parent
        tenants = (
            [p.name for p in root.iterdir() if p.is_dir()] if root.is_dir() else []
        )
    for tenant_id in tenants:
        res = dedupe_tenant(tenant_id)
        if res["records_removed"] or res["files_removed"]:
            print(res)
        assert (
            res["ref_chunks_before"] == res["ref_chunks_after"]
        ), f"chunk count changed for {tenant_id}: {res}"
        assert len(list_documents(tenant_id)) == res["docs_after"]
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
