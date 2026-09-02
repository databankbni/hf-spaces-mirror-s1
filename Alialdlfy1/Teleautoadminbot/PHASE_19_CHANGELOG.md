# Phase 19 Changelog

- Added `core/control/plane.py` operational alert/control layer.
- Extended `core/infra/metrics.py` with thread-safe latency aggregates and timers.
- Extended `core/infra/audit.py` with safe recent-event retrieval.
- Integrated control-plane data into `RuntimeIntegration.control_snapshot()`.
- Added runtime operational snapshot, recent audit access and alert acknowledgement APIs.
- Added global control callback façade without renaming old callbacks.
- Added regression tests for alerts, metrics compatibility and admin-gated control access.
