"""Local-only runtime observability for the RAG generation pipeline.

Captures three things, all written under the local ``DATA_DIR`` (nothing leaves
the machine and no prompt/completion text is ever recorded):

* **LLM call telemetry** — wall-clock latency, prompt/completion/total tokens and
  an estimated USD cost per call (``record_llm_call``), attributed to the active
  report + section via context variables.
* **Per-report quality metrics** — retrieval confidence, grounding pass rate,
  section-status breakdown, quarantine count, note-loss and auditor-violation
  counts by type (a hallucination proxy), rolled up when a report finishes
  (``report_trace`` / :meth:`ReportTrace.finalize`).
* **Optional OpenTelemetry tracing** — a parent span per report with child spans
  for retrieval / rerank / map / validate, exported to a localhost OTLP collector
  (e.g. Arize Phoenix). Fully no-op when tracing is disabled or the packages /
  endpoint are unavailable, so CI and offline runs are unaffected.

Every public entry point is defensive: a telemetry failure must never break a
generation call, so the recorders swallow their own errors (logged at DEBUG).
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import threading
import time
import uuid
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.config import settings

logger = logging.getLogger(__name__)

# Context attribution. ``asyncio.to_thread`` and ``asyncio.gather`` both copy the
# current context, so a value set in the top-level report coroutine propagates
# into section workers and into the nested LLM worker threads automatically.
_active_report: contextvars.ContextVar[ReportTrace | None] = contextvars.ContextVar(
    "rics_active_report", default=None
)
_active_section: contextvars.ContextVar[str] = contextvars.ContextVar(
    "rics_active_section", default=""
)


# ── records ──────────────────────────────────────────────────────────────────


@dataclass
class LLMCallRecord:
    label: str
    model: str
    latency_s: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    section_id: str = ""


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate USD cost from the configured pricing table (per 1M tokens).

    Matches the model id exactly first, then by the longest pricing-key prefix
    (so ``gpt-4o-mini-2024-07-18`` still prices off ``gpt-4o-mini``). Unknown
    models cost 0.0 — the call is still recorded, just not priced.
    """
    pricing = settings.model_pricing or {}
    price = pricing.get(model)
    if price is None:
        best_key = ""
        for key in pricing:
            if model.startswith(key) and len(key) > len(best_key):
                best_key = key
        if best_key:
            price = pricing[best_key]
    if not price:
        return 0.0
    inp = float(price[0]) if len(price) > 0 else 0.0
    outp = float(price[1]) if len(price) > 1 else 0.0
    cost = (prompt_tokens / 1_000_000.0) * inp + (
        completion_tokens / 1_000_000.0
    ) * outp
    return round(cost, 6)


# ── local metrics sink (thread-safe JSONL) ───────────────────────────────────


