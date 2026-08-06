---
title: skill-audit
emoji: 🛡️
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# skill-audit API

Detect malicious patterns in AI agent skills, plugins, and prompts (17 patterns:
download-and-execute, credential exfiltration, prompt injection, privilege
escalation, seed-phrase harvesting, …).

Paid via **x402** micropayments (USDC on Base, Dexter facilitator, 0% fee):

- `GET /` — service info (free)
- `GET /health` — health check (free)
- `POST /audit` — audit text — `$0.01` USDC
- `POST /audit/url` — fetch URL + audit — `$0.03` USDC
- `POST /read` — fetch URL → clean Markdown (boilerplate stripped) — `$0.005` USDC

Unpaid requests get `HTTP 402` with payment requirements. Source: github.com/eltociear/my-molt-agent
