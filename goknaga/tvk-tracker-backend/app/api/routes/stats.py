from datetime import date, datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Header, HTTPException
from app.database import get_db
from app.config import settings

router = APIRouter(prefix="/stats", tags=["stats"])

# Categories we track on the dashboard. Each one is counted by either:
#   (a) primary category match, OR
#   (b) extra tag in ai_raw.tags_extra
TRACKED_CATEGORIES = [
    "corruption", "murders", "sexual_assault", "crimes_women_kids",
    "power_cut", "eb_failure", "alcohol_menace", "honour_killing",
    "police_excess", "broken_promise", "attack_on_press", "fake_news",
    "custodial_death", "governance",
    "civic_failure", "defection", "crowd_management_failure",
    "youth_targeting", "censorship", "propaganda",
    # New promise-comparator categories (auto-set by the comparator)
    "kept_promise", "partial_promise", "new_initiative",
]

# Verification statuses that mean "press-confirmed or admin-reviewed truth".
# Anything else (pending_verification, retracted) is shown but NOT counted as
# verified — the dashboard exposes both numbers honestly so the user can see
# what's confirmed vs what's still single-source.
# 'single_source' counts toward the headline number (user choice: "counted
# in, but tagged") — the incident card carries a visible single-source badge,
# but the count includes it so the dashboard reflects everything that has
# auto-published after the 24h/48h recheck window.
VERIFIED_STATUSES = {"multi_source_verified", "admin_verified", "press_verified", "single_source"}


def _fetch_all(make_query, page_size: int = 1000):
    """Fetch ALL rows for a query, paginating past Supabase's 1000-row
    default cap.

    `make_query()` must return a FRESH query builder (filters applied, but
    no .range()/.execute()). Critical correctness fix (2026-06): once the
    incidents table exceeded 1000 rows, any endpoint doing a bare
    `.select(...).execute()` silently received only the first 1000 rows and
    UNDERCOUNTED every headline figure (this caused the dashboard 911 vs
    propaganda 976 mismatch). Always page the full set when counting.
    """
    rows: list = []
    offset = 0
    while True:
        res = make_query().range(offset, offset + page_size - 1).execute()
        batch = res.data or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return rows