class _MetricsStore:
    """Append-only JSONL sink under ``<data_dir>/metrics`` (thread-safe)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def _dir(self) -> Path:
        base = (settings.observability_metrics_dir or "").strip()
        path = Path(base) if base else (settings.data_dir_path / "metrics")
        if not path.is_absolute():
            path = settings.resolve_path(path)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _append(self, filename: str, obj: dict) -> None:
        try:
            target = self._dir() / filename
            line = json.dumps(obj, ensure_ascii=False)
            with self._lock:
                with target.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
        except Exception:  # noqa: BLE001 - telemetry must never break the pipeline
            logger.debug("metrics append failed (%s)", filename, exc_info=True)

    def append_llm_call(self, record: LLMCallRecord, *, report_id: str) -> None:
        self._append(
            "llm_calls.jsonl",
            {
                "ts": _utcnow_iso(),
                "type": "llm_call",
                "report_id": report_id,
                **record.__dict__,
            },
        )

    def append_report(self, summary: dict) -> None:
        self._append("reports.jsonl", summary)

    def read_recent(self, filename: str, limit: int) -> list[dict]:
        """Return up to ``limit`` most-recent records from one sink file."""
        try:
            target = self._dir() / filename
            if not target.is_file():
                return []
            with self._lock:
                lines = target.read_text(encoding="utf-8").splitlines()
        except Exception:  # noqa: BLE001
            logger.debug("metrics read failed (%s)", filename, exc_info=True)
            return []
        out: list[dict] = []
        for line in lines[-max(0, limit) :]:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out


_STORE = _MetricsStore()


def store() -> _MetricsStore:
    return _STORE


def recent_summary(limit: int = 50) -> dict:
    """Aggregate the most-recent per-report records for the /metrics/summary view."""
    reports = _STORE.read_recent("reports.jsonl", limit)
    calls_tail = _STORE.read_recent("llm_calls.jsonl", limit * 12)

    tokens = sum(int(r.get("total_tokens", 0) or 0) for r in reports)
    cost = round(
        sum(float(r.get("estimated_cost_usd", 0.0) or 0.0) for r in reports), 6
    )
    durations = [float(r.get("duration_s", 0.0) or 0.0) for r in reports]

    grounding_rates = [
        r["grounding"]["pass_rate"]
        for r in reports
        if isinstance(r.get("grounding"), dict)
        and r["grounding"].get("pass_rate") is not None
    ]
    confidences = [
        r["retrieval_confidence"]["mean"]
        for r in reports
        if isinstance(r.get("retrieval_confidence"), dict)
        and r["retrieval_confidence"].get("mean") is not None
    ]

    violation_counts: Counter = Counter()
    status_counts: Counter = Counter()
    quarantines = 0
    for r in reports:
        violation_counts.update(r.get("violation_counts", {}) or {})
        status_counts.update(r.get("status_breakdown", {}) or {})
        quarantines += int(r.get("quarantine_count", 0) or 0)

    label_calls: Counter = Counter()
    label_latency: dict[str, float] = {}
    for c in calls_tail:
        lab = c.get("label", "llm")
        label_calls[lab] += 1
        label_latency[lab] = label_latency.get(lab, 0.0) + float(
            c.get("latency_s", 0.0) or 0.0
        )

    def _avg(xs: list[float]) -> float | None:
        return round(sum(xs) / len(xs), 3) if xs else None

    return {
        "enabled": settings.observability_enabled,
        "tracing_enabled": settings.observability_tracing_enabled,
        "reports_considered": len(reports),
        "totals": {
            "total_tokens": tokens,
            "estimated_cost_usd": cost,
        },
        "averages": {
            "duration_s": _avg(durations),
            "grounding_pass_rate": _avg(grounding_rates),
            "retrieval_confidence_mean": _avg(confidences),
        },
        "status_breakdown": dict(status_counts),
        "violation_counts": dict(violation_counts),
        "violations_total": sum(violation_counts.values()),
        "quarantine_total": quarantines,
        "llm_calls_by_label": {
            lab: {
                "calls": label_calls[lab],
                "avg_latency_s": round(label_latency[lab] / label_calls[lab], 3),
            }
            for lab in label_calls
        },
        "recent_reports": reports[-10:],
    }


# ── per-report trace ──────────────────────────────────────────────────────────


@dataclass
class ReportTrace:
    """Accumulates per-report telemetry; finalised when the report completes."""

    report_id: str
    tenant_id: str = ""
    started_at: float = field(default_factory=time.time)
    llm_calls: list[LLMCallRecord] = field(default_factory=list)
    # section_id -> list of auditor violation_type strings (hallucination proxy)
    violations: dict[str, list[str]] = field(default_factory=dict)
    quarantines: list[str] = field(default_factory=list)
    # section_id -> top rerank/similarity score of the retrieved baseline
    confidences: dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False
    )

    def add_call(self, record: LLMCallRecord) -> None:
        with self._lock:
            self.llm_calls.append(record)

    def set_retrieval_confidence(self, section_id: str, score: float) -> None:
        with self._lock:
            # Keep the strongest observed score for the section.
            prev = self.confidences.get(section_id)
            if prev is None or score > prev:
                self.confidences[section_id] = float(score)

    def add_violations(self, section_id: str, violation_types: list[str]) -> None:
        if not violation_types:
            return
        with self._lock:
            self.violations.setdefault(section_id, []).extend(violation_types)

    def add_quarantine(self, section_id: str) -> None:
        with self._lock:
            self.quarantines.append(section_id)

    def _llm_rollup(self) -> dict:
        by_label: dict[str, Counter] = {}
        prompt = completion = total = 0
        cost = 0.0
        latency = 0.0
        for c in self.llm_calls:
            prompt += c.prompt_tokens
            completion += c.completion_tokens
            total += c.total_tokens
            cost += c.cost_usd
            latency += c.latency_s
            lab = by_label.setdefault(
                c.label,
                Counter(calls=0, prompt_tokens=0, completion_tokens=0, total_tokens=0),
            )
            lab["calls"] += 1
            lab["prompt_tokens"] += c.prompt_tokens
            lab["completion_tokens"] += c.completion_tokens
            lab["total_tokens"] += c.total_tokens
        return {
            "llm_calls": len(self.llm_calls),
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total,
            "estimated_cost_usd": round(cost, 6),
            "llm_latency_s_sum": round(latency, 3),
            "by_label": {k: dict(v) for k, v in by_label.items()},
        }

    def finalize(self, result: Any) -> dict:
        """Roll up quality metrics from a ReportResult-like object and persist.

        Duck-typed: reads ``result.sections`` (each with ``section_id``, ``status``,
        ``grounding_passed`` and ``unmatched_observations``) and ``result.unassigned_text``.
        Returns the summary dict (also appended to ``reports.jsonl``).
        """
        sections = list(getattr(result, "sections", []) or [])
        status_breakdown: Counter = Counter()
        grounding_pass = 0
        grounding_total = 0
        note_loss_sections = 0
        for sec in sections:
            status = str(getattr(sec, "status", "") or "unknown")
            status_breakdown[status] += 1
            gp = getattr(sec, "grounding_passed", None)
            if gp is not None:
                grounding_total += 1
                if gp:
                    grounding_pass += 1
            if getattr(sec, "unmatched_observations", None):
                note_loss_sections += 1

        violation_counts: Counter = Counter()
        for types in self.violations.values():
            violation_counts.update(types)

        confidences = [c for c in self.confidences.values() if c > 0.0]

        unassigned = (getattr(result, "unassigned_text", "") or "").strip()

        summary = {
            "ts": _utcnow_iso(),
            "type": "report",
            "report_id": self.report_id,
            "tenant_id": self.tenant_id,
            "duration_s": round(time.time() - self.started_at, 3),
            "sections_total": len(sections),
            "status_breakdown": dict(status_breakdown),
            "grounding": {
                "passed": grounding_pass,
                "evaluated": grounding_total,
                "pass_rate": (
                    round(grounding_pass / grounding_total, 3)
                    if grounding_total
                    else None
                ),
            },
            "retrieval_confidence": {
                "mean": (
                    round(sum(confidences) / len(confidences), 3)
                    if confidences
                    else None
                ),
                "min": round(min(confidences), 3) if confidences else None,
                "n": len(confidences),
            },
            "note_loss": {
                "sections_with_unmatched": note_loss_sections,
                "has_unassigned_appendix": bool(unassigned),
            },
            "quarantine_count": len(self.quarantines),
            "violation_counts": dict(violation_counts),
            "violations_total": sum(violation_counts.values()),
            **self._llm_rollup(),
        }
        _STORE.append_report(summary)
        if settings.observability_console_log_calls or settings.observability_enabled:
            logger.info(
                "report %s done: %ss, %d sections, grounding %s, tokens %d, ~$%.4f, "
                "violations %d, quarantine %d",
                self.report_id,
                summary["duration_s"],
                summary["sections_total"],
                summary["grounding"]["pass_rate"],
                summary["total_tokens"],
                summary["estimated_cost_usd"],
                summary["violations_total"],
                summary["quarantine_count"],
            )
        return summary


# ── recording entry points ────────────────────────────────────────────────────


def record_llm_call(
    *,
    label: str,
    model: str,
    latency_s: float,
    usage: Any | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
) -> None:
    """Record one LLM call. Safe to call from any thread; never raises."""
    try:
        pt = int(
            prompt_tokens
            if prompt_tokens is not None
            else (getattr(usage, "prompt_tokens", 0) or 0)
        )
        ct = int(
            completion_tokens
            if completion_tokens is not None
            else (getattr(usage, "completion_tokens", 0) or 0)
        )
        tt = int(getattr(usage, "total_tokens", 0) or (pt + ct))
        section = _active_section.get()
        # Per-tenant cost ledger (independent of observability_enabled).
        try:
            from backend.cost import record_llm_cost

            provider = (
                "gemini" if (model or "").lower().startswith("gemini") else "openai"
            )
            record_llm_cost(
                model=model or "",
                prompt_tokens=pt,
                completion_tokens=ct,
                label=label or "llm",
                provider=provider,
                section_id=section,
            )
        except Exception:  # noqa: BLE001
            logger.debug("cost ledger record_llm_cost bridge failed", exc_info=True)

        if not settings.observability_enabled:
            return

        record = LLMCallRecord(
            label=label or "llm",
            model=model or "",
            latency_s=round(float(latency_s), 4),
            prompt_tokens=pt,
            completion_tokens=ct,
            total_tokens=tt,
            cost_usd=estimate_cost(model or "", pt, ct),
            section_id=section,
        )
        trace = _active_report.get()
        if trace is not None:
            trace.add_call(record)
        _STORE.append_llm_call(record, report_id=trace.report_id if trace else "")
        if settings.observability_console_log_calls:
            logger.info(
                "llm_call label=%s model=%s latency=%.2fs tokens=%d/%d/%d cost=$%.4f section=%s",
                record.label,
                record.model,
                record.latency_s,
                record.prompt_tokens,
                record.completion_tokens,
                record.total_tokens,
                record.cost_usd,
                record.section_id or "-",
            )
        _annotate_current_span_with_call(record)
    except Exception:  # noqa: BLE001 - telemetry must never break an LLM call
        logger.debug("record_llm_call failed", exc_info=True)


def record_violations(section_id: str, violation_types: list[str]) -> None:
    """Attribute auditor violations to the active report (hallucination proxy)."""
    if not settings.observability_enabled:
        return
    try:
        trace = _active_report.get()
        if trace is not None:
            trace.add_violations(section_id, [str(v) for v in violation_types if v])
    except Exception:  # noqa: BLE001
        logger.debug("record_violations failed", exc_info=True)


def record_quarantine(section_id: str) -> None:
    """Record that a section was replaced by the deterministic quarantine baseline."""
    if not settings.observability_enabled:
        return
    try:
        trace = _active_report.get()
        if trace is not None:
            trace.add_quarantine(section_id)
    except Exception:  # noqa: BLE001
        logger.debug("record_quarantine failed", exc_info=True)


def record_retrieval_confidence(section_id: str, score: float) -> None:
    """Record the retrieved baseline's top rerank/similarity score for a section."""
    if not settings.observability_enabled:
        return
    try:
        trace = _active_report.get()
        if trace is not None:
            trace.set_retrieval_confidence((section_id or "").strip(), float(score))
    except Exception:  # noqa: BLE001
        logger.debug("record_retrieval_confidence failed", exc_info=True)


