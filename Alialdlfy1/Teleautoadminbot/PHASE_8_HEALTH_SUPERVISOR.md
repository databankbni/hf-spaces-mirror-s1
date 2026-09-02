# Phase 8 — Health Monitor + Supervisor

Adds:
- service health checks
- consecutive failure tracking
- health snapshots
- supervised restart with exponential backoff
- restart caps and disable-on-persistent-failure

This is intentionally a migration layer. Existing services are not forcibly wrapped yet.
The next phase can connect Telegram scheduler, workers, provider clients and publishers one by one.
