"""
CustomerCore REST API — Phase 10

This package exposes the full CustomerCore AI platform as a production-grade
FastAPI REST API. It serves as the HTTP surface for:
  - External ticket submission (from Slack, email, webhook, or direct HTTP)
  - LangGraph multi-agent triage invocation
  - HITL (Human-in-the-Loop) review and resume operations
  - Prometheus metrics export
  - SSE real-time streaming of triage progress
  - Health and readiness probes for Kubernetes

Architecture:
  src/api/
    main.py         — FastAPI app factory, lifespan, middleware, router mounting
    auth.py         — JWT validation, tenant_id extraction, RBAC
    rate_limit.py   — Redis-backed per-tenant rate limiting (slowapi)
    models.py       — Pydantic request/response schemas for the API layer
    routers/
      triage.py     — POST /triage, GET /triage/{id}, POST /triage/{id}/resume
      health.py     — GET /health, GET /ready
      metrics.py    — GET /metrics (Prometheus format)
      stream.py     — GET /triage/{id}/stream (Server-Sent Events)
    middleware/
      logging.py    — Structured JSON request logging (structlog)
      security.py   — Security headers, CORS, request ID injection
"""