@contextlib.contextmanager
def report_trace(report_id: str = "", tenant_id: str = "") -> Iterator[ReportTrace]:
    """Bind a :class:`ReportTrace` to the current context for the report's lifetime.

    Use ``with report_trace(...) as trace:`` around generation, then call
    ``trace.finalize(result)`` once the ReportResult is assembled. On exit the
    context var is restored. Also opens the parent OTel span when tracing is on.
    """
    trace = ReportTrace(report_id=report_id or uuid.uuid4().hex, tenant_id=tenant_id)
    token = _active_report.set(trace)
    with span("report.generate", report_id=trace.report_id, tenant_id=tenant_id):
        try:
            yield trace
        finally:
            _active_report.reset(token)


@contextlib.contextmanager
def section_scope(section_id: str) -> Iterator[None]:
    """Attribute LLM calls / spans made within the block to ``section_id``."""
    token = _active_section.set((section_id or "").strip())
    try:
        with span("section", section_id=section_id):
            yield
    finally:
        _active_section.reset(token)


# ── OpenTelemetry tracing (lazy, optional, localhost only) ────────────────────

_tracer: Any | None = None
_tracer_init_done = False
_tracer_lock = threading.Lock()


def _get_tracer() -> Any | None:
    """Return a configured OTel tracer, or None when tracing is unavailable.

    Initialised once, lazily. Any import/transport failure disables tracing for
    the process (logged once) rather than raising — offline runs stay clean.
    """
    global _tracer, _tracer_init_done
    if not settings.observability_tracing_enabled:
        return None
    if _tracer_init_done:
        return _tracer
    with _tracer_lock:
        if _tracer_init_done:
            return _tracer
        _tracer_init_done = True
        try:
            from opentelemetry import trace as ot_trace
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            provider = TracerProvider(
                resource=Resource.create(
                    {"service.name": settings.observability_service_name}
                )
            )
            provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(endpoint=settings.observability_otlp_endpoint)
                )
            )
            ot_trace.set_tracer_provider(provider)
            _tracer = ot_trace.get_tracer("rics.rag")
            logger.info(
                "OpenTelemetry tracing enabled -> %s",
                settings.observability_otlp_endpoint,
            )
        except Exception:  # noqa: BLE001 - tracing is strictly optional
            logger.warning(
                "Tracing requested but unavailable; continuing without spans.",
                exc_info=True,
            )
            _tracer = None
    return _tracer


