import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import create_analysis, init_db
from app.extractor import build_job_payload
from app.scoring import evaluate_job


SEED_FILE = Path("seed/vagas_demo.csv")


def main() -> None:
    init_db()
    with SEED_FILE.open(encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            job = build_job_payload(row)
            create_analysis(job, evaluate_job(job))
    print(f"Seed concluido com dados de {SEED_FILE}")


if __name__ == "__main__":
    main()
