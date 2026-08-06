"""
indexer.py — Build ChromaDB vector index from Bible SQLite files.

Usage:
    python -m luther_mcp index [--force]

Environment variables:
    BIBLE_DB_PATH    Path to scrollmapper formats/sqlite/ directory
                     (default: ../bible_databases/formats/sqlite relative to package root)
    CHROMA_PATH      Where to store ChromaDB (default: ./bible_chroma_db)
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

from .constants import BOOK_NAMES_DE, BOOK_NAMES_EN, TRANSLATIONS

BATCH_SIZE = 512
MODEL_NAME = "intfloat/multilingual-e5-small"


def get_testament(book_number: int) -> str:
    return "OT" if book_number <= 39 else "NT"


def load_verses(db_path: Path, collection_name: str) -> list[dict]:
    """Load all verses from a Bible SQLite file.

    The scrollmapper repo uses translation-specific table names, e.g.:
      GerBoLut_verses (book_id, chapter, verse, text)
    The 'web' collection maps to NHEB.db, so its table is NHEB_verses.
    """
    TABLE_PREFIX = {
        "GerBoLut": "GerBoLut",
        "KJV": "KJV",
        "web": "NHEB",
    }
    prefix = TABLE_PREFIX.get(collection_name, collection_name)
    table = f"{prefix}_verses"

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(f"SELECT book_id, chapter, verse, text FROM {table} ORDER BY book_id, chapter, verse")
    rows = cur.fetchall()
    conn.close()
    return [{"b": r[0], "c": r[1], "v": r[2], "t": r[3].strip()} for r in rows]


def build_document(book_name: str, chapter: int, verse: int, text: str) -> str:
    return f"{book_name} {chapter}:{verse} — {text}"


def index_translation(
    collection_name: str,
    db_path: Path,
    use_german_names: bool,
    chroma_client: chromadb.PersistentClient,
    model: SentenceTransformer,
    force: bool,
    limit: int | None = None,
) -> None:
    existing = [c.name for c in chroma_client.list_collections()]
    if collection_name in existing:
        if force:
            print(f"[{collection_name}] Force flag set — deleting existing collection.")
            chroma_client.delete_collection(collection_name)
        else:
            print(f"[{collection_name}] Already indexed. Use --force to re-index. Skipping.")
            return

    if not db_path.exists():
        print(f"[{collection_name}] SQLite file not found: {db_path}. Skipping.", file=sys.stderr)
        return

    collection = chroma_client.create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
        embedding_function=None,
    )

    verses = load_verses(db_path, collection_name)
    if limit is not None:
        verses = verses[:limit]
    total = len(verses)
    print(f"[{collection_name}] {total} verses loaded. Starting embedding...")

    for batch_start in range(0, total, BATCH_SIZE):
        batch = verses[batch_start : batch_start + BATCH_SIZE]

        ids = []
        documents = []
        metadatas = []

        for v in batch:
            b, c, verse_num, text = v["b"], v["c"], v["v"], v["t"]
            book_en = BOOK_NAMES_EN[b] if b < len(BOOK_NAMES_EN) else f"Book{b}"
            book_de = BOOK_NAMES_DE[b] if b < len(BOOK_NAMES_DE) else f"Buch{b}"
            book_name = book_de if use_german_names else book_en

            doc = build_document(book_name, c, verse_num, text)
            doc_id = f"{collection_name}_{b}_{c}_{verse_num}"

            ids.append(doc_id)
            documents.append(doc)
            metadatas.append({
                "book": book_name,
                "book_en": book_en,
                "book_number": b,
                "chapter": c,
                "verse": verse_num,
                "translation": collection_name,
                "testament": get_testament(b),
            })

        # E5 models use "passage: " prefix for documents at index time
        passages = [f"passage: {doc}" for doc in documents]
        embeddings = model.encode(passages, batch_size=BATCH_SIZE, normalize_embeddings=True).tolist()
        collection.add(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)

        done = min(batch_start + BATCH_SIZE, total)
        print(f"[{collection_name}] {done}/{total} verses indexed")

    print(f"[{collection_name}] Done.")


def main():
    parser = argparse.ArgumentParser(description="Index Bible translations into ChromaDB.")
    parser.add_argument("--force", action="store_true", help="Re-index even if collection already exists.")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap verses per translation (for CI smoke tests). Omit for full index.",
    )
    args = parser.parse_args()

    # Default: ../bible_databases/formats/sqlite relative to the package root
    package_root = Path(__file__).parent.parent
    bible_db_path = os.environ.get(
        "BIBLE_DB_PATH",
        str(package_root.parent / "bible_databases" / "formats" / "sqlite"),
    )

    chroma_path = os.environ.get("CHROMA_PATH", "./bible_chroma_db")

    bible_db_dir = Path(bible_db_path)
    chroma_dir = Path(chroma_path)
    chroma_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading embedding model '{MODEL_NAME}' ...")
    model = SentenceTransformer(MODEL_NAME)

    chroma_client = chromadb.PersistentClient(path=str(chroma_dir))

    for collection_name, sqlite_filename, use_german_names in TRANSLATIONS:
        db_path = bible_db_dir / sqlite_filename
        index_translation(
            collection_name=collection_name,
            db_path=db_path,
            use_german_names=use_german_names,
            chroma_client=chroma_client,
            model=model,
            force=args.force,
            limit=args.limit,
        )

    print("\nAll done. ChromaDB is at:", chroma_dir.resolve())
