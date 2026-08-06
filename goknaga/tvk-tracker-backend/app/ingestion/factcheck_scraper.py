"""Weekly scraper for external fact-check sites (RSS-based).

Discovers post-May-11 TVK / CM Vijay debunks from each site's
fact-check RSS feed and creates `propaganda_events` rows.

Why RSS, not HTML scraping
--------------------------
The first iteration tried to scrape NewsMeter's `/fact-check-tamil`
HTML tag page directly with a regex. That returned 0 articles because
NewsMeter is a React-rendered SPA — the article list is client-side
JS, not in the initial HTML. RSS feeds are the right primitive: they
expose the article list at a stable URL with title + description +
pubDate baked in. AI extraction reads from the RSS description directly,
no second fetch required.

Sites covered
-------------
- NewsMeter Tamil:     https://newsmeter.in/category/fact-check-tamil/google_feeds.xml
- NewsMeter English:   https://newsmeter.in/category/fact-check/google_feeds.xml
  (YouTurn has no public RSS — they're a pure SPA. Re-add later via
   a different mechanism if needed.)

Cost
----
Direct urllib fetch + AI extraction per article. ~5 new articles/run
maximum × 2 feeds = ~$0.02/week in Claude Haiku calls.

Schedule
--------
Weekly via cron-job.org → POST /api/cron/scrape-factcheckers.
"""
from __future__ import annotations
import json
import logging
import re
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional
import xml.etree.ElementTree as ET

from app.database import get_db
from app.ingestion.ai_processor import llm_call_with_fallback, _strip_code_fences

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (compatible; TVKTracker-FactCheckSweep/1.0; "
    "+https://tvk-tracker.vercel.app)"
)

GOVT_START = date(2026, 5, 11)


# RSS sources. tag_url is the RSS feed; outlet_label is what surfaces
# in the PropagandaReach widget; lang is informational.
SOURCES = [
    {
        "name":         "NewsMeter Tamil",
        "rss_url":      "https://newsmeter.in/category/fact-check-tamil/google_feeds.xml",
        "outlet_label": "NewsMeter Tamil",
        "lang":         "ta",
    },
    {
        "name":         "NewsMeter Fact-check",
        "rss_url":      "https://newsmeter.in/category/fact-check/google_feeds.xml",
        "outlet_label": "NewsMeter",
        "lang":         "en",
    },
]


SYSTEM_PROMPT_FC = (
    "You are an analyst cataloguing fact-checks of pro-TVK and anti-TVK "
    "propaganda in Tamil Nadu. Read the fact-check article excerpt and "
    "output strict JSON. No markdown fences. No prose around the JSON."
)