@router.get("/dashboard")
async def get_dashboard_stats():
    """Top-line dashboard counters with a verified/unverified split.

    Each category exposes:
      <category>_count            — total (verified + unverified)
      <category>_verified_count   — multi-source-verified or admin-verified

    Frontend can display "12 (8 verified)" honestly.

    Performance: previously 29 sequential Supabase queries (13 categories
    × 2 + 3 misc) taking ~9s warm. Now 2 queries total, ~600ms warm.
    """
    db = get_db()

    incidents = _fetch_all(lambda: db.table("incidents").select(
        "id, title, incident_date, source_urls, severity, "
        "category, is_credit_steal, ai_raw, verification_status"
    ).eq("status", "approved"))

    # TVK-ERA FLOOR (2026-06-11): this is a TVK-government accountability
    # tracker, so every headline counter must count only events on TVK's
    # watch (incident_date >= 2026-05-11). Without this floor the dashboard
    # total was 900 — silently including ~83 DMK-era incidents (Jan-Apr 2026
    # power cuts, crimes, etc.) — while the accountability card correctly
    # showed 817. Counting DMK-era events as TVK's record is exactly the
    # overreach this project refuses to make. Floor matches the accountability
    # card's filter so every number on the dashboard now reconciles.
    govt_start_iso = settings.govt_start_date.isoformat()
    incidents = [
        inc for inc in incidents
        if (inc.get("incident_date") or "") >= govt_start_iso
    ]

    counts_total = {c: 0 for c in TRACKED_CATEGORIES}
    counts_verified = {c: 0 for c in TRACKED_CATEGORIES}
    # Collect every incident per claimed category for top-source ranking.
    # Each entry: (severity, incident_date, id, title, source_urls, verification_status)
    by_category: dict[str, list[tuple]] = {c: [] for c in TRACKED_CATEGORIES}
    credit_total = 0
    credit_verified = 0
    credit_pool: list[tuple] = []   # for top-sources on the credit_steal widget
    verified_overall = 0
    # Granular split so the dashboard banner can show accurate labels
    # (multi-source / press-confirmed / community) instead of a lumped count.
    cross_verified_count    = 0   # multi_source_verified + admin_verified
    press_verified_count    = 0   # single press outlet (press_verified)
    community_pending_count = 0   # social_media / pending_verification

    for inc in incidents:
        vstat = inc.get("verification_status")
        verified = vstat in VERIFIED_STATUSES
        if verified:
            verified_overall += 1
        if vstat in ("multi_source_verified", "admin_verified"):
            cross_verified_count += 1
        elif vstat == "press_verified":
            press_verified_count += 1
        elif vstat == "pending_verification":
            community_pending_count += 1

        # Tuple used for top-source ranking later. severity desc, date desc.
        inc_tuple = (
            int(inc.get("severity") or 0),
            inc.get("incident_date") or "",
            inc.get("id"),
            inc.get("title") or "",
            inc.get("source_urls") or [],
            vstat,
        )

        if inc.get("is_credit_steal"):
            credit_total += 1
            if verified:
                credit_verified += 1
            credit_pool.append(inc_tuple)

        # Collect every category that should claim this incident
        claims = set()
        primary = inc.get("category")
        if primary:
            claims.add(primary)
        raw = inc.get("ai_raw") or {}
        if isinstance(raw, dict):
            for t in raw.get("tags_extra", []) or []:
                if isinstance(t, str):
                    claims.add(t)
        for c in claims:
            if c in counts_total:
                counts_total[c] += 1
                if verified:
                    counts_verified[c] += 1
                by_category[c].append(inc_tuple)

    promises_res = db.table("promises").select("status").execute()
    promises = promises_res.data or []
    kept = sum(1 for p in promises if p.get("status") == "kept")

    def _domain(url: str) -> str:
        try:
            host = url.split("//", 1)[1].split("/", 1)[0].lower()
            host = host.removeprefix("www.").removeprefix("amp.")
            parts = host.split(".")
            return parts[-2] if len(parts) >= 2 else host
        except Exception:
            return "source"

    def _build_top_sources(pool: list[tuple], n: int = 3) -> list[dict]:
        """Pick the n highest-impact source URLs from an incident pool.
        Highest severity wins; ties broken by most-recent incident_date.
        Prefers non-google-news, non-reddit URLs (direct press articles)."""
        # Highest severity first; ties broken by most recent incident_date.
        ranked = sorted(pool, key=lambda t: (t[0], t[1]), reverse=True)
        out: list[dict] = []
        for sev, dt, iid, title, urls, vstat in ranked:
            if not urls:
                continue
            preferred = next(
                (u for u in urls
                 if "news.google.com" not in u and "reddit.com" not in u),
                urls[0],
            )
            out.append({
                "url": preferred,
                "outlet": _domain(preferred),
                "incident_id": iid,
                "incident_title": title,
                "incident_date": dt or None,
                "verification_status": vstat,
            })
            if len(out) >= n:
                break
        return out

    # Build per-widget top-source lists. Map raw categories to the widget keys
    # the dashboard already exposes (Power & EB is a merged widget, etc.).
    top_sources: dict[str, list[dict]] = {}
    for c in TRACKED_CATEGORIES:
        top_sources[c] = _build_top_sources(by_category[c])
    # Power & EB merge — combine pools so the widget reflects the merged count
    top_sources["power_eb"] = _build_top_sources(
        by_category["power_cut"] + by_category["eb_failure"]
    )
    top_sources["credit_stealing"] = _build_top_sources(credit_pool)

    out = {
        "govt_day":                 settings.govt_day_number,
        # Total counts (kept for backwards-compat with existing frontend)
        "corruption_count":         counts_total["corruption"],
        "murders_count":            counts_total["murders"],
        "sexual_assault_count":     counts_total["sexual_assault"],
        "crimes_women_kids_count":  counts_total["crimes_women_kids"],
        "power_cut_count":          counts_total["power_cut"],
        "eb_failure_count":         counts_total["eb_failure"],
        "alcohol_menace_count":     counts_total["alcohol_menace"],
        "honour_killing_count":     counts_total["honour_killing"],
        "police_excess_count":      counts_total["police_excess"],
        "broken_promise_count":     counts_total["broken_promise"],
        "attack_on_press_count":    counts_total["attack_on_press"],
        "fake_news_count":          counts_total["fake_news"],
        "custodial_death_count":    counts_total["custodial_death"],
        "governance_count":         counts_total["governance"],
        "civic_failure_count":      counts_total["civic_failure"],
        "civic_failure_verified":   counts_verified["civic_failure"],
        "credit_steal_count":       credit_total,
        # Verified-only counts (the honest baseline)
        "corruption_verified":      counts_verified["corruption"],
        "murders_verified":         counts_verified["murders"],
        "sexual_assault_verified":  counts_verified["sexual_assault"],
        "crimes_women_kids_verified": counts_verified["crimes_women_kids"],
        "power_cut_verified":       counts_verified["power_cut"],
        "eb_failure_verified":      counts_verified["eb_failure"],
        "alcohol_menace_verified":  counts_verified["alcohol_menace"],
        "honour_killing_verified":  counts_verified["honour_killing"],
        "police_excess_verified":   counts_verified["police_excess"],
        "broken_promise_verified":  counts_verified["broken_promise"],
        "attack_on_press_verified": counts_verified["attack_on_press"],
        "fake_news_verified":       counts_verified["fake_news"],
        "custodial_death_verified": counts_verified["custodial_death"],
        "governance_verified":      counts_verified["governance"],
        "credit_steal_verified":    credit_verified,
        # Promise-comparator categories (auto-tagged from govt announcements)
        "kept_promise_count":       counts_total["kept_promise"],
        "kept_promise_verified":    counts_verified["kept_promise"],
        "partial_promise_count":    counts_total["partial_promise"],
        "partial_promise_verified": counts_verified["partial_promise"],
        "new_initiative_count":     counts_total["new_initiative"],
        "new_initiative_verified":  counts_verified["new_initiative"],
        # Promise + overall totals
        # Combined view for the dashboard "Power & EB" widget. We keep the
        # two categories distinct in the DB (different sub-types) but
        # surface a merged count for the user-facing widget because they
        # mean the same thing to a citizen ("electricity issues").
        "power_eb_count":           counts_total["power_cut"] + counts_total["eb_failure"],
        "power_eb_verified":        counts_verified["power_cut"] + counts_verified["eb_failure"],
        "promises_kept":            kept,
        "promises_total":           len(promises),
        "total_incidents":          len(incidents),
        "verified_incidents":       verified_overall,
        "unverified_incidents":     len(incidents) - verified_overall,
        # Granular trust split (used by the dashboard trust banner).
        "cross_verified_count":     cross_verified_count,   # 2+ outlets agree, or admin
        "press_verified_count":     press_verified_count,   # 1 press outlet (Hindu/SunNews etc.)
        "community_pending_count":  community_pending_count, # Reddit / social only
        # Per-widget top sources — each StatCard renders up to 3 chips
        # linking to the highest-impact press articles behind that count.
        # Keys: TRACKED_CATEGORIES + 'power_eb' (merged widget) + 'credit_stealing'.
        "top_sources":              top_sources,
    }
    return out


