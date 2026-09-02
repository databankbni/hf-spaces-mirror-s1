import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.github_repos_aggregator import GithubReposAggregator, EXCLUDED_KEYWORDS

# Mock current time to avoid datetime issues in tests
from datetime import datetime

class TestGithubReposAggregator:
    @pytest.mark.asyncio
    async def test_fetch_and_filter_repos_removes_curated_content(self):
        mock_data = {
            "items": [
                {
                    "name": "fastapi",
                    "description": "FastAPI framework, high performance",
                    "stargazers_count": 120000,
                    "topics": ["python", "api", "framework"]
                },
                {
                    "name": "awesome-python",
                    "description": "A curated list of awesome Python frameworks, libraries and software",
                    "stargazers_count": 200000,
                    "topics": ["python", "awesome-list", "curated"]
                },
                {
                    "name": "developer-roadmap",
                    "description": "Roadmap to becoming a web developer in 2024",
                    "stargazers_count": 250000,
                    "topics": ["roadmap", "guide", "education"]
                },
                {
                    "name": "react",
                    "description": "A declarative, efficient, and flexible JavaScript library for building user interfaces.",
                    "stargazers_count": 210000,
                    "topics": ["javascript", "ui", "library"]
                }
            ]
        }
        
        aggregator = GithubReposAggregator()
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_data
        
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            
            repos = await aggregator.fetch_and_filter_top_repos()
            
            # Should keep fastapi and react, filter out awesome-python and developer-roadmap
            assert len(repos) == 2
            assert repos[0]["name"] == "fastapi"
            assert repos[1]["name"] == "react"

    @pytest.mark.asyncio
    async def test_fetch_and_filter_repos_empty_results(self):
        aggregator = GithubReposAggregator()
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"items": []}

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            
            repos = await aggregator.fetch_and_filter_top_repos()
            
            assert repos == []
            assert len(repos) == 0

    @pytest.mark.asyncio
    async def test_fetch_and_filter_repos_api_error_returns_empty(self):
        aggregator = GithubReposAggregator()
        
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.raise_for_status.side_effect = Exception("API rate limit")
        
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            
            repos = await aggregator.fetch_and_filter_top_repos()
            
            assert repos == []

