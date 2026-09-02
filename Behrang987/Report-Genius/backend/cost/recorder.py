"""Public recorders + tenant attribution contextvar."""

from __future__ import annotations

import contextlib
import contextvars
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from backend.config import settings
from backend.cost import ledger, pricing
from backend.cost.models import CostEvent

logger = logging.getLogger(__name__)

_active_tenant: contextvars.ContextVar[str] = contextvars.ContextVar(
    "rics_cost_tenant", default=""
)


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


@contextlib.contextmanager
def tenant_scope(tenant_id: str) -> Iterator[None]:
    """Bind ``tenant_id`` for nested LLM / embed / parse calls in this context."""
    token = _active_tenant.set((tenant_id or "").strip())
    try:
        yield
    finally:
        _active_tenant.reset(token)


def resolve_tenant_id(explicit: str | None = None) -> str:
    """Resolution: explicit arg → tenant_scope → active ReportTrace → \"\"."""
    if (explicit or "").strip():
        return (explicit or "").strip()
    scoped = (_active_tenant.get() or "").strip()
    if scoped:
        return scoped
    try:
        from backend.observability import tracing

        trace = tracing._active_report.get()  # noqa: SLF001 - intentional bridge
        if trace is not None and (trace.tenant_id or "").strip():
            return (trace.tenant_id or "").strip()
    except Exception:  # noqa: BLE001
        logger.debug("cost tenant resolve from ReportTrace failed", exc_info=True)
    return ""


def _active_report_id() -> str:
    try:
        from backend.observability import tracing

        trace = tracing._active_report.get()  # noqa: SLF001
        if trace is not None:
            return (trace.report_id or "").strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


def _active_section_id() -> str:
    try:
        from backend.observability import tracing

        return (tracing._active_section.get() or "").strip()  # noqa: SLF001
    except Exception:  # noqa: BLE001
        return ""


def record_llm_cost(
    *,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    label: str = "",
    provider: str = "openai",
    tenant_id: str | None = None,
    report_id: str | None = None,
    section_id: str | None = None,
) -> None:
    """Record one chat/completions-style LLM call."""
    if not settings.cost_tracking_enabled:
        return
    try:
        pt = int(prompt_tokens or 0)
        ct = int(completion_tokens or 0)
        cost, priced = pricing.price_tokens(model or "", pt, ct)
        tid = resolve_tenant_id(tenant_id)
        event = CostEvent(
            ts=_utcnow_iso(),
            tenant_id=tid,
            provider=(provider or "openai").strip() or "openai",
            category="llm",
            model_or_tier=(model or "").strip(),
            units=float(pt + ct),
            unit_kind="tokens",
            cost_usd=cost,
            priced=priced,
            label=label or "llm",
            prompt_tokens=pt,
            completion_tokens=ct,
            report_id=(report_id if report_id is not None else _active_report_id()),
            section_id=(section_id if section_id is not None else _active_section_id()),
        )
        ledger.append_event(event)
    except Exception:  # noqa: BLE001
        logger.debug("record_llm_cost failed", exc_info=True)


def record_embedding_cost(
    *,
    model: str,
    prompt_tokens: int = 0,
    label: str = "embed",
    provider: str = "openai",
    tenant_id: str | None = None,
    document_id: str = "",
    texts_count: int = 0,
) -> None:
    """Record one embedding batch (OpenAI or local)."""
    if not settings.cost_tracking_enabled:
        return
    try:
        pt = int(prompt_tokens or 0)
        prov = (provider or "openai").strip() or "openai"
        if prov == "local":
            cost, priced = 0.0, True
        else:
            cost, priced = pricing.price_tokens(model or "", pt, 0)
        tid = resolve_tenant_id(tenant_id)
        extra: dict[str, Any] = {}
        if texts_count:
            extra["texts_count"] = int(texts_count)
        event = CostEvent(
            ts=_utcnow_iso(),
            tenant_id=tid,
            provider=prov,
            category="embedding",
            model_or_tier=(model or "").strip(),
            units=float(pt),
            unit_kind="tokens",
            cost_usd=cost,
            priced=priced,
            label=label or "embed",
            prompt_tokens=pt,
            completion_tokens=0,
            report_id=_active_report_id(),
            document_id=(document_id or "").strip(),
            section_id=_active_section_id(),
            extra=extra,
        )
        ledger.append_event(event)
    except Exception:  # noqa: BLE001
        logger.debug("record_embedding_cost failed", exc_info=True)


def record_parse_cost(
    *,
    provider: str,
    tier: str,
    pages: int,
    pages_source: str = "pdf",
    engine: str = "",
    label: str = "parse",
    tenant_id: str | None = None,
    document_id: str = "",
    priced_assumed: bool = False,
    api_page_count: int | None = None,
) -> None:
    """Record one document-parse job (LlamaParse / Textract)."""
    if not settings.cost_tracking_enabled:
        return
    try:
        n = max(0, int(pages or 0))
        prov = (provider or "llamaparse").strip() or "llamaparse"
        if prov == "llamaparse":
            cost, credits, priced = pricing.price_pages(tier, n)
        else:
            # Textract / other: record pages only; USD left for later pricing tables.
            cost, credits, priced = 0.0, 0.0, False
        tid = resolve_tenant_id(tenant_id)
        extra: dict[str, Any] = {}
        if api_page_count is not None:
            extra["api_page_count"] = int(api_page_count)
        event = CostEvent(
            ts=_utcnow_iso(),
            tenant_id=tid,
            provider=prov,
            category="parse",
            model_or_tier=(tier or "").strip(),
            units=float(n),
            unit_kind="pages",
            cost_usd=cost,
            priced=priced,
            priced_assumed=bool(priced_assumed),
            label=label or "parse",
            pages=n,
            pages_source=(pages_source or "").strip(),
            credits=float(credits),
            engine=(engine or "").strip(),
            report_id=_active_report_id(),
            document_id=(document_id or "").strip(),
            extra=extra,
        )
        ledger.append_event(event)
    except Exception:  # noqa: BLE001
        logger.debug("record_parse_cost failed", exc_info=True)
