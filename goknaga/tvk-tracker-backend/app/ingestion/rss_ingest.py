"""Free-tier RSS-based incident ingestion.

Breaks the dashboard's hard dependency on Apify Twitter scraping by
pulling from RSS feeds that have full article content for free. Each
RSS item becomes an ApifyWebhookItem and goes through the same
process_article() pipeline as Apify-monitored tweets, so trust gating,
dedup, cross-reference, etc. all work identically.

Verified working sources (probed 2026-05-29):
  - Spark+ (Tamil critical press)            sparkpluz.com/feed
  - Puthiya Thalaimurai (Tamil mainstream)   puthiyathalaimurai.com/feed
  - Reddit r/TVKFiles (curated TVK accountability)
  - Reddit r/TamilnaduDiscussion (broader TN politics)
  - Google News RSS (TVK + CM Vijay keyword search) — aggregates
    Hindu/NIE/DT Next/etc. via single query, replaces direct outlet
    RSS feeds that returned HTTP errors or 0 items

Dead / unreachable RSS feeds (left out):
  - News18 Tamil  (404 / 0 items)
  - Sun News      (DNS fail)
  - YouTurn       (0 items)
  - DT Next       (HTTP error)
  - The Hindu     (timeout)
  - NIE           (HTTP error)
  These outlets' articles still flow in via Google News when they
  cover TVK news, so we don't actually lose them.

Apify is now only used for govt-tier handles (@CMOTamilnadu,
@TNDIPRNEWS) where the Tweet IS the announcement and no press echo
exists. ~2,000 Apify scrapes/month = ~$0.50/month, comfortably
inside Apify's $5 free tier.

Cost: $0/month for this scraper. AI extraction via Groq is free.
"""
from __future__ import annotations
import logging
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional
import xml.etree.ElementTree as ET

from app.config import settings
from app.ingestion.ai_processor import process_article
from app.models.schemas import ApifyWebhookItem

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (compatible; TVKTracker-RSSIngest/1.0; "
    "+https://tvk-tracker.vercel.app)"
)


