"""
SimonLM Cloud — Hugging Face Space (ZeroGPU).

- Wheel llama-cpp-python CUDA (GPU gratuit via ZeroGPU)
- Interface Gradio (chat) + API OpenAI-compatible (/v1/chat/completions,
  /v1/models) pour que SimonLM local puisse router ses questions SIMPLE
  vers ce GPU au lieu de charger le 0.6B sur la machine.
- Le modèle est chargé une seule fois (cache global) et l'inférence passe par
  @spaces.GPU pour utiliser le GPU réel.

RÈGLE ZeroGPU : la fonction bindée aux événements Gradio (respond) DOIT être
décorée @spaces.GPU — le scan de démarrage ne détecte que les handlers
Gradio décorés. L'API utilise sa propre fonction décorée (même worker GPU).

Réglages via variables d'environnement : MODEL_REPO, MODEL_FILE, N_CTX,
N_THREADS, MAX_TOKENS, N_GPU_LAYERS.
"""
import ctypes
import glob
import os
import site
import time
import uuid

# --- Pré-chargement des libs CUDA (libcudart, libcublas) requises par llama-cpp-python ---
# L'image ZeroGPU embarque PyTorch + CUDA ; on localise et on charge les .so
# avant l'import de llama_cpp pour que ctypes les trouve.
def _preload_cuda_libs():
    dirs = []
    # torch/lib (présent dans l'image ZeroGPU)
    try:
        import torch
        dirs.append(os.path.join(os.path.dirname(torch.__file__), "lib"))
    except Exception:
        pass
    # packages nvidia installés par pip (nvidia-cuda-runtime-cu12, nvidia-cublas-cu12)
    for sp in site.getsitepackages():
        dirs.extend(glob.glob(os.path.join(sp, "nvidia", "*", "lib")))
    loaded = []
    for d in dirs:
        for so in sorted(glob.glob(os.path.join(d, "libcudart.so*")) +
                         glob.glob(os.path.join(d, "libcublas*.so*")) +
                         glob.glob(os.path.join(d, "libcuda.so*"))):
            try:
                ctypes.CDLL(so)
                loaded.append(os.path.basename(so))
            except Exception:
                pass
    return loaded

_preload_cuda_libs()

from typing import List

from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
import gradio as gr
from gradio.routes import App
try:  # spaces n'est garanti que sur les Spaces ZeroGPU ; absent sur CPU → OK
    import spaces
except Exception:  # noqa: BLE001
    spaces = None

MODEL_REPO = os.getenv("MODEL_REPO", "unsloth/Qwen3-0.6B-GGUF")
MODEL_FILE = os.getenv("MODEL_FILE", "Qwen3-0.6B-Q4_K_M.gguf")
N_CTX = int(os.getenv("N_CTX", "8192"))
N_THREADS = int(os.getenv("N_THREADS", "4"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "512"))
N_GPU_LAYERS = int(os.getenv("N_GPU_LAYERS", "-1"))  # -1 = tout sur GPU
API_MODEL_ID = os.getenv("API_MODEL_ID", "simonlm-0.6b")

_llm = None


def _install_no_think(llm):
    """Force enable_thinking=False dans le template Jinja2 Qwen3.

    llama-cpp-python 0.3.16 ne transmet pas `enable_thinking` au render du
    template. On sous-classe le formatter pour l'injecter : le template Qwen3
    pré-remplit alors un `<think>\n\n</think>` VIDE → le modèle répond
    directement, sans bloc <think> (aucun token GPU gaspillé, jamais de réponse
    tronquée en plein raisonnement).
    """
    from llama_cpp.llama_chat_format import (
        Jinja2ChatFormatter, ChatFormatterResponse,
    )
    import llama_cpp.llama as _llama_low

    class _NoThinkFormatter(Jinja2ChatFormatter):
        def __call__(self, *, messages, functions=None, function_call=None,
                     tools=None, tool_choice=None, **kwargs):
            def raise_exception(message: str):
                raise ValueError(message)
            prompt = self._environment.render(
                messages=messages,
                eos_token=self.eos_token,
                bos_token=self.bos_token,
                raise_exception=raise_exception,
                add_generation_prompt=self.add_generation_prompt,
                functions=functions,
                function_call=function_call,
                tools=tools,
                tool_choice=tool_choice,
                strftime_now=self.strftime_now,
                enable_thinking=False,
            )
            stopping_criteria = None
            if self.stop_token_ids is not None:
                def stop_on_last_token(tokens, logits):
                    return tokens[-1] in self.stop_token_ids
                stopping_criteria = _llama_low.StoppingCriteriaList(
                    [stop_on_last_token]
                )
            return ChatFormatterResponse(
                prompt=prompt,
                stop=[self.eos_token],
                stopping_criteria=stopping_criteria,
                added_special=True,
            )

    template = (llm.metadata or {}).get("tokenizer.chat_template")
    eos_id = llm.token_eos()
    bos_id = llm.token_bos()
    eos_token = llm._model.token_get_text(eos_id) if eos_id != -1 else ""
    bos_token = llm._model.token_get_text(bos_id) if bos_id != -1 else ""
    fmt = _NoThinkFormatter(
        template=template,
        eos_token=eos_token,
        bos_token=bos_token,
        add_generation_prompt=True,
        stop_token_ids=[eos_id],
    )
    llm.chat_handler = fmt.to_chat_handler()
    print("[SimonLM] Thinking Qwen3 désactivé (enable_thinking=False forcé)", flush=True)