# ---------- Incumbency meter ----------------------------------------------
#
# Evidence-driven 0-100 score that summarises how much accountability pressure
# has accumulated against the incumbent vs. how much delivery credit they have
# earned. Lower = anti-incumbency, higher = pro-incumbency, 50 = neutral.
#
# This is NOT an opinion poll. Every input is verifiable from our own DB:
#   - approved incident rates vs DMK NCRB/govt baselines
#   - severity-weighted high-impact incidents
#   - promises kept/broken vs expected delivery curve
#   - verified credit-steal count
#   - last 14d vs prior 14d incident-rate trend
#   - first-100-days honeymoon softener that fades to 0
#
# All inputs already flow through the multi-source verification gate, so the
# meter inherits the same trust posture as the rest of the dashboard.

# Per-category electoral weight. A corruption scandal moves voters far more
# than an EB blackout, so we weight the baseline-delta pressure accordingly.
_METER_CATEGORY_WEIGHTS: dict[str, float] = {
    "murders":           5.0,
    "custodial_death":   5.0,
    "corruption":        5.0,
    "honour_killing":    4.5,
    "sexual_assault":    4.5,
    "crimes_women_kids": 4.0,
    "police_excess":     4.0,
    "attack_on_press":   4.0,
    "credit_stealing":   3.0,
    "broken_promise":    3.0,
    "fake_news":         2.5,
    "alcohol_menace":    2.0,
    "power_cut":         2.0,
    "eb_failure":        2.0,
    "communal_violence": 4.5,
    "industrial_flight": 3.5,
}


def _zone_for(score: float) -> tuple[str, str]:
    """Map raw 0-100 score to (zone_key, human_label)."""
    if score < 25:
        return ("high_anti",     "High anti-incumbency risk")
    if score < 40:
        return ("elevated_anti", "Elevated pressure")
    if score < 55:
        return ("contested",     "Contested / early days")
    if score < 70:
        return ("mild_pro",      "Mild pro-incumbency")
    return     ("strong_pro",   "Strong pro-incumbency")


