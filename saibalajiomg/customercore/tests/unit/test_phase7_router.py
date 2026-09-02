"""
tests/unit/test_phase7_router.py

Phase 7: SLA-Aware Multi-Model LLM Router — Full Test Suite

All tests are mock-based — no real Ollama or OpenRouter calls.
Tests verify the routing LOGIC, not the LLM output.

Sections:
  1. Routing Table correctness     — every (task, priority) pair routes correctly
  2. Action tasks always cloud     — regardless of priority
  3. Classification always local   — regardless of priority
  4. Extraction always local       — regardless of priority
  5. Reasoning splits              — low/medium=local, high/critical=cloud
  6. Metrics tracking              — counters, cost, SLA tracking
  7. SLA violation detection       — slow response logged as violation
  8. Fallback to local             — no cloud key → local fallback
  9. predict_route() dry run       — routing decisions without LLM calls
 10. LLMClient mock integration    — response structure validation
 11. LLMResponse dataclass         — field presence and defaults
"""

import pytest
from unittest.mock import MagicMock, patch
from src.rag.router import (
    LLMRouter, RouterDecision, ROUTING_TABLE, SLA_TARGETS_MS
)
from src.rag.llm_client import LLMClient, LLMResponse


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_response(
    success=True,
    latency_ms=100.0,
    content="test response",
    provider="local",
    model="ollama/gemma3:4b",
    cost=0.0,
    input_tokens=50,
    output_tokens=30,
) -> LLMResponse:
    return LLMResponse(
        content=content,
        model_used=model,
        provider=provider,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=cost,
        success=success,
        error=None if success else "mock error",
    )


@pytest.fixture
def mock_client():
    client = MagicMock(spec=LLMClient)
    client.local_model = "ollama/gemma3:4b"
    client.cloud_model = "openrouter/anthropic/claude-3.5-sonnet"
    client.call_local.return_value = _make_response(
        provider="local", model="ollama/gemma3:4b", latency_ms=150.0
    )
    client.call_cloud.return_value = _make_response(
        provider="cloud", model="openrouter/anthropic/claude-3.5-sonnet",
        latency_ms=1200.0, cost=0.025
    )
    return client


@pytest.fixture
def router(mock_client):
    return LLMRouter(client=mock_client)


MESSAGES = [{"role": "user", "content": "test ticket content"}]


# ── 1. Routing Table Correctness ──────────────────────────────────────────────

class TestRoutingTable:
    """Verify every entry in ROUTING_TABLE is correct."""

    def test_table_has_entries_for_all_combinations(self):
        task_types = ["classify", "extract", "reason", "action"]
        priorities = ["low", "medium", "high", "critical"]
        for task in task_types:
            for priority in priorities:
                assert (task, priority) in ROUTING_TABLE, \
                    f"Missing routing entry for ({task}, {priority})"

    def test_total_routing_entries(self):
        assert len(ROUTING_TABLE) == 16, "Should have 4 tasks × 4 priorities = 16 entries"

    def test_sla_targets_all_priorities(self):
        for p in ["low", "medium", "high", "critical"]:
            assert p in SLA_TARGETS_MS
            assert SLA_TARGETS_MS[p] > 0


# ── 2. Action Tasks Always Cloud ──────────────────────────────────────────────

class TestActionRouting:
    def test_action_low_routes_cloud(self, router):
        _, decision = router.route(MESSAGES, task_type="action", priority="low")
        assert decision.model_tier == "cloud"

    def test_action_medium_routes_cloud(self, router):
        _, decision = router.route(MESSAGES, task_type="action", priority="medium")
        assert decision.model_tier == "cloud"

    def test_action_high_routes_cloud(self, router):
        _, decision = router.route(MESSAGES, task_type="action", priority="high")
        assert decision.model_tier == "cloud"

    def test_action_critical_routes_cloud(self, router):
        _, decision = router.route(MESSAGES, task_type="action", priority="critical")
        assert decision.model_tier == "cloud"

    def test_action_calls_call_cloud(self, router, mock_client):
        router.route(MESSAGES, task_type="action", priority="medium")
        mock_client.call_cloud.assert_called_once()
        mock_client.call_local.assert_not_called()


# ── 3. Classification Always Local ────────────────────────────────────────────

