import asyncio
import httpx
import random
import logging
from typing import List, Dict, Optional
from datetime import datetime
from app.models import Article
from app.services.rss_parser import RSSParser
from app.services.news_providers import (
    NewsProvider,
    GNewsProvider,
    NewsAPIProvider,
    NewsDataProvider,  # WARN-003 fixed: removed duplicate import
    GoogleNewsRSSProvider,
    MediumRSSProvider,
    OfficialCloudProvider
)
from app.config import settings
from app.services.api_quota import get_quota_tracker
from app.services.circuit_breaker import get_circuit_breaker
from app.utils.custom_logger import get_logger

# BUG-002 fixed: `random` and `logging` are now module-level imports.
# Previously they were lazy-imported inside fetch_by_category(), which fired
# 22 times per cycle and bypassed the AlignedColorFormatter logger.
logger = get_logger(__name__)

# ── Phases 3-11: New modular providers (Strangler Fig pattern) ──────────────
# These live in providers/ folder. The legacy news_providers.py is NOT touched.
# We import each new provider here and the aggregator runs both old and new
# providers side-by-side safely.
from app.services.providers.hackernews.client import HackerNewsProvider
from app.services.providers.direct_rss.client import DirectRSSProvider
from app.services.providers.thenewsapi.client import TheNewsAPIProvider
from app.services.providers.inshorts.client import InshortsProvider
from app.services.providers.sauravkanchan.client import SauravKanchanProvider
from app.services.providers.worldnewsai.client import WorldNewsAIProvider
from app.services.providers.openrss.client import OpenRSSProvider
from app.services.providers.webz.client import WebzProvider
from app.services.providers.wikinews.client import WikinewsProvider

