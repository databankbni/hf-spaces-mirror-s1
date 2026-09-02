import asyncio
import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from analyzer import analyze_product, load_config, normalize
from hf_api_client import get_rate_limiter
from queue_manager import (
    enqueue_product, get_job, get_queue_position,
    cleanup_old_jobs, worker,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate HF token early
    try:
        from hf_api_client import _get_token
        _get_token()
        logger.info("HF token validated")
    except Exception as e:
        logger.error(f"HF token issue: {e}")
        # Don't crash — let endpoints return errors gracefully

    # Start background worker
    task = asyncio.create_task(worker())
    logger.info("Background worker started")
    yield
    # Graceful shutdown
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Product Analyzer",
    description="Multi-layer content moderation using HF Inference API (free tier)",
    version="2.0.0",
    lifespan=lifespan,
)


class ProductPayload(BaseModel):
    product_id: str
    shop_id: str
    name: str
    description: Optional[str] = ""
    category: Optional[str] = ""
    google_product_category: Optional[str] = ""
    slug: Optional[str] = ""
    image_urls: Optional[list] = []


# ── Health & Root ─────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "service": "product-analyzer", "version": "2.0.0"}


@app.get("/health")
def health():
    rate_status = get_rate_limiter().get_status()
    return {
        "status": "ok",
        "service": "product-analyzer",
        "api_daily_remaining": rate_status["daily_remaining"],
        "api_per_minute_remaining": (
            rate_status["per_minute_limit"] - rate_status["per_minute_count"]
        ),
    }


# ── Analysis Endpoints ────────────────────────────────────────────────────────

@app.post("/analyze")
async def analyze(payload: ProductPayload):
    """
    Submit a product for analysis.

    Layer 1 (keyword matching) runs instantly.
    If it passes, product is queued for API-based analysis (Layers 2-4).
    Check status with GET /job/{job_id}.
    """
    result = await enqueue_product(payload.model_dump())
    return JSONResponse(content=result)


@app.get("/job/{job_id}")
def job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JSONResponse(content={
        "job_id": job_id,
        "status": job["status"],
        "result": job["result"],
        "error": job["error"],
        "queued_at": job["queued_at"],
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
    })


@app.get("/queue/stats")
def queue_stats():
    from queue_manager import jobs, STATUS_QUEUED, STATUS_LAYER1_PASSED
    from queue_manager import STATUS_PROCESSING, STATUS_DONE, STATUS_FAILED

    cleanup_old_jobs()
    rate_status = get_rate_limiter().get_status()

    return JSONResponse(content={
        "total_jobs": len(jobs),
        "queued": sum(1 for j in jobs.values() if j["status"] == STATUS_QUEUED),
        "layer1_passed": sum(
            1 for j in jobs.values() if j["status"] == STATUS_LAYER1_PASSED
        ),
        "processing": sum(
            1 for j in jobs.values() if j["status"] == STATUS_PROCESSING
        ),
        "done": sum(1 for j in jobs.values() if j["status"] == STATUS_DONE),
        "failed": sum(1 for j in jobs.values() if j["status"] == STATUS_FAILED),
        "rate_limits": rate_status,
    })


# ── Test Endpoints ────────────────────────────────────────────────────────────

@app.get("/test")
async def test_layer1():
    """Test Layer 1 keyword detection — should flag instantly (no API calls)."""
    sample = {
        "product_id": "test-001",
        "shop_id": "shop-001",
        "name": "Happy Ending Massage Service",
        "description": "Full service massage with happy ending included",
        "category": "wellness",
        "google_product_category": "",
        "slug": "happy-ending-massage",
        "image_urls": [],
    }
    result = await enqueue_product(sample)
    return JSONResponse(content={"input": sample, "result": result})


@app.get("/test-clean")
async def test_clean():
    """Test a clean product — should pass Layer 1 and queue for API."""
    sample = {
        "product_id": "test-002",
        "shop_id": "shop-001",
        "name": "Men Casual Sports Shoes",
        "description": "Comfortable everyday sneakers for men",
        "category": "footwear",
        "google_product_category": "",
        "slug": "men-casual-sports-shoes",
        "image_urls": [],
    }
    result = await enqueue_product(sample)
    return JSONResponse(content={"input": sample, "result": result})


@app.get("/test-api")
async def test_api_layer2():
    """Test Layer 2 NSFW text classifier via HF Inference API (takes ~10-30s)."""
    from hf_api_client import classify_text_nsfw
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        classify_text_nsfw,
        "This is a normal product description for running shoes",
    )
    return JSONResponse(content={"result": result})


@app.get("/test-api-image")
async def test_api_layer4():
    """Test Layer 4 NSFW image classifier via HF Inference API (takes ~10-30s)."""
    from hf_api_client import classify_image_nsfw
    loop = asyncio.get_event_loop()
    # Test with a simple placeholder
    result = await loop.run_in_executor(
        None,
        classify_image_nsfw,
        b"fake-image-bytes",
    )
    return JSONResponse(content={"result": result})


@app.get("/debug")
def debug():
    config = load_config()
    leet_map = config.get("leet_map", {})
    test_cases = ["p.o.r.n", "p-o-r-n", "happy ending", "s.e.x"]
    results = {}
    for t in test_cases:
        results[t] = normalize(t, leet_map)
    return JSONResponse(content={"normalization_tests": results})


@app.get("/rate-limit-status")
def rate_limit_status():
    """Check current API rate limit status."""
    return JSONResponse(content=get_rate_limiter().get_status())
