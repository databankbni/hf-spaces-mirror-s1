"""
CustomerCore API — Health & Readiness Router (Phase 10)

WHY TWO SEPARATE ENDPOINTS?
------------------------------
Kubernetes distinguishes between two types of probes:

  /health (Liveness probe):
    "Is the process alive and not stuck in a deadlock?"
    Kubernetes restarts the pod if this returns non-200.
    Should be fast and simple — just return 200 if the process is running.
    Never check external services here — if Redis is down, we don't want Kubernetes
    to restart our pods in a loop (that makes the outage worse).

  /ready (Readiness probe):
    "Is the pod ready to receive traffic?"
    Kubernetes removes the pod from the load balancer if this returns non-200.
    SHOULD check external dependencies — if Redis or ChromaDB is unreachable,
    we tell Kubernetes to stop sending us traffic until they recover.
    This prevents cascading failures where pods accept requests they can't serve.

This distinction is called the "liveness vs readiness" pattern and is a standard
Kubernetes production practice.
"""

from __future__ import annotations

import os
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.api.models import HealthResponse

router = APIRouter(prefix="/api/v1", tags=["Health"])

# Track API start time for uptime reporting
_START_TIME = time.time()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness probe",
    description="Returns 200 if the API process is alive. Used by Kubernetes liveness probes. "
                "Does NOT check external service connectivity.",
)
async def health() -> HealthResponse:
    """
    Liveness probe — always returns 200 if the process is running.

    Kubernetes uses this to decide: "Should I restart this pod?"
    Answer: Only if the process itself is stuck/crashed, not if a dependency is down.
    """
    return HealthResponse(
        status="ok",
        version="1.0.0",
        services={},  # No external checks — intentionally empty for liveness
    )


@router.get(
    "/ready",
    summary="Readiness probe",
    description="Returns 200 if all dependencies are reachable. Used by Kubernetes readiness "
                "probes. Checks Redis, ChromaDB, and optionally Supabase connectivity.",
)
async def readiness() -> JSONResponse:
    """
    Readiness probe — checks all critical external dependencies.

    Kubernetes uses this to decide: "Should I send traffic to this pod?"
    If Redis is down, return 503 — let another pod handle the request.
    """
    service_status: dict[str, str] = {}
    overall_ok = True

    # ── Check Redis ──────────────────────────────────────────────────────────
    try:
        import redis as redis_lib  # type: ignore
        r = redis_lib.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379"),
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        r.ping()
        service_status["redis"] = "ok"
    except Exception as exc:
        service_status["redis"] = f"error: {exc}"
        overall_ok = False

    # ── Check ChromaDB ───────────────────────────────────────────────────────
    try:
        import chromadb  # type: ignore
        client = chromadb.HttpClient(
            host=os.getenv("CHROMADB_HOST", "localhost"),
            port=int(os.getenv("CHROMADB_PORT", "8000")),
        )
        client.heartbeat()
        service_status["chromadb"] = "ok"
    except Exception as exc:
        service_status["chromadb"] = f"error: {exc}"
        # ChromaDB is not critical for basic triage (BM25 fallback exists)
        # Don't mark overall as failed for ChromaDB — degraded mode is acceptable

    # ── Supabase (optional — only if configured) ─────────────────────────────
    supabase_url = os.getenv("SUPABASE_URL")
    if supabase_url:
        try:
            import httpx
            resp = httpx.get(f"{supabase_url}/rest/v1/", timeout=2.0)
            service_status["supabase"] = "ok" if resp.status_code < 500 else f"http_{resp.status_code}"
        except Exception as exc:
            service_status["supabase"] = f"error: {exc}"
            overall_ok = False
    else:
        service_status["supabase"] = "not_configured"

    uptime_seconds = int(time.time() - _START_TIME)

    body = {
        "status": "ok" if overall_ok else "degraded",
        "version": "1.0.0",
        "uptime_seconds": uptime_seconds,
        "services": service_status,
    }
    return JSONResponse(
        content=body,
        status_code=200 if overall_ok else 503,
    )


@router.post("/run-migrations", summary="Trigger database migrations")
async def trigger_migrations() -> JSONResponse:
    import os
    import traceback
    import urllib.parse
    logs = []
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "SUPABASE_DB_URL not set in env"}
        )

    if "://" in db_url and "@" in db_url:
        try:
            prefix, rest = db_url.split("://", 1)
            creds_part, host_part = rest.rsplit("@", 1)
            if ":" in creds_part:
                user, password = creds_part.split(":", 1)
                unquoted_password = urllib.parse.unquote(password)
                encoded_password = urllib.parse.quote_plus(unquoted_password)
                db_url = f"{prefix}://{user}:{encoded_password}@{host_part}"
        except Exception as parse_err:
            logs.append(f"Failed to pre-parse SUPABASE_DB_URL: {parse_err}")
        
    try:
        import psycopg2
        conn = psycopg2.connect(db_url, connect_timeout=5)
        conn.autocommit = True
        cursor = conn.cursor()
        
        cursor.execute("""
            ALTER TABLE tickets 
            ADD COLUMN IF NOT EXISTS customer_tier TEXT NOT NULL DEFAULT 'free' 
            CHECK (customer_tier IN ('free','starter','growth','enterprise','vip'));
        """)
        logs.append("Executed customer_tier migration")
        
        cursor.execute("""
            ALTER TABLE tickets 
            ADD COLUMN IF NOT EXISTS masked_text TEXT;
        """)
        logs.append("Executed masked_text migration")
        
        cursor.execute("SELECT pg_notify('pgrst', 'reload schema');")
        logs.append("Reloaded PostgREST schema cache")
        
        cursor.close()
        conn.close()
        return JSONResponse(
            status_code=200,
            content={"status": "success", "logs": logs}
        )
    except Exception as e:
        tb = traceback.format_exc()
        # Redact password if present in db_url for safety
        redacted_db_url = None
        if db_url:
            parts = db_url.split("@")
            if len(parts) > 1:
                redacted_db_url = "postgresql://***@" + parts[1]
            else:
                redacted_db_url = db_url[:15] + "..."
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": str(e),
                "traceback": tb,
                "db_url_redacted": redacted_db_url
            }
        )

@router.get("/keep-alive", summary="Keep-alive ping for Supabase and HF Spaces")
async def keep_alive() -> JSONResponse:
    """
    Lightweight endpoint to keep the database awake on the free tier.
    This executes a fast query on Supabase.
    """
    import os
    import httpx

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")

    if not supabase_url or not supabase_key:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Supabase credentials not configured."}
        )

    try:
        headers = {
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}"
        }
        # Requesting a limit=1 from tickets table is very fast and counts as activity
        resp = httpx.get(f"{supabase_url}/rest/v1/tickets?select=id&limit=1", headers=headers, timeout=5.0)
        
        if resp.status_code >= 400:
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": f"Supabase responded with {resp.status_code}"}
            )

        return JSONResponse(
            status_code=200,
            content={"status": "success", "message": "Keep-alive ping successful"}
        )
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(exc)}
        )
