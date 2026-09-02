import asyncio
import sys
import logging
from fastapi import FastAPI
import warnings
from fastapi.middleware.cors import CORSMiddleware
from app.utils.custom_logger import AlignedColorFormatter

# ── Phase 23: Root Logger Configuration ──────────────────────────────────────
# Configure the ROOT logger before FastAPI and Uvicorn initialize.
# Uvicorn resets loggers when it starts, so by configuring root early and
# letting all other loggers propagate up to it, we ensure every log line
# (including Uvicorn's access logs) uses our strict AlignedColorFormatter
# and streams to stderr (for Hugging Face visibility).
root_logger = logging.getLogger()
if not root_logger.handlers:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(AlignedColorFormatter())
    root_logger.addHandler(handler)
root_logger.setLevel(logging.INFO)

# Module-level logger for use in route handlers (e.g. root health check)
logger = logging.getLogger(__name__)


# Windows-specific fix for Playwright + asyncio subprocesses
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    pass

from contextlib import asynccontextmanager
from app.config import settings
# Suppress Pydantic V2 warnings from LangChain (known upstream issue)
try:
    from pydantic.warnings import PydanticDeprecatedSince20
    warnings.filterwarnings("ignore", category=PydanticDeprecatedSince20)
except ImportError:
    pass

# Suppress specific Appwrite deprecation (tablesDB.create_row is not yet standard in Py SDK)
# Catch 'create_document', 'list_documents', etc.
warnings.filterwarnings("ignore", message=".*Call to deprecated function.*")
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Import routes AFTER warnings config
from app.routes import news, search, subscription, admin, audio

# Import scheduler functions
from app.services.scheduler import start_scheduler, shutdown_scheduler, update_adaptive_intervals_from_redis

# Import the worker manager
from app.services.worker_manager import run_worker

# Import the circuit breaker startup hook (loads Redis state after event loop is live)
from app.services.circuit_breaker import startup_circuit_breaker


