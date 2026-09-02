"""Ingest grouped_responses_full.json into the standard_paragraphs FAISS tier."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `python scripts/...` from repo root.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.config import settings  # noqa: E402
from backend.llm.embeddings import get_embedder, reset_embedder  # noqa: E402
from backend.rag.store import get_rag_store  # noqa: E402
from backend.rag.types import TIER_STANDARD_PARAGRAPHS  # noqa: E402
from backend.standard_paragraphs import service as sp_service  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        type=Path,
        default=_ROOT
        / "backend"
        / "standard_paragraphs"
        / "samples"
        / "grouped_responses_full.json",
    )
    parser.add_argument(
        "--tenant",
        default=settings.default_tenant_id,
        help="Tenant id (default: settings.default_tenant_id)",
    )
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()

    print("embedding_provider=", settings.embedding_provider)
    print("openai_embedding_model=", settings.openai_embedding_model)
    print("tenant=", args.tenant)
    print("json=", args.json)

    reset_embedder()
    emb = get_embedder()
    print("embed_dim=", emb.embed_dim)

    result = sp_service.ingest_from_grouped_json(
        args.tenant,
        args.json,
        batch_size=args.batch_size,
    )
    store = get_rag_store()
    total = store.count(args.tenant, TIER_STANDARD_PARAGRAPHS)
    print("ingest_result=", result)
    print("tier_total_chunks=", total)

    # Smoke: D1 similarity search
    hits = store.search(
        args.tenant,
        "chimney stacks brick flaunching",
        tier=TIER_STANDARD_PARAGRAPHS,
        top_k=3,
        section_id="D1",
        section_strict=True,
    )
    print("D1_sample_hits=", len(hits))
    for h in hits:
        print(" -", round(h.score, 4), (h.text or "")[:100].replace("\n", " "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
