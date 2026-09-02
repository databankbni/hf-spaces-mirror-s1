import pytest
from unittest.mock import AsyncMock, patch
from app.utils.data_validation import is_relevant_to_category
from app.services.ingestion_metrics import IngestionMetrics, get_ingestion_metrics
from app.services.news_processor import process_category

class TestQualityScoreRescue:
    def test_regex_fail_high_quality_rescued(self):
        # A completely irrelevant title/description (regex fail)
        # But has image, long description, and premium source (quality >= 65)
        article = {
            "title": "Baking the perfect sourdough bread at home",
            "description": "This is a very long description about baking bread that goes on and on to ensure it passes the 100 character mark for a good description. Sourdough requires patience and a good starter.",
            "url": "https://techcrunch.com/baking-bread",
            "image_url": "https://example.com/bread.jpg",
            "source": "TechCrunch"
        }
        # Should be rescued due to high quality score
        assert is_relevant_to_category(article, "ai") is True

    def test_regex_fail_low_quality_rejected(self):
        # A completely irrelevant title/description (regex fail)
        # Missing image, short description, unknown source (quality < 65)
        article = {
            "title": "Baking the perfect sourdough bread",
            "description": "Short description.",
            "url": "https://example.com/baking-bread",
            "source": "Unknown Blog"
        }
        # Should NOT be rescued
        assert is_relevant_to_category(article, "ai") is False

    def test_regex_pass_any_quality_accepted(self):
        # A highly relevant title (regex pass for 'ai' category)
        # But terrible quality (no image, short desc, no premium source)
        article = {
            "title": "New artificial intelligence model released",
            "description": "Short.",
            "url": "https://example.com/ai",
            "source": "Unknown Blog"
        }
        assert is_relevant_to_category(article, "ai") is True


class TestIngestionMetrics:
    def test_record_run_tracks_irrelevant_count(self):
        metrics = IngestionMetrics()
        
        # Will raise TypeError because irrelevant is not a valid parameter yet (RED)
        metrics.record_run(fetched=100, saved=90, duplicates=0, errors=0, categories_processed=1, irrelevant=10)
        
        stats = metrics.get_stats()
        
        # 1. Check lifetime totals
        assert stats['lifetime_totals']['irrelevant_count'] == 10
        
        # 2. Check recent runs
        latest_run = stats['recent_runs'][0]
        assert latest_run['irrelevant_count'] == 10
        assert latest_run['irrelevant_rate_approx'] == 10.0
        
        # 3. Check averages
        assert stats['averages']['avg_irrelevant_rate_approx'] == 10.0


class TestNewsProcessorMetrics:
    @pytest.mark.asyncio
    async def test_process_category_records_irrelevant_count(self):
        # Reset the metrics singleton for a clean test
        metrics = get_ingestion_metrics()
        metrics.runs = []
        metrics.total_fetched = 0
        metrics.total_saved = 0
        metrics.total_duplicates = 0
        metrics.total_errors = 0
        metrics.total_irrelevant = 0
        
        # Tuple format: category, articles, invalid_count, irrelevant_count, relevant_count
        mock_result = ("ai", [], 5, 42, 0)
        
        with patch('app.services.news_processor.get_adaptive_scheduler', return_value=None):
            with patch('app.services.scheduler.fetch_and_validate_category', new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = mock_result
                
                await process_category("ai", AsyncMock())
                
                stats = metrics.get_stats()
                
                # Ticket 3 RED test: check that irrelevant count was wired through
                assert stats['lifetime_totals']['irrelevant_count'] == 42
                # Check fetched_approx calculation: len(articles)(0) + invalid(5) + irrelevant(42) = 47
                assert stats['lifetime_totals']['fetched'] == 47
