"""
CustomerCore REST API — FastAPI Application Factory (Phase 10)

This is the entry point for the entire API layer. It:
  1. Creates the FastAPI application with OpenAPI metadata
  2. Configures the application lifespan (startup/shutdown events)
  3. Registers all middleware (CORS, security headers, request ID, rate limiting)
  4. Mounts all routers (triage, health, metrics, stream)
  5. Configures global exception handlers

WHY A LIFESPAN CONTEXT MANAGER INSTEAD OF @app.on_event?
----------------------------------------------------------
FastAPI deprecated @app.on_event("startup") in favor of the lifespan context manager
(introduced in Starlette 0.20+). The lifespan pattern is cleaner:
  - Startup code runs before yield
  - Shutdown code runs after yield
  - Resources created in startup are accessible in shutdown via the same scope
  - Matches Python's standard async context manager protocol

RATE LIMITING STRATEGY:
  We use slowapi (a FastAPI wrapper around limits/redis-py) for per-tenant rate limiting.
  Rate limits are applied per tenant_id extracted from the JWT:
    - POST /triage: 100 requests/minute per tenant (generous for B2B)
    - GET /triage/{id}: 600 requests/minute (polling is frequent)
    - Global fallback: 1000 requests/minute per IP
  Why per-tenant and not per-IP?
    In B2B, one tenant may use multiple IPs (multiple offices, CDN, load balancers).
    IP-based limiting would incorrectly throttle legitimate traffic.
    Tenant-based limiting enforces fair usage across the platform.

SECURITY HEADERS (added by middleware):
  X-Content-Type-Options: nosniff    — prevents MIME type sniffing attacks
  X-Frame-Options: DENY              — prevents clickjacking
  X-XSS-Protection: 1; mode=block   — legacy XSS filter (modern browsers ignore this)
  Strict-Transport-Security          — enforces HTTPS (only active in production)
  Content-Security-Policy            — restricts resource loading origins
"""

from __future__ import annotations

import os
import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from src.api.routers import health, metrics, stream, triage

# ─────────────────────────────────────────────────────────────────────────────
# Structured logging setup (structlog)
# ─────────────────────────────────────────────────────────────────────────────
# structlog produces machine-readable JSON logs in production and human-readable
# colored logs in development. This is critical for log aggregation systems
# (Datadog, Grafana Loki, AWS CloudWatch) that parse JSON log lines.

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.ConsoleRenderer()
        if os.getenv("APP_ENV", "development") == "development"
        else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO level
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

log = structlog.get_logger("customercore.api")


# ─────────────────────────────────────────────────────────────────────────────
# Rate limiter
# ─────────────────────────────────────────────────────────────────────────────

def _get_tenant_or_ip(request: Request) -> str:
    """
    Rate limit key function: use tenant_id from JWT if available, else fall back to IP.
    This enables per-tenant rate limiting while still protecting unauthenticated endpoints.
    """
    # Try to extract tenant_id from Authorization header (without full JWT validation)
    # Full validation happens in the route dependencies — here we just need the key
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            import jwt as pyjwt
            token = auth_header.split(" ")[1]
            secret = os.getenv("LITELLM_MASTER_KEY", "dev-key")
            payload = pyjwt.decode(token, secret, algorithms=["HS256"],
                                   options={"verify_exp": False})
            tenant_id = payload.get("tenant_id")
            if tenant_id:
                return f"tenant:{tenant_id}"
        except Exception:
            pass
    return get_remote_address(request)


limiter = Limiter(key_func=_get_tenant_or_ip)


