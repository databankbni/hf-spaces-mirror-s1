#─────────────────────────────────────────────────────────────────────────────
"""
The Foundation — every news provider in this system inherits from this file.

Think of this like a "job contract" for a news provider. Any class that wants
to act as a news provider MUST sign this contract by:
  1. Inheriting from the NewsProvider class below.
  2. Implementing the fetch_news() method with real logic.

If a class inherits from NewsProvider but does NOT implement fetch_news(),
Python will throw a TypeError at startup — which is exactly what we want.
It forces every developer to write proper fetching logic.

#── RULE: THE CATEGORY ROUTING CONTRACT ─────────────────────────────────────

Every Article produced by a provider MUST have a 'category' field.
The category value routes the article to the correct Appwrite collection.

Current routing rules (defined in appwrite_db.get_collection_id):
  "ai"             → AI collection
  "cloud-*"        → Cloud collection
  "data-*" / "business-*" / "customer-data-platform" → Data collection
  "magazines"      → Magazine collection
  "medium-article" → Medium collection
  ""  (empty)
  or any unknown   → DEFAULT 'News Articles' collection   ← SAFE FALLBACK

⚠️  IMPORTANT FOR ALL PROVIDER DEVELOPERS:
    If your provider fetches general tech news and cannot determine a specific
    category, set category = "magazines".
    If your provider truly cannot figure out a category, set category = "".
    The default collection will catch it safely.
    NEVER set category = None — that will cause a Pydantic validation error.
    NEVER invent a category string that is not in config.py CATEGORIES list.

#── HOW CLIENT-SIDE FILTERING WORKS ─────────────────────────────────────────

Many providers (Hacker News, RSS Feeds, static files) do NOT support
filtering by date or keyword in their API request. That is okay.

Do NOT try to add date filters in the URL if the API doesn't support them.
Our data_validation pipeline enforces all constraints AFTER the fetch:
  - Freshness gate: rejects articles older than midnight IST today
  - Keyword gate: rejects articles with no matching category keywords
  - Redis dedup: rejects URLs we have already saved in the last 48 hours

So your job in fetch_news() is simple: fetch as many articles as the
provider gives you, map them to Article objects, and return them.
The pipeline does the rest.
"""

# ── Imports ──────────────────────────────────────────────────────────────────
# Standard library
from abc import ABC, abstractmethod     # ABC = Abstract Base Class toolkit
from typing import List, Optional
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo           # Timezone handling (Python 3.9+ built-in)
from enum import Enum

# Third-party (all already in requirements.txt — no new installs needed)
import httpx                            # Async HTTP client for API calls

# Internal
from app.models import Article          # The standard Article shape every provider must return


# ── Provider Status ────────────────────────────────────────────────────────────

class ProviderStatus(Enum):
    """
    Represents the health of a provider at any given moment.

    ACTIVE       → Provider is working fine. Calls proceed normally.
    RATE_LIMITED → Provider hit its API limit. Calls are paused.
    ERROR        → Provider had a hard failure. Circuit breaker may kick in.
    """
    ACTIVE       = "active"
    RATE_LIMITED = "rate_limited"
    ERROR        = "error"


# ── Abstract Base Class ────────────────────────────────────────────────────────

class NewsProvider(ABC):
    """
    The contract that every news provider must follow.

    Subclass this, implement fetch_news(), and your provider
    is automatically compatible with the NewsAggregator, circuit breaker,
    quota tracker, and the full validation pipeline.

    Example of a minimal valid provider:

        from app.services.providers.base import NewsProvider, ProviderStatus
        from app.models import Article
        from typing import List

        class MyProvider(NewsProvider):
            async def fetch_news(self, category: str, limit: int = 20) -> List[Article]:
                # 1. Call your API / RSS feed
                # 2. Map the response to Article objects
                # 3. Return the list (can be empty if nothing found)
                return []
    """

    def __init__(self, api_key: Optional[str] = None):
        # The API key for paid providers. Free providers leave this as None.
        self.api_key = api_key

        # Starts as ACTIVE. The aggregator or circuit breaker may change this.
        self.status = ProviderStatus.ACTIVE

        # Tracks how many API calls this provider has made today.
        self.request_count: int = 0

        # Maximum calls per day. 0 = no limit (used by free providers).
        self.daily_limit: int = 0

        # The name of this provider. Used in logging and circuit breaker tracking.
        # Automatically takes the class name (e.g., "HackerNewsProvider").
        self.name: str = self.__class__.__name__

        # ── Task 4: Adaptive Rate Limiting ──
        self.retry_after: float = 0.0  # Timestamp until which the provider is blocked
        self.backoff_count: int = 0    # Number of consecutive 429s (Too Many Requests)

    @abstractmethod
    async def fetch_news(self, category: str, limit: int = 20) -> List[Article]:
        """
        REQUIRED: Fetch news articles for the given category.

        Args:
            category (str): The internal Segmento Pulse category name.
                            Example: "ai", "cloud-aws", "magazines"
            limit (int):    Maximum number of articles to return.
                            This is a guideline — providers may return fewer.

        Returns:
            List[Article]: A list of Article objects. Return [] on failure.
                           Never raise an unhandled exception from here.
                           Wrap all network calls in try/except.

        Remember the ROUTING RULE at the top of this file:
            Every Article MUST have a category string.
            Use "magazines" for general tech. Use "" for truly unknown.
        """
        pass

    # ── Utility Methods (inherited by all providers, no need to override) ──────

    def is_available(self) -> bool:
        """
        Check if this provider is ready to accept a fetch request.

        Returns False if:
          - It is currently rate-limited or in an error state.
          - It is waiting out a 429 exponential backoff.
          - It has used up its daily API call limit.
        """
        import time
        if time.time() < self.retry_after:
            return False

        return (
            self.status == ProviderStatus.ACTIVE
            and (self.daily_limit == 0 or self.request_count < self.daily_limit)
        )

    def handle_429(self):
        """
        Task 4: Implement exponential backoff for 429 (Too Many Requests).
        Instead of a generic 1-hour block, we pause for 30s, then 60s, then 120s...
        This allows the system to recover 'politely' if it was hitting an accidental
        rate limit spike, while still protecting our IP reputation.
        """
        import time
        self.backoff_count += 1
        
        # Exponential Backoff Formula: 30 * (2 ^ (n-1))
        # n=1 -> 30s
        # n=2 -> 60s
        # n=3 -> 120s
        # n=4 -> 240s
        # Capped at 3600s (1 hour) to ensure we eventually try again.
        wait_time = min(30 * (2 ** (self.backoff_count - 1)), 3600)
        
        self.retry_after = time.time() + wait_time
        self.status = ProviderStatus.RATE_LIMITED
        print(f"⚠️  [BACKOFF] {self.name} hit 429. Backoff count: {self.backoff_count}. Sleeping for {wait_time}s.")

    def mark_rate_limited(self):
        """
        Call this when the API returns a 429 (Too Many Requests).
        The status changes to RATE_LIMITED so the aggregator knows to skip it.
        """
        self.status = ProviderStatus.RATE_LIMITED

    def reset_daily_quota(self):
        """
        Reset this provider's call counter back to zero.
        Called once per day (midnight UTC) by the scheduler to restore access.
        """
        self.request_count = 0
        self.status = ProviderStatus.ACTIVE
