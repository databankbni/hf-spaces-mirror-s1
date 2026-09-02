from pydantic import BaseModel, HttpUrl, field_validator, Field, ConfigDict
from typing import Optional, List
from datetime import datetime
from email.utils import parsedate_to_datetime

class Article(BaseModel):
    """News article model"""
    model_config = ConfigDict(populate_by_name=True)

    # --- CRITICAL FIX: All fields are Optional with safe defaults ---
    # Previously, 'title: str' and 'published_at: datetime' were strict.
    # A single null value from Appwrite would crash the ENTIRE request with
    # a 500, returning zero articles. Now the backend is forgiving.
    title: Optional[str] = "Untitled Article"
    id: Optional[str] = Field(None, alias="$id")  # Appwrite ID
    description: Optional[str] = ""
    url: Optional[str] = "#"
    image_url: Optional[str] = ""
    published_at: Optional[datetime] = None
    source: Optional[str] = ""
    category: Optional[str] = ""
    audio_url: Optional[str] = None
    text_summary: Optional[str] = None
    url_hash: Optional[str] = None
    author: Optional[str] = None

    # Engagement Stats (Side-loaded)
    likes: int = 0
    dislikes: int = Field(default=0, validation_alias="dislike")  # Alias for DB 'dislike'
    views: int = 0

    @field_validator('published_at', mode='before')
    @classmethod
    def parse_datetime(cls, v):
        """Parse datetime from various formats including RFC 2822 (RSS feeds)"""
        if v is None:
            return None
        if isinstance(v, datetime):
            return v
        if isinstance(v, str):
            try:
                # Try RFC 2822 format (used by RSS feeds like Google News)
                return parsedate_to_datetime(v)
            except:
                try:
                    # Try ISO format
                    return datetime.fromisoformat(v.replace('Z', '+00:00'))
                except:
                    try:
                        # Fallback to dateutil parser
                        from dateutil import parser
                        return parser.parse(v)
                    except:
                        # Last resort: return None (no crash)
                        return None
        return v

class NewsResponse(BaseModel):
    """Response model for news endpoints"""
    success: bool
    category: str
    count: int
    articles: List[Article]
    cached: bool = False
    source: Optional[str] = None  # "redis", "appwrite", "empty", or "api"
    message: Optional[str] = None  # User-friendly message for empty states

class SearchResponse(BaseModel):
    """Response model for search endpoints"""
    success: bool
    query: str
    count: int
    articles: List[Article]

class ViewCountRequest(BaseModel):
    """Request model for view count increment"""
    article_url: HttpUrl

class ViewCountResponse(BaseModel):
    """Response model for view count"""
    success: bool
    article_url: str
    view_count: int

class ErrorResponse(BaseModel):
    """Error response model"""
    success: bool = False
    error: str
    detail: Optional[str] = None

class Repo(BaseModel):
    """GitHub Repository model for Top Git Repositories category"""
    model_config = ConfigDict(populate_by_name=True)

    id: Optional[str] = Field(None, alias="$id")
    name: str
    owner: str
    description: Optional[str] = ""
    repo_url: str
    language: Optional[str] = ""
    stars: int
    forks: int
    last_synced_at: Optional[datetime] = None

    # Engagement Stats (Side-loaded)
    likes: int = 0
    dislikes: int = Field(default=0, validation_alias="dislike")  # Alias for DB 'dislike'
    views: int = 0

class ReposResponse(BaseModel):
    """Response model for top repositories endpoint"""
    success: bool
    count: int
    repos: List[Repo]
    cached: bool = False
    source: Optional[str] = None  # "redis", "appwrite", "api"
    message: Optional[str] = None

