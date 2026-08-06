#!/usr/bin/env python3
"""LLM inference + web-grounded answers, sold over x402 on free inventory.

Why this exists: the Bazaar scan says the categories with real REPEAT use are the ones
we had no presence in at all — exa 30.5 calls/payer, search 13.7, ai 13.7,
llm/inference 11.1, against 1.1 for every route we sell. The standing note in
state/MEMORY.md concluded that tier was "structurally closed to us" because the winners
are gateways reselling PAID upstreams (Exa, Tavily, Firecrawl, LLM APIs) and a
receive-only wallet cannot buy inventory.

That conclusion was too strong. It is closed only if inventory has to be bought.
Measured 2026-07-29, open-weight inference is available at zero cost and zero signup:

    llm7.io          gpt-oss:20b   4/4 success, 0.4-1.7s   keyless
    pollinations.ai  gpt-oss-20b   works, but 1 concurrent request per IP and 25s+
                                   under load — last resort only, and it needs a
                                   browser User-Agent or Cloudflare answers 403 (1010)
    models.github.ai gpt-4.1 etc.  best quality, 20k req/min — but needs a token

So the margin here is 100%, exactly like the keyless routes in agentdata_routes.py, and
the risk is asymmetric: if a free backend disappears the route 502s and we lose nothing,
because nothing was ever spent on it.

⛔ DO NOT ENABLE GITHUB MODELS FOR THIS. Resolved 2026-07-29, against the primary source:
GitHub's own responsible-use page says the feature "is designed to allow for learning,
experimentation and proof-of-concept activities" and "is not designed for production use
cases", and the API docs call the free rate limits "intended to help you get started with
experimentation". Reselling that output through a paid endpoint IS a production use case,
so the GITHUB_MODELS_TOKEN branch is left in place only as a documented dead end.

It would not have paid off anyway. The `x-ratelimit-limit-requests: 20000` header is the
UPSTREAM Azure deployment's capacity, not our quota — proven by sending 25 calls in 53s
and watching `x-ratelimit-remaining-requests` sit at 19999 for every one of them. The real
documented ceiling for a Free plan is 15 req/min and **150 requests per DAY** on low-tier
models (10/min, 50/day on high tier), which caps the whole lane at a couple of dollars a
day even if every single call sold.

The keyless llm7 path serves `gpt-oss:20b` — an open-weight model — which is why it is the
default first provider and the one this is actually built on.

The flagship is /llm/answer, not /llm/chat. Raw chat competes with every gateway on the
network on a commodity; a grounded answer with citations is the `exa` shape — the single
highest calls-per-payer tag measured — and we already own both halves of it for free
(webdata_routes' multi-engine search and its SSRF-guarded reader).

Mount with:
    from llm_routes import router as _llm_router, route_specs as _llm_route_specs
    app.include_router(_llm_router, prefix="/llm")
    llm_specs = _llm_route_specs(prefix="/llm", cheap="$0.01", answer="$0.02")
"""
import json
import os
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

# A browser-ish UA is not cosmetic: Cloudflare in front of pollinations.ai answers
# `403 error code: 1010` to urllib/httpx defaults, which reads as "backend down".
_UA = "Mozilla/5.0 (compatible; tokenguard-x402/1.0; +https://github.com/eltociear/tokenguard-mcp)"

# Ordered failover chain. Each entry is (name, url, model, token) — token "" = keyless.
# GitHub Models leads when a token is present because it is the only one with a rate
# limit we could survive a burst on (20,000 req/min, 2M tokens/min) and the only one
# serving a frontier-class model. Both token-gated entries stay optional so the chain
# still works with no credential configured anywhere.
_GH_TOKEN = os.environ.get("GITHUB_MODELS_TOKEN", "").strip()
_HF_TOKEN = os.environ.get("HF_INFERENCE_TOKEN", "").strip()

_PROVIDERS = (
    ([("github", "https://models.github.ai/inference/chat/completions",
       os.environ.get("GITHUB_MODELS_MODEL", "openai/gpt-4.1-mini"), _GH_TOKEN)] if _GH_TOKEN else [])
    + [("llm7", "https://api.llm7.io/v1/chat/completions", "gpt-oss:20b", "")]
    + ([("huggingface", "https://router.huggingface.co/v1/chat/completions",
         os.environ.get("HF_INFERENCE_MODEL", "openai/gpt-oss-20b"), _HF_TOKEN)] if _HF_TOKEN else [])
    # Pollinations last: its anonymous tier is one concurrent request per IP and starts
    # answering 402 "budget too low" once that allowance is used, so it is a spare wheel.
    + [("pollinations", "https://text.pollinations.ai/openai", "openai-fast", "")]
)