# Source registry. Each source maps to:
#   source_label  — what gets stored as `sources.outlet`
#   tier          — trust tier for process_article (governs whether a
#                   single source counts as press_verified or holds at
#                   pending_verification)
#   rss_url       — the feed URL
#
# Architecture note (2026-05-30): Twitter-to-RSS bridges (nitter.net,
# rsshub.app, twiiit.com, all known Nitter mirrors) are BLOCKED from
# HuggingFace Spaces' IP range — proven via /api/diagnostics/usage
# probe returning 403 / RemoteDisconnected on every attempt. The
# bridges work from a residential / developer IP but not from HF.
# That means we cannot live-scrape Twitter for free on the cloud.
#
# Paths to Twitter content from HF:
#   1. Apify (paid, ~$0.50/mo for 2 govt handles at 2h cadence)
#   2. Google News RSS with outlet/handle keywords — catches news
#      content from these outlets when other sites cover them
#   3. Direct press-site RSS for outlets that expose one (Spark+,
#      Puthiya Thalaimurai)
#
# Apify monitor-handles cron remains the canonical path for the 2
# govt handles (CMOTamilnadu, TNDIPRNEWS) — their content is
# unavailable any other way. Free $5/mo tier handles this comfortably.
SOURCES_RSS: list[dict[str, str]] = [
    # ---- Direct press-site RSS (the only outlets that publish
    #      working RSS feeds reachable from HF) ----
    {
        "source_label": "rss_sparkplus_site",
        "tier":         "online_native",
        "rss_url":      "https://sparkpluz.com/feed/",
        "name":         "Spark+ (site)",
    },
    {
        "source_label": "rss_puthiyathalaimurai_site",
        "tier":         "regional_press",
        "rss_url":      "https://puthiyathalaimurai.com/feed/",
        "name":         "Puthiya Thalaimurai (site)",
    },
    # ---- Reddit (single post = pending_verification, needs press echo) ----
    {
        "source_label": "rss_reddit_tvkfiles",
        "tier":         "social_media",
        "rss_url":      "https://www.reddit.com/r/TVKFiles/.rss",
        "name":         "r/TVKFiles",
    },
    {
        "source_label": "rss_reddit_tn_discussion",
        "tier":         "social_media",
        "rss_url":      "https://www.reddit.com/r/TamilnaduDiscussion/.rss",
        "name":         "r/TamilnaduDiscussion",
    },
    # ---- Google News aggregator (catches every English outlet that
    #      covers TVK — Hindu, NIE, DT Next, etc. without per-outlet
    #      scraping) ----
    {
        "source_label": "rss_gnews_tvk",
        "tier":         "established_press",
        "rss_url":      "https://news.google.com/rss/search?q=%22Tamil+Nadu%22+%22CM+Vijay%22+OR+TVK&hl=en-IN&gl=IN&ceid=IN:en",
        "name":         "Google News (TVK)",
    },
    {
        "source_label": "rss_gnews_tvk_full",
        "tier":         "established_press",
        "rss_url":      "https://news.google.com/rss/search?q=Tamilaga+Vettri+Kazhagam&hl=en-IN&gl=IN&ceid=IN:en",
        "name":         "Google News (TVK full name)",
    },
    # Google News queries specifically biased toward catching content
    # from the Twitter handles HF can no longer reach directly. These
    # queries return any article that quotes/references the outlet —
    # so a Sun News tweet that becomes a news story flows in this way.
    {
        # Broadened: the old query (`"Sun News" Tamil Nadu TVK`) was too
        # narrow and rarely surfaced fresh items, and the rich Sun News
        # Twitter handle is dead (Apify exhausted). This wider query pulls
        # Sun News Tamil Nadu coverage broadly; the relevance gate + AI
        # filter non-TVK items, so widening costs nothing in quality.
        "source_label": "rss_gnews_sunnews",
        "tier":         "established_press",
        "rss_url":      "https://news.google.com/rss/search?q=%22Sun+News%22+%22Tamil+Nadu%22&hl=en-IN&gl=IN&ceid=IN:en",
        "name":         "Google News (Sun News)",
    },
    {
        # Tamil-language Sun News query — catches Tamil-script coverage the
        # English query misses (Sun News publishes primarily in Tamil).
        "source_label": "rss_gnews_sunnews_ta",
        "tier":         "established_press",
        "rss_url":      "https://news.google.com/rss/search?q=%E0%AE%9A%E0%AE%A9%E0%AF%8D+%E0%AE%A8%E0%AE%BF%E0%AE%AF%E0%AF%82%E0%AE%B8%E0%AF%8D+%E0%AE%A4%E0%AE%AE%E0%AE%BF%E0%AE%B4%E0%AF%8D%E0%AE%A8%E0%AE%BE%E0%AE%9F%E0%AF%81&hl=ta-IN&gl=IN&ceid=IN:ta",
        "name":         "Google News (Sun News Tamil)",
    },
    {
        "source_label": "rss_gnews_news18",
        "tier":         "established_press",
        "rss_url":      "https://news.google.com/rss/search?q=%22News18%22+Tamil+Nadu+TVK&hl=en-IN&gl=IN&ceid=IN:en",
        "name":         "Google News (News18 + TVK)",
    },
    {
        "source_label": "rss_gnews_vijay_cm",
        "tier":         "established_press",
        "rss_url":      "https://news.google.com/rss/search?q=%22CM+Vijay%22+%22Tamil+Nadu%22&hl=en-IN&gl=IN&ceid=IN:en",
        "name":         "Google News (CM Vijay)",
    },
    # ---- Civic / infrastructure queries (issue-based, NOT party-based) ----
    # CRITICAL: every query above is keyed on "TVK"/"CM Vijay", so a power
    # cut, water shortage, or TNEB failure that doesn't *name the party*
    # never gets fetched — even though it's happening on the govt's watch.
    # These queries are keyed on the ISSUE instead, so infra failures flow
    # in regardless of whether the article mentions TVK. The relevance gate
    # + AI still filter routine/scheduled items, so this costs nothing in
    # quality. (Added after the Power & EB feed went stale 31 May → 7 Jun
    # while Chennai had multi-day outages incl. the CM's own constituency.)
    {
        "source_label": "rss_gnews_power_en",
        "tier":         "established_press",
        "rss_url":      "https://news.google.com/rss/search?q=Tamil+Nadu+%28%22power+cut%22+OR+TANGEDCO+OR+TNEB+OR+%22power+shutdown%22%29+-scheduled&hl=en-IN&gl=IN&ceid=IN:en",
        "name":         "Google News (TN Power/EB)",
    },
    {
        # Highest-value source: Tamil-script power-cut coverage. The English
        # queries miss hyperlocal Tamil outlets (Daily Thanthi, Polimer, etc.)
        # that break these stories first.
        "source_label": "rss_gnews_power_ta",
        "tier":         "regional_press",
        "rss_url":      "https://news.google.com/rss/search?q=%E0%AE%A4%E0%AE%AE%E0%AE%BF%E0%AE%B4%E0%AF%8D%E0%AE%A8%E0%AE%BE%E0%AE%9F%E0%AF%81+%E0%AE%AE%E0%AE%BF%E0%AE%A9%E0%AF%8D%E0%AE%B5%E0%AF%86%E0%AE%9F%E0%AF%8D%E0%AE%9F%E0%AF%81&hl=ta-IN&gl=IN&ceid=IN:ta",
        "name":         "Google News (TN Power Tamil)",
    },
    {
        "source_label": "rss_gnews_chennai_power",
        "tier":         "established_press",
        "rss_url":      "https://news.google.com/rss/search?q=Chennai+%28%22power+cut%22+OR+%22transformer%22+OR+%22electrocution%22+OR+%E0%AE%AE%E0%AE%BF%E0%AE%A9%E0%AF%8D%E0%AE%B5%E0%AF%86%E0%AE%9F%E0%AF%8D%E0%AE%9F%E0%AF%81%29&hl=en-IN&gl=IN&ceid=IN:en",
        "name":         "Google News (Chennai Power)",
    },
    {
        "source_label": "rss_gnews_civic_en",
        "tier":         "established_press",
        "rss_url":      "https://news.google.com/rss/search?q=Tamil+Nadu+%28%22water+shortage%22+OR+%22drinking+water%22+OR+sewage+OR+%22garbage%22%29+Chennai&hl=en-IN&gl=IN&ceid=IN:en",
        "name":         "Google News (TN Civic)",
    },
    # ---- Law & order / serious crime (issue-based, English + Tamil) -------
    # Same blind-spot fix as power: murders, sexual assault, POCSO, and
    # opposition law-and-order criticism rarely name "TVK", so the party
    # queries miss them — leaving the crime tabs undercounted (56 murders in
    # 27 days vs an NCRB ~4.6/day real rate ≈ only ~40% captured). The
    # relevance gate + extraction prompt still gate these (a crime under the
    # current govt's watch is in-scope; non-TN / pre-govt items get dropped).
    {
        "source_label": "rss_gnews_lawandorder_en",
        "tier":         "established_press",
        "rss_url":      "https://news.google.com/rss/search?q=Tamil+Nadu+%28%22law+and+order%22+OR+murder+OR+%22sexual+assault%22+OR+POCSO+OR+kidnap%29+-cricket+-film&hl=en-IN&gl=IN&ceid=IN:en",
        "name":         "Google News (TN Law & Order)",
    },
    {
        "source_label": "rss_gnews_crime_ta",
        "tier":         "regional_press",
        "rss_url":      "https://news.google.com/rss/search?q=%E0%AE%A4%E0%AE%AE%E0%AE%BF%E0%AE%B4%E0%AF%8D%E0%AE%A8%E0%AE%BE%E0%AE%9F%E0%AF%81+%28%E0%AE%95%E0%AF%8A%E0%AE%B2%E0%AF%88+OR+%E0%AE%AA%E0%AE%BE%E0%AE%B2%E0%AE%BF%E0%AE%AF%E0%AE%B2%E0%AF%8D+OR+%E0%AE%95%E0%AE%B1%E0%AF%8D%E0%AE%AA%E0%AE%B4%E0%AE%BF%E0%AE%AA%E0%AF%8D%E0%AE%AA%E0%AF%81+OR+%E0%AE%A4%E0%AE%BE%E0%AE%95%E0%AF%8D%E0%AE%95%E0%AF%81%E0%AE%A4%E0%AE%B2%E0%AF%8D%29&hl=ta-IN&gl=IN&ceid=IN:ta",
        "name":         "Google News (TN Crime Tamil)",
    },
    {
        "source_label": "rss_gnews_drugs_en",
        "tier":         "established_press",
        "rss_url":      "https://news.google.com/rss/search?q=Tamil+Nadu+%28ganja+OR+drugs+OR+narcotics+OR+NDPS%29+%28seizure+OR+arrest+OR+smuggling%29&hl=en-IN&gl=IN&ceid=IN:en",
        "name":         "Google News (TN Drugs)",
    },
    # Chennai-suburb crime — the TN-wide law&order feed ranked these too low to
    # surface (a whole TOI "12 assaults in 24 hours" roundup across Manimangalam/
    # Mangadu/Ambattur/Koyambedu/Porur/Perambur slipped past). City-scoped query
    # catches the locality-level POCSO/assault cases.
    {
        "source_label": "rss_gnews_chennai_crime_en",
        "tier":         "established_press",
        "rss_url":      "https://news.google.com/rss/search?q=Chennai+%28POCSO+OR+rape+OR+molest+OR+%22sexual+assault%22+OR+%22minor+girl%22+OR+harassment%29+-cricket+-film&hl=en-IN&gl=IN&ceid=IN:en",
        "name":         "Google News (Chennai Crime)",
    },
    # Direct Times of India — Chennai city feed (print/online exposés the GNews
    # search misses, e.g. the children-safety investigation).
    {
        "source_label": "rss_toi_chennai",
        "tier":         "established_press",
        "rss_url":      "https://timesofindia.indiatimes.com/rssfeeds/-2128833038.cms",
        "name":         "Times of India (Chennai)",
    },
    # ---- Tamil-language accountability queries (hl=ta-IN) ------------------
    # Coverage audit (2026-07): 96% of ingested source links were Google-News
    # (English) + Reddit; Tamil-language local press — where a lot of
    # district-level corruption/crime breaks FIRST — was barely represented.
    # These 5 Tamil-script Google-News queries widen the net into Tamil outlets
    # (Dinamalar, Dinakaran, Polimer, Sun News, etc.). Each returns 55-100 items;
    # the relevance gate + AI extraction still filter non-TN / routine items.
    {
        "source_label": "rss_gnews_corruption_ta",
        "tier":         "regional_press",
        "rss_url":      "https://news.google.com/rss/search?q=%E0%AE%A4%E0%AE%AE%E0%AE%BF%E0%AE%B4%E0%AF%8D%E0%AE%A8%E0%AE%BE%E0%AE%9F%E0%AF%81%20%28%E0%AE%8A%E0%AE%B4%E0%AE%B2%E0%AF%8D%20OR%20%E0%AE%B2%E0%AE%9E%E0%AF%8D%E0%AE%9A%E0%AE%AE%E0%AF%8D%20OR%20%E0%AE%AE%E0%AF%81%E0%AE%B1%E0%AF%88%E0%AE%95%E0%AF%87%E0%AE%9F%E0%AF%81%20OR%20%E0%AE%AE%E0%AF%8B%E0%AE%9A%E0%AE%9F%E0%AE%BF%29&hl=ta-IN&gl=IN&ceid=IN:ta",
        "name":         "Google News (TN Corruption Tamil)",
    },
    {
        "source_label": "rss_gnews_drugs_ta",
        "tier":         "regional_press",
        "rss_url":      "https://news.google.com/rss/search?q=%E0%AE%A4%E0%AE%AE%E0%AE%BF%E0%AE%B4%E0%AF%8D%E0%AE%A8%E0%AE%BE%E0%AE%9F%E0%AF%81%20%28%E0%AE%AA%E0%AF%8B%E0%AE%A4%E0%AF%88%20OR%20%E0%AE%95%E0%AE%9E%E0%AF%8D%E0%AE%9A%E0%AE%BE%20OR%20%E0%AE%AA%E0%AF%8B%E0%AE%A4%E0%AF%88%E0%AE%AA%E0%AF%8D%E0%AE%AA%E0%AF%8A%E0%AE%B0%E0%AF%81%E0%AE%B3%E0%AF%8D%29%20%28%E0%AE%AA%E0%AE%B1%E0%AE%BF%E0%AE%AE%E0%AF%81%E0%AE%A4%E0%AE%B2%E0%AF%8D%20OR%20%E0%AE%95%E0%AF%88%E0%AE%A4%E0%AF%81%29&hl=ta-IN&gl=IN&ceid=IN:ta",
        "name":         "Google News (TN Drugs Tamil)",
    },
    {
        "source_label": "rss_gnews_tvk_govt_ta",
        "tier":         "regional_press",
        "rss_url":      "https://news.google.com/rss/search?q=%E0%AE%A4%E0%AE%B5%E0%AF%86%E0%AE%95%20OR%20%28%E0%AE%B5%E0%AE%BF%E0%AE%9C%E0%AE%AF%E0%AF%8D%20%E0%AE%86%E0%AE%9F%E0%AF%8D%E0%AE%9A%E0%AE%BF%29%20OR%20%28%E0%AE%A4%E0%AE%AE%E0%AE%BF%E0%AE%B4%E0%AE%95%20%E0%AE%85%E0%AE%B0%E0%AE%9A%E0%AF%81%20%E0%AE%B5%E0%AE%BF%E0%AE%9C%E0%AE%AF%E0%AF%8D%29&hl=ta-IN&gl=IN&ceid=IN:ta",
        "name":         "Google News (TVK Govt Tamil)",
    },
    {
        "source_label": "rss_gnews_civic_ta",
        "tier":         "regional_press",
        "rss_url":      "https://news.google.com/rss/search?q=%E0%AE%A4%E0%AE%AE%E0%AE%BF%E0%AE%B4%E0%AF%8D%E0%AE%A8%E0%AE%BE%E0%AE%9F%E0%AF%81%20%28%E0%AE%95%E0%AF%81%E0%AE%9F%E0%AE%BF%E0%AE%A8%E0%AF%80%E0%AE%B0%E0%AF%8D%20OR%20%E0%AE%95%E0%AE%B4%E0%AE%BF%E0%AE%B5%E0%AF%81%E0%AE%A8%E0%AF%80%E0%AE%B0%E0%AF%8D%20OR%20%E0%AE%95%E0%AF%81%E0%AE%AA%E0%AF%8D%E0%AE%AA%E0%AF%88%20OR%20%E0%AE%9A%E0%AE%BE%E0%AE%B2%E0%AF%88%20%E0%AE%AA%E0%AE%B3%E0%AF%8D%E0%AE%B3%E0%AE%AE%E0%AF%8D%29&hl=ta-IN&gl=IN&ceid=IN:ta",
        "name":         "Google News (TN Civic Tamil)",
    },
    {
        "source_label": "rss_gnews_womenchild_ta",
        "tier":         "regional_press",
        "rss_url":      "https://news.google.com/rss/search?q=%E0%AE%A4%E0%AE%AE%E0%AE%BF%E0%AE%B4%E0%AF%8D%E0%AE%A8%E0%AE%BE%E0%AE%9F%E0%AF%81%20%28%E0%AE%9A%E0%AE%BF%E0%AE%B1%E0%AF%81%E0%AE%AE%E0%AE%BF%20OR%20%E0%AE%AA%E0%AF%86%E0%AE%A3%E0%AF%8D%20OR%20%E0%AE%95%E0%AF%81%E0%AE%B4%E0%AE%A8%E0%AF%8D%E0%AE%A4%E0%AF%88%29%20%28%E0%AE%AA%E0%AE%BE%E0%AE%B2%E0%AE%BF%E0%AE%AF%E0%AE%B2%E0%AF%8D%20OR%20%E0%AE%A4%E0%AE%BE%E0%AE%95%E0%AF%8D%E0%AE%95%E0%AF%81%E0%AE%A4%E0%AE%B2%E0%AF%8D%20OR%20%E0%AE%95%E0%AE%9F%E0%AE%A4%E0%AF%8D%E0%AE%A4%E0%AE%B2%E0%AF%8D%29&hl=ta-IN&gl=IN&ceid=IN:ta",
        "name":         "Google News (TN Women/Child Crime Tamil)",
    },
]


