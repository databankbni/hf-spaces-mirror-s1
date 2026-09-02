# P29 Stage 3 — Content Gate + AI Batch Processing

## Added
- Global `ContentGate` shared by all future sections.
- Blocked-word check before fingerprint/AI/API work.
- Global + per-channel blocked-word compatibility with existing database/UI names.
- Duplicate gate before AI.
- SHA-256 normalized fingerprints for new pipeline records.
- Post-AI blocked-word and duplicate gate.
- Single AI article-package request for Blogger instead of separate rewrite/extract/summary/metadata/keyword/hashtag/alt calls.

## Compatibility
- Existing blocked-word database methods are reused; no existing secret names changed.
- Existing Blogger pending queue and legacy processor remain available.
- New pipeline is additive and can be adopted by News/Sports/future plugins.

## Safety
- A blocked or duplicate article is discarded before any AI session is acquired.
- AI output is checked again before entering the processed state.
- The gate is fail-open only for legacy DB read exceptions to avoid taking down ingestion; the item remains available for later processing.
