#!/usr/bin/env python3
"""Quick diagnostic: check if OLLAMA_ENDPOINT is configured and Ollama is reachable."""

import os
import sys

def check_config():
    # 1. Check env var
    ollama_endpoint = os.environ.get("OLLAMA_ENDPOINT", "").strip()

    if not ollama_endpoint:
        print("❌ OLLAMA_ENDPOINT is NOT set")
        print("\n📝 FIX: Add to HF Spaces Secrets:")
        print("   Key: OLLAMA_ENDPOINT")
        print("   Value: https://your-ollama-space.hf.space")
        print("\n   Then restart the PaperTrade Space.")
        return False

    print(f"✅ OLLAMA_ENDPOINT = {ollama_endpoint}")

    # 2. Test connectivity
    try:
        import requests
        resp = requests.get(f"{ollama_endpoint}/api/tags", timeout=15)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            model_names = [m["name"] for m in models]
            print(f"✅ Ollama is reachable. Models: {model_names}")
            return True
        else:
            print(f"❌ Ollama returned {resp.status_code}: {resp.text[:100]}")
            return False
    except Exception as e:
        print(f"❌ Cannot reach Ollama: {e}")
        print("   Check that OLLAMA_ENDPOINT URL is correct and Ollama Space is running.")
        return False

if __name__ == "__main__":
    success = check_config()
    sys.exit(0 if success else 1)
