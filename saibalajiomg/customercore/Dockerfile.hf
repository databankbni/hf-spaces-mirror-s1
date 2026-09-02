# ─────────────────────────────────────────────────────────────────────────────
# CustomerCore — Hugging Face Spaces Dockerfile (Phase 10)
#
# WHY A SEPARATE DOCKERFILE FOR HF SPACES?
# HF Spaces has specific constraints:
#   - 2 vCPUs, 16GB RAM on free tier (Zero GPU)
#   - No JVM/JDK allowed on the smallest tier (PySpark requires 500MB+ JDK)
#   - Container must listen on port 7860 (HF Spaces requirement)
#   - No root user (HF runs as user 1000)
#   - 50GB ephemeral storage (data is lost on restart — use Supabase for persistence)
#
# This image strips PySpark and uses a lightweight requirements file.
# The API still works: BM25 retrieval, LLM routing, and LangGraph triage all function
# without PySpark. The Bronze→Silver data pipeline is not needed for inference.
#
# HF Spaces deployment:
#   1. Create a new Space at huggingface.co/spaces
#   2. Select "Docker" as the SDK
#   3. Add this file as Dockerfile in the repo root
#   4. Set secrets in Space settings (same values as Doppler)
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.title="CustomerCore API (HF Spaces)" \
      org.opencontainers.image.description="CustomerCore — Lightweight deployment for Hugging Face Spaces" \
      org.opencontainers.image.version="1.0.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    APP_ENV=production \
    # HF Spaces requires port 7860
    PORT=7860

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# HF Spaces runs as user 1000 — create matching user
RUN useradd -m -u 1000 hfuser

WORKDIR /app

# Use the slim CI requirements file — already Linux-safe (no pywin32, pyspark, etc.)
COPY requirements-ci.txt .
RUN pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements-ci.txt

COPY src/ ./src/
COPY pyproject.toml .

RUN mkdir -p logs data \
    && chown -R hfuser:hfuser /app

USER hfuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:7860/api/v1/health || exit 1

EXPOSE 7860

# Single worker on HF free tier (2 vCPU)
CMD ["uvicorn", "src.api.main:app", \
     "--host", "0.0.0.0", \
     "--port", "7860", \
     "--workers", "1", \
     "--log-level", "warning"]
