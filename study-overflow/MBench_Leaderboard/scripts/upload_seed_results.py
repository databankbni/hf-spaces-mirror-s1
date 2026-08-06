import os
import shutil
import sys
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from constants import LEADERBOARD_REPO


REPO_TYPE = "dataset"


def main() -> None:
    token = os.environ.get("HF_TOKEN")

    seed_results = ROOT / "seed" / "results.csv"
    if not seed_results.exists():
        raise FileNotFoundError(f"Seed file not found: {seed_results}")

    api = HfApi(token=token)
    try:
        api.whoami(token=token)
    except Exception as exc:
        raise RuntimeError(
            "HF_TOKEN is not set and no cached Hugging Face login was found. "
            "Please run `export HF_TOKEN=...` or `hf auth login` first."
        ) from exc

    api.create_repo(repo_id=LEADERBOARD_REPO, repo_type=REPO_TYPE, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="mbench_seed_") as tmp_dir:
        tmp_root = Path(tmp_dir)
        shutil.copy2(seed_results, tmp_root / "results.csv")

        pending_dir = tmp_root / "submissions" / "pending"
        verified_dir = tmp_root / "submissions" / "verified"
        pending_dir.mkdir(parents=True, exist_ok=True)
        verified_dir.mkdir(parents=True, exist_ok=True)
        (pending_dir / ".gitkeep").write_text("", encoding="utf-8")
        (verified_dir / ".gitkeep").write_text("", encoding="utf-8")

        api.upload_folder(
            folder_path=str(tmp_root),
            repo_id=LEADERBOARD_REPO,
            repo_type=REPO_TYPE,
            commit_message="Initialize MBench leaderboard seed results",
        )

    print(f"Uploaded seed results to {LEADERBOARD_REPO}: results.csv")
    print("Created submissions/pending/.gitkeep and submissions/verified/.gitkeep")


if __name__ == "__main__":
    main()
