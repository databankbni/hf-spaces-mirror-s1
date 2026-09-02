"""
Async job queue with rate-limited HF Inference API processing.

Processing flow:
  1. Product submitted → Layer 1 keyword check (instant, local)
  2. If Layer 1 passes → job queued for API analysis
  3. Worker processes one job at a time with rate limiting
  4. Layers 2-4 run sequentially per job (3 API calls per product)
  5. Rate limiter enforces 6s minimum between API calls

Rate limiting handles HF free tier constraints:
  - 10 requests/min max
  - 950 requests/day (safety margin under 1000 limit)
  - Exponential backoff on 429s
  - 20s timeout for cold starts
"""

import asyncio
import uuid
import time
import logging
from typing import Optional

from analyzer import run_api_layers, load_config
from hf_api_client import get_rate_limiter

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# In-memory job store
# ─────────────────────────────────────────────────────────────
jobs: dict = {}

# Queue initialized lazily inside get_queue()
_queue: Optional[asyncio.Queue] = None

# Worker state
_worker_running = False


def get_queue() -> asyncio.Queue:
    global _queue
    if _queue is None:
        _queue = asyncio.Queue()
    return _queue


# ─────────────────────────────────────────────────────────────
# Job status constants
# ─────────────────────────────────────────────────────────────
STATUS_QUEUED = "queued"
STATUS_LAYER1_PASSED = "layer1_passed"  # Layer 1 done, waiting for API
STATUS_PROCESSING = "processing"  # API layers running
STATUS_DONE = "done"
STATUS_FAILED = "failed"


def create_job(product: dict) -> str:
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "job_id": job_id,
        "status": STATUS_QUEUED,
        "product": product,
        "result": None,
        "error": None,
        "queued_at": time.time(),
        "started_at": None,
        "finished_at": None,
        "api_calls_used": 0,
    }
    return job_id


def get_job(job_id: str) -> Optional[dict]:
    return jobs.get(job_id)


def get_queue_position(job_id: str) -> int:
    queued_jobs = [
        jid for jid, j in jobs.items()
        if j["status"] in (STATUS_QUEUED, STATUS_LAYER1_PASSED)
    ]
    try:
        return queued_jobs.index(job_id) + 1
    except ValueError:
        return 0


# ─────────────────────────────────────────────────────────────
# Background worker — processes one job at a time
# ─────────────────────────────────────────────────────────────
async def worker():
    """Background worker that processes queued jobs with rate limiting."""
    global _worker_running
    _worker_running = True
    q = get_queue()

    logger.info("Worker started — waiting for jobs")

    while True:
        job_id = await q.get()
        job = jobs.get(job_id)

        if not job:
            q.task_done()
            continue

        try:
            job["status"] = STATUS_PROCESSING
            job["started_at"] = time.time()
            logger.info(f"Processing job {job_id[:8]}...")

            # Run API layers in executor (they do I/O with rate limiting)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                run_api_layers,
                job["product"],
            )

            job["result"] = result
            job["status"] = STATUS_DONE
            job["finished_at"] = time.time()

            elapsed = job["finished_at"] - job["started_at"]
            flagged = result.get("flagged", False)
            logger.info(
                f"Job {job_id[:8]} done in {elapsed:.1f}s — "
                f"{'FLAGGED' if flagged else 'passed'}"
            )

        except Exception as e:
            job["status"] = STATUS_FAILED
            job["error"] = str(e)
            job["finished_at"] = time.time()
            logger.error(f"Job {job_id[:8]} failed: {e}")

        finally:
            q.task_done()


# ─────────────────────────────────────────────────────────────
# Enqueue — runs Layer 1 locally, queues for API if passed
# ─────────────────────────────────────────────────────────────
async def enqueue_product(product: dict) -> dict:
    """
    Submit a product for analysis.

    Layer 1 (keyword matching) runs immediately and locally.
    If it passes, the job is queued for API-based analysis (Layers 2-4).

    Returns:
        {
            "job_id": str,
            "status": str,
            "layer1_result": dict,  # Layer 1 result (always available)
            "queue_position": int,  # Position in API queue (0 if Layer 1 flagged)
            "message": str,
        }
    """
    from analyzer import layer1_check

    config = load_config()
    name = str(product.get("name", ""))
    description = str(product.get("description", ""))
    category = str(product.get("category", ""))
    google_cat = str(product.get("google_product_category", ""))
    slug = str(product.get("slug", ""))
    text_blob = " ".join([name, description, category, google_cat, slug])

    # Layer 1: instant local keyword check
    l1_result = layer1_check(text_blob, config)

    if l1_result["flagged"]:
        # Layer 1 caught it — no need for API calls
        job_id = create_job(product)
        jobs[job_id]["status"] = STATUS_DONE
        jobs[job_id]["started_at"] = time.time()
        jobs[job_id]["finished_at"] = time.time()
        jobs[job_id]["result"] = {
            "flagged": True,
            "flag_type": "prohibited_terms",
            "severity": "high",
            "reason": f"Prohibited terms detected: {', '.join(l1_result['matched_terms'])}",
            "meta": {
                "terms": l1_result["matched_terms"],
                "categories": l1_result["matched_categories"],
                "layer_triggered": "layer1_text",
                "confidence": "high",
            },
        }

        return {
            "job_id": job_id,
            "status": STATUS_DONE,
            "layer1_result": l1_result,
            "queue_position": 0,
            "message": "Prohibited terms detected — no API analysis needed",
        }

    # Layer 1 passed — queue for API analysis
    job_id = create_job(product)
    jobs[job_id]["status"] = STATUS_LAYER1_PASSED
    await get_queue().put(job_id)

    position = get_queue_position(job_id)
    rate_status = get_rate_limiter().get_status()

    return {
        "job_id": job_id,
        "status": STATUS_LAYER1_PASSED,
        "layer1_result": l1_result,
        "queue_position": position,
        "message": (
            f"Layer 1 passed — queued for API analysis. "
            f"Position {position} in queue. "
            f"Estimated wait: {position * 2}–{position * 4} minutes "
            f"(rate-limited for HF free tier)."
        ),
        "rate_limit_status": rate_status,
    }


# ─────────────────────────────────────────────────────────────
# Cleanup completed jobs older than 1 hour
# ─────────────────────────────────────────────────────────────
def cleanup_old_jobs():
    cutoff = time.time() - 3600
    to_delete = [
        jid for jid, j in jobs.items()
        if j["status"] in (STATUS_DONE, STATUS_FAILED)
        and j.get("finished_at", 0) < cutoff
    ]
    for jid in to_delete:
        del jobs[jid]
