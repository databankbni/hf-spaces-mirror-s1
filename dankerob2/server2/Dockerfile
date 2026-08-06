FROM ghcr.io/ggml-org/llama.cpp:server

USER root

# Install curl, download the 1B model, and clean up in one layer
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    mkdir -p /models && \
    curl -L https://huggingface.co/unsloth/Llama-3.2-1B-Instruct-GGUF/resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf -o /models/model.gguf && \
    chown -R 1000:1000 /models && \
    apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

USER 1000

ENV LLAMA_ARG_MODEL=/models/model.gguf
ENV LLAMA_ARG_HOST=0.0.0.0
ENV LLAMA_ARG_PORT=7860

# --- Precise Free HF Space Hardware Tuning ---
ENV LLAMA_ARG_THREADS=2
ENV LLAMA_ARG_CTX_SIZE=2048
ENV LLAMA_ARG_BATCH_SIZE=32
ENV LLAMA_ARG_UBATCH_SIZE=32
ENV LLAMA_ARG_FLASH_ATTN=true

# CRITICAL: Disable mlock (not supported on HF shared nodes)
ENV LLAMA_ARG_MLOCK=false

HEALTHCHECK --interval=30s --timeout=15s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:7860/health || exit 1

ENTRYPOINT ["/app/llama-server"]
