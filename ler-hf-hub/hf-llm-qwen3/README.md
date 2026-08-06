---
title: hf-llm · Qwen3 Chinese RAG Playground
emoji: 🔥
colorFrom: red
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
license: apache-2.0
short_description: Qwen3 Embedding + Reranker + 4B Chat, OpenAI-compatible API
tags:
  - qwen
  - qwen3
  - embedding
  - reranker
  - rag
  - chinese
  - openai-compatible
  - mteb
models:
  - Qwen/Qwen3-Embedding-0.6B
  - Qwen/Qwen3-Reranker-0.6B
  - warshanks/Qwen3-4B-Instruct-2507-AWQ
---

# 🇨🇳 hf-llm — Qwen3 Chinese RAG Playground

An **open-source, self-hosted Chinese RAG stack** in a single Space:

- 📐 **Embedding** — [`Qwen/Qwen3-Embedding-0.6B`](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) · 1024-dim · MRL truncatable · SOTA on Chinese MTEB
- 🎯 **Reranker** — [`Qwen/Qwen3-Reranker-0.6B`](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B) · CrossEncoder · outperforms `bge-reranker-v2-m3`
- 💬 **Chat** — [`Qwen3-4B-Instruct-2507-AWQ`](https://huggingface.co/warshanks/Qwen3-4B-Instruct-2507-AWQ) · int4 quantized · ~3 GB VRAM

Runs comfortably on a **T4 small (16 GB)** — total VRAM ~6-7 GB with all three models resident.

## 🎮 Try it live

Above is a **Gradio playground** with three tabs:

1. **Embedding** — paste any Chinese/English text, get a normalized 1024-dim vector; slider lets you play with MRL dimension truncation (32 → 1024).
2. **Reranker** — paste a query and candidate docs, watch Qwen3 re-order them by semantic relevance.
3. **Chat** — free-form chat with the 4B AWQ model.

## 🔌 Also an OpenAI-compatible API

Every model is also exposed via drop-in **OpenAI-compatible endpoints**, so you can plug this Space into any existing RAG codebase in one line:

| Endpoint | Compatible with |
|----------|-----------------|
| `POST /v1/embeddings` | OpenAI Embeddings |
| `POST /v1/rerank` | Cohere / SiliconFlow Rerank |
| `POST /v1/chat/completions` | OpenAI Chat |

```python
from openai import OpenAI
client = OpenAI(
    base_url="https://<your-username>-hf-llm-qwen3.hf.space/v1",
    api_key="dummy",
)
vecs = client.embeddings.create(model="qwen3-embed", input=["你好，世界"])
```

## 🎓 Who is this for?

Chinese developers building **RAG pipelines, semantic search, or education/tutoring bots** who need:

- ✅ First-class Chinese embedding & reranking quality
- ✅ Zero API cost during prototyping
- ✅ A self-hostable stack they can lift-and-shift to their own GPU later

Everything is open source, Apache-2.0, and reproducible from this Space's `Dockerfile`.

## 🙏 Powered by

- [Qwen team](https://qwenlm.github.io/) for the fantastic Qwen3 series
- Hugging Face for the Space hosting and **Community GPU Grant** program 🧡
- [sentence-transformers](https://sbert.net) · [transformers](https://huggingface.co/docs/transformers) · [AutoAWQ](https://github.com/casper-hansen/AutoAWQ) · [FastAPI](https://fastapi.tiangolo.com) · [Gradio](https://gradio.app)
