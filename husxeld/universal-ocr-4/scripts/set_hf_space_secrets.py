#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]


def load_all_env() -> None:
    path = ROOT / ".env"
    if path.exists():
        load_dotenv(path, override=False)


def selected_secret_names() -> list[str]:
    patterns = [
        r"^HF_TOKEN$",
        r"^HF_USERNAME$",
        r"^HUGGING_FACE_HUB_TOKEN$",
        r"^NVAPI\d+$",
        r"^OLAPI\d+$",
        r"^OPAPI\d+$",
        r"^OPENROUTERAPI\d+$",
        r"^NVIDIA_API_KEY$",
        r"^KGSUI_AI_OLLAMA_KEY_\d+$",
        r"^KGSUI_AI_NVIDIA_KEY_\d+$",
    ]
    compiled = [re.compile(p) for p in patterns]
    return sorted(name for name, value in os.environ.items() if value and any(p.match(name) for p in compiled))


def selected_variables(repo_id: str) -> dict[str, str]:
    defaults = {
        "OCR_DATA_DIR": "/data/ocr-automation",
        "OCR_DEFAULT_ENGINE": os.getenv("OCR_DEFAULT_ENGINE", "auto"),
        "OCR_HF_STORAGE": "1",
        "OCR_HF_STORAGE_PRIVATE": os.getenv("OCR_HF_STORAGE_PRIVATE", "1"),
        "OCR_HF_STORAGE_PULL": os.getenv("OCR_HF_STORAGE_PULL", "1"),
        "HF_STORAGE_REPO_ID": os.getenv("HF_STORAGE_REPO_ID", f"{repo_id}-storage"),
        "OCR_PAGES_PER_CHUNK": os.getenv("OCR_PAGES_PER_CHUNK", "6"),
        "OCR_CHUNK_CONCURRENCY": os.getenv("OCR_CHUNK_CONCURRENCY", "1"),
        "OCR_AI_CONTEXT_MAX_CHARS": os.getenv("OCR_AI_CONTEXT_MAX_CHARS", "180000"),
        "OCR_AI_TIMEOUT_SECONDS": os.getenv("OCR_AI_TIMEOUT_SECONDS", "900"),
        "OCR_AI_PROVIDER": os.getenv("OCR_AI_PROVIDER") or os.getenv("KGSUI_AI_PROVIDER") or "nvidia",
        "OCR_AI_MODEL": os.getenv("OCR_AI_MODEL") or os.getenv("KGSUI_AI_MODEL") or "qwen/qwen3.5-397b-a17b",
        "OLMOCR_WEBSITE": os.getenv("OLMOCR_WEBSITE", "https://playground.allenai.org/model/olmocr-2-7b-1025"),
    }
    optional_names = [
        "OCR_AI_OLLAMA_TARGET",
        "OCR_AI_OLLAMA_MODELS",
        "OCR_AI_OPENROUTER_TARGET",
        "OCR_AI_OPENROUTER_MODEL",
        "OCR_AI_OPENROUTER_MODELS",
        "OCR_AI_NVIDIA_TARGET",
        "KGSUI_AI_OLLAMA_TARGET",
        "KGSUI_AI_OLLAMA_MODELS",
        "KGSUI_AI_OPENROUTER_TARGET",
        "KGSUI_AI_OPENROUTER_MODEL",
        "KGSUI_AI_OPENROUTER_MODELS",
        "KGSUI_AI_NVIDIA_TARGET",
        "KGSUI_AI_TIMEOUT_SECONDS",
        "OLLAMA_TARGET",
    ]
    for name in optional_names:
        value = os.getenv(name)
        if value:
            defaults[name] = value
    return {k: v for k, v in defaults.items() if v is not None and str(v).strip()}


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: set_hf_space_secrets.py <repo_id>")
    repo_id = sys.argv[1]
    load_all_env()
    token = os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN")
    if not token:
        raise SystemExit("Missing HF_TOKEN/HUGGING_FACE_HUB_TOKEN")
    api = HfApi(token=token)

    for name in selected_secret_names():
        api.add_space_secret(repo_id=repo_id, key=name, value=os.environ[name])
        print(f"secret set: {name}")

    for name, value in selected_variables(repo_id).items():
        api.add_space_variable(repo_id=repo_id, key=name, value=value)
        print(f"variable set: {name}")


if __name__ == "__main__":
    main()
