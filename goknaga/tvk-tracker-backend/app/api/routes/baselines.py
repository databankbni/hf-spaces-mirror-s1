"""DMK-era baseline numbers used for delta-vs-current comparison.

Baselines are static public NCRB / govt-portal figures. We keep them in
code rather than a DB table so:
  - they're version-controlled and auditable
  - no migration needed to deploy
  - cheap reads (no DB query on dashboard load)

To update a number: edit BASELINES dict + commit. Each entry cites its
public source explicitly.
"""
from datetime import date
from fastapi import APIRouter
from app.database import get_db
from app.config import settings
from typing import Optional

router = APIRouter(prefix="/baselines", tags=["baselines"])


# All monthly averages refer to Tamil Nadu state-wide totals during the
# DMK tenure. Sources are public and citable.
#
# `confidence` is explicit so the UI never implies false precision:
#   "verified"  -> cross-checked against a published NCRB figure this session
#   "estimate"  -> NGO/news compilation or sectoral guess, NOT an official count
#
# IMPORTANT HONESTY NOTE: these are CENSUS totals (every case the state
# recorded). The dashboard's own incident counts are a PRESS SAMPLE (only
# what made the news). They are NOT directly comparable case-for-case — the
# baseline is context for scale, not a like-for-like scoreboard.
BASELINES: list[dict] = [
    {
        "category": "murders",
        "label": "Murders",
        "dmk_monthly_avg": 140.8,  # 1,690 / 12
        "confidence": "verified",
        "source": "NCRB Crime in India 2022, Tamil Nadu state total (1,690 murders)",
        "period": "2022 annual average",
        "notes": "TN recorded 1,690 murders in 2022 (NCRB) — ~141/month. "
                 "Corrected from an earlier unsourced 2,725 figure.",
    },
    {
        "category": "sexual_assault",
        "label": "Sexual Assaults",
        "dmk_monthly_avg": 105.0,
        "confidence": "estimate",
        "source": "NCRB Crime in India 2022 (IPC rape) — exact TN count not "
                  "re-verified this session",
        "period": "2022 estimate",
        "notes": "Placeholder pending source-verification of the exact TN "
                 "rape/IPC-376 count. Do not cite as precise.",
    },
    {
        "category": "crimes_women_kids",
        "label": "Crimes vs Women",
        "dmk_monthly_avg": 767.0,  # 9,207 / 12
        "confidence": "verified",
        "source": "NCRB Crime in India 2022, Tamil Nadu (9,207 crimes against "
                  "women; 8,501 in 2021)",
        "period": "2022 annual average",
        "notes": "TN: 9,207 crimes-against-women cases in 2022 (up from 8,501 in "
                 "2021) — ~767/month. Women only; POCSO/child cases excluded "
                 "(not separately verified), so this UNDERstates the combined total.",
    },
    {
        "category": "corruption",
        "label": "Corruption cases",
        "dmk_monthly_avg": 37.0,
        "confidence": "estimate",
        "source": "TN Directorate of Vigilance and Anti-Corruption (DVAC) — not "
                  "re-verified this session",
        "period": "estimate",
        "notes": "Approx; pending DVAC annual-report verification.",
    },
    {
        "category": "custodial_death",
        "label": "Custodial deaths",
        "dmk_monthly_avg": 1.0,
        "confidence": "estimate",
        "source": "NHRC TN data — not re-verified this session",
        "period": "estimate",
        "notes": "Approx ~12/yr; pending NHRC verification.",
    },
    {
        "category": "honour_killing",
        "label": "Honour killings",
        "dmk_monthly_avg": 1.2,
        "confidence": "estimate",
        "source": "Madras HC + Evidence NGO compilation",
        "period": "estimate",
        "notes": "NGO/press compilation, not an official register.",
    },
    {
        "category": "police_excess",
        "label": "Police excess incidents",
        "dmk_monthly_avg": 5.0,
        "confidence": "estimate",
        "source": "PUCL TN annual review + news compilation",
        "period": "estimate",
        "notes": "News compilation, not an official count.",
    },
    {
        "category": "communal_violence",
        "label": "Communal incidents",
        "dmk_monthly_avg": 2.5,
        "confidence": "estimate",
        "source": "News compilation",
        "period": "estimate",
        "notes": "News compilation, not an official register.",
    },
    {
        "category": "industrial_flight",
        "label": "Companies leaving TN",
        "dmk_monthly_avg": 0.2,
        "confidence": "estimate",
        "source": "Industry-chamber + press records",
        "period": "estimate",
        "notes": "Approx; very few announced exits under DMK.",
    },
]