class TestGithubReposAggregatorPersistence:
    @pytest.mark.asyncio
    @patch("app.services.appwrite_db.AppwriteDatabase")
    @patch("app.services.github_repos_aggregator.GithubReposAggregator.fetch_and_filter_top_repos")
    async def test_engagement_preservation_on_update(self, mock_fetch, MockDB):
        """
        Critical Test: Ensure likes, dislike, and views are not overwritten when updating an existing row.
        """
        # 1. Setup Mock DB instance
        mock_db_instance = AsyncMock()
        MockDB.return_value = mock_db_instance
        
        # 2. Mock previously stored row count for deviation guard (assume 1 row existed yesterday)
        mock_db_instance.list_rows.return_value = {"total": 1, "rows": []}
        
        # Mock existence check to return an existing row
        mock_db_instance.get_row.return_value = {"$id": "existing-id", "likes": 42, "dislike": 3, "views": 500, "url": "https://github.com/test/repo"}
        
        # 3. Mock the new data fetched from GitHub
        mock_fetch.return_value = [
            {
                "html_url": "https://github.com/test/repo",
                "name": "repo",
                "description": "updated description",
                "stargazers_count": 150000,
                "forks_count": 20000,
                "language": "Python"
            }
        ]
        
        aggregator = GithubReposAggregator()
        await aggregator.run()
        
        # 4. Verify that update_row was called (not create_row)
        assert mock_db_instance.update_row.call_count == 1
        assert mock_db_instance.create_row.call_count == 0
        
        # 5. Assert the payload sent to update_row does NOT contain engagement fields
        args, kwargs = mock_db_instance.update_row.call_args
        update_data = kwargs.get("data", args[2] if len(args) > 2 else {})
        
        assert "stars" in update_data
        assert update_data["stars"] == 150000
        
        # CRITICAL ASSERTIONS
        assert "likes" not in update_data
        assert "dislike" not in update_data
        assert "views" not in update_data

    @pytest.mark.asyncio
    @patch("app.services.appwrite_db.AppwriteDatabase")
    @patch("app.services.github_repos_aggregator.GithubReposAggregator.fetch_and_filter_top_repos")
    async def test_new_row_default_engagement(self, mock_fetch, MockDB):
        """
        Test that new rows are created with default engagement metrics (0).
        """
        mock_db_instance = AsyncMock()
        MockDB.return_value = mock_db_instance
        
        mock_db_instance.list_rows.return_value = {"total": 0, "rows": []}  # Deviation check: 0 existing
        mock_db_instance.get_row.return_value = None  # Check if doc exists: not found
        
        mock_fetch.return_value = [
            {
                "html_url": "https://github.com/new/repo",
                "name": "repo",
                "description": "new repo",
                "stargazers_count": 120000,
                "forks_count": 10000,
                "language": "Go"
            }
        ]
        
        aggregator = GithubReposAggregator()
        await aggregator.run()
        
        assert mock_db_instance.create_row.call_count == 1
        assert mock_db_instance.update_row.call_count == 0
        
        args, kwargs = mock_db_instance.create_row.call_args
        create_data = kwargs.get("data", args[3] if len(args) > 3 else {})
        
        # Should contain default engagement metrics
        assert create_data["likes"] == 0
        assert create_data["dislike"] == 0
        assert create_data["views"] == 0
        assert create_data["stars"] == 120000

    @pytest.mark.asyncio
    @patch("app.services.appwrite_db.AppwriteDatabase")
    @patch("app.services.github_repos_aggregator.GithubReposAggregator.fetch_and_filter_top_repos")
    async def test_deviation_guard_prevents_write(self, mock_fetch, MockDB):
        """
        Test that an unexpected drop in fetch count aborts the save process.
        """
        mock_db_instance = AsyncMock()
        MockDB.return_value = mock_db_instance
        
        # Assume there were 100 rows yesterday
        mock_db_instance.list_rows.return_value = {"total": 100, "rows": []}
        
        # But today we only fetched 70 (a 30% drop, which is > 20%)
        mock_fetch.return_value = [{"html_url": f"url{i}"} for i in range(70)]
        
        aggregator = GithubReposAggregator()
        await aggregator.run()
        
        # Guard should have triggered, so no reads or writes for individual rows
        # (list_rows is called once for the guard)
        assert mock_db_instance.list_rows.call_count == 1
        assert mock_db_instance.create_row.call_count == 0
        assert mock_db_instance.update_row.call_count == 0

    @pytest.mark.asyncio
    @patch("app.services.appwrite_db.AppwriteDatabase")
    @patch("app.services.github_repos_aggregator.GithubReposAggregator.fetch_and_filter_top_repos")
    async def test_normal_case_proceeds(self, mock_fetch, MockDB):
        """
        Test that a safe count (e.g. slight drop < 20% or increase) allows writes.
        """
        mock_db_instance = AsyncMock()
        MockDB.return_value = mock_db_instance
        
        # 100 rows yesterday for deviation guard
        mock_db_instance.list_rows.return_value = {"total": 100, "rows": []}
        
        # New repos: they don't exist yet
        mock_db_instance.get_row.return_value = None
        
        # 90 fetched today (only 10% drop, safe)
        mock_fetch.return_value = [
            {"html_url": f"https://github.com/repo/{i}", "stargazers_count": 100000 + i} 
            for i in range(90)
        ]
        
        aggregator = GithubReposAggregator()
        await aggregator.run()
        
        # Should have called create_row for each item
        assert mock_db_instance.create_row.call_count == 90
