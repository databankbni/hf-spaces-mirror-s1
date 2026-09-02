"""
Vector store dùng FAISS + SQLite + BM25 hybrid search — Hierarchical RAG.

  - faiss.index    : tất cả vectors (L1 + L2 + L3)
  - chunks.db      : SQLite — bảng chunks, documents
  - documents      : catalog thư viện (title, category, page_count, toc_json)
  - BM25 per level : keyword search chính xác theo cấp

Hybrid search: FAISS + BM25 → rerank → trả về chunks kèm metadata đầy đủ.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from contextlib import contextmanager
from typing import List

import faiss
import numpy as np
from rank_bm25 import BM25Okapi

from config import BM25_WEIGHT, EMBEDDING_DIM, FAISS_INDEX_PATH, SQLITE_PATH, TOP_K, VECTOR_WEIGHT
from chunking import Chunk, DocMeta

logger = logging.getLogger(__name__)


@contextmanager
def _db_conn():
    conn = sqlite3.connect(str(SQLITE_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _init_db() -> None:
    with _db_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS chunks (
                id          INTEGER PRIMARY KEY,
                text        TEXT    NOT NULL,
                source_file TEXT    NOT NULL,
                page_start  INTEGER NOT NULL,
                page_end    INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                level       INTEGER NOT NULL DEFAULT 3,
                heading     TEXT    NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS documents (
                name        TEXT PRIMARY KEY,
                title       TEXT    NOT NULL DEFAULT '',
                category    TEXT    NOT NULL DEFAULT 'Tài liệu khác',
                page_count  INTEGER NOT NULL DEFAULT 0,
                toc_json    TEXT    NOT NULL DEFAULT '[]',
                summary     TEXT    NOT NULL DEFAULT '',
                topics_json TEXT    NOT NULL DEFAULT '[]',
                indexed_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_file);
            CREATE INDEX IF NOT EXISTS idx_chunks_level  ON chunks(level);
        """)
        # Migration: đổi indexed_files → documents nếu DB cũ
        try:
            conn.execute("""
                INSERT OR IGNORE INTO documents (name, title)
                SELECT name, name FROM indexed_files
            """)
        except Exception:
            pass
        # Migration: thêm cột level/heading nếu DB cũ chưa có
        for col, definition in [("level", "INTEGER NOT NULL DEFAULT 3"),
                                  ("heading", "TEXT NOT NULL DEFAULT ''")]:
            try:
                conn.execute(f"ALTER TABLE chunks ADD COLUMN {col} {definition}")
            except Exception:
                pass
        # Migration: thêm cột summary/topics_json cho documents
        for col, definition in [("summary", "TEXT NOT NULL DEFAULT ''"),
                                ("topics_json", "TEXT NOT NULL DEFAULT '[]'")]:
            try:
                conn.execute(f"ALTER TABLE documents ADD COLUMN {col} {definition}")
            except Exception:
                pass


