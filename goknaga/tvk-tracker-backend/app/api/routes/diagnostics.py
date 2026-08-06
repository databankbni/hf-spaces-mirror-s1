"""Provider-cost / usage diagnostics endpoint.

Exposes a single endpoint summarising:
  - Apify wallet balance + usage this billing cycle
  - Groq daily quota state (estimated from recent activity)
  - Provider chain currently configured

Used by the admin dashboard + a future low-balance alert cron. The
goal is to never again hit a silent free-tier exhaustion mid-day —
the user can see exactly how much runway is left.

No auth required for reads (no secrets in payload). Endpoint surface
intentionally read-only.
"""
from __future__ import annotations
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional
from fastapi import APIRouter
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


def _safe_call(url: str, timeout: int = 10) -> Optional[dict]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return {"_error": True, "code": e.code, "body": e.read().decode()[:200]}
        except Exception:
            return {"_error": True, "code": e.code}
    except Exception as e:
        return {"_error": True, "msg": f"{type(e).__name__}: {str(e)[:120]}"}


@router.get("/usage")
async def usage_summary() -> dict[str, Any]:
    """Top-line view of every paid/quota'd dependency.

    Returns a uniform shape so the admin dashboard widget can render
    a colored chip per provider (green=plenty, amber=running low,
    red=exhausted).
    """
    out: dict[str, Any] = {"checked_at": datetime.now(timezone.utc).isoformat()}

    # ---- Apify ---------------------------------------------------------
    apify_status: dict[str, Any] = {"configured": bool(settings.apify_api_token)}
    if settings.apify_api_token:
        me = _safe_call(
            f"https://api.apify.com/v2/users/me?token={settings.apify_api_token}"
        )
        if me and not me.get("_error"):
            data = me.get("data") or {}
            plan = data.get("plan") or {}
            apify_status.update({
                "username": data.get("username"),
                "plan": plan.get("id"),
                "paid": plan.get("id") != "FREE",
            })
            # Usage cycle — may 404 on FREE accounts
            cycle = _safe_call(
                f"https://api.apify.com/v2/users/me/limits?token={settings.apify_api_token}"
            )
            if cycle and not cycle.get("_error"):
                cdata = cycle.get("data") or {}
                apify_status["limits"] = {
                    "current_billing_period": cdata.get("currentBillingPeriod"),
                    "monthly_usage_credit_usd": cdata.get("monthlyUsageCreditUsd"),
                    "current_usage_usd": cdata.get("currentUsageUsd"),
                }
        else:
            apify_status["error"] = me

    out["apify"] = apify_status

    # ---- Groq (no usage endpoint — but we can record key presence) ----
    out["groq"] = {
        "configured": bool(settings.groq_api_key),
        "tier": "free (14,400 req/day, llama-3.3-70b-versatile)",
    }

    # ---- OpenRouter ---------------------------------------------------
    or_status: dict[str, Any] = {"configured": bool(settings.openrouter_api_key)}
    if settings.openrouter_api_key:
        try:
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/credits",
                headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                body = json.loads(r.read())
                data = body.get("data") or {}
                or_status["credits_total_usd"] = data.get("total_credits")
                or_status["credits_used_usd"] = data.get("total_usage")
                if data.get("total_credits") is not None and data.get("total_usage") is not None:
                    or_status["credits_remaining_usd"] = round(
                        float(data["total_credits"]) - float(data["total_usage"]), 4
                    )
        except Exception as e:
            or_status["error"] = f"{type(e).__name__}: {str(e)[:120]}"

    out["openrouter"] = or_status

    # ---- Anthropic (no public usage API; just key presence) ----------
    out["anthropic_direct"] = {
        "configured": bool(settings.anthropic_api_key),
        "tier": "pay-as-you-go (no usage API exposed)",
    }

    # ---- Twitter-to-RSS bridges: permanently dead from HF ------------
    # Live probes removed 2026-06-11. They were re-proven blocked on every
    # call (403/404/RemoteDisconnected from HF's IP range, while outbound
    # HTTP itself works) and were adding ~40s of probe timeouts to every
    # diagnostics request. Twitter content flows via Google News + Apify
    # govt handles instead. See rss_ingest.py architecture note.
    out["twitter_rss_bridges"] = {
        "status": "removed",
        "note": "Nitter/RSSHub bridges are blocked from HF Spaces' IP range "
                "(verified repeatedly through 2026-06). Twitter content arrives "
                "via Google News queries and Apify govt handles.",
    }

    # ---- TRUE per-feed fetch health (feed_health table) --------------
    # Written by rss_ingest after every fetch attempt. Unlike the outlet
    # freshness below, this distinguishes a DEAD FEED (fetch/parse failed)
    # from a quiet outlet (feed fine, no new coverage).
    try:
        from app.database import get_db as _gdb0
        fh = (_gdb0().table("feed_health").select("*")
              .order("feed_label").execute().data or [])
        out["feed_health"] = fh
        out["feeds_failing"] = [
            f["feed_label"] for f in fh
            if (f.get("consecutive_failures") or 0) >= 3
        ]
    except Exception as e:
        out["feed_health"] = {"error": f"{type(e).__name__}: {str(e)[:100]}"}

    # ---- Per-outlet COVERAGE recency -----------------------------------
    # Answers "when did we last store an article from this outlet?".
    # NOTE: this is NOT feed health — most outlets arrive via Google News
    # aggregation, so an old timestamp usually means the outlet simply
    # hasn't covered TN recently (quiet), not that anything is broken.
    # For true broken-feed detection use feed_health above.
    try:
        from app.database import get_db as _gdb
        from datetime import datetime as _dt, timezone as _tz
        db = _gdb()
        # Recent sources by outlet — grouped by outlet, max scraped_at each
        r = db.table("sources").select("outlet,scraped_at").order(
            "scraped_at", desc=True
        ).limit(500).execute()
        latest_by_outlet: dict[str, str] = {}
        for row in (r.data or []):
            outlet = row.get("outlet") or "unknown"
            ts = row.get("scraped_at")
            if outlet not in latest_by_outlet and ts:
                latest_by_outlet[outlet] = ts
        now = _dt.now(_tz.utc)
        freshness = []
        for outlet, ts in sorted(latest_by_outlet.items()):
            try:
                dt = _dt.fromisoformat(ts.replace("Z", "+00:00"))
                age_hours = (now - dt).total_seconds() / 3600
                # 'quiet'/'silent' (not 'stale'/'broken') — an outlet with no
                # recent rows usually just hasn't covered TN lately.
                tier_health = "fresh" if age_hours < 6 else ("quiet" if age_hours < 24 else "silent")
                freshness.append({
                    "outlet": outlet,
                    "last_scraped": ts,
                    "age_hours": round(age_hours, 1),
                    "health": tier_health,
                })
            except Exception:
                continue
        out["source_freshness"] = freshness
        out["sources_silent"] = [f for f in freshness if f["health"] == "silent"][:20]
        out["sources_quiet"]  = [f for f in freshness if f["health"] == "quiet"][:20]
        out["sources_fresh_count"] = sum(1 for f in freshness if f["health"] == "fresh")
    except Exception as e:
        out["source_freshness"] = {"error": f"{type(e).__name__}: {str(e)[:100]}"}

    # ---- AI chain currently in use -----------------------------------
    from app.ingestion.ai_processor import _get_client_chain
    chain = _get_client_chain()
    out["ai_chain"] = [
        {"provider_index": i, "model": m, "base_url": str(c.base_url).rstrip("/")}
        for i, (c, m) in enumerate(chain)
    ]
    out["ai_chain_count"] = len(chain)

    return out