BASELINE_LOOKUP = {b["category"]: b for b in BASELINES}


# ---------------------------------------------------------------------------
# CAG (Comptroller & Auditor General) — DMK-tenure audit findings.
#
# These are OFFICIAL, citable figures from the CAG State Finances Audit
# Report. Unlike the crime baselines, CAG numbers are official totals you can
# quote directly — there is no sample-vs-census caveat. Each entry carries its
# report number + a one-line "why it matters" for accountability framing.
#
# Source: CAG State Finances Audit Report of Tamil Nadu, Report No. 2 of 2024
# (covers FY 2022-23), tabled in the TN Assembly. PDF:
# https://cag.gov.in/webroot/uploads/download_audit_report/2023/Report-No-2-of-2024-SFAR-English-0675955f21ba460.87039330.pdf
# ---------------------------------------------------------------------------
CAG_FINDINGS: list[dict] = [
    {
        "key": "revenue_deficit",
        "label": "Revenue deficit (FY 2022-23)",
        "value": "₹36,215 cr",
        "trend": "down",  # improved
        "detail": "Down 22% from ₹46,538 cr in 2021-22. The state still spent "
                  "more on day-to-day running than it earned, but the gap "
                  "narrowed.",
        "report": "CAG SFAR, Report No. 2 of 2024 (FY 2022-23)",
    },
    {
        "key": "fiscal_deficit",
        "label": "Fiscal deficit (FY 2022-23)",
        "value": "₹81,886 cr",
        "trend": "flat",
        "detail": "Essentially unchanged from ₹81,835 cr in 2021-22 (+0.06%). "
                  "Within the borrowing limit, but not falling.",
        "report": "CAG SFAR, Report No. 2 of 2024 (FY 2022-23)",
    },
    {
        "key": "borrowing_misuse",
        "label": "Borrowings used for consumption, not assets",
        "value": "only 39% to capital",
        "trend": "bad",
        "detail": "CAG flagged that just 39% of borrowed funds went to "
                  "capital creation/development; the rest covered current "
                  "consumption and debt repayment. Capital spend was only "
                  "12.1% of total expenditure (₹39,530 cr).",
        "report": "CAG SFAR, Report No. 2 of 2024 (FY 2022-23)",
    },
    {
        "key": "debt_growth",
        "label": "Public debt growth rate",
        "value": "15.86%/yr avg",
        "trend": "bad",
        "detail": "Public debt grew at an average 15.86% per year between "
                  "2018-19 and 2022-23. Outstanding liabilities were 28.64% of "
                  "GSDP (just under the 29.30% ceiling).",
        "report": "CAG SFAR, Report No. 2 of 2024 (FY 2022-23)",
    },
    {
        "key": "pending_ucs",
        "label": "Unaccounted grant money (pending UCs)",
        "value": "₹1,435.43 cr",
        "trend": "bad",
        "detail": "48 Utilisation Certificates worth ₹1,435.43 cr were still "
                  "outstanding as on 31 Mar 2023 — grant money given out but "
                  "not yet accounted for.",
        "report": "CAG SFAR, Report No. 2 of 2024 (FY 2022-23)",
    },
    {
        "key": "psu_arrears",
        "label": "PSUs with accounts in arrears",
        "value": "16 PSUs / 22 accounts",
        "trend": "bad",
        "detail": "16 state PSUs had 22 accounts in arrears, missing "
                  "prescribed deadlines for submitting financial statements — "
                  "an audit/transparency gap.",
        "report": "CAG SFAR, Report No. 2 of 2024 (FY 2022-23)",
    },
]


