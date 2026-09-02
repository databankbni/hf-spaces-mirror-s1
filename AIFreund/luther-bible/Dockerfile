# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY luther_mcp/ ./luther_mcp/

# Pre-download the embedding model so it's baked into the image. Uses the
# optional HF_TOKEN secret (Space Settings -> Secrets) to avoid the Hugging
# Face Hub's anonymous-request rate limit.
RUN --mount=type=secret,id=HF_TOKEN,mode=0444 \
    export HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)"; \
    python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-small')"

ENV CHROMA_PATH=/app/bible_chroma_db

# Download pre-built ChromaDB index from latest GitHub Release. Uses the
# optional GITHUB_TOKEN secret (Space Settings -> Secrets) to avoid GitHub
# API's anonymous rate limit (60 req/hour per IP), which HF's shared build
# infrastructure hits easily.
RUN --mount=type=secret,id=GITHUB_TOKEN,mode=0444 \
    export GITHUB_TOKEN="$(cat /run/secrets/GITHUB_TOKEN 2>/dev/null || true)"; \
    python -m luther_mcp download

# HuggingFace Spaces sets PORT=7860 automatically
CMD ["python", "-m", "luther_mcp", "--sse"]
