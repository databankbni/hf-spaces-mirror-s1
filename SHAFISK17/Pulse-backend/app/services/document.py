"""
Custom Document Class - Replacing LlamaIndex Document

This provides the same value as LlamaIndex's Document object:
- Standardized data structure
- Metadata management
- Unique identification
- Easy serialization

No external dependencies required.
"""

import hashlib
from typing import Dict, Optional
from datetime import datetime


class Document:
    """
    Custom Document class that standardizes data structure
    
    Replaces LlamaIndex Document with same functionality:
    - text: The main content
    - metadata: URL, timestamp, category, source info
    - doc_id: Unique identifier for deduplication
    """
    
    def __init__(
        self,
        text: str,
        metadata: Optional[Dict] = None,
        doc_id: Optional[str] = None
    ):
        """
        Initialize a Document
        
        Args:
            text: The document content
            metadata: Dictionary of metadata (url, category, source, etc.)
            doc_id: Optional unique ID (auto-generated if not provided)
        """
        self.text = text
        self.metadata = metadata or {}
        self.doc_id = doc_id or self._generate_id()
    
    def _generate_id(self) -> str:
        """
        Generate unique document ID from URL or content hash
        
        Returns:
            Unique identifier string
        """
        # Use URL if available for stable ID
        if 'url' in self.metadata or 'link' in self.metadata:
            url = self.metadata.get('url') or self.metadata.get('link')
            return hashlib.md5(url.encode()).hexdigest()
        
        # Fall back to content hash
        content_hash = hashlib.md5(self.text[:500].encode()).hexdigest()
        return f"doc_{content_hash}"
    
    def to_dict(self) -> Dict:
        """
        Convert Document to dictionary for serialization
        
        Returns:
            Dictionary representation
        """
        return {
            'text': self.text,
            'metadata': self.metadata,
            'doc_id': self.doc_id
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Document':
        """
        Create Document from dictionary
        
        Args:
            data: Dictionary with text, metadata, doc_id
            
        Returns:
            Document instance
        """
        return cls(
            text=data.get('text', ''),
            metadata=data.get('metadata', {}),
            doc_id=data.get('doc_id')
        )
    
    def __repr__(self) -> str:
        """String representation for debugging"""
        preview = self.text[:50] + "..." if len(self.text) > 50 else self.text
        return f"Document(id={self.doc_id}, text='{preview}')"
    
    def __len__(self) -> int:
        """Return text length"""
        return len(self.text)


def create_document_from_rss_entry(
    entry: Dict,
    category: str,
    source_feed: str
) -> Document:
    """
    Helper function to create Document from RSS feed entry
    
    Args:
        entry: Dictionary from feedparser entry
        category: News category
        source_feed: RSS feed URL
        
    Returns:
        Document instance
    """
    # Extract text content
    text = entry.get('summary', '') or entry.get('description', '')
    
    # Build metadata
    metadata = {
        'title': entry.get('title', '')[:200],
        'url': entry.get('link', ''),
        'link': entry.get('link', ''),
        'published': entry.get('published', datetime.now().isoformat()),
        'source': entry.get('source', {}).get('title', 'Unknown'),
        'category': category,
        'source_feed': source_feed,
        'author': entry.get('author', ''),
    }
    
    # Create document
    return Document(text=text, metadata=metadata)
