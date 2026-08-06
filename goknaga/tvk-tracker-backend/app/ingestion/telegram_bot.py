"""Telegram bot: image → OCR → AI extract → dedup → insert incident.

Pipeline
--------
1. Telegram POSTs an update to /api/webhook/telegram
2. Backend extracts photo (largest variant) + optional caption
3. Downloads image bytes via Telegram Bot API
4. OCRs via Google Vision (Tamil + English) — falls back to no-op if
   GOOGLE_VISION_API_KEY isn't configured
5. AI extracts structured incident from (OCR'd text + caption + any
   URL the caption mentions)
6. Fuzzy-matches against approved incidents in last 30 days
7. If duplicate -> reply 'ℹ️ already on dashboard, ignore' with link
8. If new -> insert as admin_verified incident, reply '✅ added' with link

Auth model
----------
Only chat IDs listed in settings.telegram_allowed_chat_ids
(comma-separated) are processed. All other chats are silently ignored
(don't even acknowledge — keeps the bot invisible to random people
who stumble onto it).

Cost: $0/month
  - Telegram bot (free)
  - Google Vision (1000 free OCR calls/month — admin upload volume
    is ~10-30/month, comfortably inside free tier)
  - Groq AI extraction (existing free tier)
"""
from __future__ import annotations
import base64
import difflib
import json
import logging
import re
import urllib.error
import urllib.request
from datetime import date, datetime, timezone, timedelta
from typing import Any, Optional

from app.config import settings
from app.database import get_db
from app.ingestion.ai_processor import (
    SYSTEM_PROMPT, EXTRACTION_PROMPT, llm_call_with_fallback,
    _strip_code_fences, _load_dmk_schemes_for_prompt,
)

logger = logging.getLogger(__name__)

DASHBOARD_URL = "https://tvk-tracker.vercel.app"

# Ring buffer of per-step diagnostics for the LAST ~50 Telegram
# processing attempts. Lets us debug "no reply" failures remotely
# via /api/webhook/telegram/recent-events without HF log access.
import collections as _collections
import time as _time
_RECENT_EVENTS: _collections.deque = _collections.deque(maxlen=50)


def _ev(chat_id, step: str, **detail) -> None:
    _RECENT_EVENTS.appendleft({
        "chat_id":   chat_id,
        "step":      step,
        "t":         _time.time(),
        **detail,
    })


# ---------------------------------------------------------------------------
# Telegram Bot API helpers
# ---------------------------------------------------------------------------
def _tg_api(method: str, payload: dict | None = None) -> dict:
    """Call Telegram Bot API with retry on SSL/network timeouts.

    Telegram's CDN occasionally drops SSL handshakes from HF's IPs
    (saw multiple 'handshake operation timed out' failures in the
    wild). Without retry, a one-off network glitch kills the entire
    upload. Three attempts with backoff fix ~95% of these.
    """
    if not settings.telegram_bot_token:
        return {"_error": "TELEGRAM_BOT_TOKEN not configured"}
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}"
    data = json.dumps(payload).encode() if payload else None
    import time as _t
    last_err = None
    for attempt in (1, 2, 3):
        req = urllib.request.Request(
            url,
            method="POST" if payload else "GET",
            data=data,
            headers={"Content-Type": "application/json"} if payload else {},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            # 4xx errors are not transient — don't retry, just return
            body = e.read().decode()[:200]
            if 400 <= e.code < 500:
                return {"_error": f"HTTP {e.code}: {body}"}
            last_err = f"HTTP {e.code}: {body}"
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:120]}"
        # Backoff: 0.8s, 2s before retry
        if attempt < 3:
            _t.sleep(0.8 * attempt)
    return {"_error": last_err}


def _send_message(chat_id: int, text: str, parse_mode: str | None = None) -> None:
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text[:4000],
                                "disable_web_page_preview": True}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    res = _tg_api("sendMessage", payload)
    if res.get("_error"):
        logger.warning("Telegram sendMessage failed: %s", res["_error"])


def _download_photo(file_id: str) -> tuple[Optional[bytes], Optional[str]]:
    """Two-step: getFile -> downloadFile from telegram CDN.

    Returns (bytes, None) on success, or (None, error_message) on failure
    so callers can surface the real error to the admin instead of a
    generic 'try again'.
    """
    meta = _tg_api("getFile", {"file_id": file_id})
    if meta.get("_error") or not meta.get("ok"):
        err = meta.get("_error") or str(meta)[:200]
        return None, f"getFile_failed: {err[:150]}"
    file_path = meta["result"].get("file_path")
    if not file_path:
        return None, f"getFile_no_path: {meta.get('result')}"
    url = f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{file_path}"
    # Retry once — Telegram CDN occasionally 5xx on the first hit
    last_err = None
    import time as _t
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(url, timeout=45) as r:
                data = r.read()
                if data:
                    return data, None
                last_err = "empty_body"
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}: {str(e)[:120]}"
            # 404/410 means file expired — no point retrying
            if e.code in (404, 410):
                break
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:120]}"
        if attempt == 1:
            _t.sleep(1.5)
    return None, f"cdn_download_failed: {last_err}"


def _download_any_photo_variant(photos: list[dict]) -> tuple[Optional[bytes], Optional[str], Optional[str]]:
    """Try downloading photo variants from largest to smallest.

    Telegram sends 4 size variants per photo (s/m/x/y). The largest often
    has the highest fidelity, but is also the most likely to hit CDN
    failures (bigger file = more chance of partial/timeout). Fall back
    through the sizes so a bad CDN response on the biggest variant doesn't
    block the upload.

    Returns (bytes, file_id_used, None) on success or (None, None, last_err).
    """
    # Sort largest → smallest by file_size (Telegram supplies it)
    sorted_variants = sorted(photos, key=lambda p: p.get("file_size") or 0, reverse=True)
    last_err = None
    for v in sorted_variants:
        fid = v.get("file_id")
        if not fid:
            continue
        data, err = _download_photo(fid)
        if data:
            return data, fid, None
        last_err = err
    return None, None, last_err


