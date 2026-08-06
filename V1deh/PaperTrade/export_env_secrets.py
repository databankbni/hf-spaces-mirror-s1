#!/usr/bin/env python3
"""Push local .env secrets to Hugging Face Spaces secrets.

Usage:
    python export_env_secrets.py [path/to/.env]

HF_TOKEN is read from .env first, then from the shell environment.
HF_REPO_ID can override the Space repo (default: V1deh/PaperTrade).
"""
import os
import sys

try:
    from huggingface_hub import HfApi
except ImportError:
    print("huggingface_hub not installed. Run: pip install huggingface_hub")
    sys.exit(1)

REPO_ID = os.environ.get("HF_REPO_ID", "V1deh/PaperTrade")
SPACE_URL = "https://v1deh-papertrade.hf.space"
ENV_FILE = sys.argv[1] if len(sys.argv) > 1 else ".env"


def parse_dotenv(path):
    env = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.split(" #")[0].strip()
            if (value.startswith('"') and value.endswith('"')) or \
               (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            if key:
                env[key] = value
    return env


if not os.path.exists(ENV_FILE):
    print(f"Error: {ENV_FILE} not found. Run from the project root.")
    sys.exit(1)

secrets = parse_dotenv(ENV_FILE)

# HF_TOKEN: .env takes priority, then shell environment
HF_TOKEN = secrets.get("HF_TOKEN") or os.environ.get("HF_TOKEN", "")

if not HF_TOKEN:
    print("Error: HF_TOKEN is required.")
    print("  Add it to .env:  HF_TOKEN=hf_your_token_here")
    print("  Or export it:    export HF_TOKEN=hf_your_token_here")
    sys.exit(1)

# Always inject the Space URL so app.py can print it on startup
secrets["SPACE_URL"] = SPACE_URL

api = HfApi(token=HF_TOKEN)
print(f"Pushing {len(secrets)} secrets to HF Space: {REPO_ID}\n")

failed = []
for key, value in secrets.items():
    if not value:
        print(f"  –  {key}  (empty — skipping)")
        continue
    try:
        api.add_space_secret(repo_id=REPO_ID, key=key, value=value)
        print(f"  ✓  {key}")
    except Exception as e:
        print(f"  ✗  {key}  ({e})")
        failed.append(key)

print()
if failed:
    print(f"WARNING: {len(failed)} secret(s) failed: {', '.join(failed)}")
    sys.exit(1)
else:
    print(f"All secrets uploaded successfully.")
    print(f"Space URL: {SPACE_URL}")
