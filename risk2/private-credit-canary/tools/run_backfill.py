"""tools/run_backfill.py — 4/23 ~ 5/6 영업일 backfill runner.

score_risk_test_gemma.py 를 각 영업일별로 --as-of-date 인자로 호출.
결과는 data/risk_scores_backfill.json 에 누적됨.

사용법:
    venv\\Scripts\\python.exe tools\\run_backfill.py

옵션:
    --start YYYY-MM-DD  (default 2026-04-23)
    --end   YYYY-MM-DD  (default 2026-05-06)
"""

from __future__ import annotations

import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

# Windows 콘솔 UTF-8 출력
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

ROOT = Path(__file__).resolve().parents[1]
SCORE_SCRIPT = ROOT / "tools" / "score_risk_test_gemma.py"
BACKFILL_OUT = ROOT / "data" / "risk_scores_backfill.json"


def _parse_arg(name: str, default: str) -> str:
    for i, a in enumerate(sys.argv):
        if a == name and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def _business_days(start: date, end: date):
    """월~금 영업일만 yield (US/KR 공휴일은 별도 처리 안 함 — 그날 데이터 없으면 carry_over)."""
    d = start
    while d <= end:
        if d.weekday() < 5:  # 0=월, 4=금
            yield d
        d += timedelta(days=1)


def main() -> int:
    start_str = _parse_arg("--start", "2026-04-23")
    end_str = _parse_arg("--end", "2026-05-06")
    start = date.fromisoformat(start_str)
    end = date.fromisoformat(end_str)

    dates = list(_business_days(start, end))
    print(f"=" * 60)
    print(f"Backfill runner — {len(dates)} 영업일")
    print(f"  range: {start} ~ {end}")
    print(f"  output: {BACKFILL_OUT}")
    print(f"=" * 60)

    # 이전 backfill 결과 삭제 (fresh start)
    if BACKFILL_OUT.exists():
        print(f"\n[INFO] 기존 backfill 파일 삭제: {BACKFILL_OUT.name}")
        BACKFILL_OUT.unlink()

    failed = []
    for i, d in enumerate(dates, 1):
        d_str = d.isoformat()
        print(f"\n{'#' * 60}")
        print(f"# [{i}/{len(dates)}] {d_str} ({['월','화','수','목','금','토','일'][d.weekday()]})")
        print(f"{'#' * 60}")
        result = subprocess.run(
            [sys.executable, str(SCORE_SCRIPT), "--as-of-date", d_str],
            cwd=ROOT,
        )
        if result.returncode != 0:
            print(f"[ERROR] {d_str} 실행 실패 (return code {result.returncode})")
            failed.append(d_str)

    print(f"\n{'=' * 60}")
    print(f"Backfill 완료 — {len(dates) - len(failed)} 성공 / {len(failed)} 실패")
    if failed:
        print(f"  실패한 날짜: {failed}")
    print(f"  결과 파일: {BACKFILL_OUT}")
    print(f"{'=' * 60}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
