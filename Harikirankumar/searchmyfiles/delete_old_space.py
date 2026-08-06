import os
from pathlib import Path

from huggingface_hub import HfApi


def _load_env(path: Path) -> dict:
    out = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def main() -> None:
    env = _load_env(Path(__file__).resolve().parent / ".env")
    token = env.get("HF_TOKEN") or os.getenv("HF_TOKEN", "").strip()
    if not token:
        raise RuntimeError("HF_TOKEN missing in .env or environment")

    api = HfApi(token=token)
    old_repo = "Harikirankumar/portable-pytesseract-ocr-studio"
    api.delete_repo(repo_id=old_repo, repo_type="space")
    print(f"Deleted: {old_repo}")


if __name__ == "__main__":
    main()
