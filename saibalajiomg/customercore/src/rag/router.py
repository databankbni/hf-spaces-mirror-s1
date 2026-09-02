"""
src/rag/router.py

Phase 7: SLA-Aware Multi-Model LLM Router

== The Gap We Are Closing ==
The previous setup had a manual local/cloud toggle — someone had to explicitly choose
which model to call. Real enterprise B2B AI platforms (Sierra AI, Decagon) route
automatically based on task complexity, SLA tier, and cost budget.

== Routing Logic ==
Every ticket that enters the system has a priority (low, medium, high, critical)
and a task type (classification, extraction, reasoning, action):

  Task Type     Priority      → Route To
  ────────────  ────────────  ─────────────────────────────────────────────────
  classify      low/medium    → LOCAL  (gemma3:4b via Ollama, ~150ms, $0)
  classify      high/critical → LOCAL  (still fast enough, no sensitive action)
  extract       low/medium    → LOCAL  (structured info extraction, deterministic)
  extract       high/critical → LOCAL  (same — no judgment call required)
  reason        low/medium    → LOCAL  (reasoning on routine tickets)
  reason        high/critical → CLOUD  (frontier model for complex edge cases)
  action        any           → CLOUD  (anything that takes an external action,
                                        e.g. issue refund, create Jira ticket,
                                        escalate to VIP team — requires best reasoning)

== Why Not Always Use Cloud? ==
  - 80%+ of B2B support tickets are routine (password resets, invoice requests)
  - Local Gemma 3 4B handles these in ~150ms at $0 cost
  - Cloud call costs ~$0.01-0.05 per ticket at scale = thousands per month
  - SLA: low-priority tickets don't need frontier-model reasoning
  - Privacy: local model means sensitive customer data never leaves the network

== Metrics ==
The router tracks every call: latency, model, cost, task type, priority.
These feed into Prometheus metrics for the Grafana dashboard.

Run standalone demo:
  python -m src.rag.router
"""

import logging
from dataclasses import dataclass, field
from typing import Literal, Optional
from collections import defaultdict

from src.rag.llm_client import LLMClient, LLMResponse, get_client

logger = logging.getLogger(__name__)

# ── Types ──────────────────────────────────────────────────────────────────────
Priority = Literal["low", "medium", "high", "critical"]
TaskType = Literal["classify", "extract", "reason", "action"]
ModelTier = Literal["local", "cloud"]


# ── Routing Table ──────────────────────────────────────────────────────────────
# (task_type, priority) → model tier
ROUTING_TABLE: dict[tuple[str, str], ModelTier] = {
    # Classification — always local (fast, cheap, sufficient)
    ("classify", "low"):      "local",
    ("classify", "medium"):   "local",
    ("classify", "high"):     "local",
    ("classify", "critical"): "local",

    # Extraction — always local (deterministic structured output)
    ("extract", "low"):      "local",
    ("extract", "medium"):   "local",
    ("extract", "high"):     "local",
    ("extract", "critical"): "local",

    # Reasoning — local for routine, cloud for high-stakes
    ("reason", "low"):      "local",
    ("reason", "medium"):   "local",
    ("reason", "high"):     "cloud",   # ← switch to frontier model
    ("reason", "critical"): "cloud",   # ← frontier model required

    # Action — always cloud (external side effects require best judgment)
    ("action", "low"):      "cloud",
    ("action", "medium"):   "cloud",
    ("action", "high"):     "cloud",
    ("action", "critical"): "cloud",
}

# SLA latency targets (ms) — used for logging/alerting
SLA_TARGETS_MS: dict[Priority, int] = {
    "low":      2000,   # 2 seconds acceptable
    "medium":   1000,   # 1 second
    "high":     500,    # 500ms
    "critical": 200,    # 200ms — only local can reliably hit this
}


@dataclass
class RouterDecision:
    """The routing decision made for a single request."""
    task_type: str
    priority: str
    model_tier: ModelTier
    model_name: str
    sla_target_ms: int
    reasoning: str


@dataclass
class RouterMetrics:
    """Aggregated metrics across all router calls (for Prometheus/Grafana)."""
    total_calls: int = 0
    local_calls: int = 0
    cloud_calls: int = 0
    total_cost_usd: float = 0.0
    total_latency_ms: float = 0.0
    sla_violations: int = 0
    errors: int = 0
    calls_by_task: dict = field(default_factory=lambda: defaultdict(int))
    calls_by_priority: dict = field(default_factory=lambda: defaultdict(int))

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.total_calls if self.total_calls else 0.0

    @property
    def local_pct(self) -> float:
        return (self.local_calls / self.total_calls * 100) if self.total_calls else 0.0

    @property
    def cloud_pct(self) -> float:
        return (self.cloud_calls / self.total_calls * 100) if self.total_calls else 0.0


