import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock
import app.main

@pytest.fixture
def app():
    from app.main import app as main_app
    return main_app

@pytest.mark.asyncio
@patch("app.routes.repos.appwrite_db")
async def test_get_top_repos_empty(mock_db, app):
    """Test the empty table case returns cleanly."""
    mock_db.list_rows = AsyncMock(return_value={"total": 0, "rows": []})
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/repos/top")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["count"] == 0
    assert data["repos"] == []
    assert data["cached"] is False
    assert data["source"] == "appwrite"

@pytest.mark.asyncio
@patch("app.routes.repos.appwrite_db")
async def test_get_top_repos_success_and_sort(mock_db, app):
    """Test successful data fetch, correctly mapped aliases, and sorted order."""
    mock_db.list_rows = AsyncMock(return_value={
        "total": 2,
        "rows": [
            {
                "$id": "repo2",
                "name": "Repo 2",
                "owner": "owner2",
                "repo_url": "https://github.com/owner2/repo2",
                "description": "desc2",
                "language": "Go",
                "stars": 150000,
                "forks": 10000,
                "likes": 5,
                "dislike": 1,
                "views": 20
            },
            {
                "$id": "repo1",
                "name": "Repo 1",
                "owner": "owner1",
                "repo_url": "https://github.com/owner1/repo1",
                "description": "desc1",
                "language": "Python",
                "stars": 200000,
                "forks": 20000,
                "likes": 10,
                "dislike": 2,
                "views": 100
            }
        ]
    })
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/repos/top")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["count"] == 2
    assert data["cached"] is False
    assert data["source"] == "appwrite"
    
    repos = data["repos"]
    assert len(repos) == 2
    
    # Assert sorted by stars DESC
    assert repos[0]["stars"] == 200000
    assert repos[1]["stars"] == 150000
    
    # Assert alias resolution: DB 'dislike' -> Response 'dislikes'
    assert "dislikes" in repos[0]
    assert "dislike" not in repos[0]
    assert repos[0]["dislikes"] == 2
    assert repos[0]["likes"] == 10
    
    assert repos[1]["dislikes"] == 1
