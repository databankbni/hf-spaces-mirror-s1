import os
from pathlib import Path

from huggingface_hub import HfApi, upload_folder


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ[key] = value


def main() -> None:
    root = Path(__file__).resolve().parent
    _load_env_file(root / ".env")

    token = os.getenv("HF_TOKEN", "").strip()
    if not token:
        raise RuntimeError("HF_TOKEN is missing in .env")

    api = HfApi(token=token)
    explicit_repo_id = os.getenv("HF_SPACE_REPO_ID", "").strip()
    if explicit_repo_id:
        repo_id = explicit_repo_id
    else:
        who = api.whoami()
        username = who.get("name") or who.get("email")
        if not username:
            raise RuntimeError("Could not determine Hugging Face username from token")

        space_name = os.getenv("HF_SPACE_NAME", "searchmyfiles").strip()
        repo_id = f"{username}/{space_name}"

    try:
        api.repo_info(repo_id=repo_id, repo_type="space")
    except Exception as err:
        raise RuntimeError(
            "Target Space does not exist or is not accessible. "
            "Set HF_SPACE_REPO_ID=<username>/<space_name> (or HF_SPACE_NAME) to an existing Space. "
            f"Details: {err}"
        ) from err

    upload_folder(
        repo_id=repo_id,
        repo_type="space",
        folder_path=str(root),
        path_in_repo=".",
        token=token,
        ignore_patterns=[
            ".env",
            ".venv/**",
            ".git/**",
            ".vscode/**",
            "__pycache__/*",
            "**/__pycache__/**",
            "*.pyc",
            "*.pyo",
            "*.pyd",
            "*.log",
            "*.tmp",
            "*.bak",
            "*.swp",
            "*.swo",
            "*.zip",
            "*.vsix",
            "*.ipynb",
            "dist/**",
            "build/**",
            "node_modules/**",
            "vscode-chat-logger/**",
            "copilot_chat_export/**",
            "assets/**",
            "portable_tesseract/**",
            "Tesseract-OCR.zip",
            "ui_*_smoke_test.py",
            "_*.py",
        ],
        commit_message="Deploy Portable OCR Studio",
    )

    print(f"Deployed: https://huggingface.co/spaces/{repo_id}")


if __name__ == "__main__":
    main()