# ---------------------------------------------------------------------------
# OCR — Google Vision (best Tamil quality on the free tier)
# ---------------------------------------------------------------------------
def _ocr_via_vision(image_bytes: bytes) -> tuple[str, Optional[str]]:
    """OCR via Google Vision API. Returns (text, error_msg).

    Free tier: 1000 calls/month — way more than admin upload volume.
    On any failure returns ('', error_msg) so callers can surface why.
    """
    if not settings.google_vision_api_key:
        return "", "GOOGLE_VISION_API_KEY not configured"
    # DOCUMENT_TEXT_DETECTION is more accurate than TEXT_DETECTION for
    # dense / multi-block layouts (which fact-check posters and tweets
    # screenshot like 100% of the time).
    url = f"https://vision.googleapis.com/v1/images:annotate?key={settings.google_vision_api_key}"
    payload = {
        "requests": [{
            "image": {"content": base64.b64encode(image_bytes).decode()},
            "features": [{"type": "DOCUMENT_TEXT_DETECTION", "maxResults": 1}],
            "imageContext": {"languageHints": ["ta", "en"]},
        }]
    }
    req = urllib.request.Request(
        url, method="POST",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        return "", f"HTTP {e.code}: {body}"
    except Exception as e:
        return "", f"{type(e).__name__}: {str(e)[:120]}"
    # Vision API can return per-request errors inside responses[0].error
    resp0 = (data.get("responses") or [{}])[0]
    if resp0.get("error"):
        return "", f"vision_error: {resp0['error'].get('message', '')[:200]}"
    try:
        return resp0["fullTextAnnotation"]["text"], None
    except (KeyError, IndexError):
        # No text detected — not necessarily an error
        return "", "no_text_detected"


def _describe_image_via_vision_llm(image_bytes: bytes, caption: str) -> Optional[dict]:
    """Ask the Groq vision LLM to FULLY CLASSIFY the image as a TVK-era
    incident. Used when the main extraction returns is_relevant=False
    (the structured incident prompt is calibrated for skeptical
    unsupervised ingestion; admin uploads need a more permissive prompt
    that trusts the admin's judgment).

    Returns a full incident dict {title, summary, category, severity,
    location, incident_date, is_credit_steal, ocr_text} OR None on
    failure. With full classification, the caller can land the row
    as 'approved' instead of staging it for manual review.
    """
    if not settings.groq_api_key:
        return None
    from openai import OpenAI
    b64 = base64.b64encode(image_bytes).decode()
    today_iso = date.today().isoformat()
    prompt = (
        "You are classifying a news image for a Tamil Nadu political "
        "accountability dashboard tracking the TVK government (Vijay's "
        "party, sworn in May 11 2026). It was uploaded by the dashboard "
        "ADMIN — so it IS relevant to TVK accountability. Your job is "
        "to read the Tamil/English text and STRUCTURE it.\n\n"
        "Return ONLY a JSON object (no markdown, no commentary):\n"
        "{\n"
        '  "title":         <English headline, 8-15 words, factual>,\n'
        '  "summary":       <2-4 sentences in English: what happened, who, where, any numbers>,\n'
        '  "category":      <pick ONE: murders, sexual_assault, crimes_women_kids, '
        'corruption, police_excess, custodial_death, honour_killing, alcohol_menace, '
        'power_cut, eb_failure, broken_promise, attack_on_press, fake_news, '
        'propaganda_event, dravidian_attack, credit_stealing, civic_failure, '
        'economic_failure, federalism, language_imposition, political_event, '
        'governance, other>,\n'
        '  "severity":      <integer 1-5: 1=minor 3=serious 5=fatal/major>,\n'
        '  "location":      <city/district name in English, or null>,\n'
        '  "incident_date": <YYYY-MM-DD if visible in image, else null>,\n'
        '  "is_credit_steal": <true if TVK claims credit for DMK-era work, else false>,\n'
        '  "ocr_text":      <all visible text, Tamil+English, newline-separated>\n'
        "}\n\n"
        f"Today's date: {today_iso}. TVK govt era: anything from 2026-05-11 onward.\n"
        f"User caption (may be empty): {caption[:300]}\n\n"
        "RULES:\n"
        "- ANTI-HALLUCINATION (critical): Use ONLY facts literally present "
        "in the text. Do NOT invent or guess numbers, UNITS (acres vs "
        "seats vs crore vs km), place names, or actions. If the text says "
        "'152 super-specialty medical courses/seats', do NOT turn it into "
        "'152 acres' or a 'medical college in <town>'. If a number's unit "
        "isn't explicit, keep the exact word shown. If you are unsure what "
        "happened, write a SHORT literal description, not a confident "
        "fabrication. A vague-but-true title beats a specific-but-wrong one.\n"
        "- Read the WHOLE argument, not just keywords. A tweet mentioning "
        "'medical' + a number is NOT automatically about building a college "
        "— it may be a grievance about the CENTRE denying TN's powers.\n"
        "- If the image is in Tamil, translate to English for title/summary.\n"
        "- Pick the most specific category. 'other' only if nothing fits.\n"
        "- If a date is shown in the image (top-right corner of news graphics "
        "is common), parse it into YYYY-MM-DD.\n"
        "- STATE RIGHTS / FEDERALISM: if the text is a grievance about the "
        "Union/central government overriding TN's authority — denying state "
        "approval powers, centralising decisions, super-specialty/medical "
        "seat control, NEET, fund devolution, Governor overreach, "
        "delimitation → category=federalism. For language (Hindi imposition, "
        "three-language NEP) → category=language_imposition.\n"
        "- For police harassment/atrocity by police → use police_excess.\n"
        "- For violence against women → sexual_assault or crimes_women_kids.\n"
        "- For murder/killing/sickle attack/honour killing → murders.\n"
        "- For fact-check graphics about TVK claims → propaganda_event.\n"
        "- POLITICAL/PARTY/CEREMONIAL (rally, roadshow, alliance, Rajya Sabha "
        "seat, CM speech/statement, ribbon-cutting, fan/cult content like "
        "mannequin worship) → political_event, NOT governance. These are "
        "political news, not accountability failures.\n"
        "\n"
        "IMPORTANT — DO NOT GET CONFUSED BY VIDEO/LIVE OVERLAYS:\n"
        "Many uploads are SCREENSHOTS of news TV channels (Sun News, "
        "Polimer, Thanthi, Puthiya Thalaimurai, Kalaignar) or YouTube "
        "news clips. These have overlays like 'BREAKING NEWS', 'LIVE', "
        "play-button icons, video duration timestamps, channel logos.\n"
        "  - IGNORE those overlays. They are CHROME, not content.\n"
        "  - The Tamil/English text in the center/headline strip IS the "
        "incident — read it and structure it.\n"
        "  - 'Social media post' / 'video thumbnail' is NOT a valid reason "
        "to skip — a news clip about a real event IS the event.\n"
        "\n"
        "ONLY return {\"title\": \"\"} when the image truly contains NO "
        "extractable text and NO discernible event (e.g. a blank screen, "
        "a pure logo, a meme with no factual claim). When in doubt, "
        "RETURN A TITLE — the admin already vouched by uploading."
    )
    client = OpenAI(
        timeout=40, max_retries=1,
        api_key=settings.groq_api_key,
        base_url="https://api.groq.com/openai/v1",
    )
    for model in ("meta-llama/llama-4-scout-17b-16e-instruct",
                  "llama-3.2-90b-vision-preview",
                  "llama-3.2-11b-vision-preview"):
        try:
            resp = client.chat.completions.create(
                model=model,
                max_tokens=900,
                messages=[
                    {"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}",
                        }},
                    ]},
                ],
            )
            raw = resp.choices[0].message.content
            try:
                return json.loads(_strip_code_fences(raw))
            except Exception:
                # Some models wrap JSON in prose — try to find the {...}
                m = re.search(r"\{[\s\S]+\}", raw)
                if m:
                    try:
                        return json.loads(m.group(0))
                    except Exception:
                        pass
                continue
        except Exception as e:
            logger.warning("describe_image vision model %s failed: %s", model, e)
            continue
    return None


