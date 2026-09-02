"""FastAPI application for the template-agnostic v2 backend."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.domain import template_discoverer
from backend.pii import scrubber as pii_scrubber
from backend.rag.store import get_rag_store
from backend.rag.types import TIER_MASTER, TIER_REFERENCE
from backend.startup import run_startup_ingest
from backend.standard_paragraphs.routes import router as standard_paragraphs_router
from backend.utils.runtime_paths import ensure_data_drive_runtime_dirs

ensure_data_drive_runtime_dirs()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

_STARTUP_SUMMARY: dict = {}
_PII_SCAN_PATHS = {"/api/report/generate", "/api/report/preview"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _STARTUP_SUMMARY

    # Warm jina-reranker-v3 FIRST, before startup ingest touches the embedder, so
    # the host-RAM weight load happens before the embedder + ingest stack up their
    # own allocations. Off by default (reference_cross_encoder_warmup); the lazy
    # path loads it on the first reference mapping otherwise.
    # Non-fatal: degrades to multi-signal on failure or under the RAM guard.
    try:
        from backend.llm.reranker import warmup_cross_encoder

        if warmup_cross_encoder():
            logger.info("jina-reranker-v3 warmed at startup.")
    except Exception:  # noqa: BLE001 - warmup must never block startup
        logger.warning("jina-reranker-v3 warmup skipped (non-fatal).", exc_info=True)

    _STARTUP_SUMMARY = run_startup_ingest()
    from backend.storage import document_library

    recovered = document_library.recover_all_tenants_stale_processing()
    if recovered:
        logger.info("Startup recovered %d stale processing document(s)", recovered)

    from backend.standard_paragraphs import jobs as sp_jobs
    from backend.storage import tenant_store as ts

    sp_recovered = sp_jobs.recover_stale_jobs(settings.default_tenant_id)
    if sp_recovered:
        logger.info(
            "Startup recovered %d stale standard-paragraph job(s)", sp_recovered
        )
    # Ensure migration runs even when faiss_dir is not touched yet.
    ts.migrate_legacy_master_faiss_dir(settings.default_tenant_id)

    yield


app = FastAPI(
    title="RICS Template-Agnostic Backend (v2)", version="2.0.0", lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def pii_request_middleware(request: Request, call_next):
    """Log PII in inbound notes for awareness (notes are not scrubbed; RAG docs are)."""
    if request.method == "POST" and request.url.path in _PII_SCAN_PATHS:
        body = await request.body()

        async def _receive():
            return {"type": "http.request", "body": body, "more_body": False}

        request._receive = _receive  # re-inject consumed body
        try:
            raw_notes = json.loads(body or b"{}").get("raw_notes", "")
            audit = pii_scrubber.detect_pii(raw_notes)
            flagged = {k: v for k, v in audit.items() if k in ("EMAIL", "POSTCODE")}
            if flagged:
                logger.warning(
                    "Inbound notes contain PII (notes kept verbatim; scrub RAG uploads only): %s",
                    flagged,
                )
        except Exception:  # noqa: BLE001
            pass
    response = await call_next(request)
    return response


# Routers
from backend.api.routes import (  # noqa: E402
    admin,
    auth,
    legacy_api_routes,
    photos,
    report,
    schema,
    upload,
)

app.include_router(auth.router)
app.include_router(legacy_api_routes.router)
app.include_router(schema.router)
app.include_router(report.router)
app.include_router(photos.router)
app.include_router(upload.router)
app.include_router(standard_paragraphs_router)
if settings.master_template_upload_enabled:
    app.include_router(admin.router)


@app.get("/metrics/summary", tags=["observability"])
def metrics_summary(limit: int = 50) -> dict:
    """Aggregate recent per-report telemetry from the local metrics sink.

    Reads the JSONL records written under the metrics dir (no live state), so it
    is cheap and safe to poll. Returns token/cost totals, average grounding pass
    rate + retrieval confidence, status/violation breakdowns and per-label LLM
    call latency over the most-recent reports.
    """
    from backend.observability import tracing as observability

    return observability.recent_summary(limit=max(1, min(limit, 500)))


@app.get("/health", tags=["health"])
def health() -> dict:
    tenant = settings.default_tenant_id
    loaded = template_discoverer.load_schema(tenant) is not None
    store = get_rag_store()
    master_faiss_count = store.count(tenant, TIER_MASTER)
    reference_faiss_count = store.count(tenant, TIER_REFERENCE)
    # Schema readiness is independent of standard-paragraph memory size.
    master_ready = True
    from backend.llm.embeddings import get_embedder

    try:
        emb = get_embedder()
        embedder_name = type(emb).__name__
        embed_dim = int(getattr(emb, "embed_dim", 0))
        embedder_ok = True
        embedder_error = None
    except Exception as exc:  # noqa: BLE001 - surface load failure in health
        embedder_name = None
        embed_dim = 0
        embedder_ok = False
        embedder_error = str(exc)
    return {
        "status": "ok" if loaded and master_ready and embedder_ok else "degraded",
        "embedder": embedder_name,
        "embed_dim": embed_dim,
        "embedder_ok": embedder_ok,
        "embedder_error": embedder_error,
        "master_loaded": loaded,
        "master_faiss_count": master_faiss_count,
        "standard_paragraphs_faiss_count": master_faiss_count,
        "reference_faiss_count": reference_faiss_count,
        "reference_ready": reference_faiss_count > 0
        or (
            not settings.ingest_embed_enabled
            and store.count_chunks_only(tenant, TIER_REFERENCE) > 0
        ),
        "ingest_embed_enabled": bool(settings.ingest_embed_enabled),
        "reference_chunk_only_count": store.count_chunks_only(tenant, TIER_REFERENCE),
        "startup": _STARTUP_SUMMARY,
        "admin_override_enabled": settings.master_template_upload_enabled,
        "ui_path": "/",
    }


if _FRONTEND_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_FRONTEND_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    def root_ui() -> FileResponse:
        index = _FRONTEND_DIR / "index.html"
        if index.is_file():
            return FileResponse(index)
        return FileResponse(_FRONTEND_DIR / "v2.html")

    @app.get("/v2.html", include_in_schema=False)
    def v2_ui() -> FileResponse:
        return FileResponse(_FRONTEND_DIR / "v2.html")

    @app.get("/index.html", include_in_schema=False)
    def legacy_index() -> FileResponse:
        return FileResponse(_FRONTEND_DIR / "index.html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        path = _FRONTEND_DIR / "favicon.ico"
        if path.is_file():
            return FileResponse(path)
        return FileResponse(_FRONTEND_DIR / "v2.html")