# Some sites (Spark+ behind Cloudflare) 403 the bot UA but accept a
# browser UA. Tried on 403 before giving up.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _fetch(url: str, timeout: int = 25) -> Optional[str]:
    for ua in (USER_AGENT, BROWSER_UA):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 403 and ua is USER_AGENT:
                continue  # retry once with browser UA
            logger.warning("HTTP %d fetching %s", e.code, url)
            return None
        except Exception as e:
            logger.warning("Fetch failed for %s: %s", url, e)
            return None
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
    """Parse RSS 2.0 / Atom into a uniform list of item dicts.

    Each dict has: link, title, description (+content if available),
    pub_date_iso, media_urls.
    """
    items: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_text)
        for el in root.iter():
            if "}" in el.tag:
                el.tag = el.tag.split("}", 1)[1]
        # Both RSS <item> and Atom <entry> handled
        for it in list(root.iter("item")) + list(root.iter("entry")):
            d: dict[str, Any] = {"media_urls": []}
            for child in it:
                tag = child.tag.lower()
                if tag == "link":
                    href = child.attrib.get("href")
                    d["link"] = (href or child.text or "").strip()
                elif tag in ("title", "description", "summary"):
                    d[tag] = (child.text or "").strip()
                elif tag == "encoded":
                    d["content"] = (child.text or "").strip()
                elif tag in ("pubdate", "published", "updated"):
                    d["pub_date"] = (child.text or "").strip()
                elif tag == "thumbnail":
                    u = child.attrib.get("url")
                    if u:
                        d["media_urls"].append(u)
                elif tag == "content" and child.attrib.get("url"):
                    d["media_urls"].append(child.attrib["url"])
            if "pub_date" in d:
                try:
                    dt = parsedate_to_datetime(d["pub_date"])
                    d["pub_date_iso"] = dt.astimezone(timezone.utc).isoformat()
                except Exception:
                    d["pub_date_iso"] = ""
            else:
                d["pub_date_iso"] = ""
            items.append(d)
    except ET.ParseError:
        # Regex fallback (Reddit's RSS occasionally serves slightly off XML)
        for m in re.finditer(r"<item\b[^>]*>(.*?)</item>", xml_text, flags=re.S | re.I):
            block = m.group(1)
            def _grab(tag: str) -> str:
                mm = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", block, flags=re.S | re.I)
                return (mm.group(1).strip() if mm else "")
            items.append({
                "link":          _strip_html(_grab("link")),
                "title":         _strip_html(_grab("title")),
                "description":   _strip_html(_grab("description")),
                "pub_date":      _grab("pubDate"),
                "pub_date_iso":  "",
                "media_urls":    [],
            })
    return items