@router.get("/data-health")
async def data_health() -> dict[str, Any]:
    """PUBLIC transparency endpoint for the /data-health frontend page.

    Shows readers exactly how alive the pipeline is: per-feed fetch health,
    per-outlet coverage recency, and the verification-status mix of the
    incident corpus. Deliberately contains ZERO provider/key/quota info —
    that stays in /usage (which is also keyless but admin-oriented).
    """
    from app.database import get_db
    out: dict[str, Any] = {"checked_at": datetime.now(timezone.utc).isoformat()}
    db = get_db()

    # Configured feeds — true fetch telemetry
    try:
        fh = (db.table("feed_health").select(
            "feed_label, feed_name, last_success_at, last_attempt_at, "
            "last_item_count, last_new_processed, consecutive_failures"
        ).order("feed_label").execute().data or [])
        now = datetime.now(timezone.utc)
        feeds = []
        for f in fh:
            ts = f.get("last_success_at")
            age_h = None
            if ts:
                try:
                    age_h = round((now - datetime.fromisoformat(
                        ts.replace("Z", "+00:00"))).total_seconds() / 3600, 1)
                except Exception:
                    pass
            failing = (f.get("consecutive_failures") or 0) >= 3 or (age_h is not None and age_h > 24)
            feeds.append({
                "label": f.get("feed_name") or f["feed_label"],
                "last_success_hours_ago": age_h,
                "items_last_fetch": f.get("last_item_count"),
                "status": "failing" if failing else "ok",
            })
        out["feeds"] = feeds
        out["feeds_ok"] = sum(1 for f in feeds if f["status"] == "ok")
        out["feeds_failing"] = sum(1 for f in feeds if f["status"] == "failing")
    except Exception as e:
        out["feeds"] = []
        out["feeds_error"] = f"{type(e).__name__}: {str(e)[:100]}"

    # Outlet coverage recency (informational — quiet != broken)
    try:
        r = db.table("sources").select("outlet,scraped_at").order(
            "scraped_at", desc=True).limit(500).execute()
        latest: dict[str, str] = {}
        for row in (r.data or []):
            o = row.get("outlet") or "unknown"
            if o not in latest and row.get("scraped_at"):
                latest[o] = row["scraped_at"]
        now = datetime.now(timezone.utc)
        coverage = []
        for outlet, ts in sorted(latest.items()):
            try:
                age_h = round((now - datetime.fromisoformat(
                    ts.replace("Z", "+00:00"))).total_seconds() / 3600, 1)
                coverage.append({"outlet": outlet, "last_article_hours_ago": age_h})
            except Exception:
                continue
        out["outlet_coverage"] = coverage
    except Exception as e:
        out["outlet_coverage"] = []
        out["coverage_error"] = f"{type(e).__name__}: {str(e)[:100]}"

    # Verification mix of the corpus — the honesty metric
    try:
        counts: dict[str, int] = {}
        for vs in ("multi_source_verified", "press_verified", "admin_verified",
                   "single_source", "pending_verification"):
            res = (db.table("incidents").select("id", count="exact")
                   .eq("verification_status", vs).execute())
            counts[vs] = res.count or 0
        total = sum(counts.values())
        verified = (counts["multi_source_verified"] + counts["press_verified"]
                    + counts["admin_verified"])
        out["verification_mix"] = counts
        out["incidents_total"] = total
        out["verified_pct"] = round(100 * verified / total, 1) if total else None
    except Exception as e:
        out["verification_error"] = f"{type(e).__name__}: {str(e)[:100]}"

    return out