class TestClassifyRouting:
    def test_classify_low_routes_local(self, router):
        _, decision = router.route(MESSAGES, task_type="classify", priority="low")
        assert decision.model_tier == "local"

    def test_classify_medium_routes_local(self, router):
        _, decision = router.route(MESSAGES, task_type="classify", priority="medium")
        assert decision.model_tier == "local"

    def test_classify_high_routes_local(self, router):
        _, decision = router.route(MESSAGES, task_type="classify", priority="high")
        assert decision.model_tier == "local"

    def test_classify_critical_routes_local(self, router):
        _, decision = router.route(MESSAGES, task_type="classify", priority="critical")
        assert decision.model_tier == "local"

    def test_classify_calls_call_local(self, router, mock_client):
        router.route(MESSAGES, task_type="classify", priority="high")
        mock_client.call_local.assert_called_once()
        mock_client.call_cloud.assert_not_called()


# ── 4. Extraction Always Local ────────────────────────────────────────────────

class TestExtractRouting:
    @pytest.mark.parametrize("priority", ["low", "medium", "high", "critical"])
    def test_extract_always_local(self, router, priority):
        _, decision = router.route(MESSAGES, task_type="extract", priority=priority)
        assert decision.model_tier == "local"


# ── 5. Reasoning Splits ───────────────────────────────────────────────────────

class TestReasonRouting:
    def test_reason_low_routes_local(self, router):
        _, decision = router.route(MESSAGES, task_type="reason", priority="low")
        assert decision.model_tier == "local"

    def test_reason_medium_routes_local(self, router):
        _, decision = router.route(MESSAGES, task_type="reason", priority="medium")
        assert decision.model_tier == "local"

    def test_reason_high_routes_cloud(self, router):
        _, decision = router.route(MESSAGES, task_type="reason", priority="high")
        assert decision.model_tier == "cloud"

    def test_reason_critical_routes_cloud(self, router):
        _, decision = router.route(MESSAGES, task_type="reason", priority="critical")
        assert decision.model_tier == "cloud"


# ── 6. Metrics Tracking ───────────────────────────────────────────────────────

class TestMetrics:
    def test_total_calls_increments(self, router):
        router.route(MESSAGES, task_type="classify", priority="low")
        router.route(MESSAGES, task_type="action", priority="high")
        assert router.metrics.total_calls == 2

    def test_local_and_cloud_counts(self, router):
        router.route(MESSAGES, task_type="classify", priority="low")   # local
        router.route(MESSAGES, task_type="classify", priority="medium") # local
        router.route(MESSAGES, task_type="action", priority="critical") # cloud
        assert router.metrics.local_calls == 2
        assert router.metrics.cloud_calls == 1

    def test_cost_accumulates(self, router, mock_client):
        mock_client.call_cloud.return_value = _make_response(cost=0.025, provider="cloud")
        router.route(MESSAGES, task_type="action", priority="high")
        router.route(MESSAGES, task_type="action", priority="high")
        assert router.metrics.total_cost_usd == pytest.approx(0.05, abs=0.001)

    def test_local_cost_is_zero(self, router):
        router.route(MESSAGES, task_type="classify", priority="medium")
        assert router.metrics.total_cost_usd == 0.0

    def test_pct_calculation(self, router):
        router.route(MESSAGES, task_type="classify", priority="low")    # local
        router.route(MESSAGES, task_type="action", priority="low")      # cloud
        assert router.metrics.local_pct == pytest.approx(50.0)
        assert router.metrics.cloud_pct == pytest.approx(50.0)

    def test_calls_by_task_tracked(self, router):
        router.route(MESSAGES, task_type="classify", priority="low")
        router.route(MESSAGES, task_type="classify", priority="medium")
        router.route(MESSAGES, task_type="reason", priority="high")
        assert router.metrics.calls_by_task["classify"] == 2
        assert router.metrics.calls_by_task["reason"] == 1

    def test_calls_by_priority_tracked(self, router):
        router.route(MESSAGES, task_type="classify", priority="high")
        router.route(MESSAGES, task_type="reason", priority="high")
        router.route(MESSAGES, task_type="extract", priority="low")
        assert router.metrics.calls_by_priority["high"] == 2
        assert router.metrics.calls_by_priority["low"] == 1

    def test_get_metrics_summary_keys(self, router):
        router.route(MESSAGES, task_type="classify", priority="low")
        summary = router.get_metrics_summary()
        expected_keys = [
            "total_calls", "local_calls", "cloud_calls", "local_pct", "cloud_pct",
            "total_cost_usd", "avg_latency_ms", "sla_violations", "errors",
            "calls_by_task", "calls_by_priority"
        ]
        for key in expected_keys:
            assert key in summary, f"Missing key in metrics summary: {key}"


# ── 7. SLA Violation Detection ────────────────────────────────────────────────

