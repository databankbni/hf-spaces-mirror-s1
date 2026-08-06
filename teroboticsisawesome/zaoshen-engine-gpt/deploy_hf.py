"""Deploy 造神引擎GPT版 to its Hugging Face Docker Space."""
import os

from huggingface_hub import HfApi, create_repo


REPO_ID = "teroboticsisawesome/zaoshen-engine-gpt"


def main():
    token = os.environ["HF_TOKEN"]
    create_repo(
        REPO_ID,
        repo_type="space",
        space_sdk="docker",
        private=False,
        exist_ok=True,
        token=token,
    )
    result = HfApi(token=token).upload_folder(
        folder_path=".",
        repo_id=REPO_ID,
        repo_type="space",
        ignore_patterns=[
            ".git/*",
            ".env",
            "data/saas.db",
            "__pycache__/*",
            "*.pyc",
            "build/*",
            "dist/*",
            "dist-installer/*",
            "dist-installer/*-1.0.0.exe",
            "dist-installer/*-1.1.0.exe",
            "dist-installer/*-1.2.0.exe",
            "dist-installer/*-1.2.1.exe",
            "dist-installer/*-1.2.2.exe",
            "static/brand/*-source.png",
            "data/fb_profile/*",
            "data/server.log",
            "runtime/*",
            "output/*",
        ],
        commit_message="Deploy unified content pool, Page Token and RPA 1.2.0",
    )
    print(result)


if __name__ == "__main__":
    main()
