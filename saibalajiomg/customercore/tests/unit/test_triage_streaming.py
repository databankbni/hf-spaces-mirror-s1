import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from src.streaming.producer_helper import publish_ticket_event
from fastapi import BackgroundTasks
from src.api.routers.triage import submit_ticket
from src.api.models import TicketSubmitRequest, CustomerTier, TicketChannel

class TestProducerHelper:
    @patch("socket.create_connection")
    @patch("src.streaming.producer_helper.Producer")
    def test_get_producer_initializes_once(self, mock_producer_cls, mock_create_connection):
        # Reset singleton just for this test
        import src.streaming.producer_helper as ph
        ph._PRODUCER = None
        
        prod1 = ph.get_producer()
        prod2 = ph.get_producer()
        
        assert prod1 is prod2
        mock_producer_cls.assert_called_once()

    @patch("src.streaming.producer_helper.get_producer")
    def test_publish_ticket_event_offline_fails_gracefully(self, mock_get_producer):
        mock_get_producer.return_value = None
        
        res = publish_ticket_event(
            ticket_id="tkt-123",
            tenant_id="tenant-123",
            customer_id="cust-123",
            customer_tier="enterprise",
            channel="web",
            text="This is a test ticket."
        )
        assert res is False

    @patch("src.streaming.producer_helper.get_producer")
    def test_publish_ticket_event_online_produces_message(self, mock_get_producer):
        mock_prod = MagicMock()
        mock_get_producer.return_value = mock_prod
        
        res = publish_ticket_event(
            ticket_id="tkt-123",
            tenant_id="tenant-123",
            customer_id="cust-123",
            customer_tier="enterprise",
            channel="web",
            text="This is a test ticket."
        )
        assert res is True
        mock_prod.produce.assert_called_once()
        mock_prod.poll.assert_called_once_with(0)

class TestAPIStreamingIntegration:
    @patch("src.streaming.producer_helper.publish_ticket_event")
    @patch("src.api.routers.triage.TicketRepository")
    @pytest.mark.asyncio
    async def test_submit_ticket_streaming_skips_background_task(self, mock_repo_cls, mock_publish):
        # Mock repository
        mock_repo = MagicMock()
        mock_repo.create = AsyncMock(return_value={})
        mock_repo.write_audit = AsyncMock()
        mock_repo_cls.return_value = mock_repo
        
        # Redpanda is online
        mock_publish.return_value = True
        
        body = TicketSubmitRequest(
            text="Test ticket message which is long enough",
            customer_id="cust-1",
            customer_tier=CustomerTier.ENTERPRISE,
            channel=TicketChannel.API
        )
        
        background_tasks = MagicMock(spec=BackgroundTasks)
        
        from src.api.auth import AuthenticatedTenant
        caller = AuthenticatedTenant(tenant_id="a0000000-0000-0000-0000-000000000001", role="support_agent", claims={})
        
        resp = await submit_ticket(body, background_tasks, caller)
        
        # Verify it was published to Redpanda
        mock_publish.assert_called_once()
        # Verify background_tasks was NOT scheduled
        background_tasks.add_task.assert_not_called()
        assert resp.status.value == "pending"

    @patch("src.streaming.producer_helper.publish_ticket_event")
    @patch("src.api.routers.triage.TicketRepository")
    @pytest.mark.asyncio
    async def test_submit_ticket_fallback_runs_background_task(self, mock_repo_cls, mock_publish):
        # Mock repository
        mock_repo = MagicMock()
        mock_repo.create = AsyncMock(return_value={})
        mock_repo.write_audit = AsyncMock()
        mock_repo_cls.return_value = mock_repo
        
        # Redpanda is offline
        mock_publish.return_value = False
        
        body = TicketSubmitRequest(
            text="Test ticket message which is long enough",
            customer_id="cust-1",
            customer_tier=CustomerTier.ENTERPRISE,
            channel=TicketChannel.API
        )
        
        background_tasks = MagicMock(spec=BackgroundTasks)
        
        from src.api.auth import AuthenticatedTenant
        caller = AuthenticatedTenant(tenant_id="a0000000-0000-0000-0000-000000000001", role="support_agent", claims={})
        
        resp = await submit_ticket(body, background_tasks, caller)
        
        # Verify it attempted to publish
        mock_publish.assert_called_once()
        # Verify background_tasks WAS scheduled as fallback
        background_tasks.add_task.assert_called_once()
        assert resp.status.value == "pending"
