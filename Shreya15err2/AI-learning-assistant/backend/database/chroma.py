import hashlib
import re
import chromadb
from chromadb.config import Settings
from typing import List, Optional, Dict, Any
from utils.config import CHROMA_DIR, CHROMA_COLLECTION
from services.embedding_service import embed_texts, embed_query

_client = None
_collection = None

def get_client() -> chromadb.Client:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=str(CHROMA_DIR),
            settings=Settings(anonymized_telemetry=False)
        )
    return _client

def get_collection():
    global _collection
    if _collection is None:
        client = get_client()
        _collection = client.get_or_create_collection(
            name=CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"}
        )
    return _collection

def store_document(document_id: str, filename: str, chunks: List[str]) -> int:
    """
    Store text chunks in ChromaDB.
    Generates MD5 hash-based IDs for deduplication.
    """
    collection = get_collection()
    
    unique_chunks = []
    unique_ids = []
    unique_metas = []
    seen_hashes = set()
    
    for i, chunk in enumerate(chunks):
        # Deduplicate within the current upload
        h = hashlib.md5(chunk.encode("utf-8")).hexdigest()
        if h in seen_hashes:
            continue
        seen_hashes.add(h)
        
        # Try to find page number: e.g. "[Page 3]"
        page_match = re.findall(r"\[Page (\d+)\]", chunk)
        page_num = page_match[0] if page_match else "?"
        
        unique_chunks.append(chunk)
        unique_ids.append(f"{document_id}_{h}")
        unique_metas.append({
            "document_id": document_id,
            "filename": filename,
            "chunk_index": i,
            "page": page_num
        })
        
    if not unique_chunks:
        return 0
        
    embeddings = embed_texts(unique_chunks)
    
    collection.add(
        ids=unique_ids,
        documents=unique_chunks,
        embeddings=embeddings,
        metadatas=unique_metas
    )
    
    return len(unique_chunks)

def search_chunks(query: str, top_k: int = 5, document_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Search chunks matching query, with optional document filtering.
    """
    collection = get_collection()
    query_embedding = embed_query(query)
    
    where_filter = None
    if document_id:
        where_filter = {"document_id": document_id}
        
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=where_filter,
        include=["documents", "metadatas", "distances"]
    )
    
    chunks = []
    if results and results["documents"] and results["documents"][0]:
        for i, doc in enumerate(results["documents"][0]):
            distance = results["distances"][0][i] if results["distances"] else 1.0
            similarity = round(1 - distance, 4)
            metadata = results["metadatas"][0][i] if results["metadatas"] else {}
            chunks.append({
                "text": doc,
                "similarity": similarity,
                "page": metadata.get("page", "?"),
                "document_id": metadata.get("document_id", "unknown"),
                "filename": metadata.get("filename", "unknown"),
                "chunk_index": metadata.get("chunk_index", 0)
            })
            
    chunks.sort(key=lambda x: x["similarity"], reverse=True)
    return chunks

def get_document_chunks(document_id: str) -> List[Dict[str, Any]]:
    """
    Fetch all chunks of a specific document, sorted by chunk_index.
    """
    collection = get_collection()
    results = collection.get(
        where={"document_id": document_id},
        include=["documents", "metadatas"]
    )
    
    chunks = []
    if results and results["documents"]:
        for i, doc in enumerate(results["documents"]):
            metadata = results["metadatas"][i] if results["metadatas"] else {}
            chunks.append({
                "text": doc,
                "page": metadata.get("page", "?"),
                "document_id": metadata.get("document_id", document_id),
                "filename": metadata.get("filename", "unknown"),
                "chunk_index": metadata.get("chunk_index", 0)
            })
            
    # Sort chunks in original reading order
    chunks.sort(key=lambda x: x["chunk_index"])
    return chunks

def delete_document(document_id: str):
    """
    Delete all chunks matching a document_id.
    """
    collection = get_collection()
    collection.delete(where={"document_id": document_id})

def list_documents() -> List[Dict[str, str]]:
    """
    List all unique documents stored in ChromaDB.
    """
    collection = get_collection()
    results = collection.get(include=["metadatas"])
    
    seen = {}
    if results and results["metadatas"]:
        for meta in results["metadatas"]:
            doc_id = meta.get("document_id")
            filename = meta.get("filename")
            if doc_id and doc_id not in seen:
                seen[doc_id] = {
                    "document_id": doc_id,
                    "filename": filename or "Unknown PDF"
                }
    return list(seen.values())
