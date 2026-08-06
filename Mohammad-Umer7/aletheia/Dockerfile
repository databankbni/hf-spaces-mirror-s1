# Aletheia backend — self-hosted Cognee + FastAPI, for Hugging Face Spaces (Docker SDK).
# Spaces free tier: ephemeral disk (fine — the demo reseeds), port 7860 required.
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY scripts/ scripts/

ENV PYTHONUTF8=1
# HF Spaces writes are only permitted outside the image's baked-in paths under
# some runtimes; give cognee's storage an explicit, writable home.
ENV HOME=/app
RUN mkdir -p /app/data

EXPOSE 7860
CMD ["uvicorn", "backend.api:app", "--host", "0.0.0.0", "--port", "7860", "--timeout-keep-alive", "75"]