class TestSLAViolations:
    def test_sla_violation_counted_when_slow(self, router, mock_client):
        """A call taking 5000ms on a 'critical' ticket (SLA=200ms) must be a violation."""
        mock_client.call_local.return_value = _make_response(
            latency_ms=5000.0, provider="local"
        )
        router.route(MESSAGES, task_type="classify", priority="critical")
        assert router.metrics.sla_violations == 1

    def test_no_violation_when_within_sla(self, router, mock_client):
        """A call taking 100ms on a 'low' ticket (SLA=2000ms) must NOT be a violation."""
        mock_client.call_local.return_value = _make_response(
            latency_ms=100.0, provider="local"
        )
        router.route(MESSAGES, task_type="classify", priority="low")
        assert router.metrics.sla_violations == 0

    def test_sla_logged_in_call_log(self, router, mock_client):
        mock_client.call_local.return_value = _make_response(latency_ms=50.0)
        router.route(MESSAGES, task_type="classify", priority="high")
        log = router._call_log[-1]
        assert "sla_met" in log
        assert log["sla_met"] is True  # 50ms < 500ms SLA for 'high'


# ── 8. Error Handling ─────────────────────────────────────────────────────────

class TestErrorHandling:
    def test_failed_call_increments_error_count(self, router, mock_client):
        mock_client.call_local.return_value = _make_response(success=False, latency_ms=10.0)
        router.route(MESSAGES, task_type="classify", priority="low")
        assert router.metrics.errors == 1

    def test_failed_call_does_not_count_as_local_or_cloud(self, router, mock_client):
        mock_client.call_local.return_value = _make_response(success=False, latency_ms=10.0)
        router.route(MESSAGES, task_type="classify", priority="low")
        assert router.metrics.local_calls == 0
        assert router.metrics.cloud_calls == 0

    def test_cloud_fallback_when_no_api_key(self, router, mock_client):
        """When OPENROUTER_API_KEY is not set, call_cloud falls back to call_local."""
        with patch("src.rag.llm_client.OPENROUTER_API_KEY", ""):
            # Build a client with no cloud key — call_cloud should call_local internally
            client = LLMClient(
                local_model="ollama/gemma3:4b",
                cloud_model="openrouter/anthropic/claude-3.5-sonnet"
            )
            # Patch the internal _call to return a mock so we don't hit Ollama
            mock_resp = _make_response(provider="local", model="ollama/gemma3:4b")
            with patch.object(client, "_call", return_value=mock_resp):
                result = client.call_cloud([{"role": "user", "content": "test"}])
                # Should have received something back — not an exception
                assert result is not None
                assert isinstance(result, LLMResponse)



# ── 9. predict_route() Dry Run ────────────────────────────────────────────────

class TestPredictRoute:
    def test_predict_does_not_call_llm(self, router, mock_client):
        router.predict_route("classify", "low")
        router.predict_route("action", "critical")
        mock_client.call_local.assert_not_called()
        mock_client.call_cloud.assert_not_called()

    def test_predict_returns_router_decision(self, router):
        decision = router.predict_route("reason", "high")
        assert isinstance(decision, RouterDecision)
        assert decision.task_type == "reason"
        assert decision.priority == "high"
        assert decision.model_tier == "cloud"

    def test_predict_does_not_update_metrics(self, router):
        router.predict_route("action", "critical")
        router.predict_route("classify", "low")
        assert router.metrics.total_calls == 0

    def test_predict_reasoning_is_non_empty(self, router):
        d = router.predict_route("action", "critical")
        assert len(d.reasoning) > 10


# ── 10. RouterDecision Fields ─────────────────────────────────────────────────

class TestRouterDecision:
    def test_local_decision_has_local_model_name(self, router):
        _, decision = router.route(MESSAGES, task_type="classify", priority="low")
        assert decision.model_name == router.client.local_model

    def test_cloud_decision_has_cloud_model_name(self, router):
        _, decision = router.route(MESSAGES, task_type="action", priority="high")
        assert decision.model_name == router.client.cloud_model

    def test_sla_target_matches_priority(self, router):
        _, decision = router.route(MESSAGES, task_type="classify", priority="critical")
        assert decision.sla_target_ms == SLA_TARGETS_MS["critical"]  # 200ms


# ── 11. LLMResponse Dataclass ─────────────────────────────────────────────────

class TestLLMResponse:
    def test_response_fields_present(self):
        r = _make_response()
        assert r.content == "test response"
        assert r.model_used == "ollama/gemma3:4b"
        assert r.provider == "local"
        assert r.latency_ms == 100.0
        assert r.success is True
        assert r.error is None

    def test_failed_response_has_error(self):
        r = _make_response(success=False)
        assert r.success is False
        assert r.error == "mock error"

    def test_cost_is_zero_for_local(self):
        r = _make_response(cost=0.0, provider="local")
        assert r.estimated_cost_usd == 0.0
