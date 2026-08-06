"""Stable local trace schema with an optional OpenTelemetry bridge."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import LOGS_DIR

TRACE_SCHEMA_VERSION = "rag-trace-v2"
PARSER_VERSION = "laws-parser-v1"
PROMPT_VERSION = "rag-prompts-2026-07-29"


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float | None = None
    by_stage: dict[str, dict[str, int]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def record(self, stage: str, response: Any) -> None:
        usage = getattr(response, "usage_metadata", None) or {}
        if not usage:
            response_meta = getattr(response, "response_metadata", None) or {}
            usage = response_meta.get("token_usage", {}) or response_meta.get(
                "usage_metadata", {}
            )
        input_tokens = int(
            usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0
        )
        output_tokens = int(
            usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0
        )
        total_tokens = int(
            usage.get("total_tokens", input_tokens + output_tokens) or 0
        )
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.total_tokens += total_tokens
        stage_usage = self.by_stage.setdefault(
            stage,
            {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
        stage_usage["input_tokens"] += input_tokens
        stage_usage["output_tokens"] += output_tokens
        stage_usage["total_tokens"] += total_tokens


@dataclass
class QueryTrace:
    request_id: str
    run_id: str
    started_at: str
    original_query: str
    schema_version: str = TRACE_SCHEMA_VERSION
    rewritten_queries: list[str] = field(default_factory=list)
    route: dict[str, Any] = field(default_factory=dict)
    retrieval: list[dict[str, Any]] = field(default_factory=list)
    retrieval_diagnostics: dict[str, Any] = field(default_factory=dict)
    graph_expansion: list[dict[str, Any]] = field(default_factory=list)
    evidence_requirements: dict[str, Any] = field(default_factory=dict)
    confidence_gate: dict[str, Any] = field(default_factory=dict)
    shadow_adaptive: dict[str, Any] = field(default_factory=dict)
    generation: dict[str, Any] = field(default_factory=dict)
    grounding: dict[str, Any] = field(default_factory=dict)
    latency_ms: dict[str, float] = field(default_factory=dict)
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    retry_count: int = 0
    refinement_count: int = 0
    versions: dict[str, str] = field(default_factory=dict)
    final_status: str = "running"
    completed_at: str | None = None

    @classmethod
    def start(
        cls,
        query: str,
        *,
        request_id: str | None = None,
        run_id: str | None = None,
    ) -> "QueryTrace":
        return cls(
            request_id=request_id or str(uuid4()),
            run_id=run_id or str(uuid4()),
            started_at=utc_now(),
            original_query=query,
            versions={
                "index": active_index_version(),
                "law": active_law_version(),
                "parser": PARSER_VERSION,
                "prompt": PROMPT_VERSION,
                "trace_schema": TRACE_SCHEMA_VERSION,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def active_index_version() -> str:
    from .config import DATA_DIR

    manifest = DATA_DIR / "index_manifest.json"
    if not manifest.exists():
        return "legacy-unversioned"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        return str(data.get("active_version") or data.get("version") or "unknown")
    except (OSError, ValueError):
        return "manifest-unreadable"


def active_law_version() -> str:
    from .config import DATA_DIR

    manifest = DATA_DIR / "index_manifest.json"
    if not manifest.exists():
        return "legacy-current-laws"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        return str(data.get("law_version") or "unknown")
    except (OSError, ValueError):
        return "manifest-unreadable"


_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_NATIONAL_ID_RE = re.compile(r"(?i)\b[A-Z][12]\d{8}\b")
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?886[-\s]?)?(?:0?\d{1,2}[-\s]?)?\d{3,4}[-\s]?\d{3,4}(?!\d)"
)
_ADDRESS_RE = re.compile(
    r"[\u4e00-\u9fff]{2,}(?:縣|市)[\u4e00-\u9fff0-9\-]{1,30}"
    r"(?:路|街|巷|弄|號)(?:\d+樓)?"
)


def redact_pii(text: str) -> str:
    """Best-effort deterministic redaction for common Taiwan identifiers."""
    text = _EMAIL_RE.sub("[EMAIL]", text)
    text = _NATIONAL_ID_RE.sub("[NATIONAL_ID]", text)
    text = _PHONE_RE.sub("[PHONE]", text)
    return _ADDRESS_RE.sub("[ADDRESS]", text)


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_pii(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_value(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class TracePolicy:
    """Local trace privacy, sampling and retention policy.

    Sampling is deterministic by run ID so retries of the same trace do not
    randomly appear and disappear.  Errors may be retained independently from
    the normal sample to preserve incident evidence.
    """

    sample_rate: float = 1.0
    redact_pii: bool = False
    retention_days: int | None = 30
    always_keep_errors: bool = True

    def __post_init__(self) -> None:
        if not 0 <= self.sample_rate <= 1:
            raise ValueError("sample_rate must be between 0 and 1")
        if self.retention_days is not None and self.retention_days < 1:
            raise ValueError("retention_days must be positive or None")

    @classmethod
    def from_env(cls) -> "TracePolicy":
        from .config import get_settings

        settings = get_settings()
        return cls(
            sample_rate=settings.trace_sample_rate,
            redact_pii=settings.trace_redact_pii,
            retention_days=settings.trace_retention_days,
            always_keep_errors=settings.trace_keep_errors,
        )

    def should_write(self, record: dict[str, Any]) -> bool:
        if self.always_keep_errors and record.get("final_status") == "error":
            return True
        if self.sample_rate >= 1:
            return True
        if self.sample_rate <= 0:
            return False
        key = str(record.get("run_id") or record.get("request_id") or "")
        bucket = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16)
        return bucket / 0xFFFFFFFF < self.sample_rate

    def prepare(self, record: dict[str, Any]) -> dict[str, Any]:
        copied = json.loads(json.dumps(record, ensure_ascii=False))
        original_query = str(copied.get("original_query", ""))
        if self.redact_pii:
            copied = _redact_value(copied)
        copied["privacy"] = {
            "pii_redacted": self.redact_pii,
            "query_sha256": hashlib.sha256(
                original_query.encode("utf-8")
            ).hexdigest(),
            "sample_rate": self.sample_rate,
            "retention_days": self.retention_days,
        }
        return copied


class JsonlTraceWriter:
    """Thread-safe JSONL writer; it has no external-service dependency."""

    _lock = threading.Lock()

    def __init__(
        self,
        path: Path | None = None,
        *,
        policy: TracePolicy | None = None,
    ) -> None:
        self.path = path or LOGS_DIR / "traces" / "rag.jsonl"
        self.policy = policy or TracePolicy.from_env()

    def write(self, trace: QueryTrace | dict[str, Any]) -> bool:
        record = trace.to_dict() if isinstance(trace, QueryTrace) else trace
        if not self.policy.should_write(record):
            return False
        record = self.policy.prepare(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        with self._lock, self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
        return True

    def prune(self, *, now: datetime | None = None) -> int:
        """Atomically remove expired valid records and preserve malformed lines."""
        if self.policy.retention_days is None or not self.path.exists():
            return 0
        now = now or datetime.now(UTC)
        cutoff = now - timedelta(days=self.policy.retention_days)
        kept: list[str] = []
        removed = 0
        with self._lock:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    record = json.loads(line)
                    timestamp = record.get("completed_at") or record.get("started_at")
                    parsed = datetime.fromisoformat(str(timestamp))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=UTC)
                    if parsed < cutoff:
                        removed += 1
                        continue
                except (TypeError, ValueError, json.JSONDecodeError):
                    # Retention must never destroy an event it cannot parse.
                    pass
                kept.append(line)
            if removed:
                tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
                with tmp.open("w", encoding="utf-8", newline="\n") as handle:
                    if kept:
                        handle.write("\n".join(kept) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, self.path)
        return removed


class OpenTelemetryAdapter:
    """Optional adapter: importing this module never requires an OTel backend."""

    def __init__(self, tracer=None) -> None:
        if tracer is not None:
            self._tracer = tracer
            return
        try:
            from opentelemetry import trace

            self._tracer = trace.get_tracer("twlongcare.rag")
        except ImportError:
            self._tracer = None

    def emit(self, trace_record: QueryTrace | dict[str, Any]) -> bool:
        if self._tracer is None:
            return False
        data = (
            trace_record.to_dict()
            if isinstance(trace_record, QueryTrace)
            else trace_record
        )
        with self._tracer.start_as_current_span("rag.query") as span:
            span.set_attribute("rag.request_id", data["request_id"])
            span.set_attribute("rag.run_id", data["run_id"])
            span.set_attribute("rag.route", data.get("route", {}).get("route", ""))
            span.set_attribute("rag.final_status", data.get("final_status", ""))
            span.set_attribute(
                "rag.latency.total_ms",
                float(data.get("latency_ms", {}).get("total", 0.0)),
            )
            span.add_event(
                "retrieval.confidence_gate",
                attributes={
                    "decision": data.get("confidence_gate", {}).get(
                        "decision", ""
                    )
                },
            )
        return True
