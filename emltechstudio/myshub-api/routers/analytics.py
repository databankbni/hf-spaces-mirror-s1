"""Central analytics services for MyShub.

This module owns analytics collection and aggregation for:

* platform surfaces: the landing page, app shell, and Discover;
* individual public shops; and
* admin/shop dashboard response preparation.

The module intentionally keeps the existing shop analytics fields compatible. It
adds date-keyed fields for new data while preserving cumulative totals already
stored in shop_json.analytics.

Persistence model:
    * shop analytics remain in each shop's public shop_json record because that
      is the current MyShub contract;
    * platform-wide events are aggregated into one private Parquet file and do
      not expose raw IP addresses or passwords.

The router is included by main.py with no prefix. It exposes POST
/analytics/event for the static frontend event collector.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
import threading
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import pandas as pd
import requests
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from huggingface_hub import HfApi, hf_hub_download
from huggingface_hub.utils import EntryNotFoundError

from utils.db import get_shop_by_slug, update_shop


router = APIRouter()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HF_TOKEN = os.getenv("HF_TOKEN")
PRIVATE_REPO = os.getenv("PRIVATE_DATASET", "emltechstudio/myshub-db-private")
PLATFORM_ANALYTICS_FILE = os.getenv(
    "PLATFORM_ANALYTICS_FILE", "platform_analytics.parquet"
)
PLATFORM_FLUSH_DELAY = float(os.getenv("PLATFORM_ANALYTICS_FLUSH_DELAY", "30"))
# Keep history long enough for multi-year customer comparisons. Existing environment
# values remain supported, but the default is deliberately longer than one year.
MAX_SHOP_DAILY_DAYS = int(os.getenv("SHOP_ANALYTICS_RETENTION_DAYS", "3650"))
MAX_PLATFORM_DAYS = int(os.getenv("PLATFORM_ANALYTICS_RETENTION_DAYS", "3650"))

api = HfApi(token=HF_TOKEN)
_platform_lock = threading.RLock()
_platform_rows: Optional[List[dict]] = None
_platform_dirty = False
_platform_timer: Optional[threading.Timer] = None

_recent_event_keys: Dict[str, float] = {}
_recent_event_lock = threading.Lock()
RECENT_DEDUPE_SECONDS = 15 * 60

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

ALLOWED_EVENTS = {
    "page_view",
    "discover_search",
    "discover_result_open",
    "discover_shop_click",
    "shop_view",
    "shop_click",
    "signup_started",
    "signup_completed",
    "profile_completed",
}

ALLOWED_SURFACES = {"site", "app", "discover", "shop", "auth", "other"}

PLATFORM_COLUMNS = [
    "date",
    "surface",
    "event",
    "path",
    "shop_slug",
    "detail",
    "referrer",
    "country",
    "device",
    "count",
]


# ---------------------------------------------------------------------------
# General helpers
# ---------------------------------------------------------------------------


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_date_key(value: Optional[datetime] = None) -> str:
    return (value or utc_now()).strftime("%Y-%m-%d")


def parse_json_object(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        for parser in (json.loads, ast.literal_eval):
            try:
                value = parser(raw)
                if isinstance(value, dict):
                    return value
            except Exception:
                continue
    return {}


def sanitize_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): sanitize_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_json(v) for v in value]
    if isinstance(value, tuple):
        return [sanitize_json(v) for v in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def clean_text(value: Any, max_length: int = 240) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text[:max_length]


def normalize_slug(value: Any) -> str:
    return clean_text(value, 120).lower().strip()


def normalize_referrer(raw: Any) -> str:
    value = clean_text(raw, 240)
    if not value:
        return "direct"
    try:
        parsed = urlparse(value if "://" in value else f"https://{value}")
        host = parsed.netloc or parsed.path.split("/")[0]
        host = host.lower().removeprefix("www.")
        if host in {"myshub.site", "www.myshub.site"}:
            # Keep Discover attribution distinct when the frontend sends it.
            if "/discover" in parsed.path:
                return "myshub.site/discover"
            return "myshub.site"
        return host or "direct"
    except Exception:
        return "direct"


def classify_device(user_agent: Any) -> str:
    ua = clean_text(user_agent, 600).lower()
    if "ipad" in ua or "tablet" in ua:
        return "tablet"
    if any(token in ua for token in ("mobile", "android", "iphone", "ipod")):
        return "mobile"
    return "desktop"


def request_referrer(request: Optional[Request]) -> str:
    if request is None:
        return "direct"
    return normalize_referrer(request.headers.get("referer", ""))


def request_device(request: Optional[Request]) -> str:
    if request is None:
        return "unknown"
    return classify_device(request.headers.get("user-agent", ""))


def get_visitor_ip(request: Optional[Request]) -> str:
    if request is None:
        return "unknown"
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def get_country_from_ip(ip_address: str) -> str:
    try:
        if ip_address in {"127.0.0.1", "localhost", "::1"} or ip_address.startswith(("192.168.", "10.", "172.")):
            return "Local"
        if not ip_address or ip_address == "unknown":
            return "Unknown"
        response = requests.get(
            f"http://ip-api.com/json/{ip_address}?fields=country",
            timeout=2.5,
        )
        if response.ok:
            return clean_text(response.json().get("country", "Unknown"), 80) or "Unknown"
    except Exception:
        pass
    return "Unknown"


def request_country(request: Optional[Request]) -> str:
    if request is None:
        return "Unknown"
    for header in (
        "cf-ipcountry",
        "x-vercel-ip-country",
        "x-country",
    ):
        value = clean_text(request.headers.get(header, ""), 80)
        if value:
            return value.upper() if len(value) == 2 else value
    return get_country_from_ip(get_visitor_ip(request))


def request_client_fingerprint(request: Optional[Request]) -> str:
    """Return a short non-reversible fingerprint for in-memory deduplication.

    The fingerprint is never persisted. It exists only to prevent a frontend
    retry or repeated automatic page event from inflating platform counters.
    """
    if request is None:
        return "unknown"
    client_ip = request.headers.get("x-forwarded-for", "")
    if client_ip:
        client_ip = client_ip.split(",")[0].strip()
    if not client_ip and request.client:
        client_ip = request.client.host
    ua = request.headers.get("user-agent", "")
    raw = f"{client_ip}|{ua}"
    return hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()[:24]


def previous_period_range(period: str) -> Tuple[date, date]:
    end = utc_now().date()
    current_start, current_end = period_range(period)
    length = (current_end - current_start).days + 1
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=length - 1)
    return previous_start, previous_end


def period_range(period: str = "30d") -> Tuple[date, date]:
    today = utc_now().date()
    normalized = str(period or "30d").lower().strip()
    if normalized in {"today", "1d"}:
        return today, today
    if normalized in {"7d", "week", "7"}:
        return today - timedelta(days=6), today
    if normalized in {"90d", "quarter", "90"}:
        return today - timedelta(days=89), today
    if normalized in {"365d", "12m", "year", "12"}:
        return today - timedelta(days=364), today
    if normalized in {"730d", "24m", "2y", "2years"}:
        return today - timedelta(days=729), today
    if normalized in {"1095d", "36m", "3y", "3years"}:
        return today - timedelta(days=1094), today
    if normalized in {"1825d", "60m", "5y", "5years"}:
        return today - timedelta(days=1824), today
    if normalized in {"3650d", "120m", "10y", "10years", "all", "all_time"}:
        return today - timedelta(days=MAX_SHOP_DAILY_DAYS - 1), today
    return today - timedelta(days=29), today


def period_days(period: str = "30d") -> int:
    normalized = str(period or "30d").lower().strip()
    if normalized in {"today", "1d"}:
        return 1
    if normalized in {"7d", "week", "7"}:
        return 7
    if normalized in {"90d", "quarter", "90"}:
        return 90
    if normalized in {"365d", "12m", "year", "12"}:
        return 365
    if normalized in {"730d", "24m", "2y", "2years"}:
        return 730
    if normalized in {"1095d", "36m", "3y", "3years"}:
        return 1095
    if normalized in {"1825d", "60m", "5y", "5years"}:
        return 1825
    if normalized in {"3650d", "120m", "10y", "10years", "all", "all_time"}:
        return MAX_SHOP_DAILY_DAYS
    return 30


def period_allowed_for_plan(period: str, plan: str) -> bool:
    normalized_plan = str(plan or "free").lower().strip()
    days = period_days(period)
    if normalized_plan == "premium":
        return days <= MAX_SHOP_DAILY_DAYS
    if normalized_plan == "pro":
        return days <= 365
    return days <= 30


def iter_dates(start: date, end: date) -> Iterable[str]:
    cursor = start
    while cursor <= end:
        yield cursor.isoformat()
        cursor += timedelta(days=1)


def safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except Exception:
        return 0


def merge_counter(target: Dict[str, int], source: Any) -> None:
    if not isinstance(source, dict):
        return
    for key, value in source.items():
        name = clean_text(key, 180) or "Unknown"
        target[name] = target.get(name, 0) + safe_int(value)


def total_clicks(clicks: Any) -> int:
    if not isinstance(clicks, dict):
        return 0
    total = safe_int(clicks.get("catalog")) + safe_int(clicks.get("whatsapp"))
    for key in ("socials", "custom_links", "custom"):
        value = clicks.get(key)
        if isinstance(value, dict):
            total += sum(safe_int(v) for v in value.values())
    return total


def empty_clicks() -> dict:
    return {
        "catalog": 0,
        "whatsapp": 0,
        "catalog_details": {},
        "whatsapp_details": {},
        "socials": {},
        "custom_links": {},
    }


def add_clicks(target: dict, source: Any) -> None:
    if not isinstance(source, dict):
        return
    target["catalog"] += safe_int(source.get("catalog"))
    target["whatsapp"] += safe_int(source.get("whatsapp"))
    for key in ("catalog_details", "whatsapp_details", "socials", "custom_links", "custom"):
        source_map = source.get(key)
        if not isinstance(source_map, dict):
            continue
        output_key = "custom_links" if key == "custom" else key
        if output_key not in target or not isinstance(target.get(output_key), dict):
            target[output_key] = {}
        for name, value in source_map.items():
            target[output_key][clean_text(name, 180)] = (
                target[output_key].get(clean_text(name, 180), 0) + safe_int(value)
            )


# ---------------------------------------------------------------------------
# Platform analytics persistence
# ---------------------------------------------------------------------------


def _empty_platform_rows() -> List[dict]:
    return []


def _load_platform_rows() -> List[dict]:
    global _platform_rows
    if _platform_rows is not None:
        return _platform_rows
    with _platform_lock:
        if _platform_rows is not None:
            return _platform_rows
        try:
            local_path = hf_hub_download(
                repo_id=PRIVATE_REPO,
                filename=PLATFORM_ANALYTICS_FILE,
                repo_type="dataset",
                token=HF_TOKEN,
            )
            frame = pd.read_parquet(local_path)
            rows = frame.to_dict("records")
            normalized = []
            for row in rows:
                item = {column: row.get(column, "") for column in PLATFORM_COLUMNS}
                item["count"] = safe_int(item.get("count"))
                normalized.append(item)
            _platform_rows = normalized
        except EntryNotFoundError:
            _platform_rows = _empty_platform_rows()
        except Exception as exc:
            print(f"[Analytics] platform load error: {exc}")
            _platform_rows = _empty_platform_rows()
        return _platform_rows


def _write_platform_rows(rows: List[dict]) -> None:
    frame = pd.DataFrame(rows, columns=PLATFORM_COLUMNS)
    if not frame.empty:
        frame["count"] = pd.to_numeric(frame["count"], errors="coerce").fillna(0).astype("int64")
    else:
        frame = pd.DataFrame({
            "date": pd.Series(dtype="object"),
            "surface": pd.Series(dtype="object"),
            "event": pd.Series(dtype="object"),
            "path": pd.Series(dtype="object"),
            "shop_slug": pd.Series(dtype="object"),
            "detail": pd.Series(dtype="object"),
            "referrer": pd.Series(dtype="object"),
            "country": pd.Series(dtype="object"),
            "device": pd.Series(dtype="object"),
            "count": pd.Series(dtype="int64"),
        })
    buffer = BytesIO()
    frame.to_parquet(buffer, index=False)
    buffer.seek(0)
    api.upload_file(
        path_or_fileobj=buffer,
        path_in_repo=PLATFORM_ANALYTICS_FILE,
        repo_id=PRIVATE_REPO,
        repo_type="dataset",
        token=HF_TOKEN,
    )


def _flush_platform_rows() -> None:
    global _platform_dirty, _platform_timer
    with _platform_lock:
        if not _platform_dirty or _platform_rows is None:
            _platform_timer = None
            return
        rows = list(_platform_rows)
        _platform_dirty = False
        _platform_timer = None
    try:
        _write_platform_rows(rows)
    except Exception as exc:
        print(f"[Analytics] platform flush error: {exc}")
        with _platform_lock:
            _platform_dirty = True
            _schedule_platform_flush_locked()


def _schedule_platform_flush_locked() -> None:
    global _platform_timer
    if _platform_timer is not None:
        _platform_timer.cancel()
    _platform_timer = threading.Timer(PLATFORM_FLUSH_DELAY, _flush_platform_rows)
    _platform_timer.daemon = True
    _platform_timer.start()


def flush_platform_analytics() -> None:
    _flush_platform_rows()


def _trim_platform_rows_locked() -> None:
    cutoff = utc_now().date() - timedelta(days=MAX_PLATFORM_DAYS - 1)
    cutoff_key = cutoff.isoformat()
    if _platform_rows is not None:
        _platform_rows[:] = [
            row for row in _platform_rows if str(row.get("date", "")) >= cutoff_key
        ]


def _platform_row_key(row: dict) -> Tuple[str, ...]:
    return tuple(str(row.get(column, "")) for column in PLATFORM_COLUMNS[:-1])


def _record_platform_row(
    *,
    event: str,
    surface: str,
    path: str = "",
    shop_slug: str = "",
    detail: str = "",
    referrer: str = "direct",
    country: str = "Unknown",
    device: str = "unknown",
    event_date: Optional[str] = None,
    count: int = 1,
) -> bool:
    rows = _load_platform_rows()
    normalized = {
        "date": event_date or utc_date_key(),
        "surface": surface,
        "event": event,
        "path": clean_text(path, 240),
        "shop_slug": normalize_slug(shop_slug),
        "detail": clean_text(detail, 180),
        "referrer": normalize_referrer(referrer),
        "country": clean_text(country, 80) or "Unknown",
        "device": clean_text(device, 30) or "unknown",
        "count": safe_int(count),
    }
    if normalized["count"] <= 0:
        return False
    key = _platform_row_key(normalized)
    with _platform_lock:
        for row in rows:
            if _platform_row_key(row) == key:
                row["count"] = safe_int(row.get("count")) + normalized["count"]
                break
        else:
            rows.append(normalized)
        _trim_platform_rows_locked()
        global _platform_dirty
        _platform_dirty = True
        _schedule_platform_flush_locked()
    return True


def _should_dedupe(event: str) -> bool:
    return event in {"page_view", "discover_search", "shop_view"}


def _dedupe_event(request: Optional[Request], event: str, surface: str, path: str, shop_slug: str, detail: str) -> bool:
    if not _should_dedupe(event):
        return False
    fingerprint = request_client_fingerprint(request)
    minute_bucket = int(utc_now().timestamp() // RECENT_DEDUPE_SECONDS)
    raw = f"{fingerprint}|{event}|{surface}|{path}|{shop_slug}|{detail}|{minute_bucket}"
    key = hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()
    now_ts = utc_now().timestamp()
    with _recent_event_lock:
        stale = [k for k, seen in _recent_event_keys.items() if now_ts - seen > RECENT_DEDUPE_SECONDS * 2]
        for stale_key in stale:
            _recent_event_keys.pop(stale_key, None)
        if key in _recent_event_keys:
            return True
        _recent_event_keys[key] = now_ts
    return False


def record_event(
    request: Optional[Request],
    event: str,
    surface: str,
    *,
    path: str = "",
    shop_slug: str = "",
    detail: str = "",
    count: int = 1,
    referrer: Optional[str] = None,
    country: Optional[str] = None,
    device: Optional[str] = None,
) -> bool:
    """Record a validated platform event as a daily aggregate.

    No IP address, password, or raw user-agent is persisted. A short in-memory
    fingerprint is used only for deduplication of automatic page events.
    """
    event = clean_text(event, 60).lower()
    surface = clean_text(surface, 30).lower()
    if event not in ALLOWED_EVENTS or surface not in ALLOWED_SURFACES:
        return False
    path = clean_text(path, 240)
    shop_slug = normalize_slug(shop_slug)
    detail = clean_text(detail, 180)
    if _dedupe_event(request, event, surface, path, shop_slug, detail):
        return False
    try:
        return _record_platform_row(
            event=event,
            surface=surface,
            path=path,
            shop_slug=shop_slug,
            detail=detail,
            referrer=referrer if referrer is not None else request_referrer(request),
            country=country if country is not None else request_country(request),
            device=device if device is not None else request_device(request),
            count=count,
        )
    except Exception as exc:
        # Platform analytics must never break registration, shop views, or clicks.
        print(f"[Analytics] event record error: {exc}")
        return False


class AnalyticsEvent(BaseModel):
    event: str = Field(..., min_length=1, max_length=60)
    surface: str = Field(..., min_length=1, max_length=30)
    path: str = Field(default="", max_length=240)
    shop_slug: str = Field(default="", max_length=120)
    detail: str = Field(default="", max_length=180)
    count: int = Field(default=1, ge=1, le=20)


@router.post("/analytics/event")
def collect_event(payload: AnalyticsEvent, request: Request):
    """Public, allow-listed event collector for static frontends."""
    accepted = record_event(
        request,
        payload.event,
        payload.surface,
        path=payload.path,
        shop_slug=payload.shop_slug,
        detail=payload.detail,
        count=payload.count,
    )
    return {"ok": True, "accepted": accepted}


# ---------------------------------------------------------------------------
# Shop analytics collection
# ---------------------------------------------------------------------------


def _shop_analytics(shop: dict) -> Tuple[dict, dict]:
    shop_json = parse_json_object(shop.get("shop_json", {}))
    analytics = shop_json.get("analytics")
    if not isinstance(analytics, dict):
        analytics = {}
        shop_json["analytics"] = analytics
    return shop_json, analytics


def _increment_nested_counter(container: dict, key: str, amount: int = 1) -> None:
    container[key] = safe_int(container.get(key)) + safe_int(amount)


def _get_daily_map(analytics: dict, key: str) -> dict:
    value = analytics.get(key)
    return value if isinstance(value, dict) else {}


def _prune_daily_map(daily: dict, retention_days: int = MAX_SHOP_DAILY_DAYS) -> None:
    cutoff = utc_now().date() - timedelta(days=retention_days - 1)
    cutoff_key = cutoff.isoformat()
    for key in list(daily.keys()):
        if isinstance(key, str) and DATE_RE.match(key) and key < cutoff_key:
            daily.pop(key, None)


def record_shop_view(
    shop: dict,
    request: Optional[Request] = None,
    *,
    is_owner_preview: bool = False,
) -> Optional[dict]:
    """Record a public shop view and update compatible daily analytics."""
    if not shop or is_owner_preview:
        return shop
    shop_json, analytics = _shop_analytics(shop)
    today = utc_date_key()
    analytics["visit_count"] = safe_int(analytics.get("visit_count")) + 1
    daily_visits = _get_daily_map(analytics, "daily_visits")
    _increment_nested_counter(daily_visits, today)
    analytics["daily_visits"] = daily_visits

    # Preserve existing cumulative fields while also recording date buckets.
    referrer = request_referrer(request)
    referrers = analytics.setdefault("referrers", {})
    _increment_nested_counter(referrers, referrer)
    daily_referrers = analytics.setdefault("daily_referrers", {})
    daily_referrers.setdefault(today, {})
    _increment_nested_counter(daily_referrers[today], referrer)

    device = request_device(request)
    devices = analytics.setdefault("devices", {"mobile": 0, "desktop": 0, "tablet": 0})
    _increment_nested_counter(devices, device)
    daily_devices = analytics.setdefault("daily_devices", {})
    daily_devices.setdefault(today, {"mobile": 0, "desktop": 0, "tablet": 0})
    _increment_nested_counter(daily_devices[today], device)

    country = request_country(request)
    countries = analytics.setdefault("countries", {})
    _increment_nested_counter(countries, country)
    daily_countries = analytics.setdefault("daily_countries", {})
    daily_countries.setdefault(today, {})
    _increment_nested_counter(daily_countries[today], country)

    analytics["last_visit"] = utc_now().isoformat()
    _prune_daily_map(daily_visits)
    _prune_daily_map(daily_referrers)
    _prune_daily_map(daily_devices)
    _prune_daily_map(daily_countries)
    update_shop(shop["slug"], {"shop_json": shop_json})
    record_event(request, "shop_view", "shop", path=f"/{shop['slug']}", shop_slug=shop["slug"])
    return shop


def _ensure_click_shape(analytics: dict) -> dict:
    clicks = analytics.get("clicks")
    if not isinstance(clicks, dict):
        clicks = empty_clicks()
    clicks.setdefault("catalog", 0)
    clicks.setdefault("whatsapp", 0)
    clicks.setdefault("catalog_details", {})
    clicks.setdefault("whatsapp_details", {})
    clicks.setdefault("socials", {})
    clicks.setdefault("custom_links", clicks.get("custom", {}))
    if not isinstance(clicks.get("catalog_details"), dict):
        clicks["catalog_details"] = {}
    if not isinstance(clicks.get("whatsapp_details"), dict):
        clicks["whatsapp_details"] = {}
    if not isinstance(clicks.get("socials"), dict):
        clicks["socials"] = {}
    if not isinstance(clicks.get("custom_links"), dict):
        clicks["custom_links"] = {}
    analytics["clicks"] = clicks
    return clicks


def _ensure_daily_click_shape(bucket: Any) -> dict:
    if not isinstance(bucket, dict):
        bucket = empty_clicks()
    bucket.setdefault("catalog", 0)
    bucket.setdefault("whatsapp", 0)
    bucket.setdefault("catalog_details", {})
    bucket.setdefault("whatsapp_details", {})
    bucket.setdefault("socials", {})
    bucket.setdefault("custom_links", bucket.get("custom", {}))
    for key in ("catalog_details", "whatsapp_details", "socials", "custom_links"):
        if not isinstance(bucket.get(key), dict):
            bucket[key] = {}
    return bucket


def record_shop_clicks(
    slug: str,
    click_items: Iterable[Any],
    request: Optional[Request] = None,
) -> Optional[dict]:
    """Record a batch of shop clicks, preserving old and new schemas."""
    shop = get_shop_by_slug(normalize_slug(slug))
    if not shop:
        return None
    if shop.get("plan", "free") == "free":
        return shop
    shop_json, analytics = _shop_analytics(shop)
    clicks = _ensure_click_shape(analytics)
    today = utc_date_key()
    daily_clicks = analytics.setdefault("daily_clicks", {})
    daily_clicks[today] = _ensure_daily_click_shape(daily_clicks.get(today))

    for item in click_items:
        item_type = clean_text(getattr(item, "type", None) if not isinstance(item, dict) else item.get("type"), 40).lower()
        detail = clean_text(getattr(item, "detail", None) if not isinstance(item, dict) else item.get("detail"), 180)
        amount = safe_int(getattr(item, "count", 1) if not isinstance(item, dict) else item.get("count", 1))
        if amount <= 0:
            continue
        if item_type == "catalog":
            clicks["catalog"] += amount
            daily_clicks[today]["catalog"] += amount
            clicks["catalog_details"][detail or "catalog"] = safe_int(clicks["catalog_details"].get(detail or "catalog")) + amount
            daily_clicks[today]["catalog_details"][detail or "catalog"] = safe_int(daily_clicks[today]["catalog_details"].get(detail or "catalog")) + amount
        elif item_type == "whatsapp":
            clicks["whatsapp"] += amount
            daily_clicks[today]["whatsapp"] += amount
            clicks["whatsapp_details"][detail or "whatsapp"] = safe_int(clicks["whatsapp_details"].get(detail or "whatsapp")) + amount
            daily_clicks[today]["whatsapp_details"][detail or "whatsapp"] = safe_int(daily_clicks[today]["whatsapp_details"].get(detail or "whatsapp")) + amount
        elif item_type in {"social", "socials"}:
            clicks["socials"][detail] = safe_int(clicks["socials"].get(detail)) + amount
            daily_clicks[today]["socials"][detail] = safe_int(daily_clicks[today]["socials"].get(detail)) + amount
        elif item_type in {"custom_link", "custom", "link"}:
            clicks["custom_links"][detail] = safe_int(clicks["custom_links"].get(detail)) + amount
            daily_clicks[today]["custom_links"][detail] = safe_int(daily_clicks[today]["custom_links"].get(detail)) + amount
        else:
            continue
        try:
            record_event(
                request,
                "shop_click",
                "shop",
                path=f"/{shop['slug']}",
                shop_slug=shop["slug"],
                detail=f"{item_type}:{detail}" if detail else item_type,
                count=amount,
            )
        except Exception as exc:
            # Keep shop click persistence independent from platform analytics.
            print(f"[Analytics] shop click event error: {exc}")

    analytics["clicks"] = clicks
    _prune_daily_map(daily_clicks)
    shop_json["analytics"] = analytics
    update_shop(shop["slug"], {"shop_json": shop_json})
    return shop


# ---------------------------------------------------------------------------
# Shop analytics normalization and aggregation
# ---------------------------------------------------------------------------


def _date_bucket_map(analytics: dict, primary_keys: Iterable[str]) -> dict:
    """Find a date-keyed map across compatible analytics schema variants."""
    for key in primary_keys:
        value = analytics.get(key)
        if isinstance(value, dict) and any(DATE_RE.match(str(k)) for k in value.keys()):
            return value
    daily = analytics.get("daily")
    if isinstance(daily, dict):
        date_keys = {k: v for k, v in daily.items() if DATE_RE.match(str(k))}
        if date_keys:
            return date_keys
    return {}


def _daily_click_map(analytics: dict) -> dict:
    # Supports daily_clicks, daily analytics buckets, and a date-keyed clicks map.
    value = _date_bucket_map(analytics, ("daily_clicks", "clicks_by_day"))
    if value:
        return value
    clicks = analytics.get("clicks")
    if isinstance(clicks, dict) and any(DATE_RE.match(str(k)) for k in clicks):
        return clicks
    daily = analytics.get("daily")
    if isinstance(daily, dict):
        output = {}
        for key, bucket in daily.items():
            if DATE_RE.match(str(key)) and isinstance(bucket, dict):
                if "clicks" in bucket:
                    output[key] = bucket.get("clicks", {})
        return output
    return {}


def _daily_submap(analytics: dict, name: str) -> dict:
    direct = _date_bucket_map(analytics, (f"daily_{name}", f"{name}_by_day"))
    if direct:
        return direct
    daily = analytics.get("daily")
    if isinstance(daily, dict):
        output = {}
        for key, bucket in daily.items():
            if DATE_RE.match(str(key)) and isinstance(bucket, dict):
                if name in bucket:
                    output[key] = bucket[name]
        return output
    return {}


def _period_daily_visits(analytics: dict) -> dict:
    value = _date_bucket_map(analytics, ("daily_visits", "visits_by_day"))
    if value:
        return {str(k): safe_int(v) for k, v in value.items()}
    daily = analytics.get("daily")
    if isinstance(daily, dict):
        output = {}
        for key, bucket in daily.items():
            if DATE_RE.match(str(key)) and isinstance(bucket, dict):
                output[key] = safe_int(bucket.get("visits", bucket.get("visit_count", 0)))
        return output
    return {}


def _aggregate_daily_clicks(daily_clicks: dict, start: date, end: date) -> dict:
    output = empty_clicks()
    for day_key, bucket in daily_clicks.items():
        if not DATE_RE.match(str(day_key)):
            continue
        if not (start.isoformat() <= str(day_key) <= end.isoformat()):
            continue
        add_clicks(output, bucket)
    return output


def _aggregate_daily_map(daily_map: dict, start: date, end: date) -> dict:
    output: Dict[str, int] = {}
    for day_key, bucket in daily_map.items():
        if not DATE_RE.match(str(day_key)):
            continue
        if not (start.isoformat() <= str(day_key) <= end.isoformat()):
            continue
        merge_counter(output, bucket)
    return output


def _daily_rows_for_shop(analytics: dict, start: date, end: date) -> List[dict]:
    visits = _period_daily_visits(analytics)
    daily_clicks = _daily_click_map(analytics)
    daily_referrers = _daily_submap(analytics, "referrers")
    daily_countries = _daily_submap(analytics, "countries")
    daily_devices = _daily_submap(analytics, "devices")
    rows = []
    for day_key in iter_dates(start, end):
        clicks = empty_clicks()
        add_clicks(clicks, daily_clicks.get(day_key, {}))
        rows.append({
            "date": day_key,
            "visits": safe_int(visits.get(day_key)),
            "actions": total_clicks(clicks),
            "clicks": clicks,
            "referrers": daily_referrers.get(day_key, {}) if isinstance(daily_referrers.get(day_key), dict) else {},
            "countries": daily_countries.get(day_key, {}) if isinstance(daily_countries.get(day_key), dict) else {},
            "devices": daily_devices.get(day_key, {}) if isinstance(daily_devices.get(day_key), dict) else {},
        })
    return rows


def _sum_daily_dimension(rows: List[dict], dimension: str) -> dict:
    output: Dict[str, int] = {}
    for row in rows:
        merge_counter(output, row.get(dimension, {}))
    return output


def _sum_daily_clicks(rows: List[dict]) -> dict:
    output = empty_clicks()
    for row in rows:
        add_clicks(output, row.get("clicks", {}))
    return output


def _percentage(value: int, total: int) -> float:
    return round((value / total) * 100, 1) if total else 0.0


def _with_percentages(counter: dict) -> dict:
    total = sum(safe_int(v) for v in counter.values())
    return {
        key: {"count": safe_int(value), "percentage": _percentage(safe_int(value), total)}
        for key, value in sorted(counter.items(), key=lambda item: safe_int(item[1]), reverse=True)
    }


def _click_breakdown(clicks: dict) -> dict:
    categories = {
        "catalog": safe_int(clicks.get("catalog")),
        "whatsapp": safe_int(clicks.get("whatsapp")),
        "socials": sum(safe_int(v) for v in (clicks.get("socials") or {}).values()),
        "custom_links": sum(safe_int(v) for v in (clicks.get("custom_links") or {}).values()),
    }
    total = sum(categories.values())
    return {
        key: {"count": value, "percentage": _percentage(value, total)}
        for key, value in categories.items()
    }


def _period_summary(rows: List[dict], all_time_clicks: Optional[dict] = None) -> dict:
    visits = sum(safe_int(row.get("visits")) for row in rows)
    clicks = _sum_daily_clicks(rows)
    actions = total_clicks(clicks)
    # For old records without daily clicks, expose all-time clicks only when the
    # caller asks for an all-time period. Never label cumulative clicks as a
    # seven-day or thirty-day value.
    if actions == 0 and all_time_clicks is not None:
        clicks = all_time_clicks
        actions = total_clicks(clicks)
    best_day = max(rows, key=lambda row: safe_int(row.get("visits")), default={})
    return {
        "visits": visits,
        "actions": actions,
        "action_rate": _percentage(actions, visits),
        "clicks": clicks,
        "click_breakdown": _click_breakdown(clicks),
        "best_day": {
            "date": best_day.get("date", ""),
            "visits": safe_int(best_day.get("visits")),
        },
    }


def _change_percentage(current: int, previous: int) -> Optional[float]:
    if previous <= 0:
        return None
    return round(((current - previous) / previous) * 100, 1)


def _year_over_year_summary(analytics: dict) -> dict:
    """Compare the latest 365 days with the preceding 365 days.

    This is calculated from the retained daily buckets. It never invents a
    value when the previous period has no measured baseline.
    """
    current_start, current_end = period_range("365d")
    previous_start, previous_end = previous_period_range("365d")
    current_rows = _daily_rows_for_shop(analytics, current_start, current_end)
    previous_rows = _daily_rows_for_shop(analytics, previous_start, previous_end)
    current = _period_summary(current_rows)
    previous = _period_summary(previous_rows)
    return {
        "current": current,
        "previous": previous,
        "current_from": current_start.isoformat(),
        "current_to": current_end.isoformat(),
        "previous_from": previous_start.isoformat(),
        "previous_to": previous_end.isoformat(),
        "visits_change_percentage": _change_percentage(current["visits"], previous["visits"]),
        "actions_change_percentage": _change_percentage(current["actions"], previous["actions"]),
    }


def get_shop_analytics(slug: str, period: str = "30d") -> Optional[dict]:
    """Return a period-aware analytics response for one shop."""
    shop = get_shop_by_slug(normalize_slug(slug))
    if not shop:
        return None
    shop_json, analytics = _shop_analytics(shop)
    start, end = period_range(period)
    previous_start, previous_end = previous_period_range(period)
    rows = _daily_rows_for_shop(analytics, start, end)
    previous_rows = _daily_rows_for_shop(analytics, previous_start, previous_end)
    all_time_clicks = _ensure_click_shape(dict(analytics)).copy()
    all_time_clicks = parse_json_object(analytics.get("clicks", empty_clicks()))
    summary = _period_summary(rows)
    previous_summary = _period_summary(previous_rows)
    change = _change_percentage(summary["visits"], previous_summary["visits"])
    summary["previous_period_visits"] = previous_summary["visits"]
    summary["previous_period_actions"] = previous_summary["actions"]
    summary["visits_change_percentage"] = change
    cumulative_clicks = parse_json_object(analytics.get("clicks", empty_clicks()))
    referrers = _sum_daily_dimension(rows, "referrers")
    countries = _sum_daily_dimension(rows, "countries")
    devices = _sum_daily_dimension(rows, "devices")
    # If daily dimensions do not exist yet, expose cumulative values only in
    # the explicit all-time response; the UI can mark them as all-time data.
    if not referrers and period in {"all", "all_time"}:
        referrers = analytics.get("referrers", {}) if isinstance(analytics.get("referrers"), dict) else {}
    if not countries and period in {"all", "all_time"}:
        countries = analytics.get("countries", {}) if isinstance(analytics.get("countries"), dict) else {}
    if not devices and period in {"all", "all_time"}:
        devices = analytics.get("devices", {}) if isinstance(analytics.get("devices"), dict) else {}
    return sanitize_json({
        "slug": shop.get("slug", normalize_slug(slug)),
        "plan": shop.get("plan", "free"),
        "period": period,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "summary": summary,
        "daily": rows,
        "referrers": _with_percentages(referrers),
        "countries": _with_percentages(countries),
        "devices": _with_percentages(devices),
        "year_over_year": _year_over_year_summary(analytics),
        "all_time": {
            "visits": safe_int(analytics.get("visit_count")),
            "clicks": cumulative_clicks,
            "referrers": _with_percentages(analytics.get("referrers", {})),
            "countries": _with_percentages(analytics.get("countries", {})),
            "devices": _with_percentages(analytics.get("devices", {})),
        },
        "last_updated": analytics.get("last_visit", ""),
        "data_notes": {
            "visits": "Tracked public shop visits; owner previews are excluded.",
            "actions": "Tracked catalogue, WhatsApp, social, and custom-link clicks.",
            "unique_visitors": "Not currently reported as a guaranteed unique-person metric.",
        },
    })


# ---------------------------------------------------------------------------
# Platform-wide aggregation
# ---------------------------------------------------------------------------


def _platform_rows_in_period(period: str) -> Tuple[List[dict], date, date]:
    start, end = period_range(period)
    start_key, end_key = start.isoformat(), end.isoformat()
    rows = [
        row for row in (_load_platform_rows() or [])
        if start_key <= str(row.get("date", "")) <= end_key
    ]
    return rows, start, end


def _counter_from_platform(rows: List[dict], field: str) -> dict:
    output: Dict[str, int] = {}
    for row in rows:
        key = clean_text(row.get(field), 180) or "Unknown"
        output[key] = output.get(key, 0) + safe_int(row.get("count"))
    return output


def get_platform_analytics(period: str = "30d") -> dict:
    rows, start, end = _platform_rows_in_period(period)
    daily = defaultdict(lambda: {"page_views": 0, "events": 0, "actions": 0})
    surfaces: Dict[str, int] = {}
    events: Dict[str, int] = {}
    referrers: Dict[str, int] = {}
    countries: Dict[str, int] = {}
    devices: Dict[str, int] = {}
    paths: Dict[str, int] = {}
    shops: Dict[str, int] = {}
    for row in rows:
        count = safe_int(row.get("count"))
        day = str(row.get("date", ""))
        event = clean_text(row.get("event"), 60)
        surface = clean_text(row.get("surface"), 30)
        daily[day]["events"] += count
        events[event] = events.get(event, 0) + count
        surfaces[surface] = surfaces.get(surface, 0) + count
        if event == "page_view" or event == "shop_view":
            daily[day]["page_views"] += count
        if event in {"shop_click", "discover_shop_click", "discover_result_open", "signup_started", "signup_completed", "profile_completed"}:
            daily[day]["actions"] += count
        ref = clean_text(row.get("referrer"), 180) or "direct"
        referrers[ref] = referrers.get(ref, 0) + count
        country = clean_text(row.get("country"), 80) or "Unknown"
        countries[country] = countries.get(country, 0) + count
        device = clean_text(row.get("device"), 30) or "unknown"
        devices[device] = devices.get(device, 0) + count
        path = clean_text(row.get("path"), 240)
        if path:
            paths[path] = paths.get(path, 0) + count
        shop_slug = normalize_slug(row.get("shop_slug"))
        if shop_slug:
            shops[shop_slug] = shops.get(shop_slug, 0) + count
    daily_rows = []
    for day_key in iter_dates(start, end):
        daily_rows.append({"date": day_key, **daily.get(day_key, {"page_views": 0, "events": 0, "actions": 0})})
    page_views = sum(item["page_views"] for item in daily_rows)
    actions = sum(item["actions"] for item in daily_rows)
    return sanitize_json({
        "period": period,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "summary": {
            "page_views": page_views,
            "events": sum(item["events"] for item in daily_rows),
            "actions": actions,
            "action_rate": _percentage(actions, page_views),
        },
        "daily": daily_rows,
        "surfaces": _with_percentages(surfaces),
        "events": _with_percentages(events),
        "referrers": _with_percentages(referrers),
        "countries": _with_percentages(countries),
        "devices": _with_percentages(devices),
        "top_paths": _with_percentages(paths),
        "top_shops": _with_percentages(shops),
        "last_updated": utc_now().isoformat(),
    })


def get_discover_analytics(period: str = "30d") -> dict:
    response = get_platform_analytics(period)
    allowed_surfaces = {"discover"}
    rows, start, end = _platform_rows_in_period(period)
    discover_rows = [row for row in rows if row.get("surface") in allowed_surfaces]
    # Reuse platform aggregation logic by temporarily aggregating the filtered
    # rows directly. This keeps the response shape familiar.
    events: Dict[str, int] = {}
    shops: Dict[str, int] = {}
    paths: Dict[str, int] = {}
    referrers: Dict[str, int] = {}
    daily = defaultdict(lambda: {"page_views": 0, "events": 0, "actions": 0})
    for row in discover_rows:
        count = safe_int(row.get("count"))
        day = str(row.get("date", ""))
        event = clean_text(row.get("event"), 60)
        events[event] = events.get(event, 0) + count
        daily[day]["events"] += count
        if event == "page_view":
            daily[day]["page_views"] += count
        if event in {"discover_shop_click", "discover_result_open", "signup_started", "signup_completed"}:
            daily[day]["actions"] += count
        slug = normalize_slug(row.get("shop_slug"))
        if slug:
            shops[slug] = shops.get(slug, 0) + count
        path = clean_text(row.get("path"), 240)
        if path:
            paths[path] = paths.get(path, 0) + count
        ref = clean_text(row.get("referrer"), 180) or "direct"
        referrers[ref] = referrers.get(ref, 0) + count
    daily_rows = []
    for day_key in iter_dates(start, end):
        daily_rows.append({"date": day_key, **daily.get(day_key, {"page_views": 0, "events": 0, "actions": 0})})
    return sanitize_json({
        "period": period,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "summary": {
            "page_views": sum(item["page_views"] for item in daily_rows),
            "events": sum(item["events"] for item in daily_rows),
            "actions": sum(item["actions"] for item in daily_rows),
        },
        "daily": daily_rows,
        "events": _with_percentages(events),
        "top_shops": _with_percentages(shops),
        "top_paths": _with_percentages(paths),
        "referrers": _with_percentages(referrers),
        "platform_summary": response.get("summary", {}),
    })


# ---------------------------------------------------------------------------
# Shutdown safety
# ---------------------------------------------------------------------------


try:
    import atexit

    atexit.register(flush_platform_analytics)
except Exception:
    pass