# ---------------------------------------------------------------------------
# Fuzzy dedup against recent incidents
# ---------------------------------------------------------------------------
def _normalize_for_match(text: str) -> str:
    """Lowercase + strip non-alphanumerics for fuzzy match."""
    return re.sub(r"[^a-z0-9 ]+", "", (text or "").lower()).strip()


def _event_sig(category: str, location: str | None, incident_date: str | None) -> str:
    """Coarse event signature — matches identical (category, normalized
    location, incident_date) triples. Catches the case where AI words
    the title differently each time but extracts the same underlying
    event."""
    loc = re.sub(r"[^a-z0-9]+", "", (location or "").lower())[:30]
    return f"{(category or '').lower()}:{loc}:{incident_date or ''}"


def _find_duplicate(extracted: dict, lookback_days: int = 30) -> Optional[dict]:
    """Return the most-similar existing approved incident.

    Two-layer dedup:
      A. Event-signature exact match — (category, normalized location,
         incident_date) triple. Most reliable when AI worded the title
         differently across uploads (e.g. 'SC-Christians' vs 'Dalits').
      B. Fuzzy title+summary similarity >= 0.55 — backstop for when
         AI got slightly-off date or location.

    Threshold dropped 0.65 -> 0.55 after the AI extracted the same
    Tenkasi sickle-attack image with different wordings each time,
    pushing ratio below the old cutoff.
    """
    db = get_db()
    since = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).date().isoformat()
    try:
        r = (
            db.table("incidents")
            .select("id, title, summary, category, location, incident_date, event_signature")
            .eq("status", "approved")
            .gte("incident_date", since)
            .execute()
        )
        rows = r.data or []
    except Exception:
        return None

    # Layer A: event-signature exact match — but GUARDED. A bare
    # (category, date) signature with an empty or broad location collides
    # across totally unrelated incidents (e.g. two 'governance' items on
    # the same day), which produced false "100% match" rejections that
    # silently discarded real incidents — e.g. a state-rights tweet
    # wrongly matched to a road-construction entry. So we only trust the
    # signature match when BOTH:
    #   (1) the location is specific (not empty / not a bare state name), AND
    #   (2) the titles are at least loosely similar (ratio >= 0.35) —
    #       otherwise the signature collision is spurious.
    new_sig = _event_sig(
        extracted.get("category", ""),
        extracted.get("location"),
        extracted.get("incident_date"),
    )
    new_loc = re.sub(r"[^a-z0-9]+", "", (extracted.get("location") or "").lower())
    BROAD_LOC = {"tamilnadu", "tn", "india", "chennai"}  # too broad to dedup on alone
    new_title_norm = _normalize_for_match(
        f"{extracted.get('title', '')} {extracted.get('summary', '')[:200]}"
    )
    if new_loc and len(new_loc) >= 4 and new_loc not in BROAD_LOC:
        for row in rows:
            if row.get("event_signature") == new_sig and new_sig != ":":
                cand = _normalize_for_match(
                    f"{row.get('title', '')} {(row.get('summary', '') or '')[:200]}"
                )
                # Spurious-collision guard: same cat+loc+date but different
                # event → titles won't match → not a duplicate.
                if new_title_norm and cand:
                    tr = difflib.SequenceMatcher(None, new_title_norm, cand).ratio()
                    if tr < 0.35:
                        continue
                row["_match_ratio"] = 1.0
                row["_match_via"] = "event_signature"
                return row

    # Layer B: fuzzy similarity on title+summary head
    target = _normalize_for_match(
        f"{extracted.get('title', '')} {extracted.get('summary', '')[:200]}"
    )
    if not target:
        return None
    best_match = None
    best_ratio = 0.0
    for row in rows:
        candidate = _normalize_for_match(
            f"{row.get('title', '')} {(row.get('summary', '') or '')[:200]}"
        )
        if not candidate:
            continue
        ratio = difflib.SequenceMatcher(None, target, candidate).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = row
    if best_match and best_ratio >= 0.55:
        best_match["_match_ratio"] = round(best_ratio, 2)
        best_match["_match_via"] = "fuzzy_title"
        return best_match
    return None


# ---------------------------------------------------------------------------
# AI extraction (reuses the same prompt as Twitter/RSS path)
# ---------------------------------------------------------------------------
def _extract_incident(*, ocr_text: str, caption: str, source_url: str) -> Optional[dict]:
    db = get_db()
    schemes_block = _load_dmk_schemes_for_prompt(db)
    combined_text = ocr_text
    if caption:
        combined_text = f"USER CAPTION: {caption}\n\n--- OCR'D ARTICLE TEXT ---\n{ocr_text}"
    prompt = EXTRACTION_PROMPT.format(
        url=source_url or "telegram_upload",
        source="telegram_admin_upload",
        published=date.today().isoformat(),
        title=caption[:100] if caption else "Telegram-uploaded screenshot",
        text=combined_text[:8000],
        dmk_schemes=schemes_block,
        today=date.today().isoformat(),
    )
    raw = llm_call_with_fallback(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=900,
    )
    if not raw:
        return None
    try:
        return json.loads(_strip_code_fences(raw))
    except Exception:
        logger.warning("Telegram bot: AI returned invalid JSON")
        return None


