# P29 Phase 5 — AI Gateway

All future AI calls should go through `core.ai.AIGateway`.

## What it adds

- Uses the existing Provider Pool.
- Preserves legacy secret names.
- Automatic key/provider failover.
- Rate-limit cooldown.
- Token usage accounting when provider responses expose usage.
- One structured `article_package()` request for title/body/summary/keywords/hashtags/SEO/category/slug.

## Migration rule

Do not rewrite the existing provider clients in one risky step. Register their HTTP/API functions as adapters, then migrate call sites one service at a time. This keeps the legacy bot operational during the transition.

## Token-minimization rule

Before invoking this gateway, the global content gate must reject blocked or duplicate articles. The gateway should only receive accepted content.
