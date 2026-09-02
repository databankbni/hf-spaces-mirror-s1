"""
Article ID Generation Utilities
================================

Generates Appwrite-compatible document IDs from URLs.

Issue: Base64-encoded URLs exceed Appwrite's 36-character limit
Solution: Use SHA-256 hash (32 characters)
"""

import hashlib
import uuid
from typing import Optional


def generate_article_id(url: str) -> str:
    """
    Generate Appwrite-compatible ID from URL

    **INTEGRATION FIX #2**: Matches frontend and appwrite_db.py

    Uses SHA-256 hash truncated to 32 characters to ensure
    it fits within Appwrite's 36-character document ID limit.

    [I5 — URL Canonicalization Fix]
    Canonicalize before hashing so UTM variants of the same URL
    produce the SAME ID. Before this fix, ?utm_source=rss and no
    params would generate different IDs for the same article.

    Args:
        url: Article URL

    Returns:
        32-character hex string (Appwrite-compatible)

    Example:
        >>> generate_article_id("https://example.com/article")
        "a1b2c3d4e5f67890abcdef1234567890"
    """
    from app.utils.url_canonicalization import canonicalize_url
    # Canonicalize first: strips UTM params, www, trailing slash, etc.
    canonical = canonicalize_url(url)
    # Generate SHA-256 hash from canonical URL
    hash_obj = hashlib.sha256(canonical.encode('utf-8'))
    # Return first 32 characters of hex digest
    # (full hex is 64 chars, we only need 32 for uniqueness)
    return hash_obj.hexdigest()[:32]


def generate_article_id_uuid(url: str) -> str:
    """
    Generate Appwrite-compatible UUID from URL
    
    Alternative method using UUID v5 (namespace-based).
    Returns 36-character UUID string.
    
    Args:
        url: Article URL
        
    Returns:
        36-character UUID string (with hyphens)
        
    Example:
        >>> generate_article_id_uuid("https://example.com/article")
        "550e8400-e29b-41d4-a716-446655440000"
    """
    # Use URL namespace for consistent generation
    namespace = uuid.NAMESPACE_URL
    return str(uuid.uuid5(namespace, url))





def validate_appwrite_id(doc_id: str) -> bool:
    """
    Validate that document ID meets Appwrite requirements
    
    Appwrite document ID rules:
    - Maximum 36 characters
    - Only: a-z, A-Z, 0-9, underscore, hyphen
    - Cannot start with underscore
    
    Args:
        doc_id: Document ID to validate
        
    Returns:
        True if valid, False otherwise
    """
    import re
    
    # Check length
    if len(doc_id) > 36:
        return False
    
    # Check characters (alphanumeric + underscore + hyphen)
    if not re.match(r'^[a-zA-Z0-9\-_]+$', doc_id):
        return False
    
    # Cannot start with underscore
    if doc_id.startswith('_'):
        return False
    
    return True


# Example usage:
if __name__ == "__main__":
    test_url = "https://news.google.com/rss/articles/CBMiqwFBVlY5NWNVeFBaRWR4TkRoalkxRllSWFYxYVVNNFVF"
    
    print("=" * 70)
    print("Article ID Generation Test")
    print("=" * 70)
    print(f"Input URL: {test_url}")
    print(f"URL Length: {len(test_url)} characters")
    print()
    
    # Method 1: SHA-256 (recommended)
    sha_id = generate_article_id(test_url)
    print(f"SHA-256 ID: {sha_id}")
    print(f"Length: {len(sha_id)} chars")
    print(f"Valid: {validate_appwrite_id(sha_id)}")
    print()
    
    # Method 2: UUID v5
    uuid_id = generate_article_id_uuid(test_url)
    print(f"UUID ID: {uuid_id}")
    print(f"Length: {len(uuid_id)} chars")
    print(f"Valid: {validate_appwrite_id(uuid_id)}")
    print()
    
    # Old method (base64) - BROKEN
    import base64
    base64_id = base64.b64encode(test_url.encode()).decode()
    print(f"Base64 ID (OLD): {base64_id}")
    print(f"Length: {len(base64_id)} chars ❌ TOO LONG")
    print(f"Valid: {validate_appwrite_id(base64_id)} ❌")
    print("=" * 70)
