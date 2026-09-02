# chunker.py

import tiktoken
import logging
import threading

# Global cache for the tokenizer encoding
_ENCODING = None
_ENCODING_LOCK = threading.Lock()
logger = logging.getLogger(__name__)

def get_encoding(name="cl100k_base"):
    """Loads and caches a tiktoken encoding in a thread-safe way."""
    global _ENCODING
    
    # First check without lock for performance
    if _ENCODING is not None:
        return _ENCODING
    
    # If not loaded, acquire lock
    with _ENCODING_LOCK:
        # Double-check inside lock
        if _ENCODING is None:
            try:
                logger.info("Initializing tiktoken encoding...", extra={"encoding_name": name})
                _ENCODING = tiktoken.get_encoding(name)
            except Exception:
                logger.warning(
                    "Tiktoken encoding not found. Falling back to character count.",
                    exc_info=True
                )
                _ENCODING = None # Explicitly set to None on failure
    return _ENCODING

def count_tokens(text: str) -> int:
    """Counts the number of tokens in a string."""
    enc = get_encoding()
    return len(enc.encode(text)) if enc else len(text) // 4

def smart_chunk(text: str, max_tokens=300, overlap_tokens=50) -> list[str]:
    """
    Splits text into token-bounded chunks with overlap.
    """
    words = text.split()
    chunks = []
    current_chunk = []
    current_tokens = 0

    for word in words:
        word_tokens = count_tokens(word + " ")
        if current_tokens + word_tokens > max_tokens:
            chunks.append(" ".join(current_chunk))
            # Create overlap by backtracking
            overlap_word_count = 0
            overlap_token_count = 0
            for w in reversed(current_chunk):
                overlap_token_count += count_tokens(w + " ")
                overlap_word_count += 1
                if overlap_token_count >= overlap_tokens:
                    break
            current_chunk = current_chunk[-overlap_word_count:]
            current_tokens = count_tokens(" ".join(current_chunk) + " ")
        
        current_chunk.append(word)
        current_tokens += word_tokens

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks