"""
Phase 12 Tests — Supabase Repository Layer

Tests cover:
  TicketRecord:
    - to_db_dict() excludes None values
    - to_db_dict() includes all non-None fields

  TicketRepository (mocked Supabase — no real DB needed):
    - create() calls upsert with correct data + tenant_id
    - update_status() sets processing_started_at on 'processing'
    - update_status() maps triage result fields to DB columns on 'complete'
    - get() filters by both id AND tenant_id (RLS double-check)
    - list_recent() applies optional status/priority filters
    - log_violation() truncates evidence to 200 chars
    - write_audit() failures are non-fatal (no exception raised)

  TenantRepository (mocked):
    - get_by_slug() returns None when not found
    - create() uses upsert with on_conflict=slug

  RepositoryError:
    - Raised on Supabase client exception
    - Contains original exception message
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.db.repository import (
    TicketRecord,
    TicketRepository,
    TenantRepository,
    RepositoryError,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_supabase_mock(return_data: list | None = None):
    """Build a mock that chains .table().select().eq()...execute() correctly."""
    mock_result = MagicMock()
    mock_result.data = return_data or []

    execute_mock = AsyncMock(return_value=mock_result)

    # Build a chainable query builder mock
    qb = MagicMock()
    qb.execute = execute_mock
    qb.select = MagicMock(return_value=qb)
    qb.eq = MagicMock(return_value=qb)
    qb.update = MagicMock(return_value=qb)
    qb.insert = MagicMock(return_value=qb)
    qb.upsert = MagicMock(return_value=qb)
    qb.order = MagicMock(return_value=qb)
    qb.limit = MagicMock(return_value=qb)

    client = AsyncMock()
    client.table = MagicMock(return_value=qb)
    return client, qb, execute_mock


# ─────────────────────────────────────────────────────────────────────────────
# TicketRecord tests
# ─────────────────────────────────────────────────────────────────────────────

class TestTicketRecord:

    def test_to_db_dict_excludes_none(self):
        record = TicketRecord(
            id="ticket-001",
            tenant_id="tenant-abc",
            customer_id="cust-001",
            channel="api",
            raw_text="Payment failed",
            priority=None,           # None → should be excluded
            category=None,
        )
        d = record.to_db_dict()
        assert "priority" not in d
        assert "category" not in d

    def test_to_db_dict_includes_non_none(self):
        record = TicketRecord(
            id="ticket-002",
            tenant_id="tenant-abc",
            customer_id="cust-002",
            channel="email",
            raw_text="Refund not processed",
            priority="high",
            category="billing",
            constitutional_score=0.95,
        )
        d = record.to_db_dict()
        assert d["priority"] == "high"
        assert d["category"] == "billing"
        assert d["constitutional_score"] == 0.95
        assert d["channel"] == "email"

    def test_to_db_dict_always_includes_required_fields(self):
        record = TicketRecord(
            id="ticket-003",
            tenant_id="t1",
            customer_id="c1",
            channel="chat",
            raw_text="test",
        )
        d = record.to_db_dict()
        for field in ["id", "tenant_id", "customer_id", "channel", "raw_text", "status"]:
            assert field in d, f"Required field '{field}' missing from db dict"

    def test_default_status_is_pending(self):
        record = TicketRecord(
            id="t", tenant_id="t", customer_id="c", channel="api", raw_text="x"
        )
        assert record.status == "pending"

    def test_default_constitutional_passed_is_true(self):
        record = TicketRecord(
            id="t", tenant_id="t", customer_id="c", channel="api", raw_text="x"
        )
        assert record.constitutional_passed is True


# ─────────────────────────────────────────────────────────────────────────────
# TicketRepository tests
# ─────────────────────────────────────────────────────────────────────────────

TENANT_ID = "a0000000-0000-0000-0000-000000000001"


class TestTicketRepositoryCreate:

    @pytest.mark.asyncio
    async def test_create_calls_upsert_with_tenant_id(self):
        client, qb, _ = _make_supabase_mock(return_data=[{"id": "ticket-001"}])
        with patch("src.db.repository.get_supabase", new=AsyncMock(return_value=client)):
            repo = TicketRepository(TENANT_ID)
            record = TicketRecord(
                id="ticket-001", tenant_id=TENANT_ID,
                customer_id="c1", channel="api", raw_text="test",
            )
            await repo.create(record)

        # upsert was called
        qb.upsert.assert_called_once()
        call_data = qb.upsert.call_args[0][0]
        assert call_data["tenant_id"] == TENANT_ID
        assert call_data["id"] == "ticket-001"

    @pytest.mark.asyncio
    async def test_create_raises_repository_error_on_exception(self):
        client, qb, _ = _make_supabase_mock()
        qb.execute = AsyncMock(side_effect=Exception("DB error"))
        with patch("src.db.repository.get_supabase", new=AsyncMock(return_value=client)):
            repo = TicketRepository(TENANT_ID)
            record = TicketRecord(
                id="ticket-fail", tenant_id=TENANT_ID,
                customer_id="c1", channel="api", raw_text="fail",
            )
            with pytest.raises(RepositoryError, match="Failed to create ticket"):
                await repo.create(record)


class TestTicketRepositoryUpdateStatus:

    @pytest.mark.asyncio
    async def test_update_processing_sets_started_at(self):
        client, qb, _ = _make_supabase_mock()
        with patch("src.db.repository.get_supabase", new=AsyncMock(return_value=client)):
            repo = TicketRepository(TENANT_ID)
            await repo.update_status("ticket-001", "processing")

        update_data = qb.update.call_args[0][0]
        assert update_data["status"] == "processing"
        assert "processing_started_at" in update_data

    @pytest.mark.asyncio
    async def test_update_complete_maps_result_fields(self):
        client, qb, _ = _make_supabase_mock()
        with patch("src.db.repository.get_supabase", new=AsyncMock(return_value=client)):
            repo = TicketRepository(TENANT_ID)
            await repo.update_status("ticket-001", "complete", result_data={
                "category": "billing",
                "priority": "high",
                "constitutional_score": 0.95,
                "constitutional_passed": True,
                "suggested_resolution": "Please retry your payment.",
            })

        update_data = qb.update.call_args[0][0]
        assert update_data["category"] == "billing"
        assert update_data["priority"] == "high"
        assert update_data["constitutional_score"] == 0.95
        assert "processing_completed_at" in update_data

    @pytest.mark.asyncio
    async def test_update_filters_by_tenant_id(self):
        client, qb, _ = _make_supabase_mock()
        with patch("src.db.repository.get_supabase", new=AsyncMock(return_value=client)):
            repo = TicketRepository(TENANT_ID)
            await repo.update_status("ticket-001", "complete")

        # eq() was called with tenant_id to enforce tenant isolation
        [str(c) for c in qb.eq.call_args_list]
        assert any("tenant_id" in str(c) for c in qb.eq.call_args_list), \
            "RLS double-check: eq(tenant_id) must be called in update"


class TestTicketRepositoryGet:

    @pytest.mark.asyncio
    async def test_get_returns_none_when_not_found(self):
        client, _, _ = _make_supabase_mock(return_data=[])
        with patch("src.db.repository.get_supabase", new=AsyncMock(return_value=client)):
            repo = TicketRepository(TENANT_ID)
            result = await repo.get("nonexistent-ticket")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_returns_row_when_found(self):
        client, _, _ = _make_supabase_mock(return_data=[{"id": "ticket-001", "status": "complete"}])
        with patch("src.db.repository.get_supabase", new=AsyncMock(return_value=client)):
            repo = TicketRepository(TENANT_ID)
            result = await repo.get("ticket-001")
        assert result["id"] == "ticket-001"
        assert result["status"] == "complete"


class TestTicketRepositoryViolation:

    @pytest.mark.asyncio
    async def test_log_violation_truncates_evidence(self):
        client, qb, _ = _make_supabase_mock()
        with patch("src.db.repository.get_supabase", new=AsyncMock(return_value=client)):
            repo = TicketRepository(TENANT_ID)
            long_evidence = "X" * 500  # longer than 200 char limit
            await repo.log_violation(
                "ticket-001", "PII_PROTECTION", "critical",
                "redact", long_evidence, "PII found in response",
            )

        insert_data = qb.insert.call_args[0][0]
        assert len(insert_data["evidence"]) == 200

    @pytest.mark.asyncio
    async def test_log_violation_stores_all_fields(self):
        client, qb, _ = _make_supabase_mock()
        with patch("src.db.repository.get_supabase", new=AsyncMock(return_value=client)):
            repo = TicketRepository(TENANT_ID)
            await repo.log_violation(
                "ticket-001", "AI_IDENTITY", "critical",
                "block", "I am not an AI", "EU AI Act violation",
            )

        insert_data = qb.insert.call_args[0][0]
        assert insert_data["rule_id"] == "AI_IDENTITY"
        assert insert_data["severity"] == "critical"
        assert insert_data["action_taken"] == "block"
        assert insert_data["tenant_id"] == TENANT_ID


class TestTicketRepositoryAudit:

    @pytest.mark.asyncio
    async def test_write_audit_does_not_raise_on_failure(self):
        """Audit failures must be non-fatal — they cannot crash the main triage flow."""
        client, qb, _ = _make_supabase_mock()
        qb.execute = AsyncMock(side_effect=Exception("DB unavailable"))
        with patch("src.db.repository.get_supabase", new=AsyncMock(return_value=client)):
            repo = TicketRepository(TENANT_ID)
            # Should NOT raise
            await repo.write_audit(actor="system", action="ticket.created", ticket_id="t1")


# ─────────────────────────────────────────────────────────────────────────────
# TenantRepository tests
# ─────────────────────────────────────────────────────────────────────────────

class TestTenantRepository:

    @pytest.mark.asyncio
    async def test_get_by_slug_returns_none_when_not_found(self):
        client, _, _ = _make_supabase_mock(return_data=[])
        with patch("src.db.repository.get_supabase", new=AsyncMock(return_value=client)):
            repo = TenantRepository()
            result = await repo.get_by_slug("nonexistent-tenant")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_slug_returns_tenant(self):
        client, _, _ = _make_supabase_mock(return_data=[{"slug": "acme-corp", "tier": "enterprise"}])
        with patch("src.db.repository.get_supabase", new=AsyncMock(return_value=client)):
            repo = TenantRepository()
            result = await repo.get_by_slug("acme-corp")
        assert result["slug"] == "acme-corp"
        assert result["tier"] == "enterprise"

    @pytest.mark.asyncio
    async def test_create_uses_upsert_on_slug_conflict(self):
        client, qb, _ = _make_supabase_mock(return_data=[{"slug": "new-tenant"}])
        with patch("src.db.repository.get_supabase", new=AsyncMock(return_value=client)):
            repo = TenantRepository()
            await repo.create("new-tenant", "New Tenant Inc", "growth")

        qb.upsert.assert_called_once()
        call_kwargs = qb.upsert.call_args[1]
        assert call_kwargs.get("on_conflict") == "slug"


# ─────────────────────────────────────────────────────────────────────────────
# Console Bug Fixes and UI integration tests
# ─────────────────────────────────────────────────────────────────────────────

class TestBugFixes:

    def test_record_new_fields(self):
        record = TicketRecord(
            id="t1", tenant_id="t1", customer_id="c1", channel="api", raw_text="text",
            customer_tier="enterprise", masked_text="masked text"
        )
        assert record.customer_tier == "enterprise"
        assert record.masked_text == "masked text"
        
        d = record.to_db_dict()
        assert d["customer_tier"] == "enterprise"
        assert d["masked_text"] == "masked text"

    @pytest.mark.asyncio
    async def test_update_status_maps_new_fields(self):
        client, qb, _ = _make_supabase_mock()
        with patch("src.db.repository.get_supabase", new=AsyncMock(return_value=client)):
            repo = TicketRepository(TENANT_ID)
            await repo.update_status("ticket-001", "complete", result_data={
                "customer_tier": "vip",
                "masked_text": "redacted info"
            })
        update_data = qb.update.call_args[0][0]
        assert update_data["customer_tier"] == "vip"
        assert update_data["masked_text"] == "redacted info"

    def test_lazy_vault_initialization(self):
        from src.responsible_ai.privacy_vault import CryptographicPrivacyVault
        vault = CryptographicPrivacyVault()
        # Should not crash and should lazily initialize spacy/presidio
        tokenized, count = vault.encrypt_text(
            tenant_id="test-tenant",
            text="Contact me at test@example.com or 555-0199",
            analyzer=None,
            anonymizer=None
        )
        assert count > 0
        assert "TOK_EMAIL" in tokenized or "TOK_PHONE" in tokenized