class LLMRouter:
    """
    SLA-Aware Multi-Model LLM Router.

    Automatically selects local or cloud model based on task type and ticket
    priority. Tracks latency, cost, and SLA compliance for every call.

    Usage:
        router = LLMRouter()

        response, decision = router.route(
            messages=[{"role": "user", "content": "Classify this ticket: ..."}],
            task_type="classify",
            priority="medium",
        )
        print(f"Used: {decision.model_name} ({decision.model_tier})")
        print(f"Latency: {response.latency_ms}ms")
        print(f"Cost: ${response.estimated_cost_usd:.4f}")
    """

    def __init__(self, client: Optional[LLMClient] = None):
        self.client = client or get_client()
        self.metrics = RouterMetrics()
        self._call_log: list[dict] = []

    def _decide(self, task_type: str, priority: str) -> RouterDecision:
        """
        Determine which model tier to use based on routing table.
        Falls back to local if the combination is not in the table.
        """
        tier = ROUTING_TABLE.get((task_type, priority), "local")
        model_name = self.client.local_model if tier == "local" else self.client.cloud_model
        sla_ms = SLA_TARGETS_MS.get(priority, 2000)

        # Human-readable explanation for audit/debugging
        if tier == "local":
            reasoning = (
                f"Task '{task_type}' at priority '{priority}' routed to LOCAL model "
                f"({self.client.local_model}) — fast, free, data stays on-premise."
            )
        else:
            reasoning = (
                f"Task '{task_type}' at priority '{priority}' routed to CLOUD model "
                f"({self.client.cloud_model}) — frontier reasoning required for "
                f"high-stakes or action-taking tasks."
            )

        return RouterDecision(
            task_type=task_type,
            priority=priority,
            model_tier=tier,
            model_name=model_name,
            sla_target_ms=sla_ms,
            reasoning=reasoning,
        )

    def route(
        self,
        messages: list[dict],
        task_type: TaskType,
        priority: Priority,
        temperature: float = 0.1,
        max_tokens: int = 512,
    ) -> tuple[LLMResponse, RouterDecision]:
        """
        Main routing entry point.

        Decides which model to use, calls it, updates metrics, logs the decision,
        and checks SLA compliance. Returns (LLMResponse, RouterDecision).
        """
        decision = self._decide(task_type, priority)

        logger.info(
            "ROUTER → %s | task=%s priority=%s | %s",
            decision.model_tier.upper(), task_type, priority, decision.model_name
        )

        # Execute the call
        if decision.model_tier == "local":
            response = self.client.call_local(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        else:
            response = self.client.call_cloud(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        # Update metrics
        self.metrics.total_calls += 1
        self.metrics.calls_by_task[task_type] += 1
        self.metrics.calls_by_priority[priority] += 1

        if response.success:
            self.metrics.total_latency_ms += response.latency_ms
            self.metrics.total_cost_usd += response.estimated_cost_usd

            if decision.model_tier == "local":
                self.metrics.local_calls += 1
            else:
                self.metrics.cloud_calls += 1

            # SLA check
            if response.latency_ms > decision.sla_target_ms:
                self.metrics.sla_violations += 1
                logger.warning(
                    "SLA VIOLATION: task=%s priority=%s latency=%.0fms target=%dms",
                    task_type, priority, response.latency_ms, decision.sla_target_ms
                )
        else:
            self.metrics.errors += 1
            logger.error(
                "LLM call FAILED: task=%s priority=%s error=%s",
                task_type, priority, response.error
            )

        # Append to call log
        self._call_log.append({
            "task_type": task_type,
            "priority": priority,
            "model_tier": decision.model_tier,
            "model_name": response.model_used,
            "latency_ms": response.latency_ms,
            "cost_usd": response.estimated_cost_usd,
            "success": response.success,
            "sla_target_ms": decision.sla_target_ms,
            "sla_met": response.latency_ms <= decision.sla_target_ms,
        })

        return response, decision

    def get_metrics_summary(self) -> dict:
        """Return a dict of aggregated metrics suitable for Prometheus export."""
        return {
            "total_calls": self.metrics.total_calls,
            "local_calls": self.metrics.local_calls,
            "cloud_calls": self.metrics.cloud_calls,
            "local_pct": round(self.metrics.local_pct, 1),
            "cloud_pct": round(self.metrics.cloud_pct, 1),
            "total_cost_usd": round(self.metrics.total_cost_usd, 4),
            "avg_latency_ms": round(self.metrics.avg_latency_ms, 1),
            "sla_violations": self.metrics.sla_violations,
            "errors": self.metrics.errors,
            "calls_by_task": dict(self.metrics.calls_by_task),
            "calls_by_priority": dict(self.metrics.calls_by_priority),
        }

    def predict_route(self, task_type: str, priority: str) -> RouterDecision:
        """
        Predict routing decision WITHOUT making an LLM call.
        Useful for UI display, testing, and cost estimation.
        """
        return self._decide(task_type, priority)


# ── Module-level singleton ─────────────────────────────────────────────────────
_default_router: Optional[LLMRouter] = None


def get_router() -> LLMRouter:
    global _default_router
    if _default_router is None:
        _default_router = LLMRouter()
    return _default_router


# ── Standalone Demo ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)

    router = LLMRouter()

    print("=" * 65)
    print("CustomerCore Phase 7 — SLA-Aware LLM Router Demo")
    print("(Routing decisions only — no actual LLM calls in dry-run)")
    print("=" * 65)

    test_cases = [
        ("classify", "low",      "Classify this support ticket: 'I forgot my password'"),
        ("classify", "medium",   "Classify this ticket: 'API returning 500 errors on checkout'"),
        ("classify", "high",     "Classify urgency: 'Production database is down for 200 users'"),
        ("classify", "critical", "Classify: 'ALL services offline - complete outage for enterprise'"),
        ("extract",  "medium",   "Extract customer ID and error code from this ticket"),
        ("reason",   "low",      "Reason about whether this ticket needs escalation"),
        ("reason",   "medium",   "Determine if SLA is at risk for this ticket"),
        ("reason",   "high",     "Reason: Should we proactively offer a refund for this outage?"),
        ("reason",   "critical", "Critical: Is this a coordinated security breach across tenants?"),
        ("action",   "low",      "Send automated acknowledgment email to customer"),
        ("action",   "medium",   "Create Jira ticket and assign to billing team"),
        ("action",   "high",     "Issue $150 partial refund and update HubSpot CRM"),
        ("action",   "critical", "Escalate to VIP team + notify on-call engineer immediately"),
    ]

    print(f"\n{'Task':<10} {'Priority':<10} {'-> Tier':<8} {'Model':<35} {'SLA Target'}")
    print("─" * 90)

    local_count = 0
    cloud_count = 0

    for task_type, priority, _ in test_cases:
        decision = router.predict_route(task_type, priority)
        tier_display = f"{'🟢 LOCAL' if decision.model_tier == 'local' else '🔵 CLOUD'}"
        model_short = decision.model_name.split("/")[-1][:32]
        print(
            f"{task_type:<10} {priority:<10} {tier_display:<14} {model_short:<35} "
            f"≤{decision.sla_target_ms}ms"
        )
        if decision.model_tier == "local":
            local_count += 1
        else:
            cloud_count += 1

    total = len(test_cases)
    print("─" * 90)
    print(f"\nRouting summary: {local_count}/{total} LOCAL (${0:.2f} cost) | "
          f"{cloud_count}/{total} CLOUD (frontier reasoning)")
    print(f"\nCost savings vs. always-cloud: "
          f"~{local_count/total*100:.0f}% of calls are free")

    # Verify critical routing rules
    print("\n" + "─" * 40)
    print("Verifying critical routing rules:")
    rules = [
        (("action", "low"),       "cloud",  "ALL actions must use cloud"),
        (("action", "critical"),  "cloud",  "ALL actions must use cloud"),
        (("reason", "critical"),  "cloud",  "Critical reasoning must use cloud"),
        (("reason", "high"),      "cloud",  "High-priority reasoning must use cloud"),
        (("classify", "critical"),"local",  "Classification always local"),
        (("extract", "high"),     "local",  "Extraction always local"),
        (("reason", "low"),       "local",  "Low-priority reasoning is local"),
    ]
    all_ok = True
    for (task, prio), expected_tier, desc in rules:
        d = router.predict_route(task, prio)
        ok = d.model_tier == expected_tier
        icon = "✓" if ok else "✗"
        print(f"  {icon} {desc}: {task}/{prio} → {d.model_tier} (expected {expected_tier})")
        if not ok:
            all_ok = False

    print(f"\n{'All routing rules VERIFIED ✓' if all_ok else 'ROUTING RULE FAILURES!'}")
    print("=" * 65)
