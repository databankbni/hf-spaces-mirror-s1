# Combined single-container image for a Hugging Face Docker Space.
# Runs the Python model API (uvicorn, internal :8000) + the Next.js UI
# (public :7860). The browser only hits the Next server, which proxies to
# the backend over localhost.

# --- build the Next.js standalone bundle ---
FROM node:22-bookworm-slim AS webbuild
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# --- runtime: node + python in one image ---
FROM node:22-bookworm-slim
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Python backend deps in an isolated venv. Install CPU-only PyTorch first
# (from the CPU wheel index) so the default CUDA build + nvidia-* packages
# aren't pulled in — keeps the image small for a CPU Space.
COPY verse_predictor/requirements.txt /app/backend/requirements.txt
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -U pip \
    && /opt/venv/bin/pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && /opt/venv/bin/pip install --no-cache-dir -r /app/backend/requirements.txt

# Backend source (includes the prebuilt int8 index, so no embedding at boot).
COPY verse_predictor/ /app/backend/

# Pre-download the model weights into the image so cold starts don't fetch
# ~1 GB over the network — the Space just loads from disk and is ready fast.
ENV HF_HOME=/app/backend/data/hf
RUN /opt/venv/bin/python - <<'PY'
from faster_whisper import WhisperModel
# Bake the accent-robust "small" model so cold starts don't re-download.
WhisperModel("small", device="cpu", compute_type="int8")
from sentence_transformers import SentenceTransformer, CrossEncoder
SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
CrossEncoder("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")
print("model weights baked into image")
PY

# Next.js standalone output (server + traced deps + static assets).
COPY --from=webbuild /web/.next/standalone /app/web/
COPY --from=webbuild /web/.next/static /app/web/.next/static
COPY --from=webbuild /web/public /app/web/public

COPY huggingface/start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Make the data dir writable whether HF runs the container as root or uid 1000.
RUN chmod -R 777 /app/backend/data

ENV PYTHON_API_URL=http://127.0.0.1:8000 \
    ANSWER_MODEL=claude-opus-4-8 \
    ANSWER_MODEL_FALLBACK=claude-haiku-4-5 \
    ASR_MODEL=small \
    RERANK=1 \
    PORT=7860 \
    HOSTNAME=0.0.0.0 \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

EXPOSE 7860
CMD ["/app/start.sh"]
