# Phase 7 — Publish Idempotency

Adds a durable publish ledger on the same SQLite/WAL store.

## Safety
- One logical key per `(target, article_id)`.
- A completed publish is never sent again.
- A second worker seeing `publishing` will not issue another remote request.
- Failed attempts remain retryable.
- Remote IDs are retained when the adapter returns one.

## Migration
Existing Blogger/News/Sports adapters should be wrapped with `IdempotentPublisher` one target at a time. No legacy secret names are changed.

Important: a provider that supports an idempotency key should receive the generated key. For providers without native idempotency, the ledger still prevents duplicates within this application, while reconciliation by remote ID/search should be added before retrying ambiguous network failures.
