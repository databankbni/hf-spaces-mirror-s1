"""HTTP-triggered cron endpoints.

Designed for cron-job.org (free external scheduler) to hit on a real
schedule, replacing the GitHub Actions workflows that were getting
throttled 3-5h past their configured cadence on the free tier.

All endpoints:
  - Require x-admin-secret header
  - Return 202 Accepted immediately
  - Run heavy work in BackgroundTasks so cron-job.org sees a fast response

Cost: zero — cron-job.org is free unlimited. Apify scrapes cost the
same as before (~$0.50/month current). HF Spaces handles orchestration
on free tier (kept warm by /api/cron/keep-warm itself).
"""
from __future__ import annotations
import logging
import asyncio
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cron", tags=["cron"])


def _require_admin(secret: Optional[str]) -> None:
    if not secret or secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")


# ---------------------------------------------------------------------------
# Tamil press + govt-handle monitor
# ---------------------------------------------------------------------------
@router.post("/monitor-handles")
async def cron_monitor_handles(
    background_tasks: BackgroundTasks,
    hours_back: int = Query(6, ge=1, le=72,
        description="Lookback window per handle (hours). Default 6h."),
    max_per_handle: int = Query(50, ge=1, le=200,
        description="Max tweets to pull per handle per run"),
    x_admin_secret: Optional[str] = Header(None),
):
    """Scrape every configured Tamil press / govt handle via Apify and
    AI-process the recent ones. Schedule on cron-job.org every 1h or 2h.

    Returns 202 immediately; work runs in background. Check /api/stats/
    dashboard or the admin Pending Verification queue after a few min
    to see new arrivals.
    """
    _require_admin(x_admin_secret)
    from app.ingestion.twitter_monitor import monitor_all_handles, HANDLES

    async def _go():
        try:
            summaries = await monitor_all_handles(
                hours_back=hours_back,
                max_per_handle=max_per_handle,
            )
            total = sum(s.get("processed", 0) for s in summaries)
            logger.info("monitor-handles run complete: %d total tweets processed across %d handles",
                        total, len(summaries))
        except Exception as e:
            logger.error("monitor-handles background task failed: %s", e)

    background_tasks.add_task(lambda: asyncio.run(_go()))
    return {
        "status": "queued",
        "handles": len(__import__("app.ingestion.twitter_monitor", fromlist=["HANDLES"]).HANDLES),
        "hours_back": hours_back,
        "max_per_handle": max_per_handle,
    }


@router.post("/monitor-handle/{handle}")
async def cron_monitor_one_handle(
    handle: str,
    background_tasks: BackgroundTasks,
    tier: str = Query("social_media",
        description="Tier (govt_announcement | established_press | regional_press | online_native | social_media)"),
    hours_back: int = Query(6, ge=1, le=72),
    max_per_handle: int = Query(50, ge=1, le=200),
    x_admin_secret: Optional[str] = Header(None),
):
    """Scrape a single named handle. Use when you want one cron-job.org
    job per handle (better isolation, easier to debug per-handle issues)."""
    _require_admin(x_admin_secret)
    from app.ingestion.twitter_monitor import monitor_single_handle

    async def _go():
        try:
            s = await monitor_single_handle(handle, tier=tier,
                                             hours_back=hours_back,
                                             max_per_handle=max_per_handle)
            logger.info("monitor-handle %s: %s", handle, s)
        except Exception as e:
            logger.error("monitor-handle %s failed: %s", handle, e)

    background_tasks.add_task(lambda: asyncio.run(_go()))
    return {"status": "queued", "handle": handle, "tier": tier}


