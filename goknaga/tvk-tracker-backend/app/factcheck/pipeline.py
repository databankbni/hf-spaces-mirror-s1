"""Fact-check copilot pipeline (Phase 0 — internal admin tool).

Design contract: this is a COPILOT, not an oracle. It does the legwork —
extracts the checkable claim, matches it against our known-debunk corpus,
checks the DMK archive for credit-steal/first-ever angles, searches press
coverage, and drafts a verdict WITH citations and a confidence level.
A human confirms before anything is treated as a verdict. The 'unverifiable'
and 'needs_context' verdicts are first-class outcomes, not failures — they
are what stop the model from being forced into a confident wrong answer.

Pipeline stages (each ~1 LLM call max; a full run is ~4 LLM calls + a few
HTTP fetches — safely inside what the free-tier Space can do in one
BackgroundTask; see the 2026-06-11 lesson about NOT batching 80+ calls):

  1. ingest      — URL? fetch + extract readable text (browser-UA fallback,
                   X/Twitter via the public syndication endpoint).
  2. extract     — LLM: pull the 1-3 main CHECKABLE claims.
  3. debunk match— compare against propaganda_events + fake_news incidents
                   (keyword overlap shortlist → LLM confirm). A hit here is
                   the cheapest, highest-trust verdict we can give.
  4. dmk match   — if the claim smells like 'first ever / launched / new
                   scheme', check dmk_schemes for a DMK-era original.
  5. evidence    — Google News search per claim, press-tier outlets only
                   (reuses corroboration's outlet identification).
  6. synthesize  — LLM: verdict ∈ {true, partly_true, misleading, false,
                   unverifiable, needs_context} + confidence + rationale +
                   what_would_change + per-source stance.

Scope guard: this tool is for TN-politics/TVK-governance claims. Anything
else gets 'needs_context' with a scope note rather than a fake verdict.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Optional

from app.database import get_db

logger = logging.getLogger(__name__)

UA_BOT = "Mozilla/5.0 (compatible; TVKTracker-FactCheck/1.0)"
UA_BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
GNEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"


# --------------------------------------------------------------------------
# Stage 1 — ingest (URL fetch + text extraction)
# --------------------------------------------------------------------------

def _strip_html(text: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&quot;", '"').replace("&#39;", "'")
                .replace("&lt;", "<").replace("&gt;", ">"))
    return re.sub(r"\s+", " ", text).strip()


def _fetch_url_text(url: str) -> Optional[str]:
    """Fetch a URL and return readable text. Handles X/Twitter via the
    public syndication endpoint (x.com blocks normal fetchers)."""
    tw = re.match(r"https?://(?:x|twitter)\.com/\w+/status/(\d+)", url)
    if tw:
        syn = f"https://cdn.syndication.twimg.com/tweet-result?id={tw.group(1)}&token=a"
        try:
            req = urllib.request.Request(syn, headers={"User-Agent": UA_BROWSER})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode("utf-8", errors="replace"))
            parts = [data.get("text") or ""]
            qt = data.get("quoted_tweet") or {}
            if qt.get("text"):
                parts.append(f"[quoted tweet] {qt['text']}")
            user = (data.get("user") or {}).get("screen_name")
            if user:
                parts.append(f"[posted by @{user}]")
            return " ".join(p for p in parts if p)[:6000] or None
        except Exception as e:
            logger.warning("factcheck: tweet syndication fetch failed: %s", e)
            return None
    for ua in (UA_BOT, UA_BROWSER):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua})
            with urllib.request.urlopen(req, timeout=25) as r:
                html = r.read(800_000).decode("utf-8", errors="replace")
            text = _strip_html(html)
            return text[:6000] if text else None
        except Exception:
            continue
    return None


_IMAGE_OCR_PROMPT = (
    "This is a social-media card, poster, or screenshot about Tamil Nadu "
    "politics (often a 'breaking news' graphic). Do two things:\n"
    "1. Transcribe ALL visible text — English AND Tamil — including small print, "
    "handles, and captions.\n"
    "2. Then write, in ONE clear English sentence prefixed with 'CLAIM: ', the "
    "single main factual claim the image is making.\n"
    "Output the CLAIM line first, then the full transcription. Do not judge "
    "truth — just transcribe and state the claim."
)


def _ocr_image(data_url: str) -> Optional[str]:
    """Read the text + main claim from an uploaded image via Gemini Vision
    (free tier, vision-capable). `data_url` is a base64 data: URL. Returns the
    CLAIM line + transcription, or None."""
    from app.config import settings
    gem = getattr(settings, "gemini_api_key", None)
    if not gem:
        logger.warning("factcheck image OCR: no GEMINI_API_KEY configured")
        return None
    try:
        from openai import OpenAI
        client = OpenAI(
            timeout=45, max_retries=1, api_key=gem,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        resp = client.chat.completions.create(
            model="gemini-2.0-flash",
            max_tokens=600,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": _IMAGE_OCR_PROMPT},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]}],
        )
        out = (resp.choices[0].message.content or "").strip()
        return out or None
    except Exception as e:
        logger.warning("factcheck image OCR failed: %s", e)
        return None


# --------------------------------------------------------------------------
# Stage 2 — claim extraction
# --------------------------------------------------------------------------

_EXTRACT_PROMPT = """You extract CHECKABLE factual claims for a Tamil Nadu politics
fact-checking tool (TVK government in office since 2026-05-11; previous govt: DMK
2021-2026). Content may be in English or Tamil.