@router.get("/ai-probe")
async def ai_probe() -> dict[str, Any]:
    """Live-test EACH provider in the AI chain independently. Returns
    per-provider success/failure with the actual error message.

    Use when ingestion silently stops landing rows — this tells you
    in one curl whether the chain is healthy or which provider died.
    No auth (response contains no secrets, just provider status).
    """
    from app.ingestion.ai_processor import _get_client_chain
    chain = _get_client_chain()
    results = []
    test_messages = [
        {"role": "system", "content": "You output exactly the token OK and nothing else."},
        {"role": "user", "content": "OK"},
    ]
    for i, (client, model) in enumerate(chain):
        entry: dict[str, Any] = {
            "provider_index": i,
            "model": model,
            "base_url": str(client.base_url).rstrip("/"),
        }
        t0 = datetime.now(timezone.utc)
        try:
            resp = client.chat.completions.create(
                model=model, max_tokens=5, messages=test_messages,
            )
            entry["ok"] = True
            entry["latency_ms"] = int(
                (datetime.now(timezone.utc) - t0).total_seconds() * 1000
            )
            entry["response_preview"] = (resp.choices[0].message.content or "")[:80]
        except Exception as e:
            entry["ok"] = False
            entry["latency_ms"] = int(
                (datetime.now(timezone.utc) - t0).total_seconds() * 1000
            )
            entry["error_type"] = type(e).__name__
            entry["error"] = str(e)[:300]
        results.append(entry)
    healthy = [r for r in results if r.get("ok")]
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "chain_length": len(chain),
        "healthy_count": len(healthy),
        "first_healthy_provider": healthy[0]["model"] if healthy else None,
        "providers": results,
    }


