import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class PublishTarget(ABC):
    """Base class for all publish targets (Blogger, WordPress, Medium, etc.)."""

    @abstractmethod
    async def authenticate(self) -> bool:
        """Authenticate with the target platform. Returns True on success."""

    @abstractmethod
    async def publish(self, article: Dict[str, Any]) -> Optional[str]:
        """Publish an article. Returns the URL or ID of the published post, or None on failure."""

    @abstractmethod
    async def test_connection(self) -> bool:
        """Test if the target is reachable and credentials work."""

    @abstractmethod
    def is_configured(self) -> bool:
        """Check if the target has all required configuration."""

    @abstractmethod
    async def get_post_url(self, post_id: str) -> Optional[str]:
        """Get the full URL of a published post by its ID."""

    @abstractmethod
    async def update_post(self, post_id: str, article: Dict[str, Any]) -> bool:
        """Update an existing post."""