CONTENT:
{content}

Rules:
- A checkable claim asserts something verifiable: an event happened, a number,
  a "first ever", an attribution ("X said/did Y"), a scheme/policy fact.
- Opinions, predictions, and pure insults are NOT checkable.
- If the content is outside Tamil Nadu politics/governance, set in_scope=false.
- Max 3 claims, most significant first. Normalize each into one clear English sentence.

Output ONLY this JSON:
{{"in_scope": true/false, "claims": [{{"text": "...", "checkable": true/false}}],
  "language": "en"/"ta"/"mixed"}}"""


# --------------------------------------------------------------------------
# Stage 3 — known-debunk corpus match
# --------------------------------------------------------------------------

_STOP = {"the", "a", "an", "of", "in", "on", "at", "to", "and", "or", "for",
         "with", "is", "was", "are", "were", "has", "have", "tamil", "nadu",
         "tvk", "government", "govt", "minister", "chief"}


def _keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) > 3 and w not in _STOP}


def _match_debunk_corpus(db, claim: str) -> list[dict]:
    """Keyword-overlap shortlist against propaganda_events + fake_news
    incidents. Cheap (no LLM) — the synthesis step weighs the matches."""
    kw = _keywords(claim)
    if not kw:
        return []
    matches: list[dict] = []
    try:
        props = (db.table("propaganda_events")
                 .select("id, title, status, debunk_url, debunk_source, propaganda_type")
                 .execute().data or [])
        for p in props:
            overlap = kw & _keywords(p.get("title") or "")
            if len(overlap) >= 2:
                matches.append({
                    "kind": "propaganda_event", "id": p["id"],
                    "title": p.get("title"), "status": p.get("status"),
                    "debunk_url": p.get("debunk_url"),
                    "debunk_source": p.get("debunk_source"),
                    "overlap": sorted(overlap),
                })
    except Exception:
        pass
    try:
        fakes = (db.table("incidents")
                 .select("id, title, summary, verification_status, source_urls")
                 .eq("category", "fake_news").eq("status", "approved")
                 .execute().data or [])
        for f in fakes:
            overlap = kw & _keywords((f.get("title") or "") + " " + (f.get("summary") or ""))
            if len(overlap) >= 2:
                matches.append({
                    "kind": "fake_news_incident", "id": f["id"],
                    "title": f.get("title"),
                    "verification_status": f.get("verification_status"),
                    "url": (f.get("source_urls") or [None])[0],
                    "overlap": sorted(overlap),
                })
    except Exception:
        pass
    return matches[:5]


# --------------------------------------------------------------------------
# Stage 4 — DMK archive match (credit-steal / first-ever angle)
# --------------------------------------------------------------------------

_FIRST_EVER_RE = re.compile(
    r"first[- ]ever|first time|never before|"
    r"first\b[\w\s]{0,25}\b(country|india|state|nation|world)|"  # 'first state in the country'
    r"launch|introduc|inaugurat|new scheme|unveil", re.I)


def _match_dmk_archive(db, claim: str) -> list[dict]:
    if not _FIRST_EVER_RE.search(claim):
        return []
    kw = _keywords(claim)
    out: list[dict] = []
    try:
        schemes = (db.table("dmk_schemes")
                   .select("id, name, aliases, launch_date, description")
                   .execute().data or [])
        for s in schemes:
            hay = (s.get("name") or "") + " " + " ".join(s.get("aliases") or []) \
                  + " " + (s.get("description") or "")
            overlap = kw & _keywords(hay)
            if len(overlap) >= 2:
                out.append({
                    "scheme": s.get("name"), "launch_date": s.get("launch_date"),
                    "overlap": sorted(overlap),
                })
    except Exception:
        pass
    return out[:3]


# --------------------------------------------------------------------------
# Stage 5 — press evidence search
# --------------------------------------------------------------------------

def _gnews_evidence(claim: str, *, max_items: int = 6) -> list[dict]:
    """Google News search for the claim; press outlets identified via the
    corroboration module's registry so tiers are consistent site-wide."""
    from app.ingestion.corroboration import _identify_outlet  # reuse registry
    kw = list(_keywords(claim))[:7]
    if not kw:
        return []
    q = urllib.parse.quote(" ".join(kw))
    try:
        req = urllib.request.Request(GNEWS_RSS.format(query=q),
                                     headers={"User-Agent": UA_BOT})
        with urllib.request.urlopen(req, timeout=20) as r:
            xml_text = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning("factcheck gnews fetch failed: %s", e)
        return []
    out: list[dict] = []
    try:
        root = ET.fromstring(xml_text)
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            src = (it.findtext("source") or "").strip()
            pub = (it.findtext("pubDate") or "").strip()
            if not (title and link):
                continue
            outlet, tier = _identify_outlet(link, src)
            out.append({"url": link, "headline": title, "outlet": outlet,
                        "tier": tier, "date": pub})
            if len(out) >= max_items:
                break
    except ET.ParseError:
        pass
    return out


