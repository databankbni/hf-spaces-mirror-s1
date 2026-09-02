# P29 Phase 17 Changelog

## Runtime / Reliability
- Added `attempt_started_at` to `publish_ledger` with additive migration.
- Added stale publish lease recovery before each publish.
- Preserved the same `(target, article_id)` idempotency key across recovery.
- Added queue job listing and dead-letter requeue primitives.
- Added safe operational queue snapshots without payload exposure.
- Persisted global Auto-Repair enable/disable state.

## Control Bot
Existing section callbacks remain available. New additive callbacks:
- `{section}:metrics`
- `{section}:health`
- `{section}:dead`

These are generated for News, Sports and Blogger using the same section-control contract.

## Security
- Dead-letter requeue requires admin approval at the runtime API.
- Operational queue views omit article payloads.
- Audit logging continues through the existing redaction layer.
- Secret names remain unchanged.

## Verification
- `python3 -m compileall -q .` — PASS
- Phase 16 + Phase 17 + runtime/core compatibility tests — PASS
- Legacy non-Telegram test subset — PASS
- Full pytest collection remains blocked by missing `pyrogram` in the execution environment; affected tests are Telegram/Blogger UI-dependent.
- `python3 v29_app.py` — PASS; discovered `blogger, news, sports`.
