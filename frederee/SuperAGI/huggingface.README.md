---
title: SuperAGI Chat API
emoji: 🤖
colorFrom: gray
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# SuperAGI Chat API

Docker Space wrapper for the SuperAGI chat backend.

The container exposes:

- `GET /`
- `GET /health`
- `GET /api/models/active`
- `GET /api/chat/sessions/<session_id>`
- `POST /api/chat`

The backend stores chat context in SQLite by default. On Hugging Face free CPU
Spaces this local database should be treated as disposable unless persistent
storage is enabled.

## Supabase Storage

For durable chat logs, add this Space secret:

```bash
SUPABASE_DATABASE_URL=postgresql://postgres.jscgykqjejcfdfnihizw:<URL-ENCODED-PASSWORD>@aws-0-eu-west-1.pooler.supabase.com:5432/postgres?sslmode=require
```

When `SUPABASE_DATABASE_URL` is present, the backend stores session snapshots
and every successful chat turn in Supabase Postgres while mirroring to local
SQLite. If Supabase is paused or unreachable, chat falls back to local SQLite
instead of failing the request. The backend creates the tables on first use, or
you can run `python_backend/migrations/001_chat_storage.sql` in Supabase before
deploying.

For free Supabase projects, also add the GitHub repository secrets
`SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` so the scheduled
`keep-supabase-awake.yml` workflow can query the database twice per week.

## Model Configuration

The Space image includes the bundled SuperAGI source and uses the current
`SuperAGI 0.2` runner by default. To override the checkpoint/source, set:

```bash
SUPERAGI_REPO_PATH=/path/to/SuperAGI
SUPERAGI_CHECKPOINT_PATH=/path/to/SuperAGI/prod/night-0606/best.pt
SUPERAGI_DEVICE=cpu
SUPERAGI_MAX_NEW_TOKENS=80
```

The Docker image installs model runtime dependencies by default. To build a
smaller placeholder-only image:

```bash
docker build --build-arg INSTALL_SUPERAGI_DEPS=false -t superagi-chat-backend .
```