@router.get("/incumbency-meter")
async def get_incumbency_meter():
    """Realtime anti/pro-incumbency score (0-100) with full breakdown.

    Score = 50 (neutral)
          − anti_pressure (baseline + severity + promise_failure + credit + trend)
          + pro_boost     (delivery + baseline_beats + falling_trend)
          + honeymoon_softener (fades from 10 → 0 by day 100)
    """
    # Local imports dodge circular: baselines + economic both share stats path.
    from app.api.routes.baselines import BASELINES
    from app.api.routes.economic import DMK_CAGR_BASELINES, _annualise

    db = get_db()
    today = date.today()
    govt_start_iso = settings.govt_start_date.isoformat()
    days = max(1, settings.govt_day_number)

    # Try to fetch press_sentiment too; fall back to the original select if
    # the column doesn't exist yet (migration 010 may not have been applied
    # on this Supabase project).
    try:
        incidents = _fetch_all(lambda: db.table("incidents").select(
            "category, is_credit_steal, verification_status, severity, incident_date, press_sentiment"
        ).eq("status", "approved"))
    except Exception:
        incidents = _fetch_all(lambda: db.table("incidents").select(
            "category, is_credit_steal, verification_status, severity, incident_date"
        ).eq("status", "approved"))

    promises_res = db.table("promises").select("status").execute()
    promises = promises_res.data or []

    # --- 1) Baseline-vs-DMK pressure ---------------------------------------
    # Reuse the per-category DMK monthly averages from baselines.py. Anything
    # measurably worse than DMK pace adds anti-pressure proportional to its
    # electoral weight. Anything notably better counts as a "beat" → pro boost.
    baseline_pressure = 0.0
    baseline_beats = 0
    baseline_worse_categories: list[str] = []

    for b in BASELINES:
        cat = b["category"]
        cat_count = sum(
            1 for inc in incidents
            if inc.get("category") == cat
            and (inc.get("incident_date") or "") >= govt_start_iso
        )
        expected = float(b["dmk_monthly_avg"]) * (days / 30.0)
        if expected <= 0:
            continue
        ratio = cat_count / expected
        weight = _METER_CATEGORY_WEIGHTS.get(cat, 2.0)
        if ratio > 1.05:
            excess = min(ratio - 1.0, 3.0)  # cap at 3× baseline to avoid infinite pressure
            baseline_pressure += weight * excess
            baseline_worse_categories.append(b["label"])
        elif ratio < 0.85:
            baseline_beats += 1
    baseline_pressure_pts = min(baseline_pressure * 1.5, 30.0)  # cap at 30

    # --- 2) Severity-weighted high-impact pressure -------------------------
    # A single severity-5 corruption scandal needs its own line — it can move
    # the meter even before it shows up as a baseline-rate problem.
    verified_states = {"multi_source_verified", "admin_verified"}
    high_severity = sum(
        1 for inc in incidents
        if (inc.get("severity") or 1) >= 4
        and inc.get("verification_status") in verified_states
    )
    severity_pressure_pts = min(high_severity * 0.8, 15.0)

    # --- 3) Promise delivery deficit ---------------------------------------
    # Broken promises are direct anti-pressure. Underdelivery vs the expected
    # curve (~30% kept by year-1, scaling up) adds more.
    total_promises = len(promises)
    kept_promises = sum(1 for p in promises if p.get("status") == "kept")
    broken_promises = sum(1 for p in promises if p.get("status") == "broken")
    if total_promises > 0:
        delivery_ratio = kept_promises / total_promises
        broken_ratio = broken_promises / total_promises
        expected_kept_ratio = min(0.3 * (days / 365.0), 0.7)
        delivery_gap = max(0.0, expected_kept_ratio - delivery_ratio)
        promise_failure_pts = min(broken_ratio * 15.0 + delivery_gap * 10.0, 20.0)
    else:
        delivery_ratio = 0.0
        broken_ratio = 0.0
        promise_failure_pts = 0.0

    # --- 4) Credit-steal pressure ------------------------------------------
    credit_steals = sum(1 for inc in incidents if inc.get("is_credit_steal"))
    credit_pressure_pts = min(credit_steals * 0.5, 5.0)

    # --- 5) Trend (last 14d vs prior 14d) ----------------------------------
    recent_cutoff = (today - timedelta(days=14)).isoformat()
    prior_cutoff = (today - timedelta(days=28)).isoformat()
    recent_count = sum(
        1 for inc in incidents
        if (inc.get("incident_date") or "") >= recent_cutoff
    )
    prior_count = sum(
        1 for inc in incidents
        if prior_cutoff <= (inc.get("incident_date") or "") < recent_cutoff
    )
    trend_pts = 0.0
    if prior_count > 0:
        ratio = recent_count / prior_count
        if ratio > 1.2:
            trend_pts = min((ratio - 1.0) * 5.0, 5.0)        # rising → anti
        elif ratio < 0.8:
            trend_pts = -min((1.0 - ratio) * 5.0, 3.0)       # falling → pro

    # --- 6) Press sentiment (last 14 days, press-tier articles) ------------
    # Counts press-tier articles in the recent window classified by the AI as
    # positive_for_govt vs negative_for_govt.  A net-negative tilt adds anti
    # pressure (cap +10pts), net-positive tilt adds pro boost (cap +5pts).
    # Caps are deliberately asymmetric — negative press is a stronger
    # electoral signal than positive press (which can be PR-driven).
    sentiment_window_start = recent_cutoff  # reuse the 14d window already computed
    sentiment_counts = {"positive_for_govt": 0, "negative_for_govt": 0, "neutral": 0}
    for inc in incidents:
        ps = inc.get("press_sentiment")
        if not ps or ps not in sentiment_counts:
            continue
        if (inc.get("incident_date") or "") >= sentiment_window_start:
            sentiment_counts[ps] += 1

    sentiment_total = sum(sentiment_counts.values())
    sentiment_pressure_pts = 0.0
    sentiment_pro_boost = 0.0
    sentiment_net_pct: float | None = None

    # Need at least 5 classified press articles in window for a signal
    if sentiment_total >= 5:
        neg = sentiment_counts["negative_for_govt"]
        pos = sentiment_counts["positive_for_govt"]
        # Net negative share, ranges -1.0 .. +1.0 (negative dominates -> -ve)
        # E.g. 8 negative / 2 positive / 0 neutral (n=10) -> net = (2-8)/10 = -0.6
        sentiment_net_pct = round((pos - neg) / sentiment_total, 2)
        if sentiment_net_pct < 0:
            # Each -0.1 of net = ~1pt of anti, cap at 10pts (net = -1.0)
            sentiment_pressure_pts = min(abs(sentiment_net_pct) * 10.0, 10.0)
        elif sentiment_net_pct > 0:
            # Each +0.1 of net = ~0.5pt of pro, cap at 5pts (net = +1.0)
            sentiment_pro_boost = min(sentiment_net_pct * 5.0, 5.0)

    # --- 8) Economic pressure (sectoral CAGR vs DMK) -----------------------
    # Gated: only active once we have observations for at least 3 distinct
    # metric_keys. A single noisy quarter shouldn't swing the meter ±20 pts.
    # Compares each TVK observation to the DMK CAGR for that metric and
    # accumulates pp-deltas weighted by sector electoral importance.
    economic_pressure_pts = 0.0       # anti-incumbency push (positive value)
    economic_pro_boost = 0.0          # pro-incumbency push (positive value)
    econ_obs_count = 0
    econ_metrics_compared = 0
    econ_avg_delta_pp: float | None = None
    try:
        eco_res = (
            db.table("economic_quarterly_data")
            .select("metric_key, fy, quarter, value, value_type, ingested_at")
            .order("fy", desc=True)
            .order("quarter", desc=True)
            .order("ingested_at", desc=True)
            .execute()
        )
        eco_observations = eco_res.data or []
    except Exception:
        eco_observations = []

    # Pick latest observation per metric (already sorted desc)
    latest_by_metric: dict[str, dict] = {}
    for obs in eco_observations:
        k = obs.get("metric_key")
        if k and k not in latest_by_metric:
            latest_by_metric[k] = obs
    econ_obs_count = len(latest_by_metric)

    if econ_obs_count >= 3:
        dmk_lookup = {b["key"]: b for b in DMK_CAGR_BASELINES}
        # Sector weights — headline + manufacturing matter most electorally
        ECON_SECTOR_WEIGHT = {
            "headline":    2.0,
            "industry":    1.5,
            "services":    1.0,
            "agriculture": 1.5,  # politically charged in TN
            "investment":  1.0,
        }
        weighted_delta_sum = 0.0
        weight_sum = 0.0
        for key, obs in latest_by_metric.items():
            dmk = dmk_lookup.get(key)
            tvk_pct = _annualise(obs)
            if not dmk or tvk_pct is None:
                continue
            sector_w = ECON_SECTOR_WEIGHT.get(dmk["sector"], 1.0)
            delta_pp = tvk_pct - float(dmk["dmk_cagr_pct"])
            weighted_delta_sum += delta_pp * sector_w
            weight_sum += sector_w
            econ_metrics_compared += 1

        if weight_sum > 0:
            econ_avg_delta_pp = round(weighted_delta_sum / weight_sum, 2)
            # Convert weighted avg pp-delta into meter points.
            # Each 1pp under DMK CAGR = ~2.5 anti pts (cap 20).
            # Each 1pp over DMK CAGR = ~2.5 pro pts (cap 15).
            pts_per_pp = 2.5
            if econ_avg_delta_pp < 0:
                economic_pressure_pts = min(abs(econ_avg_delta_pp) * pts_per_pp, 20.0)
            elif econ_avg_delta_pp > 0:
                economic_pro_boost = min(econ_avg_delta_pp * pts_per_pp, 15.0)

    # --- Total anti / pro ---------------------------------------------------
    anti_pressure = (
        baseline_pressure_pts
        + severity_pressure_pts
        + promise_failure_pts
        + credit_pressure_pts
        + max(0.0, trend_pts)
        + economic_pressure_pts
        + sentiment_pressure_pts
    )

    delivery_bonus = delivery_ratio * 20.0
    baseline_beats_bonus = min(baseline_beats * 3.0, 15.0)
    trend_bonus = max(0.0, -trend_pts)
    pro_boost = delivery_bonus + baseline_beats_bonus + trend_bonus + economic_pro_boost + sentiment_pro_boost

    # First-100-days honeymoon softens the meter — voters give a new govt
    # some benefit of the doubt. Fades linearly to 0 by day 100.
    honeymoon_softener = max(0.0, (100.0 - days) / 100.0 * 10.0)

    raw_score = 50.0 - anti_pressure + pro_boost + honeymoon_softener
    score = round(max(0.0, min(100.0, raw_score)), 1)
    zone, zone_label = _zone_for(score)

    # --- Top contributing factors (for the "why" bullets) ------------------
    worse_cat_str = (
        ", ".join(baseline_worse_categories[:3])
        + (f" +{len(baseline_worse_categories) - 3} more"
           if len(baseline_worse_categories) > 3 else "")
    ) if baseline_worse_categories else "categories above DMK pace"

    econ_label_anti = (
        f"Economy: avg {econ_avg_delta_pp:+.1f}pp under DMK CAGR across {econ_metrics_compared} sectors"
        if econ_avg_delta_pp is not None else "Economic underperformance vs DMK CAGR"
    )
    econ_label_pro = (
        f"Economy: avg {econ_avg_delta_pp:+.1f}pp above DMK CAGR across {econ_metrics_compared} sectors"
        if econ_avg_delta_pp is not None else "Economic outperformance vs DMK CAGR"
    )

    contributors = [
        ("baseline_pressure", baseline_pressure_pts, "anti",
         f"Above DMK pace: {worse_cat_str}"),
        ("severity_pressure", severity_pressure_pts, "anti",
         f"{high_severity} high-severity verified incidents (sev 4-5)"),
        ("promise_failure",   promise_failure_pts, "anti",
         f"{broken_promises} of {total_promises} promises broken, only {kept_promises} kept"),
        ("credit_pressure",   credit_pressure_pts, "anti",
         f"{credit_steals} credit-stealing incidents documented"),
        ("trend_rising",      max(0.0, trend_pts), "anti",
         f"Rising incident rate ({recent_count} last 14d vs {prior_count} prior)"),
        ("economic_pressure", economic_pressure_pts, "anti", econ_label_anti),
        ("press_sentiment",   sentiment_pressure_pts, "anti",
         f"Press tone last 14d: {sentiment_counts['negative_for_govt']} negative vs "
         f"{sentiment_counts['positive_for_govt']} positive ({sentiment_counts['neutral']} neutral)"),
        ("delivery_bonus",    delivery_bonus, "pro",
         f"{kept_promises} of {total_promises} promises delivered"),
        ("baseline_beats",    baseline_beats_bonus, "pro",
         f"{baseline_beats} categories outperform DMK pace"),
        ("trend_falling",     max(0.0, -trend_pts), "pro",
         f"Falling incident rate ({recent_count} last 14d vs {prior_count} prior)"),
        ("economic_pro",      economic_pro_boost, "pro", econ_label_pro),
        ("sentiment_pro",     sentiment_pro_boost, "pro",
         f"Press tone last 14d: {sentiment_counts['positive_for_govt']} positive vs "
         f"{sentiment_counts['negative_for_govt']} negative"),
        ("honeymoon",         honeymoon_softener, "pro",
         f"Day {days} of {settings.govt_name} govt — first-100-days honeymoon"),
    ]
    contributors.sort(key=lambda x: x[1], reverse=True)
    factors = [
        {"key": k, "points": round(p, 1), "direction": d, "label": lbl}
        for (k, p, d, lbl) in contributors
        if p >= 0.5
    ][:4]

    return {
        "score": score,
        "zone": zone,
        "zone_label": zone_label,
        "govt_day": days,
        "govt_name": settings.govt_name,
        "anti_pressure_total": round(anti_pressure, 1),
        "pro_boost_total": round(pro_boost, 1),
        "honeymoon_softener": round(honeymoon_softener, 1),
        "factors": factors,
        "breakdown": {
            "baseline_pressure":     round(baseline_pressure_pts, 1),
            "severity_pressure":     round(severity_pressure_pts, 1),
            "promise_failure":       round(promise_failure_pts, 1),
            "credit_pressure":       round(credit_pressure_pts, 1),
            "trend":                 round(trend_pts, 1),
            "delivery_bonus":        round(delivery_bonus, 1),
            "baseline_beats_bonus":  round(baseline_beats_bonus, 1),
            "economic_pressure":     round(economic_pressure_pts, 1),
            "economic_pro_boost":    round(economic_pro_boost, 1),
            "sentiment_pressure":    round(sentiment_pressure_pts, 1),
            "sentiment_pro_boost":   round(sentiment_pro_boost, 1),
        },
        "raw_inputs": {
            "total_incidents":       len(incidents),
            "high_severity_verified": high_severity,
            "credit_steals":         credit_steals,
            "promises_kept":         kept_promises,
            "promises_broken":       broken_promises,
            "promises_total":        total_promises,
            "categories_beating_dmk": baseline_beats,
            "categories_worse_than_dmk": len(baseline_worse_categories),
            "recent_14d_incidents":  recent_count,
            "prior_14d_incidents":   prior_count,
            "economic_obs_count":    econ_obs_count,
            "economic_metrics_compared": econ_metrics_compared,
            "economic_avg_delta_pp": econ_avg_delta_pp,
            "economic_meter_active": econ_obs_count >= 3,
            "press_sentiment_window_total": sentiment_total,
            "press_sentiment_positive": sentiment_counts["positive_for_govt"],
            "press_sentiment_negative": sentiment_counts["negative_for_govt"],
            "press_sentiment_neutral":  sentiment_counts["neutral"],
            "press_sentiment_net_pct": sentiment_net_pct,
            "press_sentiment_meter_active": sentiment_total >= 5,
        },
    }