def _extract_incident_from_image(*, image_bytes: bytes, caption: str, source_url: str) -> Optional[dict]:
    """Vision-model extraction — reads the image directly, skipping OCR.

    Works much better than 'OCR + then AI on the text' for:
      - mobile-compressed screenshots (Tamil glyphs survive better when
        read pixel-by-pixel vs OCR'd to text first)
      - multi-panel composites (vision model sees layout context, not
        just a wall of de-positioned text)
      - mixed-language headlines (Tamil + English in same image)
      - tweets/social posts with images (extracts both the post text
        AND any sub-images at once)

    Uses Groq's llama-3.2-90b-vision-preview (free tier). Falls back
    to None on failure — caller can then attempt the OCR+text path
    if Vision API is configured.
    """
    if not settings.groq_api_key:
        return None
    from openai import OpenAI
    db = get_db()
    schemes_block = _load_dmk_schemes_for_prompt(db)
    b64 = base64.b64encode(image_bytes).decode()

    # OCR-FIRST for accuracy. The Groq vision model is unreliable at READING
    # dense Tamil from pixels — it hallucinated "152 acres in Namakkal" and
    # "152 doctors to get MBBS" for a tweet that actually says TN was denied
    # approval power over 152 super-specialty medical courses. Google Vision
    # OCR reads Tamil far more accurately. So we OCR the exact text first and
    # feed it to the model as the AUTHORITATIVE source — the model then only
    # has to translate + classify clean text, not decipher glyphs. The image
    # still rides along for layout/context. Degrades gracefully if OCR is
    # unavailable (billing off / no key) — falls back to pixel reading.
    ocr_text, ocr_err = _ocr_via_vision(image_bytes)
    # Diagnostic: record whether OCR actually produced text or errored, so
    # /recent-events tells us if Google Vision billing is the blocker (the
    # bot can't read dense Tamil well without it). chat_id unknown here, use
    # None — the recent-events endpoint shows all entries.
    _ev(None, "ocr_first_result", chars=len((ocr_text or "").strip()),
        err=(ocr_err or "")[:120])
    ocr_block = ""
    if ocr_text and len(ocr_text.strip()) >= 30:
        ocr_block = (
            "\n\n=== AUTHORITATIVE EXACT TEXT (Google Vision OCR — TRUST THIS "
            "over your own reading of the pixels) ===\n"
            f"{ocr_text.strip()[:5000]}\n"
            "=== END OCR TEXT ===\n"
            "Base your title/summary on the OCR text above. Translate it to "
            "English faithfully. Do NOT add facts, numbers, units, or place "
            "names that are not in this OCR text. Use the image only for "
            "layout/date context."
        )

    prompt_text = EXTRACTION_PROMPT.format(
        url=source_url or "telegram_upload",
        source="telegram_admin_upload",
        published=date.today().isoformat(),
        title=caption[:100] if caption else "Telegram-uploaded screenshot",
        text=(
            f"USER CAPTION: {caption}\n\n"
            f"--- IMAGE BELOW — read all text (Tamil + English), "
            f"understand the layout, identify the incident ---"
            f"{ocr_block}"
        ),
        dmk_schemes=schemes_block,
        today=date.today().isoformat(),
    )
    client = OpenAI(
        timeout=40, max_retries=1,
        api_key=settings.groq_api_key,
        base_url="https://api.groq.com/openai/v1",
    )
    # Groq's multimodal models — try newer first, fall back
    for model in ("meta-llama/llama-4-scout-17b-16e-instruct",
                  "llama-3.2-90b-vision-preview",
                  "llama-3.2-11b-vision-preview"):
        try:
            resp = client.chat.completions.create(
                model=model,
                max_tokens=900,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": [
                        {"type": "text", "text": prompt_text},
                        {"type": "image_url", "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}",
                        }},
                    ]},
                ],
            )
            raw = resp.choices[0].message.content
            try:
                return json.loads(_strip_code_fences(raw))
            except Exception:
                logger.warning("Vision model returned invalid JSON: %s", raw[:200])
                continue
        except Exception as e:
            logger.warning("Vision model %s failed: %s", model, e)
            continue
    return None


# ---------------------------------------------------------------------------
# Caption URL extraction (so admin can paste a press URL alongside image)
# ---------------------------------------------------------------------------
_URL_RE = re.compile(r"https?://[^\s]+", re.I)


def _extract_url_from_caption(caption: str) -> str:
    if not caption:
        return ""
    m = _URL_RE.search(caption)
    return m.group(0) if m else ""


# ---------------------------------------------------------------------------
# URL ingestion — admin can paste a tweet link, news URL, or image URL
# instead of uploading a screenshot.
# ---------------------------------------------------------------------------
_IMG_EXT_RE = re.compile(r"\.(jpg|jpeg|png|webp|gif|bmp)(\?|$)", re.I)
_DASHBOARD_HOSTS = ("tvk-tracker.vercel.app", "goknaga-tvk-tracker")


def _is_dashboard_url(url: str) -> bool:
    return any(h in url for h in _DASHBOARD_HOSTS)


