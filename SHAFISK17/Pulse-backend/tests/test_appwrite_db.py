import pytest
from app.services.appwrite_db import AppwriteDatabase
from app.config import settings

def test_get_collection_id_routing():
    db = AppwriteDatabase()
    
    # 1. Existing mappings
    assert db.get_collection_id("ai") == settings.APPWRITE_AI_COLLECTION_ID
    assert db.get_collection_id("cloud-aws") == settings.APPWRITE_CLOUD_COLLECTION_ID
    assert db.get_collection_id("research-papers") == settings.APPWRITE_RESEARCH_COLLECTION_ID
    
    # 2. New mapping for top-git-repositories
    assert db.get_collection_id("top-git-repositories") == settings.APPWRITE_TOP_REPOS_COLLECTION_ID
    
    # 3. Fallback routing
    assert db.get_collection_id("unknown-category") == settings.APPWRITE_COLLECTION_ID