class NewsAggregator:
    """Service for aggregating news from multiple sources with automatic failover"""
    
    def __init__(self):
        self.rss_parser = RSSParser()
        
        # Initialize all available providers
        self.providers: Dict[str, NewsProvider] = {}
        
        # Initialize GNews if API key is available
        if settings.GNEWS_API_KEY:
            self.providers['gnews'] = GNewsProvider(settings.GNEWS_API_KEY)
        
        # Initialize NewsAPI if API key is available
        if settings.NEWSAPI_API_KEY:
            self.providers['newsapi'] = NewsAPIProvider(settings.NEWSAPI_API_KEY)
        
        # Initialize NewsData if API key is available
        if settings.NEWSDATA_API_KEY:
            self.providers['newsdata'] = NewsDataProvider(settings.NEWSDATA_API_KEY)
        
        # Always include Google News RSS as fallback (no API key needed)
        # Always include Google News RSS as fallback (no API key needed)
        self.providers['google_rss'] = GoogleNewsRSSProvider()

        # Always include Medium RSS (no API key, specialized content)
        self.providers['medium'] = MediumRSSProvider()
        
        # Official Cloud Provider (Strict Isolation)
        self.providers['official_cloud'] = OfficialCloudProvider()

        # Direct RSS from premium tech publications (TechCrunch, Wired, The Verge,
        # Engadget, Ars Technica). Free, no key, great images and descriptions.
        # Runs for ALL categories — the keyword gate filters off-topic results.
        self.providers['direct_rss'] = DirectRSSProvider()

        # TheNewsAPI.com — Position 4 in the PAID_CHAIN (failover after the
        # existing 3 paid providers). 100 requests/day on the free tier.
        # Only registered when the API key is present in the environment.
        if settings.THENEWSAPI_API_KEY:
            self.providers['thenewsapi'] = TheNewsAPIProvider(
                api_key=settings.THENEWSAPI_API_KEY
            )

        # WorldNewsAI.com — Position 5 in the PAID_CHAIN (final paid failover).
        # Point-based quota, conservative daily_limit = 50 calls.
        # Gives global, non-US-centric news from tens of thousands of sources.
        # Only registered when the API key is present in the environment.
        if settings.WORLDNEWS_API_KEY:
            self.providers['worldnewsai'] = WorldNewsAIProvider(
                api_key=settings.WORLDNEWS_API_KEY
            )

        # OpenRSS.org — generates feeds for sites with no native RSS.
        # Free, no key. Has strict 60-minute internal cooldown to avoid IP ban.
        # Runs for ALL categories — no category guardrail needed.
        # The cooldown timer is the only protection this provider needs.
        self.providers['openrss'] = OpenRSSProvider()

        # Webz.io — Position 6 in the PAID_CHAIN (deepest paid failover).
        # Enterprise-grade crawl from 3.5M articles/day. Rich, global coverage.
        # 1,000 calls/month free tier — paced to 30/day = ~900/month (10% margin).
        # Only registered when the API key is present in the environment.
        if settings.WEBZ_API_KEY:
            self.providers['webz'] = WebzProvider(
                api_key=settings.WEBZ_API_KEY
            )

        # Wikinews — Public Domain, copyright-bulletproof tech news.
        # Free, no key. Searches 'Computing' and 'Internet' categories concurrently.
        # Gated behind GENERAL_TECH_CATEGORIES (broad tech content only).
        self.providers['wikinews'] = WikinewsProvider()
        
        # ── Provider role lists ──────────────────────────────────────────────
        # PAID_CHAIN: tried in order, stop after the first success (save credits)
        # FREE_SOURCES: always tried, always in parallel (no cost, no limits)
        self.PAID_CHAIN  = ['gnews', 'newsapi', 'newsdata', 'thenewsapi', 'worldnewsai', 'webz']
        # NOTE: 'inshorts' removed — 100% connection-reset failures on HF Spaces (geo-blocked).
        # NOTE: 'wikinews' removed — returns stale 2009-era political articles (0 keyword matches).
        self.FREE_SOURCES = ['google_rss', 'medium', 'official_cloud', 'direct_rss', 'hacker_news', 'saurav_static', 'openrss']

        # Medium only publishes articles for a small set of topics.
        # Calling it for 'data-centers' or 'cloud-oracle' would return nothing.
        self.MEDIUM_SUPPORTED_CATEGORIES = {
            'ai', 'data-science', 'cloud-computing', 'programming',
            'technology', 'data-laws'
        }

        # Official Cloud RSS only makes sense for cloud-related categories.
        self.CLOUD_CATEGORIES = {
            c for c in [
                'cloud-computing', 'cloud-aws', 'cloud-azure', 'cloud-gcp',
                'cloud-oracle', 'cloud-ibm', 'cloud-alibaba', 'cloud-digitalocean',
                'cloud-huawei', 'cloud-cloudflare'
            ]
        }

        # ── Phase 3: Hacker News Category Guardrail ──────────────────────────
        # Hacker News gives broad tech news — it does NOT know about "cloud-alibaba"
        # or "data-governance". Asking it for niche categories wastes CPU cycles
        # and risks polluting those collections with off-topic articles.
        # Only enable Hacker News for the broad categories below where it adds value.
        self.GENERAL_TECH_CATEGORIES = {
            'ai', 'magazines', 'data-engineering', 'cloud-computing',
            'data-security', 'business-intelligence'
        }

        # Register the Hacker News provider (free, no key needed).
        # It lives in providers/hackernews/client.py — completely isolated from
        # the legacy news_providers.py file.
        self.providers['hacker_news'] = HackerNewsProvider()

        # Inshorts — 60-word tech summaries. Free, no key, broad tech topics.
        # Gated behind GENERAL_TECH_CATEGORIES (same as Hacker News).
        self.providers['inshorts'] = InshortsProvider()

        # SauravKanchan static JSON — reads two GitHub Pages files (IN + US).
        # Zero cost, zero rate limits, NewsAPI-format data structure.
        # Gated behind GENERAL_TECH_CATEGORIES (broad tech news only).
        self.providers['saurav_static'] = SauravKanchanProvider()
        
        # Cloud provider RSS feeds
        self.cloud_rss_urls = {
            "aws": "https://aws.amazon.com/blogs/aws/feed/",
            "gcp": "https://cloudblog.withgoogle.com/rss/",
            "azure": "https://azure.microsoft.com/en-us/blog/feed/",
            "ibm": "https://www.ibm.com/blog/rss",
            "oracle": "https://blogs.oracle.com/cloud-infrastructure/rss",
            "digitalocean": "https://www.digitalocean.com/blog/rss.xml"
        }
        
        # Statistics tracking
        self.stats = {
            'total_requests': 0,
            'provider_usage': {},
            'failover_count': 0
        }

        # Async lock — keeps stats correct when 22 category tasks share this one aggregator.
        # Without this, two tasks updating the same counter at the same time could miss a count.
        self._lock = asyncio.Lock()

        # --- Phase 2 additions: infrastructure guards ---

        # Which providers cost real API credits.
        # Kept as a set for O(1) lookup inside the waterfall loop.
        self.paid_providers = set(self.PAID_CHAIN)

        # The Quota Tracker counts how many API calls we have made today.
        # It is a module-level singleton — once created it lives in memory for the
        # entire lifetime of the server process, surviving every hourly scheduler
        # run without resetting. (It DOES reset if the server itself restarts;
        # that is acceptable for now and noted as a future improvement.)
        self.quota = get_quota_tracker()

        # The Circuit Breaker watches each provider for repeated failures.
        # If a provider fails 3 times in 5 minutes, we stop calling it for 1 hour
        # (like hanging up on a broken phone line and trying it again later).
        # It is also a module-level singleton — same lifetime as the quota tracker.
        self.circuit = get_circuit_breaker()
    
    async def fetch_by_category(self, category: str) -> List[Article]:
        """
        Fetch news from ALL available sources for a category.

        Strategy (Phase 5 — True Multi-Source Aggregation):

          STEP A ─ Paid Waterfall:
            Try GNews → NewsAPI → NewsData in order.
            Stop as soon as one returns articles.
            We only want ONE paid call per category to stay inside our daily budget.
            Think of it like: only knock on the first open door, don't ring every bell.

          STEP B ─ Free Parallel Run (always runs, even if Step A succeeded):
            Simultaneously fetch from Google RSS, Medium, and Official Cloud.
            These are free and have no rate-limit cost, so we always want them.
            Think of it like: sending postcards to all your free newspaper subscriptions.

          STEP C ─ Combine:
            Merge paid + free results into one big list.
            Duplicates are fine here — the in-batch deduplication in scheduler.py
            will clean them up right after this function returns.
        """
        # ── Task 4: Worker Start-up Jitter ────────────────────────────────────
        # Before the worker begins fetching the actual URLs for a popped category,
        # inject a randomized sleep to break up predictable robotic execution patterns.
        # BUG-002 fixed: random and logger are now module-level — no lazy import needed here.
        startup_jitter = random.uniform(3.0, 8.0)
        logger.info("🎲 [JITTER] Worker start-up jitter: sleeping for %.2fs...", startup_jitter)
        await asyncio.sleep(startup_jitter)

        async with self._lock:
            self.stats['total_requests'] += 1

        combined_articles: List[Article] = []

        # ======================================================================
        # STEP A: PAID WATERFALL — one successful call is all we need
        # ======================================================================
        # BUG-001 fixed: replaced the inverted `paid_success` guard with an
        # attempt counter. The old code checked `if paid_success:` before
        # applying an intra-delay, but `paid_success` is False until a provider
        # succeeds — at which point `break` fires immediately. The delay was
        # therefore unreachable and NEVER executed. The correct check is
        # `if paid_attempts > 0:` — i.e. "have we already tried at least one
        # provider that failed?" — which fires on providers #2, #3 onwards.
        paid_success = False
        paid_attempts = 0  # BUG-001: counts actual attempt iterations
        for provider_name in self.PAID_CHAIN:
            provider = self.providers.get(provider_name)

            # Skip if this paid provider was not configured (no API key set).
            if not provider:
                continue

            # Guard 1 ─ Circuit Breaker
            if self.circuit.should_skip(provider_name):
                logger.debug("[CIRCUIT] [%s] Circuit OPEN — skipping this run.", provider_name.upper())
                async with self._lock:
                    self.stats['failover_count'] += 1
                continue

            # Guard 2 ─ Quota Check (paid only)
            if not await self.quota.async_can_make_call(provider_name):
                logger.warning("[QUOTA]   [%s] Daily limit reached — skipping.", provider_name.upper())
                continue

            # Guard 3 ─ Provider's own 429 flag
            if not provider.is_available():
                logger.warning("[SKIP]    [%s] Provider reported 429 — recording and skipping.", provider_name.upper())
                self.circuit.record_failure(provider_name, error_type="rate_limit", status_code=429)
                async with self._lock:
                    self.stats['failover_count'] += 1
                continue

            try:
                # ── Task 4: Intra-Category Rate Limiting (Sequential Chain) ───
                # BUG-001 fixed: delay fires on providers #2, #3 onwards (when
                # a previous provider was attempted but failed). Previously this
                # checked `paid_success` which is always False at this point.
                if paid_attempts > 0:
                    intra_delay = random.uniform(1.5, 3.5)
                    logger.debug("[PAID] Intra-chain delay: %.2fs before %s", intra_delay, provider_name)
                    await asyncio.sleep(intra_delay)

                logger.info("[PAID]    [%s] Fetching '%s'...", provider_name.upper(), category)
                paid_attempts += 1
                articles = await provider.fetch_news(category, limit=20)

                if articles:
                    self.circuit.record_success(provider_name)
                    await self.quota.async_record_call(provider_name)
                    async with self._lock:
                        self.stats['provider_usage'][provider_name] = \
                            self.stats['provider_usage'].get(provider_name, 0) + 1
                    combined_articles.extend(articles)
                    paid_success = True
                    logger.info("[PAID]    [%s] Got %d articles — stopping paid chain.", provider_name.upper(), len(articles))
                    break  # ← KEY: one success is enough, protect our credits
                else:
                    logger.info("[PAID]    [%s] No articles — trying next paid provider.", provider_name.upper())

            except Exception as e:
                logger.error("[PAID]    [%s] Fetch failed: %s — recording failure.", provider_name.upper(), e)
                self.circuit.record_failure(provider_name, error_type="exception")
                async with self._lock:
                    self.stats['failover_count'] += 1
                continue  # try next paid provider

        if not paid_success:
            logger.info("[PAID]    No paid provider delivered articles for '%s'.", category)

        # ======================================================================
        # STEP B: FREE PARALLEL RUN — always fires, no cost
        # ======================================================================
        # We build a list of coroutines for free sources, but only include a
        # provider if it actually supports this category (avoid pointless calls).
        free_tasks: list = []
        free_names: list = []  # track which name maps to which task result

        # Google RSS supports ALL categories.
        google_rss = self.providers.get('google_rss')
        if google_rss and not self.circuit.should_skip('google_rss'):
            if google_rss.is_available():
                free_tasks.append(google_rss.fetch_news(category, limit=20))
                free_names.append('google_rss')

        # Medium only supports a small set of topics.
        if category in self.MEDIUM_SUPPORTED_CATEGORIES:
            medium = self.providers.get('medium')
            if medium and not self.circuit.should_skip('medium'):
                if medium.is_available():
                    free_tasks.append(medium.fetch_news(category, limit=10))
                    free_names.append('medium')

        # Official Cloud RSS only makes sense for cloud-* categories.
        if category in self.CLOUD_CATEGORIES:
            official = self.providers.get('official_cloud')
            if official and not self.circuit.should_skip('official_cloud'):
                if official.is_available():
                    free_tasks.append(official.fetch_news(category, limit=10))
                    free_names.append('official_cloud')

        # ── Phase 3: Hacker News Guardrail ────────────────────────────────────
        # Only fire Hacker News when the category is a broad tech topic.
        # For niche categories (e.g., cloud-alibaba), we skip it entirely.
        if category in self.GENERAL_TECH_CATEGORIES:
            hn = self.providers.get('hacker_news')
            if hn and not self.circuit.should_skip('hacker_news'):
                if hn.is_available():
                    free_tasks.append(hn.fetch_news(category, limit=30))
                    free_names.append('hacker_news')

        # ── Phase 6: Inshorts Guardrail ─────────────────────────────────────
        # DISABLED: Inshorts — geo-blocked on HF Spaces (RemoteProtocolError on every call).
        # Provider is registered but NOT dispatched. Re-enable when/if hosting changes.
        # if category in self.GENERAL_TECH_CATEGORIES:
        #     inshorts = self.providers.get('inshorts')
        #     if inshorts and not self.circuit.should_skip('inshorts'):
        #         if inshorts.is_available():
        #             free_tasks.append(inshorts.fetch_news(category, limit=20))
        #             free_names.append('inshorts')

        # ── Phase 7: SauravKanchan Guardrail ─────────────────────────────────
        # Static JSON files (IN + US). Same guardrail as Hacker News and Inshorts.
        # Broad tech content only — niche categories get no value from these files.
        if category in self.GENERAL_TECH_CATEGORIES:
            saurav = self.providers.get('saurav_static')
            if saurav and not self.circuit.should_skip('saurav_static'):
                if saurav.is_available():
                    free_tasks.append(saurav.fetch_news(category, limit=50))
                    free_names.append('saurav_static')

        # DISABLED: Wikinews — returns stale political/social articles from 2009-2015.
        # Searching incategory:Computing and incategory:Internet returns zero relevant
        # tech news. All articles fail keyword validation (0 matches). Wastes ~22 HTTP
        # calls per category with no output. Re-evaluate if Wikinews improves recency.
        # if category in self.GENERAL_TECH_CATEGORIES:
        #     wikinews = self.providers.get('wikinews')
        #     if wikinews and not self.circuit.should_skip('wikinews'):
        #         if wikinews.is_available():
        #             free_tasks.append(wikinews.fetch_news(category, limit=20))
        #             free_names.append('wikinews')

        if free_tasks:
            # ── Task 4: Intra-Category Rate Limiting (Parallel Launch Jitter) ──
            # To prevent parallel tasks from hitting the same shared IP outbound
            # gate simultaneously, we wrap each task in a small jittered wrapper.
            async def _jittered_fetch(name, task):
                # Increased delay to avoid Hugging Face burst bans
                delay = random.uniform(1.0, 3.0)
                await asyncio.sleep(delay)
                return await task

            jittered_tasks = [
                _jittered_fetch(name, task)
                for name, task in zip(free_names, free_tasks)
            ]

            logger.info("[FREE]    Launching %d free source(s) in batches of 2 for '%s' to prevent OOM...",
                        len(free_tasks), category)
            free_results = []
            for i in range(0, len(jittered_tasks), 2):
                batch = jittered_tasks[i:i+2]
                # Slight extra jitter between batches to avoid HF bans
                if i > 0:
                    await asyncio.sleep(random.uniform(1.0, 2.0))
                batch_results = await asyncio.gather(*batch, return_exceptions=True)
                free_results.extend(batch_results)

            for name, result in zip(free_names, free_results):
                if isinstance(result, Exception):
                    logger.error("[FREE]    [%s] Free fetch error: %s", name.upper(), result)
                    self.circuit.record_failure(name, error_type="exception")
                elif isinstance(result, list) and result:
                    self.circuit.record_success(name)
                    combined_articles.extend(result)
                    logger.info("[FREE]    [%s] Got %d articles.", name.upper(), len(result))
                    async with self._lock:
                        self.stats['provider_usage'][name] = \
                            self.stats['provider_usage'].get(name, 0) + 1

        # ======================================================================
        # STEP C: RETURN COMBINED LIST
        # ======================================================================
        # Return everything we collected. Duplicates are expected and welcome —
        # the in-batch dedup in scheduler.py (Phase 1) will strip them cleanly.
        if combined_articles:
            logger.info("[DONE]    '%s': %d total articles from all sources.", category, len(combined_articles))
        else:
            logger.warning("[WARN]    '%s': No articles from any source this run.", category)

        return combined_articles

    async def fetch_from_provider(self, provider_name: str, category: str) -> List[Article]:
        """Fetch news specifically from a named provider (bypassing priority/failover)"""
        provider = self.providers.get(provider_name)
        if not provider or not provider.is_available():
            return []

        try:
            return await provider.fetch_news(category)
        except Exception as e:
            logger.error("[PROVIDER] [%s] Specific fetch error: %s", provider_name.upper(), e)
            return []
    
    async def fetch_rss(self, provider: str) -> List[Article]:
        """Fetch RSS from cloud providers"""
        url = self.cloud_rss_urls.get(provider)
        if not url:
            return []
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    content = response.text
                    return await self.rss_parser.parse_provider_rss(content, provider)
                return []
        except Exception as e:
            logger.error("[RSS] Error fetching RSS for %s: %s", provider, e)
            return []
    
    async def search(self, query: str) -> List[Article]:
        """
        Search news articles using hybrid approach
        Currently uses Google News RSS for search functionality
        """
        # Use Google News RSS for search
        google_rss = self.providers.get('google_rss')
        if google_rss:
            try:
                # Create a custom search URL
                search_url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
                
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(search_url)
                    if response.status_code == 200:
                        return await self.rss_parser.parse_google_news(response.text, "search")
            except Exception as e:
                logger.error("[SEARCH] Error searching news: %s", e)
        
        return []
    
    def get_stats(self) -> Dict:
        """Get usage statistics for monitoring"""
        return {
            **self.stats,
            'available_providers': [
                name for name, provider in self.providers.items() 
                if provider.is_available()
            ],
            'provider_status': {
                name: {
                    'status': provider.status.value,
                    'request_count': provider.request_count,
                    'daily_limit': provider.daily_limit
                }
                for name, provider in self.providers.items()
            }
        }
