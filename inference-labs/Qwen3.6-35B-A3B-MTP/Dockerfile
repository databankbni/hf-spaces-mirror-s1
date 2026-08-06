
FROM python:3.11-slim-bookworm AS downloader

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /models

RUN pip install --no-cache-dir -U huggingface_hub

RUN python3 -c 'from huggingface_hub import hf_hub_download; \
    model_repo="unsloth/Qwen3.6-35B-A3B-MTP-GGUF"; \
    mmproj_repo="unsloth/Qwen3.6-35B-A3B-GGUF"; \
    hf_hub_download(repo_id=model_repo, filename="Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf", local_dir="/models"); \
    hf_hub_download(repo_id=mmproj_repo, filename="mmproj-BF16.gguf", local_dir="/models")'

FROM ghcr.io/ggml-org/llama.cpp:full

RUN apt-get update && apt-get install -y --no-install-recommends \
        libjemalloc2 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -d /home/llama -s /bin/bash -g root -G sudo -u 1001 llama

WORKDIR /app

COPY --from=downloader --chown=llama:root /models /app

USER llama

ENV LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libjemalloc.so.2
ENV MALLOC_CONF="background_thread:true,metadata_thp:auto,dirty_decay_ms:0,muzzy_decay_ms:0"

ENV OMP_NUM_THREADS=2
ENV KMP_AFFINITY=granularity=fine,compact
ENV OMP_WAIT_POLICY=ACTIVE
ENV KMP_BLOCKTIME=infinite

CMD ["--server", \
     "-m", "/app/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf", \
     "--mmproj", "/app/mmproj-BF16.gguf", \
     "--host", "0.0.0.0", \
     "--port", "7860", \
     "-t", "2", \
     "-tb", "2", \
     "-fa", "on", \
     "-ub", "128", \
     "-b", "512", \
     "--cache-type-k", "q4_0", \
     "--cache-type-v", "q4_0", \
     "-c", "262000", \
     "-n", "-1", \
     "--spec-type", "draft-mtp", \
     "--spec-draft-n-max", "4"]