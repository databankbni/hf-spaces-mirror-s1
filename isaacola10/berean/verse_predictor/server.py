"""FastAPI service: speech/text -> Bible verse, plus chapter view and a
Claude-powered natural-language Q&A grounded in the retrieved verses.

Models load in a background thread at startup so the server is reachable
immediately; endpoints return 503 until the index + ASR model are ready.

Run:
    uvicorn server:app --reload --port 8000
"""
import io
import json
import os
import re
import threading
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import adminauth
import billing
import clerkauth
import matcher as matcher_mod
import store
from corpus import version_info
from matcher import VerseMatcher
from reference import format_reference, parse_reference
from transcribe import DECODE_OPTS, DEFAULT_MODEL, get_model

# Below this top score we report "no confident match" (still return guesses).
CONFIDENCE_MIN = 0.45
# Claude models for the Q&A feature. Primary, then a cheaper fallback used on
# overload / rate-limit (override with env vars).
ANSWER_MODEL = os.environ.get("ANSWER_MODEL", "claude-opus-4-8")
ANSWER_MODEL_FALLBACK = os.environ.get("ANSWER_MODEL_FALLBACK", "claude-haiku-4-5")
MAX_QUESTION_LEN = 500
ANSWER_CACHE_SIZE = 256

LANGUAGE_NAMES = {"en": "English", "es": "Español"}

state: dict = {"ready": False, "error": None}

# Tiny LRU cache of Q&A answers keyed by (question, version).
_answer_cache: "OrderedDict[str, str]" = OrderedDict()


class TextQuery(BaseModel):
    text: str
    top_k: int = 5
    version: str = "all"
    scope: str = "all"
    mode: str = "type"


class AskQuery(BaseModel):
    question: str
    version: str = "all"


class LoginBody(BaseModel):
    password: str


class TopicBody(BaseModel):
    label: str
    emoji: str = ""
    query: str


class PreviewBody(BaseModel):
    text: str
    version: str = "all"
    scope: str = "all"
    weights: dict | None = None


