# PHASE 16 — Production Reliability & Control Plane

Phase 16 hardens the Phase-15 runtime for restarts and long-running operation without renaming legacy secrets or removing legacy callbacks.

## Changes
- Durable per-section runtime/control state in `p29_runtime_state` with additive schema versioning.
- Section settings survive process restart: enabled state, blocked words, duplicate protection, AI, Auto-Repair and source allowlist.
- Source allowlist is enforced before Queue/AI; empty source is rejected when an allowlist is configured.
- Duplicate protection toggle is now honored by the runtime gate.
- Worker lease heartbeat prevents long AI/publish jobs from being reclaimed while still running.
- Completion is worker-aware to reduce stale-worker races.
- Auto-Repair respects each section's `auto_repair_enabled` flag.
- Runtime state changes invalidate cached section gates/pipelines.
- Existing legacy secrets and callback namespaces remain unchanged.

## Verification
- `compileall` is required.
- Phase-15 and Phase-16 runtime tests cover persistence, source gating, duplicate toggle, worker heartbeat and section repair policy.
- Telegram-dependent legacy tests are reported separately when `pyrogram` is unavailable.
