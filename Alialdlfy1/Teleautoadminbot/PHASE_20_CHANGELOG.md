# P29 Phase 20 Changelog — Performance, Concurrency & Chaos

- Added canonical bounded concurrent worker pool over the persistent queue.
- Added compatibility facade so legacy `core.jobs.store.JobStore` callers use the canonical storage implementation without changing old call signatures.
- Added deterministic load harness and chaos scenario matrix.
- Added runtime helpers `build_concurrent_workers()` and `load_snapshot()`.
- Added tests for duplicate enqueue, concurrent claims, lease recovery, 40-job load, and chaos coverage.
- Existing secret names/callbacks/public runtime compatibility preserved.

## Verification
- `python -m compileall -q .`: PASS
- Phase 20 + regression/core suite selected for non-Telegram paths: **61 passed**
- App smoke: PASS; `blogger, news, sports` discovered.
- Load test: 200 jobs / 8 workers: **200 processed, 0 queued, 200 done, 0 dead**, ~175.35 jobs/s in the local test environment.
- Full pytest collection is blocked by missing `pyrogram` in this environment; Telegram-dependent imports fail at collection. This is an environment dependency, not a compile/core test failure.
