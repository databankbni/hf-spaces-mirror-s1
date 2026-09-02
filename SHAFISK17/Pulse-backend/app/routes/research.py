
from fastapi import APIRouter, HTTPException
from typing import Dict, Any, Optional
from app.services.appwrite_db import get_appwrite_db
from app.config import settings
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/{paper_id}")
async def get_research_paper(paper_id: str):
    """
    Get a single research paper by ID.
    """
    try:
        appwrite_db = get_appwrite_db()
        
        # Try to find by ID in research collection
        try:
            doc = await appwrite_db.tablesDB.get_row(
                database_id=settings.APPWRITE_DATABASE_ID,
                collection_id=settings.APPWRITE_RESEARCH_COLLECTION_ID,
                document_id=paper_id
            )
            
            # Helper to map fields
            if doc:
                return {
                    "success": True,
                    "paper": {
                        "$id": doc.get('$id'),
                        "title": doc.get('title'),
                        "summary": doc.get('summary'),
                        "authors": doc.get('authors'),
                        "published_at": doc.get('published_at'),
                        "pdf_url": doc.get('pdf_url'),
                        "category": doc.get('category'),
                        "likes": doc.get('likes', 0),
                        "views": doc.get('views', 0),
                        "text_summary": doc.get('summary'), # Compat
                        "description": doc.get('summary'), # Compat
                        "url": doc.get('pdf_url'), # Compat
                        "image_url": doc.get('image_url'),
                        "id": doc.get('$id'), # Compat
                        "source": "ArXiv"
                    }
                }
        except Exception as e:
            logger.warning(f"Paper {paper_id} not found: {e}")
            pass

        raise HTTPException(status_code=404, detail="Research paper not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching paper {paper_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