# ---------------------------------------------------------------------------
# Corroboration sweeps (replaces continuous-trickle-sweep + corroboration-sweep)
# ---------------------------------------------------------------------------
@router.post("/sweep-verify")
async def cron_sweep_verify(
    background_tasks: BackgroundTasks,
    max_age_days: int = Query(45, ge=1, le=365),
    limit: Optional[int] = Query(10, ge=1, le=500,
        description="Cap on incidents scanned per run. 10 = trickle, omit/500 = full sweep."),
    x_admin_secret: Optional[str] = Header(None),
):
    """Wraps /api/ingest/sweep-verify with BackgroundTasks so cron-job.org
    sees an instant 202. The actual Google News verification loop can
    take several minutes for large limits.

    Recommended cron-job.org schedules:
      - Every 30 min: limit=10 (trickle, near-realtime promotion)
      - Daily 03:30 IST: limit=500 (full nightly sweep)
    """
    _require_admin(x_admin_secret)
    from app.ingestion.corroboration import sweep_pending

    def _go():
        try:
            r = sweep_pending(max_age_days=max_age_days, limit=limit)
            logger.info("sweep-verify completed: %s", r)
        except Exception as e:
            logger.error("sweep-verify background task failed: %s", e)

    background_tasks.add_task(_go)
    return {"status": "queued", "max_age_days": max_age_days, "limit": limit}


# ---------------------------------------------------------------------------
# Daily meter snapshot (replaces meter-snapshot.yml)
# ---------------------------------------------------------------------------
@router.post("/meter-snapshot")
async def cron_meter_snapshot(
    background_tasks: BackgroundTasks,
    x_admin_secret: Optional[str] = Header(None),
):
    """Captures today's incumbency meter score as a snapshot for the
    trend sparkline. Idempotent per day. Schedule daily 23:30 IST."""
    _require_admin(x_admin_secret)
    from app.api.routes.stats import capture_meter_snapshot

    async def _go():
        try:
            r = await capture_meter_snapshot(x_admin_secret=settings.admin_secret)
            logger.info("meter-snapshot captured: %s", r.get("score") if isinstance(r, dict) else r)
        except Exception as e:
            logger.error("meter-snapshot background task failed: %s", e)

    background_tasks.add_task(lambda: asyncio.run(_go()))
    return {"status": "queued"}


# ---------------------------------------------------------------------------
# Daily promise audit (replaces promise-audit-daily.yml)
# ---------------------------------------------------------------------------
@router.post("/promise-audit")
async def cron_promise_audit(
    background_tasks: BackgroundTasks,
    retro_limit: Optional[int] = Query(None, ge=1, le=500,
        description="Cap on retro-comparator items. Omit to scan everything."),
    x_admin_secret: Optional[str] = Header(None),
):
    """Runs the daily promise-accountability audit:
      1. Deadline-pass: pending promises whose deadline lapsed without
         verifiable delivery -> auto-flipped to broken
      2. Retro-comparator: re-runs the Promise Comparator over the last
         24h of post-May-11 incidents that mention scheme keywords

    Schedule daily 24:00 IST (after the day's news cycle settles)."""
    _require_admin(x_admin_secret)

    def _go():
        try:
            # Import lazily — these scripts live outside the app package
            import sys
            from pathlib import Path
            scripts = Path(__file__).resolve().parents[3] / "scripts"
            if str(scripts) not in sys.path:
                sys.path.insert(0, str(scripts))
            from audit_promises import deadline_pass, retro_comparator
            deadline_pass(dry_run=False)
            retro_comparator(dry_run=False, limit=retro_limit)
            logger.info("promise-audit complete (deadline-pass + retro-comparator)")
        except Exception as e:
            logger.error("promise-audit background task failed: %s", e)

    background_tasks.add_task(_go)
    return {"status": "queued", "retro_limit": retro_limit}


# ---------------------------------------------------------------------------
# Press + Reddit + Google News RSS ingestion (free-tier replacement
# for most Apify Twitter scraping)
# ---------------------------------------------------------------------------
@router.post("/scrape-press-rss")
async def cron_scrape_press_rss(
    background_tasks: BackgroundTasks,
    max_items_per_source: int = Query(25, ge=1, le=100,
        description="Cap on items pulled per RSS source per run"),
    x_admin_secret: Optional[str] = Header(None),
):
    """Pull every registered RSS source (Spark+, Puthiya Thalaimurai,
    r/TVKFiles, r/TamilnaduDiscussion, Google News TVK keyword) and
    AI-process each item through the same process_article pipeline as
    Apify-monitored tweets.

    Free-tier replacement for most of the Apify scraping load.
    Recommended cadence: every 30 min (cheap — just HTTP fetches +
    Groq AI extraction).
    """
    _require_admin(x_admin_secret)
    from app.ingestion.rss_ingest import ingest_all_sources

    async def _go():
        try:
            results = await ingest_all_sources(max_items_per_source=max_items_per_source)
            total_processed = sum(r.get("processed", 0) for r in results)
            logger.info("rss_ingest run: %d items processed across %d sources",
                        total_processed, len(results))
        except Exception as e:
            logger.error("rss_ingest background task failed: %s", e)

    background_tasks.add_task(lambda: __import__("asyncio").run(_go()))
    return {"status": "queued", "max_items_per_source": max_items_per_source}


