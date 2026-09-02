"""Append-only per-tenant cost ledger + rolling summary."""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.config import settings
from backend.cost.models import CostEvent
from backend.storage import tenant_store

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _month_key(ts: str | None = None) -> str:
    if ts:
        try:
            return ts[:7]  # YYYY-MM from ISO
        except Exception:  # noqa: BLE001
            pass
    return datetime.now(UTC).strftime("%Y-%m")


def _empty_bucket() -> dict[str, Any]:
    return {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "pages": 0,
        "credits": 0.0,
        "cost_usd": 0.0,
        "unpriced_calls": 0,
        "by_model": {},
    }


def _empty_month() -> dict[str, Any]:
    return {
        "openai": {"llm": _empty_bucket(), "embedding": _empty_bucket()},
        "gemini": {"llm": _empty_bucket()},
        "llamaparse": {"parse": _empty_bucket()},
        "textract": {"parse": _empty_bucket()},
        "local": {"embedding": _empty_bucket()},
        "total_usd": 0.0,
    }


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    tmp = path.with_name(f"{path.stem}.write{path.suffix}")
    tmp.write_text(text, encoding="utf-8")
    if path.is_file():
        path.unlink()
    tmp.replace(path)


def _metrics_dir() -> Path:
    base = (settings.observability_metrics_dir or "").strip()
    path = Path(base) if base else (settings.data_dir_path / "metrics")
    if not path.is_absolute():
        path = settings.resolve_path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def unattributed_events_path() -> Path:
    return _metrics_dir() / "cost_events_unattributed.jsonl"


def _bucket_for(summary_month: dict, provider: str, category: str) -> dict | None:
    prov = summary_month.get(provider)
    if not isinstance(prov, dict):
        prov = {}
        summary_month[provider] = prov
    bucket = prov.get(category)
    if not isinstance(bucket, dict):
        bucket = _empty_bucket()
        prov[category] = bucket
    return bucket


def _apply_event_to_bucket(bucket: dict, event: CostEvent) -> None:
    bucket["calls"] = int(bucket.get("calls", 0) or 0) + 1
    bucket["prompt_tokens"] = int(bucket.get("prompt_tokens", 0) or 0) + int(
        event.prompt_tokens or 0
    )
    bucket["completion_tokens"] = int(bucket.get("completion_tokens", 0) or 0) + int(
        event.completion_tokens or 0
    )
    bucket["pages"] = int(bucket.get("pages", 0) or 0) + int(event.pages or 0)
    bucket["credits"] = float(bucket.get("credits", 0.0) or 0.0) + float(
        event.credits or 0.0
    )
    bucket["cost_usd"] = round(
        float(bucket.get("cost_usd", 0.0) or 0.0) + float(event.cost_usd or 0.0), 6
    )
    if not event.priced:
        bucket["unpriced_calls"] = int(bucket.get("unpriced_calls", 0) or 0) + 1
    by_model = bucket.setdefault("by_model", {})
    key = (event.model_or_tier or "unknown").strip() or "unknown"
    row = by_model.setdefault(
        key,
        {
            "calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "pages": 0,
            "credits": 0.0,
            "cost_usd": 0.0,
            "unpriced_calls": 0,
        },
    )
    row["calls"] += 1
    row["prompt_tokens"] += int(event.prompt_tokens or 0)
    row["completion_tokens"] += int(event.completion_tokens or 0)
    row["pages"] += int(event.pages or 0)
    row["credits"] = round(float(row["credits"]) + float(event.credits or 0.0), 6)
    row["cost_usd"] = round(float(row["cost_usd"]) + float(event.cost_usd or 0.0), 6)
    if not event.priced:
        row["unpriced_calls"] += 1


def _update_summary(tenant_id: str, event: CostEvent) -> None:
    path = tenant_store.cost_summary_path(tenant_id)
    data: dict[str, Any] = {
        "tenant_id": tenant_store.normalize_tenant_id(tenant_id),
        "updated_at": _utcnow_iso(),
        "total_usd": 0.0,
        "by_month": {},
    }
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                data = existing
        except (OSError, ValueError):
            pass

    month = _month_key(event.ts)
    by_month = data.setdefault("by_month", {})
    month_row = by_month.get(month)
    if not isinstance(month_row, dict):
        month_row = _empty_month()
        by_month[month] = month_row

    bucket = _bucket_for(month_row, event.provider, event.category)
    if bucket is not None:
        _apply_event_to_bucket(bucket, event)

    month_row["total_usd"] = round(
        float(month_row.get("total_usd", 0.0) or 0.0) + float(event.cost_usd or 0.0), 6
    )
    data["total_usd"] = round(
        float(data.get("total_usd", 0.0) or 0.0) + float(event.cost_usd or 0.0), 6
    )
    data["updated_at"] = _utcnow_iso()
    data["tenant_id"] = tenant_store.normalize_tenant_id(tenant_id)
    _atomic_write_json(path, data)


def append_event(event: CostEvent) -> None:
    """Persist one cost event. Never raises — metering must not break the pipeline."""
    if not settings.cost_tracking_enabled:
        return
    try:
        with _lock:
            line = json.dumps(event.to_dict(), ensure_ascii=False)
            tid = (event.tenant_id or "").strip()
            if tid:
                path = tenant_store.cost_events_path(tid, month=_month_key(event.ts))
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
                _update_summary(tid, event)
            else:
                path = unattributed_events_path()
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
    except Exception:  # noqa: BLE001 - cost metering must never break callers
        logger.debug("cost ledger append failed", exc_info=True)
