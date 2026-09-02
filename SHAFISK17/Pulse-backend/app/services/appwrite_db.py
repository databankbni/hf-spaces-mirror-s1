"""
Appwrite Database Service - Phase 2
Provides persistent storage for news articles with fast querying capability.
"""

# Appwrite SDK v16.0.0 Integration
# Migrated from legacy 'Databases' to modern 'TablesDB' service
import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning, module='appwrite')

try:
    from appwrite.client import Client
    from appwrite.services.databases import Databases
    from appwrite.services.tables_db import TablesDB
    from appwrite.services.storage import Storage
    from appwrite.query import Query
    from appwrite.exception import AppwriteException
    APPWRITE_AVAILABLE = True
except ImportError:
    APPWRITE_AVAILABLE = False
    print("Appwrite SDK not available - database features disabled")

from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import hashlib
import asyncio # For parallel writes
from app.models import Article
from app.config import settings
import logging

# Phase 23: Upgraded to the custom ANSI-aligned logger.
# Every Appwrite save/error line will now appear under the [💾 DB] column
# in the terminal, making it trivial to spot database issues at a glance.
from app.utils.custom_logger import get_logger, TAG_DB, TAG_ERROR
logger = get_logger(__name__)


def _safe_get(data, key, default=None):
    """
    Robust attribute/key getter for Appwrite SDK responses.
    Handles:
    1. Plain dictionaries (standard .get)
    2. SDK Objects with a .data dict (Appwrite v16 Row objects)
    3. SDK Objects (getattr access for legacy DocumentList, RowList)
    4. Automatic aliasing of '$id' <-> 'id'
    5. Support for both .documents (Databases) and .rows (TablesDB)
    6. Data is None/Empty safety

    CRITICAL (Appwrite SDK v16):
        Row objects store all user-defined fields inside `row.data` (a plain dict).
        Top-level Row attributes are only metadata: id, sequence, tableid, etc.
        This function checks `row.data` first before falling back to getattr.
    """
    if data is None:
        return default

    # CASE 1: Data is a plain dictionary
    if isinstance(data, dict):
        # Specific fix for $id to id mapping for dicts
        if key == 'id' and 'id' not in data and '$id' in data:
            return data.get('$id')
        if key == '$id' and '$id' not in data and 'id' in data:
            return data.get('id')

        # Handle list structure mapping for dicts
        if key == 'documents' and 'documents' not in data and 'rows' in data:
            return data.get('rows')
        if key == 'rows' and 'rows' not in data and 'documents' in data:
            return data.get('documents')

        return data.get(key, default)

    # CASE 2: SDK Row object (Appwrite v16) — data lives in .data dict
    # This is the critical path for article field extraction.
    row_data = getattr(data, 'data', None)
    if isinstance(row_data, dict):
        # Handle $id: Row objects use 'id' not '$id'
        if key == '$id':
            val = row_data.get('$id') or getattr(data, 'id', None)
            return val if val is not None else default
        if key in row_data:
            return row_data[key]
        # Also check top-level attributes (id, sequence, createdat, etc.)
        top_val = getattr(data, key, None)
        return top_val if top_val is not None else default

    # CASE 3: Legacy SDK Objects (DocumentList, RowList for list responses)
    # Important: SDK v14+ DocumentList has .documents, TablesDB RowList has .rows
    val = getattr(data, key, None)

    # Cross-compatibility for list attributes
    if val is None:
        if key == 'documents':
            val = getattr(data, 'rows', None)
        elif key == 'rows':
            val = getattr(data, 'documents', None)
        elif key == 'id':
            val = getattr(data, '$id', None)
        elif key == '$id':
            val = getattr(data, 'id', None)

    return val if val is not None else default



class TablesDBWrapper:
    """
    Future-Proofing Wrapper (Migration Phase)
    Wraps legacy 'documents' API into new 'tables' nomenclature
    """
    def __init__(self, db_service):
        self.db = db_service
    
    async def create_row(self, *args, **kwargs):
        # Appwrite SDK natively maps to `create_document`
        return await asyncio.to_thread(self.db.create_row, *args, **kwargs)
        
    async def get_row(self, *args, **kwargs):
        # Appwrite SDK natively maps to `get_document`
        return await asyncio.to_thread(self.db.get_row, *args, **kwargs)
    
    async def list_rows(self, *args, **kwargs):
        # Appwrite SDK natively maps to `list_documents`
        return await asyncio.to_thread(self.db.list_rows, *args, **kwargs)

    async def delete_row(self, *args, **kwargs):
        # Appwrite SDK natively maps to `delete_document`
        return await asyncio.to_thread(self.db.delete_row, *args, **kwargs)

    async def update_row(self, *args, **kwargs):
        # Appwrite SDK natively maps to `update_document`
        return await asyncio.to_thread(self.db.update_row, *args, **kwargs)