# --------------------------------------------------------------------------
# Stage 6 — verdict synthesis
# --------------------------------------------------------------------------

_SYNTH_PROMPT = """You draft a fact-check verdict for a HUMAN REVIEWER (this draft is
never published without human confirmation). Today is {today}. Context: Tamil Nadu;
TVK government in office since 2026-05-11; previous DMK government 2021-2026.

CLAIM: "{claim}"

KNOWN-DEBUNK MATCHES (our own verified corpus — strongest signal when relevant):
{debunks}

DMK-ARCHIVE MATCHES (for 'first ever'/'new scheme' claims — a match means a
DMK-era original exists, suggesting the claim over-credits TVK):
{dmk}

PRESS COVERAGE FOUND (Google News; tier = source trust level):
{evidence}

Rules — this tool's credibility depends on you following them exactly:
- Verdict ladder: "true", "partly_true", "misleading", "false", "unverifiable",
  "needs_context". Use "unverifiable" when evidence is thin — NEVER force a
  confident verdict from weak evidence. Use "needs_context" when literally true
  but framed deceptively.
- Headlines alone are weak evidence; weigh outlet count and tier. 2+ established
  outlets supporting = strong. Zero relevant coverage of a dramatic claim is
  itself a signal (real dramatic events get covered).
- A known-debunk match with status 'debunked' is near-decisive for "false".
- Do not import outside knowledge about events after your training data; reason
  from the provided evidence. You MAY use general knowledge for stable facts
  (geography, law, institutional structure).
- confidence: 0.0-1.0, honest. Below 0.6 → prefer "unverifiable".
- stance per evidence item: "supports" | "contradicts" | "related" | "irrelevant".

Output ONLY this JSON:
{{"verdict": "...", "confidence": 0.0,
  "rationale": "<one tight paragraph for the reviewer>",
  "what_would_change": "<what evidence would flip this>",
  "evidence_stances": [{{"url": "...", "stance": "..."}}]}}"""


def _json_from(raw: Optional[str]) -> Optional[dict]:
    """Pull a JSON object out of an LLM response. Tolerates ```json fences,
    preamble text, and a trailing example by trying the greedy span first
    then the first balanced object."""
    if not raw:
        return None
    txt = re.sub(r"```(?:json)?", "", raw).strip()
    # Try the greedy outermost {...} first, then a non-greedy first object.
    for pat in (r"\{.*\}", r"\{.*?\}"):
        m = re.search(pat, txt, flags=re.S)
        if not m:
            continue
        try:
            return json.loads(m.group(0))
        except Exception:
            continue
    return None