# ---------------------------------------------------------------------------
# Weekly fact-check scraper (NewsMeter)
# ---------------------------------------------------------------------------
@router.post("/scrape-factcheckers")
async def cron_scrape_factcheckers(
    background_tasks: BackgroundTasks,
    max_per_source: int = Query(8, ge=1, le=30,
        description="Cap on articles per source per run"),
    x_admin_secret: Optional[str] = Header(None),
):
    """Sweep NewsMeter and YouTurn fact-check tag pages for new
    post-May-11 TVK / CM Vijay debunks. New articles are AI-extracted
    and inserted into propaganda_events with status='active'.

    Recommended schedule: weekly (e.g., Sundays 04:30 IST). Debunks
    land on slow cadence and the AI cost is bounded (~$0.03/week).
    """
    _require_admin(x_admin_secret)
    from app.ingestion.factcheck_scraper import scrape_all_sources

    def _go():
        try:
            result = scrape_all_sources(max_per_source=max_per_source)
            logger.info("factcheck scrape complete: %s", result)
        except Exception as e:
            logger.error("factcheck scrape background task failed: %s", e)
        # Newly-scraped debunks only reach the public ledger via sync — run it
        # here so the Fact-Checks page never drifts stale between manual syncs.
        try:
            from app.factcheck.sync import sync_all
            logger.info("fact_checks sync after scrape: %s", sync_all())
        except Exception as e:
            logger.error("fact_checks sync after scrape failed: %s", e)

    background_tasks.add_task(_go)
    return {"status": "queued", "max_per_source": max_per_source}


# ---------------------------------------------------------------------------
# Pending escalation — the 24h / 48h auto-recheck ladder
# ---------------------------------------------------------------------------
def _run_pending_escalation() -> dict:
    """Two-stage auto-handling of pending_review incidents left unchecked:

      Stage 1 (aged >= 24h): run press corroboration. If 2+ outlets found,
        promote to multi_source_verified + status=approved (handled inside
        attempt_corroborate).
      Stage 2 (aged >= 48h, still single-source): auto-publish anyway with
        verification_status='single_source' (counts in the headline but
        the card shows a 'single source' tag). This clears the queue of
        items that will never get press echo, while staying honest.
    """
    from datetime import datetime, timezone, timedelta
    from app.database import get_db
    from app.ingestion.corroboration import attempt_corroborate
    db = get_db()
    now = datetime.now(timezone.utc)
    cutoff_24 = (now - timedelta(hours=24)).isoformat()
    cutoff_48 = (now - timedelta(hours=48)).isoformat()
    summary = {"checked_at": now.isoformat(), "corroborated": 0,
               "single_source_published": 0, "scanned": 0}

    try:
        rows = (db.table("incidents")
                .select("id, title, summary, location, incident_date, "
                        "source_urls, verification_status, source_count, created_at")
                .eq("status", "pending_review")
                .eq("verification_status", "pending_verification")
                .lte("created_at", cutoff_24)
                .execute().data or [])
    except Exception as e:
        return {"error": str(e)[:120], **summary}

    summary["scanned"] = len(rows)
    for inc in rows:
        try:
            # Stage 1: try corroboration (promotes if 2+ press outlets)
            outcome = attempt_corroborate(inc)
            if outcome.get("promoted"):
                summary["corroborated"] += 1
                continue
            # Stage 2: 48h+ and still uncorroborated -> single-source publish
            if (inc.get("created_at") or "") <= cutoff_48:
                db.table("incidents").update({
                    "status": "approved",
                    "verification_status": "single_source",
                }).eq("id", inc["id"]).execute()
                try:
                    db.table("incident_audit").insert({
                        "incident_id": inc["id"], "action": "single_source_published",
                        "to_value": "single_source", "actor": "pending_escalation",
                        "reason": "Unverified after 48h recheck window; auto-published "
                                  "with single-source tag.",
                    }).execute()
                except Exception:
                    pass
                summary["single_source_published"] += 1
        except Exception:
            logger.exception("pending escalation failed for %s", inc.get("id"))
    logger.info("pending-escalation: %s", summary)
    return summary


