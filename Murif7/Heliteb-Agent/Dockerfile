# ───────────────────────────────────────────────────────────────────────
# Dockerfile.hf — HELITEB AI Agent (HF Spaces Docker deployment)
# ───────────────────────────────────────────────────────────────────────

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx curl ca-certificates build-essential \
    && rm -rf /var/lib/apt/lists/*

# ── Python deps ────────────────────────────────────────────────────────
WORKDIR /app
COPY agent/requirements.txt /app/agent/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/agent/requirements.txt

# ── User setup ─────────────────────────────────────────────────────────
RUN useradd -m -u 1000 user \
    && mkdir -p /var/cache/nginx /var/log/nginx /var/lib/nginx \
    && chown -R user:user /var/cache/nginx /var/log/nginx /var/lib/nginx

# ── App code ───────────────────────────────────────────────────────────
COPY --chown=user:user agent/ /app/agent/
COPY --chown=user:user nginx.conf /app/nginx.conf
COPY --chown=user:user start.sh /app/start.sh
RUN chmod +x /app/start.sh

# ── Persistent data ────────────────────────────────────────────────────
ENV HF_HOME=/data/.cache/huggingface
RUN mkdir -p /data/.cache/huggingface && chown -R user:user /data

USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH
EXPOSE 7860
CMD ["./start.sh"]