# ---------- METER SNAPSHOT HISTORY ----------------------------------------
#
# Daily cron stores one row per day so the dashboard can render a trend
# sparkline. Endpoint is admin-gated for writes (so random callers can't
# poison the history); reads are public.

def _verify_admin(secret: Optional[str]):
    if secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="admin secret required")


@router.post("/meter-snapshot")
async def capture_meter_snapshot(x_admin_secret: Optional[str] = Header(None)):
    """Capture the current meter score + breakdown as a daily snapshot.

    Idempotent per day — re-running the same day upserts on snapshot_date.
    Designed to be hit by the daily GH Action cron.
    """
    _verify_admin(x_admin_secret)

    # Reuse the live computation so the snapshot can't drift from what
    # the dashboard would show at the same moment.
    meter = await get_incumbency_meter()

    db = get_db()
    today_iso = date.today().isoformat()
    payload = {
        "snapshot_date":       today_iso,
        "score":               meter["score"],
        "zone":                meter["zone"],
        "zone_label":          meter["zone_label"],
        "govt_day":            meter["govt_day"],
        "anti_pressure_total": meter["anti_pressure_total"],
        "pro_boost_total":     meter["pro_boost_total"],
        "honeymoon_softener":  meter["honeymoon_softener"],
        "breakdown":           meter.get("breakdown"),
        "raw_inputs":          meter.get("raw_inputs"),
        "factors":             meter.get("factors"),
        "captured_at":         datetime.now(timezone.utc).isoformat(),
    }
    try:
        res = (
            db.table("meter_snapshots")
            .upsert(payload, on_conflict="snapshot_date")
            .execute()
        )
        return {"ok": True, "snapshot_date": today_iso, "score": meter["score"], "data": res.data}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Insert failed (table 'meter_snapshots' may not exist yet). "
                f"Run migration 012. Underlying: {e}"
            ),
        )


