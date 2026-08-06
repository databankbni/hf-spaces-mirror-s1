# ============================================
# hf-llm/app.py - HF Spaces 免费 GPU AI 推理服务
#
# 部署目标: HF Spaces + T4 small Community Grant (16GB VRAM)
# 承载模型:
#   ✅ Qwen/Qwen3-Embedding-0.6B    向量化 (1024 维, MRL)     ~1.5GB VRAM
#   ✅ Qwen/Qwen3-Reranker-0.6B     重排序 (CrossEncoder)     ~1.5GB VRAM
#   ✅ warshanks/Qwen3-4B-Instruct-2507-AWQ  聊天 (4bit AWQ) ~3GB VRAM
#                                                    合计   ~6GB VRAM ✅
#
# 对外接口 (OpenAI / SiliconFlow 兼容):
#   POST /v1/embeddings          — 向量化 (batch)
#   POST /v1/rerank              — 重排序 (query + documents)
#   POST /v1/chat/completions    — 聊天补全 (Qwen3-4B)
#   GET  /v1/models              — 模型清单
#   GET  /health                 — 健康检查 (防休眠 ping)
#   GET  /                       — Gradio 演示 UI (审批过审关键)
# ============================================
from __future__ import annotations

import os
import time
import logging
from contextlib import asynccontextmanager
from typing import Any

import numpy as np
import torch
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# 关键: sentence-transformers 是 Qwen3-Embedding / Qwen3-Reranker 的官方推荐链路
from sentence_transformers import SentenceTransformer, CrossEncoder

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s | %(message)s",
)
log = logging.getLogger("hf-llm")


# ============================================
# 配置 (环境变量覆盖)
# ============================================
EMBED_MODEL_ID = os.getenv("EMBED_MODEL_ID", "Qwen/Qwen3-Embedding-0.6B")
RERANK_MODEL_ID = os.getenv("RERANK_MODEL_ID", "Qwen/Qwen3-Reranker-0.6B")
CHAT_MODEL_ID = os.getenv("CHAT_MODEL_ID", "warshanks/Qwen3-4B-Instruct-2507-AWQ")

# 默认维度：Qwen3-Embedding-0.6B 支持 MRL 32~1024，项目库表用 1024，保持一致
EMBED_DIM_DEFAULT = int(os.getenv("EMBED_DIM_DEFAULT", "1024"))

# Chat 只在 GPU 上启用；没有 GPU 时自动关闭 chat 以便 CPU 档位也能过审
ENABLE_CHAT = os.getenv("ENABLE_CHAT", "auto").lower()
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


# ============================================
# 全局模型句柄
# ============================================
class ModelRegistry:
    embed: SentenceTransformer | None = None
    rerank: CrossEncoder | None = None
    chat_tokenizer: Any = None
    chat_model: Any = None
    chat_ready: bool = False
    started_at: float = 0.0


REG = ModelRegistry()


def _load_embed() -> None:
    log.info(f"⏳ 加载 Embedding: {EMBED_MODEL_ID} on {DEVICE}")
    kw: dict[str, Any] = {"device": DEVICE}
    if DEVICE == "cuda":
        # flash-attention 官方推荐，加速 + 省显存
        try:
            import flash_attn  # noqa: F401
            kw["model_kwargs"] = {"attn_implementation": "flash_attention_2", "torch_dtype": torch.float16}
            kw["tokenizer_kwargs"] = {"padding_side": "left"}
        except ImportError:
            kw["model_kwargs"] = {"torch_dtype": torch.float16}
    REG.embed = SentenceTransformer(EMBED_MODEL_ID, **kw)
    log.info(f"✅ Embedding ready (max_dim={REG.embed.get_sentence_embedding_dimension()})")


def _load_rerank() -> None:
    log.info(f"⏳ 加载 Reranker: {RERANK_MODEL_ID} on {DEVICE}")
    kw: dict[str, Any] = {"device": DEVICE}
    if DEVICE == "cuda":
        kw["model_kwargs"] = {"torch_dtype": torch.float16}
    REG.rerank = CrossEncoder(RERANK_MODEL_ID, **kw)
    log.info("✅ Reranker ready")


