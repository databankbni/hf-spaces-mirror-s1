# ---------------------------------------------------------------------------
# ingestion/build_corpus.py — Phase A2.
#
# Take the normalized verse rows and persist them into two stores:
#
#   1. SQLite (data/gita.sqlite, table `verses`) — the source of truth for
#      reading. Indexed on (chapter, verse) for ordered traversal.
#   2. Chroma (data/.chroma, collection `gita_verses`) — English-translation
#      embeddings, used ONLY by the chat panel's semantic search.
#
# `ensure_corpus()` is the idempotent entry point app.py calls at startup:
# it builds only if the SQLite table is missing/empty, mirroring the
# ensure_index() pattern from the smoltestagent Space.
# ---------------------------------------------------------------------------

import sqlite3

from config import CHROMA_DIR, COLLECTION_NAME, DB_PATH, DATA_DIR

_SCHEMA = """
CREATE TABLE IF NOT EXISTS verses (
    verse_id    TEXT PRIMARY KEY,
    chapter     INTEGER NOT NULL,
    verse       INTEGER NOT NULL,
    title       TEXT,
    sanskrit    TEXT NOT NULL,
    english     TEXT NOT NULL,
    hindi       TEXT,
    sa_seconds  REAL,
    en_seconds  REAL
);
CREATE INDEX IF NOT EXISTS idx_verses_order ON verses (chapter, verse);
"""


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _write_sqlite(rows: list[dict]) -> None:
    conn = _connect()
    try:
        conn.executescript(_SCHEMA)
        conn.execute("DELETE FROM verses")  # full rebuild — no duplicates
        conn.executemany(
            """
            INSERT INTO verses
                (verse_id, chapter, verse, title, sanskrit, english, hindi)
            VALUES
                (:verse_id, :chapter, :verse, :title, :sanskrit, :english, :hindi)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def _write_chroma(rows: list[dict]) -> None:
    import chromadb

    from ingestion.embedder import Embedder

    print("[build_corpus] loading embedder...")
    embedder = Embedder()
    english_texts = [r["english"] for r in rows]
    print(f"[build_corpus] embedding {len(english_texts)} verses...")
    embeddings = embedder.embed_batch(english_texts)

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    # chromadb >=0.6.0 returns collection *names* (strings) from
    # list_collections(); older releases returned Collection objects.
    existing = {c if isinstance(c, str) else c.name for c in client.list_collections()}
    if COLLECTION_NAME in existing:
        client.delete_collection(COLLECTION_NAME)
    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    collection.add(
        ids=[r["verse_id"] for r in rows],
        embeddings=embeddings,
        documents=english_texts,
        metadatas=[
            {
                "verse_id": r["verse_id"],
                "chapter": r["chapter"],
                "verse": r["verse"],
            }
            for r in rows
        ],
    )
    print(f"[build_corpus] chroma collection has {collection.count()} records")


def build_corpus() -> None:
    """Fetch verses and (re)build both SQLite and Chroma from scratch."""
    from ingestion.fetch_dataset import fetch_verses

    rows = fetch_verses()
    print(f"[build_corpus] fetched {len(rows)} verses")
    _write_sqlite(rows)
    print(f"[build_corpus] wrote SQLite at {DB_PATH}")
    _write_chroma(rows)
    print("[build_corpus] done")


def _verse_count() -> int:
    if not DB_PATH.exists():
        return 0
    conn = _connect()
    try:
        conn.executescript(_SCHEMA)
        row = conn.execute("SELECT COUNT(*) AS n FROM verses").fetchone()
        return int(row["n"])
    finally:
        conn.close()


def ensure_corpus() -> None:
    """Build the corpus only if SQLite is missing or empty. Safe to call
    repeatedly — cheap no-op once the table is populated."""
    count = _verse_count()
    if count > 0:
        print(f"[ensure_corpus] {count} verses already present, skipping build.")
        return
    build_corpus()


if __name__ == "__main__":
    build_corpus()
