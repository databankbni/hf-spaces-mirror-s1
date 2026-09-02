# P29 Migration Plan

## What was changed now
- Added `core/` foundation: durable jobs, health registry, supervisor, dynamic secrets, plugin registry, event bus, provider failover, repair validation.
- Added `v29_app.py` as a composition root.
- Added foundation tests under `tests/v29/`.
- Fixed the confirmed scheduler reference bug (`db` -> `self.db`).
- Changed Blogger DB read failure from silent `{}` fallback to an explicit error so corruption cannot masquerade as an empty database.

## What is intentionally NOT changed yet
The existing Telegram/Blogger runtime remains in place. This is deliberate: a big-bang rewrite would create a larger outage risk.

## Next migration slices
1. Wrap existing AI manager/Gemini clients with `ProviderRouter`.
2. Move scheduler queue persistence to `JobStore` and add claim/lease/idempotency.
3. Put Blogger and Telegram operations behind adapters.
4. Migrate JSON state to SQLite through a compatibility repository.
5. Split `bot_core.py` by responsibility while preserving public functions.
6. Add crash/restart integration tests.
7. Enable AI auto-repair in proposal-only mode.
8. Enable automatic patch application only after sandbox + tests + rollback checks are green.

## Safety rule
No AI-generated patch is allowed to modify production directly. Production changes must have a backup, a validation result, and a rollback path.

## Phase 15 completed
- RuntimeIntegration is now the shared orchestration path for new section traffic.
- News/Sports/Blogger receive the same section control contract while legacy callbacks remain intact.
- AI provider adapters, per-key rate limiting, bounded retry/backoff, persistent queue migration, publisher idempotency, health hooks, metrics and audit are wired together.