@router.post("/pending-escalation")
async def cron_pending_escalation(
    background_tasks: BackgroundTasks,
    x_admin_secret: Optional[str] = Header(None),
):
    """The 24h/48h auto-recheck ladder for pending incidents. Schedule on
    cron-job.org every 6-12 hours. Returns 202; work runs in background.

      - pending >= 24h -> press corroboration (promote if 2+ outlets)
      - pending >= 48h still single-source -> auto-publish, tag single_source
    """
    _require_admin(x_admin_secret)
    background_tasks.add_task(_run_pending_escalation)
    return {"status": "queued"}


# ---------------------------------------------------------------------------
# Investment watcher — flag DMK-era commitments showing signs of shifting
# ---------------------------------------------------------------------------
def _run_investment_watch(max_companies: int) -> dict:
    from app.ingestion.investment_watcher import run_investment_watch
    try:
        res = run_investment_watch(max_companies=max_companies)
        logger.info("investment-watch: %s", res)
        return res
    except Exception as e:
        logger.exception("investment-watch failed")
        return {"error": str(e)[:160]}


@router.post("/investment-watch")
async def cron_investment_watch(
    background_tasks: BackgroundTasks,
    x_admin_secret: Optional[str] = Header(None),
    max_companies: int = Query(40),
):
    """Weekly sweep of the investment registry. For each active DMK-era
    commitment, search news for shift/stall/cancel signals and raise a
    PENDING incident for review (never auto-declares a loss). Schedule
    weekly on cron-job.org / GitHub Actions."""
    _require_admin(x_admin_secret)
    background_tasks.add_task(_run_investment_watch, max_companies)
    return {"status": "queued"}


# ---------------------------------------------------------------------------
# Daily review digest — the 5-minute triage, delivered to Telegram
# ---------------------------------------------------------------------------
def _run_review_digest(limit: int) -> dict:
    from app.database import get_db
    from app.ingestion.telegram_bot import _send_message
    db = get_db()
    rows = (db.table("incidents")
            .select("id, title, category, summary, incident_date, created_at")
            .eq("status", "pending_review").order("created_at", desc=True)
            .limit(200).execute().data or [])
    flagged = [r for r in rows if str(r.get("summary") or "").startswith("⚑")]
    others = [r for r in rows if not str(r.get("summary") or "").startswith("⚑")]
    SITE = "https://tvk-tracker.vercel.app/incidents"

    # Feed-health alarm: surface dead feeds in the SAME daily glance, so a
    # broken source gets noticed in <24h instead of when a tab looks stale.
    feed_alerts: list[str] = []
    try:
        from datetime import datetime, timezone
        fh = (db.table("feed_health")
              .select("feed_name, feed_label, last_success_at, consecutive_failures")
              .execute().data or [])
        now = datetime.now(timezone.utc)
        for f in fh:
            fails = f.get("consecutive_failures") or 0
            age_h = None
            if f.get("last_success_at"):
                try:
                    age_h = (now - datetime.fromisoformat(
                        str(f["last_success_at"]).replace("Z", "+00:00"))
                    ).total_seconds() / 3600
                except Exception:
                    pass
            if fails >= 3 or (age_h is not None and age_h > 24):
                name = f.get("feed_name") or f.get("feed_label")
                detail = f"{fails} consecutive failures" if fails >= 3 else f"no fetch success in {age_h:.0f}h"
                feed_alerts.append(f"• {name} — {detail}")
    except Exception:
        pass

    if not rows and not feed_alerts:
        msg = "✅ TVK Tracker — review queue is clear, all feeds healthy."
    else:
        parts = ["🗞️ TVK Tracker — daily review queue\n"]
        if flagged:
            parts.append(f"⚑ {len(flagged)} need a DMK-lineage check (possible re-credits):")
            for r in flagged[:limit]:
                parts.append(f"• {(r.get('title') or '')[:70]}\n  {SITE}/{r['id']}")
            parts.append("")
        parts.append(f"📋 {len(others)} other items awaiting verification.")
        if feed_alerts:
            parts.append(f"\n📡 {len(feed_alerts)} feed(s) need attention:")
            parts.extend(feed_alerts[:8])
        parts.append(f"\nTriage: {SITE}?status=pending_review")
        msg = "\n".join(parts)

    chat_ids = [c.strip() for c in (settings.telegram_allowed_chat_ids or "").split(",") if c.strip()]
    sent = 0
    for cid in chat_ids:
        try:
            _send_message(int(cid), msg); sent += 1
        except Exception:
            pass
    res = {"flagged": len(flagged), "other_pending": len(others), "sent_to": sent}
    logger.info("review-digest: %s", res)
    return res