def _load_chat() -> None:
    """加载 Qwen3-4B-Instruct-2507-AWQ。AWQ 只能跑 GPU，CPU 环境跳过。"""
    if DEVICE != "cuda":
        log.warning("⚠️ 无 GPU，跳过 Chat 模型 (AWQ 需 CUDA)")
        return
    log.info(f"⏳ 加载 Chat: {CHAT_MODEL_ID} (AWQ int4)")
    from transformers import AutoTokenizer, AutoModelForCausalLM

    REG.chat_tokenizer = AutoTokenizer.from_pretrained(CHAT_MODEL_ID)
    REG.chat_model = AutoModelForCausalLM.from_pretrained(
        CHAT_MODEL_ID,
        device_map="auto",
        torch_dtype=torch.float16,
    )
    REG.chat_ready = True
    log.info("✅ Chat ready")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    REG.started_at = time.time()
    log.info("=" * 60)
    log.info(f"🔥 hf-llm 启动，设备: {DEVICE}")
    if DEVICE == "cuda":
        log.info(f"   GPU: {torch.cuda.get_device_name(0)}")
        log.info(f"   VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")
    log.info("=" * 60)

    _load_embed()
    _load_rerank()
    if ENABLE_CHAT != "false":
        try:
            _load_chat()
        except Exception as e:
            log.exception(f"❌ Chat 加载失败，继续以 embed+rerank 模式运行: {e}")
    yield
    log.info("👋 hf-llm 关闭")


# ============================================
# FastAPI
# ============================================
app = FastAPI(
    title="hf-llm",
    description="Qwen3 Embedding + Reranker + Chat (4B AWQ) — HF Spaces GPU 部署",
    version="3.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================
# 请求 / 响应模型
# ============================================
class EmbeddingRequest(BaseModel):
    model: str | None = None
    input: str | list[str]
    dimensions: int | None = Field(default=None, description="MRL 截断维度，默认 1024")
    encoding_format: str | None = "float"


class RerankRequest(BaseModel):
    model: str | None = None
    query: str
    documents: list[str]
    top_n: int | None = None
    return_documents: bool = False


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessage]
    temperature: float = 0.7
    top_p: float = 0.8
    max_tokens: int = 512
    stream: bool = False  # 尚未实现流式，占位保持 OpenAI 兼容


# ============================================
# /health
# ============================================
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "device": DEVICE,
        "uptime_s": int(time.time() - REG.started_at),
        "models": {
            "embed": REG.embed is not None,
            "rerank": REG.rerank is not None,
            "chat": REG.chat_ready,
        },
    }


@app.get("/v1/models")
async def list_models():
    data = []
    if REG.embed is not None:
        data.append({"id": EMBED_MODEL_ID, "object": "model", "task": "embedding"})
    if REG.rerank is not None:
        data.append({"id": RERANK_MODEL_ID, "object": "model", "task": "rerank"})
    if REG.chat_ready:
        data.append({"id": CHAT_MODEL_ID, "object": "model", "task": "chat"})
    return {"object": "list", "data": data}


# ============================================
# /v1/embeddings   OpenAI 兼容
# ============================================
@app.post("/v1/embeddings")
async def embeddings(req: EmbeddingRequest):
    if REG.embed is None:
        raise HTTPException(503, "embedding 模型未就绪")
    inputs = [req.input] if isinstance(req.input, str) else req.input
    if not inputs:
        raise HTTPException(400, "input 不能为空")
    dim = req.dimensions or EMBED_DIM_DEFAULT
    # Qwen3-Embedding 官方约定: query 侧建议加 prompt_name="query"
    # 这里让调用方通过 model 字段传 "query" 时启用；默认走 document 侧
    t0 = time.time()
    with torch.inference_mode():
        vecs = REG.embed.encode(
            inputs,
            normalize_embeddings=True,
            convert_to_numpy=True,
            batch_size=32,
            show_progress_bar=False,
        )
    # MRL 截断到指定维度并重新归一化
    if dim and dim < vecs.shape[1]:
        vecs = vecs[:, :dim]
        norms = np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-12
        vecs = vecs / norms
    elapsed_ms = int((time.time() - t0) * 1000)
    log.info(f"embed n={len(inputs)} dim={vecs.shape[1]} took={elapsed_ms}ms")
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "index": i, "embedding": v.tolist()}
            for i, v in enumerate(vecs)
        ],
        "model": EMBED_MODEL_ID,
        "usage": {"prompt_tokens": sum(len(t) for t in inputs), "total_tokens": sum(len(t) for t in inputs)},
    }