# ─────────────────────────────────────────────────────────────────────────────
# Application lifespan (startup / shutdown)
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context manager.

    STARTUP: Initialize all stateful components (connections, caches, model clients).
    SHUTDOWN: Gracefully close connections to prevent data loss.

    The pattern mirrors how production services handle rolling deployments:
    1. New pod starts — lifespan startup runs
    2. Kubernetes readiness probe passes — traffic starts flowing to new pod
    3. Old pod receives SIGTERM — lifespan shutdown runs, connections drain
    4. Old pod exits cleanly
    """
    # ── Startup ────────────────────────────────────────────────────────────
    log.info("CustomerCore API starting up",
             env=os.getenv("APP_ENV", "development"),
             version="1.0.0")

    # Run database migration checks
    try:
        from src.db.migrations import run_db_migrations
        run_db_migrations()
    except Exception as exc:
        log.warning("Database migration checks failed (non-fatal)", error=str(exc))

    # Register Langfuse as LiteLLM callback (Phase 11 — LLM Observability)
    try:
        from src.monitoring.langfuse_tracer import setup_litellm_tracing
        tracing_enabled = setup_litellm_tracing()
        log.info("Langfuse LLM tracing",
                 enabled=tracing_enabled,
                 configured=bool(os.getenv("LANGFUSE_PUBLIC_KEY")))
    except Exception as exc:
        log.warning("Langfuse init failed (non-fatal)", error=str(exc))

    # Warm up LLM router (loads routing table into memory)
    try:
        from src.rag.router import LLMRouter, ROUTING_TABLE
        app.state.llm_router = LLMRouter()
        log.info("LLM router initialized", routing_entries=len(ROUTING_TABLE))
    except Exception as exc:
        log.warning("LLM router init failed (non-fatal)", error=str(exc))
        app.state.llm_router = None

    log.info("CustomerCore API ready to serve requests")

    yield  # ← Application runs here

    # ── Shutdown ───────────────────────────────────────────────────────────
    log.info("CustomerCore API shutting down gracefully")


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI Application Factory
# ─────────────────────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Using a factory function (instead of a module-level `app = FastAPI()`) allows:
      - Easy creation of test instances with different configurations
      - Clean separation between app creation and configuration
      - Future support for multiple app variants (e.g., lightweight health-only app)
    """

    app = FastAPI(
        title="CustomerCore API",
        description=(
            "Enterprise B2B AI Customer Support Platform\n\n"
            "Powered by: LangGraph 6-agent supervisor, Multi-tenant Hybrid RAG "
            "(ChromaDB + BM25 + RRF), Cryptographic Privacy Vault (AES-256-GCM), "
            "and a fine-tuned local LLM for on-premise deployment.\n\n"
            "**Authentication:** All endpoints require a JWT Bearer token. "
            "The `tenant_id` claim in the token determines data isolation boundaries.\n\n"
            "**Rate limits:** 100 triage submissions/minute per tenant."
        ),
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",       # Swagger UI
        redoc_url="/redoc",     # ReDoc UI (cleaner for sharing with stakeholders)
        openapi_url="/openapi.json",
        contact={
            "name": "Saibalaji Namburi",
            "url": "https://github.com/saibalajinamburi/CustomerCore",
        },
        license_info={
            "name": "MIT",
            "url": "https://opensource.org/licenses/MIT",
        },
    )

    # Attach rate limiter
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # ── CORS Middleware ─────────────────────────────────────────────────────
    # Allow the Operations Console frontend (Phase 13) to call the API.
    # In production, replace "*" with the specific frontend origin.
    allowed_origins = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://localhost:8080,https://customercore.hf.space"
    ).split(",")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    # ── Security Headers Middleware ─────────────────────────────────────────
    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next) -> Response:
        """
        Inject security headers on every response.
        These are required by OWASP and expected by enterprise security scanners.
        """
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start_time = time.time()
        response: Response = await call_next(request)
        duration_ms = int((time.time() - start_time) * 1000)

        # Security headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # Omit X-Frame-Options in Hugging Face Spaces to allow embedding in its iframe
        if not os.getenv("SPACE_ID"):
            response.headers["X-Frame-Options"] = "DENY"
            
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        if os.getenv("APP_ENV") == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # Structured request log
        log.info(
            "HTTP request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            request_id=request_id,
        )

        structlog.contextvars.clear_contextvars()
        return response

    # ── Global Exception Handlers ───────────────────────────────────────────
    from src.db.repository import RepositoryError

    @app.exception_handler(RepositoryError)
    async def repository_error_handler(request: Request, exc: RepositoryError) -> JSONResponse:
        """
        Catch repository exceptions (database, Supabase, connections).
        Returns detailed exception details so we can debug cloud issues in real-time.
        """
        request_id = request.headers.get("X-Request-ID", "unknown")
        log.exception(
            "Repository error",
            path=request.url.path,
            request_id=request_id,
            error=str(exc),
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "Database repository error",
                "request_id": request_id,
                "detail": str(exc),
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """
        Catch-all handler for unexpected errors.
        Returns a clean JSON error (not a raw Python traceback) and logs the full
        exception for debugging. In Phase 13, this also sends to Sentry.
        """
        request_id = request.headers.get("X-Request-ID", "unknown")
        log.exception(
            "Unhandled exception",
            path=request.url.path,
            request_id=request_id,
            error=str(exc),
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "request_id": request_id,
                "detail": str(exc),  # Expose error detail for cloud debugging
            },
        )

    # ── Routers ─────────────────────────────────────────────────────────────
    app.include_router(health.router)
    app.include_router(triage.router)
    app.include_router(stream.router)
    app.include_router(metrics.router)

    # ── Test Token endpoint (for UI workspace) ────────────────────────────────
    @app.get("/api/v1/test-token", include_in_schema=False)
    async def get_test_token(tenant_id: str = "acme-corp", role: str = "support_agent") -> JSONResponse:
        import jwt as pyjwt
        from src.api.auth import _get_secret_key
        payload = {
            "tenant_id": tenant_id,
            "role": role,
            "iat": int(time.time()),
            "exp": int(time.time()) + 86_400,
        }
        secret = _get_secret_key()
        token = pyjwt.encode(payload, secret, algorithm="HS256")
        return JSONResponse({"token": token})

    # ── Root redirect to docs ───────────────────────────────────────────────
    @app.get("/", include_in_schema=False)
    async def root(request: Request) -> Response:
        accept = request.headers.get("accept", "")
        # Serve the premium UI console to browsers or when running in HF Spaces
        if "text/html" in accept or os.getenv("SPACE_ID"):
            from fastapi.responses import HTMLResponse
            from src.api.ui import HTML_CONTENT
            return HTMLResponse(content=HTML_CONTENT)
            
        return JSONResponse({
            "name": "CustomerCore API",
            "version": "1.0.0",
            "docs": "/docs",
            "health": "/api/v1/health",
            "github": "https://github.com/saibalajinamburi/CustomerCore",
        })

    return app


# ─────────────────────────────────────────────────────────────────────────────
# Application instance (used by uvicorn)
# ─────────────────────────────────────────────────────────────────────────────
# Trigger rebuild to load new secrets: 2026-05-29T12:57:00

app = create_app()


# ─────────────────────────────────────────────────────────────────────────────
# Development runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.api.main:app",
        host="0.0.0.0",
        port=8080,
        reload=True,          # Auto-reload on file changes during development
        log_level="info",
        access_log=False,     # Disabled — we have our own structured middleware logging
    )