_MAX_PROMPT_CHARS = 60_000   # ~15k tokens; every backend here is a 20B-class model
_PER_PAGE_CHARS = 6_000      # keep one long page from crowding out the other citations

# gpt-oss is a REASONING model: it emits chain-of-thought into a separate `reasoning`
# field, but `max_tokens` caps reasoning AND answer together. Passing the caller's
# max_tokens straight through therefore lets the reasoning eat the whole budget and return
# HTTP 200 with content="". Measured 2026-07-29 on "In one sentence, what is EIP-3009?":
# max_tokens 150 -> empty, 400 -> fine, 800 -> empty. It is not a threshold, it is a race,
# so the fix is headroom plus one retry, not a bigger constant. The caller's number governs
# the ANSWER; these are invisible thinking tokens on top of it.
_REASONING_HEADROOM = 1_500
_REASONING_RETRY = 4_000


class ChatRequest(BaseModel):
    prompt: str
    system: Optional[str] = None
    max_tokens: Optional[int] = 800
    temperature: Optional[float] = 0.3


class AnswerRequest(BaseModel):
    query: str
    max_sources: Optional[int] = 4
    max_tokens: Optional[int] = 700


class ExtractRequest(BaseModel):
    text: Optional[str] = None
    url: Optional[str] = None
    schema_hint: Optional[dict] = None
    instruction: Optional[str] = None