@router.post("/review-digest")
async def cron_review_digest(
    x_admin_secret: Optional[str] = Header(None),
    limit: int = Query(12, ge=1, le=40),
):
    """Send the admin a Telegram digest of the pending-review queue —
    lineage-flagged (⚑) items first, with direct links. Turns 'hunt the
    dashboard daily' into a 5-minute glance. Outbound only, so it works even
    if the inbound webhook is down. Schedule daily."""
    _require_admin(x_admin_secret)
    return _run_review_digest(limit)


# ---------------------------------------------------------------------------
# Promise evidence sweep — proactive delivery-evidence hunt (weekly)
# ---------------------------------------------------------------------------
@router.post("/promise-evidence-sweep")
async def cron_promise_evidence(
    background_tasks: BackgroundTasks,
    limit: int = Query(50, ge=1, le=200,
        description="How many open promises to search this run"),
    x_admin_secret: Optional[str] = Header(None),
):
    """Search Google News for delivery evidence per open promise (deadline-
    bearing promises first). Attaches evidence_url on confident matches and
    upgrades pending->partial only — never auto-kept, never auto-broken.
    Schedule weekly (e.g. Sundays 05:00 IST) on cron-job.org."""
    _require_admin(x_admin_secret)
    from app.ingestion.promise_evidence import sweep_promise_evidence

    def _go():
        try:
            r = sweep_promise_evidence(limit=limit)
            logger.info("promise-evidence-sweep: %s", r)
        except Exception as e:
            logger.error("promise-evidence-sweep failed: %s", e)

    background_tasks.add_task(_go)
    return {"status": "queued", "limit": limit}


@router.post("/promise-evidence-clean")
async def cron_promise_evidence_clean(x_admin_secret: Optional[str] = Header(None)):
    """One-off: revert the loose auto-matches from the earlier date-blind
    promise-evidence sweep (single Google-News-redirect evidence → cleared,
    'partial' → 'pending'). Synchronous and small. Safe to re-run."""
    _require_admin(x_admin_secret)
    from app.ingestion.promise_evidence import clear_lowquality_evidence
    return clear_lowquality_evidence()


