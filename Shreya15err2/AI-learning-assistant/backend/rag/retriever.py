from database.chroma import search_chunks, get_document_chunks
from typing import List, Optional

def retrieve_chunks(
    query: str,
    top_k: int = 5,
    document_id: Optional[str] = None
) -> List[dict]:
    """
    Retrieve top K most similar chunks for a query.
    """
    return search_chunks(query=query, top_k=top_k, document_id=document_id)

def retrieve_all_document_chunks(document_id: str) -> List[dict]:
    """
    Retrieve all chunks belonging to a document, in reading order.
    """
    return get_document_chunks(document_id=document_id)

def build_context(chunks: List[dict], max_chars: int = 3000) -> str:
    """
    Concatenate chunks with page/file details into a single context string.
    """
    context_parts = []
    total_chars = 0
    for chunk in chunks:
        text = chunk["text"]
        if total_chars + len(text) > max_chars:
            break
        source = f"[Source: {chunk['filename']}, Page {chunk['page']}]"
        context_parts.append(f"{source}\n{text}")
        total_chars += len(text)
    return "\n\n---\n\n".join(context_parts)