@router.get("/meter-history")
async def get_meter_history(days: int = 90):
    """Return the last N daily snapshots, oldest first (for line chart).

    Defaults to 90 days. Public read.
    """
    db = get_db()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    try:
        res = (
            db.table("meter_snapshots")
            .select("snapshot_date, score, zone, govt_day, anti_pressure_total, "
                    "pro_boost_total, honeymoon_softener")
            .gte("snapshot_date", cutoff)
            .order("snapshot_date")
            .execute()
        )
        return res.data or []
    except Exception:
        # Table missing — degrade cleanly so the dashboard sparkline just
        # hides itself rather than erroring out.
        return []


# ---------- DISTRICT MOOD -------------------------------------------------
#
# For each of TN's 38 districts: compute a 0-100 sentiment score using
# the same anti-pressure logic as the main meter but localised to that
# district's incidents.  Two windows: 7 days (recent intensity) and 30
# days (medium-term trend) so the UI can toggle.
#
# Lower score = angrier district.  Categories with higher severity have
# more anti-pressure weight per incident.

_DISTRICT_CATEGORY_WEIGHT = {
    "murders":           5.0,
    "custodial_death":   5.0,
    "honour_killing":    4.5,
    "sexual_assault":    4.5,
    "crimes_women_kids": 4.0,
    "corruption":        4.0,
    "police_excess":     4.0,
    "attack_on_press":   4.0,
    "broken_promise":    3.0,
    "communal_violence": 4.0,
    "fake_news":         2.0,
    "alcohol_menace":    2.0,
    "power_cut":         2.5,
    "water_shortage":    2.5,
    "civic_failure":     2.0,
    "eb_failure":        2.0,
    "credit_stealing":   2.0,
    "governance":        1.5,
    "kept_promise":     -3.0,        # negative weight = pro-govt boost
    "partial_promise":   1.0,
    "new_initiative":   -1.0,        # mild pro
}


