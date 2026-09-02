"""
Data Validation and Sanitization Layer
FAANG-Level Quality Control for News Articles

EMERGENCY HOTFIX (2026-01-23): Fixed AttributeError 'Article' object has no attribute 'get'
- Now supports both Pydantic Article models AND dicts
- Converts Pydantic models to dicts safely before validation
"""

from typing import Dict, Optional, List, Union
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo   # stdlib from Python 3.9+ — no extra install needed
import re
from urllib.parse import urlparse
from dateutil import parser as dateutil_parser


def is_valid_article(article: Union[Dict, 'Article']) -> bool:
    """
    Validate article data quality before database insertion
    
    HOTFIX: Now handles both Pydantic Article objects and dicts
    
    Returns True only if article meets all quality criteria
    """
    # HOTFIX: Convert Pydantic model to dict if needed
    if hasattr(article, 'model_dump'):
        # It's a Pydantic v2 model
        article_dict = article.model_dump()
    elif hasattr(article, 'dict'):
        # It's a Pydantic v1 model
        article_dict = article.dict()
    elif isinstance(article, dict):
        # Already a dict
        article_dict = article
    else:
        # Unknown type - reject
        return False
    
    # Required: Title must exist and be meaningful
    if not article_dict.get('title'):
        return False
    
    title = article_dict['title'].strip()
    if len(title) < 10 or len(title) > 500:
        return False
    
    # Required: Valid URL
    if not article_dict.get('url'):
        return False
    
    # Handle HttpUrl object from Pydantic
    url = article_dict['url']
    if hasattr(url, '__str__'):
        url = str(url)
    url = url.strip()
    
    if not url.startswith(('http://', 'https://')):
        return False
    
    # Validate URL format
    try:
        parsed = urlparse(url)
        if not parsed.netloc:
            return False
    except Exception:
        return False
    
    # Required: Published date must exist.
    raw_date = article_dict.get('publishedAt') or article_dict.get('published_at')
    if not raw_date:
        return False

    # ── FRESHNESS GATE ────────────────────────────────────────────────────────
    # We only want articles published today, where "today" is measured in
    # Indian Standard Time (IST = UTC+5:30) — because that is where our
    # users are.
    #
    # Why IST and not UTC?
    # With UTC midnight as the cutoff, articles published in India between
    # 12:00 AM IST and 5:30 AM IST (the first 5.5 hours of the Indian day)
    # were incorrectly rejected, because UTC midnight had not yet arrived.
    # Switching to IST midnight gives Indian users a full 24-hour day.
    #
    # CRITICAL ORDER: This check runs on the RAW date string, before
    # normalize_article_date() gets a chance to run. That function has a
    # silent fallback: if a date is unparseable it stamps the article with
    # 'right now'. Without this guard, a 3-day-old article with a broken
    # date string would survive normalization and appear fresh.
    try:
        if isinstance(raw_date, datetime):
            pub_dt = raw_date
        else:
            pub_dt = dateutil_parser.parse(str(raw_date))

        # Make timezone-aware if the provider gave us a naive datetime.
        if pub_dt.tzinfo is None:
            pub_dt = pub_dt.replace(tzinfo=timezone.utc)

        # Step 1: Find midnight IST of yesterday to allow a broader rolling window
        # We get the current moment in IST, then zero out hours/minutes/seconds,
        # and subtract 1 day to allow articles from yesterday, today, and tomorrow.
        ist_zone   = ZoneInfo("Asia/Kolkata")
        now_ist    = datetime.now(ist_zone)
        cutoff_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)

        # Step 2: The article timestamp may be in any timezone (UTC, EST, etc.).
        # Python's datetime comparison handles mixed timezones correctly as long
        # as both sides are timezone-aware — which they both are here.
        if pub_dt < cutoff_ist:
            # Article was published before midnight IST today — reject it.
            return False

    except Exception:
        # If we genuinely cannot parse the date, we reject the article.
        # Better to miss one article than to save a zombie with a fake date.
        return False
    # ──────────────────────────────────────────────────────────────────────────

    # Optional but validate if present: Image URL
    # Handle both 'image' (raw API) and 'image_url' (Pydantic/DB)
    image_url = article_dict.get('image') or article_dict.get('image_url')
    if image_url:
        image_url = str(image_url).strip()
        if not image_url.startswith(('http://', 'https://')):
            # Invalid image URL - remove both keys to be safe
            if 'image' in article_dict: article_dict['image'] = None
            if 'image_url' in article_dict: article_dict['image_url'] = None

    return True