def _build_webhook_item(item: dict[str, Any], source: dict[str, str]) -> Optional[ApifyWebhookItem]:
    url = item.get("link")
    if not url:
        return None
    title = item.get("title") or ""
    # Body: prefer full content, fall back to description/summary
    body_html = item.get("content") or item.get("description") or item.get("summary") or ""
    body = _strip_html(body_html)
    if not body and not title:
        return None
    return ApifyWebhookItem(
        url=url,
        title=title[:200],
        text=body[:8000],
        published_at=item.get("pub_date_iso") or item.get("pub_date", ""),
        source=source["source_label"],
        tier=source["tier"],
        image_urls=(item.get("media_urls") or [])[:5],
    )


def _record_feed_health(source: dict[str, str], *, ok: bool,
                        item_count: int = 0, processed: int = 0,
                        error: str | None = None) -> None:
    """Upsert true fetch telemetry for this feed (table: feed_health).

    This is what makes 'broken feed' detection honest — the sources-table
    freshness metric only sees when an article last arrived, which can't
    distinguish a dead feed from an outlet that simply had no TN coverage.
    Never raises: telemetry must not break ingestion.
    """
    try:
        from app.database import get_db
        from datetime import datetime, timezone
        db = get_db()
        now = datetime.now(timezone.utc).isoformat()
        row: dict[str, Any] = {
            "feed_label":         source["source_label"],
            "feed_name":          source.get("name") or source["source_label"],
            "last_attempt_at":    now,
            "last_http_ok":       ok,
            "last_item_count":    item_count,
            "last_new_processed": processed,
            "last_error":         (error or "")[:300] or None,
            "updated_at":         now,
        }
        if ok:
            row["last_success_at"] = now
            row["consecutive_failures"] = 0
        else:
            prev = (db.table("feed_health").select("consecutive_failures")
                    .eq("feed_label", source["source_label"]).execute().data or [])
            row["consecutive_failures"] = (prev[0].get("consecutive_failures", 0) + 1) if prev else 1
        db.table("feed_health").upsert(row, on_conflict="feed_label").execute()
    except Exception as e:
        logger.debug("feed_health telemetry failed for %s: %s", source.get("source_label"), e)


