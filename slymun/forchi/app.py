import os
import threading
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from llama_cpp import Llama
import uvicorn

MODEL_PATH = os.environ.get("MODEL_PATH", "/models/Qwen2.5-7B-Instruct-Q4_K_M.gguf")
N_CTX = int(os.environ.get("N_CTX", "4096"))
PORT = int(os.environ.get("PORT", "7860"))

app = FastAPI()

_llm = None
_loading = False


def _load_model():
    global _llm, _loading
    _loading = True
    try:
        print("[llm] Loading Qwen2.5-7B into memory (this takes ~1-2 min)...", flush=True)
        _llm = Llama(model_path=MODEL_PATH, n_ctx=N_CTX, n_gpu_layers=0, verbose=False)
        print("[llm] Model loaded and ready.", flush=True)
    except Exception as e:
        print(f"[llm] Model load FAILED: {e}", flush=True)
        _llm = None
    finally:
        _loading = False


@app.on_event("startup")
def _startup():
    # Start model load in background so health checks respond immediately.
    threading.Thread(target=_load_model, daemon=True).start()


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": _llm is not None, "loading": _loading}


@app.get("/")
def root():
    return {"status": "ok", "service": "forchi-llm", "model": "Qwen2.5-7B-Instruct"}


@app.get("/v1/models")
def list_models():
    return {
        "object": "list",
        "data": [{"id": "qwen2.5-7b", "object": "model", "owned_by": "qwen"}],
    }


# UptimeRobot / uptime monitors probe with HEAD requests; FastAPI would 405 them.
@app.head("/")
@app.head("/health")
@app.head("/v1/models")
def head_endpoints():
    return Response(status_code=200)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": {"message": "Invalid JSON body"}})

    if _llm is None:
        return JSONResponse(status_code=503, content={"error": {"message": "Model is still loading. Try again shortly."}})

    messages = body.get("messages", [])
    if not messages:
        return JSONResponse(status_code=400, content={"error": {"message": "messages is required"}})

    max_tokens = int(body.get("max_tokens", 600))
    temperature = float(body.get("temperature", 0.7))

    try:
        output = _llm.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return output
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": {"message": str(e)}})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