@router.get("/ai-probe-real")
async def ai_probe_real() -> dict[str, Any]:
    """Stress-test the AI chain with a REAL-SIZED extraction prompt.

    The trivial /ai-probe endpoint can pass while real ingestion fails
    if the issue is prompt length / TPM throttling. This calls each
    provider with the actual SYSTEM_PROMPT + a realistic EXTRACTION
    payload (~3-4K tokens). Surfaces token-limit / TPM errors that
    only show up on production-size requests."""
    from app.ingestion.ai_processor import (
        _get_client_chain, SYSTEM_PROMPT, EXTRACTION_PROMPT,
        _load_dmk_schemes_for_prompt,
    )
    from app.database import get_db
    db = get_db()
    try:
        schemes_block = _load_dmk_schemes_for_prompt(db)
    except Exception:
        schemes_block = "(unavailable)"
    test_text = (
        "A 45-year-old farmer in Cuddalore was found dead Sunday after "
        "TNEB power cut. Family blamed TVK govt failure to maintain rural "
        "EB infra. Third such death this week since May 11."
    ) * 20  # ~2K chars
    prompt = EXTRACTION_PROMPT.format(
        url="https://test/probe",
        source="probe",
        published="2026-06-01",
        title="Farmer death after power cut in Cuddalore",
        text=test_text,
        dmk_schemes=schemes_block,
        today="2026-06-01",
    )
    chain = _get_client_chain()
    results = []
    msgs = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    sys_len = len(SYSTEM_PROMPT)
    usr_len = len(prompt)
    for i, (client, model) in enumerate(chain):
        entry: dict[str, Any] = {
            "provider_index": i,
            "model": model,
            "base_url": str(client.base_url).rstrip("/"),
            "system_chars": sys_len,
            "user_chars": usr_len,
        }
        t0 = datetime.now(timezone.utc)
        try:
            resp = client.chat.completions.create(
                model=model, max_tokens=1024, messages=msgs,
            )
            entry["ok"] = True
            entry["latency_ms"] = int(
                (datetime.now(timezone.utc) - t0).total_seconds() * 1000
            )
            entry["response_chars"] = len(resp.choices[0].message.content or "")
            entry["response_preview"] = (resp.choices[0].message.content or "")[:200]
        except Exception as e:
            entry["ok"] = False
            entry["latency_ms"] = int(
                (datetime.now(timezone.utc) - t0).total_seconds() * 1000
            )
            entry["error_type"] = type(e).__name__
            entry["error"] = str(e)[:500]
        results.append(entry)
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "providers": results,
    }