def _download_image_url(url: str) -> Optional[bytes]:
    """Download an image from a direct URL. Returns bytes or None."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            ctype = (r.headers.get("Content-Type") or "").lower()
            data = r.read()
            if "image" in ctype or _IMG_EXT_RE.search(url):
                return data
    except Exception as e:
        logger.warning("image URL download failed: %s", e)
    return None


def _fetch_url_text(url: str) -> str:
    """Fetch a web page / tweet as clean readable text via Jina Reader
    (r.jina.ai — free, no auth, renders JS so it works on x.com/twitter
    which are otherwise un-scrapable). Falls back to a raw fetch + HTML
    strip if Jina is unavailable."""
    # 1. Jina Reader — best for JS-heavy pages (tweets) and articles
    try:
        jina = "https://r.jina.ai/" + url
        req = urllib.request.Request(jina, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=40) as r:
            txt = r.read().decode("utf-8", "ignore")
            if txt and len(txt.strip()) >= 50:
                return txt[:8000]
    except Exception as e:
        logger.warning("Jina reader failed for %s: %s", url, e)
    # 2. Fallback: raw fetch + crude HTML strip
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read().decode("utf-8", "ignore")
        text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:8000]
    except Exception as e:
        logger.warning("raw fetch failed for %s: %s", url, e)
    return ""


def _ingest_from_url(chat_id: int, url: str, caption: str) -> None:
    """Ingest an incident from a pasted URL (tweet / news article / image).
    Self-contained: fetch -> extract -> date-gate -> dedup -> insert ->
    reply. Mirrors the image-upload finalize, lands as admin_verified."""
    is_image = bool(_IMG_EXT_RE.search(url))
    _ev(chat_id, "url_ingest_start", kind="image" if is_image else "page",
        url=url[:50])
    _send_message(chat_id, "Got it — reading the link (~15s)...")

    extracted = None
    if is_image:
        img = _download_image_url(url)
        if img:
            extracted = _extract_incident_from_image(
                image_bytes=img, caption=caption, source_url=url)
    if extracted is None:
        text = _fetch_url_text(url)
        _ev(chat_id, "url_text_fetched", chars=len(text))
        if len(text.strip()) >= 50:
            extracted = _extract_incident(
                ocr_text=text, caption=caption, source_url=url)
        elif not is_image:
            # last resort: maybe it's actually an image with no extension
            img = _download_image_url(url)
            if img:
                extracted = _extract_incident_from_image(
                    image_bytes=img, caption=caption, source_url=url)

    if not extracted or not (extracted.get("title") or "").strip():
        _send_message(chat_id,
            "Couldn't read a usable incident from that link.\n"
            "If it's an x.com/twitter post, the page may be login-walled — "
            "screenshot it and upload the image instead.")
        return

    # Admin pasted it -> admin vouches; bypass the relevance gate.
    extracted["_admin_override"] = True

    # Hard date gate
    from datetime import date as _date
    inc_date_s = extracted.get("incident_date")
    if inc_date_s:
        try:
            if _date.fromisoformat(inc_date_s) < _date(2026, 5, 11):
                _send_message(chat_id,
                    f"Not added: incident is pre-May-11 2026 ({inc_date_s}). "
                    f"The tracker only covers the TVK admin era.")
                return
        except Exception:
            pass

    # Dedup
    try:
        duplicate = _find_duplicate(extracted)
    except Exception:
        duplicate = None
    if duplicate:
        _send_message(chat_id,
            f"ℹ️ Already on dashboard ({int(duplicate['_match_ratio']*100)}% match):\n"
            f"\"{duplicate['title']}\"\n"
            f"{DASHBOARD_URL}/incidents/{duplicate['id']}\n\n"
            f"You can ignore this — it's already captured.")
        return

    db = get_db()
    payload = {
        "title":              (extracted.get("title") or "Untitled incident")[:200],
        "summary":            (extracted.get("summary") or extracted.get("title") or "")[:2000],
        "category":           extracted.get("category", "other"),
        "incident_date":      extracted.get("incident_date") or date.today().isoformat(),
        "location":           extracted.get("location"),
        "severity":           _clamp_severity(extracted.get("severity")),
        "ai_confidence":      extracted.get("confidence", 0.8),
        "status":             "approved",
        "verification_status": "admin_verified",
        "source_urls":        [url],
        "source_count":       1,
        "ai_raw": {
            "telegram_source": True, "caption": caption,
            "extraction_path": "url_paste", "from_chat_id": chat_id,
            "source_url": url,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "admin_override": True, "ai_reason": extracted.get("reason"),
        },
        "is_credit_steal":    extracted.get("is_credit_steal", False),
        "press_sentiment":    extracted.get("press_sentiment"),
        "image_urls":         [],
        "member_ids":         [],
        "event_signature":    _event_sig(
            extracted.get("category", ""), extracted.get("location"),
            extracted.get("incident_date")),
    }
    _ev(chat_id, "url_insert_attempt", title=payload["title"][:50],
        category=payload["category"])
    try:
        res = db.table("incidents").insert(payload).execute()
        if not res.data:
            _send_message(chat_id, "Insert failed (no row). Check backend logs.")
            return
        new_id = res.data[0]["id"]
        _LAST_INCIDENT_BY_CHAT[chat_id] = new_id
        try:
            db.table("incident_audit").insert({
                "incident_id": new_id, "action": "created",
                "actor": "telegram_bot", "to_value": "admin_verified",
                "reason": f"Telegram URL paste from chat {chat_id}: {url[:120]}",
            }).execute()
        except Exception:
            pass
        _send_message(chat_id,
            f"NEW INCIDENT ADDED (from link)\n"
            f"Title: {payload['title']}\n"
            f"Category: {payload['category']} · severity {payload['severity']}\n"
            f"{DASHBOARD_URL}/incidents/{new_id}")
    except Exception as e:
        _ev(chat_id, "url_insert_exception", err=f"{type(e).__name__}: {str(e)[:120]}")
        _send_message(chat_id, f"Insert error: {str(e)[:200]}")


# ---------------------------------------------------------------------------
# Auth: only allow whitelisted chat IDs
# ---------------------------------------------------------------------------
def _clamp_severity(raw: Any) -> int:
    """Coerce AI's severity output to a valid int in [1,5].

    The DB has `severity int check (severity between 1 and 5)`; the AI
    has been observed returning out-of-range ints (0, 6, 10) and even
    strings ('high', 'critical'). Without this clamp the insert blows
    up with a `incidents_severity_check` violation and the upload is
    dropped on the floor.
    """
    if raw is None:
        return 3
    if isinstance(raw, str):
        s = raw.strip().lower()
        mapping = {"low": 2, "medium": 3, "moderate": 3, "high": 4,
                   "severe": 5, "critical": 5, "extreme": 5, "fatal": 5}
        if s in mapping:
            return mapping[s]
        try:
            raw = int(float(s))
        except Exception:
            return 3
    try:
        n = int(raw)
    except Exception:
        return 3
    if n < 1:
        return 1
    if n > 5:
        return 5
    return n


# ---------------------------------------------------------------------------
# Per-chat "most recent incident" pointer — lets admin issue follow-up
# commands without re-stating the incident ID. Survives until next HF
# redeploy, which is fine (commands are reactive, not async).
# ---------------------------------------------------------------------------
_LAST_INCIDENT_BY_CHAT: dict[int, str] = {}

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.I,
)


def _extract_incident_id(text: str) -> Optional[str]:
    """Pull an incident UUID from a URL, raw UUID, or short prefix."""
    if not text:
        return None
    m = _UUID_RE.search(text)
    return m.group(0).lower() if m else None


# Category synonyms — admin's natural-language → canonical category.
# Keep this LOW: only the categories admins actually retag toward.
_CATEGORY_SYNONYMS: dict[str, str] = {
    "credit steal":     "credit_steal_meta",  # special: also flips flag
    "credit stealing":  "credit_steal_meta",
    "credit theft":     "credit_steal_meta",
    "credit":           "credit_steal_meta",
    "propaganda":       "propaganda_event",
    "fact check":       "propaganda_event",
    "factcheck":        "propaganda_event",
    "murder":           "law_and_order",
    "murders":          "law_and_order",
    "law order":        "law_and_order",
    "law and order":    "law_and_order",
    "promise":          "broken_promise",
    "broken promise":   "broken_promise",
    "dravidian":        "dravidian_attack",
    "economy":          "economic_failure",
    "economic":         "economic_failure",
    "state rights":     "federalism",
    "state right":      "federalism",
    "states rights":    "federalism",
    "federalism":       "federalism",
    "federal":          "federalism",
    "union overreach":  "federalism",
    "language":         "language_imposition",
    "hindi imposition": "language_imposition",
}


def _parse_admin_command(text: str) -> Optional[dict]:
    """Parse a plain-text command into a structured update dict.

    Supports natural-language tags an admin might type while looking at
    their phone, NOT a strict CLI. Returns None if no command detected.

    Examples that work:
      "tag under credit stealing"           → {category: credit_steal_meta, is_credit_steal: true}
      "credit steal"                        → same
      "severity 4"                          → {severity: 4}
      "set severity to 5"                   → {severity: 5}
      "category propaganda"                 → {category: propaganda_event}
      "location chennai"                    → {location: 'chennai'}
      "delete" / "reject" / "not relevant"  → {status: rejected}
      "approve"                             → {status: approved, verification_status: admin_verified}
      "credit"                              → {is_credit_steal: true}
    """
    if not text:
        return None
    s = text.strip().lower()
    updates: dict[str, Any] = {}

    # Severity: "severity 4", "set severity to 5", "sev 3"
    m = re.search(r"\bsev(?:erity)?\s+(?:to\s+)?(\d)\b", s)
    if m:
        sev = int(m.group(1))
        if 1 <= sev <= 5:
            updates["severity"] = sev

    # Explicit "category X" prefix → look up synonym
    m = re.search(r"\b(?:category|cat|tag(?:\s+under|\s+as)?)\s+([a-z_ ]+?)(?:\s+(?:severity|location|$)|$)", s)
    if m:
        phrase = m.group(1).strip()
        # Best-match synonym
        for k, v in _CATEGORY_SYNONYMS.items():
            if k in phrase:
                if v == "credit_steal_meta":
                    updates["category"] = "credit_stealing"
                    updates["is_credit_steal"] = True
                else:
                    updates["category"] = v
                break

    # Bare synonym match (no "category" prefix needed) — only if no
    # category was set above
    if "category" not in updates:
        for k, v in _CATEGORY_SYNONYMS.items():
            if re.search(rf"\b{re.escape(k)}\b", s):
                if v == "credit_steal_meta":
                    updates["category"] = "credit_stealing"
                    updates["is_credit_steal"] = True
                else:
                    updates["category"] = v
                break

    # Location: "location chennai", "in chennai"
    m = re.search(r"\b(?:location|loc|in)\s+([a-z][a-z ]{2,40})", s)
    if m:
        loc = m.group(1).strip().title()
        # Strip trailing common words that bleed in
        loc = re.sub(r"\s+(Severity|Category|Tag)$", "", loc, flags=re.I)
        updates["location"] = loc

    # Status verbs
    if re.search(r"\b(delete|reject|remove|not\s+relevant|drop)\b", s):
        updates["status"] = "rejected"
    elif re.search(r"\b(approve|approved|verified|ok|publish)\b", s):
        updates["status"] = "approved"
        updates["verification_status"] = "admin_verified"

    return updates or None


def _apply_incident_update(incident_id: str, updates: dict, chat_id: int) -> Optional[dict]:
    """Apply admin command updates to an incident. Returns the new row
    (or None on failure)."""
    db = get_db()
    try:
        res = db.table("incidents").update(updates).eq("id", incident_id).execute()
    except Exception as e:
        logger.error("Telegram command update failed: %s", e)
        return None
    if not res.data:
        return None
    # Audit trail
    try:
        db.table("incident_audit").insert({
            "incident_id": incident_id,
            "action":      "updated",
            "actor":       "telegram_bot",
            "to_value":    json.dumps(updates),
            "reason":      f"Admin command from chat {chat_id}",
        }).execute()
    except Exception:
        pass
    return res.data[0]


def _is_allowed_chat(chat_id: int) -> bool:
    raw = (settings.telegram_allowed_chat_ids or "").strip()
    if not raw:
        # Empty whitelist = disabled (deny all). Operator must opt in
        # by adding their chat ID to the env var.
        return False
    allowed = {s.strip() for s in raw.split(",") if s.strip()}
    return str(chat_id) in allowed


# ---------------------------------------------------------------------------
# Main entry — called from the webhook endpoint
# ---------------------------------------------------------------------------
async def handle_update(update: dict[str, Any]) -> None:
    """Process one Telegram Update payload. Idempotent; fast-returns on
    non-allowed chats / non-photo messages."""
    msg = update.get("message") or update.get("channel_post") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    _ev(chat_id, "handler_entered", has_photo=bool(msg.get("photo")),
        has_document=bool(msg.get("document")),
        has_text=bool(msg.get("text")))
    if not chat_id or not _is_allowed_chat(chat_id):
        _ev(chat_id, "rejected_unauthorized_chat")
        return

    # Telegram represents image uploads two ways:
    #  - `photo`: compressed inline image (mobile/standard upload)
    #  - `document`: original-quality file (Telegram Web drag-drop often
    #    uses this for images, also when user explicitly attaches as
    #    file). We accept both transparently.
    photos = msg.get("photo") or []
    document = msg.get("document") or {}
    is_image_doc = (
        document
        and (document.get("mime_type") or "").startswith("image/")
    )
    caption = (msg.get("caption") or "").strip()

    # /start handshake — confirm the bot is alive for new admins
    text = (msg.get("text") or "").strip()
    if text.startswith("/start") or text.startswith("/help"):
        _send_message(chat_id,
            "TVK Tracker bot — upload a screenshot and I'll extract the "
            "incident, check for duplicates, and add it to the dashboard.\n\n"
            "After upload, you can tag the incident with plain text:\n"
            "  • \"tag under credit stealing\" / \"credit\"\n"
            "  • \"category propaganda\" / \"category murders\"\n"
            "  • \"severity 4\"\n"
            "  • \"location chennai\"\n"
            "  • \"delete\" / \"reject\" / \"approve\"\n\n"
            "Commands apply to your most recent incident, or reply to a "
            f"specific bot message to target that one.\n\n"
            f"Dashboard: {DASHBOARD_URL}"
        )
        return

    if not photos and not is_image_doc:
        # Text-only message. Three paths:
        #  A. Reply to a bot message with an incident URL → command on that
        #  B. Bare command (e.g. "credit steal") → apply to most recent
        #     incident from this chat
        #  C. URL → not yet implemented, prompt for image
        #  D. Anything else → upload prompt
        if text:
            # Look for incident ID in the message the user replied to
            target_id = None
            reply_to = msg.get("reply_to_message") or {}
            reply_text = (reply_to.get("text") or "") + " " + (reply_to.get("caption") or "")
            if reply_text:
                target_id = _extract_incident_id(reply_text)
            # Or pulled out of the admin's own message text
            if not target_id:
                target_id = _extract_incident_id(text)
            # Or default to "most recent" pointer for this chat
            if not target_id:
                target_id = _LAST_INCIDENT_BY_CHAT.get(chat_id)

            # URL INGESTION — if the message contains an EXTERNAL content
            # URL (not a dashboard link), ingest it directly (tweet / news /
            # image). Checked before command parsing so a pasted link is
            # treated as ingestion, not a tag command. A dashboard incident
            # URL in a reply is NOT treated as content (it's a command target).
            url_m = _URL_RE.search(text)
            if url_m and not _is_dashboard_url(url_m.group(0)):
                _ingest_from_url(chat_id, url_m.group(0), caption=text[:300])
                return

            cmd = _parse_admin_command(text)
            _ev(chat_id, "text_command_received",
                has_target=bool(target_id),
                target=(target_id or "")[:8],
                parsed_keys=list(cmd.keys()) if cmd else [])

            if cmd and target_id:
                updated = _apply_incident_update(target_id, cmd, chat_id)
                if updated:
                    diff = ", ".join(f"{k}={v}" for k, v in cmd.items())
                    _send_message(chat_id,
                        f"✓ Updated: {diff}\n"
                        f"\"{updated.get('title', '')[:80]}\"\n"
                        f"{DASHBOARD_URL}/incidents/{target_id}"
                    )
                else:
                    _send_message(chat_id,
                        f"Update failed — incident {target_id[:8]} not found or DB rejected the change."
                    )
                return
            if cmd and not target_id:
                _send_message(chat_id,
                    "I understood the command but no target incident found.\n"
                    "Reply to a bot message containing the incident link, "
                    "or upload an image first then send the command."
                )
                return
        _send_message(chat_id,
            "Send me one of:\n"
            "• a screenshot of a news article / tweet\n"
            "• a tweet link, news URL, or image URL\n"
            "and I'll extract the incident and add it to the dashboard.")
        return

    _ev(chat_id, "image_detected", photos=len(photos), is_image_doc=is_image_doc)
    # Immediate ack so user knows we received it. Vision-AI takes ~15-30s.
    _send_message(chat_id, "Got it — reading image (~20s)...")
    _ev(chat_id, "ack_sent")

    # Pick the file to download. Document uploads have a single file_id.
    # Photo uploads have 4 size variants — try largest first, fall back
    # to smaller ones if the Telegram CDN errors on the big one (we've
    # seen the CDN repeatedly fail to serve specific file_ids).
    if is_image_doc:
        file_id = document["file_id"]
        image_bytes, dl_err = _download_photo(file_id)
        file_id_used = file_id
    else:
        image_bytes, file_id_used, dl_err = _download_any_photo_variant(photos)
    if not image_bytes:
        fid_preview = (file_id_used or "?")[:30]
        _ev(chat_id, "download_failed", file_id=fid_preview, err=(dl_err or "")[:200])
        _send_message(chat_id,
            f"Couldn't download the image from Telegram's servers.\n"
            f"Error: {(dl_err or 'unknown')[:200]}\n\n"
            f"Try: re-take the screenshot fresh and send it as a NEW message "
            f"(don't forward an old one — old Telegram file_ids sometimes expire)."
        )
        return
    _ev(chat_id, "download_ok", bytes=len(image_bytes), file_id=(file_id_used or "")[:30])

    # Pull a URL from the caption if present (used as source_url)
    source_url = _extract_url_from_caption(caption)

    # OCR-FIRST, TEXT-MODEL extraction (faster + more accurate + avoids
    # the slow/dead Groq VISION models). The healthy fast path is:
    # Google Vision OCR (reads Tamil accurately) -> Groq 70b TEXT model
    # (157ms, reliable) via _extract_incident. We only fall back to the
    # vision model (slow, sometimes dead) if OCR returns nothing — e.g.
    # billing off, or a pure-image meme with no text.
    extraction_path = "ocr_text"
    extracted = None
    _ev(chat_id, "ocr_first_extract_start")
    ocr_text, ocr_err = _ocr_via_vision(image_bytes)
    ocr_len = len((ocr_text or "").strip())
    _ev(chat_id, "ocr_first_done", chars=ocr_len, err=(ocr_err or "")[:90])
    if ocr_len >= 40:
        extracted = _extract_incident(
            ocr_text=ocr_text, caption=caption, source_url=source_url)
        _ev(chat_id, "ocr_text_extract_done", got_result=bool(extracted))

    # Vision-model fallback ONLY if OCR gave us nothing usable.
    if not extracted:
        _ev(chat_id, "vision_fallback_start", reason="ocr_empty" if ocr_len < 40 else "text_extract_failed")
        extracted = _extract_incident_from_image(
            image_bytes=image_bytes, caption=caption, source_url=source_url)
        extraction_path = "vision_fallback"
        _ev(chat_id, "vision_fallback_done", got_result=bool(extracted))

    if not extracted:
        if (ocr_len + len(caption.strip())) < 30:
            _send_message(chat_id,
                f"Couldn't read anything usable from this image.\n"
                f"  OCR: {ocr_len} chars ({ocr_err or 'ok'})\n"
                f"  caption: {len(caption)} chars\n\n"
                f"Tip: paste the tweet/article LINK instead — I read links "
                f"more reliably than dense-Tamil screenshots."
            )
        else:
            _send_message(chat_id,
                "AI extraction failed (providers may be busy). Try again in "
                "a moment, or paste the source link instead.")
        return
    # ADMIN-UPLOAD TRUST OVERRIDE:
    # The AI's relevance gate is calibrated for unsupervised Twitter/RSS
    # ingestion where most content is opinion/spam. For admin Telegram
    # uploads, the admin already filtered by deciding to upload — we
    # respect that judgment. The AI extraction still runs (for category
    # / location / date structuring) but is_relevant=False does NOT block.
    #
    # Edge case: AI couldn't extract a usable title at all.  Bail in
    # that case — there's nothing useful to insert.
    if not extracted.get("is_relevant"):
        _ev(chat_id, "ai_relevance_overridden", ai_reason=extracted.get("reason"))
        # If the AI couldn't even produce a title, salvage via OCR so we
        # never silently drop an admin upload. Fact-check graphics,
        # tweet screenshots, and multi-panel composites often confuse
        # the vision model into saying "no specific incident" — but the
        # underlying text is still there, we just need to extract it
        # mechanically. Stage as pending_review so the admin classifies
        # in the dashboard rather than letting AI hallucinate a category.
        if not (extracted.get("title") or "").strip():
            # Salvage path: try TWO ways to get text out of the image
            #   1. Ask Groq vision LLM to describe it with no relevance
            #      gate (Groq already proved it can READ the image in the
            #      first extraction — it just refused to structure it as
            #      an incident, which is the prompt's fault, not vision's)
            #   2. Fall back to Google Vision OCR if Groq describe fails
            _ev(chat_id, "salvage_describe_start")
            described = _describe_image_via_vision_llm(image_bytes, caption)
            describe_title = (described or {}).get("title", "").strip()
            describe_summary = (described or {}).get("summary", "").strip()
            describe_ocr = (described or {}).get("ocr_text", "").strip()
            _ev(chat_id, "salvage_describe_done",
                got_title=bool(describe_title),
                title_len=len(describe_title),
                ocr_chars=len(describe_ocr))

            ocr_text, ocr_err, ocr_clean = "", None, ""
            if not describe_title:
                # Vision-describe failed — try Google Vision OCR
                _ev(chat_id, "salvage_ocr_start")
                ocr_text, ocr_err = _ocr_via_vision(image_bytes)
                ocr_clean = re.sub(r"\s+", " ", ocr_text).strip()
                _ev(chat_id, "salvage_ocr_done",
                    chars=len(ocr_clean), err=ocr_err)

            if describe_title:
                # Vision-describe returns a FULLY classified incident now
                # (category, severity, location, date, credit_steal). Use
                # those values — they're better than the failed first
                # extraction's nulls. Only fall back to 'unclassified'/
                # pending_review if vision-describe also failed to provide
                # a category.
                describe_cat       = ((described or {}).get("category") or "").strip()
                describe_severity  = (described or {}).get("severity")
                describe_location  = ((described or {}).get("location") or "").strip()
                describe_date      = ((described or {}).get("incident_date") or "").strip()
                describe_credit    = bool((described or {}).get("is_credit_steal"))

                extracted["title"]   = describe_title[:200]
                extracted["summary"] = (describe_summary or describe_ocr or describe_title)[:1500]
                extracted["_admin_override"]   = True
                extracted["_vision_described"] = True
                if describe_ocr:
                    extracted["_raw_ocr"] = describe_ocr[:4000]

                if describe_cat and describe_cat != "other":
                    # Full classification — auto-approve, NOT pending review.
                    # Admin can still retag via "tag under X" if AI got it
                    # wrong, but the default is to trust the salvage pass
                    # since admin already vouched by uploading.
                    extracted["category"]         = describe_cat
                    extracted["severity"]         = describe_severity
                    extracted["location"]         = describe_location or extracted.get("location")
                    extracted["incident_date"]    = describe_date or extracted.get("incident_date")
                    extracted["is_credit_steal"]  = describe_credit
                    extracted["confidence"]       = 0.7  # salvage path is lower-confidence
                    # NOTE: NOT setting _pending_review — this lands as approved
                else:
                    # Vision-describe returned a title but no good category.
                    # Stage as pending so admin classifies manually.
                    extracted["category"] = "other"
                    extracted["_pending_review"] = True
            elif len(ocr_clean) >= 20:
                first_line = next(
                    (ln.strip() for ln in ocr_text.splitlines()
                     if len(ln.strip()) >= 15),
                    ocr_clean[:120]
                )
                extracted["title"]   = first_line[:120]
                extracted["summary"] = ocr_clean[:1500]
                extracted["category"] = extracted.get("category") or "unclassified"
                extracted["_admin_override"]  = True
                extracted["_ocr_salvaged"]    = True
                extracted["_pending_review"]  = True
            else:
                # Both salvage paths failed — surface ALL reasons to admin
                reason = (extracted.get("reason") or "AI couldn't structure the image")[:200]
                _send_message(chat_id,
                    f"Couldn't extract anything from this image.\n"
                    f"  AI extract: {reason}\n"
                    f"  Vision describe: {'ok' if describe_title else 'no title returned'}\n"
                    f"  OCR: {len(ocr_clean)} chars ({ocr_err or 'ok'})\n\n"
                    f"Add a caption describing what's in it and re-upload."
                )
                return
        else:
            # Otherwise: proceed. The admin uploaded it, the admin vouches.
            extracted["_admin_override"] = True

    # CAPTION-TAG OVERRIDE: if the admin put a tag command in the image
    # CAPTION (e.g. "tag under credit stealing"), apply it now — before
    # insert. This avoids the timing race where a separate "tag under X"
    # message arrives BEFORE the incident exists (so it has no target).
    # Tagging during upload is the natural flow and always lands.
    if caption:
        cap_cmd = _parse_admin_command(caption)
        if cap_cmd:
            _ev(chat_id, "caption_tag_applied", keys=list(cap_cmd.keys()))
            for k, v in cap_cmd.items():
                # Don't let a caption command flip status to rejected on upload
                if k == "status" and v == "rejected":
                    continue
                extracted[k] = v

    # Hard date gate — same as the AI pipeline elsewhere
    from datetime import date as _date
    inc_date_s = extracted.get("incident_date")
    _ev(chat_id, "date_gate_check", date=inc_date_s)
    if inc_date_s:
        try:
            if _date.fromisoformat(inc_date_s) < _date(2026, 5, 11):
                _ev(chat_id, "date_gate_rejected", date=inc_date_s)
                _send_message(chat_id,
                    f"Not added: incident is pre-May-11 2026 "
                    f"({inc_date_s}). The tracker only covers the TVK admin era."
                )
                return
        except Exception as e:
            _ev(chat_id, "date_gate_parse_error", err=str(e)[:80])

    # Fuzzy dedup against recent incidents
    _ev(chat_id, "dedup_start")
    try:
        duplicate = _find_duplicate(extracted)
    except Exception as e:
        _ev(chat_id, "dedup_error", err=str(e)[:140])
        duplicate = None
    _ev(chat_id, "dedup_done", found=bool(duplicate))
    if duplicate:
        _send_message(chat_id,
            f"ℹ️ Already on dashboard ({int(duplicate['_match_ratio']*100)}% match):\n"
            f"\"{duplicate['title']}\"\n"
            f"{DASHBOARD_URL}/incidents/{duplicate['id']}\n\n"
            f"You can ignore this upload — it's already captured."
        )
        return

    # Insert as admin_verified (you uploaded it, you vouch for it).
    # Exception: OCR-salvaged uploads land as pending_review so the
    # admin can classify them via the dashboard — these are the ones
    # the AI couldn't structure on its own.
    is_pending = bool(extracted.get("_pending_review"))
    db = get_db()
    payload = {
        "title":              (extracted.get("title") or "Untitled incident")[:200],
        "summary":            (extracted.get("summary") or extracted.get("title") or "")[:2000],
        "category":           extracted.get("category", "other"),
        "incident_date":      extracted.get("incident_date") or date.today().isoformat(),
        "location":           extracted.get("location"),
        "severity":           _clamp_severity(extracted.get("severity")),
        "ai_confidence":      extracted.get("confidence", 0.85),
        "status":             "pending_review" if is_pending else "approved",
        "verification_status": "pending_verification" if is_pending else "admin_verified",
        # If caption had a URL we use it as the source. Otherwise the
        # source IS the Telegram upload + admin trust.
        "source_urls":        [source_url] if source_url else [
            f"telegram://admin-upload/chat-{chat_id}/{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
        ],
        "source_count":       1,
        "ai_raw":             {
            "telegram_source":   True,
            "caption":           caption,
            "extraction_path":   extraction_path,  # 'vision' or 'ocr_fallback'
            "from_chat_id":      chat_id,
            "ingested_at":       datetime.now(timezone.utc).isoformat(),
            "tags_extra":        (extracted.get("tags_extra") or []),
            # Whether the AI said is_relevant=False but admin override
            # let it through. Useful for retroactive QA.
            "admin_override":    bool(extracted.get("_admin_override")),
            "ocr_salvaged":      bool(extracted.get("_ocr_salvaged")),
            "pending_review":    is_pending,
            "ai_reason":         extracted.get("reason"),
        },
        "is_credit_steal":    extracted.get("is_credit_steal", False),
        "press_sentiment":    extracted.get("press_sentiment"),
        "image_urls":         [],
        "member_ids":         [],
        # event_signature lets future Telegram uploads dedup against
        # this row even if the AI words the title differently next time
        "event_signature":    _event_sig(
            extracted.get("category", ""),
            extracted.get("location"),
            extracted.get("incident_date"),
        ),
    }
    _ev(chat_id, "insert_attempt",
        title=payload["title"][:60],
        category=payload["category"],
        date=payload["incident_date"])
    try:
        res = db.table("incidents").insert(payload).execute()
        if not res.data:
            _ev(chat_id, "insert_no_data")
            _send_message(chat_id, "Insert failed (no row returned). Check backend logs.")
            return
        new_id = res.data[0]["id"]
        _ev(chat_id, "insert_ok", id=new_id[:8])
        # Remember for follow-up text commands ("tag under credit stealing", etc.)
        _LAST_INCIDENT_BY_CHAT[chat_id] = new_id
        # Audit
        try:
            db.table("incident_audit").insert({
                "incident_id": new_id,
                "action":      "created",
                "actor":       "telegram_bot",
                "to_value":    "admin_verified",
                "reason":      f"Telegram upload from chat {chat_id}. Caption: {caption[:200]}",
            }).execute()
        except Exception:
            pass
        if is_pending:
            _send_message(chat_id,
                f"STAGED FOR REVIEW (AI couldn't auto-classify)\n"
                f"Title: {payload['title']}\n"
                f"Pulled via OCR. Classify it at:\n"
                f"{DASHBOARD_URL}/admin/incidents/{new_id}"
            )
        else:
            _send_message(chat_id,
                f"NEW INCIDENT ADDED\n"
                f"Title: {extracted['title']}\n"
                f"Category: {extracted.get('category', 'other')} · severity {payload['severity']}\n"
                f"{DASHBOARD_URL}/incidents/{new_id}"
            )
    except Exception as e:
        _ev(chat_id, "insert_exception", err=f"{type(e).__name__}: {str(e)[:140]}")
        logger.error("Telegram bot insert failed: %s", e)
        _send_message(chat_id, f"Insert error: {str(e)[:200]}")
