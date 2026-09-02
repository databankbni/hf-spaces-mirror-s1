import asyncio
from app.services.appwrite_db import AppwriteDatabase, _safe_get
from app.config import settings
from appwrite.query import Query

async def test_appwrite():
    db = AppwriteDatabase()
    print(f"Initialized: {db.initialized}")
    table_id = settings.APPWRITE_TOP_REPOS_COLLECTION_ID
    print(f"Table ID: {table_id}")
    
    # 1. Test list_rows with no queries
    res = await db.list_rows(table_id)
    total1 = _safe_get(res, "total", 0)
    rows1 = _safe_get(res, "rows", [])
    print(f"list_rows (no queries): total={total1}, rows count={len(rows1)}")
    
    # 2. Test list_rows with limit
    try:
        res2 = await db.list_rows(table_id, queries=[Query.limit(100)])
        total2 = _safe_get(res2, "total", 0)
        rows2 = _safe_get(res2, "rows", [])
        print(f"list_rows (with limit): total={total2}, rows count={len(rows2)}")
    except Exception as e:
        print(f"list_rows (with limit) error: {e}")

if __name__ == "__main__":
    asyncio.run(test_appwrite())
