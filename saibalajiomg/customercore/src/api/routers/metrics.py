"""
CustomerCore API — Prometheus Metrics Router (Phase 10)

WHY PROMETHEUS METRICS IN THE API?
------------------------------------
Prometheus is the industry-standard metrics collection system. It works by
"scraping" — Prometheus server periodically calls GET /metrics on your API,
parses the response, and stores the time-series data. Grafana then queries
Prometheus to render dashboards.

The metrics endpoint uses the OpenMetrics text format — plain text, one metric per line.
Every monitoring system (Datadog, New Relic, Grafana, AWS CloudWatch) can ingest this format.

WHAT WE TRACK:
  customercore_triage_requests_total  — counter: how many tickets processed (by status, tenant, priority)
  customercore_triage_duration_ms     — histogram: processing latency distribution (p50/p95/p99)
  customercore_llm_calls_total        — counter: LLM API calls (by model, task_type, status)
  customercore_llm_cost_usd_total     — counter: running LLM spend (by model)
  customercore_sla_violations_total   — counter: SLA breaches (by tenant, priority)
  customercore_hitl_reviews_total     — counter: HITL pauses (by reason)
  customercore_cache_hits_total       — counter: RAG cache hits vs misses

WHY COUNTERS AND HISTOGRAMS?
  Counter: A value that only increases (total requests, errors, LLM calls).
    You query the RATE of change: rate(customercore_triage_requests_total[5m])
    = "tickets per second in the last 5 minutes"

  Histogram: Records a distribution of values in configurable buckets.
    histogram_quantile(0.95, customercore_triage_duration_ms) = "95th percentile latency"
    This is how you calculate p50/p95/p99 latency — the SLAs we defined in Phase 7.
"""

from __future__ import annotations


from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)

router = APIRouter(prefix="/api/v1", tags=["Metrics"])

# ─────────────────────────────────────────────────────────────────────────────
# Metric Definitions
# Labels are dimensions you can filter by in Grafana dashboards.
# Keep label cardinality low — don't use customer_id as a label (millions of values
# would overload Prometheus). Use category, priority, tenant_id (bounded set).
# ─────────────────────────────────────────────────────────────────────────────

triage_requests_total = Counter(
    name="customercore_triage_requests_total",
    documentation="Total number of triage requests processed.",
    labelnames=["status", "priority", "detected_language"],
)

triage_duration_ms = Histogram(
    name="customercore_triage_duration_ms",
    documentation="End-to-end triage latency in milliseconds.",
    labelnames=["priority"],
    buckets=[500, 1000, 2000, 3000, 5000, 8000, 15000, 30000],
    # Buckets define the histogram resolution:
    # 500ms, 1s, 2s, 3s, 5s, 8s, 15s, 30s
    # Allows computing: what % of tickets complete in under 3 seconds?
)

llm_calls_total = Counter(
    name="customercore_llm_calls_total",
    documentation="Total LLM API calls made by the router.",
    labelnames=["model", "task_type", "status"],
    # model: "gemma3:4b", "openrouter/meta-llama/llama-3.1-8b-instruct"
    # task_type: "classify", "rag_summary", "churn", "incident"
    # status: "success", "error", "timeout"
)

llm_cost_usd_total = Counter(
    name="customercore_llm_cost_usd_total",
    documentation="Cumulative LLM API cost in USD.",
    labelnames=["model"],
)

sla_violations_total = Counter(
    name="customercore_sla_violations_total",
    documentation="Total SLA violations by priority level.",
    labelnames=["priority"],
)

hitl_reviews_total = Counter(
    name="customercore_hitl_reviews_total",
    documentation="Total HITL reviews triggered.",
    labelnames=["reason"],
    # reason: "low_confidence", "critical_priority", "security_flag", "vip_customer"
)

cache_hits_total = Counter(
    name="customercore_cache_hits_total",
    documentation="RAG semantic cache hits vs misses.",
    labelnames=["cache_layer", "result"],
    # cache_layer: "l1_exact", "l2_semantic", "l3_tenant"
    # result: "hit", "miss"
)


# ─────────────────────────────────────────────────────────────────────────────
# Helper functions — called by the triage background task to record metrics
# ─────────────────────────────────────────────────────────────────────────────

def record_triage_complete(
    *,
    status: str,
    priority: str,
    detected_language: str,
    duration_ms: int,
) -> None:
    """Record a completed triage request in Prometheus metrics."""
    triage_requests_total.labels(
        status=status,
        priority=priority or "unknown",
        detected_language=detected_language or "en",
    ).inc()

    triage_duration_ms.labels(priority=priority or "unknown").observe(duration_ms)


def record_llm_call(
    *,
    model: str,
    task_type: str,
    status: str = "success",
    cost_usd: float = 0.0,
) -> None:
    """Record an LLM API call for cost and reliability tracking."""
    llm_calls_total.labels(model=model, task_type=task_type, status=status).inc()
    if cost_usd > 0:
        llm_cost_usd_total.labels(model=model).inc(cost_usd)


def record_sla_violation(priority: str) -> None:
    """Record an SLA violation for a given priority level."""
    sla_violations_total.labels(priority=priority).inc()


def record_hitl(reason: str) -> None:
    """Record a HITL review trigger."""
    hitl_reviews_total.labels(reason=reason).inc()


def record_cache_result(cache_layer: str, hit: bool) -> None:
    """Record a RAG cache hit or miss."""
    cache_hits_total.labels(
        cache_layer=cache_layer,
        result="hit" if hit else "miss",
    ).inc()


# ─────────────────────────────────────────────────────────────────────────────
# Metrics endpoint — Prometheus scrapes this
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/metrics",
    response_class=PlainTextResponse,
    summary="Prometheus metrics endpoint",
    description=(
        "Exposes all CustomerCore metrics in Prometheus OpenMetrics text format. "
        "Configure Prometheus to scrape this endpoint every 15s. "
        "Connect Grafana to Prometheus to visualize dashboards."
    ),
    include_in_schema=True,
)
async def metrics() -> PlainTextResponse:
    """
    Prometheus metrics scrape endpoint.

    Prometheus configuration (prometheus.yml):
        scrape_configs:
          - job_name: customercore
            scrape_interval: 15s
            static_configs:
              - targets: ['localhost:8080']
            metrics_path: /api/v1/metrics

    This endpoint is unauthenticated deliberately — Prometheus scrapers typically
    cannot authenticate with JWTs. In production, restrict access via network policy
    (only allow Prometheus pod IP) rather than application-level auth.
    """
    data = generate_latest()
    return PlainTextResponse(content=data.decode("utf-8"), media_type=CONTENT_TYPE_LATEST)
