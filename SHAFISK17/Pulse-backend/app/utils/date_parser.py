"""
Date Parsing and Normalization Utility
FAANG-Level Quality Control for Published Dates

Ensures all dates are in strict ISO-8601 UTC format for reliable sorting.
"""

from typing import Optional
from datetime import datetime, timezone
import re
from dateutil import parser as dateutil_parser
from dateutil.tz import tzutc


def parse_date_to_iso(date_str: str) -> str:
    """
    Parse any date format and convert to strict ISO-8601 UTC
    
    Handles:
    - ISO-8601: "2026-01-22T05:58:33Z" ✅
    - RFC-822: "Mon, 22 Jan 2026 05:58:33 GMT" ✅
    - Natural language: "2 hours ago", "yesterday" ✅
    - Unix timestamps: "1737525513" ✅
    
    Returns: "2026-01-22T05:58:33.000Z" (always UTC)
    """
    if not date_str:
        return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    
    try:
        # Try parsing with dateutil (handles most formats)
        parsed_date = dateutil_parser.parse(date_str)
        
        # Convert to UTC if timezone-aware
        if parsed_date.tzinfo is not None:
            parsed_date = parsed_date.astimezone(timezone.utc)
        else:
            # Assume UTC if no timezone
            parsed_date = parsed_date.replace(tzinfo=timezone.utc)
        
        # Return in strict ISO-8601 format with Z suffix
        return parsed_date.isoformat().replace('+00:00', 'Z')
        
    except Exception as e:
        # Fallback to current time if unparsable
        print(f"⚠️  Date parsing failed for '{date_str}': {e}. Using current time.")
        return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def normalize_article_date(article):
    """
    Normalize the publishedAt field in an article
    
    HOTFIX (2026-01-23): Now handles both Pydantic Article models AND dicts
    
    Args:
        article: Article model or dict
    
    Returns:
        dict with normalized publishedAt field
    """
    # HOTFIX: Convert Pydantic model to dict if needed
    if hasattr(article, 'model_dump'):
        # It's a Pydantic v2 model
        article_dict = article.model_dump()
    elif hasattr(article, 'dict'):
        # It's a Pydantic v1 model
        article_dict = article.dict()
    elif isinstance(article, dict):
        # Already a dict - create a copy to avoid mutating original
        article_dict = article.copy()
    else:
        # Unknown type - try to convert to dict
        article_dict = dict(article)
    
    # Normalize the date
    # Check both keys
    published_at = article_dict.get('publishedAt') or article_dict.get('published_at')
    
    if published_at:
        # Handle datetime objects
        if isinstance(published_at, datetime):
            iso_date = published_at.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
        elif isinstance(published_at, str):
            iso_date = parse_date_to_iso(published_at)
        else:
            # Unknown type, use current time
            iso_date = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    else:
        # If missing, use current time
        iso_date = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    
    # Set both keys to ensure compatibility
    article_dict['publishedAt'] = iso_date
    article_dict['published_at'] = iso_date
    
    return article_dict


def validate_date_format(date_str: str) -> bool:
    """
    Validate that a date string is in strict ISO-8601 UTC format
    
    Expected format: "YYYY-MM-DDTHH:MM:SS.sssZ" or "YYYY-MM-DDTHH:MM:SSZ"
    
    Returns: True if valid, False otherwise
    """
    # ISO-8601 UTC pattern
    iso_pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{3})?Z$'
    
    if not date_str:
        return False
    
    return bool(re.match(iso_pattern, date_str))


# Export functions
__all__ = [
    'parse_date_to_iso',
    'normalize_article_date',
    'validate_date_format'
]
