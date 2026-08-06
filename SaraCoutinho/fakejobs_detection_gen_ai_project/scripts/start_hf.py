import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import create_analysis, init_db, list_analyses
from app.extractor import build_job_payload
from app.scoring import evaluate_job
from app.server import run


def seed_if_empty() -> None:
    init_db()
    if list_analyses():
        return

    import csv

    seed_file = Path("seed/vagas_demo.csv")
    with seed_file.open(encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            job = build_job_payload(row)
            create_analysis(job, evaluate_job(job))


def main() -> None:
    seed_if_empty()
    port = int(os.environ.get("PORT", "7860"))
    run("0.0.0.0", port)


if __name__ == "__main__":
    main()