async def _complete(messages, max_tokens: int, temperature: float, timeout: float = 45.0):
    """Run the failover chain. Returns (provider, text, usage, attempts).

    A provider that answers 200 with an EMPTY content string counts as a failure and we
    move on: gpt-oss puts its chain of thought in a separate `reasoning` field and does
    sometimes return content="" for terse instructions, which would otherwise settle a
    payment for nothing.
    """
    import httpx

    attempts = {}
    for name, url, model, token in _PROVIDERS:
        headers = {"Content-Type": "application/json", "User-Agent": _UA,
                   "Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        # Two budgets, not one. See _REASONING_HEADROOM: an empty answer is usually a
        # starved reasoning budget, not a broken provider, and every backend here runs the
        # same model family — so failing over immediately just repeats the same failure.
        for attempt, budget in enumerate((max_tokens + _REASONING_HEADROOM,
                                          max_tokens + _REASONING_RETRY)):
            body = {"model": model, "messages": messages,
                    "max_tokens": budget, "temperature": temperature}
            t0 = time.monotonic()
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(url, json=body, headers=headers)
                if resp.status_code != 200:
                    attempts[name] = f"HTTP {resp.status_code}"
                    break  # a non-200 will not be fixed by a bigger budget
                data = resp.json()
                text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
                text = text.strip()
                if not text:
                    attempts[name] = f"empty content (budget {budget})"
                    continue  # retry this same provider with the larger budget
                usage = data.get("usage") or {}
                usage["ms"] = int((time.monotonic() - t0) * 1000)
                usage["token_budget"] = budget
                if attempt:
                    usage["retried_for_empty_content"] = True
                return name, text, usage, attempts
            except Exception as e:
                attempts[name] = f"{type(e).__name__}"
                break
    # 502, never 200: the payment middleware must not settle a call that produced nothing.
    raise HTTPException(502, f"all inference backends failed: {attempts}")


@router.post("/chat")
async def chat(req: ChatRequest):
    prompt = (req.prompt or "").strip()
    if not prompt:
        raise HTTPException(400, "prompt is required")
    messages = ([{"role": "system", "content": req.system}] if req.system else []) + \
               [{"role": "user", "content": prompt[:_MAX_PROMPT_CHARS]}]
    provider, text, usage, _ = await _complete(
        messages, max(1, min(int(req.max_tokens or 800), 4000)),
        max(0.0, min(float(req.temperature if req.temperature is not None else 0.3), 2.0)))
    return {"answer": text, "provider": provider, "usage": usage,
            "generated_at": datetime.utcnow().isoformat() + "Z"}


@router.post("/answer")
async def answer(req: AnswerRequest):
    """Search the live web, read the top hits, and synthesise a cited answer."""
    query = (req.query or "").strip()
    if not query:
        raise HTTPException(400, "query is required")
    try:
        from webdata_routes import _run_search, _fetch_text, _to_markdown
    except Exception as e:
        raise HTTPException(503, f"web-data backend unavailable: {type(e).__name__}: {e}")

    k = max(1, min(int(req.max_sources or 4), 8))
    engine, results, errors = await _run_search(query, k * 2)
    if not results:
        raise HTTPException(502, f"all search backends failed or returned nothing: {errors}")

    # Read the top hits in order, keeping the ones that actually yield text. A page that
    # 403s a datacenter IP is common enough that fetching exactly k would routinely leave
    # the model with two sources, so we walk further down the ranking until k stick.
    sources, blocks = [], []
    for r in results:
        if len(sources) >= k:
            break
        url = r.get("url") or ""
        if not url:
            continue
        try:
            html, final_url = await _fetch_text(url, 1_000_000, timeout=15.0, ua=_UA)
            markdown, title = _to_markdown(html, include_links=False)
        except Exception:
            continue
        if not markdown or len(markdown) < 200:
            continue
        n = len(sources) + 1
        sources.append({"n": n, "title": title or r.get("title") or url, "url": final_url})
        blocks.append(f"[{n}] {title or r.get('title') or url}\n{markdown[:_PER_PAGE_CHARS]}")

    if not sources:
        raise HTTPException(502, "search returned hits but none of them could be read")

    context = "\n\n---\n\n".join(blocks)[:_MAX_PROMPT_CHARS]
    system = ("You answer questions strictly from the numbered sources given. Cite every "
              "claim inline as [1], [2] and so on. If the sources do not contain the "
              "answer, say so plainly instead of guessing. Be concise and factual.")
    user = f"Question: {query}\n\nSources:\n\n{context}\n\nAnswer the question, citing sources inline."
    provider, text, usage, _ = await _complete(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max(1, min(int(req.max_tokens or 700), 2000)), 0.2, timeout=60.0)
    return {"query": query, "answer": text, "sources": sources, "engine": engine,
            "provider": provider, "usage": usage,
            "generated_at": datetime.utcnow().isoformat() + "Z"}


@router.post("/extract")
async def extract(req: ExtractRequest):
    """Turn free text (or a URL's content) into structured JSON."""
    text = (req.text or "").strip()
    source_url = None
    if not text:
        if not req.url:
            raise HTTPException(400, "one of text or url is required")
        try:
            from webdata_routes import _fetch_text, _to_markdown
            html, source_url = await _fetch_text(req.url, 1_000_000, timeout=20.0, ua=_UA)
            text = (_to_markdown(html, include_links=False)[0] or "").strip()
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(502, f"could not read url: {type(e).__name__}: {e}")
        if not text:
            raise HTTPException(502, "url returned no extractable text")

    want = json.dumps(req.schema_hint) if req.schema_hint else \
        '{"<field>": "<value>"} using whatever fields the text supports'
    system = ("You are a precise extraction engine. Output ONLY a single JSON object, no "
              "prose, no markdown fence. Use null for fields the text does not support; "
              "never invent values.")
    user = (f"{req.instruction or 'Extract the structured data from the text below.'}\n\n"
            f"Target shape: {want}\n\nText:\n{text[:_MAX_PROMPT_CHARS]}")
    provider, raw, usage, _ = await _complete(
        [{"role": "system", "content": system}, {"role": "user", "content": user}], 1200, 0.0)

    # Models fence JSON even when told not to; recover rather than 502 on a formatting tic.
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1] if "```" in cleaned[3:] else cleaned[3:]
        cleaned = cleaned.split("\n", 1)[1] if cleaned.lower().startswith("json") else cleaned
    try:
        parsed, ok = json.loads(cleaned.strip()), True
    except Exception:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        try:
            parsed, ok = json.loads(cleaned[start:end + 1]), True
        except Exception:
            parsed, ok = None, False
    if not ok:
        raise HTTPException(502, "model did not return parseable JSON")
    out = {"data": parsed, "provider": provider, "usage": usage,
           "generated_at": datetime.utcnow().isoformat() + "Z"}
    if source_url:
        out["source_url"] = source_url
    return out