class VectorStore:
    def __init__(self):
        self._index: faiss.Index | None = None
        self._id_to_level: dict[int, int] = {}
        self._bm25: dict[int, tuple[BM25Okapi, list[int]]] = {}
        _init_db()

    # ── FAISS persistence ──────────────────────────────────────────────────────

    def load(self) -> bool:
        if not FAISS_INDEX_PATH.exists():
            return False
        self._index = faiss.read_index(str(FAISS_INDEX_PATH))
        with _db_conn() as conn:
            n_docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        logger.info("Đã nạp FAISS: %d vector, %d tài liệu", self._index.ntotal, n_docs)
        self._build_bm25()
        return True

    def save(self) -> None:
        if self._index is None:
            return
        faiss.write_index(self._index, str(FAISS_INDEX_PATH))
        logger.info("Đã lưu FAISS index (%d vector)", self._index.ntotal)

    # ── BM25 ───────────────────────────────────────────────────────────────────

    def _build_bm25(self) -> None:
        with _db_conn() as conn:
            rows = conn.execute(
                "SELECT id, text, level FROM chunks ORDER BY id"
            ).fetchall()

        self._id_to_level = {row["id"]: row["level"] for row in rows}

        by_level: dict[int, list[tuple[int, str]]] = {}
        for row in rows:
            by_level.setdefault(row["level"], []).append((row["id"], row["text"]))

        self._bm25 = {}
        for level, items in by_level.items():
            ids = [i for i, _ in items]
            corpus = [t.lower().split() for _, t in items]
            self._bm25[level] = (BM25Okapi(corpus), ids)

        logger.info("BM25 rebuilt: %s", {lvl: len(v[1]) for lvl, v in self._bm25.items()})

    # ── Document catalog ───────────────────────────────────────────────────────

    def is_indexed(self, source_name: str) -> bool:
        with _db_conn() as conn:
            return conn.execute(
                "SELECT 1 FROM documents WHERE name = ?", (source_name,)
            ).fetchone() is not None

    def upsert_document(self, source_name: str, meta: DocMeta) -> None:
        with _db_conn() as conn:
            conn.execute(
                """INSERT INTO documents (name, title, category, page_count, toc_json, summary, topics_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                     title=excluded.title,
                     category=excluded.category,
                     page_count=excluded.page_count,
                     toc_json=excluded.toc_json,
                     summary=excluded.summary,
                     topics_json=excluded.topics_json,
                     indexed_at=datetime('now', 'localtime')
                """,
                (source_name, meta.title, meta.category, meta.page_count,
                 json.dumps(meta.toc, ensure_ascii=False),
                 meta.summary,
                 json.dumps(meta.topics, ensure_ascii=False)),
            )

    def get_all_documents(self) -> list[dict]:
        with _db_conn() as conn:
            rows = conn.execute(
                "SELECT name, title, category, page_count, summary, topics_json, indexed_at "
                "FROM documents ORDER BY indexed_at DESC"
            ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["topics"] = json.loads(d.pop("topics_json") or "[]")
            result.append(d)
        return result

    def get_document(self, name: str) -> dict | None:
        with _db_conn() as conn:
            row = conn.execute(
                "SELECT name, title, category, page_count, toc_json, summary, topics_json, indexed_at "
                "FROM documents WHERE name = ?",
                (name,)
            ).fetchone()
        if row is None:
            return None
        doc = dict(row)
        doc["toc"] = json.loads(doc.pop("toc_json") or "[]")
        doc["topics"] = json.loads(doc.pop("topics_json") or "[]")
        return doc

    def get_library_stats(self) -> dict:
        with _db_conn() as conn:
            total_docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            total_pages = conn.execute("SELECT COALESCE(SUM(page_count), 0) FROM documents").fetchone()[0]
            categories = conn.execute(
                "SELECT category, COUNT(*) as count FROM documents GROUP BY category ORDER BY count DESC"
            ).fetchall()
            total_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        return {
            "total_documents": total_docs,
            "total_pages": total_pages,
            "total_chunks": total_chunks,
            "categories": [{"category": r["category"], "count": r["count"]} for r in categories],
        }

    def find_document_by_keyword(self, keyword: str) -> dict | None:
        """Tìm tài liệu theo từ khóa trong tên hoặc tiêu đề."""
        kw = f"%{keyword.lower()}%"
        with _db_conn() as conn:
            row = conn.execute(
                """SELECT name, title, category, page_count, toc_json, summary, topics_json, indexed_at
                   FROM documents
                   WHERE lower(name) LIKE ? OR lower(title) LIKE ?
                   LIMIT 1""",
                (kw, kw)
            ).fetchone()
        if row is None:
            return None
        doc = dict(row)
        doc["toc"] = json.loads(doc.pop("toc_json") or "[]")
        doc["topics"] = json.loads(doc.pop("topics_json") or "[]")
        return doc

    def get_l1_chunk(self, source_name: str) -> dict | None:
        """Lấy L1 (document summary) chunk của một tài liệu."""
        with _db_conn() as conn:
            row = conn.execute(
                "SELECT * FROM chunks WHERE source_file = ? AND level = 1 LIMIT 1",
                (source_name,)
            ).fetchone()
        return dict(row) if row else None

    # ── Indexing ───────────────────────────────────────────────────────────────

    def add_chunks(self, chunks: List[Chunk], embeddings: np.ndarray) -> None:
        if self._index is None:
            self._index = faiss.IndexFlatIP(EMBEDDING_DIM)

        offset = self._index.ntotal
        self._index.add(embeddings)

        with _db_conn() as conn:
            conn.executemany(
                """INSERT INTO chunks
                     (id, text, source_file, page_start, page_end, chunk_index, level, heading)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        offset + i,
                        chunk.text,
                        chunk.source_file,
                        chunk.page_start,
                        chunk.page_end,
                        chunk.chunk_index,
                        chunk.level,
                        chunk.heading,
                    )
                    for i, chunk in enumerate(chunks)
                ],
            )

        self._build_bm25()

    # ── Search ─────────────────────────────────────────────────────────────────

    def hybrid_search(
        self,
        query_embedding: np.ndarray,
        query_text: str,
        k: int = TOP_K,
        levels: tuple[int, ...] = (2, 3),
        source_filter: str | None = None,
    ) -> list[dict]:
        """
        Hybrid search (FAISS + BM25).
        source_filter: nếu có, chỉ trả kết quả từ tài liệu đó.
        """
        if self._index is None or self._index.ntotal == 0:
            return []

        t0 = time.perf_counter()
        candidate_k = min(k * 15, self._index.ntotal)
        faiss_scores, faiss_indices = self._index.search(query_embedding, candidate_k)

        faiss_map: dict[int, float] = {}
        for score, idx in zip(faiss_scores[0], faiss_indices[0]):
            if idx != -1:
                doc_id = int(idx)
                if self._id_to_level.get(doc_id) in levels:
                    faiss_map[doc_id] = float(score)

        bm25_map: dict[int, float] = {}
        tokens = query_text.lower().split()
        for level in levels:
            if level not in self._bm25:
                continue
            bm25_model, bm25_ids = self._bm25[level]
            raw_scores = bm25_model.get_scores(tokens)
            top_pos = np.argsort(raw_scores)[::-1][:k * 3]
            for pos in top_pos:
                doc_id = bm25_ids[pos]
                bm25_map[doc_id] = max(bm25_map.get(doc_id, 0.0), float(raw_scores[pos]))

        all_ids = set(faiss_map) | set(bm25_map)
        if not all_ids:
            return []

        faiss_max = max(faiss_map.values(), default=1.0) or 1.0
        bm25_max = max(bm25_map.values(), default=1.0) or 1.0

        combined: dict[int, float] = {
            doc_id: (
                VECTOR_WEIGHT * faiss_map.get(doc_id, 0.0) / faiss_max
                + BM25_WEIGHT * bm25_map.get(doc_id, 0.0) / bm25_max
            )
            for doc_id in all_ids
        }

        top_ids = sorted(combined, key=lambda x: combined[x], reverse=True)[:k * 3]

        placeholders = ",".join("?" * len(top_ids))
        filter_clause = f"AND source_file = ?" if source_filter else ""
        params = top_ids + ([source_filter] if source_filter else [])
        with _db_conn() as conn:
            rows = conn.execute(
                f"SELECT id, text, source_file, page_start, page_end, level, heading "
                f"FROM chunks WHERE id IN ({placeholders}) {filter_clause}",
                params,
            ).fetchall()

        row_by_id = {row["id"]: dict(row) for row in rows}
        results = []
        for doc_id in top_ids:
            if doc_id not in row_by_id:
                continue
            meta = row_by_id[doc_id]
            meta["score"] = round(combined[doc_id], 4)
            results.append(meta)
            if len(results) >= k:
                break

        logger.info("  [search] %.0fms | faiss=%d bm25=%d → %d kết quả",
                    1000 * (time.perf_counter() - t0),
                    len(faiss_map), len(bm25_map), len(results))
        return results

    @property
    def total_vectors(self) -> int:
        return self._index.ntotal if self._index else 0


_store: VectorStore | None = None


def get_store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore()
        _store.load()
    return _store


def reset_store() -> VectorStore:
    """Reset singleton sau khi xóa index trên disk để tránh dùng dữ liệu cũ trong RAM."""
    global _store
    _store = VectorStore()
    return _store