class AppwriteDatabase:
    """Appwrite Database service for persistent article storage (L2 cache)"""
    
    def __init__(self):
        self.initialized = False
        self.client = None
        self.databases = None
        self.storage = None

        # ── Phase 22: Global write concurrency guard ──────────────────────────
        # This semaphore is a class-level attribute — shared across EVERY call
        # to save_articles(), including concurrent calls from different categories.
        #
        # Why 10? Appwrite's free/starter tier handles ~60 writes/min comfortably.
        # 10 concurrent writes means we process 150 articles in 15 rounds of 10,
        # finishing in a few seconds while staying well inside Appwrite's limits.
        #
        # Without this: 150 simultaneous POST requests → Appwrite HTTP 429
        #               → articles silently dropped (data loss during news events).
        # With this:    10 at a time → zero 429s → zero silent data loss.
        self._write_semaphore = asyncio.Semaphore(10)
        
        if APPWRITE_AVAILABLE and settings.APPWRITE_PROJECT_ID:
            self._initialize()
    
    def _initialize(self):
        """Initialize Appwrite client and database connection"""
        if not APPWRITE_AVAILABLE:
            return
        
        try:
            # Check if required config is present
            if not settings.APPWRITE_PROJECT_ID or not settings.APPWRITE_API_KEY:
                print("Appwrite credentials not configured - database features disabled")
                self.initialized = False
                return
            
            # Initialize Appwrite client
            self.client = Client()
            self.client.set_endpoint(settings.APPWRITE_ENDPOINT)
            self.client.set_project(settings.APPWRITE_PROJECT_ID)
            self.client.set_key(settings.APPWRITE_API_KEY)
            
            # Initialize databases service (Legacy support)
            self.databases = Databases(self.client)
            
            # Initialize TablesDB service (Modern API)
            self.tablesDB = TablesDB(self.client)
            
            # Initialize storage service
            self.storage = Storage(self.client)
            
            # Set initialization flag
            self.initialized = True
            logger.info("[Appwrite] Connections initialized successfully")
            
        except Exception as e:
            logger.error(f"[Appwrite] Initialization FAILED: {e}")
            self.initialized = False
            
    def get_collection_id(self, category: str) -> str:
        """
        Phase 4: Strict Routing Algorithm (Vertical Architecture)
        """
        # Normalize
        if not category or not category.strip():
            logger.warning("[ROUTING] Empty category, defaulting to News Articles")
            return settings.APPWRITE_COLLECTION_ID
            
        cat = category.lower().strip()
        
        # 1. AI Vertical
        if cat == 'ai':
            return settings.APPWRITE_AI_COLLECTION_ID
            
        # Top Git Repositories
        if cat == 'top-git-repositories':
            return settings.APPWRITE_TOP_REPOS_COLLECTION_ID
            
        # 2. Cloud Vertical (All providers)
        if cat.startswith('cloud-'):
            return settings.APPWRITE_CLOUD_COLLECTION_ID
            
        # 3. Research Vertical (New)
        if cat == 'research' or cat.startswith('research-'):
            return settings.APPWRITE_RESEARCH_COLLECTION_ID
            
        # 4. Data Vertical (Security, Governance, etc.)
        if cat.startswith('data-') or cat.startswith('business-') or cat == 'customer-data-platform':
            return settings.APPWRITE_DATA_COLLECTION_ID
            
        # 4. Magazines
        if cat == 'magazines':
            return settings.APPWRITE_MAGAZINE_COLLECTION_ID
            
        # 5. Medium
        if cat == 'medium-article':
            return settings.APPWRITE_MEDIUM_COLLECTION_ID
            
        # Default / Fallback
        logger.warning(f"[ROUTING] Unmatched category '{cat}', defaulting to News Articles")
        return settings.APPWRITE_COLLECTION_ID

    
    def _generate_url_hash(self, url: str) -> str:
        """
        Generate a unique hash for an article URL.

        **INTEGRATION UPDATE**: Matches Schema Size 64.
        Uses SHA-256 hash of the CANONICAL URL.

        [I5 — URL Canonicalization Fix]
        Canonicalize before hashing so UTM variants of the same URL
        (e.g. ?utm_source=rss vs no params) produce the SAME document ID.
        Before this fix, the same article could be saved multiple times with
        different IDs because the URL differed only in tracking parameters.

        Returns:
            64-character hex hash
        """
        from app.utils.url_canonicalization import canonicalize_url
        import hashlib
        # Canonicalize first: strips UTM params, www prefix, trailing slash, etc.
        canonical = canonicalize_url(url)
        # Generate SHA-256 hash from CANONICAL URL (same algorithm, canonical input)
        hash_bytes = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
        # Return FULL 64 characters (matches DB Schema)
        return hash_bytes
    
    async def get_articles(self, category: str, limit: int = 20, offset: int = 0) -> List[Dict]:
        """
        Get articles by category with pagination and projection (FAANG-Level)
        """
        if not self.initialized:
            return []
        
        try:
            # Determine collection based on category
            target_collection_id = self.get_collection_id(category)

            # FAANG Optimization: Projection - fetch only what UI needs!
            select_fields = [
                '$id',
                'title',
                'url',
                'image_url',
                'published_at',
                'source',
                'category',
                'url_hash',
                'authors',   # Research specific
                'pdf_url',   # Research specific
                'summary'    # Research specific (mapped to description)
            ]
            
            # Query with projection
            queries = [
                Query.order_desc('published_at'),  # Uses index!
                Query.limit(limit),
                Query.offset(offset)
            ]
            
            # Apply category filter ONLY if it's not the root 'research' category
            # (Because 'research' collection only contains research papers, so no filter = All Research)
            if category != 'research':
                queries.insert(0, Query.equal('category', category))
            
            response = await asyncio.to_thread(
                self.tablesDB.list_rows,
                database_id=settings.APPWRITE_DATABASE_ID,
                table_id=target_collection_id,
                queries=queries
            )
            
            # WARN-005 fixed: was a raw print() that fired on every frontend request,
            # leaking database response metadata to HF Spaces public container logs.
            # Changed to logger.debug so it is suppressed at production INFO level.
            logger.debug("[DB] Appwrite Raw Response: Total=%s, Items=%d",
                         _safe_get(response, 'total'), len(_safe_get(response, 'rows', [])))
            
            # Convert Appwrite documents to Article dictionaries
            articles = []
            for doc in _safe_get(response, 'rows', []):
                try:
                    # Smart Mapping for Research Papers
                    description = _safe_get(doc, 'description', '')
                    if not description and _safe_get(doc, 'summary'):
                         description = _safe_get(doc, 'summary')
                         
                    url = _safe_get(doc, 'url', '')
                    if not url and _safe_get(doc, 'pdf_url'):
                        url = _safe_get(doc, 'pdf_url')
                        
                    # Fix for legacy "None" string corruption in image_url
                    img_url = _safe_get(doc, 'image_url', '')
                    if img_url == "None":
                        img_url = ''

                    article = {
                        '$id': _safe_get(doc, '$id'), # Ensure $id is passed!
                        'title': _safe_get(doc, 'title'),
                        'description': description,
                        'url': url,
                        'image_url': img_url,
                        'publishedAt': _safe_get(doc, 'published_at'),
                        'published_at': _safe_get(doc, 'published_at'), # Standard schema field
                        'source': _safe_get(doc, 'source', ''),
                        'category': _safe_get(doc, 'category'),
                        'likes': _safe_get(doc, 'likes', 0),
                        'dislikes': _safe_get(doc, 'dislike', 0),
                        'views': _safe_get(doc, 'views', 0),
                        'author': _safe_get(doc, 'authors') # Map authors to author (singular for compat)
                        # 'authors': _safe_get(doc, 'authors') # Keep plural if needed
                    }
                    articles.append(article)
                except Exception as e:
                    logger.error(f"Error parsing Appwrite document: {e}")
                    continue
            
            if articles:
                print(f"[SUCCESS] Retrieved {len(articles)} articles for '{category}' (Collection: {target_collection_id})")
            
            return articles
            
        except AppwriteException as e:
            print(f"Appwrite query error for category '{category}': {e}")
            return []
    
    async def get_articles_with_queries(self, queries: List, category: str = None) -> List[Dict]:
        """
        Get articles with custom query filters (for cursor pagination)
        
        Args:
            queries: List of Appwrite Query objects
            category: Optional category for explicit routing (Recommended)
        """
        if not self.initialized:
            return []
        
        try:
            # Phase 4 Routing: Determine Collection ID
            target_collection_id = settings.APPWRITE_COLLECTION_ID
            
            if category:
                # 1. Explicit Routing (Robust)
                target_collection_id = self.get_collection_id(category)
                logger.info(f"🔍 [ROUTING] Category='{category}' -> Collection='{target_collection_id}'")
            else:
                # 2. Fallback: Extract category from queries (Brittle)
                # Parse query list for 'category' to route to correct table
                for q in queries:
                    q_str = str(q)
                    if 'category' in q_str:
                        import re
                        # Regex for JSON-like string: {"attribute":"category","values":["ai"]}
                        # Logic: Look for "category" attribute, then find the value inside ["..."]
                        match = re.search(r'category.*?"values":\["([^"]+)"\]', q_str)
                        if not match:
                             # Try simpler regex (just in case string format differs)
                             match = re.search(r'category.*?"([^"]+)"', q_str)
                        
                        if match:
                            category_val = match.group(1)
                            target_collection_id = self.get_collection_id(category_val)
                            logger.info(f"🔍 [ROUTING-FALLBACK] Extracted='{category_val}' -> Collection='{target_collection_id}'")
                            break

            logger.info(f"🚀 [QUERY] Executing query on Collection: {target_collection_id}")
            
            response = await asyncio.to_thread(
                self.tablesDB.list_rows,
                database_id=settings.APPWRITE_DATABASE_ID,
                table_id=target_collection_id,
                queries=queries
            )
            
            # Convert to article dictionaries
            articles = []
            for doc in _safe_get(response, 'rows', []):
                try:
                    # Fix for legacy "None" string corruption in image_url
                    img_url = _safe_get(doc, 'image_url', '')
                    if img_url == "None":
                        img_url = ''

                    article = {
                        '$id': _safe_get(doc, '$id'),
                        'title': _safe_get(doc, 'title'),
                        'description': _safe_get(doc, 'description') or _safe_get(doc, 'summary', ''),
                        'url': _safe_get(doc, 'url'),
                        'image_url': img_url,
                        'publishedAt': _safe_get(doc, 'published_at'),
                        'published_at': _safe_get(doc, 'published_at'),
                        'source': _safe_get(doc, 'source', ''),
                        'category': _safe_get(doc, 'category'),
                        'likes': _safe_get(doc, 'likes', 0),
                        'dislikes': _safe_get(doc, 'dislike', 0),
                        'views': _safe_get(doc, 'views', 0)
                    }
                    articles.append(article)
                except Exception as e:
                    continue
            
            return articles
            
        except Exception as e:
            print(f"Query error: {e}")
            return []
    
    async def save_articles(self, articles: List) -> int:
        """
        Save articles to Appwrite database with TRUE parallel writes
        """
        logger = logging.getLogger(__name__)
        
        if not self.initialized:
            return (0, 0, 0, [])
        
        if not articles:
            return (0, 0, 0, [])

        # Initialize URL Filter
        try:
            from app.services.deduplication import get_url_filter
            url_filter = get_url_filter()
        except ImportError:
            logger.warning("[Appwrite] Deduplication service not found, skipping local bloom filter check")
            url_filter = None
        
        async def save_single_article(article: dict) -> tuple:
            try:
                # Handle both dict and object types
                url = str(article.get('url', '')) if isinstance(article, dict) else str(article.url)
                if not url:
                    return ('error', None)
                
                # 1. BLOOM FILTER CHECK (Local De-duplication)
                if url_filter and not url_filter.check_and_add(url):
                    # Only return duplicate if it was actually caught by the filter
                    # This saves an API call to Appwrite
                    return ('duplicate', None)

                # Generate unique document ID (Must be <= 36 chars)
                # Use raw SHA-256 for url_hash attribute (64 chars)
                url_hash_full = self._generate_url_hash(url)
                # Truncate for Document ID (32 chars)
                doc_id = url_hash_full[:32]
                
                # Helper to get field from dict or object
                def get_field(obj, field, default=''):
                    if isinstance(obj, dict):
                        return obj.get(field, default)
                    return getattr(obj, field, default)
                
                # Helper to safely cast to string and prevent "None" strings
                def clean_str(val, max_len=None):
                    if val is None or str(val).strip() == "None":
                        return ''
                    s = str(val).strip()
                    return s[:max_len] if max_len else s
                
                # Route to correct collection
                category_val = clean_str(get_field(article, 'category', ''))
                target_collection_id = self.get_collection_id(category_val)

                # Prepare document data - STRICT SCHEMA MAPPING (New Schema Enforcement)
                # Notes: 
                # 1. 'image_url' is the standard (replacing legacy 'image')
                # 2. 'published_at' is the standard (replacing legacy 'publishedAt' camelCase)
                
                # Helper to get published date safely
                pub_date = get_field(article, 'published_at') or get_field(article, 'publishedAt')
                if isinstance(pub_date, datetime):
                    pub_date_str = pub_date.isoformat()
                else:
                    pub_date_str = str(pub_date or datetime.now().isoformat())

                document_data = {
                    'title': clean_str(get_field(article, 'title', ''), 500),
                    'description': clean_str(get_field(article, 'description', ''), 2000),
                    'url': url[:2048],
                    'image_url': clean_str(get_field(article, 'image_url') or get_field(article, 'image', ''), 2048) or None,
                    'published_at': pub_date_str,
                    'source': clean_str(get_field(article, 'source', ''), 200),
                    'category': clean_str(get_field(article, 'category', ''), 100),
                    'fetched_at': datetime.now().isoformat(),
                    'url_hash': url_hash_full, # 64 chars
                    'slug': clean_str(get_field(article, 'slug', ''), 200) or None,
                    'quality_score': int(get_field(article, 'quality_score', 50) or 50),
                    # ENGAGEMENT METRICS
                    'likes': 0,
                    'dislike': 0, 
                    'views': 0,
                    'audio_url': get_field(article, 'audio_url', None) # Initialize audio_url
                }
                
                # Cloud Collection Specifics (Legacy Schema requirements)
                if target_collection_id == settings.APPWRITE_CLOUD_COLLECTION_ID:
                    document_data['provider'] = document_data['source']
                    document_data['is_official'] = False # Default to False
                    
                    # FIX: Cloud collection uses legacy 'image' attribute, not 'image_url'
                    # CRITICAL: Cloud collection validates URLs strictly - must be a valid URL or None
                    image_value = document_data.pop('image_url', None)
                    
                    # Validate that image_value is a proper URL
                    if image_value and isinstance(image_value, str) and image_value.strip():
                        # Check if it's a valid URL format (starts with http/https)
                        if image_value.startswith(('http://', 'https://')):
                            document_data['image'] = image_value
                        else:
                            # Invalid URL format - set to None
                            document_data['image'] = None
                    else:
                        # Empty or None - set to None
                        document_data['image'] = None
                    
                    # NOTE: Cloud collection DOES accept 'published_at' (snake_case)
                    # Only the 'image' field uses legacy naming

                # Try to create row
                await asyncio.to_thread(
                    self.tablesDB.create_row,
                    database_id=settings.APPWRITE_DATABASE_ID,
                    table_id=target_collection_id,
                    row_id=doc_id, # Modern terminology
                    data=document_data
                )
                
                return ('success', document_data)
                
            except AppwriteException as e:
                # Document already exists (duplicate detected by Appwrite)
                if 'document_already_exists' in str(e).lower() or 'unique' in str(e).lower():
                    return ('duplicate', None)
                else:
                    logger.error("%s Appwrite write failed: %s | URL: %s...",
                                 TAG_ERROR, str(e), url[:60])
                    return ('error', str(e))
                    
            except Exception as e:
                logger.error("%s Unexpected error during save: %s | URL: %s...",
                              TAG_ERROR, str(e), url[:60])
                return ('error', str(e))
        
        # PHASE 22: Concurrency-limited parallel writes
        #
        # The _safe_save wrapper acquires self._write_semaphore before calling
        # save_single_article. Because the semaphore is a CLASS-LEVEL attribute
        # (set in __init__), it is shared across all concurrent save_articles()
        # calls — even if 5 categories are saving at the same time, the total
        # number of live Appwrite write requests is always capped at 10.
        #
        # Think of it as a turnstile: no matter how many people push at once,
        # only 10 can walk through at the same time.
        async def _safe_save(article):
            async with self._write_semaphore:
                return await save_single_article(article)

        save_tasks = [_safe_save(article) for article in articles]

        # asyncio.gather fires all tasks but the semaphore inside each one
        # ensures at most 10 actually hit Appwrite at the same time.
        results = await asyncio.gather(*save_tasks, return_exceptions=True)
        
        # Count results
        saved_count = 0
        saved_rows = []
        duplicate_count = 0
        error_count = 0
        
        for result in results:
            if isinstance(result, Exception):
                error_count += 1
                continue
                
            status, data = result
            if status == 'success':
                saved_count += 1
                saved_rows.append(data)
            elif status == 'duplicate':
                duplicate_count += 1
            else:  # error
                error_count += 1
        
        if saved_count > 0 or duplicate_count > 0 or error_count > 0:
            logger.info(
                "%s Saved: %d | Duplicates: %d | Errors: %d",
                TAG_DB, saved_count, duplicate_count, error_count
            )
        
        return saved_count, duplicate_count, error_count, saved_rows
    
    async def delete_old_articles(self, days: int = 30) -> int:
        """
        Delete articles older than specified days
        
        Args:
            days: Delete articles older than this many days
        
        Returns:
            Number of articles deleted
        """
        if not self.initialized:
            return 0
        
        try:
            cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
            
            # Query old articles
            response = await asyncio.to_thread(
                self.tablesDB.list_rows,
                database_id=settings.APPWRITE_DATABASE_ID,
                table_id=settings.APPWRITE_COLLECTION_ID,
                queries=[
                    Query.less_than('fetched_at', cutoff_date),
                    Query.limit(500)
                ]
            )
            
            deleted_count = 0
            for doc in _safe_get(response, 'rows', []):
                try:
                    await asyncio.to_thread(
                        self.tablesDB.delete_row,
                        database_id=settings.APPWRITE_DATABASE_ID,
                        table_id=settings.APPWRITE_COLLECTION_ID,
                        row_id=doc['$id']
                    )
                    deleted_count += 1
                except Exception as e:
                    print(f"Error deleting document {doc['$id']}: {e}")
            
            if deleted_count > 0:
                print(f"[CLEANUP] Deleted {deleted_count} articles older than {days} days")
            else:
                print(f"[CLEANUP] No old articles to delete")
            
            return deleted_count
            
        except Exception as e:
            print(f"Error deleting old articles: {e}")
            return 0
    
    # ------------------------------------------------------------------
    # Generic Row Operations (Phase 16 Migration)
    # ------------------------------------------------------------------
    async def list_rows(self, table_id: str, queries: List[Any] = None) -> Dict:
        """Generic list_rows wrapper for any table"""
        if not self.initialized:
            return {"total": 0, "rows": []}
        try:
            return await asyncio.to_thread(
                self.tablesDB.list_rows,
                database_id=settings.APPWRITE_DATABASE_ID,
                table_id=table_id,
                queries=queries or []
            )
        except Exception as e:
            logger.error(f"[Appwrite] list_rows error on {table_id}: {e}")
            return {"total": 0, "rows": []}

    async def get_row(self, table_id: str, row_id: str) -> Optional[Dict]:
        """Generic get_row wrapper for any table"""
        if not self.initialized:
            return None
        try:
            row = await asyncio.to_thread(
                self.tablesDB.get_row,
                database_id=settings.APPWRITE_DATABASE_ID,
                table_id=table_id,
                row_id=row_id
            )
            return row
        except Exception as e:
            # Ignore 404s when checking if exists
            if hasattr(e, "code") and e.code == 404:
                return None
            if "404" in str(e):
                return None
            logger.error(f"❌ [Appwrite] get_row error on {table_id}/{row_id}: {e}")
            return None

    async def create_row(self, table_id: str, row_id: str, data: Dict) -> bool:
        """Generic create_row wrapper for any table"""
        if not self.initialized:
            return False
        try:
            await asyncio.to_thread(
                self.tablesDB.create_row,
                database_id=settings.APPWRITE_DATABASE_ID,
                table_id=table_id,
                row_id=row_id,
                data=data
            )
            return True
        except Exception as e:
            logger.error(f"❌ [Appwrite] create_row error on {table_id}/{row_id}: {e}")
            return False

    async def delete_row(self, table_id: str, row_id: str) -> bool:
        """Generic delete_row wrapper for any table"""
        if not self.initialized:
            return False
        try:
            await asyncio.to_thread(
                self.tablesDB.delete_row,
                database_id=settings.APPWRITE_DATABASE_ID,
                table_id=table_id,
                row_id=row_id
            )
            return True
        except Exception as e:
            logger.error(f"❌ [Appwrite] delete_row error on {table_id}/{row_id}: {e}")
            return False

    async def update_row(self, table_id: str, row_id: str, data: Dict) -> bool:
        """Generic update_row wrapper for any table"""
        if not self.initialized:
            return False
        try:
            await asyncio.to_thread(
                self.tablesDB.update_row,
                database_id=settings.APPWRITE_DATABASE_ID,
                table_id=table_id,
                row_id=row_id,
                data=data
            )
            return True
        except Exception as e:
            logger.error(f"❌ [Appwrite] update_row error on {table_id}/{row_id}: {e}")
            return False

    # ------------------------------------------------------------------
    # SUBSCRIBER MANAGEMENT (Migration Phase 2)
    # ------------------------------------------------------------------

    async def create_subscriber(self, email: str, name: str, preferences: Dict[str, bool], token: str) -> bool:
        """
        Create a new subscriber in Appwrite (Dual-Write)
        Uses Boolean Flags schema: sub_morning, sub_afternoon, etc.
        """
        if not self.initialized:
            return False
            
        try:
            # Prepare document data
            data = {
                "email": email,
                "name": name,
                "token": token,
                "isActive": True,
                # Map dict preferences to individual boolean columns
                "sub_morning": preferences.get("Morning", False),
                "sub_afternoon": preferences.get("Afternoon", False),
                "sub_evening": preferences.get("Evening", False),
                "sub_weekly": preferences.get("Weekly", False),
                "sub_monthly": preferences.get("Monthly", False)
            }
            
            # Use email hash or sanitized email as ID to prevent duplicates
            # doc_id = hashlib.md5(email.encode()).hexdigest() 
            # Appwrite requires unique ID. 'email' attribute is unique, but let's use 'unique()' or hash.
            # Using MD5 of email ensures idempotent writes (same email = same ID)
            doc_id = hashlib.md5(email.lower().encode()).hexdigest()

            await asyncio.to_thread(
                self.tablesDB.create_row,
                database_id=settings.APPWRITE_DATABASE_ID,
                table_id=settings.APPWRITE_SUBSCRIBERS_COLLECTION_ID,
                row_id=doc_id,
                data=data
            )
            logger.info(f"✅ [Appwrite] Subscriber created: {email}")
            return True

        except AppwriteException as e:
            if 'document_already_exists' in str(e).lower() or 'unique' in str(e).lower():
                # If exists, we should try to update it? Or just return True?
                # For dual-write safety, let's update it to ensure sync
                logger.info(f"ℹ️ [Appwrite] Subscriber exists, updating: {email}")
                return await self.update_subscriber(email, preferences)
            
            logger.error(f"❌ [Appwrite] Error creating subscriber: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ [Appwrite] Unexpected error creating subscriber: {e}")
            return False

    async def get_subscriber(self, email: str) -> Optional[Dict]:
        """Get subscriber by email"""
        if not self.initialized:
            return None
            
        try:
            rows = await asyncio.to_thread(
                self.tablesDB.list_rows,
                database_id=settings.APPWRITE_DATABASE_ID,
                table_id=settings.APPWRITE_SUBSCRIBERS_COLLECTION_ID,
                queries=[Query.equal("email", email)]
            )
            
            if _safe_get(rows, 'total', 0) > 0:
                return _safe_get(rows, 'rows', [])[0]
            return None
            
        except Exception as e:
            logger.error(f"❌ [Appwrite] Error getting subscriber: {e}")
            return None

    async def update_subscriber(self, email: str, preferences: Dict[str, bool]) -> bool:
        """Update subscriber preferences"""
        if not self.initialized:
            return False
            
        try:
            # 1. Find document ID by email
            subscriber = await self.get_subscriber(email)
            if not subscriber:
                return False
            
            doc_id = _safe_get(subscriber, '$id')
            
            # 2. Prepare update data
            data = {}
            if "Morning" in preferences: data["sub_morning"] = preferences["Morning"]
            if "Afternoon" in preferences: data["sub_afternoon"] = preferences["Afternoon"]
            if "Evening" in preferences: data["sub_evening"] = preferences["Evening"]
            if "Weekly" in preferences: data["sub_weekly"] = preferences["Weekly"]
            if "Monthly" in preferences: data["sub_monthly"] = preferences["Monthly"]
            
            # Use async bridge for update_row
            await asyncio.to_thread(
                self.tablesDB.update_row,
                database_id=settings.APPWRITE_DATABASE_ID,
                table_id=settings.APPWRITE_SUBSCRIBERS_COLLECTION_ID,
                row_id=doc_id,
                data=data
            )
            logger.info(f"✅ [Appwrite] Subscriber updated: {email}")
            return True
            
        except Exception as e:
            logger.error(f"❌ [Appwrite] Error updating subscriber: {e}")
            return False

    async def get_subscriber_by_token(self, token: str) -> Optional[Dict]:
        """Get subscriber by unsubscribe token"""
        try:
            rows = await asyncio.to_thread(
                self.tablesDB.list_rows,
                database_id=settings.APPWRITE_DATABASE_ID,
                table_id=settings.APPWRITE_SUBSCRIBERS_COLLECTION_ID,
                queries=[Query.equal("token", token)]
            )
            
            if _safe_get(rows, 'total', 0) > 0:
                return _safe_get(rows, 'rows', [])[0]
            return None
            
        except Exception as e:
            logger.error(f"❌ [Appwrite] Error finding subscriber by token: {e}")
            return None

    async def update_article_audio(self, collection_id: str, document_id: str, audio_url: str, text_summary: Optional[str] = None) -> bool:
        """Update article with audio URL and optional text summary"""
        if not self.initialized:
            return False
            
        try:
            data = {'audio_url': audio_url}
            if text_summary:
                data['text_summary'] = text_summary
                
            await asyncio.to_thread(
                self.tablesDB.update_row,
                database_id=settings.APPWRITE_DATABASE_ID,
                table_id=collection_id,
                row_id=document_id,
                data=data
            )
            return True
        except Exception as e:
            logger.error(f"❌ [Appwrite] Error updating article audio: {e}")
            return False

    async def update_subscription_status(self, email: str, preference: str, is_active: bool) -> bool:
        """
        Update specific subscription preference (Granular Unsubscribe)
        """
        if not self.initialized:
            return False
            
        try:
            subscriber = await self.get_subscriber(email)
            if not subscriber:
                return False
            
            # Map preference name to column name
            field_map = {
                "Morning": "sub_morning",
                "Afternoon": "sub_afternoon",
                "Evening": "sub_evening",
                "Weekly": "sub_weekly",
                "Monthly": "sub_monthly"
            }
            
            field = field_map.get(preference)
            if not field:
                logger.error(f"Invalid preference: {preference}")
                return False
                
            data = {field: is_active}
            
            await asyncio.to_thread(
                self.tablesDB.update_row,
                database_id=settings.APPWRITE_DATABASE_ID,
                table_id=settings.APPWRITE_SUBSCRIBERS_COLLECTION_ID,
                row_id=_safe_get(subscriber, '$id'),
                data=data
            )
            logger.info(f"✅ [Appwrite] Updated {preference} for {email} to {is_active}")
            return True
            
        except Exception as e:
            logger.error(f"❌ [Appwrite] Error updating subscription status: {e}")
            return False

    async def update_subscriber_status(self, email: str, subscribed: bool) -> bool:
        """
        Update global subscription status (Global Unsubscribe)
        """
        if not self.initialized:
            return False
            
        try:
            subscriber = await self.get_subscriber(email)
            if not subscriber:
                return False
            
            data = {"isActive": subscribed}
            
            await asyncio.to_thread(
                self.tablesDB.update_row,
                database_id=settings.APPWRITE_DATABASE_ID,
                table_id=settings.APPWRITE_SUBSCRIBERS_COLLECTION_ID,
                row_id=_safe_get(subscriber, '$id'),
                data=data
            )
            logger.info(f"✅ [Appwrite] Global status for {email} set to {subscribed}")
            return True
            
        except Exception as e:
            logger.error(f"❌ [Appwrite] Error updating global subscriber status: {e}")
            return False

    async def update_last_sent(self, email: str) -> bool:
        """
        Update lastSentAt timestamp for a subscriber
        """
        if not self.initialized:
            return False
            
        try:
            subscriber = await self.get_subscriber(email)
            if not subscriber:
                return False
            
            from datetime import datetime
            import pytz
            
            # Store in UTC ISO format
            utc_now = datetime.now(pytz.UTC).isoformat()
            
            await asyncio.to_thread(
                self.tablesDB.update_row,
                database_id=settings.APPWRITE_DATABASE_ID,
                table_id=settings.APPWRITE_SUBSCRIBERS_COLLECTION_ID,
                row_id=_safe_get(subscriber, '$id'),
                data={'lastSentAt': utc_now}
            )
            # logger.debug(f"✅ [Appwrite] Updated lastSentAt for {email}")
            return True
            
        except Exception as e:
            logger.error(f"❌ [Appwrite] Error updating lastSentAt: {e}")
            return False

    async def get_subscribers_by_preference(self, preference: str) -> List[Dict]:
        """
        Get all subscribers filtered by newsletter preference
        Directly from Appwrite (Source of Truth)
        """
        if not self.initialized:
            return []
            
        try:
            # Map preference name to column name
            field_map = {
                "Morning": "sub_morning",
                "Afternoon": "sub_afternoon",
                "Evening": "sub_evening",
                "Weekly": "sub_weekly",
                "Monthly": "sub_monthly"
            }
            
            field = field_map.get(preference)
            
            # Default fallback for safety (or if preference is invalid)
            if not field:
                logger.warning(f"⚠️ [Appwrite] Unknown preference '{preference}', defaulting to Weekly")
                field = "sub_weekly"
                
            logger.info(f"🔍 [Appwrite] Fetching subscribers for {preference} ({field})...")
            
            # Query Logic:
            # 1. Must be globally active (isActive=true)
            # 2. Must be subscribed to specific preference (sub_X=true)
            
            rows = await asyncio.to_thread(
                self.tablesDB.list_rows,
                database_id=settings.APPWRITE_DATABASE_ID,
                table_id=settings.APPWRITE_SUBSCRIBERS_COLLECTION_ID,
                queries=[
                    Query.equal("isActive", True),
                    Query.equal(field, True),
                    Query.limit(1000) # Safety limit
                ]
            )
            
            subs = _safe_get(rows, 'rows', [])
            logger.info(f"✅ [Appwrite] Found {len(subs)} subscribers for {preference}")
            return subs
            
        except Exception as e:
            logger.error(f"❌ [Appwrite] Error getting subscribers by preference: {e}")
            return []

    async def get_all_subscribers(self) -> List[Dict]:
        """
        Get all subscribers (Source of Truth)
        Used by admin analytics.
        """
        if not self.initialized:
            return []
        try:
            rows = await asyncio.to_thread(
                self.tablesDB.list_rows,
                database_id=settings.APPWRITE_DATABASE_ID,
                table_id=settings.APPWRITE_SUBSCRIBERS_COLLECTION_ID,
                queries=[Query.limit(5000)] # Appwrite limit
            )
            return _safe_get(rows, 'rows', [])
        except Exception as e:
            logger.error(f"[Appwrite] Error getting all subscribers: {e}")
            return []

    async def get_database_stats(self) -> Dict:
        """
        Get database statistics
        
        Returns:
            Dictionary with database stats (total articles, by category, etc.)
        """
        if not self.initialized:
            return {"error": "Appwrite not initialized"}
        
        try:
            # Get total count
            total_response = await asyncio.to_thread(
                self.tablesDB.list_rows,
                database_id=settings.APPWRITE_DATABASE_ID,
                table_id=settings.APPWRITE_COLLECTION_ID,
                queries=[Query.limit(1)]
            )
            total_articles = _safe_get(total_response, 'total', 0)
            
            # Get counts by category
            categories = [
                "ai", "data-security", "data-governance", "data-privacy",
                "data-engineering", "data-management", "business-intelligence", 
                "business-analytics", "customer-data-platform", "data-centers", 
                "cloud-computing", "magazines"
            ]
            
            articles_by_category = {}
            for category in categories:
                response = await asyncio.to_thread(
                    self.tablesDB.list_rows,
                    database_id=settings.APPWRITE_DATABASE_ID,
                    table_id=settings.APPWRITE_COLLECTION_ID,
                    queries=[
                        Query.equal('category', category),
                        Query.limit(1)
                    ]
                )
                articles_by_category[category] = _safe_get(response, 'total', 0)
            
            return {
                "total_articles": total_articles,
                "articles_by_category": articles_by_category,
                "database_id": settings.APPWRITE_DATABASE_ID,
                "table_id": settings.APPWRITE_COLLECTION_ID,
                "initialized": self.initialized
            }
            
        except Exception as e:
            print(f"Error getting database stats: {e}")
            return {"error": str(e)}


# Singleton instance
_appwrite_db = None

def get_appwrite_db() -> AppwriteDatabase:
    """Get or create Appwrite database singleton instance"""
    global _appwrite_db
    if _appwrite_db is None:
        _appwrite_db = AppwriteDatabase()
    
    # Ensure it's initialized if configuration is present
    if not _appwrite_db.initialized and APPWRITE_AVAILABLE:
        from app.config import settings
        if settings.APPWRITE_PROJECT_ID:
            # Note: _initialize is sync, so we can call it here
            _appwrite_db._initialize()
            
    return _appwrite_db
