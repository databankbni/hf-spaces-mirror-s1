---
title: Verseo
emoji: 📖
colorFrom: purple
colorTo: pink
sdk: docker
app_port: 7860
pinned: false
short_description: Find Bible verses by voice, text, or question
---

# Verseo

Speak, type, or ask a natural-language question and Verseo finds the closest
Bible verses across multiple translations and languages (Whisper speech-to-text
+ semantic/lexical retrieval, with a Claude-grounded Q&A mode).

This Space runs the whole stack in one container: a Python model API plus the
Next.js UI.

## Setup

- **`ANTHROPIC_API_KEY`** (Space secret) — enables the "Ask" Q&A mode. Without
  it the app still works and shows the relevant verses.
- **`ADMIN_PASSWORD`** (Space secret) — enables the `/admin` dashboard
  (analytics, topic CMS, feature flags, search-quality lab). If unset, admin
  login is disabled.
- Optional variables: `ANSWER_MODEL` (default `claude-opus-4-8`; set
  `claude-haiku-4-5` for cheaper answers), `RERANK` (`0` disables the
  cross-encoder for faster cold starts / less memory).
- **Accounts & billing** (all optional; features hide when unset):
  `DATABASE_URL` (Supabase Postgres — moves every record off the ephemeral
  container so deploys never touch data), `SUPABASE_URL`, `SUPABASE_ANON_KEY`,
  `SUPABASE_JWT_SECRET` (sign-in), and Stripe keys — which can instead be set
  at runtime in **Admin → Services** (`STRIPE_SECRET_KEY`,
  `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_PLUS`, `STRIPE_PRICE_SPEAKER`).

> On the free CPU tier the first load downloads models and builds the index
> (a couple of minutes — the UI shows "Warming up…"). Storage is ephemeral, so
> analytics and admin edits reset when the Space sleeps/cold-starts; point a
> persistent disk at `VERSEO_DB` for durable data.
