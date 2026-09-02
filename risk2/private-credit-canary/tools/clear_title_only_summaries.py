"""[일회성] 옛 google rss 링크였던 해외 뉴스 행의 title_kr / summary_kr 비우기.

google news RSS 디코딩 백필 이전에 본문 추출 실패 → title 만으로 요약된 행들의
LLM 결과를 비워서, 다음 summarize_news.py 실행 시 본문 기반으로 재요약하게 함.

사용법
------
1) 코랩에서 백필 끝낸 후, Drive 의 history CSV 를 아직 로컬로 다운로드 하기 전에 실행
   (이때 로컬 CSV 의 link 컬럼은 여전히 google rss 형태)
2) venv\\Scripts\\python.exe tools\\clear_title_only_summaries.py
3) 그 다음 Drive 에서 history CSV 다운로드 → data/ 덮어쓰기 → summarize_news.py 실행
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

ROOT = Path(__file__).resolve().parents[1]
EN_FILE = ROOT / "data" / "private_credit_news_global_history.csv"


def main() -> int:
    if not EN_FILE.exists():
        print(f"[ERROR] 파일 없음: {EN_FILE}")
        return 1

    df = pd.read_csv(EN_FILE, encoding="utf-8-sig")
    print(f"전체 행수: {len(df)}")

    # google rss 였던 행 식별
    was_google = df["link"].astype(str).str.contains("news.google.com", na=False)
    print(f"google rss 링크 행: {was_google.sum()}건")

    if was_google.sum() == 0:
        print("\n[INFO] google rss 링크가 없습니다. 이미 디코딩된 CSV 인 것 같음.")
        print("       백업 파일 비교 방식이 필요하거나, 그냥 모든 행 비우기를 원하면")
        print("       아래 줄의 was_google 을 True 로 바꾸세요.")
        return 0

    # 비우기 전 통계
    for col in ["title_kr", "summary_kr"]:
        if col not in df.columns:
            continue
        filled = df.loc[was_google, col].astype(str).str.strip().ne("").sum()
        print(f"  {col} 채워진 google rss 행: {filled}건")

    # 비우기
    for col in ["title_kr", "summary_kr"]:
        if col in df.columns:
            df.loc[was_google, col] = ""

    df.to_csv(EN_FILE, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료 → {EN_FILE}")
    print(f"\n다음 단계: Drive 에서 백필된 history CSV 다운로드 → data/ 덮어쓰기 → ")
    print(f"          venv\\Scripts\\python.exe tools\\summarize_news.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
