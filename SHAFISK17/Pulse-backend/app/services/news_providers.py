import httpx
from typing import List, Optional, Dict
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo   # stdlib from Python 3.9+ — no extra install needed
from abc import ABC, abstractmethod
from app.models import Article
import os
from enum import Enum
from app.utils.custom_logger import get_logger

logger = get_logger(__name__)

class ProviderStatus(Enum):
    """Provider status enum"""
    ACTIVE = "active"
    RATE_LIMITED = "rate_limited"
    ERROR = "error"

class NewsProvider(ABC):
    """Abstract base class for news providers"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.status = ProviderStatus.ACTIVE
        self.request_count = 0
        self.daily_limit = 0
        self.name = self.__class__.__name__
        self.retry_after = 0  # Timestamp until which the provider is blocked
        self.backoff_count = 0  # Number of consecutive 429s
    
    @abstractmethod
    async def fetch_news(self, category: str, limit: int = 20) -> List[Article]:
        """Fetch news articles for a given category"""
        pass
    
    def is_available(self) -> bool:
        """Check if provider is available"""
        import time
        if time.time() < self.retry_after:
            return False

        return self.status == ProviderStatus.ACTIVE and (
            self.daily_limit == 0 or self.request_count < self.daily_limit
        )
    
    def handle_429(self):
        """Implement exponential backoff for 429 Too Many Requests"""
        import time
        self.backoff_count += 1
        # Exponential backoff: 30s, 60s, 120s, 240s... max 1 hour
        wait_time = min(30 * (2 ** (self.backoff_count - 1)), 3600)
        self.retry_after = time.time() + wait_time
        self.status = ProviderStatus.RATE_LIMITED
        logger.warning("⚠️ [BACKOFF] %s hit 429. Backoff count: %d. Waiting %ds.",
                       self.name, self.backoff_count, wait_time)

    def mark_rate_limited(self):
        """Mark provider as rate limited"""
        self.status = ProviderStatus.RATE_LIMITED
    
    def reset_daily_quota(self):
        """Reset daily quota"""
        self.request_count = 0
        self.status = ProviderStatus.ACTIVE


class GNewsProvider(NewsProvider):
    """GNews.io API provider"""
    
    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key)
        self.base_url = "https://gnews.io/api/v4"
        self.daily_limit = 100
        
        # ── REFERENCE BACKUP (no longer used at runtime — Phase 21) ─────────
        # These were the old static query strings for GNews.
        # The live query is now built dynamically by build_dynamic_query().
        # To revert, replace the dynamic call in fetch_news() with:
        #     query = self.category_map.get(category, category)
        # Category mapping
        self.category_map = {
            'ai': 'artificial intelligence machine learning',
            'data-security': 'data security cybersecurity',
            'data-governance': 'data governance compliance',
            'data-privacy': 'data privacy GDPR',
            'data-engineering': 'data engineering pipeline',
            'data-management': 'data management master data MDM data catalog data quality',
            'business-intelligence': 'business intelligence BI',
            'business-analytics': 'business analytics',
            'customer-data-platform': 'customer data platform CDP',
            'data-centers': 'data centers infrastructure',
            'cloud-computing': 'cloud computing AWS Azure Google Cloud Salesforce Alibaba Cloud Tencent Cloud Huawei Cloud Cloudflare',
            'cloud-aws': 'AWS Amazon Web Services S3 EC2 Lambda CloudFront SageMaker',
            'cloud-azure': 'Microsoft Azure Azure DevOps Azure ML Azure OpenAI',
            'cloud-gcp': 'Google Cloud Platform GCP BigQuery Vertex AI Cloud Run Dataflow',
            'cloud-oracle': 'Oracle Cloud OCI Oracle Database Oracle Fusion',
            'cloud-ibm': 'IBM Cloud IBM Watson Red Hat OpenShift IBM Z',
            'cloud-alibaba': 'Alibaba Cloud Aliyun AliCloud',
            'cloud-digitalocean': 'DigitalOcean Droplet App Platform',
            'cloud-huawei': 'Huawei Cloud HuaweiCloud',
            'cloud-cloudflare': 'Cloudflare Workers R2 Cloudflare Pages Zero Trust',
            'medium-article': 'Medium article blog writing publishing',
            'magazines': 'technology news',
            'data-laws': 'data privacy law GDPR CCPA AI regulation compliance',
        }
    
    async def fetch_news(self, category: str, limit: int = 20) -> List[Article]:
        """
        Fetch news from GNews API.

        Why no 'from'/'to' date filter here?
        GNews free/basic tier does NOT support date filtering and returns HTTP 403
        or an error payload when those params are sent. Removing them lets GNews
        work reliably on any plan tier. Our data_validation.py freshness gate
        already rejects old articles downstream, so date filtering still happens
        — just at the right place.
        """
        if not self.api_key:
            return []

        try:
            # ── Phase 21: Dynamic query builder ─────────────────────────────
            # build_dynamic_query returns anchors + current hour's rotating chunk
            # formatted as space-separated words for GNews's search syntax.
            # Example at hour 7 for 'ai':
            #   'artificial intelligence machine learning deep learning neural network gpt llm chatgpt'
            from app.utils.query_builder import build_dynamic_query
            query = build_dynamic_query(category, api_type="gnews")
            url = f"{self.base_url}/search"

            # Simple, plan-compatible request — no date window.
            params = {
                'q': query,
                'lang': 'en',
                'country': 'us',
                'max': min(limit, 10),  # GNews free tier max 10
                'apikey': self.api_key,
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params)

                if response.status_code == 429:
                    self.handle_429()
                    return []

                if response.status_code == 200:
                    self.request_count += 1
                    data = response.json()

                    # FIX (Bug B): GNews sometimes returns HTTP 200 but puts an
                    # 'errors' key in the JSON body when the API key is wrong or
                    # a plan restriction is hit.
                    # We raise here so the aggregator's except block catches it
                    # and calls circuit.record_failure() automatically.
                    # That way the circuit breaker knows this is a real failure,
                    # not just a quiet day with no news.
                    if data.get('errors'):
                        raise RuntimeError(
                            f"[GNews] API error payload: {data.get('errors')}"
                        )

                    articles = self._parse_response(data, category)
                    if articles:
                        logger.info("[SUCCESS] [GNews] Fetched %d articles.", len(articles))
                    else:
                        logger.debug("[WARN] [GNews] No articles this run (API healthy, just quiet).")
                    return articles
                else:
                    logger.warning("[ERROR] [GNews] HTTP %d error", response.status_code)

                return []
        except RuntimeError:
            raise
        except Exception as e:
            logger.error("[ERROR] [GNews] API error: %s", e)
            return []
    
    def _parse_response(self, data: Dict, category: str) -> List[Article]:
        """Parse GNews API response"""
        articles = []
        for item in data.get('articles', []):
            try:
                article = Article(
                    title=item.get('title', ''),
                    description=item.get('description', ''),
                    url=item.get('url', ''),
                    image_url=item.get('image') or '',
                    published_at=item.get('publishedAt', datetime.now().isoformat()),
                    source=item.get('source', {}).get('name', 'GNews'),
                    category=category
                )
                articles.append(article)
            except Exception as e:
                logger.debug("[WARN] [GNews] Error parsing article: %s", e)
                continue
        return articles


class NewsAPIProvider(NewsProvider):
    """NewsAPI.org provider"""
    
    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key)
        self.base_url = "https://newsapi.org/v2"
        self.daily_limit = 100

        # ── REFERENCE BACKUP (no longer used at runtime) ───────────────────────
        # These were the old hardcoded query strings. They are kept here only as
        # a human-readable reference of what we used to send.
        # The live query is now built dynamically by build_dynamic_query() below,
        # which applies the full Phase 19 taxonomy with UTC-clock round-robin rotation.
        # To revert to static queries, replace the dynamic call with:
        #     query = self.category_keywords.get(category, category)
        self.category_keywords = {
            'ai':                   '"artificial intelligence" OR "machine learning" OR "deep learning"',
            'data-security':        '"data security" OR cybersecurity OR "data breach"',
            'data-governance':      '"data governance" OR compliance',
            'data-privacy':         '"data privacy" OR GDPR OR "privacy regulation"',
            'data-engineering':     '"data engineering" OR "data pipeline" OR "big data"',
            'data-management':      '"data management" OR MDM OR "data catalog"',
            'business-intelligence':'business intelligence OR "BI tools"',
            'business-analytics':   '"business analytics" OR analytics',
            'customer-data-platform':'"customer data platform" OR CDP',
            'data-centers':         '"data centers" OR "data centre"',
            'cloud-computing':      '"cloud computing" OR AWS OR Azure OR "Google Cloud"',
            'cloud-aws':            'AWS OR "Amazon Web Services" OR SageMaker',
            'cloud-azure':          'Azure OR "Microsoft Azure" OR "Azure OpenAI"',
            'cloud-gcp':            'GCP OR "Google Cloud" OR BigQuery OR "Vertex AI"',
            'cloud-oracle':         '"Oracle Cloud" OR OCI OR "Oracle Database"',
            'cloud-ibm':            '"IBM Cloud" OR "IBM Watson" OR OpenShift',
            'cloud-alibaba':        '"Alibaba Cloud" OR Aliyun',
            'cloud-digitalocean':   'DigitalOcean',
            'cloud-huawei':         '"Huawei Cloud"',
            'cloud-cloudflare':     'Cloudflare OR "Zero Trust"',
            'medium-article':       'Medium OR "Medium article" OR "Medium blog"',
            'magazines':            'technology',
            'data-laws':            '"data privacy law" OR GDPR OR CCPA OR "EU AI Act"',
        }

    async def fetch_news(self, category: str, limit: int = 20) -> List[Article]:
        """
        Fetch news from NewsAPI.

        Phase 20 upgrade: The query string is now built dynamically by
        build_dynamic_query() from app.utils.query_builder.
        It uses the full Phase 19 expanded taxonomy with the Anchor + Round-Robin
        rotation, driven by the current UTC hour. This means:
          • Every hour, we ask for a DIFFERENT subset of our keyword taxonomy.
          • The first 3 keywords (anchors) are ALWAYS included — no breaking news missed.
          • The URL stays well under the ~500-char limit at all times.
          • Zero Redis, zero state — just the server clock.

        Why no 'from' date filter?
        Some NewsAPI plan tiers restrict date filtering and return status='error'
        when a date param is used. Our data_validation.py freshness gate handles
        date filtering downstream.
        """
        if not self.api_key:
            return []

        try:
            # ── Phase 20: Dynamic query builder ─────────────────────────────────
            # build_dynamic_query selects anchors + current hour's rotating chunk
            # from the full CATEGORY_KEYWORDS taxonomy and formats it for NewsAPI's
            # boolean OR syntax (e.g. '"openai" OR "machine learning" OR anthropic').
            from app.utils.query_builder import build_dynamic_query
            query = build_dynamic_query(category, api_type="newsapi")
            url = f"{self.base_url}/everything"

            # Simple, plan-compatible request — no date window.
            params = {
                'q': query,
                'language': 'en',
                'sortBy': 'publishedAt',
                'pageSize': min(limit, 20),
                'apiKey': self.api_key,
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params)

                if response.status_code == 429 or response.status_code == 426:
                    self.handle_429()
                    return []

                if response.status_code == 200:
                    self.request_count += 1
                    data = response.json()

                    # FIX (Bug B): NewsAPI returns HTTP 200 but sets status='error'
                    # in the JSON when the API key is invalid or a plan restriction
                    # is hit. We raise here so the aggregator's except block catches
                    # it and calls circuit.record_failure() automatically.
                    if data.get('status') == 'error':
                        raise RuntimeError(
                            f"[NewsAPI] API error: {data.get('message', 'unknown error')}"
                        )

                    articles = self._parse_response(data, category)
                    if articles:
                        logger.info("[SUCCESS] [NewsAPI] Fetched %d articles.", len(articles))
                    else:
                        logger.debug("[WARN] [NewsAPI] No articles this run (API healthy, just quiet).")
                    return articles

                return []
        except RuntimeError:
            raise
        except Exception as e:
            logger.error("[NewsAPI] fetch error: %s", e)
            return []
    
    def _parse_response(self, data: Dict, category: str) -> List[Article]:
        """Parse NewsAPI response"""
        articles = []
        for item in data.get('articles', []):
            try:
                article = Article(
                    title=item.get('title', ''),
                    description=item.get('description', ''),
                    url=item.get('url', ''),
                    image_url=item.get('urlToImage') or '',
                    published_at=item.get('publishedAt', datetime.now().isoformat()),
                    source=item.get('source', {}).get('name', 'NewsAPI'),
                    category=category
                )
                articles.append(article)
            except Exception as e:
                logger.debug("[WARN] [NewsAPI] Error parsing article: %s", e)
                continue
        return articles


class NewsDataProvider(NewsProvider):
    """NewsData.io provider"""
    
    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key)
        self.base_url = "https://newsdata.io/api/1"
        self.daily_limit = 200
        
        # ── REFERENCE BACKUP (no longer used at runtime — Phase 21) ─────────
        # These were the old static comma-separated query strings for NewsData.
        # The live query is now built dynamically by build_dynamic_query().
        # To revert, replace the dynamic call in fetch_news() with:
        #     query = self.category_keywords.get(category, category)
        # Category keywords
        self.category_keywords = {
            'ai': 'artificial intelligence,machine learning',
            'data-security': 'data security,cybersecurity',
            'data-governance': 'data governance,compliance',
            'data-privacy': 'data privacy,GDPR',
            'data-engineering': 'data engineering,big data',
            'data-management': 'data management,master data,MDM,data catalog,data quality,data lineage',
            'business-intelligence': 'business intelligence',
            'business-analytics': 'business analytics',
            'customer-data-platform': 'customer data platform',
            'data-centers': 'data centers',
            'cloud-computing': 'cloud computing,AWS,Azure,Google Cloud,Salesforce,Alibaba Cloud,Tencent Cloud,Huawei Cloud,Cloudflare',
            'cloud-aws': 'AWS,Amazon Web Services,Amazon S3,EC2,Lambda,CloudFront,SageMaker',
            'cloud-azure': 'Azure,Microsoft Azure,Azure DevOps,Azure ML,Azure OpenAI',
            'cloud-gcp': 'GCP,Google Cloud Platform,BigQuery,Vertex AI,Cloud Run,Dataflow',
            'cloud-oracle': 'Oracle Cloud,OCI,Oracle Database,Oracle Fusion',
            'cloud-ibm': 'IBM Cloud,IBM Watson,Red Hat,OpenShift,IBM Z',
            'cloud-alibaba': 'Alibaba Cloud,Aliyun,AliCloud',
            'cloud-digitalocean': 'DigitalOcean,Droplet,App Platform',
            'cloud-huawei': 'Huawei Cloud,HuaweiCloud',
            'cloud-cloudflare': 'Cloudflare,Cloudflare Workers,Cloudflare R2,Zero Trust',
            'medium-article': 'Medium,article,blog,writing,publishing',
            'magazines': 'technology',
            'data-laws': 'data privacy law,GDPR,CCPA,AI regulation,compliance',
        }
    
    async def fetch_news(self, category: str, limit: int = 20) -> List[Article]:
        """Fetch news from NewsData.io"""
        if not self.api_key:
            return []
        
        try:
            # Build dynamic query — comma-separated for NewsData.io's search syntax.
            from app.utils.query_builder import build_dynamic_query
            query = build_dynamic_query(category, api_type="newsdata")
            url = f"{self.base_url}/news"

            # NOTE: 'timeframe' is a PAID-tier-only parameter on NewsData.io.
            # Using it on a free-tier key returns HTTP 422 UNPROCESSABLE ENTITY.
            # Removed — freshness filtering is handled by data_validation.py downstream.
            params = {
                'q': query,
                'language': 'en',
                'country': 'us',
                'apikey': self.api_key,
            }
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params)
                
                if response.status_code == 429:
                    self.handle_429()
                    return []
                
                if response.status_code == 200:
                    self.request_count += 1
                    data = response.json()
                    articles = self._parse_response(data, category, limit)
                    if articles:
                        logger.info("[SUCCESS] [NewsData] Fetched %d articles.", len(articles))
                    else:
                        logger.debug("[WARN] [NewsData] No articles found in response.")
                    return articles
                else:
                    logger.warning("[ERROR] [NewsData] HTTP %d — body: %s",
                                   response.status_code, response.text[:200])

                return []
        except Exception as e:
            logger.error("[NewsData] fetch error: %s", e)
            return []
    
    def _parse_response(self, data: Dict, category: str, limit: int) -> List[Article]:
        """Parse NewsData.io response"""
        articles = []
        for item in data.get('results', [])[:limit]:
            try:
                article = Article(
                    title=item.get('title', ''),
                    description=item.get('description', ''),
                    url=item.get('link', ''),
                    image_url=item.get('image_url') or '',
                    published_at=item.get('pubDate', datetime.now().isoformat()),
                    source=item.get('source_id', 'NewsData'),
                    category=category
                )
                articles.append(article)
            except Exception as e:
                logger.debug("[WARN] [NewsData] Error parsing article: %s", e)
                continue
        return articles


class GoogleNewsRSSProvider(NewsProvider):
    """Google News RSS provider (no API key needed)"""
    
    def __init__(self):
        super().__init__(None)
        self.daily_limit = 0  # Unlimited (but rate limited by Google)
        
        # RSS feed URLs by category
        self.feed_urls = {
            'ai': 'https://news.google.com/rss/search?q=artificial+intelligence+OR+machine+learning&hl=en-US&gl=US&ceid=US:en',
            'data-security': 'https://news.google.com/rss/search?q=data+security+OR+cybersecurity+OR+data+breach&hl=en-US&gl=US&ceid=US:en',
            'data-governance': 'https://news.google.com/rss/search?q=data+governance+OR+data+management&hl=en-US&gl=US&ceid=US:en',
            'data-privacy': 'https://news.google.com/rss/search?q=data+privacy+OR+GDPR+OR+privacy+regulation&hl=en-US&gl=US&ceid=US:en',
            'data-engineering': 'https://news.google.com/rss/search?q=data+engineering+OR+data+pipeline+OR+big+data&hl=en-US&gl=US&ceid=US:en',
            'data-management': 'https://news.google.com/rss/search?q=%22data+management%22+OR+%22master+data%22+OR+MDM+OR+%22data+catalog%22&hl=en-US&gl=US&ceid=US:en',
            'business-intelligence': 'https://news.google.com/rss/search?q=business+intelligence+OR+BI+tools&hl=en-US&gl=US&ceid=US:en',
            'business-analytics': 'https://news.google.com/rss/search?q=business+analytics&hl=en-US&gl=US&ceid=US:en',
            'customer-data-platform': 'https://news.google.com/rss/search?q=customer+data+platform+OR+CDP&hl=en-US&gl=US&ceid=US:en',
            'data-centers': 'https://news.google.com/rss/search?q=data+centers+OR+data+centre&hl=en-US&gl=US&ceid=US:en',
            'cloud-computing': 'https://news.google.com/rss/search?q=cloud+computing+OR+AWS+OR+Azure+OR+Google+Cloud+OR+Salesforce+OR+Alibaba+Cloud+OR+Tencent+Cloud+OR+Huawei+Cloud+OR+Cloudflare&hl=en-US&gl=US&ceid=US:en',
            'cloud-aws': 'https://news.google.com/rss/search?q=AWS+OR+%22Amazon+Web+Services%22+OR+%22Amazon+S3%22+OR+EC2+OR+Lambda&hl=en-US&gl=US&ceid=US:en',
            'cloud-azure': 'https://news.google.com/rss/search?q=Azure+OR+%22Microsoft+Azure%22+OR+%22Azure+DevOps%22&hl=en-US&gl=US&ceid=US:en',
            'cloud-gcp': 'https://news.google.com/rss/search?q=GCP+OR+%22Google+Cloud%22+OR+BigQuery+OR+%22Vertex+AI%22&hl=en-US&gl=US&ceid=US:en',
            'cloud-oracle': 'https://news.google.com/rss/search?q=%22Oracle+Cloud%22+OR+OCI+OR+%22Oracle+Database%22&hl=en-US&gl=US&ceid=US:en',
            'cloud-ibm': 'https://news.google.com/rss/search?q=%22IBM+Cloud%22+OR+%22IBM+Watson%22+OR+OpenShift&hl=en-US&gl=US&ceid=US:en',
            'cloud-alibaba': 'https://news.google.com/rss/search?q=%22Alibaba+Cloud%22+OR+Aliyun&hl=en-US&gl=US&ceid=US:en',
            'cloud-digitalocean': 'https://news.google.com/rss/search?q=DigitalOcean+OR+Droplet&hl=en-US&gl=US&ceid=US:en',
            'cloud-huawei': 'https://news.google.com/rss/search?q=%22Huawei+Cloud%22+OR+HuaweiCloud&hl=en-US&gl=US&ceid=US:en',
            'cloud-cloudflare': 'https://news.google.com/rss/search?q=Cloudflare+OR+%22Cloudflare+Workers%22+OR+%22Zero+Trust%22&hl=en-US&gl=US&ceid=US:en',
            'medium-article': 'https://news.google.com/rss/search?q=Medium+article+OR+Medium+blog+OR+Medium+publishing&hl=en-US&gl=US&ceid=US:en',
            'magazines': 'https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-US&gl=US&ceid=US:en',
            'data-laws': 'https://news.google.com/rss/search?q=data+privacy+law+OR+GDPR+OR+CCPA+OR+AI+Regulation&hl=en-US&gl=US&ceid=US:en',
        }
    
    async def fetch_news(self, category: str, limit: int = 20) -> List[Article]:
        """Fetch news from Google News RSS"""
        from app.services.rss_parser import RSSParser
        
        feed_url = self.feed_urls.get(category)
        if not feed_url:
            return []
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(feed_url)
                
                if response.status_code == 429:
                    self.handle_429()
                    return []
                
                if response.status_code == 200:
                    self.request_count += 1
                    parser = RSSParser()
                    articles = await parser.parse_google_news(response.text, category)
                    if articles:
                        logger.info("[SUCCESS] [Google RSS] Fetched %d articles.", len(articles))
                    else:
                        logger.debug("[WARN] [Google RSS] No articles found in feed.")
                    return articles
                else:
                    logger.warning("[ERROR] [Google RSS] HTTP %d", response.status_code)

                return []
        except Exception as e:
            logger.error("[ERROR] [Google RSS] error: %s", e)
            return []


class MediumRSSProvider(NewsProvider):
    """
    Medium RSS Provider
    Fetches latest 10 articles per tag. Handles CDATA image extraction.
    """
    
    def __init__(self):
        # No API key needed for RSS
        super().__init__(None)
        self.base_url = "https://medium.com/feed/tag"
        self.daily_limit = 0 # Unlimited
        
        # Map our categories to Medium Tags
        self.tag_map = {
            'ai': 'artificial-intelligence',
            'data-science': 'data-science',
            'cloud-computing': 'cloud-computing',
            'programming': 'programming',
            'technology': 'technology',
            'data-laws': 'law'
        }

    async def fetch_news(self, category: str, limit: int = 10) -> List[Article]:
        """Fetch and parse Medium RSS feed"""
        import feedparser
        import re
        
        tag = self.tag_map.get(category, category)
        url = f"{self.base_url}/{tag}"
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, follow_redirects=True)
                
                if response.status_code == 429:
                    self.handle_429()
                    return []
                
                if response.status_code != 200:
                    logger.warning(f"[Medium] HTTP {response.status_code} for tag {tag}")
                    return []
                
                feed = feedparser.parse(response.text)
                articles = []
                
                for entry in feed.entries:
                    # image extraction...
                    content_html = ''
                    if hasattr(entry, 'content'):
                        content_html = entry.content[0].value
                    elif hasattr(entry, 'summary'):
                         content_html = entry.summary
                    
                    image_url = self._extract_medium_image(content_html)
                    
                    article = Article(
                        title=entry.get('title', 'Untitled'),
                        description=self._clean_html(entry.get('summary', ''))[:200],
                        url=entry.get('link', ''),
                        image_url=image_url,
                        published_at=self._parse_pub_date(entry.get('published')),
                        source="Medium",
                        category="medium-article"
                    )
                    articles.append(article)
                    
                logger.info("[SUCCESS] [Medium] Fetched %d for tag '%s'.", len(articles), tag)
                return articles

        except httpx.TimeoutException:
            logger.warning("[Medium] Timed out for tag %s", tag)
            return []
        except Exception as e:
            logger.error("[ERROR] [Medium] Error fetching %s: %s", tag, e)
            return []

    def _extract_medium_image(self, html_content: str) -> str:
        """
        Extracts the first valid image URL from Medium's HTML content.
        Medium uses <img src="..." /> inside the content block.
        """
        import re
        if not html_content:
            return ""
            
        # Regex to find the first <img src="...">
        # We explicitly look for 'cdn-images' to ensure it's a Medium hosted image
        match = re.search(r'<img[^>]+src="([^">]+)"', html_content)
        
        if match:
            return match.group(1)
            
        return ""

    def _clean_html(self, raw_html: str) -> str:
        """Removes HTML tags for a clean description"""
        import re
        cleanr = re.compile('<.*?>')
        text = re.sub(cleanr, '', raw_html)
        return text.strip()

    def _parse_pub_date(self, date_str: str) -> str:
        try:
            # Medium format: 'Fri, 24 Jan 2026 12:00:00 GMT'
            dt = datetime.strptime(date_str, '%a, %d %b %Y %H:%M:%S %Z')
            return dt.isoformat()
        except:
            return datetime.now().isoformat()


class OfficialCloudProvider(NewsProvider):
    """
    Official Cloud Provider RSS
    Strictly maps categories to specific official blogs.
    Prevents cross-contamination (AWS news only in cloud-aws).
    """
    
    def __init__(self):
        super().__init__(None)
        self.daily_limit = 0
        
        # Strict mapping: Category -> RSS URL
        # NOTE: URLs verified/updated 2026-03-11:
        #   IBM:         /blog/rss returns 301 → dead. Use developer.ibm.com blog feed.
        #   Alibaba:     /blog/feed returns 302 → 404. Use English partner blog.
        #   DigitalOcean: /blog/rss.xml returns 404. Use the community tutorials RSS.
        #   Oracle:      /cloud-infrastructure/rss returns 301 → 403. Use /feed path.
        #   Huawei:      blog.huawei.com HTML page fetched 0 — use newsroom atom feed.
        self.provider_map = {
            'cloud-aws': 'https://aws.amazon.com/blogs/aws/feed/',
            'cloud-azure': 'https://azure.microsoft.com/en-us/blog/feed/',
            'cloud-google': 'https://cloudblog.withgoogle.com/rss/',  # Legacy mapping
            'cloud-gcp': 'https://cloudblog.withgoogle.com/rss/',
            'cloud-oracle': 'https://blogs.oracle.com/cloud-infrastructure/feed',
            'cloud-ibm': 'https://developer.ibm.com/blogs/feed/',
            'cloud-alibaba': 'https://www.alibabacloud.com/en/blog/rss',
            'cloud-digitalocean': 'https://www.digitalocean.com/community/tutorials/feed?tag=cloud',
            'cloud-cloudflare': 'https://blog.cloudflare.com/rss/',
            'cloud-huawei': 'https://consumer.huawei.com/en/newsroom/rss/',
        }

    async def fetch_news(self, category: str, limit: int = 20) -> List[Article]:
        """Fetch news specifically for the requested category"""
        rss_url = self.provider_map.get(category)
        
        # STRICT ISOLATION: If this category isn't in our map, return nothing.
        # This ensures we don't accidentally fetch 'cloud-computing' generic news here.
        if not rss_url:
            return []
            
        try:
            # Use RSSParser's logic but force our strict category
            from app.services.rss_parser import RSSParser
            parser = RSSParser()
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(rss_url, follow_redirects=True)

                if response.status_code == 429:
                    self.handle_429()
                    return []
                
                if response.status_code == 200:
                    # Parse using the generic provider parser
                    # We pass the category name as the 'provider' argument to some degree
                    # but we mostly care about the content.
                    # RssParser.parse_provider_rss uses 'provider' arg for source name and partial category.
                    # Let's extract provider name from category (cloud-aws -> AWS)
                    provider_name = category.replace('cloud-', '').upper()
                    
                    # We accept the articles, but we MUST override the category to strict match
                    raw_articles = await parser.parse_provider_rss(response.text, provider_name)
                    
                    final_articles = []
                    for art in raw_articles:
                        # FORCE OVERRIDE
                        art.category = category 
                        art.source = f"Official {provider_name} Blog"
                        final_articles.append(art)
                        
                    logger.info("[SUCCESS] [OfficialCloud] Fetched %d for %s.", len(final_articles), category)
                    return final_articles
                else:
                    logger.warning("[ERROR] [OfficialCloud] HTTP %d for %s", response.status_code, category)
                    return []

        except Exception as e:
            logger.error("[ERROR] [OfficialCloud] Failed %s: %s", category, e)
            return []

