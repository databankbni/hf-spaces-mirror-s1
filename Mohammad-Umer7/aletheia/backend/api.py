"""Aletheia's FastAPI backend — the only thing the frontend ever talks to.

Long operations (ingest, seed, post-retraction re-enrichment) run as background
tasks; the frontend polls GET /api/sources for status. Run with:

    uvicorn backend.api:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import os
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend import changelog, llm_direct, memory, sources

app = FastAPI(title="Aletheia", description="An AI research assistant that can change its mind.")

sources.backfill_raw_text()  # older registries predate raw_text (conflict detection needs it)

# Dev origins always allowed; ALLOWED_ORIGINS (comma-separated) adds deployed
# ones (e.g. the Vercel frontend) without a code change per environment.
_extra_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", *_extra_origins],
    allow_origin_regex=r"https://.*\.vercel\.app",  # preview + prod Vercel deployments
    allow_methods=["*"],
    allow_headers=["*"],
)

# Single-process app: track fire-and-forget jobs so /api/status can report them
# and so exceptions never vanish silently.
_background_tasks: set[asyncio.Task] = set()


def _spawn(coro, label: str) -> None:
    task = asyncio.create_task(coro, name=label)
    _background_tasks.add(task)

    def _done(t: asyncio.Task) -> None:
        _background_tasks.discard(t)
        if not t.cancelled() and t.exception():
            print(f"[background:{label}] failed: {t.exception()!r}")

    task.add_done_callback(_done)


class AddSourceBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    kind: Literal["study", "news", "retraction", "meta-analysis", "note"] = "note"
    text: Optional[str] = Field(default=None, max_length=20000)
    url: Optional[str] = None


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class RetractBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


@app.get("/api/status")
async def status():
    return {
        "sources": len(sources.list_sources()),
        "busy": sorted(t.get_name() for t in _background_tasks),
    }


@app.post("/api/sources", status_code=202)
async def add_source(body: AddSourceBody):
    content = body.text or body.url
    if not content:
        raise HTTPException(422, "provide 'text' or 'url'")
    source_id = sources._slugify(body.title)
    if sources.get_source(source_id):
        raise HTTPException(409, f"source '{source_id}' already exists")

    async def _ingest():
        await sources.ingest_source(body.title, body.kind, content, source_id=source_id)

    _spawn(_ingest(), f"ingest:{source_id}")
    return {"source_id": source_id, "status": "ingesting"}


@app.get("/api/sources")
async def get_sources():
    return {"sources": sources.list_sources()}


@app.post("/api/ask")
async def ask(body: AskBody):
    # Memory-grounded answer and the no-memory baseline run concurrently, so the
    # compare toggle costs no extra latency. The baseline is best-effort (None on
    # failure) — it must never break the real answer.
    result, stateless = await asyncio.gather(
        sources.ask(body.question),
        llm_direct.stateless_answer(body.question),
    )
    result["stateless_answer"] = stateless
    return result


@app.post("/api/sources/{source_id}/retract")
async def retract(source_id: str, body: RetractBody):
    source = sources.get_source(source_id)
    if source is None:
        raise HTTPException(404, f"unknown source '{source_id}'")
    if source["trust"] == "retracted":
        raise HTTPException(409, f"source '{source_id}' is already retracted")
    if source["status"] != "ready":
        raise HTTPException(409, f"source '{source_id}' is not ready (status={source['status']})")

    # forget + diff runs inline (fast — this response drives the death animation);
    # the improve() re-enrichment pass over surviving datasets runs in background.
    result = await sources.retract_source(source_id, body.reason, reenrich=False)
    _spawn(sources.reenrich_remaining(), f"reenrich:after:{source_id}")
    return result


@app.get("/api/graph")
async def graph():
    return await sources.graph_snapshot()


@app.get("/api/changelog")
async def get_changelog():
    return {"entries": changelog.read_entries(newest_first=True)}


@app.post("/api/demo/seed", status_code=202)
async def demo_seed():
    if any(t.get_name().startswith("seed") for t in _background_tasks):
        raise HTTPException(409, "seed already running")

    async def _seed():
        await sources.seed_demo(include_retraction=False)

    _spawn(_seed(), "seed:demo")
    return {"status": "seeding", "note": "3 sources; the retraction notice arrives separately"}


@app.post("/api/demo/ingest-retraction", status_code=202)
async def demo_ingest_retraction():
    spec = next(s for s in sources.SEED_SOURCES if s["id"] == "jch_retraction")
    if sources.get_source(spec["id"]):
        raise HTTPException(409, "retraction notice already ingested")

    async def _ingest():
        await sources.ingest_source(
            spec["title"], spec["kind"], spec["text"], source_id=spec["id"]
        )

    _spawn(_ingest(), f"ingest:{spec['id']}")
    return {"source_id": spec["id"], "status": "ingesting"}