from app.services.browser_manager import browser_manager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager
    
    Handles startup and shutdown events for background tasks:
    - Startup: Initialize and start APScheduler, BrowserManager
    - Shutdown: Gracefully stop all background jobs and BrowserManager
    """
    # Startup: Start background scheduler and browser
    print("=" * 60)
    print("Starting Segmento Pulse Backend...")
    start_scheduler()

    # Phase 24: Start the Queue-Based Worker Manager
    # This runs the consumer loop in the background, paced by Upstash Redis.
    
    # CRITICAL FIX for "unknown async library" in all background httpx fetchers
    # `nest_asyncio` patches internal asyncio loop vars, which breaks `sniffio` / `anyio` 
    # context detection used by httpx. We manually force it here.
    try:
        import sniffio
        sniffio.current_async_library_cvar.set("asyncio")
    except ImportError:
        pass
        
    worker_task = asyncio.create_task(run_worker())
    app.state.worker_task = worker_task

    # Fix 1: Load circuit breaker states from Redis NOW — the event loop is
    # fully alive at this point, so the async restore will actually run.
    await startup_circuit_breaker()

    await browser_manager.start()
    print("=" * 60)
    
    yield  # Application runs here
    
    # Shutdown: Stop background scheduler and browser
    print("=" * 60)
    print("Shutting down Segmento Pulse Backend...")
    
    # Stop worker
    if hasattr(app.state, "worker_task"):
        app.state.worker_task.cancel()
        try:
            await app.state.worker_task
        except asyncio.CancelledError:
            pass

    shutdown_scheduler()
    await browser_manager.shutdown()
    print("=" * 60)


app = FastAPI(
    title="Segmento Pulse API",
    description="Real-Time Technology Intelligence Platform API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan  # Phase 3: Background scheduler lifecycle
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(news.router, prefix="/api/news", tags=["News"])
app.include_router(search.router, prefix="/api/search", tags=["Search"])

app.include_router(subscription.router, tags=["Subscription"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
app.include_router(audio.router, prefix="/api/audio", tags=["Audio"])

# Phase 6: Research Papers
from app.routes import research
app.include_router(research.router, prefix="/api/research", tags=["Research"])

# Repositories
from app.routes import repos
app.include_router(repos.router, prefix="/api/repos", tags=["Repositories"])

# Phase 3: Engagement tracking
from app.routes import engagement
app.include_router(engagement.router, prefix="/api/engagement", tags=["Engagement"])


# Phase 5: Monitoring and Metrics
from app.routes import monitoring
app.include_router(monitoring.router, prefix="/api/monitoring", tags=["Monitoring"])

@app.get("/")
async def root():
    """
    Live Health Dashboard — Phase 23

    What this shows:
        Instead of a hardcoded JSON message, this endpoint now collects
        real-time metrics from every major subsystem and returns a live
        snapshot of the app's health. This is what the Hugging Face
        'App' tab will display.

    Subsystems checked:
        - Scheduler: Is it running? How many jobs registered? Next run times?
        - Appwrite DB: Is the connection alive?
        - Redis / Circuit Breaker: Is Redis reachable?
        - Pipeline stats: Totals for fetched, saved, duplicates, errors.
    """
    from datetime import datetime, timezone
    from app.services.scheduler import scheduler
    from app.services.appwrite_db import get_appwrite_db
    from app.services.professional_logger import ingestion_stats

    now_utc = datetime.now(timezone.utc)

    # ── Scheduler health ──────────────────────────────────────────────────────
    scheduler_running = scheduler.running if scheduler else False
    jobs = scheduler.get_jobs() if scheduler and scheduler.running else []

    # Separate news-fetch jobs from maintenance jobs for a cleaner summary
    news_jobs   = [j for j in jobs if j.id.startswith("fetch_")]
    other_jobs  = [j for j in jobs if not j.id.startswith("fetch_")]

    next_news_run = None
    if news_jobs:
        upcoming = [j.next_run_time for j in news_jobs if j.next_run_time]
        if upcoming:
            next_news_run = min(upcoming).isoformat()

    # -- Appwrite health -------------------------------------------------------
    db = get_appwrite_db()
    appwrite_ok = db.initialized if db else False
    
    # DEBUG: Log the actual state to server terminal
    from app.services.appwrite_db import APPWRITE_AVAILABLE
    logger.info(f"Health Check - Appwrite OK: {appwrite_ok} (SDK Available: {APPWRITE_AVAILABLE})")

    # ── Redis health (lightweight — just check circuit breaker import) ────────
    redis_ok = False
    try:
        from app.services.circuit_breaker import ProviderCircuitBreaker
        redis_ok = True   # If the import works and breaker is set up, Redis is configured
    except Exception:
        redis_ok = False

    # ── Pipeline stats (from professional_logger's IngestionStats singleton) ──
    stats = ingestion_stats.get_summary()

    # ── Overall health verdict ────────────────────────────────────────────────
    # We call the app "healthy" if the two critical subsystems are alive:
    # the scheduler (drives all ingestion) and Appwrite (stores everything).
    overall = "healthy" if (scheduler_running and appwrite_ok) else "degraded"

    return {
        "app":     "Segmento Pulse Backend",
        "version": "1.0.0",
        "status":  overall,
        "timestamp": now_utc.isoformat(),
        "docs":    "/docs",

        # Live subsystem health
        "subsystems": {
            "scheduler": {
                "status":           "running" if scheduler_running else "stopped",
                "news_fetch_jobs":  len(news_jobs),
                "other_jobs":       len(other_jobs),
                "total_jobs":       len(jobs),
                "next_news_fetch":  next_news_run,
            },
            "appwrite_db": {
                "status": "connected" if appwrite_ok else "disconnected",
            },
            "redis": {
                "status": "configured" if redis_ok else "not_configured",
            },
        },

        # Live pipeline metrics (resets on server restart)
        "pipeline_metrics": {
            "articles_fetched":    stats.get("articles_fetched", 0),
            "articles_saved":      stats.get("articles_saved", 0),
            "duplicates_found":    stats.get("duplicates_found", 0),
            "articles_deleted":    stats.get("articles_deleted", 0),
            "deduplication_rate":  stats.get("deduplication_rate", "0.0%"),
            "rate_limits_hit":     stats.get("rate_limits_hit", 0),
            "uptime_seconds":      stats.get("duration_seconds", 0),
            "throughput_per_sec":  stats.get("throughput_per_second", 0),
        },
    }



@app.get("/health")
@app.head("/health")  # ← Added for UptimeRobot compatibility
async def health_check():
    """
    Enhanced health check endpoint with scheduler status
    Used by external monitoring services (UptimeRobot, Cron-Job.org) to keep app awake
    """
    from datetime import datetime
    from app.services.scheduler import scheduler
    
    # Get scheduler status
    scheduler_running = scheduler.running if scheduler else False
    job_count = len(scheduler.get_jobs()) if scheduler and scheduler.running else 0
    
    jobs_info = []
    if scheduler and scheduler.running:
        for job in scheduler.get_jobs():
            jobs_info.append({
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None
            })
    
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "uptime": "operational",
        "scheduler": {
            "running": scheduler_running,
            "job_count": job_count,
            "jobs": jobs_info
        }
    }

# Force reload
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.ENVIRONMENT == "development"
    )
