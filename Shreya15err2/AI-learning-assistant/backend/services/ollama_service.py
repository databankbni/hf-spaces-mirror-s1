import requests
import json
from typing import Optional

# Using literal IPv4 address to prevent Windows DNS resolution issues
OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "gemma:2b"
FALLBACK_MODEL = "llama3:latest"

def is_ollama_running() -> bool:
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=0.5)
        return response.status_code == 200
    except Exception:
        return False

def get_available_models() -> list:
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2)
        if response.status_code == 200:
            data = response.json()
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        pass
    return []

def generate_response(
    prompt: str,
    model: str,
    system_prompt: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 512
) -> str:
    if not is_ollama_running():
        raise RuntimeError("Ollama is not running.")

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        }
    }

    if system_prompt:
        payload["system"] = system_prompt

    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json=payload,
            timeout=35
        )
        response.raise_for_status()
        data = response.json()
        return data.get("response", "").strip()
    except requests.exceptions.Timeout:
        raise RuntimeError(f"Ollama generation timed out for model {model}.")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Ollama request failed: {str(e)}")

def generate_with_fallback(
    prompt: str,
    system_prompt: Optional[str] = None,
    preferred_model: Optional[str] = None
) -> tuple:
    if not is_ollama_running():
        return None, "none"
        
    models = get_available_models()
    if not models:
        return None, "none"

    search_order = []
    if preferred_model and preferred_model in models:
        search_order.append(preferred_model)
        
    for m in [DEFAULT_MODEL, FALLBACK_MODEL, "gemma:latest", "llama3"]:
        for installed_model in models:
            if installed_model.startswith(m) and installed_model not in search_order:
                search_order.append(installed_model)

    for installed_model in models:
        if installed_model not in search_order:
            search_order.append(installed_model)

    for model in search_order:
        try:
            answer = generate_response(
                prompt=prompt,
                model=model,
                system_prompt=system_prompt
            )
            if answer:
                return answer, model
        except Exception:
            continue

    return None, "none"