def run_factcheck(factcheck_id: str) -> dict[str, Any]:
    """Execute the full pipeline for one queued factchecks row and write the
    draft back. Designed to run inside ONE BackgroundTask (~4 LLM calls)."""
    from app.ingestion.ai_processor import llm_call_with_fallback
    db = get_db()

    def _save(fields: dict) -> None:
        fields["updated_at"] = datetime.now(timezone.utc).isoformat()
        db.table("factchecks").update(fields).eq("id", factcheck_id).execute()

    row = (db.table("factchecks").select("*").eq("id", factcheck_id)
           .execute().data or [None])[0]
    if not row:
        return {"error": "factcheck row not found"}
    _save({"status": "running"})

    try:
        # 1. ingest
        content = row["input_content"]
        fetched = None
        if row["input_type"] == "url":
            fetched = _fetch_url_text(content)
            if not fetched:
                _save({"status": "error",
                       "error_detail": "Could not fetch/extract the URL content."})
                return {"error": "fetch failed"}
            _save({"fetched_excerpt": fetched[:2000]})
            content = fetched
        elif row["input_type"] == "image":
            fetched = _ocr_image(content)
            if not fetched:
                _save({"status": "error",
                       "error_detail": "Could not read the image. The AI vision "
                       "quota may be exhausted (resets 5:30 AM IST), or the image "
                       "had no legible text."})
                return {"error": "ocr failed"}
            # Replace the bulky base64 payload with the OCR'd text so the row
            # stays lean and the rest of the pipeline runs on the transcription.
            _save({"fetched_excerpt": fetched[:2000], "input_content": "[image upload]"})
            content = fetched

        # 2. extract claims
        raw_ext = llm_call_with_fallback(
            [{"role": "user", "content": _EXTRACT_PROMPT.format(content=content[:5000])}],
            max_tokens=400,
        )
        ext = _json_from(raw_ext)
        if not ext or not ext.get("claims"):
            # Resilience: a pasted TEXT claim IS the claim — no extraction
            # needed. Fall back to checking it verbatim so a flaky/exhausted
            # free-tier LLM on the (optional) extraction step doesn't sink the
            # whole check. URLs genuinely need extraction, so they still error
            # — but with the raw response captured for diagnosis.
            if row["input_type"] == "text" and len(content.strip()) >= 12:
                claims = [{"text": content.strip()[:500], "checkable": True}]
                main_claim = content.strip()[:500]
            else:
                detail = ("Claim extraction failed. "
                          + ("LLM returned no usable response (all providers "
                             "exhausted/rate-limited — check /diagnostics/ai-probe)."
                             if not raw_ext
                             else f"Unparseable response: {raw_ext[:240]}"))
                _save({"status": "error", "error_detail": detail})
                return {"error": "no claims"}
        else:
            claims = ext["claims"]
            main_claim = next((c["text"] for c in claims if c.get("checkable")),
                              claims[0]["text"])
        if ext is not None and not ext.get("in_scope", True):
            _save({"status": "draft", "claims": claims, "claim_text": main_claim,
                   "verdict": "needs_context", "confidence": 0.0,
                   "rationale": "Out of scope: this tool checks Tamil Nadu "
                                "politics/governance claims only.",
                   "what_would_change": "n/a (out of scope)",
                   "evidence": []})
            return {"verdict": "needs_context", "out_of_scope": True}
        _save({"claims": claims, "claim_text": main_claim})

        # 3 + 4. corpus matches (no LLM cost)
        debunks = _match_debunk_corpus(db, main_claim)
        dmk = _match_dmk_archive(db, main_claim)

        # 5. press evidence
        evidence = _gnews_evidence(main_claim)

        # 6. synthesize
        raw_synth = llm_call_with_fallback(
            [{"role": "user", "content": _SYNTH_PROMPT.format(
                today=datetime.now(timezone.utc).date().isoformat(),
                claim=main_claim,
                debunks=json.dumps(debunks, ensure_ascii=False) if debunks else "none",
                dmk=json.dumps(dmk, ensure_ascii=False) if dmk else "none",
                evidence=json.dumps(evidence, ensure_ascii=False) if evidence else "none",
            )}],
            max_tokens=600,
        )
        synth = _json_from(raw_synth)
        if not synth or synth.get("verdict") not in (
                "true", "partly_true", "misleading", "false",
                "unverifiable", "needs_context"):
            detail = ("Verdict synthesis failed. "
                      + ("LLM returned no usable response (all providers "
                         "exhausted/rate-limited — check /diagnostics/ai-probe)."
                         if not raw_synth
                         else f"Invalid/unparseable verdict: {raw_synth[:240]}"))
            # Keep the claim + evidence we already gathered so the reviewer
            # can still judge manually even when synthesis couldn't run.
            _save({"status": "error", "error_detail": detail,
                   "evidence": evidence, "debunk_match": debunks or None,
                   "dmk_match": dmk or None})
            return {"error": "synthesis failed"}

        # attach stances back onto evidence (guard non-dict/null elements —
        # the LLM occasionally emits a null or a bare string in this list)
        stances = {}
        for s in (synth.get("evidence_stances") or []):
            if isinstance(s, dict) and s.get("url"):
                stances[s["url"]] = s.get("stance")
        for ev in evidence:
            ev["stance"] = stances.get(ev["url"], "related")

        conf = float(synth.get("confidence") or 0)
        _save({
            "status": "draft",
            "verdict": synth["verdict"],
            "confidence": conf,
            "rationale": (synth.get("rationale") or "")[:2000],
            "what_would_change": (synth.get("what_would_change") or "")[:800],
            "evidence": evidence,
            "debunk_match": debunks or None,
            "dmk_match": dmk or None,
        })
        return {"verdict": synth["verdict"], "confidence": conf,
                "evidence_count": len(evidence)}

    except Exception as e:
        logger.exception("factcheck pipeline failed for %s", factcheck_id)
        try:
            _save({"status": "error", "error_detail": f"{type(e).__name__}: {str(e)[:200]}"})
        except Exception:
            pass
        return {"error": str(e)[:200]}
