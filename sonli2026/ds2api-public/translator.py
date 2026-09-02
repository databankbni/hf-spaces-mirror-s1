import os
import threading
from pathlib import Path

MODEL_REPO = os.getenv("MODEL_REPO", "mradermacher/translategemma-4b-it-GGUF")
MODEL_FILE = os.getenv("MODEL_FILE", "translategemma-4b-it.Q4_K_M.gguf")
_model = None
_lock = threading.Lock()


def engine_status():
    return f"Local CPU · TranslateGemma 4B Q4_K_M · {MODEL_REPO}"


def _load():
    global _model
    if _model is not None:
        return _model
    with _lock:
        if _model is not None:
            return _model
        from huggingface_hub import hf_hub_download
        from llama_cpp import Llama
        path = hf_hub_download(MODEL_REPO, MODEL_FILE)
        _model = Llama(model_path=path, n_ctx=2048, n_threads=2, n_batch=256, verbose=False)
    return _model


def translate_text(text: str, source: str = "en", target: str = "vi") -> str:
    if not text or not text.strip():
        return ""
    model = _load()
    prompt = (
        "<bos><start_of_turn>user\n"
        f"Translate the following text from {source} to {target}. "
        "Return only the translation. Preserve names, numbers, units, URLs, and line breaks.\n\n"
        f"{text.strip()}<end_of_turn>\n<start_of_turn>model\n"
    )
    result = model(prompt, max_tokens=min(1536, max(128, len(text) * 2)), temperature=0.1, stop=["<end_of_turn>"])
    return result["choices"][0]["text"].strip()

