FROM python:3.11-slim

# curl for model download at startup
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# llama-cpp-python (prebuilt CPU wheel) + FastAPI server
RUN pip install --no-cache-dir --only-binary=:all: \
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu \
    'llama-cpp-python==0.3.34' fastapi 'uvicorn[standard]'

WORKDIR /app
COPY app.py /app/app.py
COPY entrypoint.sh /app/entrypoint.sh
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Qwen2.5-7B-Instruct Q4_K_M (single-file GGUF, ~4.4GB)
ENV MODEL_URL="https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf"
ENV MODEL_PATH="/models/Qwen2.5-7B-Instruct-Q4_K_M.gguf"

EXPOSE 7860
ENTRYPOINT ["/app/entrypoint.sh"]
