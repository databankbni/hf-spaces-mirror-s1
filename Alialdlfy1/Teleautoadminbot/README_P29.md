# P29 Foundation

This package is a safe, incremental refactor of the P28 automatic publishing bot.

### Start foundation check
`python v29_app.py`

### Generate a Fernet master key
`python scripts_generate_secret_key.py`

Set it as `P29_SECRET_MASTER_KEY` before using `core.secrets.SecretManager`.

### Run new foundation tests
`pytest -q tests/v29`

The legacy runtime is intentionally retained during migration so the refactor can be introduced service-by-service instead of risking a big-bang failure.

## Phase 17 — Operational Resilience
- Durable publish leases with stale-operation recovery.
- Dead-letter queue inspection/requeue with admin approval.
- Persistent global Auto-Repair control state.
- Section health/metrics/dead-letter control callbacks added additively.
- No legacy secret names or callback namespaces were renamed.
