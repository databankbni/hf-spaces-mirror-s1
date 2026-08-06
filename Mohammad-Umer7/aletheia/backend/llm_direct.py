"""Direct Groq chat-completion calls that bypass cognee entirely.

Two consumers, both deliberately memory-free:
- the conflict detector (does a new source dispute a trusted one?)
- the "Stateless LLM" comparison answer (what would an LLM with no memory say?)

Uses the OpenAI-compatible endpoint with the key already in .env (LLM_API_KEY).
A separate model from cognee's pipeline: Groq quotas are per-model, so these
small calls never eat the ingest/recall token budget.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import re
from typing import Optional

import httpx

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.3-70b-versatile"

STATELESS_SYSTEM_PROMPT = (
    "Answer from your general knowledge only. If you don't have verified "
    "information, say so."
)

CONFLICT_SYSTEM_PROMPT = (
    "You are a research-integrity checker. You are given one NEW source and a "
    "library of TRUSTED sources. Report which trusted sources the new source "
    "directly disputes, contradicts, retracts, or debunks. A conflict means the "
    "new source states that a specific claim in a trusted source is false, "
    "fabricated, retracted, or unsupported. Differences in emphasis or topic are "
    "NOT conflicts.\n"
    'Reply with STRICT JSON only — no prose, no code fences: '
    '{"conflicts": [{"disputed_source_id": "<id of an existing trusted source>", '
    '"reason": "<one sentence>"}]}\n'
    "Use an empty list if there are no conflicts."
)


async def chat(
    messages: list[dict],
    *,
    temperature: float = 0.0,
    max_tokens: int = 700,
    tries: int = 4,
) -> str:
    """One chat completion against Groq, with backoff on 429/5xx."""
    api_key = os.environ.get("LLM_API_KEY", "")
    if not api_key:
        raise RuntimeError("LLM_API_KEY is not set")
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    last_status = None
    for attempt in range(1, tries + 1):
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                GROQ_CHAT_URL,
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        last_status = resp.status_code
        if resp.status_code in (429, 500, 502, 503) and attempt < tries:
            delay = 2.0 * (2 ** (attempt - 1)) + random.uniform(0.0, 1.0)
            print(f"  [llm_direct] HTTP {resp.status_code}, retrying in {delay:.0f}s")
            await asyncio.sleep(delay)
            continue
        resp.raise_for_status()
    raise RuntimeError(f"Groq call failed after {tries} tries (last status {last_status})")


async def stateless_answer(question: str) -> Optional[str]:
    """The no-memory baseline answer for the compare toggle. Never raises."""
    try:
        return await chat(
            [
                {"role": "system", "content": STATELESS_SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            temperature=0.2,
            max_tokens=400,
        )
    except Exception as exc:
        print(f"  [stateless] unavailable: {type(exc).__name__}: {exc}")
        return None


def _parse_conflicts(raw: str, valid_ids: set[str]) -> list[dict]:
    """Strict-JSON parse with defensive cleanup. Raises on malformed output."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL).strip()
    # tolerate a stray sentence around the object: grab the outermost braces
    if not text.startswith("{"):
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if m:
            text = m.group(0)
    data = json.loads(text)
    out = []
    for item in data.get("conflicts", []):
        sid = item.get("disputed_source_id")
        reason = str(item.get("reason") or "").strip()
        if sid in valid_ids and reason:
            out.append({"disputed_source_id": sid, "reason": reason})
    return out


async def detect_conflicts(new_source: dict, trusted: list[dict]) -> list[dict]:
    """Does `new_source` dispute any of the `trusted` sources?

    One temperature-0 call; parse-retry once; NEVER raises — a failed check
    returns no conflicts rather than failing the ingestion it rides on.
    """
    candidates = [t for t in trusted if t.get("raw_text") and t["id"] != new_source["id"]]
    if not candidates:
        return []
    valid_ids = {t["id"] for t in candidates}
    user_payload = {
        "new_source": {"title": new_source["title"], "text": new_source.get("raw_text", "")},
        "trusted_sources": [
            {"id": t["id"], "title": t["title"], "text": t["raw_text"]} for t in candidates
        ],
    }
    messages = [
        {"role": "system", "content": CONFLICT_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]
    for attempt in (1, 2):  # retry once on parse failure per spec
        try:
            raw = await chat(messages, temperature=0.0, max_tokens=500)
            return _parse_conflicts(raw, valid_ids)
        except Exception as exc:
            print(f"  [conflicts] attempt {attempt} failed: {type(exc).__name__}: {exc}")
    return []