# ---------------------------------------------------------------------------
# District backfill — fix incidents with no district tag
# ---------------------------------------------------------------------------
def _run_district_backfill(limit: int, use_ai: bool) -> dict:
    """Backfill `district` on incidents missing it.

    Pass 1 (free): dictionary match — first on the `location` field, then on
    title+summary text (the locality dictionary does substring matching, so
    'power cut in Perambur disrupts...' resolves to Chennai).
    Pass 2 (cheap, optional): AI resolution of the `location` field only.
    Statewide/unresolvable incidents legitimately stay district-less.
    """
    from app.database import get_db
    from app.ingestion.district_mapper import (
        map_location_to_district, map_location_via_ai,
    )
    db = get_db()
    rows = (db.table("incidents")
            .select("id, title, summary, location")
            .is_("district", "null")
            .limit(limit).execute().data or [])
    # Rows WITH a location field first — they're the most resolvable, and on
    # HF's free tier this background task can die partway, so the highest-
    # value rows must come before the long statewide tail.
    rows.sort(key=lambda r: 0 if r.get("location") else 1)
    # Statewide tokens: dictionary correctly returns None for these, and the
    # AI would also return NONE — every run, for ~100+ rows. Skip the AI call.
    STATEWIDE = {"tamil nadu", "tamilnadu", "tn", "tn state", "statewide",
                 "tamil nadu state", "across tamil nadu", "all districts"}
    out = {"scanned": len(rows), "dict_location": 0, "dict_text": 0,
           "ai_location": 0, "unresolved": 0}
    for inc in rows:
        district = None
        loc = inc.get("location")
        if loc:
            district = map_location_to_district(loc)
            if district:
                out["dict_location"] += 1
        if not district:
            blob = f"{inc.get('title') or ''} {inc.get('summary') or ''}"[:400]
            district = map_location_to_district(blob)
            if district:
                out["dict_text"] += 1
        if (not district and use_ai and loc
                and loc.strip().lower() not in STATEWIDE):
            try:
                district = map_location_via_ai(loc)
                if district:
                    out["ai_location"] += 1
            except Exception:
                pass
        if district:
            try:
                db.table("incidents").update({"district": district}).eq("id", inc["id"]).execute()
            except Exception:
                logger.exception("district backfill update failed for %s", inc["id"])
        else:
            out["unresolved"] += 1
    logger.info("district-backfill: %s", out)
    return out


@router.post("/district-backfill")
async def cron_district_backfill(
    background_tasks: BackgroundTasks,
    limit: int = Query(100, ge=1, le=500),
    use_ai: bool = Query(True, description="AI-resolve unknown localities (location field only)"),
    x_admin_secret: Optional[str] = Header(None),
):
    """Backfill missing district tags (dictionary first, AI fallback for the
    location field only). Safe to run repeatedly — it only touches rows where
    district IS NULL. Trigger a few times after deploy, then monthly."""
    _require_admin(x_admin_secret)
    background_tasks.add_task(_run_district_backfill, limit, use_ai)
    return {"status": "queued", "limit": limit, "use_ai": use_ai}


# ---------------------------------------------------------------------------
# Reclassify mis-tagged 'corruption' incidents (anti-corruption actions +
# prior-regime prosecutions are NOT TVK corruption)
# ---------------------------------------------------------------------------
def _run_reclassify_corruption(limit: int, dry_run: bool) -> dict:
    from app.ingestion.reclassify_corruption import reclassify_corruption
    try:
        return reclassify_corruption(limit=limit, dry_run=dry_run)
    except Exception as e:
        logger.exception("reclassify-corruption failed")
        return {"error": str(e)[:160]}


@router.post("/reclassify-corruption")
async def cron_reclassify_corruption(
    background_tasks: BackgroundTasks,
    limit: int = Query(20, ge=1, le=40,
        description="SMALL batches only. Each corruption incident costs a "
                    "blocking LLM call; on the free-tier Space a big batch "
                    "(80+) saturates the worker and hangs it. Cap is 40. "
                    "Call repeatedly to cover the backlog — already-correct "
                    "incidents are judged 'keep' and left untouched, so "
                    "re-runs converge safely."),
    dry_run: bool = Query(False, description="Judge but don't write (preview)"),
    x_admin_secret: Optional[str] = Header(None),
):
    """Re-judge a batch of category=corruption incidents and move the ones that
    aren't TVK-side corruption (govt anti-corruption ACTIONS, or prosecutions
    of prior-regime/DMK figures) to category=political_event. Genuine TVK
    corruption is left untouched. Non-destructive (audit-logged)."""
    _require_admin(x_admin_secret)
    if dry_run:
        return _run_reclassify_corruption(limit, True)  # sync preview (small batch only)
    background_tasks.add_task(_run_reclassify_corruption, limit, False)
    return {"status": "queued", "limit": limit}