def _get_llm():
    """Charge le modèle une seule fois (cache global, dans le worker GPU)."""
    global _llm
    if _llm is None:
        from llama_cpp import Llama

        print(f"[SimonLM] Chargement de {MODEL_REPO}/{MODEL_FILE} "
              f"(n_ctx={N_CTX}, gpu_layers={N_GPU_LAYERS})…", flush=True)
        _llm = Llama.from_pretrained(
            repo_id=MODEL_REPO,
            filename=MODEL_FILE,
            n_ctx=N_CTX,
            n_threads=N_THREADS,
            n_gpu_layers=N_GPU_LAYERS,
            verbose=False,
        )
        _install_no_think(_llm)
        print("[SimonLM] Modèle prêt (GPU)", flush=True)
    return _llm


def _infer(messages: list, max_tokens: int, temperature: float, top_p: float) -> str:
    """Inférence GPU brute (à appeler DANS une fonction @spaces.GPU)."""
    llm = _get_llm()
    out = llm.create_chat_completion(
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
    )
    return out["choices"][0]["message"].get("content", "")


def _split_think(text: str):
    """Sépare le bloc <think> Qwen3 : (reasoning, content)."""
    if "<think>" in text and "</think>" in text:
        reasoning, content = text.split("</think>", 1)
        reasoning = reasoning.replace("<think>", "").strip()
        return reasoning, content.lstrip("\n")
    return "", text


# ── Interface Gradio (chat humain) ────────────────────────────────────────────
# ⚠️ DÉCORÉ @spaces.GPU : le scan ZeroGPU ne détecte QUE les handlers Gradio
# décorés. respond est bindé à ChatInterface → c'est lui qui doit l'être.

_history: list = []


def respond(message: str, chat_history):
    global _history
    _history.append({"role": "user", "content": message})
    if len(_history) > 12:
        del _history[:2]
    try:
        raw = _infer(list(_history), max_tokens=MAX_TOKENS, temperature=0.7, top_p=0.9)
        _, content = _split_think(raw)
        reply = content
    except Exception as e:  # noqa: BLE001 — jamais planter l'interface
        reply = f"⚠️ Erreur : {e}"
    _history.append({"role": "assistant", "content": reply})
    return reply


demo = gr.ChatInterface(
    fn=respond,
    title="🤖 SimonLM Cloud",
    description=f"Assistant IA — modèle {MODEL_FILE} sur ZeroGPU (GPU gratuit HF Spaces).",
)


# ── API OpenAI-compatible ─────────────────────────────────────────────────────
# App = sous-classe FastAPI de Gradio → on y ajoute nos routes /v1/* puis on la
# passe à demo.launch(_app=...) : Gradio s'y monte et le scan ZeroGPU s'exécute.
app = App(title="SimonLM Cloud API")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = API_MODEL_ID
    messages: List[ChatMessage]
    temperature: float = 0.7
    top_p: float = 0.9
    max_tokens: int = MAX_TOKENS
    stream: bool = False


def _api_infer(messages: list, max_tokens: int, temperature: float, top_p: float) -> str:
    return _infer(messages, max_tokens, temperature, top_p)


@app.get("/v1/models")
def list_models():
    return JSONResponse({
        "object": "list",
        "data": [{
            "id": API_MODEL_ID,
            "object": "model",
            "owned_by": "simonlm",
        }],
    })


def _sse_chunks(content: str, model: str):
    """Découpe la réponse en fragments SSE (ressenti streaming)."""
    import json as _json
    frags = []
    for part in content.split(" "):
        frags.append(part + " " if part else " ")
    buf = ""
    for f in frags:
        buf += f
        if len(buf) >= 15:
            chunk = {
                "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {"content": buf},
                    "finish_reason": None,
                }],
            }
            yield f"data: {_json.dumps(chunk)}\n\n"
            buf = ""
    if buf:
        chunk = {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "delta": {"content": buf},
                "finish_reason": None,
            }],
        }
        yield f"data: {_json.dumps(chunk)}\n\n"
    done = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {_json.dumps(done)}\n\n"
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
def chat_completions(req: ChatRequest):
    raw_messages = [{"role": m.role, "content": m.content} for m in req.messages]
    try:
        raw = _api_infer(
            raw_messages,
            max_tokens=min(req.max_tokens, MAX_TOKENS),
            temperature=req.temperature,
            top_p=req.top_p,
        )
    except Exception as e:  # noqa: BLE001 — erreur propre côté client
        return JSONResponse({
            "error": {"message": f"Inférence GPU en échec : {e}", "type": "server_error"},
        }, status_code=500)

    reasoning, content = _split_think(raw)
    msg = {"role": "assistant", "content": content}
    if reasoning:
        msg["reasoning_content"] = reasoning

    if req.stream:
        return StreamingResponse(
            _sse_chunks(content, req.model),
            media_type="text/event-stream",
        )

    return JSONResponse({
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model,
        "choices": [{
            "index": 0,
            "message": msg,
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    })


# Lancement via demo.launch(_app=...) : le scan ZeroGPU s'exécute au launch()
# (gr.Blocks.launch est patché par le runtime) ET nos routes /v1/* sont montées
# sur la même app FastAPI que Gradio.
demo.launch(_app=app)
