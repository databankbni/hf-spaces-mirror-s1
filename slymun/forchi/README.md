---
title: ForChi LLM Server
emoji: 🧠
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# ForChi LLM Server

Runs **Qwen2.5-7B-Instruct** (Q4_K_M, ~4.4GB) on **free CPU Basic** hardware using `llama.cpp`.

OpenAI-compatible endpoint:

```
POST https://slymun-forchi.hf.space/v1/chat/completions
Authorization: Bearer <HF_TOKEN>
{
  "model": "qwen2.5-7b",
  "messages": [{"role": "user", "content": "..."}]
}
```

The model is downloaded on first start into ephemeral storage (re-downloaded on redeploy). Keep the Space awake with a periodic ping (HF free tier sleeps after 48h).
