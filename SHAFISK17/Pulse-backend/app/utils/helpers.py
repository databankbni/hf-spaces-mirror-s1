"""Helper utilities"""

import hashlib
from datetime import datetime
from typing import Optional

def generate_id(text: str) -> str:
    """Generate unique ID from text"""
    return hashlib.md5(text.encode()).hexdigest()

def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe storage"""
    return "".join(c for c in filename if c.isalnum() or c in (' ', '.', '_')).rstrip()

def format_datetime(dt: Optional[datetime] = None) -> str:
    """Format datetime to ISO string"""
    if dt is None:
        dt = datetime.now()
    return dt.isoformat()

def truncate_text(text: str, max_length: int = 200) -> str:
    """Truncate text to max length"""
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."

import re

def strip_html_if_needed(text: str) -> str:
    """
    Remove HTML tags from text if present.
    
    Args:
        text: Input text that might contain HTML
        
    Returns:
        Clean text without HTML tags
    """
    if not text or not isinstance(text, str):
        return ""
    
    # Check if looks like HTML (contains < and >)
    if '<' in text and '>' in text:
        # Simple regex to strip tags
        clean = re.compile('<.*?>')
        return re.sub(clean, '', text)
    
    return text
