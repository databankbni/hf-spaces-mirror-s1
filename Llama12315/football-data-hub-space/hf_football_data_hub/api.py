"""HF Football Data Hub — FastAPI app with lifecycle keepalive support.

Endpoints marked LIFECYCLE ( /health, /ready, /warmup, /keepalive-status )
must never be removed or change field semantics — only backward-compatible
extension is permitted as the project evolves through Phase 2B → Phase 3 → Final.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
import secrets
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Header, BackgroundTasks
from pydantic import BaseModel, Field

from .settings import settings
import collect_api  # noqa: E402  (cloud collector, data-only)
from .dataset_store import store, rel_hot_pool, rel_crow_full_merged_pool, rel_packet, rel_status, rel_correct_score, rel_crow_screener, shanghai_day, packet_lookup_days
from .titan007_correct_score import match_view, collect_correct_score
from .packet_builder import PACKET_VERSION
from .lifecycle_keepalive import (
    lightweight_heartbeat_loop,
    mark_warmup,
    get_keepalive_state,
)
from .daily_hot_pool_scheduler import trigger_from_health_ping, status as daily_hot_pool_status

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

ACTIVE_PHASE = "phase2a"

app = FastAPI(
    title="HF Football Data Hub",
    version="0.2.0",
    description=(
        "Free-HF-compatible football compact packet API. "
        "Lifecycle: /health /ready /warmup /keepalive-status. "
        "Prediction decisions remain in Hermes."
    ),
)

# ---------------------------------------------------------------------------
# Startup — lightweight heartbeat in background
# ---------------------------------------------------------------------------


@app.on_event("startup")
async def start_lifecycle_keepalive():
    asyncio.create_task(lightweight_heartbeat_loop(interval=600))


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class HotMatchPool(BaseModel):
    date: str
    source: str = "titan007_hot_manual_or_external_trigger"
    matches: list[dict] = Field(default_factory=list)


class RefreshRequest(BaseModel):
    match_id: str
    date: Optional[str] = None
    company_ids: Optional[str] = None


class WarmupRequest(BaseModel):
    mode: str = "manual_test"  # manual_test | analysis_preflight | keepalive
    external_fetch_allowed: bool = False
    analysis_allowed: bool = False


class CorrectScoreRefreshRequest(BaseModel):
    date: Optional[str] = None


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------


def require_api_key(x_api_key: str | None):
    if not settings.api_key:
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="invalid api key")


def load_crow_full_pool(day: str) -> dict | None:
    """Read the merged Crow full pool, with legacy hot-pool fallback."""
    return store.load_json(rel_crow_full_merged_pool(day)) or store.load_json(rel_hot_pool(day))


# ===================================================================
# LIFECYCLE ENDPOINTS — must never be removed; backward-compatible only
# ===================================================================


@app.get("/health")
@app.head("/health")
def health():
    """Lightest liveness endpoint plus a narrowly scoped free-cloud schedule trigger.

    UptimeRobot's existing five-minute GET wakes a free Space. During the daily
    Shanghai capture window it launches only the data-only collector in a daemon
    thread; the health response itself never waits for source I/O.
    """
    schedule = trigger_from_health_ping()
    return {
        "ok": True,
        "space_awake": True,
        "service": "hf_football_data_hub",
        "active_phase": ACTIVE_PHASE,
        "packet_version": PACKET_VERSION,
        "hf_data_layer_only": True,
        "dataset_only": True,
        "decision_layer_local": True,
        "external_fetch_performed": False,
        "model_call_performed": False,
        "analysis_performed": False,
        "raw_returned": False,
        "daily_hot_pool_scheduler": schedule,
    }


@app.get("/ready")
def ready():
    """Check that Data Hub can return compact packets.

    Only checks local Dataset / config availability.
    No external fetches. No model calls.
    """
    dataset_ok = bool(settings.has_remote_dataset)

    today = shanghai_day()
    hot_pool = load_crow_full_pool(today)

    hot_pool_ok = hot_pool is not None
    schema_ok = True  # schema is always valid at this version

    return {
        "ok": dataset_ok and hot_pool_ok,
        "dataset_read_ok": dataset_ok,
        "hot_match_pool_available": hot_pool_ok,
        "schema_ready": schema_ok,
        "active_phase": ACTIVE_PHASE,
        "packet_version": PACKET_VERSION,
        "feature_flags": {
            # Phase 2A — always true
            "identity_lock": True,
            "hot_match_pool": True,
            "titan007_compact": True,
            "multi_company_metrics": True,
            "kline_summary": True,
            "football_data": True,
            "weather": True,
            "source_conflict_audit": True,
            "data_completeness_score": True,
            "prediction_quality_guard": True,
            "titan007_jingcai_correct_score": True,
            "correct_score_optional_enrichment": True,
            # Phase 2B — false now, toggled when THE_ODDS_API_KEY provisioned
            "the_odds_api": False,
            # Phase 3 — false now
            "phase3_sources": False,
        },
        "decision_layer_local": True,
        "final_pick_allowed_in_hf": False,
        "stake_allowed_in_hf": False,
        "bankroll_allowed_in_hf": False,
    }


@app.post("/warmup")
def warmup(req: WarmupRequest, x_api_key: str | None = Header(default=None)):
    """Preheat internal caches. No external fetches, no model calls.

    Call before analysis (analysis_preflight) or periodically (keepalive).

    If external_fetch_allowed or analysis_allowed are set to true they
    are silently ignored — this endpoint NEVER performs heavy work.
    """
    require_api_key(x_api_key)

    # Light in-memory warmup — only local config / dataset reads
    _ = settings.data_dir.exists()

    hot_pool_ok = False
    today = shanghai_day()
    hot_pool = load_crow_full_pool(today)
    if hot_pool:
        hot_pool_ok = True

    # Attempt load of source_status for cache warm
    _ = store.load_json(rel_status(today))

    mark_warmup()

    return {
        "ok": True,
        "warmup_done": True,
        "active_phase": ACTIVE_PHASE,
        "packet_version": PACKET_VERSION,
        "configs_loaded": True,
        "feature_flags_loaded": True,
        "dataset_read_ok": settings.has_remote_dataset,
        "hot_match_pool_loaded": hot_pool_ok,
        "source_status_loaded": True,
        "external_fetch_performed": False,
        "analysis_performed": False,
        "model_call_performed": False,
        "final_pick_written": False,
        "bankroll_written": False,
        "raw_returned": False,
    }


@app.get("/keepalive-status")
def keepalive_status():
    """Return current in-memory heartbeat state."""
    return get_keepalive_state(
        packet_version=PACKET_VERSION,
        active_phase=ACTIVE_PHASE,
    )


@app.get("/daily-hot-pool-status")
def get_daily_hot_pool_status():
    """Public audit status for the free UptimeRobot-triggered data-only runner."""
    return {"ok": True, **daily_hot_pool_status(), "external_fetch_performed": False, "model_call_performed": False, "analysis_performed": False}


# ===================================================================
# DATA ENDPOINTS — stable, unchanged
# ===================================================================


@app.get("/hot-matches")
def get_hot_matches(date_: str | None = None, date: str | None = None):
    day = date_ or date or shanghai_day()
    data = load_crow_full_pool(day)
    if not data:
        return {"ok": False, "date": day, "matches": [], "reason": "hot_match_pool_not_found"}
    return {"ok": True, "date": day, **data}


@app.post("/hot-matches")
def put_hot_matches(pool: HotMatchPool, x_api_key: str | None = Header(default=None)):
    require_api_key(x_api_key)
    meta = store.save_json(rel_crow_full_merged_pool(pool.date), pool.model_dump())
    return {"ok": True, "store": meta, "count": len(pool.matches)}


@app.get("/match-packet")
def get_match_packet(match_id: str, date_: str | None = None):
    days = packet_lookup_days(date_)
    packet = None
    freshness = {"eligible_for_directional_analysis": False, "reason": "packet_not_found"}
    day = days[0]
    for candidate_day in days:
        packet, freshness = store.packet_with_freshness(rel_packet(candidate_day, match_id))
        if packet:
            day = candidate_day
            break
    if not packet:
        return {
            "ok": False,
            "match_id": match_id,
            "date": day,
            "source_mode": "hf_remote_packet",
            "freshness_contract": freshness,
            "reason": "packet_not_found_dataset_only",
        }
    # Preserve the immutable packet returned by HF. The server already stores
    # packet_sha256 over this exact object; API-only enrichment is returned beside
    # it and must never mutate the packet.
    packet = dict(packet)
    cs_payload = store.load_json(rel_correct_score(day), prefer_remote=True)
    if cs_payload:
        try:
            correct_score_enrichment = match_view(cs_payload, str(match_id))
        except Exception as exc:
            correct_score_enrichment = {"ok": False, "source": "titan007_jingcai_score_market", "blocking": False, "crow_or_crown": False, "reason": f"attach_failed:{type(exc).__name__}"}
    else:
        correct_score_enrichment = {"ok": False, "source": "titan007_jingcai_score_market", "blocking": False, "crow_or_crown": False, "reason": "correct_score_dataset_not_found"}
    if not freshness.get("eligible_for_directional_analysis"):
        return {
            "ok": False,
            "match_id": match_id,
            "date": day,
            "source_mode": "hf_remote_packet",
            "packet": packet,
            "freshness_contract": freshness,
            "correct_score_enrichment": correct_score_enrichment,
            "reason": "packet_stale_or_nonlive",
            "raw_returned": False,
        }
    return {
        "ok": True,
        "packet": packet,
        "correct_score_enrichment": correct_score_enrichment,
        "source_mode": "hf_remote_packet",
        "freshness_contract": freshness,
        "packet_size_kb": packet.get("packet_meta", {}).get("packet_size_kb"),
        "generated_at": packet.get("packet_meta", {}).get("generated_at"),
        "source_coverage": packet.get("source_coverage", {}),
        "data_quality_score": packet.get("data_quality_score", {}),
        "missing_critical_fields": packet.get("missing_critical_fields", []),
        "missing_noncritical_fields": packet.get("missing_noncritical_fields", []),
        "raw_available": True,
        "raw_returned": False,
    }


@app.post("/refresh-match")
def refresh_match(req: RefreshRequest, x_api_key: str | None = Header(default=None)):
    """Hard-blocked: source capture belongs exclusively to the local collector."""
    del x_api_key
    raise HTTPException(
        status_code=409,
        detail={
            "code": "DATASET_ONLY_REFRESH_FORBIDDEN",
            "match_id": req.match_id,
            "external_fetch_performed": False,
            "reason": "Upload a validated local compact packet to the Dataset, then read it here.",
        },
    )


@app.get("/crow-screener")
def get_crow_screener(match_id: str, date_: str | None = None):
    """Serve one immutable data-only Crow artifact from the Dataset."""
    day = date_ or shanghai_day()
    data = store.load_json(rel_crow_screener(day, match_id), prefer_remote=True)
    if not data:
        return {"ok": False, "date": day, "match_id": match_id, "reason": "crow_artifact_not_found_dataset_only", "blocking": False}
    return {"ok": True, "date": day, "match_id": match_id, "artifact": data, "blocking": False, "data_only": True}


@app.get("/correct-score")
def get_correct_score(match_id: str | None = None, date_: str | None = None):
    """Return optional Titan007 JingCai correct-score enrichment.

    This is not Crow/Crown bookmaker data. It is never blocking and never a final
    pick source; Hermes may use it only to audit AH/OU depth and settlement paths.
    """
    day = date_ or shanghai_day()
    data = store.load_json(rel_correct_score(day), prefer_remote=True)
    if not data:
        return {"ok": False, "date": day, "source": "titan007_jingcai_score_market", "reason": "correct_score_dataset_not_found", "blocking": False, "crow_or_crown": False}
    if match_id:
        return {"date": day, **match_view(data, match_id)}
    return {"ok": True, "date": day, "source": data.get("source"), "source_url": data.get("source_url"), "bookmaker": data.get("bookmaker"), "crow_or_crown": False, "decision_impact": data.get("decision_impact"), "blocking": False, "coverage_match_count": data.get("coverage_match_count", 0), "match_ids": data.get("match_ids", []), "captured_at": data.get("captured_at")}


@app.post("/correct-score/refresh")
def refresh_correct_score(req: CorrectScoreRefreshRequest, x_api_key: str | None = Header(default=None)):
    """Refresh optional JingCai score-market odds and persist to Dataset.

    This endpoint updates odds changes for matches covered by Titan007's JingCai
    score page. It is data-only and non-blocking; no prediction is made here.
    """
    require_api_key(x_api_key)
    day = req.date or shanghai_day()
    payload = collect_correct_score()
    meta = store.save_json(rel_correct_score(day), payload)
    status_payload = store.load_json(rel_status(day)) or {"artifact_type": "source_status", "pool_date": day}
    status_payload["correct_score"] = {"configured": True, "available_match_count": payload.get("coverage_match_count", 0), "match_ids": payload.get("match_ids", []), "crow_or_crown": False, "source": payload.get("source"), "captured_at": payload.get("captured_at"), "canonical_sha256": payload.get("canonical_sha256"), "blocking": False, "updated_by": "correct_score_refresh"}
    store.save_json(rel_status(day), status_payload)
    return {"ok": True, "date": day, "store": meta, "coverage_match_count": payload.get("coverage_match_count", 0), "match_ids": payload.get("match_ids", []), "crow_or_crown": False, "blocking": False}


class CollectPacketsRequest(BaseModel):
    match_ids: list[str] | None = None
    admissions: dict[str, dict] | None = None
    date: str | None = None
    lead_minutes: int = 20
    horizon_minutes: int = 240
    limit: int | None = None
    workers: int | None = None


def _save_cloud_packet(day: str, match_id: str, packet: dict) -> dict:
    """Persist one cloud-collected packet to the Dataset (data-only)."""
    return store.save_json(rel_packet(day, str(match_id)), packet)


@app.post("/collect-packets")
def collect_packets(req: CollectPacketsRequest, background: BackgroundTasks,
                    x_api_key: str | None = Header(default=None)):
    """Collect complete five-company packets on the cloud side.

    The Hermes host cannot reach vip.titan007.com directly (single public relay,
    ~112s/page, 10 pages per match). This Space reaches it in 2-3s, so all
    collection runs here and the host only reads finished packets.

    Data-only: no direction, stake, or bankroll is produced.
    """
    require_api_key(x_api_key)
    day = req.date or shanghai_day()
    if req.match_ids:
        targets = [str(m) for m in req.match_ids]
    else:
        pool = load_crow_full_pool(day) or {}
        targets = collect_api.select_targets(pool, req.lead_minutes,
                                            req.horizon_minutes, req.limit)
    if not targets:
        return {"ok": True, "code": "NO_TARGETS_IN_WINDOW", "date": day,
                "lead_minutes": req.lead_minutes,
                "horizon_minutes": req.horizon_minutes, "targets": 0}
    workers = req.workers or collect_api.MAX_WORKERS
    background.add_task(collect_api.run_batch, targets, day,
                        _save_cloud_packet, workers, req.admissions or {})
    return {"ok": True, "accepted": True, "date": day,
            "targets": len(targets), "match_ids": targets,
            "workers": workers, "data_only": True,
            "poll": "/collect-status"}


@app.get("/collect-status")
def collect_status():
    """Progress of the current/last cloud collection batch."""
    return {"ok": True, "state": collect_api.public_state()}


@app.get("/egress-probe")
def egress_probe(match_id: str = "2971043", company_id: str = "3"):
    """Data-only egress probe: can this Space reach vip.titan007.com directly?

    Decides whether five-company changeDetail collection can be migrated here.
    Fetches one public odds URL, reports bytes/latency only. No packet, no
    decision, no Dataset write.
    """
    import time as _t, urllib.request as _u
    out = []
    targets = [
        f"https://vip.titan007.com/changeDetail/handicap.aspx?id={match_id}&companyID={company_id}&l=0",
        f"https://vip.titan007.com/changeDetail/overunder.aspx?id={match_id}&companyID={company_id}&l=0",
        f"https://vip.titan007.com/AsianOdds_n.aspx?id={match_id}&l=0",
    ]
    for url in targets:
        t0 = _t.time()
        try:
            req = _u.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://live.titan007.com/"})
            with _u.urlopen(req, timeout=20) as r:
                body = r.read()
            out.append({"url": url, "ok": True, "status": r.status,
                        "bytes": len(body), "elapsed": round(_t.time() - t0, 2)})
        except Exception as exc:
            out.append({"url": url, "ok": False, "error": type(exc).__name__,
                        "detail": str(exc)[:160], "elapsed": round(_t.time() - t0, 2)})
    return {"ok": True, "direct_vip_reachable": all(x.get("ok") for x in out),
            "probe": out, "data_only": True}


@app.get("/source-status")
def source_status(date_: str | None = None):
    day = date_ or shanghai_day()
    data = store.load_json(rel_status(day))
    if not data:
        return {
            "ok": True,
            "date": day,
            "status": {
                "phase": ACTIVE_PHASE,
                "titan007": "configured",
                "multi_company_analyzer": "configured",
                "kline_compact": "configured",
                "titan007_jingcai_correct_score": "configured_optional_nonblocking",
                "crow_screener": "not_migrated_optional_fallback",
                "decision_layer": "Hermes local",
            },
        }
    return {"ok": True, "date": day, "status": data}
