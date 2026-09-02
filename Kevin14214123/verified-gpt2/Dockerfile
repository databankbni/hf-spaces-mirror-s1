FROM python:3.11-slim
WORKDIR /app

# Model and tokenizer caches live inside the image, so a cold start needs no network.
ENV HF_HOME=/app/hf_cache \
    TIKTOKEN_CACHE_DIR=/app/tiktoken_cache

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the GPT-2 weights and the BPE vocab into their own layer, placed before the
# code is copied so that editing serve.py does not invalidate a ~0.5GB download.
RUN python -c "from transformers import GPT2LMHeadModel; GPT2LMHeadModel.from_pretrained('gpt2'); import tiktoken; tiktoken.get_encoding('gpt2')" \
    && chmod -R a+rwX /app/hf_cache /app/tiktoken_cache

COPY serve.py gpt.py ./

EXPOSE 7860
CMD ["uvicorn", "serve:app", "--host", "0.0.0.0", "--port", "7860"]