EXTRACTION_PROMPT_FC = """Analyze this fact-check article. Decide if it documents a debunked claim
about the TVK government, CM Vijay (C. Joseph Vijay), or Tamil Nadu post-May-11 2026
politics.  If yes, extract structured fields below.

Article URL:    {url}
Outlet:         {outlet}
Pub date:       {pub_date}
Article title:  {title}
Article body / description:
{text}

Return ONLY JSON with these fields:
{{
  "is_relevant":      true/false,
  "title":            "FAKE: <one-line summary of the false claim>",
  "description":      "2-4 sentences: what was claimed, what the truth is, what frame the propaganda served",
  "propaganda_type":  one of [
                        "manufactured_achievement",
                        "dubbed_footage",
                        "deepfake",
                        "paid_trending",
                        "misleading_edit",
                        "fake_quote",
                        "meme_glorification",
                        "astroturfing",
                        "misattributed_event",
                        "other"
                      ],
  "favoring":         "TVK" | "ANTI-TVK",
  "platform":         "instagram"|"twitter"|"whatsapp"|"facebook"|"youtube"|"tiktok"|"telegram"|"multiple"|null,
  "reach_estimate":   integer estimate of fake reach if article cites view/share counts, else null,
  "first_seen":       "YYYY-MM-DD",
  "incident_date":    "YYYY-MM-DD",
  "tags":             [3-6 short keywords],
  "confidence":       0.0-1.0
}}

RULES:
- is_relevant=FALSE if not about TVK / CM Vijay / Tamil Nadu post-May-11 govt.
- Skip electoral / pre-May-11 content.
- first_seen MUST be on or after 2026-05-11.
- Prefer specific propaganda_type over "other".
- favoring='TVK' if propaganda benefits TVK image; 'ANTI-TVK' if propaganda
  manufactures outrage against TVK.
- reach_estimate: only fill from explicit citation; "viral" alone = null.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _fetch(url: str, timeout: int = 25) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        logger.warning("HTTP %d fetching %s", e.code, url)
        return None
    except Exception as e:
        logger.warning("Fetch failed for %s: %s", url, e)
        return None


def _strip_html(text: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<style[^>]*>.*?</style>",   " ", text, flags=re.S | re.I)
    text = re.sub(r"<!\[CDATA\[", "", text)
    text = re.sub(r"\]\]>", "", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&quot;", '"').replace("&#39;", "'")
                .replace("&apos;", "'").replace("&lt;", "<").replace("&gt;", ">"))
    return re.sub(r"\s+", " ", text).strip()


def _parse_rss(xml_text: str) -> list[dict[str, str]]:
    """Parse an RSS 2.0 feed into a list of item dicts.

    Each item has: link, title, description, pub_date_iso.
    Survives malformed XML by falling back to a regex-based fallback.
    """
    items: list[dict[str, str]] = []
    try:
        root = ET.fromstring(xml_text)
        # Strip namespaces for simpler tag access (content:encoded etc.)
        for el in root.iter():
            if "}" in el.tag:
                el.tag = el.tag.split("}", 1)[1]
        for it in root.iter("item"):
            d: dict[str, str] = {}
            for child in it:
                tag = child.tag.lower()
                if tag == "link":   d["link"]        = (child.text or "").strip()
                if tag == "title":  d["title"]       = (child.text or "").strip()
                if tag == "description": d["description"] = (child.text or "").strip()
                if tag == "encoded":      d["encoded"]    = (child.text or "").strip()
                if tag == "pubdate":      d["pub_date"]   = (child.text or "").strip()
            # Normalize pub_date to ISO
            if "pub_date" in d:
                try:
                    dt = parsedate_to_datetime(d["pub_date"])
                    d["pub_date_iso"] = dt.astimezone(timezone.utc).isoformat()
                except Exception:
                    d["pub_date_iso"] = ""
            else:
                d["pub_date_iso"] = ""
            items.append(d)
    except ET.ParseError as e:
        logger.warning("XML parse failed (%s); falling back to regex", e)
        # Regex fallback — RSS items are reliably bounded by <item>...</item>
        for m in re.finditer(r"<item\b[^>]*>(.*?)</item>", xml_text, flags=re.S | re.I):
            block = m.group(1)
            def _grab(tag: str) -> str:
                mm = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", block, flags=re.S | re.I)
                return (mm.group(1).strip() if mm else "")
            link = _grab("link")
            title = _strip_html(_grab("title"))
            desc  = _strip_html(_grab("description"))
            pub_date = _grab("pubDate")
            iso = ""
            try:
                iso = parsedate_to_datetime(pub_date).astimezone(timezone.utc).isoformat()
            except Exception:
                pass
            items.append({"link": link, "title": title, "description": desc,
                          "pub_date": pub_date, "pub_date_iso": iso})
    return items


def _already_processed(db, url: str) -> bool:
    try:
        r = (
            db.table("propaganda_events")
            .select("id")
            .or_(f"debunk_url.eq.{url},source_urls.cs.{{{url}}}")
            .limit(1)
            .execute()
        )
        return bool(r.data)
    except Exception:
        return False


def _extract_propaganda(*, url: str, outlet: str, title: str, pub_date: str, body: str) -> Optional[dict[str, Any]]:
    prompt = EXTRACTION_PROMPT_FC.format(
        url=url, outlet=outlet, pub_date=pub_date, title=title, text=body[:6000],
    )
    raw = llm_call_with_fallback(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_FC},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=900,
    )
    if not raw:
        return None
    try:
        return json.loads(_strip_code_fences(raw))
    except json.JSONDecodeError:
        logger.warning("AI returned invalid JSON for %s", url)
        return None


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
def scrape_all_sources(max_per_source: int = 10) -> dict[str, dict[str, int]]:
    """Sweep every registered RSS source. Returns per-source counts of
    {discovered, new, queued, skipped_irrelevant, ai_failed}.
    """
    db = get_db()
    out: dict[str, dict[str, int]] = {}

    for src in SOURCES:
        name = src["name"]
        outlet = src["outlet_label"]
        counts = {"discovered": 0, "new": 0, "queued": 0,
                  "skipped_irrelevant": 0, "ai_failed": 0}

        xml_text = _fetch(src["rss_url"])
        if not xml_text:
            logger.warning("Could not fetch RSS for %s", name)
            out[name] = counts
            continue
        items = _parse_rss(xml_text)
        counts["discovered"] = len(items)

        processed = 0
        for item in items:
            if processed >= max_per_source:
                break
            url = item.get("link") or ""
            if not url or _already_processed(db, url):
                continue
            counts["new"] += 1

            # Body: prefer content:encoded, fall back to description
            body_html = item.get("encoded") or item.get("description") or ""
            body = _strip_html(body_html)
            if len(body) < 80:
                # Sometimes description is just a teaser; fetch the article page
                full = _fetch(url, timeout=20)
                if full:
                    body = _strip_html(full)[:8000]

            extracted = _extract_propaganda(
                url=url, outlet=outlet,
                title=item.get("title", ""),
                pub_date=item.get("pub_date_iso") or item.get("pub_date", ""),
                body=body,
            )
            processed += 1

            if not extracted:
                counts["ai_failed"] += 1
                continue
            if not extracted.get("is_relevant"):
                counts["skipped_irrelevant"] += 1
                continue

            fs = extracted.get("first_seen")
            try:
                if fs and date.fromisoformat(fs) < GOVT_START:
                    counts["skipped_irrelevant"] += 1
                    continue
            except Exception:
                pass

            try:
                row = {
                    "title":         (extracted.get("title") or "FAKE: <unparsed>")[:200],
                    "description":   extracted.get("description"),
                    "propaganda_type": extracted.get("propaganda_type", "other"),
                    "favoring":      extracted.get("favoring", "TVK"),
                    "platform":      extracted.get("platform"),
                    "reach_estimate": extracted.get("reach_estimate"),
                    "debunk_url":    url,
                    "debunk_source": outlet,
                    "debunk_reach_estimate": 15_000,
                    "first_seen":    extracted.get("first_seen"),
                    "incident_date": extracted.get("incident_date"),
                    "status":        "active",
                    "tags":          extracted.get("tags") or [],
                    "source_urls":   [url, src["rss_url"]],
                    "notes": (
                        f"Auto-ingested by factcheck_scraper on "
                        f"{datetime.now(timezone.utc).isoformat()} "
                        f"(AI confidence: {extracted.get('confidence')}). "
                        f"Debunk source: {outlet}. Reach estimate is "
                        f"conservative lower bound."
                    ),
                }
                db.table("propaganda_events").insert(row).execute()
                counts["queued"] += 1
            except Exception as e:
                logger.warning("Insert failed for %s: %s", url, e)
                counts["ai_failed"] += 1

        out[name] = counts
        logger.info("factcheck_scraper: %s -> %s", name, counts)

    return out
