"""
One-time upload of the fine-tuned sentiment DistilBERT checkpoint
(app/model_output_v3) to a Hugging Face Hub model repo, so the Render
Docker build can pull it without committing 254MB to git.

Setup (once):
    pip install huggingface_hub
    huggingface-cli login          # paste a token from https://huggingface.co/settings/tokens

Usage:
    python scripts/upload_model_to_hf.py <your-username>/careertrust-sentiment-distilbert
"""

import sys
from pathlib import Path

from huggingface_hub import HfApi

MODEL_FILES = [
    "best.pt",
    "config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
]


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python upload_model_to_hf.py <username>/<repo-name>")
        sys.exit(1)

    repo_id = sys.argv[1]
    model_dir = Path(__file__).resolve().parents[1] / "app" / "model_output_v3"

    api = HfApi()
    api.create_repo(repo_id, repo_type="model", exist_ok=True)

    for filename in MODEL_FILES:
        path = model_dir / filename
        if not path.exists():
            print(f"Skipping missing file: {filename}")
            continue
        print(f"Uploading {filename}...")
        api.upload_file(path_or_fileobj=str(path), path_in_repo=filename, repo_id=repo_id)

    print(f"\nDone: https://huggingface.co/{repo_id}")
    print(f'Now set  ENV HF_MODEL_REPO="{repo_id}"  in backend-ai/Dockerfile.')


if __name__ == "__main__":
    main()
