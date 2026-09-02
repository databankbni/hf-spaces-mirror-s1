# Phase 15 — Runtime Integration

## Runtime order

`article -> blocked words -> duplicate/fingerprint -> deterministic cleanup -> durable queue -> AI Gateway -> validation -> Publisher -> Idempotency -> Health`

The gate runs before queue/AI/API use. Blocked or duplicate content is rejected without AI calls.

## Integrated components

- `core/runtime/integration.py`: phase-15 composition/orchestration root.
- News, Sports and Blogger use the same runtime contract with isolated section state.
- Persistent P29 job table (`p29_jobs`) with schema metadata and migration from the two older `jobs` schemas.
- AI Provider Pool rotates `GEMINI_KEY_N`, `GROQ_KEY_N`, `OPENROUTER_KEY_N` without renaming legacy secrets.
- Per-key token-bucket rate limits, cooldown and bounded retry/backoff.
- HTTP adapters for Gemini, Groq and OpenRouter.
- Post-AI validation reuses the same blocked-word and duplicate protection.
- Publisher remains idempotent through the durable publish ledger.
- Health monitoring is registered per section/provider.
- Auto-repair can be triggered by unhealthy services through the existing guarded sandbox/rollback policy; sensitive changes still require admin approval.
- Audit and metrics are exposed through the runtime control snapshot.
- Control Bot adds additive `news:*`, `sports:*`, and `blogger:*` callbacks while legacy callbacks remain unchanged.
- Plugin discovery remains the extension point for future sections.

## Compatibility

Existing secret names are unchanged. Existing legacy Blogger modules and callbacks remain available. The phase-15 job store uses a namespaced table so incompatible historical `jobs` schemas do not break startup; queued legacy rows are copied forward when their schema is recognized.

## Verification

Phase-15 tests cover:
- blocked content before queue/AI
- persistent duplicate rejection
- one structured AI package request
- provider/key failover
- idempotent publish
- stale-worker recovery
- legacy job schema migration
- section isolation/control parity
