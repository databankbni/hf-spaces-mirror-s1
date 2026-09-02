# P29 Phase 4 — AI Provider Pool

This phase adds a provider/key scheduler without renaming legacy secrets.

## Supported legacy names

- `GEMINI_KEY_1 ... GEMINI_KEY_N`
- `GROQ_KEY_1 ... GROQ_KEY_N`
- `OPENROUTER_KEY_1 ... OPENROUTER_KEY_N`

Any numbered key already present is discovered automatically.

## Selection policy

1. Ignore empty/unavailable keys.
2. Prefer the least-used key.
3. Break ties with least-recently-used.
4. Put failed/rate-limited keys into cooldown.
5. A future provider adapter can call `report_success()` / `report_failure()`.

## Important

This phase deliberately does not hard-wire provider HTTP SDKs into the pool. The existing provider clients remain responsible for making requests. The pool only decides which credential should be used, so migration is low-risk.

The next integration step is to route every real AI request through this pool and add persistent usage/quota state.