def _district_score(incidents_in_district: list[dict], *, now_iso: str, window_days: int) -> dict:
    """Compute one district's anti-pressure score + top issue breakdown
    for a given lookback window."""
    cutoff = (date.today() - timedelta(days=window_days)).isoformat()
    recent = [
        i for i in incidents_in_district
        if (i.get("incident_date") or "") >= cutoff
    ]
    if not recent:
        return {"score": 50.0, "incidents": 0, "top_categories": [], "last_incident_date": None}

    # Pressure per category, with severity multiplier + recency multiplier
    anti = 0.0
    pro  = 0.0
    today = date.today()
    cat_counts: dict[str, int] = {}
    last_date: str | None = None

    for inc in recent:
        cat = (inc.get("category") or "other").lower()
        weight = _DISTRICT_CATEGORY_WEIGHT.get(cat, 1.0)
        severity = max(1, min(5, int(inc.get("severity") or 1)))
        sev_mult = 0.6 + severity * 0.2        # sev 1=0.8x, sev 5=1.6x

        # Recency multiplier: 1.0 today, 0.5 at end of window
        try:
            age_days = max(0, (today - date.fromisoformat((inc.get("incident_date") or today.isoformat())[:10])).days)
        except Exception:
            age_days = 0
        rec_mult = max(0.5, 1.0 - (age_days / window_days) * 0.5)

        pressure = weight * sev_mult * rec_mult
        if weight < 0:
            pro += abs(pressure)
        else:
            anti += pressure
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

        if not last_date or (inc.get("incident_date") or "") > last_date:
            last_date = inc.get("incident_date")

    # Squash anti-pressure into 0-50 range so total score never exits 0-100
    # without making single horrible districts swing too fast.  Cap raw
    # anti at 50 effective points.
    anti_capped = min(anti, 50.0)
    pro_capped  = min(pro, 15.0)
    score = max(0.0, min(100.0, 50.0 - anti_capped + pro_capped))

    # Top categories by count, plain-English label
    top = sorted(cat_counts.items(), key=lambda x: -x[1])[:4]

    return {
        "score":             round(score, 1),
        "incidents":         len(recent),
        "top_categories":    [{"category": c, "count": n} for c, n in top],
        "last_incident_date": last_date,
    }


