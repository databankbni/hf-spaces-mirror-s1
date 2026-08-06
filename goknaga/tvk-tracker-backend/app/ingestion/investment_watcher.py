"""Investment watcher — Phase 2 of the Investment Commitment Registry.

For each active commitment in `investment_commitments`, search Google News
for status/risk signals ("shifted", "stalled", "moves to Andhra", etc.).
When a risk signal is found, raise a PENDING incident for human review and
stamp `last_checked`. It never auto-declares a loss and never auto-flips the
registry status — a stall is not a loss until a human confirms it. Free:
RSS + keyword match, no AI call.
"""
from __future__ import annotations
import logging
import re
import urllib.parse
from datetime import datetime, timezone

from app.database import get_db
from app.ingestion.rss_ingest import _fetch

logger = logging.getLogger(__name__)

# STRONG signals — a clear shift/stall/death; fire on their own.
STRONG_RISK = [
    "shifts to", "shifted to", "shifts away", "moves to", "moving to",
    "relocat", "scrapp", "cancel", "shelv", "withdraw", "pulls out", "pull out",
    "pull-out", "abandon", "drops plan", "drop plan", "exits tamil nadu",
    "puts on hold", "put on hold", "stalled", "stalls", "lost to",
]
# RIVAL-STATE names — only fire when paired with an INVEST_VERB (an actual
# competing investment), so a bare mention of "Andhra" doesn't trigger.
RIVAL_STATES = ["andhra", "telangana", "karnataka", "gujarat", "maharashtra", "odisha"]
INVEST_VERB = ["invest", "new plant", "plant in", "to set up", "sets up", "factory in",
               "unit in", "facility in", "crore in", "gigafactory", "mega plant",
               "to build in", "shifts to", "moves to"]
# Never fire on these — positive/irrelevant (kills the recruitment / rooftop /
# stock / TN-positive false alarms).
POSITIVE_GUARD = [
    "inaugurat", "commission", "operational", "begins production", "starts production",
    "opens", "in tamil nadu", "thoothukudi", "rooftop", "installs", "recruitment",
    "apprentice", "result", "battery swapping", "share price", " stock", "q1 fy",
    "q2 fy", "q3 fy", "q4 fy", "dividend", "bags order", "wins order", "tamil nadu pitch",
]


def _is_risk(title: str, first_word: str) -> bool:
    t = title.lower()
    if not first_word or first_word not in t:
        return False
    if any(g in t for g in POSITIVE_GUARD):
        return False
    if any(s in t for s in STRONG_RISK):
        return True
    if any(rs in t for rs in RIVAL_STATES) and any(v in t for v in INVEST_VERB):
        return True
    return False


def _news_rss(company: str) -> str:
    q = f'"{company}" Tamil Nadu'
    return ("https://news.google.com/rss/search?q="
            + urllib.parse.quote(q) + "&hl=en-IN&gl=IN&ceid=IN:en")


def _parse_items(xml: str) -> list[dict]:
    out = []
    for block in re.findall(r"<item>(.*?)</item>", xml, flags=re.S | re.I):
        def grab(tag):
            m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", block, flags=re.S | re.I)
            v = (m.group(1) if m else "").strip()
            v = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", v, flags=re.S)
            return re.sub(r"<.*?>", "", v).strip()
        out.append({"title": grab("title"), "link": grab("link"),
                    "pubDate": grab("pubDate")})
    return out


def run_investment_watch(max_companies: int = 40) -> dict:
    db = get_db()
    try:
        rows = (db.table("investment_commitments").select("*")
                .in_("status", ["committed", "in_progress"]).execute().data or [])
    except Exception as e:
        logger.warning("investment_watch: registry read failed: %s", e)
        return {"checked": 0, "flagged": 0, "error": str(e)[:120]}

    now = datetime.now(timezone.utc).isoformat()
    flagged = 0
    for r in rows[:max_companies]:
        company = r["company"]
        first_word = re.sub(r"[^a-z]", "", company.split()[0].lower())
        xml = _fetch(_news_rss(company))
        try:
            db.table("investment_commitments").update({"last_checked": now}).eq("id", r["id"]).execute()
        except Exception:
            pass
        if not xml:
            continue

        hits = [it for it in _parse_items(xml)
                if _is_risk(it.get("title") or "", first_word)]
        if not hits:
            continue

        top = hits[0]
        sig = f"inv_watch:{first_word}:{now[:7]}"  # one alert per company per month
        try:
            exists = db.table("incidents").select("id").eq("event_signature", sig).execute().data
            if exists:
                continue
            db.table("incidents").insert({
                "title": f"WATCH: {company} — possible investment shift flagged",
                "summary": (
                    f"Auto-watcher flagged a risk signal on the DMK-era commitment "
                    f"'{company}' (₹{int(r.get('amount_cr') or 0)} cr, {r.get('sector')}, "
                    f"{r.get('location')}). Headline: \"{top['title']}\". "
                    f"NOT a confirmed loss — pending human review. Verify the source "
                    f"before this is treated as a shift/cancellation."),
                "category": "industrial_flight",
                "incident_date": now[:10],
                "location": r.get("location"),
                "source_urls": [top.get("link")] if top.get("link") else [],
                "source_count": 1,
                "severity": 3,
                "ai_confidence": 0.5,
                "member_ids": [],
                "status": "pending_review",
                "verification_status": "pending_verification",
                "event_signature": sig,
            }).execute()
            flagged += 1
            logger.info("investment_watch: flagged %s", company)
        except Exception as e:
            logger.warning("investment_watch: insert failed for %s: %s", company, e)

    return {"checked": len(rows), "flagged": flagged}
