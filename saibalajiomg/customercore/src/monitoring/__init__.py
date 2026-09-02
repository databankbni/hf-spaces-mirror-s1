"""
CustomerCore Monitoring Package — Phase 11

Provides:
  - Langfuse LLM observability (traces every LLM call end-to-end)
  - Constitutional Policy Engine (AI safety guardrails on every output)
  - Unified tracing context (works with or without Langfuse keys)

All Langfuse calls degrade gracefully to no-ops when LANGFUSE_PUBLIC_KEY
is not set — tests and local development work without a Langfuse account.
"""
