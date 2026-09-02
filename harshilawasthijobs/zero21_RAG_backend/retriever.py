# retriever.py - REWRITTEN FOR PINECONE

import os
import asyncio
import logging
import threading
from pinecone import Pinecone
from typing import Optional, Tuple, List, Dict, Any

# FIX: Corrected config import names
from config import PINECONE_API_KEY, PINECONE_ENVIRONMENT, AGENT_CONFIG, VECTOR_INDEX_NAME
from embeddings import embed_documents

# --- Global Cache for Pinecone Connection and Index ---
# FIX: Corrected variable names
_PINECONE_CLIENT = None
_PINECONE_INDEX = None 
_PINECONE_LOCK = threading.Lock() # NEW: Thread-safe lock
logger = logging.getLogger(__name__) # NEW: Logger

def _get_pinecone_index(agent_name: str):
    """
    Initializes and returns a cached Pinecone Index object for runtime queries
    in a thread-safe way.
    """
    # FIX: Corrected global variable names
    global _PINECONE_CLIENT, _PINECONE_INDEX

    # First check without lock for performance
    if _PINECONE_INDEX is not None:
        return _PINECONE_INDEX

    # FIX: Corrected env var check
    if not PINECONE_API_KEY or not PINECONE_ENVIRONMENT:
        logger.warning("Pinecone API key or Environment not configured. Retrieval skipped.")
        return None

    # If not loaded, acquire lock
    with _PINECONE_LOCK:
        # Double-check inside lock
        if _PINECONE_CLIENT is None:
            try:
                logger.info("Initializing Pinecone client...")
                # FIX: Corrected variable assignment
                _PINECONE_CLIENT = Pinecone(api_key=PINECONE_API_KEY, environment=PINECONE_ENVIRONMENT)
                _PINECONE_INDEX = _PINECONE_CLIENT.Index(VECTOR_INDEX_NAME)
                logger.info("Pinecone client and index initialized successfully.")
            except Exception as e:
                logger.error(f"Error initializing Pinecone client/index: {e}", exc_info=True)
                # Ensure we don't retry on failed init
                _PINECONE_CLIENT = None
                _PINECONE_INDEX = None
                return None
    
    return _PINECONE_INDEX

async def retrieve(
    query: str, agent_name: str, k: int = 5
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Asynchronously retrieves the top-k most relevant documents from Pinecone.
    """
    index = _get_pinecone_index(agent_name)
    if index is None:
        logger.warning("Pinecone index is not available. Skipping retrieval.")
        return [], None
    
    # This .get() is now safe because "IDEA VALIDATOR" is in AGENT_CONFIG
    agent_config = AGENT_CONFIG.get(agent_name.upper())
    
    # FIX: Add a check here to prevent the 'NoneType' error if a role is still not found
    if agent_config is None:
        logger.warning(
            f"Agent config not found for '{agent_name}'. Using default namespace.",
            extra={"agent_name": agent_name}
        )
        namespace = "default" # Or skip retrieval
        # As a fallback, let's skip retrieval if config is missing
        return [], None
    
    namespace = agent_config.get("namespace", "default") # Use .get() for safety

    # 1. Get the query embedding
    logger.debug("Generating query embedding for retrieval.")
    query_embedding_list = (await embed_documents([query]))[0]

    # 2. Query Pinecone (blocking call wrapped in to_thread)
    logger.debug(
        "Querying Pinecone index.", 
        extra={"namespace": namespace, "top_k": k}
    )
    try:
        results = await asyncio.to_thread(
            index.query,
            vector=query_embedding_list,
            top_k=k,
            namespace=namespace, # Use the correct namespace
            include_metadata=True,
            include_values=False
        )
    except Exception as e:
        logger.error(f"Error querying Pinecone index: {e}", exc_info=True)
        return [], None

    items = []
    digest_lines = []

    for match in results.get("matches", []):
        score = match.get("score", 0.0)
        metadata = match.get("metadata", {})
        
        # Retrieve the full text chunk from the metadata
        document_text = metadata.get("document_text", "Document text not found in metadata.")

        items.append({
            "id": match.get("id"), 
            "preview": document_text,
            "metadata": metadata, 
            "score": score
        })
        
        digest_lines.append(
            f"- Snippet from {metadata.get('source_file', 'N/A')}: "
            f"{document_text[:240].replace('/n', ' ')} (score={score:.4f})"
        )

    digest = "\n".join(digest_lines) if items else None
    
    logger.info(
        f"Retrieval complete. Found {len(items)} matching documents.",
        extra={"matches": len(items)}
    )

    return items, digest