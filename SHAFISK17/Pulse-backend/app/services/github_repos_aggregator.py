import logging
import httpx
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# Heuristic list of keywords to filter out curated content like awesome-lists and roadmaps.
EXCLUDED_KEYWORDS = [
    "awesome-list", 
    "roadmap", 
    "interview", 
    "resources", 
    "books", 
    "free-"
]

MIN_STARS_THRESHOLD: int = 100000

class GithubReposAggregator:
    """
    Fetches the top starred repositories from GitHub.
    Filters out curated-content repos to keep only actual software.
    """
    
    def __init__(self):
        self.api_url = "https://api.github.com/search/repositories"

    async def fetch_and_filter_top_repos(self) -> List[Dict[str, Any]]:
        """
        Fetches the top repos and applies software-only filtering.
        Returns a raw list of repository dictionaries.
        """
        logger.info(f"🔍 [GITHUB AGGREGATOR] Fetching repos with >{MIN_STARS_THRESHOLD} stars...")
        
        params = {
            "q": f"stars:>{MIN_STARS_THRESHOLD}",
            "sort": "stars",
            "order": "desc",
            "per_page": 100
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    self.api_url, 
                    params=params,
                    headers={"Accept": "application/vnd.github.v3+json"}
                )
                response.raise_for_status()
                data = response.json()
        except Exception as e:
            logger.error(f"❌ Error fetching from GitHub: {e}")
            return []
            
        items = data.get("items", [])
        logger.info(f"   Found {len(items)} total repos from GitHub API.")
        
        filtered_repos = []
        for repo in items:
            if self._is_software_repo(repo):
                filtered_repos.append(repo)
                
        logger.info(f"✅ [GITHUB AGGREGATOR] Completed. Kept {len(filtered_repos)} software repos.")
        return filtered_repos

    def _is_software_repo(self, repo: Dict[str, Any]) -> bool:
        """
        Applies a software-only heuristic.
        Excludes repos whose name, description, or topics contain curated-content keywords.
        """
        name = (repo.get("name") or "").lower()
        description = (repo.get("description") or "").lower()
        topics = [t.lower() for t in repo.get("topics", [])]
        
        # Combine all searchable text
        search_text = f"{name} {description} {' '.join(topics)}"
        
        for keyword in EXCLUDED_KEYWORDS:
            if keyword in search_text:
                logger.debug(f"   ⏭️  Skipping non-software repo: {name} (Matched: {keyword})")
                return False
                
        return True

    async def run(self) -> Dict[str, Any]:
        """
        Coordinates fetch, deviation-guard, and upsert of top git repositories.
        """
        from app.services.appwrite_db import AppwriteDatabase
        from app.utils.id_generator import generate_article_id
        from datetime import datetime
        try:
            from appwrite.query import Query
        except ImportError:
            # Fallback for mocked environments where Appwrite SDK is not installed
            Query = None
            
        from app.config import settings
        COLLECTION_ID = settings.APPWRITE_TOP_REPOS_COLLECTION_ID
        db = AppwriteDatabase()
        
        # 1. Deviation Guard: Get previous count
        # In a real environment, this lists the total rows.
        from app.services.appwrite_db import _safe_get
        prev_response = await db.list_rows(table_id=COLLECTION_ID)
        prev_count = _safe_get(prev_response, "total", 0)
        
        # 2. Fetch fresh data
        fresh_repos = await self.fetch_and_filter_top_repos()
        fresh_count = len(fresh_repos)
        
        # 3. Check Deviation
        if prev_count > 0:
            drop_percentage = (prev_count - fresh_count) / prev_count
            if drop_percentage > 0.20:
                logger.warning(
                    f"⚠️ [GITHUB AGGREGATOR] Deviation Guard Triggered! "
                    f"Previous count: {prev_count}, Fresh count: {fresh_count} (Drop > 20%). Aborting sync."
                )
                return {"status": "aborted", "reason": "deviation_guard_triggered", "fetched": fresh_count}
                
        # 4. Upsert
        saved = 0
        updated = 0
        errors = 0
        
        for repo in fresh_repos:
            url = repo.get("html_url")
            if not url:
                continue
                
            doc_id = generate_article_id(url)
            
            existing = await db.get_row(table_id=COLLECTION_ID, row_id=doc_id)
            
            if existing is not None:
                # UPDATING existing (Do NOT include likes, dislike, views)
                update_data = {
                    "stars": repo.get("stargazers_count", 0),
                    "forks": repo.get("forks_count", 0),
                    "language": repo.get("language") or "",
                    "description": repo.get("description") or "",
                    "last_synced_at": datetime.now().isoformat()
                }
                success = await db.update_row(table_id=COLLECTION_ID, row_id=doc_id, data=update_data)
                if success:
                    updated += 1
                else:
                    errors += 1
            else:
                # CREATING new (Include default engagement metrics)
                owner = repo.get("owner", {}).get("login", "") if isinstance(repo.get("owner"), dict) else ""
                create_data = {
                    "name": repo.get("name") or "",
                    "owner": owner,
                    "repo_url": url,
                    "description": repo.get("description") or "",
                    "stars": repo.get("stargazers_count", 0),
                    "forks": repo.get("forks_count", 0),
                    "language": repo.get("language") or "",
                    "likes": 0,
                    "dislike": 0,
                    "views": 0,
                    "last_synced_at": datetime.now().isoformat()
                }
                success = await db.create_row(table_id=COLLECTION_ID, row_id=doc_id, data=create_data)
                if success:
                    saved += 1
                else:
                    errors += 1
                    
        logger.info(f"✅ [GITHUB AGGREGATOR] Sync Complete. Created: {saved}, Updated: {updated}, Errors: {errors}")
        return {
            "status": "success", 
            "fetched": fresh_count, 
            "created": saved, 
            "updated": updated, 
            "errors": errors
        }