@router.get("/selftest")
async def llm_selftest():
    """FREE. Per-backend reachability for the inference chain.

    Same reasoning as the web-data selftest: a paid route cannot be exercised without
    paying, so without this there is no way to tell a backend that has gone away from one
    that is answering 200 with empty content. Returns latency and a boolean only — never
    generated text — so it gives away nothing the paid routes charge for.
    """
    import httpx

    probe = [{"role": "user", "content": "Reply with the single word: ready"}]
    out = {}
    for name, url, model, token in _PROVIDERS:
        headers = {"Content-Type": "application/json", "User-Agent": _UA,
                   "Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(url, json={"model": model, "messages": probe,
                                                    "max_tokens": 200}, headers=headers)
            chars = 0
            if resp.status_code == 200:
                chars = len(((resp.json().get("choices") or [{}])[0]
                             .get("message", {}).get("content") or "").strip())
            out[name] = {"ok": resp.status_code == 200 and chars > 0, "model": model,
                         "status": resp.status_code, "chars": chars,
                         "ms": int((time.monotonic() - t0) * 1000)}
        except Exception as e:
            out[name] = {"ok": False, "model": model, "error": type(e).__name__,
                         "ms": int((time.monotonic() - t0) * 1000)}
    return {"backends": out, "usable": sum(1 for v in out.values() if v.get("ok")),
            "github_models_enabled": bool(_GH_TOKEN),
            "huggingface_enabled": bool(_HF_TOKEN),
            "checked_at": datetime.utcnow().isoformat() + "Z"}


def route_specs(prefix: str = "", cheap: str = "$0.01", answer: str = "$0.02"):
    """(path, price, description, input_example, input_schema, output_example) per route."""
    p = prefix.rstrip("/")
    return [
        (p + "/answer", answer,
         "What is the actual answer to this question, according to the live web right now? "
         "Runs a multi-engine search, reads the top pages, and returns one synthesised answer "
         "with inline [1][2] citations and the source URLs behind them — the whole "
         "search-read-summarise loop in a single paid call instead of a dozen",
         {"query": "What does the x402 payment-required header contain?"},
         {"properties": {"query": {"type": "string", "description": "Question to answer from the live web"},
                         "max_sources": {"type": "integer", "description": "1-8 pages to read (default 4)"},
                         "max_tokens": {"type": "integer", "description": "Answer length cap (default 700)"}},
          "required": ["query"]},
         {"query": "What does the x402 payment-required header contain?",
          "answer": "It carries the accepted payment options, each with scheme, network, "
                    "amount and payTo address [1], plus the x402 protocol version [2].",
          "sources": [{"n": 1, "title": "x402 spec", "url": "https://example.com/spec"},
                      {"n": 2, "title": "x402 docs", "url": "https://example.com/docs"}],
          "engine": "duckduckgo", "provider": "llm7"}),
        (p + "/chat", cheap,
         "Run a chat completion against an open-weight 20B-class model — plain prompt in, "
         "text out, with automatic failover across independent inference backends so a "
         "single call still answers when any one provider is down or rate-limiting",
         {"prompt": "Summarise the EIP-3009 transferWithAuthorization flow in three sentences."},
         {"properties": {"prompt": {"type": "string", "description": "The user prompt"},
                         "system": {"type": "string", "description": "Optional system instruction"},
                         "max_tokens": {"type": "integer", "description": "1-4000 (default 800)"},
                         "temperature": {"type": "number", "description": "0-2 (default 0.3)"}},
          "required": ["prompt"]},
         {"answer": "EIP-3009 lets a holder sign an off-chain authorization…",
          "provider": "llm7", "usage": {"total_tokens": 210, "ms": 740}}),
        (p + "/extract", cheap,
         "Turn messy text — or any URL's page content — into structured JSON matching the "
         "shape you ask for, so an agent can consume a web page as data instead of prose",
         {"url": "https://example.com/pricing",
          "schema_hint": {"plan": "string", "price_usd": "number"}},
         {"properties": {"text": {"type": "string", "description": "Raw text to extract from"},
                         "url": {"type": "string", "description": "Page to fetch and extract from (used when text is omitted)"},
                         "schema_hint": {"type": "object", "description": "Target JSON shape"},
                         "instruction": {"type": "string", "description": "Optional extra extraction instruction"}},
          "required": []},
         {"data": {"plan": "Pro", "price_usd": 20}, "provider": "llm7",
          "source_url": "https://example.com/pricing"}),
    ]
