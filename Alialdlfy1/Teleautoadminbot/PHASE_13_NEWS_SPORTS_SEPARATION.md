# Phase 13 — Separate News and Sports

News and Sports are now first-class independent sections.

Each section has:
- its own key and namespace
- its own settings/state
- its own callbacks
- its own enable/disable status
- its own sources/blocked words/duplicate policy/AI settings/queue/repair controls

They share infrastructure:
- ContentPipeline
- AI Gateway/provider rotation
- persistent Queue/Recovery
- idempotent publishing
- Health/Supervisor
- Auto-Repair policy and Sandbox

Control buttons are generated with the same set for both sections, but callback namespaces are isolated:
`news:*` vs `sports:*`.

No old secret names are changed.
