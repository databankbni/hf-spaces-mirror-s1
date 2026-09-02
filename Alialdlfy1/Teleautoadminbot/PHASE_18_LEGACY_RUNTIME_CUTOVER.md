# PHASE 18 — Full Legacy Runtime Migration & Production Cutover

Phase 18 turns the previously parallel legacy/new architecture into a controlled compatibility cutover.

## Runtime path

Telegram/legacy source -> legacy compatibility bridge -> RuntimeIntegration -> ContentGate -> persistent queue -> AI Gateway -> validation -> IdempotentPublisher -> legacy external target -> Health/Audit/Metrics.

## Compatibility

- Existing `BloggerPublisher`, `ArticleProcessor`, scheduler and UI APIs remain available.
- Legacy `enqueue_raw_post()` now routes automatic Blogger ingestion into the durable P29 runtime when a runtime is supplied by `BloggerPublisher`.
- Legacy direct/manual processing remains available for callers that construct `ArticleProcessor` without a runtime.
- Existing secret names are untouched.
- Existing callback modules remain untouched.

## Cutover safety

The bridge never bypasses the ContentGate. A rejected/duplicate item is stopped before the durable queue and therefore before AI/API consumption. Publisher idempotency remains owned by the core ledger.

## Recovery

The runtime worker uses the Phase 17 job lease/heartbeat/recovery path. The external Blogger client remains the legacy-compatible publishing adapter, so remote publishing semantics are not duplicated.