def _zone_label_for(score: float) -> str:
    if score < 25:  return "Very angry"
    if score < 40:  return "Angry"
    if score < 55:  return "Tense"
    if score < 70:  return "Calm"
    return            "Quiet"


@router.get("/districts")
async def get_districts_mood():
    """Per-district sentiment for the District Mood page.

    Returns scores for two windows (7d and 30d) plus top issue categories.
    All 38 TN districts are returned even when they have zero incidents
    (score=50 'Quiet') so the map renders fully.
    """
    from app.ingestion.district_mapper import TN_DISTRICTS

    db = get_db()
    # Pull every approved incident with a district tag in the last 30 days
    cutoff_30 = (date.today() - timedelta(days=30)).isoformat()
    try:
        incidents = _fetch_all(lambda: db.table("incidents")
            .select("district, category, incident_date, severity, verification_status, title")
            .eq("status", "approved")
            .not_.is_("district", "null")
            .gte("incident_date", cutoff_30))
    except Exception:
        # Migration 015 may not be applied yet -> return all-quiet baseline
        incidents = []

    # Bucket by district
    by_district: dict[str, list[dict]] = {d: [] for d in TN_DISTRICTS}
    for inc in incidents:
        d = inc.get("district")
        if d in by_district:
            by_district[d].append(inc)

    now_iso = datetime.now(timezone.utc).isoformat()
    rows = []
    for district in TN_DISTRICTS:
        bucket = by_district[district]
        m7  = _district_score(bucket, now_iso=now_iso, window_days=7)
        m30 = _district_score(bucket, now_iso=now_iso, window_days=30)
        rows.append({
            "district":               district,
            "score_7d":               m7["score"],
            "score_30d":              m30["score"],
            "zone_7d":                _zone_label_for(m7["score"]),
            "zone_30d":               _zone_label_for(m30["score"]),
            "incidents_7d":           m7["incidents"],
            "incidents_30d":          m30["incidents"],
            "top_categories_7d":      m7["top_categories"],
            "top_categories_30d":     m30["top_categories"],
            "last_incident_date":     m30["last_incident_date"],
        })

    # Sort by angriest 7d-window first (most actionable view)
    rows.sort(key=lambda r: r["score_7d"])

    return {
        "as_of":     now_iso,
        "districts": rows,
        "totals": {
            "districts_tracked":  len(TN_DISTRICTS),
            "with_incidents_7d":  sum(1 for r in rows if r["incidents_7d"] > 0),
            "with_incidents_30d": sum(1 for r in rows if r["incidents_30d"] > 0),
        },
    }
