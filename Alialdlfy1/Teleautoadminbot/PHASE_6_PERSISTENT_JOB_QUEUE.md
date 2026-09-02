# Phase 6 — Persistent Job Queue & Crash Recovery

Adds a SQLite/WAL job store with:
- durable queued jobs
- atomic-ish claim under SQLite locking
- worker lease timestamps
- recovery of jobs whose worker crashed
- retry with max attempts
- dead-letter (`dead`) state
- idempotent enqueue by job id

This is a migration layer. Existing scheduler code is not deleted or replaced in this phase.
The next migration step is to route actual article processing/publishing through this store and make publish idempotency explicit.
