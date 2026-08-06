"""建立檢索索引：chromadb（向量）+ bm25s（關鍵詞），供 hybrid 檢索使用。

流程：laws.json → chunking（GTAIDE tokenizer 計數，chunk 與模型無關）→
Contextual 摘要前置（可關閉）→ 向量入 chroma、合成文字入 bm25s。

從 `scripts/build_index.py` 抽出（Phase 7），比照 Phase 6 `pipeline.py` 先例：
CLI（`scripts/build_index.py`）與 `retriever.py`（HF Space 冷啟動自動建索引）
共用同一份邏輯，避免兩處分岔。`build_chroma()` 可接收呼叫端已載入的 embedder
（Space 自動建索引時重用 `HybridRetriever` 已載入的實例，不必重複載入模型）。

Contextual 摘要缺漏且未確認成本時拋 `ContextualCostConfirmationRequired`——
**絕不靜默呼叫付費 API**：CLI 由使用者加 `--confirm-cost` 處理；Space 自動
建索引固定傳 `confirm_cost=False`，缺漏代表凍結資料被意外改動，必須讓它
明確失敗、由作者查明，而不是在使用者看不到的地方偷偷花錢。
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .chunking import Chunk, chunk_articles, gtaide_token_counter
from .config import DATA_DIR, get_settings
from .contextual import (
    ContextualCache,
    composite_text,
    estimate_cost,
    generate_summaries,
)
from .knowledge_base import (
    INDEX_MANIFEST_PATH,
    activate_index_manifest,
    atomic_write_json,
    build_law_manifest,
)

CHROMA_DIR = DATA_DIR / "chroma"
BM25_DIR = DATA_DIR / "bm25s"
CACHE_PATH = DATA_DIR / "contextual_cache.json"
USERDICT_PATH = Path(__file__).resolve().parent / "legal_userdict.txt"

# 精簡中文停用詞（法規語境：連接詞與虛詞；保留「應」「得」等規範動詞的名詞搭配由 BM25 自行處理）
STOPWORDS = set("的之及或與其於者所如各由並而亦均即因此惟另嗣後暨等到自從、，。；：（）「」")
INDEX_SCHEMA_VERSION = "hybrid-index-v1"


class ContextualCostConfirmationRequired(RuntimeError):
    """Contextual 快取有缺漏、且呼叫端未確認成本。"""


def load_chunks() -> tuple[list[Chunk], dict[str, str], object]:
    settings = get_settings()
    data = json.loads((DATA_DIR / "laws.json").read_text(encoding="utf-8"))
    counter = gtaide_token_counter(settings.embedding_model, settings.hf_token)
    chunks = chunk_articles(data["articles"], counter)
    law_texts: dict[str, list[str]] = {}
    for a in data["articles"]:
        law_texts.setdefault(a["law_name"], []).append(
            f"第 {a['article_no']} 條\r\n{a['content']}"
        )
    return chunks, {k: "\r\n\r\n".join(v) for k, v in law_texts.items()}, counter


def ensure_contextual(
    chunks: list[Chunk], law_texts: dict[str, str], counter, confirm_cost: bool
) -> ContextualCache:
    settings = get_settings()
    cache = ContextualCache(CACHE_PATH)
    pending = cache.pending(chunks)
    if not pending:
        print(f"contextual 快取齊全（{len(chunks)} chunks）")
        return cache
    est = estimate_cost(pending, law_texts, counter)
    print(f"\n=== Contextual 摘要成本估算（模型 {settings.gemini_lite_model}）===")
    print(f"待生成 chunks：{est.n_chunks}")
    print(f"預估輸入 tokens：{est.input_tokens:,}（含各法全文為共享前綴）")
    print(f"預估輸出 tokens：{est.output_tokens:,}")
    print(f"上限估算（無快取折扣）：US${est.cost_no_cache:.3f}")
    print(f"樂觀估算（隱式快取命中）：US${est.cost_with_implicit_cache:.3f}")
    if not confirm_cost:
        raise ContextualCostConfirmationRequired(
            f"{est.n_chunks} 個 chunk 尚無 contextual 摘要快取，且未確認成本"
            "（CLI 請加 --confirm-cost 或 --no-contextual；若在 Space 自動建索引"
            "時看到此訊息，代表凍結資料被意外改動，請勿直接允許呼叫，先查明原因）"
        )
    print("\n已確認成本，開始生成…")
    generate_summaries(
        pending, law_texts, cache,
        settings.gemini_lite_model, api_key=settings.google_api_key,
    )
    print(f"完成，快取寫入 {CACHE_PATH.name}")
    return cache


def jieba_tokenize(texts: list[str]) -> list[list[str]]:
    import jieba

    if USERDICT_PATH.exists():
        jieba.load_userdict(str(USERDICT_PATH))
    return [
        [t for t in jieba.lcut(text) if t.strip() and t not in STOPWORDS]
        for text in texts
    ]


def build_chroma(
    chunks: list[Chunk], texts: list[str], embedding_key: str, dim: int | None,
    contextual: bool, embedder=None,
) -> str:
    """embedder 由呼叫端提供時重用（Space 自動建索引重用 HybridRetriever 已載入
    的實例，省一次模型載入）；未提供時依 embedding_key/dim 自行載入（CLI 用）。"""
    import chromadb

    settings = get_settings()
    if embedder is None:
        model_id = (
            settings.embedding_model if embedding_key == "gtaide"
            else settings.embedding_baseline_model
        )
        from .embeddings import STEmbeddings

        embedder = STEmbeddings(model_id, truncate_dim=dim, hf_token=settings.hf_token)
    vectors = embedder.embed_documents(texts)
    actual_dim = len(vectors[0])

    name = f"{embedding_key}_{actual_dim}_{'ctx' if contextual else 'noctx'}"
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    try:
        client.delete_collection(name)
    except Exception:  # noqa: BLE001 - 不存在即略過
        pass
    coll = client.create_collection(name, metadata={"hnsw:space": "cosine"})
    coll.add(
        ids=[c.chunk_id for c in chunks],
        embeddings=vectors,
        documents=texts,
        metadatas=[{
            "law_name": c.law_name,
            "pcode": c.pcode,
            "article_no": c.article_no,
            "chapter": c.chapter or "",
            "url": c.url,
            "parent_id": c.parent_id,
            "part": c.part,
        } for c in chunks],
    )
    return name


def build_bm25(
    chunks: list[Chunk],
    texts: list[str],
    contextual: bool,
    out_dir: Path | None = None,
) -> Path:
    import bm25s

    out_dir = out_dir or BM25_DIR / ("ctx" if contextual else "noctx")
    out_dir.mkdir(parents=True, exist_ok=True)
    tokens = jieba_tokenize(texts)
    retriever = bm25s.BM25()
    retriever.index(tokens)
    retriever.save(str(out_dir))
    (out_dir / "chunk_ids.json").write_text(
        json.dumps([c.chunk_id for c in chunks], ensure_ascii=False),
        encoding="utf-8", newline="\n",
    )
    return out_dir


class RetrievalRegressionError(RuntimeError):
    """A candidate index is left inactive when locked retrieval regresses."""


def build_chroma_incremental(
    chunks: list[Chunk],
    texts: list[str],
    embedding_key: str,
    contextual: bool,
    version: str,
    *,
    embedder,
    previous_collection_name: str | None = None,
) -> tuple[str, int, int, int]:
    """Build a new immutable collection while reusing unchanged embeddings.

    Chroma collections are versioned instead of mutated in place.  Documents
    whose composite text is unchanged copy their previous vector; only changed
    or new chunks call the embedding model.  The previous collection remains
    available for rollback.
    """
    import chromadb

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    previous_vectors: dict[str, list[float]] = {}
    previous_documents: dict[str, str] = {}
    if previous_collection_name:
        try:
            previous = client.get_collection(previous_collection_name)
            old = previous.get(include=["documents", "embeddings"])
            embeddings = old.get("embeddings")
            if embeddings is not None:
                for cid, document, vector in zip(
                    old["ids"], old["documents"], embeddings
                ):
                    previous_documents[cid] = document
                    previous_vectors[cid] = [float(value) for value in vector]
        except Exception:  # noqa: BLE001 - corrupted/missing old index means re-embed
            previous_vectors = {}
            previous_documents = {}

    vectors_by_id: dict[str, list[float]] = {}
    changed_chunks: list[Chunk] = []
    changed_texts: list[str] = []
    for chunk, text in zip(chunks, texts):
        if (
            chunk.chunk_id in previous_vectors
            and previous_documents.get(chunk.chunk_id) == text
        ):
            vectors_by_id[chunk.chunk_id] = previous_vectors[chunk.chunk_id]
        else:
            changed_chunks.append(chunk)
            changed_texts.append(text)

    if changed_texts:
        new_vectors = embedder.embed_documents(changed_texts)
        vectors_by_id.update({
            chunk.chunk_id: [float(value) for value in vector]
            for chunk, vector in zip(changed_chunks, new_vectors)
        })
    if not vectors_by_id:
        raise ValueError("cannot build an empty vector index")

    actual_dim = len(next(iter(vectors_by_id.values())))
    suffix = version.replace("_", "-")[-32:]
    name = f"{embedding_key}-{actual_dim}-{'ctx' if contextual else 'noctx'}-{suffix}"
    if previous_collection_name == name:
        # Repairing a same-version local artifact must not delete the
        # collection currently referenced by the active manifest.
        name = f"{name}-candidate-{uuid4().hex[:8]}"
    # A same-version retry may leave an incomplete candidate.  It is never the
    # active collection because activation happens only after regression.
    try:
        client.delete_collection(name)
    except Exception:  # noqa: BLE001 - exact candidate does not exist
        pass
    collection = client.create_collection(
        name,
        metadata={
            "hnsw:space": "cosine",
            "index_schema_version": INDEX_SCHEMA_VERSION,
            "version": version,
        },
    )
    ordered_vectors = [vectors_by_id[chunk.chunk_id] for chunk in chunks]
    try:
        collection.add(
            ids=[chunk.chunk_id for chunk in chunks],
            embeddings=ordered_vectors,
            documents=texts,
            metadatas=[{
                "law_name": chunk.law_name,
                "pcode": chunk.pcode,
                "article_no": chunk.article_no,
                "chapter": chunk.chapter or "",
                "url": chunk.url,
                "parent_id": chunk.parent_id,
                "part": chunk.part,
            } for chunk in chunks],
        )
    except Exception:
        client.delete_collection(name)
        raise
    return name, actual_dim, len(chunks) - len(changed_chunks), len(changed_chunks)


def run_retrieval_regression(
    collection_name: str,
    bm25_dir: Path,
    embedder,
    *,
    testset_path: Path = DATA_DIR / "testset.json",
    minimum_recall: float = 0.90,
) -> dict:
    """Locked, generation-free candidate recall check before index activation."""
    import bm25s
    import chromadb

    from .retriever import BM25_TOP_K, VECTOR_TOP_K, rrf_fuse

    testset = json.loads(testset_path.read_text(encoding="utf-8"))
    items = list(testset["items"])
    collection = chromadb.PersistentClient(path=str(CHROMA_DIR)).get_collection(
        collection_name
    )
    bm25 = bm25s.BM25.load(str(bm25_dir))
    bm25_ids = json.loads(
        (bm25_dir / "chunk_ids.json").read_text(encoding="utf-8")
    )
    query_vectors = embedder.embed_documents([item["question"] for item in items])
    raw: list[dict] = []
    hits = 0
    for item, vector in zip(items, query_vectors):
        rankings: dict[str, list[str]] = {}
        tokens = jieba_tokenize([item["question"]])[0]
        if tokens:
            result, _scores = bm25.retrieve(
                [tokens], k=min(BM25_TOP_K, len(bm25_ids))
            )
            rankings["bm25"] = [bm25_ids[int(index)] for index in result[0]]
        dense = collection.query(
            query_embeddings=[vector],
            n_results=VECTOR_TOP_K,
            include=["metadatas"],
        )
        rankings["dense"] = dense["ids"][0]
        fused_ids = [cid for cid, _score, _sources in rrf_fuse(rankings)[:20]]
        got = collection.get(ids=fused_ids, include=["metadatas"])
        parent_by_id = {
            cid: meta["parent_id"]
            for cid, meta in zip(got["ids"], got["metadatas"])
        }
        parents = [parent_by_id[cid] for cid in fused_ids if cid in parent_by_id]
        expected = set(item["expected_parent_ids"])
        hit = bool(expected & set(parents))
        hits += int(hit)
        raw.append({
            "id": item["id"],
            "hit": hit,
            "expected_parent_ids": sorted(expected),
            "candidate_parent_ids": parents,
        })
    recall = hits / len(items) if items else 0.0
    return {
        "name": "locked_hybrid_candidate_recall_at_20",
        "testset": (
            testset_path.relative_to(DATA_DIR.parent).as_posix()
            if testset_path.is_relative_to(DATA_DIR.parent)
            else str(testset_path)
        ),
        "count": len(items),
        "recall_at_20": recall,
        "minimum_recall": minimum_recall,
        "passed": recall >= minimum_recall,
        "raw": raw,
    }


def build_versioned_index(
    embedding_key: str = "gtaide",
    dim: int | None = None,
    contextual: bool = True,
    confirm_cost: bool = False,
    embedder=None,
    *,
    regression_minimum_recall: float = 0.90,
    manifest_path: Path = INDEX_MANIFEST_PATH,
    force_regression: bool = False,
) -> dict:
    """Build, regress and atomically activate a versioned hybrid index."""
    settings = get_settings()
    laws = json.loads((DATA_DIR / "laws.json").read_text(encoding="utf-8"))
    law_manifest = build_law_manifest(laws)
    variant = f"{embedding_key}-{'native' if dim is None else dim}-{'ctx' if contextual else 'noctx'}"
    version = f"{INDEX_SCHEMA_VERSION}-{law_manifest['corpus_hash'][:12]}-{variant}"

    previous = None
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            previous.get("active_version") == version
            and previous.get("state") == "ready"
        ):
            candidate_bm25 = Path(previous["bm25_path"])
            if not candidate_bm25.is_absolute():
                candidate_bm25 = DATA_DIR / candidate_bm25
            try:
                import chromadb

                collection = chromadb.PersistentClient(
                    path=str(CHROMA_DIR)
                ).get_collection(previous["collection_name"])
                if (
                    collection.count() == int(previous["chunk_count"])
                    and (candidate_bm25 / "chunk_ids.json").exists()
                ):
                    manifest_updated = False
                    if force_regression:
                        if embedder is None:
                            model_id = (
                                settings.embedding_model
                                if embedding_key == "gtaide"
                                else settings.embedding_baseline_model
                            )
                            from .embeddings import STEmbeddings

                            embedder = STEmbeddings(
                                model_id,
                                truncate_dim=dim,
                                hf_token=settings.hf_token,
                            )
                        regression = run_retrieval_regression(
                            previous["collection_name"],
                            candidate_bm25,
                            embedder,
                            minimum_recall=regression_minimum_recall,
                        )
                        if not regression["passed"]:
                            raise RetrievalRegressionError(
                                f"active recall {regression['recall_at_20']:.3f} "
                                f"< required {regression_minimum_recall:.3f}; "
                                "law snapshot binding unchanged"
                            )
                        previous = {
                            **previous,
                            "regression": regression,
                            "last_regression_verified_at": datetime.now(
                                UTC
                            ).isoformat(timespec="seconds"),
                        }
                        manifest_updated = True
                    if previous.get("law_version") != law_manifest["version"]:
                        previous = {
                            **previous,
                            "law_version": law_manifest["version"],
                            "law_corpus_hash": law_manifest["corpus_hash"],
                            "source_metadata_only_refresh": True,
                            "law_snapshot_activated_at": datetime.now(
                                UTC
                            ).isoformat(timespec="seconds"),
                        }
                        manifest_updated = True
                    if manifest_updated:
                        atomic_write_json(manifest_path, previous)
                    return previous
            except Exception:  # noqa: BLE001 - rebuild missing/corrupt local artifacts
                pass

    chunks, law_texts, counter = load_chunks()
    summaries: dict[str, str | None] = {}
    if contextual:
        cache = ensure_contextual(chunks, law_texts, counter, confirm_cost)
        summaries = {chunk.chunk_id: cache.get(chunk) for chunk in chunks}
    texts = [
        composite_text(chunk, summaries.get(chunk.chunk_id))
        for chunk in chunks
    ]
    if embedder is None:
        model_id = (
            settings.embedding_model
            if embedding_key == "gtaide"
            else settings.embedding_baseline_model
        )
        from .embeddings import STEmbeddings

        embedder = STEmbeddings(
            model_id,
            truncate_dim=dim,
            hf_token=settings.hf_token,
        )

    previous_collection = None
    if previous and previous.get("variant") == variant:
        previous_collection = previous.get("collection_name")
    collection_name, actual_dim, reused, embedded = build_chroma_incremental(
        chunks,
        texts,
        embedding_key,
        contextual,
        version,
        embedder=embedder,
        previous_collection_name=previous_collection,
    )

    final_bm25_dir = BM25_DIR / "versions" / version
    stage_bm25_dir = BM25_DIR / "versions" / f".{version}.{uuid4().hex}.staging"
    try:
        build_bm25(chunks, texts, contextual, out_dir=stage_bm25_dir)
        if final_bm25_dir.exists():
            try:
                import bm25s

                bm25s.BM25.load(str(final_bm25_dir))
                json.loads(
                    (final_bm25_dir / "chunk_ids.json").read_text(encoding="utf-8")
                )
                shutil.rmtree(stage_bm25_dir)
            except Exception:
                shutil.rmtree(final_bm25_dir)
                stage_bm25_dir.replace(final_bm25_dir)
        else:
            stage_bm25_dir.replace(final_bm25_dir)
        regression = run_retrieval_regression(
            collection_name,
            final_bm25_dir,
            embedder,
            minimum_recall=regression_minimum_recall,
        )
        if not regression["passed"]:
            raise RetrievalRegressionError(
                f"candidate recall {regression['recall_at_20']:.3f} "
                f"< required {regression_minimum_recall:.3f}; active index unchanged"
            )
    except Exception:
        if stage_bm25_dir.exists():
            shutil.rmtree(stage_bm25_dir)
        raise

    candidate = {
        "version": version,
        "state": "ready",
        "variant": variant,
        "embedding_key": embedding_key,
        "embedding_model": (
            settings.embedding_model
            if embedding_key == "gtaide"
            else settings.embedding_baseline_model
        ),
        "dimension": actual_dim,
        "contextual": contextual,
        "collection_name": collection_name,
        "bm25_path": final_bm25_dir.relative_to(DATA_DIR).as_posix(),
        "law_version": law_manifest["version"],
        "law_corpus_hash": law_manifest["corpus_hash"],
        "chunk_count": len(chunks),
        "reused_embedding_count": reused,
        "embedded_chunk_count": embedded,
        "bm25_rebuild_reason": "global IDF requires a bounded full rebuild",
        "regression": regression,
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    return activate_index_manifest(candidate, manifest_path=manifest_path)


def build_index(
    embedding_key: str = "gtaide", dim: int | None = None, contextual: bool = True,
    confirm_cost: bool = False, embedder=None,
) -> str:
    """完整建一次索引（chroma + bm25s），回傳 chroma collection 名稱。

    CLI（`scripts/build_index.py`）與 `retriever.py` 的 Space 冷啟動自動建索引
    共用本函式；差異只在 `embedder`（有無重用既有實例）與 `confirm_cost`。
    """
    chunks, law_texts, counter = load_chunks()
    print(f"chunks：{len(chunks)}")

    summaries: dict[str, str | None] = {}
    if contextual:
        cache = ensure_contextual(chunks, law_texts, counter, confirm_cost)
        summaries = {c.chunk_id: cache.get(c) for c in chunks}
    texts = [composite_text(c, summaries.get(c.chunk_id)) for c in chunks]

    coll_name = build_chroma(chunks, texts, embedding_key, dim, contextual, embedder=embedder)
    print(f"chroma collection：{coll_name}（{len(chunks)} 筆）")
    bm25_dir = build_bm25(chunks, texts, contextual)
    try:
        bm25_display = bm25_dir.relative_to(DATA_DIR.parent)
    except ValueError:  # BM25_DIR 被覆寫到 repo 外（如測試用 tmp_path）時印絕對路徑
        bm25_display = bm25_dir
    print(f"bm25s 索引：{bm25_display}")
    return coll_name