# ---------------------------------------------------------------------------
# Retroactive de-duplication — merge same-event incidents logged 2-3 times
# ---------------------------------------------------------------------------
@router.post("/dedup-incidents")
async def cron_dedup_incidents(
    background_tasks: BackgroundTasks,
    days: int = Query(21, ge=1, le=120),
    dry_run: bool = Query(False, description="Report clusters without merging"),
    x_admin_secret: Optional[str] = Header(None),
):
    """Find incidents that are the SAME event logged multiple times (the
    location-variant dedup gap) and merge each cluster into one keeper,
    retracting the rest. Title-similarity guarded so distinct events never
    merge. dry_run=true returns the clusters it WOULD merge (runs synchronously
    so you can eyeball them); otherwise runs in the background."""
    _require_admin(x_admin_secret)
    from app.ingestion.dedup import dedup_existing
    if dry_run:
        return dedup_existing(days=days, dry_run=True)

    def _go():
        try:
            r = dedup_existing(days=days, dry_run=False)
            logger.info("dedup-incidents: %s", {k: v for k, v in r.items() if k != "sample"})
        except Exception as e:
            logger.error("dedup-incidents failed: %s", e)

    background_tasks.add_task(_go)
    return {"status": "queued", "days": days}


@router.post("/credit-steal-sweep")
async def cron_credit_steal_sweep(
    background_tasks: BackgroundTasks,
    days: int = Query(60, ge=1, le=180),
    dry_run: bool = Query(False, description="Preview decisions without writing"),
    use_ai: bool = Query(True, description="LLM judge decides; false = keyword preview only"),
    max_ai: int = Query(35, ge=1, le=60, description="LLM-call cap (HF free-tier safety)"),
    x_admin_secret: Optional[str] = Header(None),
):
    """Cross-check recent TVK announcements against the FULL DMK archive
    (3,000+ items, beyond the ~387 curated schemes the AI prompt knows). Keyword
    search shortlists; an LLM judge confirms before anything is auto-marked —
    keyword overlap alone is too noisy to publish a credit-steal accusation.

    dry_run=true runs synchronously and returns what it WOULD auto-mark /
    review (eyeball it first). use_ai=false returns the keyword shortlist with
    NO decisions. Real runs go to the background (LLM calls are slow); capped at
    max_ai calls so it never hangs the free Space."""
    _require_admin(x_admin_secret)
    from app.ingestion.credit_steal_sweep import sweep_credit_steals
    if dry_run:
        return sweep_credit_steals(days=days, dry_run=True, use_ai=use_ai, max_ai=max_ai)

    def _go():
        try:
            r = sweep_credit_steals(days=days, dry_run=False, use_ai=use_ai, max_ai=max_ai)
            logger.info("credit-steal-sweep: scanned=%s shortlisted=%s ai=%s auto=%s review=%s cleared=%s",
                        r["scanned"], r["shortlisted"], r["ai_calls"],
                        r["auto_marked"], r["sent_to_review"], r["ai_cleared"])
        except Exception as e:
            logger.error("credit-steal-sweep failed: %s", e)
        # Push newly-confirmed credit-steals into the public fact-check ledger.
        try:
            from app.factcheck.sync import sync_all
            logger.info("fact_checks sync after credit-steal-sweep: %s", sync_all())
        except Exception as e:
            logger.error("fact_checks sync after credit-steal-sweep failed: %s", e)

    background_tasks.add_task(_go)
    return {"status": "queued", "days": days, "use_ai": use_ai, "max_ai": max_ai}


# ---------------------------------------------------------------------------
# Keep-warm — no work, just touches the Space
# ---------------------------------------------------------------------------
@router.get("/keep-warm")
async def cron_keep_warm():
    """No-auth GET so cron-job.org can keep the HF Space warm without
    needing the admin secret. Returns 200 cheaply; importantly the very
    act of receiving the request keeps the Space's container alive past
    the idle-shutdown threshold.
    Schedule every 5 minutes."""
    return {"status": "warm", "govt_day": settings.govt_day_number}


