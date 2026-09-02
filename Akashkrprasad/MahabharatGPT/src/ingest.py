"""
Ingest the Mahabharata source material into Pinecone.

Two kinds of sources are loaded:
  1. data/*_memories.txt  -> short, hand-written first-person memories
  2. Books/*.pdf          -> full reference novels / retellings

Everything goes into ONE shared pool. We do NOT hard-bind a book to a single
character (the books mention everyone). Instead each chunk keeps a `source`
tag, and retrieval at query time is biased by the character's name so their
passages rank highest while shared events stay reachable.
"""

import os
import glob
from dotenv import load_dotenv
from langchain_community.document_loaders import TextLoader, PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone, ServerlessSpec

load_dotenv()

ROOT = os.path.join(os.path.dirname(__file__), "..")
DATA_DIR = os.path.join(ROOT, "data")
BOOKS_DIR = os.path.join(ROOT, "Books")
INDEX_NAME = "mahabharata-characters"
EMBED_MODEL = "all-MiniLM-L6-v2"
BATCH_SIZE = 100


def get_index(pc):
    """Create the index if missing and wipe it for a clean re-ingest."""
    existing = [i.name for i in pc.list_indexes()]
    if INDEX_NAME not in existing:
        print(f"Creating index '{INDEX_NAME}'...")
        pc.create_index(
            name=INDEX_NAME,
            dimension=384,  # all-MiniLM-L6-v2
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
    index = pc.Index(INDEX_NAME)
    try:
        index.delete(delete_all=True)
        print("Cleared existing vectors for a fresh ingest.")
    except Exception:
        print("Index is empty (nothing to clear).")
    return index


def load_memory_docs(splitter):
    """Short hand-written memories. Tagged with the character from the filename."""
    docs = []
    for path in glob.glob(os.path.join(DATA_DIR, "*_memories.txt")):
        filename = os.path.basename(path)
        character = filename.split("_")[0].capitalize()
        raw = TextLoader(path, encoding="utf-8").load()
        if not raw or not raw[0].page_content.strip():
            continue
        for chunk in splitter.split_documents(raw):
            chunk.metadata.update(
                {"source": filename, "character_name": character, "type": "memory"}
            )
            docs.append(chunk)
    print(f"  memories: {len(docs)} chunks")
    return docs


def load_book_docs(splitter):
    """Full books. Shared pool: tagged only with their source filename."""
    docs = []
    pdfs = glob.glob(os.path.join(BOOKS_DIR, "*.pdf"))
    for path in pdfs:
        filename = os.path.basename(path)
        # A readable short title from the filename (text before the first ' -- ')
        title = filename.split(" -- ")[0].strip()
        try:
            pages = PyPDFLoader(path).load()
        except Exception as e:
            print(f"  ! skipped {title}: {e}")
            continue

        text = "".join(p.page_content for p in pages).strip()
        if len(text) < 200:
            # Almost certainly a scanned/image-only PDF with no extractable text
            print(f"  ! no text extracted from {title} (likely scanned) - skipped")
            continue

        chunks = splitter.split_documents(pages)
        for chunk in chunks:
            chunk.metadata.update(
                {"source": title, "type": "book"}
            )
        docs.extend(chunks)
        print(f"  + {title}: {len(chunks)} chunks")
    print(f"  books total: {len(docs)} chunks from {len(pdfs)} files")
    return docs


def ingest_data():
    if not os.getenv("PINECONE_API_KEY"):
        print("Error: PINECONE_API_KEY not found in .env")
        return

    pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
    get_index(pc)

    embeddings = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=120)

    print("Loading sources...")
    documents = load_memory_docs(splitter) + load_book_docs(splitter)

    if not documents:
        print("No documents found to ingest.")
        return

    print(f"Embedding and uploading {len(documents)} chunks (in batches of {BATCH_SIZE})...")
    store = PineconeVectorStore(index_name=INDEX_NAME, embedding=embeddings)
    for i in range(0, len(documents), BATCH_SIZE):
        batch = documents[i:i + BATCH_SIZE]
        store.add_documents(batch)
        print(f"  uploaded {min(i + BATCH_SIZE, len(documents))}/{len(documents)}")

    print("Ingestion complete.")


if __name__ == "__main__":
    ingest_data()
