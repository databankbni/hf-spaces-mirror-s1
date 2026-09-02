# Hugging Face Spaces — RICS v2 backend (OpenAI embeddings; no local torch/reranker).
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 user \
    && mkdir -p /data /data/hf_cache \
    && chown -R user:user /data

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/user \
    PATH="/home/user/.local/bin:$PATH" \
    PORT=7860 \
    DATA_DIR=/data

USER user
WORKDIR /app

COPY --chown=user backend/requirements-spaces.txt ./backend/requirements-spaces.txt
RUN pip install --upgrade pip && \
    pip install -r backend/requirements-spaces.txt

COPY --chown=user backend ./backend
COPY --chown=user frontend ./frontend
# PDF extractors (LlamaParse / Textract) load modules from REPO_ROOT/scripts/.
COPY --chown=user scripts ./scripts

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=5 \
    CMD curl -fsS "http://127.0.0.1:${PORT:-7860}/health" || exit 1

CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-7860} --workers 1"]
