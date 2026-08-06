---
title: Heliteb Agent
emoji: 🤖
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
startup_duration_timeout: 1h
pinned: false
---

# HELITEB AI Sales Agent

Agente comercial con IA para HELITEB SAS — LangGraph + Mistral + Gemini + BGE-M3 + Supabase pgvector.

**Endpoints:**
- `/health` — Liveness probe
- `/agent/query` — Agente conversacional (POST)
- `/webhooks/whatsapp` — WhatsApp Cloud API (GET verify + POST messages)

**Stack:** Python 3.12 · FastAPI · LangGraph · Mistral · Gemini 2.5 Flash · BGE-M3 · Supabase pgvector · NGINX · n8n