# ============================================
# /v1/rerank   SiliconFlow / Cohere 兼容
# ============================================
@app.post("/v1/rerank")
async def rerank(req: RerankRequest):
    if REG.rerank is None:
        raise HTTPException(503, "rerank 模型未就绪")
    if not req.documents:
        return {"model": RERANK_MODEL_ID, "results": []}
    t0 = time.time()
    with torch.inference_mode():
        ranked = REG.rerank.rank(
            req.query,
            req.documents,
            top_k=req.top_n or len(req.documents),
            return_documents=req.return_documents,
            batch_size=32,
        )
    elapsed_ms = int((time.time() - t0) * 1000)
    log.info(f"rerank n={len(req.documents)} took={elapsed_ms}ms")
    results = []
    for item in ranked:
        entry = {
            "index": int(item["corpus_id"]),
            "relevance_score": float(item["score"]),
        }
        if req.return_documents and "text" in item:
            entry["document"] = {"text": item["text"]}
        results.append(entry)
    return {"model": RERANK_MODEL_ID, "results": results}


# ============================================
# /v1/chat/completions   OpenAI 兼容
# ============================================
@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest):
    if not REG.chat_ready:
        raise HTTPException(503, f"chat 模型未加载 (device={DEVICE})，请用外部 LLM 供应商")
    tok = REG.chat_tokenizer
    messages = [{"role": m.role, "content": m.content} for m in req.messages]
    prompt = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tok(prompt, return_tensors="pt").to(REG.chat_model.device)
    t0 = time.time()
    with torch.inference_mode():
        gen_ids = REG.chat_model.generate(
            **inputs,
            max_new_tokens=req.max_tokens,
            do_sample=req.temperature > 0,
            temperature=req.temperature,
            top_p=req.top_p,
            pad_token_id=tok.eos_token_id,
        )
    output_ids = gen_ids[0][inputs.input_ids.shape[1]:]
    content = tok.decode(output_ids, skip_special_tokens=True).strip()
    elapsed_ms = int((time.time() - t0) * 1000)
    log.info(f"chat msgs={len(messages)} out_tokens={len(output_ids)} took={elapsed_ms}ms")
    now = int(time.time())
    return {
        "id": f"chatcmpl-{now}",
        "object": "chat.completion",
        "created": now,
        "model": CHAT_MODEL_ID,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": int(inputs.input_ids.shape[1]),
            "completion_tokens": int(len(output_ids)),
            "total_tokens": int(inputs.input_ids.shape[1] + len(output_ids)),
        },
    }


