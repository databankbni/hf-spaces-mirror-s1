# Phase 10 — Auto-Repair Policy + Control Bot

Adds a conservative policy gate between sandbox-tested patches and production.

Rules:
- secrets/credentials/tokens/keys/sessions/data/.git are blocked.
- code changes are medium risk by default and require admin approval.
- changes outside allowed roots are high risk and require admin approval.
- per-incident attempt cap and cooldown prevent repair loops.
- optional health check triggers rollback after application.

Control-bot buttons are additive and callback-style:
- repair status
- pending repairs
- approve repair
- rollback last repair
- disable/enable auto-repair

Existing button callbacks are not renamed or removed by this phase. The host bot should attach these buttons to its existing menu/router using the same callback mechanism already used by the project.