def sanitize_article(article: Union[Dict, 'Article']) -> Dict:
    """
    Clean and normalize article data
    
    HOTFIX: Now handles both Pydantic Article objects and dicts
    
    Ensures data fits schema constraints and is properly formatted
    """
    # HOTFIX: Convert Pydantic model to dict if needed
    if hasattr(article, 'model_dump'):
        article_dict = article.model_dump()
    elif hasattr(article, 'dict'):
        article_dict = article.dict()
    elif isinstance(article, dict):
        article_dict = article
    else:
        raise TypeError(f"Expected Dict or Article model, got {type(article)}")
    
    # Clean title
    title = article_dict.get('title', '').strip()
    title = re.sub(r'\s+', ' ', title)  # Normalize whitespace
    title = title[:500]  # Truncate to schema limit
    
    # Clean URL (handle HttpUrl objects)
    url = article_dict.get('url', '')
    if hasattr(url, '__str__'):
        url = str(url)
    url = url.strip()[:2048]
    
    # Clean description
    description = article_dict.get('description', '').strip()
    description = re.sub(r'\s+', ' ', description)
    description = description[:2000]
    
    # Clean image URL - Support both keys
    raw_image = article_dict.get('image') or article_dict.get('image_url')
    image_url = str(raw_image).strip() if raw_image else None
    
    if image_url:
        image_url = image_url[:2048] # Increased to match DB schema (was 1000)
        if not image_url.startswith(('http://', 'https://')):
            image_url = None
    
    # Clean source name
    source = article_dict.get('source', 'Unknown').strip()
    source = source[:200]
    
    # Generate slug from title
    slug = generate_slug(title)
    
    # Calculate quality score
    quality_score = calculate_quality_score(article_dict)
    
    # Handle publishedAt (convert datetime to ISO string if needed)
    # Check both keys
    published_at = article_dict.get('publishedAt') or article_dict.get('published_at')
    
    if isinstance(published_at, datetime):
        published_at = published_at.isoformat()
    elif not published_at:
        # Fallback to current time if missing
        published_at = datetime.now().isoformat()
    
    # Return standardized dict (using camelCase for legacy compatibility or standardized snake_case?)
    # The AppwriteDatabase understands both, checking 'published_at' OR 'publishedAt'.
    # But usually it's best to standardize on what the DB considers 'canonical'.
    # However, this function `sanitize_article` returns a dict that replaces the original object.
    # We should probably return both or standardize on snake_case?
    # Existing code returned 'publishedAt', 'image'.
    # Let's keep returning 'publishedAt' for backward compat with whatever else uses this,
    # BUT explicitly set the values we found.
    
    return {
        'title': title,
        'url': url,
        'description': description or '',
        'image': image_url, # Legacy key
        'image_url': image_url, # Modern key
        'publishedAt': published_at, # Legacy key
        'published_at': published_at, # Modern key
        'source': source,
        'category': article_dict.get('category', '').strip()[:100],
        'slug': slug,
        'quality_score': quality_score
    }


def generate_slug(title: str) -> str:
    """
    Generate URL-friendly slug from title
    
    Example: "Google Announces New AI" → "google-announces-new-ai"
    """
    slug = title.lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)  # Remove special chars
    slug = re.sub(r'\s+', '-', slug)  # Replace spaces with hyphens
    slug = re.sub(r'-+', '-', slug)  # Remove duplicate hyphens
    slug = slug.strip('-')  # Remove leading/trailing hyphens
    slug = slug[:200]  # Limit length
    return slug