@contextlib.contextmanager
def span(name: str, **attributes: Any) -> Iterator[Any]:
    """Start an OTel span if tracing is active; otherwise a no-op context."""
    tracer = _get_tracer()
    if tracer is None:
        yield None
        return
    try:
        with tracer.start_as_current_span(name) as sp:
            for key, value in attributes.items():
                if value is None:
                    continue
                try:
                    sp.set_attribute(f"rics.{key}", value)
                except Exception:  # noqa: BLE001
                    pass
            yield sp
    except Exception:  # noqa: BLE001 - never let a span error break the pipeline
        logger.debug("span %s failed", name, exc_info=True)
        yield None


def _annotate_current_span_with_call(record: LLMCallRecord) -> None:
    tracer = _get_tracer()
    if tracer is None:
        return
    try:
        from opentelemetry import trace as ot_trace

        sp = ot_trace.get_current_span()
        if sp is None:
            return
        sp.add_event(
            "llm_call",
            attributes={
                "rics.label": record.label,
                "rics.model": record.model,
                "rics.latency_s": record.latency_s,
                "rics.total_tokens": record.total_tokens,
                "rics.cost_usd": record.cost_usd,
            },
        )
    except Exception:  # noqa: BLE001
        logger.debug("span annotate failed", exc_info=True)
