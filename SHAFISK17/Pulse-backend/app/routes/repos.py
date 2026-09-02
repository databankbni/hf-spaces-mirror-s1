from fastapi import APIRouter, HTTPException
from app.models import ReposResponse, Repo
from app.services.appwrite_db import get_appwrite_db, _safe_get
from app.config import settings
import logging

logger = logging.getLogger(__name__)

router = APIRouter()
appwrite_db = get_appwrite_db()

@router.get("/top", response_model=ReposResponse)
async def get_top_repos():
    """
    Get top GitHub repositories sorted by stars descending.
    Always queries Appwrite directly for v1 (no caching, no pagination).
    """
    try:
        from appwrite.query import Query
        
        queries = [
            Query.limit(5000),
            Query.order_desc("stars")
        ]
        
        response = await appwrite_db.list_rows(
            table_id=settings.APPWRITE_TOP_REPOS_COLLECTION_ID,
            queries=queries
        )
        
        raw_docs = _safe_get(response, "rows", [])
        
        repos = []
        for doc in raw_docs:
            try:
                # Appwrite v16 stores actual document payload in .data
                if hasattr(doc, 'data') and isinstance(doc.data, dict):
                    doc_copy = dict(doc.data)
                    doc_copy['id'] = getattr(doc, 'id', _safe_get(doc, '$id'))
                else:
                    doc_copy = dict(doc) if isinstance(doc, dict) else {k: getattr(doc, k) for k in dir(doc) if not k.startswith('_')}
                    doc_id = _safe_get(doc, '$id')
                    if doc_id:
                        doc_copy['id'] = doc_id
                        
                # Ensure validation alias works if backend returns '$id' instead of 'id'
                if '$id' not in doc_copy and 'id' in doc_copy:
                    doc_copy['$id'] = doc_copy['id']
                    
                repo = Repo(**doc_copy)
                repos.append(repo)
            except Exception as e:
                logger.error(f"Error parsing repo doc {_safe_get(doc, '$id')}: {e}")
                
        # Per spec: Sort manually just in case DB doesn't, but Appwrite Query handles it.
        # We ensure they are sorted by stars descending.
        repos.sort(key=lambda r: r.stars, reverse=True)
                
        return ReposResponse(
            success=True,
            count=len(repos),
            repos=repos,
            cached=False,
            source="appwrite"
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error(f"Error fetching top repos: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