@router.get("/")
async def list_baselines(category: Optional[str] = None):
    if category:
        b = BASELINE_LOOKUP.get(category)
        return [b] if b else []
    return BASELINES


@router.get("/cag")
async def list_cag_findings():
    """Official CAG (Comptroller & Auditor General) audit findings for the
    DMK tenure. These are quotable official figures — no sample caveat."""
    return {
        "source_report": "CAG State Finances Audit Report of Tamil Nadu, "
                         "Report No. 2 of 2024 (FY 2022-23)",
        "source_url": "https://cag.gov.in/webroot/uploads/download_audit_report/2023/Report-No-2-of-2024-SFAR-English-0675955f21ba460.87039330.pdf",
        "findings": CAG_FINDINGS,
    }


def _domain_of(url: str) -> str:
    """Cheap outlet label from URL host (no urllib parse to keep it tight)."""
    try:
        host = url.split("//", 1)[1].split("/", 1)[0].lower()
        host = host.removeprefix("www.").removeprefix("amp.")
        # Strip TLDs and common subdomains for a clean chip label
        parts = host.split(".")
        if len(parts) >= 2:
            return parts[-2]
        return host
    except Exception:
        return "source"


@router.get("/dashboard")
async def dashboard_baselines_with_deltas():
    """Returns DMK baseline + current TVK count + delta for each category,
    PLUS up to 3 top source URLs per category so the dashboard cards can
    link directly to the press evidence behind the count."""
    db = get_db()
    days_under_tvk = max(1, (date.today() - settings.govt_start_date).days)

    out = []
    for b in BASELINES:
        try:
            current_res = (
                db.table("incidents")
                .select("id", count="exact")
                .eq("category", b["category"])
                .eq("status", "approved")
                .gte("incident_date", settings.govt_start_date.isoformat())
                .execute()
            )
            current = current_res.count or 0
        except Exception:
            current = 0

        # Pull up to 3 representative incidents — most recent + highest
        # severity. We surface the FIRST source_url from each as a
        # clickable chip on the dashboard card. Press credibility ranking
        # would be ideal, but order-by(severity desc, incident_date desc)
        # gives the user the most-citable rows first.
        top_sources: list[dict] = []
        try:
            inc_res = (
                db.table("incidents")
                .select("id, title, incident_date, source_urls, severity, verification_status")
                .eq("category", b["category"])
                .eq("status", "approved")
                .gte("incident_date", settings.govt_start_date.isoformat())
                .order("severity", desc=True)
                .order("incident_date", desc=True)
                .limit(5)
                .execute()
            )
            for row in (inc_res.data or []):
                urls = row.get("source_urls") or []
                if not urls:
                    continue
                # Prefer a non-google-news, non-reddit URL when available —
                # those are direct press articles. Falls back to whatever
                # the row carries.
                preferred = next(
                    (u for u in urls
                     if "news.google.com" not in u and "reddit.com" not in u),
                    urls[0],
                )
                top_sources.append({
                    "url": preferred,
                    "outlet": _domain_of(preferred),
                    "incident_id": row["id"],
                    "incident_title": row.get("title"),
                    "incident_date": row.get("incident_date"),
                    "verification_status": row.get("verification_status"),
                })
                if len(top_sources) >= 3:
                    break
        except Exception:
            pass

        baseline_month_avg = float(b["dmk_monthly_avg"])
        expected = round(baseline_month_avg * (days_under_tvk / 30.0), 1)
        delta_pct = None
        if expected > 0:
            delta_pct = round((current - expected) / expected * 100, 1)

        out.append({
            "category": b["category"],
            "label": b["label"],
            "dmk_monthly_avg": baseline_month_avg,
            "dmk_source": b["source"],
            "dmk_period": b["period"],
            "confidence": b.get("confidence", "estimate"),
            "tvk_count": current,
            "tvk_period_days": days_under_tvk,
            "expected_at_dmk_rate": expected,
            "delta_pct": delta_pct,
            "top_sources": top_sources,
        })
    return out