# ---------------------------------------------------------------------------
# Ingestion watchdog — the thing that ENDS manual "are we up to date?" checks
# ---------------------------------------------------------------------------
def _run_ingestion_watchdog(stale_hours: int) -> dict:
    """The actual health check. Runs in a BackgroundTask (the live AI
    probes are too slow for a synchronous HF response). Sends a Telegram
    alert to the admin if anything is wrong."""
    from datetime import datetime, timezone, timedelta
    from app.database import get_db

    db = get_db()
    now = datetime.now(timezone.utc)
    problems: list[str] = []
    summary: dict = {"checked_at": now.isoformat()}

    # 1. Ingestion freshness — any incident rows created recently?
    since = (now - timedelta(hours=stale_hours)).isoformat()
    recent_count = -1
    try:
        r = db.table("incidents").select("id", count="exact").gte("created_at", since).execute()
        recent_count = r.count or 0
    except Exception as e:
        problems.append(f"DB count failed: {str(e)[:80]}")
    summary[f"incidents_last_{stale_hours}h"] = recent_count
    if recent_count == 0:
        problems.append(f"No incidents ingested in {stale_hours}h")

    # 2. AI provider liveness — fire one trivial probe through each chain
    try:
        from app.ingestion.ai_processor import _get_client_chain, _get_gate_chain
        live = []
        for label, chain in [("extract", _get_client_chain()), ("gate", _get_gate_chain())]:
            ok = False
            for client, model in chain:
                try:
                    client.chat.completions.create(
                        model=model, max_tokens=3,
                        messages=[{"role": "user", "content": "OK"}],
                    )
                    ok = True
                    live.append(f"{label}:{model.split('/')[-1]}")
                    break
                except Exception:
                    continue
            if not ok:
                problems.append(f"No live AI provider for '{label}' chain")
        summary["ai_live"] = live
    except Exception as e:
        problems.append(f"AI probe failed: {str(e)[:80]}")

    # 3. OpenRouter balance (the silent killer all day)
    try:
        import json as _json, urllib.request
        if settings.openrouter_api_key:
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/credits",
                headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read()).get("data", {})
            remaining = (data.get("total_credits", 0) or 0) - (data.get("total_usage", 0) or 0)
            summary["openrouter_remaining_usd"] = round(remaining, 3)
            if remaining < 1.0:
                problems.append(f"OpenRouter low: ${remaining:.2f} left")
    except Exception as e:
        summary["openrouter_check"] = f"err: {str(e)[:60]}"

    summary["healthy"] = not problems
    summary["problems"] = problems

    # 4. Alert admin on Telegram if unhealthy (the whole point)
    if problems:
        try:
            from app.ingestion.telegram_bot import _send_message
            chat_ids = [c.strip() for c in (settings.telegram_allowed_chat_ids or "").split(",") if c.strip()]
            msg = (
                "⚠️ TVK Tracker ingestion needs attention:\n\n"
                + "\n".join(f"• {p}" for p in problems)
                + f"\n\nLast {stale_hours}h: {recent_count} incidents."
                + f"\nAI live: {', '.join(summary.get('ai_live', [])) or 'NONE'}"
                + ("\n\nLikely fix: top up OpenRouter (openrouter.ai/credits) "
                   "or wait for Groq daily reset (midnight UTC).")
            )
            for cid in chat_ids:
                try:
                    _send_message(int(cid), msg)
                except Exception:
                    pass
            summary["alerted_chats"] = len(chat_ids)
        except Exception as e:
            summary["alert_error"] = str(e)[:100]

    logger.info("ingestion-watchdog: %s", summary)
    return summary


@router.post("/ingestion-watchdog")
async def cron_ingestion_watchdog(
    background_tasks: BackgroundTasks,
    stale_hours: int = Query(4, ge=1, le=48,
        description="Alert if zero incidents created in this many hours"),
    x_admin_secret: Optional[str] = Header(None),
):
    """Health-check ingestion and PING THE ADMIN ON TELEGRAM if it stalled.

    Converts 'the admin has to keep manually checking the dashboard' into
    'the system tells the admin when it needs attention'. Checks:
      1. Were any incidents created in the last `stale_hours`?
      2. Is at least one AI provider actually answering (extract + gate)?
      3. Is OpenRouter still funded?

    If anything is wrong, sends ONE concise Telegram message to every
    allowed chat id. Schedule on cron-job.org every 2-3 hours.

    Returns 202 immediately; the live AI probes run in the background
    (they're too slow for a synchronous HF response). The Telegram alert
    fires from the background task.
    """
    _require_admin(x_admin_secret)
    background_tasks.add_task(_run_ingestion_watchdog, stale_hours)
    return {"status": "queued", "stale_hours": stale_hours}
