---
title: Verified GPT-2
emoji: 🔬
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# Verified GPT-2

A from-scratch GPT-2 implementation whose logits match HuggingFace's reference
weights bitwise (fp32 / eval / eager / CPU), served over FastAPI.

## Endpoints

- `GET /health` — liveness probe
- `POST /generate` — `{"prompt": str, "max_new_tokens": int, "temperature": float, "top_k": int | null}`
- `GET /docs` — interactive OpenAPI UI

```bash
curl -X POST .../generate \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "Hello, I am a language model,", "max_new_tokens": 40, "temperature": 0.8, "top_k": 200}'
```