# -- admin auth dependency ----------------------------------------------------
def require_admin(authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ").strip()
    if not adminauth.verify(token):
        raise HTTPException(status_code=401, detail="Admin auth required")
    return True


# -- user auth dependencies (Clerk session token) ------------------------------
def optional_user(authorization: str = Header(default="")) -> dict | None:
    """Resolve the signed-in user from a Clerk session token, if present."""
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        return None
    claims = clerkauth.verify_token(token)
    if not claims:
        return None
    info = clerkauth.user_from_claims(claims)
    if not info["id"]:
        return None
    try:
        return store.upsert_user(info["id"], info["email"], info["name"])
    except Exception:  # noqa: BLE001 - auth shouldn't fail on a DB hiccup
        return {"id": info["id"], "email": info["email"], "plan": "free"}


def require_user(user: dict | None = Depends(optional_user)) -> dict:
    if not user:
        raise HTTPException(status_code=401, detail="Sign in required.")
    return user


def require_speaker(user: dict = Depends(require_user)) -> dict:
    if user.get("plan") != "speaker":
        raise HTTPException(status_code=402, detail="Sermon Studio requires the Speaker plan.")
    return user


def _load_models():
    try:
        store.init_db()
        matcher_mod.set_weights(store.get_weights())  # apply saved search weights
        state["matcher"] = VerseMatcher()
        state["asr"] = get_model(DEFAULT_MODEL)
        state["ready"] = True
        print("Models ready.")
    except Exception as e:  # noqa: BLE001
        state["error"] = str(e)
        print(f"Model load failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Don't block startup on the heavy model load — do it in the background.
    threading.Thread(target=_load_models, daemon=True).start()
    yield
    state.clear()


app = FastAPI(title="Verseo API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_ready():
    if state["error"]:
        raise HTTPException(status_code=500, detail=f"Model load failed: {state['error']}")
    if not state["ready"]:
        raise HTTPException(status_code=503, detail="Models are still loading")


def require_enabled():
    """Global kill switch — admin can disable all actions app-wide."""
    if store.get_flags().get("disabled", "0") == "1":
        raise HTTPException(status_code=503, detail="Verseo is temporarily unavailable.")


# Map a feature to the column on test_keys that gates it.
_FEATURE_COL = {"speak": "speak", "type": "type_", "ask": "ask", "listen": "listen"}


def require_test_access(feature: str, x_test_key: str = Header(default="")):
    """In test mode, the named feature requires a valid key with that feature on.
    Outside test mode this is a no-op."""
    flags = store.get_flags()
    if flags.get("test_mode", "0") != "1":
        return  # public mode: always allowed
    key = store.get_test_key(x_test_key)
    if not key:
        raise HTTPException(status_code=401, detail="A valid test key is required.")
    col = _FEATURE_COL.get(feature)
    if col and not key.get(col):
        raise HTTPException(
            status_code=403,
            detail=f"Your test key does not have the '{feature}' feature enabled.",
        )


def confidence_label(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.55:
        return "medium"
    return "low"


@app.get("/api/health")
def health():
    return {
        "status": "ok" if state["ready"] else ("error" if state["error"] else "loading"),
        "ready": state["ready"],
        "error": state["error"],
    }


@app.get("/api/versions")
def versions():
    info = version_info()
    langs = {v["language"] for v in info}
    return {
        "versions": [
            {"code": v["code"], "name": v["name"], "language": v["language"]}
            for v in info
        ],
        "languages": [
            {"code": c, "name": LANGUAGE_NAMES.get(c, c)} for c in sorted(langs)
        ],
    }


def _with_names(translations: list[dict]) -> list[dict]:
    return [
        {
            "version": t["version"],
            "language": t["language"],
            "languageName": LANGUAGE_NAMES.get(t["language"], t["language"]),
            "ref": t["ref"],
            "text": t["text"],
        }
        for t in translations
    ]


def _book_chapter_verse(key: str):
    book_no, chapter, verse = (int(x) for x in key.split(":"))
    return book_no, chapter, verse


def search(query: str, top_k: int, version: str = "all", scope: str = "all",
           mode: str = "type", lang: str = "") -> dict:
    """Hybrid retrieval across translations, grouped by verse."""
    query = (query or "").strip()
    if not query:
        return {"transcript": "", "results": [], "confident": False, "topScore": 0.0}

    top_k = max(1, min(top_k, 10))
    matches = state["matcher"].predict(query, top_k=top_k, version=version, scope=scope)

    results = []
    for i, r in enumerate(matches, start=1):
        book_no, chapter, verse = _book_chapter_verse(r["key"])
        results.append(
            {
                "rank": i,
                "ref": r["ref"],
                "book_no": book_no,
                "chapter": chapter,
                "verse": verse,
                "version": r["version"],
                "language": r["language"],
                "languageName": LANGUAGE_NAMES.get(r["language"], r["language"]),
                "text": r["text"],
                "score": round(r["score"], 4),
                "relevance": round(r["score"] * 100),
                "confidence": confidence_label(r["score"]),
                "exact": r["exact"],
                "translations": _with_names(r["translations"]),
            }
        )

    top_score = results[0]["score"] if results else 0.0
    confident = bool(results) and (results[0]["exact"] or top_score >= CONFIDENCE_MIN)
    store.log_event(
        "search", mode, query, results[0]["ref"] if results else "",
        confident, version, scope, lang,
    )
    return {"transcript": query, "results": results, "confident": confident, "topScore": top_score}


@app.post("/api/predict")
async def predict(
    audio: UploadFile = File(...),
    top_k: int = 5,
    version: str = "all",
    lang: str = "auto",
    scope: str = "all",
    x_test_key: str = Header(default=""),
):
    """Speech path: transcribe the uploaded audio, then search."""
    require_ready()
    require_enabled()
    require_test_access("speak", x_test_key)
    data = await audio.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty audio upload")

    segments, info = state["asr"].transcribe(
        io.BytesIO(data), language=(None if lang == "auto" else lang), **DECODE_OPTS
    )
    transcript = " ".join(seg.text.strip() for seg in segments).strip()
    detected = getattr(info, "language", "") or ""
    return search(transcript, top_k, version, scope, mode="speak", lang=detected)


@app.post("/api/search")
def search_text(query: TextQuery, x_test_key: str = Header(default="")):
    """Text path: search directly on the typed query (no ASR)."""
    require_ready()
    require_enabled()
    require_test_access("type", x_test_key)
    return search(query.text, query.top_k, query.version, query.scope, mode=query.mode)


# Cue phrases that signal the speaker is REFERENCING scripture. Each pattern
# captures the *sub-phrase* that follows (a book name, quote, etc.) so we can
# isolate the reference from surrounding conversation.
_CUE_PATTERNS = [
    # "in the book of Romans chapter 8 verse 28" — capture what follows.
    re.compile(r"\b(?:in|from|according to)\s+(?:the\s+)?book\s+of\s+(.+)$", re.I),
    re.compile(r"\bbook\s+of\s+(.+)$", re.I),
    # "the Bible says (in|that) …", "scripture says …"
    re.compile(r"\b(?:the\s+)?(?:bible|scripture|scriptures|word\s+of\s+god)\s+says?\b(?:\s+in)?\s*(.+)$", re.I),
    # "as it is written in …" / "it says in …"
    re.compile(r"\b(?:as\s+)?it\s+(?:is\s+written|says)\b(?:\s+in)?\s*(.+)$", re.I),
    # "in [book] chapter …"
    re.compile(r"\bin\s+([1-3]?\s?[a-z]+(?:\s+[a-z]+)?\s+chapter\s+\d+.*)$", re.I),
    # "Jesus said …" / "the Lord said …" / "Paul wrote …" — the reference (if any)
    # will follow; we still try to parse the tail.
    re.compile(r"\b(?:jesus|christ|the\s+lord|god|paul|moses|david|peter|isaiah)\s+"
               r"(?:said|says|wrote|writes|prayed|declared|answered)\b[^.]*?(.+)$", re.I),
]

# Softer cue words — just a signal to lower the semantic-match threshold.
_CUES = (
    "scripture", "scriptures", "bible", "verse", "chapter", "gospel",
    "psalm", "psalms", "proverb", "proverbs", "book of", "it is written",
    "word of god", "the lord said", "jesus said", "amen",
)
LISTEN_THRESHOLD = 0.60       # strong semantic match required to surface
LISTEN_CUE_THRESHOLD = 0.50   # relaxed when a scripture cue is present


def _extract_reference_from_cue(text: str) -> tuple[int, int, int | None] | None:
    """Try the cue patterns and parse each captured tail as a reference."""
    for pat in _CUE_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        tail = m.group(1).strip(" .,;:—-")
        ref = parse_reference(tail)
        if ref:
            return ref
    return None


class ListenBody(BaseModel):
    text: str
    version: str = "all"
    ref_style: str = "colon"  # "colon" -> "Matthew 5:2", "v" -> "Matthew 5v2"


@app.post("/api/listen")
def listen(body: ListenBody, x_test_key: str = Header(default="")):
    """Active listening (context-driven).

    Detects when a speaker references scripture by (a) matching contextual
    cue phrases like "in the book of …", "the Bible says in …", "Jesus
    said …" and extracting the reference from what follows; (b) normalising
    spoken forms like "Matthew chapter five verse two" -> "Matthew 5:2";
    (c) falling back to a semantic match with a lower threshold when a cue
    word is present, and a stricter one otherwise (filters noise)."""
    require_ready()
    require_enabled()
    require_test_access("listen", x_test_key)
    if store.get_flags().get("listen_enabled", "1") == "0":
        raise HTTPException(status_code=403, detail="Active listening is disabled.")

    text = (body.text or "").strip()
    if not text or len(text.split()) < 3:
        return {"matched": False, "reason": "too_short"}

    style = "v" if body.ref_style == "v" else "colon"
    low = text.lower()
    has_cue = any(c in low for c in _CUES)

    # 1. Look for a reference straight in the text (works for "Matthew 5:2",
    #    "Matthew chapter five verse two", "psalm 23", "John three sixteen").
    ref = parse_reference(text)
    trigger = "direct"

    # 2. If not found directly, try to isolate it from a cue phrase.
    if not ref:
        ref = _extract_reference_from_cue(text)
        if ref:
            trigger = "cue_phrase"

    if ref:
        book_no, chapter, verse = ref
        display = format_reference(book_no, chapter, verse, style=style)
        # Look up the matched verse (verse-level if given, else chapter head).
        key = f"{book_no}:{chapter}:{verse or 1}"
        canonical = state["matcher"].by_key.get(key)
        if canonical:
            eff_version = body.version if (body.version != "all" and body.version in canonical) else (
                "KJV" if "KJV" in canonical else next(iter(canonical))
            )
            m = canonical[eff_version]
            store.log_event("listen", "listen", text, m["ref"], True, body.version, "all")
            return {
                "matched": True,
                "exact": True,
                "cue": has_cue,
                "trigger": trigger,
                "snippet": text,
                "normalized_ref": display,   # e.g. "Matthew 5:2" or "Matthew 5v2"
                "result": {
                    "ref": m["ref"], "version": m["version"], "text": m["text"],
                    "book_no": book_no, "chapter": chapter,
                    "verse": verse or 1,
                    "relevance": 100,
                },
            }

    # 3. Semantic fallback — paraphrased quotes/comments about a verse.
    matches = state["matcher"].predict(text, top_k=1, version=body.version)
    if not matches:
        return {"matched": False, "reason": "no_match"}
    top = matches[0]
    threshold = LISTEN_CUE_THRESHOLD if has_cue else LISTEN_THRESHOLD
    if top["exact"] or top["score"] >= threshold:
        store.log_event("listen", "listen", text, top["ref"], True, body.version, "all")
        book_no, chapter, verse = _book_chapter_verse(top["key"])
        return {
            "matched": True,
            "exact": bool(top["exact"]),
            "cue": has_cue,
            "trigger": "semantic",
            "snippet": text,
            "normalized_ref": format_reference(book_no, chapter, verse, style=style),
            "result": {
                "ref": top["ref"], "version": top["version"], "text": top["text"],
                "book_no": book_no, "chapter": chapter, "verse": verse,
                "relevance": round(top["score"] * 100),
            },
        }
    return {"matched": False, "reason": "low_confidence", "score": round(top["score"], 3)}


def _verse_payload(r: dict) -> dict:
    book_no, chapter, verse = _book_chapter_verse(r["key"])
    return {
        "ref": r["ref"], "version": r["version"], "text": r["text"],
        "book_no": book_no, "chapter": chapter, "verse": verse,
        "score": round(r.get("score", 0.0), 4),
        "relevance": round(r.get("score", 0.0) * 100),
    }


@app.get("/api/chapter")
def chapter(book_no: int, chapter: int, version: str = "KJV"):
    """Return a full chapter of a translation (for the context / chapter view)."""
    require_ready()
    require_enabled()
    result = state["matcher"].get_chapter(book_no, chapter, version)
    if not result:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return result


@app.get("/api/crossrefs")
def crossrefs(book_no: int, chapter: int, verse: int, version: str = "all"):
    """Cross-references for a verse (openbible, CC-BY)."""
    require_ready()
    require_enabled()
    if store.get_flags().get("crossrefs_enabled", "1") == "0":
        return {"refs": []}
    key = f"{book_no}:{chapter}:{verse}"
    return {"refs": state["matcher"].get_crossrefs(key, version)}


@app.get("/api/similar")
def similar(book_no: int, chapter: int, verse: int, version: str = "all", top_k: int = 6):
    """Verses most semantically similar to the given verse."""
    require_ready()
    require_enabled()
    if store.get_flags().get("similar_enabled", "1") == "0":
        return {"results": []}
    key = f"{book_no}:{chapter}:{verse}"
    rows = state["matcher"].similar(key, top_k=max(1, min(top_k, 12)), version=version)
    return {"results": [_verse_payload(r) for r in rows]}


@app.get("/api/topics")
def topics():
    """Curated topic chips (admin-managed, enabled only)."""
    try:
        rows = store.list_topics(enabled_only=True)
    except Exception:  # noqa: BLE001
        rows = []
    return {"topics": [{"label": t["label"], "emoji": t["emoji"], "query": t["query"]} for t in rows]}


@app.get("/api/config")
def config():
    """Public feature flags the UI uses to toggle features."""
    f = store.get_flags()
    return {
        "ask_enabled": f.get("ask_enabled", "1") == "1",
        "crossrefs_enabled": f.get("crossrefs_enabled", "1") == "1",
        "similar_enabled": f.get("similar_enabled", "1") == "1",
        "listen_enabled": f.get("listen_enabled", "1") == "1",
        "maintenance": f.get("maintenance", "0") == "1",
        "disabled": f.get("disabled", "0") == "1",
        "test_mode": f.get("test_mode", "0") == "1",
        "admin_configured": adminauth.is_configured(),
    }


@app.post("/api/test/access")
def test_access(x_test_key: str = Header(default="")):
    """Validate a test key and return its per-feature permissions."""
    key = store.get_test_key(x_test_key)
    if not key:
        raise HTTPException(status_code=401, detail="Invalid or disabled test key.")
    return {
        "valid": True,
        "label": key.get("label") or "",
        "features": {
            "speak": bool(key.get("speak")),
            "type": bool(key.get("type_")),
            "ask": bool(key.get("ask")),
            "listen": bool(key.get("listen")),
        },
    }


class FeedbackBody(BaseModel):
    rating: int | None = None
    message: str = ""


@app.post("/api/feedback")
def submit_feedback(body: FeedbackBody, x_test_key: str = Header(default="")):
    """Test users leave feedback; visible to admin in the console."""
    key = store.get_test_key(x_test_key)
    if not key:
        raise HTTPException(status_code=401, detail="A valid test key is required.")
    if not (body.message or "").strip():
        raise HTTPException(status_code=400, detail="Feedback message is required.")
    store.add_feedback(x_test_key, key.get("label") or "", body.rating, body.message)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Claude-powered natural-language Q&A (RAG grounded in retrieved verses).
# ---------------------------------------------------------------------------
ASK_SYSTEM = (
    "You are a concise Bible study assistant. Answer the user's question using "
    "ONLY the Bible verses provided as context. Cite the relevant references "
    "(e.g. John 3:16) inline. If the provided verses do not address the "
    "question, say so plainly rather than guessing. Keep the answer to a short "
    "paragraph. Do not invent verses or references."
)


def _ask_verses(question: str, version: str) -> list[dict]:
    matches = state["matcher"].predict(question, top_k=8, version=version)
    verses = []
    for r in matches:
        book_no, chapter, verse = _book_chapter_verse(r["key"])
        kjv = next((t for t in r["translations"] if t["version"] == "KJV"), None)
        chosen = kjv or r["translations"][0]
        verses.append(
            {
                "ref": chosen["ref"], "text": chosen["text"],
                "book_no": book_no, "chapter": chapter, "verse": verse,
            }
        )
    return verses


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def _ask_stream(question: str, version: str, verses: list[dict]):
    """SSE generator: verses, then streamed answer tokens (or a graceful note)."""
    yield _sse({"type": "verses", "verses": verses})

    # Vault first (admin-managed), env fallback.
    api_key = store.get_app_key("anthropic_api_key", env="ANTHROPIC_API_KEY")
    if not api_key:
        yield _sse({"type": "error", "error": "Q&A is not configured (no API key). "
                    "Showing the most relevant verses instead."})
        yield _sse({"type": "done"})
        return

    cache_key = f"{version}::{question.lower()}"
    if cache_key in _answer_cache:
        _answer_cache.move_to_end(cache_key)
        yield _sse({"type": "delta", "text": _answer_cache[cache_key]})
        yield _sse({"type": "done", "cached": True})
        return

    context = "\n".join(f"{v['ref']}: {v['text']}" for v in verses)
    prompt = f"Context verses:\n{context}\n\nQuestion: {question}"

    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    last_err = None
    for model in (ANSWER_MODEL, ANSWER_MODEL_FALLBACK):
        collected: list[str] = []
        try:
            with client.messages.stream(
                model=model, max_tokens=1024, system=ASK_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for text in stream.text_stream:
                    collected.append(text)
                    yield _sse({"type": "delta", "text": text})
            answer = "".join(collected).strip()
            _answer_cache[cache_key] = answer
            if len(_answer_cache) > ANSWER_CACHE_SIZE:
                _answer_cache.popitem(last=False)
            yield _sse({"type": "done", "model": model})
            return
        except Exception as e:  # noqa: BLE001
            last_err = e
            if collected:  # already streamed partial output — don't retry
                yield _sse({"type": "error", "error": f"Answer interrupted: {e}"})
                yield _sse({"type": "done"})
                return
            # nothing streamed yet: fall through to the cheaper fallback model
            continue

    yield _sse({"type": "error", "error": f"Q&A request failed: {last_err}. "
                "Showing the most relevant verses instead."})
    yield _sse({"type": "done"})


@app.post("/api/ask")
def ask(query: AskQuery, x_test_key: str = Header(default="")):
    """Stream a natural-language answer grounded in retrieved verses (SSE)."""
    require_ready()
    require_enabled()
    require_test_access("ask", x_test_key)
    if store.get_flags().get("ask_enabled", "1") == "0":
        raise HTTPException(status_code=403, detail="The Ask feature is disabled.")
    question = (query.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Empty question")
    question = question[:MAX_QUESTION_LEN]

    verses = _ask_verses(question, query.version)
    store.log_event("ask", "ask", question, verses[0]["ref"] if verses else "",
                    bool(verses), query.version, "all")
    return StreamingResponse(
        _ask_stream(question, query.version, verses),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Admin API (auth-gated): analytics, topic CMS, feature flags, search lab.
# ---------------------------------------------------------------------------
@app.post("/api/admin/login")
def admin_login(body: LoginBody):
    if not adminauth.is_configured():
        raise HTTPException(status_code=503, detail="Admin is not configured (set ADMIN_PASSWORD).")
    token = adminauth.login(body.password)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid password")
    return {"token": token}


@app.get("/api/admin/stats")
def admin_stats(days: int = 30, _: bool = Depends(require_admin)):
    return store.stats(days=days)


@app.get("/api/admin/zero-results")
def admin_zero_results(days: int = 30, _: bool = Depends(require_admin)):
    return {"queries": store.zero_results(days=days)}


@app.get("/api/admin/topics")
def admin_topics(_: bool = Depends(require_admin)):
    return {"topics": store.list_topics()}


@app.post("/api/admin/topics")
def admin_add_topic(body: TopicBody, _: bool = Depends(require_admin)):
    tid = store.add_topic(body.label, body.emoji, body.query)
    return {"id": tid}


@app.put("/api/admin/topics/{topic_id}")
def admin_update_topic(topic_id: int, body: dict, _: bool = Depends(require_admin)):
    store.update_topic(topic_id, body)
    return {"ok": True}


@app.delete("/api/admin/topics/{topic_id}")
def admin_delete_topic(topic_id: int, _: bool = Depends(require_admin)):
    store.delete_topic(topic_id)
    return {"ok": True}


@app.get("/api/admin/flags")
def admin_get_flags(_: bool = Depends(require_admin)):
    return {"flags": store.get_flags()}


@app.put("/api/admin/flags")
def admin_set_flags(body: dict, _: bool = Depends(require_admin)):
    store.set_flags(body)
    # Apply any weight changes to the live matcher immediately.
    matcher_mod.set_weights(store.get_weights())
    return {"flags": store.get_flags()}


@app.post("/api/admin/search-preview")
def admin_search_preview(body: PreviewBody, _: bool = Depends(require_admin)):
    """Run a query with optional weight overrides and return ranked results
    with their component scores (the search-quality lab)."""
    require_ready()
    matches = state["matcher"].predict(
        body.text, top_k=10, version=body.version, scope=body.scope, weights=body.weights
    )
    return {
        "results": [
            {
                "ref": r["ref"], "version": r["version"], "text": r["text"],
                "score": round(r["score"], 4),
                "semantic": round(r.get("semantic", 0.0), 4),
                "lexical": round(r.get("lexical", 0.0), 4),
                "ce": round(r.get("ce", 0.0), 4),
                "exact": r["exact"],
            }
            for r in matches
        ]
    }


# -- admin: test keys + feedback ---------------------------------------------
@app.get("/api/admin/test-keys")
def admin_list_keys(_: bool = Depends(require_admin)):
    return {"keys": store.list_test_keys()}


@app.post("/api/admin/test-keys")
def admin_add_key(body: dict, _: bool = Depends(require_admin)):
    return store.add_test_key((body or {}).get("label", ""))


@app.put("/api/admin/test-keys/{key_id}")
def admin_update_key(key_id: int, body: dict, _: bool = Depends(require_admin)):
    store.update_test_key(key_id, body or {})
    return {"ok": True}


@app.delete("/api/admin/test-keys/{key_id}")
def admin_delete_key(key_id: int, _: bool = Depends(require_admin)):
    store.delete_test_key(key_id)
    return {"ok": True}


@app.get("/api/admin/feedback")
def admin_feedback(_: bool = Depends(require_admin)):
    return {"feedback": store.list_feedback()}


@app.delete("/api/admin/feedback/{fid}")
def admin_delete_feedback(fid: int, _: bool = Depends(require_admin)):
    store.delete_feedback(fid)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Accounts & billing (Supabase auth + Stripe).
# ---------------------------------------------------------------------------
class CheckoutBody(BaseModel):
    plan: str
    origin: str = ""


@app.get("/api/me")
def me(user: dict | None = Depends(optional_user)):
    """Current user profile + plan (null when anonymous)."""
    return {
        "user": (
            {
                "id": user["id"],
                "email": user.get("email", ""),
                "name": user.get("name", ""),
                "plan": user.get("plan", "free"),
                "status": user.get("status", "active"),
                "onboarded": bool(user.get("onboarded_at")),
            }
            if user
            else None
        ),
        "auth_configured": clerkauth.is_configured(),
        "billing_configured": billing.is_configured(),
    }


@app.post("/api/me/onboarded")
def me_onboarded(user: dict = Depends(require_user)):
    """Mark the onboarding walkthrough as seen (idempotent, once per account)."""
    store.mark_onboarded(user["id"])
    return {"ok": True}


@app.post("/api/billing/checkout")
def billing_checkout(body: CheckoutBody, user: dict = Depends(require_user)):
    """Start a Stripe Checkout session for a paid plan."""
    if body.plan not in ("plus", "speaker"):
        raise HTTPException(status_code=400, detail="Unknown plan.")
    origin = (body.origin or "").rstrip("/") or "http://localhost:3000"
    try:
        url = billing.create_checkout(user, body.plan, origin)
        return {"url": url}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/api/billing/portal")
def billing_portal(body: CheckoutBody, user: dict = Depends(require_user)):
    """Open the Stripe customer portal (manage / cancel subscription)."""
    origin = (body.origin or "").rstrip("/") or "http://localhost:3000"
    try:
        url = billing.create_portal(user, origin)
        return {"url": url}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/api/billing/webhook")
async def billing_webhook(request: Request):
    """Stripe webhook — signature-verified, idempotent."""
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        event = billing.verify_webhook(payload, signature)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Webhook verification failed: {e}")
    try:
        billing.apply_event(event)
    except Exception as e:  # noqa: BLE001
        # Return 500 so Stripe retries.
        raise HTTPException(status_code=500, detail=f"Webhook handling failed: {e}")
    return {"received": True}


# -- Sermon Studio (Speaker plan) -----------------------------------------------
class SermonPointBody(BaseModel):
    beat: str = ""
    title: str = ""
    notes: str = ""
    verse_refs: list[dict] = []


class SermonBody(BaseModel):
    title: str
    description: str = ""
    points: list[SermonPointBody] = []


class SermonUpdateBody(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    points: list[SermonPointBody] | None = None


@app.get("/api/sermons")
def list_sermons_route(user: dict = Depends(require_speaker)):
    return {"sermons": store.list_sermons(user["id"])}


@app.post("/api/sermons")
def create_sermon_route(body: SermonBody, user: dict = Depends(require_speaker)):
    if not body.title.strip():
        raise HTTPException(status_code=400, detail="Title is required.")
    sermon = store.create_sermon(
        user["id"], body.title.strip(), body.description,
        [p.model_dump() for p in body.points],
    )
    return {"sermon": sermon}


@app.get("/api/sermons/{sermon_id}")
def get_sermon_route(sermon_id: int, user: dict = Depends(require_speaker)):
    sermon = store.get_sermon(user["id"], sermon_id)
    if not sermon:
        raise HTTPException(status_code=404, detail="Sermon not found.")
    return {"sermon": sermon}


@app.put("/api/sermons/{sermon_id}")
def update_sermon_route(sermon_id: int, body: SermonUpdateBody, user: dict = Depends(require_speaker)):
    title = body.title.strip() if body.title is not None else None
    sermon = store.update_sermon(
        user["id"], sermon_id,
        title=title, description=body.description, status=body.status,
        points=[p.model_dump() for p in body.points] if body.points is not None else None,
    )
    if not sermon:
        raise HTTPException(status_code=404, detail="Sermon not found.")
    return {"sermon": sermon}


@app.delete("/api/sermons/{sermon_id}")
def archive_sermon_route(sermon_id: int, user: dict = Depends(require_speaker)):
    if not store.archive_sermon(user["id"], sermon_id):
        raise HTTPException(status_code=404, detail="Sermon not found.")
    return {"ok": True}


# -- admin: billing, users, app-key vault --------------------------------------
@app.get("/api/admin/users")
def admin_users(_: bool = Depends(require_admin)):
    return {"users": store.list_users()}


@app.get("/api/admin/payments")
def admin_payments(_: bool = Depends(require_admin)):
    return {"payments": store.list_payments()}


@app.get("/api/admin/billing-stats")
def admin_billing_stats(_: bool = Depends(require_admin)):
    return store.billing_stats()


class AppKeyBody(BaseModel):
    name: str
    value: str


@app.get("/api/admin/app-keys")
def admin_app_keys(_: bool = Depends(require_admin)):
    """Known + custom service keys, values always masked."""
    return {"keys": store.list_app_keys_masked()}


@app.put("/api/admin/app-keys")
def admin_set_app_key(body: AppKeyBody, _: bool = Depends(require_admin)):
    name = body.name.strip().lower().replace(" ", "_")
    if not name or not body.value.strip():
        raise HTTPException(status_code=400, detail="Name and value are required.")
    store.set_app_key(name, body.value.strip())
    return {"ok": True, "keys": store.list_app_keys_masked()}


@app.delete("/api/admin/app-keys/{name}")
def admin_delete_app_key(name: str, _: bool = Depends(require_admin)):
    store.delete_app_key(name)
    return {"ok": True}
