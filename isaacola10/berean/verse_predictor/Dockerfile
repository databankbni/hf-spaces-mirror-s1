FROM python:3.12-slim

WORKDIR /app

# ca-certificates for HTTPS downloads (translations + model weights).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# CPU-only PyTorch (avoids pulling the multi-GB CUDA build + nvidia-* packages).
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x docker-entrypoint.sh

# Cache model weights (Whisper, embeddings, cross-encoder) under a mountable dir.
ENV HF_HOME=/cache/hf
EXPOSE 8000

CMD ["./docker-entrypoint.sh"]
