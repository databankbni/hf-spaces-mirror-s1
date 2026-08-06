# syntax=docker/dockerfile:1.7
#
# Two-stage build for thebeast, tuned for Hugging Face Spaces (Docker SDK).
#
#   Stage 1 (web)     — compile the SvelteKit static bundle.
#   Stage 2 (runtime) — Python image running FastAPI, which serves both the
#                       /api/* JSON and the static bundle from one process.
#
# HF Spaces runs containers as non-root UID 1000 ("user") on port 8080.

# ─────────────────────────── Stage 1: web build ────────────────────────────
FROM node:22-alpine AS web

WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build
# → /web/build is the static SPA bundle.


# ───────────────────────── Stage 2: Python runtime ─────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    THEBEAST_DB_PATH=/home/user/app/data/thebeast.db

RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:${PATH}"
WORKDIR /home/user/app

COPY --chown=user:user requirements.txt ./
RUN pip install --user --no-cache-dir -r requirements.txt

# Application code.
COPY --chown=user:user thebeast ./thebeast
# Prebuilt statline/schedule DB (bundled so the demo shows real data; the app
# falls back to league-average synthetic players if it is absent).
COPY --chown=user:user data ./data
# Static frontend produced by stage 1.
COPY --chown=user:user --from=web /web/build ./web/build

EXPOSE 8080
CMD ["uvicorn", "thebeast.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