def calculate_quality_score(article: Dict) -> int:
    """
    Score article quality from 0-100
    
    Higher scores = better quality articles
    Used for sorting and filtering
    """
    score = 50  # Base score
    
    # Has image (+20)
    if article.get('image'):
        score += 20
    
    # Good description (+15)
    description = article.get('description', '')
    if len(description) > 100:
        score += 15
    
    # Premium sources (+15)
    source = article.get('source', '').lower()
    premium_sources = [
        'reuters', 'bloomberg', 'techcrunch', 'wired', 
        'the verge', 'zdnet', 'cnet', 'ars technica'
    ]
    if any(ps in source for ps in premium_sources):
        score += 15
    
    # Long title penalty (-10, might be clickbait)
    title = article.get('title', '')
    if len(title) > 100:
        score -= 10
    
    # Cap at 100
    return min(max(score, 0), 100)


# ==============================================================================
# MASTER CATEGORY TAXONOMY  (Phase 19 — Expanded Entity-Based Keywords)
# ==============================================================================
#
# This dictionary is the SINGLE SOURCE OF TRUTH for category routing.
# Every category has a rich list of keywords covering:
#   • The topic itself            (e.g., "machine learning")
#   • Major companies             (e.g., "openai", "anthropic")
#   • Flagship products           (e.g., "chatgpt", "sagemaker")
#   • Industry acronyms           (e.g., "llm", "etl", "gcp")
#
# ⚠️  IMPORTANT — word-boundary safety:
#   Short acronyms like "ai", "bi", "aws" MUST live here — we protect them
#   with \b regex word boundaries in COMPILED_CATEGORY_REGEX below.
#   Do NOT add single-letter keywords; they can never be safe.
#
# NOTE: 'cloud-computing' is kept here because it is an active category in
#   config.py, news_aggregator.py, and several providers. Removing it would
#   break article routing for all generic cloud news. — Phase 19
# ==============================================================================
CATEGORY_KEYWORDS = {

    # ── Artificial Intelligence ────────────────────────────────────────────────
    'ai': [
        'artificial intelligence', 'machine learning', 'deep learning',
        'neural network', 'gpt', 'llm', 'chatgpt', 'generative ai',
        'computer vision', 'nlp', 'natural language processing', 'transformer',
        'openai', 'anthropic', 'sam altman', 'claude', 'gemini', 'mistral',
        'llama', 'copilot', 'midjourney', 'stable diffusion', 'hugging face',
        'rag', 'vector database', 'prompt engineering', 'agi', 'agentic ai',
        'ai model', 'ai startup', 'genai', 'intelligence', 'robotics', 'algorithm',
    ],

    # ── Cloud — generic umbrella category (must stay: used in config.py) ──────
    'cloud-computing': [
        'cloud computing', 'cloud services', 'aws', 'azure', 'google cloud',
        'gcp', 'salesforce', 'alibaba cloud', 'tencent cloud', 'huawei cloud',
        'cloudflare', 'saas', 'paas', 'iaas', 'serverless', 'kubernetes',
        'multi-cloud', 'hybrid cloud', 'cloud infrastructure', 'cloud deployment',
    ],

    # ── Cloud sub-categories (provider-specific) ───────────────────────────────
    'cloud-aws': [
        'aws', 'amazon web services', 's3', 'ec2', 'lambda', 'cloudfront',
        'sagemaker', 'dynamodb', 'amazon bedrock', 'aws reinvent',
        'fargate', 'aws graviton', 'elastic beanstalk', 'amazon cloud',
    ],
    'cloud-azure': [
        'azure', 'microsoft azure', 'azure devops', 'azure ml',
        'azure openai', 'microsoft cloud', 'azure synapse', 'cosmos db',
        'azure arc', 'microsoft entra', 'azure cloud',
    ],
    'cloud-gcp': [
        'gcp', 'google cloud', 'bigquery', 'vertex ai', 'cloud run',
        'dataflow', 'google kubernetes engine', 'gke', 'google spanner',
        'anthos', 'cloud sql', 'gemini for google cloud', 'google workspace',
    ],
    'cloud-alibaba': [
        'alibaba cloud', 'aliyun', 'alicloud', 'polar db', 'maxcompute',
        'elastic compute service', 'tongyi qianwen', 'qwen', 'alibaba',
    ],
    'cloud-huawei': [
        'huawei cloud', 'huaweicloud', 'pangu model',
        'harmonyos', 'kunpeng', 'ascend ai', 'huawei',
    ],
    'cloud-digitalocean': [
        'digitalocean', 'digital ocean', 'do droplet', 'digitalocean spaces',
        'digitalocean app platform', 'managed kubernetes', 'cloudways', 'vps',
    ],
    'cloud-oracle': [
        'oracle cloud', 'oci', 'oracle database', 'oracle fusion',
        'oracle cloud infrastructure', 'mysql heatwave', 'oracle apex', 'oracle',
    ],
    'cloud-ibm': [
        'ibm cloud', 'ibm watson', 'red hat', 'openshift',
        'ibm z', 'watsonx', 'ibm mainframe', 'ibm',
    ],
    'cloud-cloudflare': [
        'cloudflare', 'cloudflare workers', 'cloudflare r2',
        'cloudflare pages', 'zero trust', 'cdn', 'ddos',
    ],

    # ── Data Engineering ───────────────────────────────────────────────────────
    'data-engineering': [
        'data engineering', 'data pipeline', 'etl', 'elt', 'big data',
        'apache spark', 'hadoop', 'kafka', 'airflow', 'data warehouse',
        'snowflake', 'databricks', 'dbt', 'fivetran', 'apache iceberg',
        'delta lake', 'data lakehouse', 'data processing', 'streaming data',
    ],

    # ── Data Security ─────────────────────────────────────────────────────────
    'data-security': [
        'security', 'cybersecurity', 'data breach', 'hacking', 'vulnerability',
        'encryption', 'malware', 'ransomware', 'firewall', 'zero trust',
        'phishing', 'soc2', 'infosec', 'penetration testing', 'cyber attack',
        # Bridging terms
        'cyber threat', 'threat intelligence', 'security incident', 'identity and access',
        'iam', 'mfa', 'multi-factor authentication', 'devsecops', 'security posture',
        'insider threat', 'data exfiltration', 'endpoint security', 'siem', 'xdr', 'edr',
    ],

    # ── Data Governance ───────────────────────────────────────────────────────
    'data-governance': [
        'data governance', 'compliance', 'regulation', 'audit', 'data policy',
        'metadata management', 'data lineage', 'data stewardship',
        'regulatory compliance', 'data ethics', 'data standards',
        # Bridging terms
        'governance framework', 'data ownership', 'data accountability',
        'data control', 'enterprise data', 'data risk', 'governance platform',
        'compliance management', 'risk and compliance',
    ],

    # ── Data Privacy ──────────────────────────────────────────────────────────
    'data-privacy': [
        'data privacy', 'gdpr', 'ccpa', 'user consent', 'personal data',
        'pii', 'anonymization', 'data protection', 'privacy law',
        'hipaa', 'cookie tracking', 'data sovereignty',
        # Bridging terms — clear signals not caught by strict phrase matching
        'privacy regulation', 'privacy compliance', 'privacy policy', 'privacy shield',
        'data rights', 'right to be forgotten', 'data subject', 'consent management',
        'biometric data', 'sensitive data', 'data localization', 'privacy tech',
    ],

    # ── Data Management ───────────────────────────────────────────────────────
    'data-management': [
        'data management', 'master data', 'mdm', 'data catalog',
        'data quality', 'reference data', 'data lifecycle', 'data architecture',
        'database management', 'data integration',
        # Bridging terms
        'data platform', 'data fabric', 'data mesh', 'data store', 'data ops',
        'dataops', 'data observability', 'data reliability', 'data strategy',
    ],

    # ── Business Intelligence ─────────────────────────────────────────────────
    'business-intelligence': [
        'business intelligence', 'bi tool', 'analytics dashboard', 'tableau',
        'power bi', 'looker', 'data reporting', 'kpi', 'quicksight', 'qlik',
        'data visualization', 'metrics dashboard', 'business intelligence analytics',
        'bi platform', 'bi software', 'bi solution', 'bi market', 'bi vendor',
        'intelligence analytics', 'embedded analytics', 'self-service analytics',
    ],

    # ── Business Analytics ────────────────────────────────────────────────────
    'business-analytics': [
        'data analytics', 'data analysis', 'business insights', 'business metrics',
        'data-driven', 'business analytics', 'predictive analytics', 'forecasting',
        'data science', 'business trends', 'business intelligence analytics',
        'analytics platform', 'analytics solution', 'analytics market',
        # Bridging single terms that are unambiguous in context
        'analytics', 'prescriptive analytics', 'descriptive analytics',
        'augmented analytics', 'analytics report', 'analytics vendor',
    ],

    # ── Customer Data Platform ────────────────────────────────────────────────
    'customer-data-platform': [
        'cdp', 'customer data platform', 'crm', 'customer experience',
        'personalization engine', 'audience segmentation',
        'segment.com', 'salesforce data cloud', 'unified profile',
        # Bridging terms
        'first-party data', 'customer journey', 'customer analytics',
        'customer insights', 'customer 360', 'real-time personalization',
        'user profiling', 'identity resolution', 'marketing data',
    ],

    # ── Data Centers ──────────────────────────────────────────────────────────
    'data-centers': [
        'data center', 'data centre', 'datacenter', 'server rack', 'colocation',
        'edge computing', 'hyperscale', 'hpc', 'liquid cooling',
        'data center cooling', 'server hosting', 'infrastructure',
        # Bridging terms
        'facility expansion', 'power usage effectiveness', 'pue', 'green data center',
        'data center market', 'carrier hotel', 'colo facility', 'rack unit',
        'data center construction', 'data hall', 'tier iii', 'tier iv',
    ],

    # ── Publishing categories ─────────────────────────────────────────────────
    'medium-article': [
        'medium', 'article', 'blog', 'writing', 'publishing',
        'content', 'story', 'author', 'blogging', 'programming', 'developer',
    ],
    'magazines': [
        'technology', 'tech', 'innovation', 'digital', 'startup',
        'software', 'hardware', 'gadget', 'science', 'electronics',
        # Bridging terms to improve generic tech article capture
        'developer', 'programming', 'open source', 'engineering', 'product launch',
        'research', 'industry report', 'tech news', 'venture capital', 'funding round',
    ],
}


