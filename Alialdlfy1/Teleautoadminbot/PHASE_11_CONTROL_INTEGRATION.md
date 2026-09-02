# Phase 11 — Control Bot Integration + Common Content Pipeline

Adds an additive callback router and RepairControl façade for the existing control bot.

New callbacks:
- `repair:status`
- `repair:pending`
- `repair:approve`
- `repair:rollback`
- `repair:disable`
- `repair:enable`

The router does not replace or rename existing callbacks.

Also adds `ContentPipeline`, a common service façade intended for Blogger, News, Sports and future sections. It applies the existing gate before queueing and sends accepted articles to the common AI Gateway.

The actual Telegram framework handler should bind these callback strings to the project's existing button/menu code during final integration; this phase keeps framework-specific code isolated.
