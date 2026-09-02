# Dockerfile for Hugging Face Spaces (Docker SDK)
# Runs the Flask app with gunicorn on port 7860 (the HF Spaces default).

FROM python:3.11-slim

# Build tools some Python wheels may need
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# HF Spaces runs containers as a non-root user (uid 1000).
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    HF_HOME=/home/user/.cache/huggingface \
    PORT=7860

WORKDIR /home/user/app

# Install dependencies first for better layer caching
COPY --chown=user requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Pre-download the embedding model so the first request isn't slow.
# Cached under the (writable) user home so it persists into runtime.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Copy the rest of the app (Books/ and venv are excluded via .dockerignore)
COPY --chown=user . .

EXPOSE 7860

# One worker is plenty for a personal demo; long timeout for model/LLM calls.
CMD ["gunicorn", "--bind", "0.0.0.0:7860", "--workers", "1", "--timeout", "180", "app:app"]