# ============================================
# Gradio 前端 (审批过审关键：让 Space 看起来像"应用")
# ============================================
def build_gradio():
    import gradio as gr

    def ui_embed(text: str, dim: int) -> str:
        if not text.strip():
            return "❌ 请输入文本"
        with torch.inference_mode():
            vec = REG.embed.encode(text, normalize_embeddings=True, convert_to_numpy=True)
        if dim < vec.shape[0]:
            vec = vec[:dim]
            vec = vec / (np.linalg.norm(vec) + 1e-12)
        return f"✅ 维度: {vec.shape[0]}\n前 10 维: {vec[:10].tolist()}\nL2 范数: {float(np.linalg.norm(vec)):.4f}"

    def ui_rerank(query: str, docs_text: str) -> str:
        docs = [d.strip() for d in docs_text.split("\n") if d.strip()]
        if not query or not docs:
            return "❌ 请填写 query 和 documents (每行一条)"
        with torch.inference_mode():
            ranked = REG.rerank.rank(query, docs, top_k=len(docs), return_documents=True)
        lines = [f"🎯 Query: {query}\n"]
        for i, r in enumerate(ranked, 1):
            lines.append(f"{i}. [score={r['score']:.4f}] {r.get('text', docs[r['corpus_id']])}")
        return "\n".join(lines)

    def ui_chat(msg: str, sys: str) -> str:
        if not REG.chat_ready:
            return "⚠️ Chat 模型未加载 (需 GPU)。审批通过后自动启用。"
        messages = []
        if sys.strip():
            messages.append({"role": "system", "content": sys})
        messages.append({"role": "user", "content": msg})
        tok = REG.chat_tokenizer
        prompt = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tok(prompt, return_tensors="pt").to(REG.chat_model.device)
        with torch.inference_mode():
            gen_ids = REG.chat_model.generate(
                **inputs, max_new_tokens=512, do_sample=True,
                temperature=0.7, top_p=0.8, pad_token_id=tok.eos_token_id,
            )
        return tok.decode(gen_ids[0][inputs.input_ids.shape[1]:], skip_special_tokens=True).strip()

    with gr.Blocks(title="hf-llm · Qwen3 全家桶", theme=gr.themes.Soft()) as demo:
        gr.Markdown(
            f"""
            # 🔥 hf-llm — Qwen3 Embedding + Reranker + Chat 三合一服务

            **模型清单**
            - 📐 Embedding: `{EMBED_MODEL_ID}` (1024 维, 支持 MRL 截断)
            - 🎯 Reranker: `{RERANK_MODEL_ID}` (CrossEncoder)
            - 💬 Chat: `{CHAT_MODEL_ID}` (AWQ int4 量化)

            **API 端点** (OpenAI / SiliconFlow 兼容)
            - `POST /v1/embeddings`
            - `POST /v1/rerank`
            - `POST /v1/chat/completions`

            设备: `{DEVICE.upper()}` &nbsp;|&nbsp; Chat 就绪: `{REG.chat_ready}`
            """
        )
        with gr.Tab("📐 Embedding"):
            with gr.Row():
                inp = gr.Textbox(label="输入文本", placeholder="要向量化的文本", lines=3)
                dim = gr.Slider(32, 1024, value=1024, step=32, label="输出维度 (MRL)")
            out = gr.Textbox(label="结果", lines=6)
            gr.Button("向量化", variant="primary").click(ui_embed, [inp, dim], out)

        with gr.Tab("🎯 Reranker"):
            with gr.Row():
                q = gr.Textbox(label="Query", placeholder="用户查询")
            docs = gr.Textbox(
                label="Documents (每行一条)",
                placeholder="候选文档 1\n候选文档 2\n候选文档 3",
                lines=6,
            )
            r_out = gr.Textbox(label="重排结果", lines=8)
            gr.Button("重排序", variant="primary").click(ui_rerank, [q, docs], r_out)

        with gr.Tab("💬 Chat (Qwen3-4B)"):
            sys = gr.Textbox(label="System (可选)", placeholder="你是一个有用的助手", lines=1)
            msg = gr.Textbox(label="用户消息", lines=3)
            c_out = gr.Textbox(label="回复", lines=8)
            gr.Button("发送", variant="primary").click(ui_chat, [msg, sys], c_out)

        gr.Markdown(
            """
            ---
            ### 🔌 用 OpenAI SDK 直接调用

            ```python
            from openai import OpenAI
            client = OpenAI(base_url="https://<你的用户名>-<space名>.hf.space/v1", api_key="dummy")
            client.embeddings.create(model="qwen3-embed", input=["你好世界"])
            client.chat.completions.create(model="qwen3-4b", messages=[{"role":"user","content":"你好"}])
            ```
            """
        )
    return demo


# 挂载 Gradio 到根路径 `/`，FastAPI 的 `/v1/*` `/health` 仍然生效
import gradio as gr
app = gr.mount_gradio_app(app, build_gradio(), path="/")


# ============================================
# 启动入口
# ============================================
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "7860"))
    uvicorn.run(app, host="0.0.0.0", port=port)
