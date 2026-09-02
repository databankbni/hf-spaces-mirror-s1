"""
Utility Functions for Segmento Pulse
Provides common helpers for text processing, HTML cleaning, and data transformation
"""

import re
from html import unescape


def strip_html_if_needed(text: str) -> str:
    """
    Intelligently strip HTML only if HTML tags are detected.
    
    This optimization avoids unnecessary regex processing when text is already clean.
    RSS feeds can return either plain text or HTML - we handle both efficiently.
    
    Args:
        text: Input text (may or may not contain HTML)
        
    Returns:
        Cleaned text without HTML tags or entities
        
    Examples:
        >>> strip_html_if_needed("Plain text")
        'Plain text'
        
        >>> strip_html_if_needed("<b>Bold</b> text")
        'Bold text'
        
        >>> strip_html_if_needed("AT&amp;T announces...")
        'AT&T announces...'
    """
    if not text:
        return ""
    
    # Quick check: does this text have HTML?
    # This avoids expensive regex on plain text
    if '<' not in text and '>' not in text and '&' not in text:
        return text.strip()  # Already clean!
    
    # HTML detected - perform full cleanup
    
    # Step 1: Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Step 2: Decode HTML entities (&amp; → &, &lt; → <, etc.)
    text = unescape(text)
    
    # Step 3: Clean excessive whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text


def detect_html(text: str) -> bool:
    """
    Quickly detect if text contains HTML markup.
    
    Args:
        text: Text to check
        
    Returns:
        True if HTML tags detected, False otherwise
    """
    if not text:
        return False
    
    return '<' in text or '>' in text


def truncate_text(text: str, max_length: int = 200, suffix: str = "...") -> str:
    """
    Safely truncate text to maximum length.
    
    Args:
        text: Text to truncate
        max_length: Maximum length (default: 200)
        suffix: Suffix to add if truncated (default: "...")
        
    Returns:
        Truncated text
    """
    if not text or len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)].strip() + suffix


def normalize_url(url: str) -> str:
    """
    Normalize URL for deduplication.
    
    - Converts to lowercase
    - Removes trailing slashes
    - Strips whitespace
    
    Args:
        url: URL to normalize
        
    Returns:
        Normalized URL
    """
    if not url:
        return ""
    
    return url.strip().rstrip('/').lower()


def extract_domain(url: str) -> str:
    """
    Extract domain from URL.
    
    Args:
        url: Full URL
        
    Returns:
        Domain name (e.g., "techcrunch.com")
    """
    import re
    
    # Remove protocol
    domain = re.sub(r'^https?://', '', url)
    
    # Remove path
    domain = domain.split('/')[0]
    
    # Remove www.
    domain = domain.replace('www.', '')
    
    return domain.lower()


def comma_separated_to_list(text: str) -> list:
    """
    Convert comma-separated string to list.
    
    Args:
        text: Comma-separated string (e.g., "AI,Tech,Cloud")
        
    Returns:
        List of strings (e.g., ["AI", "Tech", "Cloud"])
    """
    if not text:
        return []
    
    return [item.strip() for item in text.split(',') if item.strip()]


def list_to_comma_separated(items: list) -> str:
    """
    Convert list to comma-separated string.
    
    Args:
        items: List of strings
        
    Returns:
        Comma-separated string
    """
    if not items:
        return ""
    
    return ",".join(str(item).strip() for item in items if item)