async def ingest_one_source(source: dict[str, str], *, max_items: int = 25) -> dict[str, Any]:
    """Pull one RSS source and AI-process every item via process_article.

    Returns counts {discovered, processed, errors}. Dedup happens
    inside process_article (URL already in `sources` table -> skip).
    """
    out = {"source": source["name"], "discovered": 0, "processed": 0, "errors": 0}
    xml_text = _fetch(source["rss_url"])
    if not xml_text:
        out["errors"] = 1
        _record_feed_health(source, ok=False, error="fetch failed (HTTP error or timeout)")
        return out
    items = _parse_rss(xml_text)
    out["discovered"] = len(items)
    for it in items[:max_items]:
        webhook_item = _build_webhook_item(it, source)
        if not webhook_item:
            continue
        try:
            await process_article(webhook_item)
            out["processed"] += 1
        except Exception as e:
            logger.warning("rss_ingest: process_article failed for %s: %s", webhook_item.url, e)
            out["errors"] += 1
    _record_feed_health(source, ok=True, item_count=len(items), processed=out["processed"])
    return out


def _rotated_sources(sources: list[dict[str, str]]) -> list[dict[str, str]]:
    """Rotate the source list by a time-derived offset so every source
    gets to be near the FRONT across the day.

    Why: on HF's free tier the background task running this sweep often
    dies partway through the loop, never reaching sources lower in the
    static list. With a fixed order, the same early sources get scraped
    every run while later ones (e.g. Sun News) starve for days. Rotating
    the start point each run means that even if only a few sources finish
    per run, the front of the queue moves — so over a handful of runs
    every source is covered. Simple, deterministic, no DB lookup, immune
    to the outlet-vs-source_label naming mismatch.
    """
    from datetime import datetime, timezone
    n = len(sources)
    if n <= 1:
        return list(sources)
    # New start index every ~30 min; walks the whole list over ~n*30 min.
    slot = int(datetime.now(timezone.utc).timestamp() // 1800)
    off = slot % n
    return sources[off:] + sources[:off]


async def ingest_all_sources(
    *, max_items_per_source: int = 25, max_seconds: float | None = None
) -> list[dict[str, Any]]:
    """Sweep every registered RSS source, with a ROTATING start point so HF
    background-task death never permanently starves the sources lower in the
    static list (Sun News, News18, etc. were chronically skipped).

    `max_seconds` is a soft time budget: once exceeded we stop STARTING new
    sources and return cleanly (the rotating start point means the next run
    picks up where this one left off). This lets the GitHub Actions job finish
    as a SUCCESS instead of being killed at the 20-min hard timeout (which
    showed as 'cancelled' on every run) — and it bounds the free-tier AI spend
    per run now that GH Actions is the single owner of this lane.
    """
    results: list[dict[str, Any]] = []
    start = time.monotonic()
    for src in _rotated_sources(SOURCES_RSS):
        if max_seconds is not None and (time.monotonic() - start) > max_seconds:
            results.append({"source": src["name"], "skipped": "time budget reached"})
            continue
        try:
            r = await ingest_one_source(src, max_items=max_items_per_source)
            results.append(r)
        except Exception as e:
            results.append({"source": src["name"], "error": str(e)})
    return results