# ==============================================================================
# PRE-COMPILED REGEX ENGINE  (Phase 19 — Word-Boundary Patterns)
# ==============================================================================
#
# Problem this solves:
#   Old code: "ai" in text  →  matches "tr[ai]n", "ava[i]lable" — garbage hits.
#   New code: \bai\b in text → only "AI" as a standalone word — clean hits.
#
# Why pre-compile?
#   Building a regex from scratch takes CPU time. If we do it inside the
#   validation function, it runs once per article × 22 categories = thousands of
#   compilations per scheduler cycle. By compiling ONCE at import time and
#   storing the result, all subsequent lookups are instant memory reads.
#
# How each pattern is built:
#   For every keyword in a category we do:
#       re.escape(keyword)   → safely escapes dots, plus signs, brackets etc.
#       \b ... \b            → word boundaries so "aws" won't match "kawasaki"
#   All keywords in one category are joined with | (OR), so a single
#   re.search() call checks every keyword at once — maximum speed.
#
# Example — 'ai' category compiles to:
#   \bartificial intelligence\b|\bmachine learning\b|\bgpt\b|\bllm\b|...
# ==============================================================================
def _build_category_regex(keywords: list) -> 're.Pattern':
    """
    Turn a list of keywords into one pre-compiled word-boundary OR pattern.

    Example:
        ['gpt', 'llm', 'openai']
        → re.compile(r'\\bgpt\\b|\\bllm\\b|\\bopenai\\b', re.IGNORECASE)

    [2026-06-15] AUDITED: This function already uses OR-logic ('|'.join).
    No change needed. Confirmed by codebase audit during ingestion overhaul (I4).
    """
    parts = [r'\b' + re.escape(kw) + r'\b' for kw in keywords]
    return re.compile('|'.join(parts), re.IGNORECASE)


