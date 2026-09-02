# embeddings.py

import asyncio
import numpy as np
import logging
import threading
from sentence_transformers import SentenceTransformer
from config import EMBED_MODEL

# --- Global Cache for the Embedding Model ---
_EMBEDDING_MODEL = None
_EMBED_LOCK = threading.Lock() # NEW: Thread-safe lock
logger = logging.getLogger(__name__) # NEW: Logger

def get_embedding_model():
    """
    Loads and caches the SentenceTransformer model using a lazy loading pattern
    in a thread-safe way.
    """
    global _EMBEDDING_MODEL
    
    # First check without lock for performance
    if _EMBEDDING_MODEL is not None:
        return _EMBEDDING_MODEL

    # If not loaded, acquire lock
    with _EMBED_LOCK:
        # Double-check inside lock
        if _EMBEDDING_MODEL is None:
            try:
                logger.info(
                    "Loading sentence-transformer model...",
                    extra={"model_name": EMBED_MODEL}
                )
                _EMBEDDING_MODEL = SentenceTransformer(EMBED_MODEL)
                logger.info("Sentence-transformer model loaded successfully.")
            except ImportError:
                logger.error(
                    "sentence-transformers is not installed.", 
                    exc_info=True
                )
                raise RuntimeError("sentence-transformers is not installed.")
            except Exception as e:
                logger.error(
                    f"Failed to load embedding model '{EMBED_MODEL}': {e}",
                    exc_info=True
                )
                raise RuntimeError(f"Failed to load embedding model: {e}")
                
    return _EMBEDDING_MODEL

async def embed_documents(docs: list[str], batch_size: int = 32) -> list[list[float]]:
    """
    Asynchronously generates embeddings for a list of documents.
    """
    try:
        model = get_embedding_model()
    except RuntimeError as e:
        logger.error(f"Cannot embed documents: {e}", exc_info=True)
        return [[] for _ in docs] # Return empty embeddings on failure

    logger.debug(f"Embedding {len(docs)} documents...")
    # Run the CPU-bound encoding task in a separate thread to avoid blocking the event loop
    embeddings = await asyncio.to_thread(
        model.encode, docs, show_progress_bar=False, convert_to_numpy=True
    )
    logger.debug("Document embedding complete.")
    return [e.tolist() for e in embeddings]