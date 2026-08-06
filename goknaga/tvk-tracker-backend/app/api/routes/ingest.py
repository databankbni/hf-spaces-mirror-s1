from fastapi import APIRouter, HTTPException, Header, BackgroundTasks, Query
from pydantic import BaseModel
from app.models.schemas import ApifyWebhookPayload
from app.ingestion.ai_processor import process_article, analyze_only
from app.ingestion.corroboration import sweep_pending, attempt_corroborate
from app.database import get_db
from app.config import settings
from urllib.parse import urlparse
import httpx
import re
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ingest", tags=["ingestion"])


class QuickAnalyzeRequest(BaseModel):
    url: str
    title: str | None = None
    text: str | None = None


def _strip_html(html: str) -> tuple[str, str]:
    """Very small HTML→title+text extractor (no BeautifulSoup dependency).
    Returns (title, plaintext). Drops scripts/styles, keeps article-like text."""
    # Title
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""

    # Drop script/style/nav/footer blocks
    body = re.sub(r"<(script|style|nav|footer|header|aside|noscript|iframe)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    # Prefer article tag if present
    article = re.search(r"<article[^>]*>(.*?)</article>", body, re.I | re.S)
    if article:
        body = article.group(1)

    # Strip remaining tags
    text = re.sub(r"<[^>]+>", " ", body)
    # Decode common entities
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", '"').replace("&#039;", "'").replace("&apos;", "'"))
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return title, text[:12000]


@router.post("/quick-analyze")
async def quick_analyze(body: QuickAnalyzeRequest, x_admin_secret: str = Header(...)):
    """Fetch a URL, run the AI extractor, and return the structured incident
    data WITHOUT saving it. The admin can then edit + publish via POST /incidents.
    """
    if x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")

    title = body.title or ""
    text = body.text or ""

    # Fetch URL if text not provided
    if not text:
        try:
            async with httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (TVK-Tracker AdminBot)"},
            ) as client:
                r = await client.get(body.url)
            if r.status_code >= 400:
                raise HTTPException(status_code=400, detail=f"Could not fetch URL (HTTP {r.status_code})")
            fetched_title, fetched_text = _strip_html(r.text)
            title = title or fetched_title
            text = fetched_text
        except httpx.RequestError as e:
            raise HTTPException(status_code=400, detail=f"Fetch failed: {e}")

    if not text or len(text) < 100:
        raise HTTPException(status_code=400, detail="Could not extract enough text from URL — paste manually")

    # Derive source outlet from URL host
    host = urlparse(body.url).netloc.replace("www.", "")

    # Run AI extractor in preview mode (no DB writes)
    try:
        extracted = analyze_only(url=body.url, source=host, title=title, text=text)
    except Exception as e:
        logger.exception("analyze_only failed")
        raise HTTPException(status_code=500, detail=f"AI analysis failed: {e}")

    return {
        "fetched_title": title,
        "fetched_text_preview": text[:1000],
        "source_host": host,
        "extracted": extracted,
    }


@router.post("/apify-webhook")
async def apify_webhook(
    payload: ApifyWebhookPayload,
    background_tasks: BackgroundTasks,
    x_apify_secret: str = Header(...),
):
    if x_apify_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")

    logger.info(f"Received {len(payload.items)} items from actor {payload.actorId}")
    for item in payload.items:
        background_tasks.add_task(process_article, item)

    return {"queued": len(payload.items)}


@router.post("/manual")
async def manual_ingest(
    url: str,
    title: str,
    text: str,
    background_tasks: BackgroundTasks,
    x_admin_secret: str = Header(...),
):
    """Manually submit an article URL for AI processing."""
    if x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")

    from app.models.schemas import ApifyWebhookItem
    item = ApifyWebhookItem(url=url, title=title, text=text)
    background_tasks.add_task(process_article, item)
    return {"status": "queued"}


@router.post("/sweep-verify")
async def sweep_verify(
    max_age_days: int = Query(45, ge=1, le=365,
        description="Only scan pending incidents whose incident_date is within this window"),
    limit: int | None = Query(None, ge=1, le=500,
        description="Cap the number of incidents scanned this call (omit for all)"),
    x_admin_secret: str = Header(...),
):
    """Sweep pending_verification incidents and try to auto-promote them
    using Google News RSS. For each pending incident:
      - Search Google News for press articles about the same event
      - If 2+ DISTINCT press outlets are found within ±7 days → promote
        to multi_source_verified, attach the corroborating URLs as sources

    Returns a summary: {candidates_scanned, promoted, failed, avg_outlets_per_promote}

    Hit this manually from the admin UI, or schedule via GitHub Actions cron.
    """
    if x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")

    summary = sweep_pending(max_age_days=max_age_days, limit=limit)
    return summary


@router.post("/verify-one/{incident_id}")
async def verify_one(
    incident_id: str,
    x_admin_secret: str = Header(...),
):
    """Try to auto-corroborate a single incident on demand.
    Useful when you've just added something and want to find press coverage
    immediately rather than waiting for the nightly sweep."""
    if x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")

    db = get_db()
    res = db.table("incidents").select(
        "id, title, summary, location, incident_date, source_urls, verification_status"
    ).eq("id", incident_id).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Incident not found")

    return attempt_corroborate(res.data)