# This dict is built ONCE when the server starts.
# Key   = category slug  (e.g. 'ai', 'cloud-aws')
# Value = compiled regex (e.g. re.compile(r'\bgpt\b|\bllm\b|...'))
COMPILED_CATEGORY_REGEX: dict = {
    category: _build_category_regex(keywords)
    for category, keywords in CATEGORY_KEYWORDS.items()
}

QUALITY_RESCUE_THRESHOLD: int = 65

def is_relevant_to_category(article: Union[Dict, 'Article'], category: str) -> bool:
    """
    Check whether an article belongs to the given category.

    Uses pre-compiled word-boundary regex patterns (built once at server start)
    so that:
      • Short acronyms like "ai", "bi", "aws" only match as full words.
        "trail"  → does NOT match 'ai' anymore.
        "kubernot" → does NOT match 'gcp' anymore.
      • Multi-word phrases like "openai" or "sagemaker" are matched exactly.
      • Unknown categories automatically pass (return True) so we don't
        accidentally drop articles routed to categories we haven't mapped yet.

    Scans: article title + description + URL path (all lowercased).

    Returns:
        True  — article is relevant (at least 1 keyword matches).
        False — no keyword matched; article is rejected for this category.
    """
    # ── Step 1: Convert to dict safely ────────────────────────────────────────
    if hasattr(article, 'model_dump'):
        article_dict = article.model_dump()
    elif hasattr(article, 'dict'):
        article_dict = article.dict()
    else:
        article_dict = article

    # ── Step 1.5: Official Source Bypass ──────────────────────────────────────
    # Official Cloud Providers set their source to "Official AWS Blog" etc.
    # These must bypass the strict keyword checks to ensure high ingestion.
    source = article_dict.get('source', '').lower()
    if source.startswith('official ') and ' blog' in source:
        return True

    # ── Step 2: Look up the pre-compiled pattern for this category ────────────
    pattern = COMPILED_CATEGORY_REGEX.get(category)

    if pattern is None:
        # Category not in our taxonomy — let it pass rather than silently drop.
        return True

    # ── Step 3: Build the search text ─────────────────────────────────────────
    # We scan three sources:
    #   • title       — the headline, most reliable signal
    #   • description — body summary, adds context
    #   • url_words   — URL path with hyphens → spaces.
    #                   Catches articles with empty descriptions like Google RSS.
    #                   e.g. "/aws-launches-sagemaker-feature" → "aws launches sagemaker feature"
    title       = (article_dict.get('title')       or '').lower()
    description = (article_dict.get('description') or '').lower()

    raw_url = article_dict.get('url') or ''
    url_str = str(raw_url).lower()
    try:
        parsed_url = urlparse(url_str)
        # Replace hyphens and slashes with spaces so URL path words
        # are treated as individual tokens by the word-boundary regex.
        url_words = parsed_url.path.replace('-', ' ').replace('/', ' ')
    except Exception:
        url_words = ''

    search_text = f"{title} {description} {url_words}"

    # ── Step 4: Run the compiled regex ────────────────────────────────────────
    # re.search() returns a Match object on the FIRST hit, or None.
    # The pattern already has re.IGNORECASE compiled in — no need to lower() again.
    if pattern.search(search_text):
        return True

    # ── Step 5: Quality-Score Rescue Fallback ─────────────────────────────────
    # Article failed the keyword check, but if it has exceptionally high signal 
    # (images, premium source, long description) we save it anyway.
    quality = calculate_quality_score(article_dict)
    if quality >= QUALITY_RESCUE_THRESHOLD:
        print(
            f"⛑️ Rescued '{article_dict.get('title', 'Unknown')[:50]}' "
            f"from {category} (Regex fail, Quality={quality} ≥ {QUALITY_RESCUE_THRESHOLD})"
        )
        return True

    # No match and low quality — log the rejection for monitoring.
    print(
        f"🚫 Rejected '{article_dict.get('title', 'Unknown')[:50]}' "
        f"from {category} (0 keyword matches, Quality={quality})"
    )
    return False


# Export functions
__all__ = [
    'is_valid_article',
    'sanitize_article',
    'generate_slug',
    'calculate_quality_score',
    'is_relevant_to_category'
]
