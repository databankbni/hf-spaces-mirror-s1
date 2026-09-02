"""모든 batch 단계 (데이터 수집 + 요약 + 점수 산출) 완료 후 결과를 HF Space repo 로 push.

entrypoint.sh 의 마지막 batch 단계로 실행. summary_kr, risk_scores_history.json 등
이전 단계에서 생성된 모든 결과가 git 에 누적되도록 함.

환경변수:
    HF_TOKEN  — HF Write 토큰 (필수)
    HF_REPO_ID — push 대상 Space repo (기본: risk2/private-credit-canary)
"""

import os
import datetime
from pathlib import Path

HF_TOKEN = os.environ.get("HF_TOKEN")
HF_REPO_ID = os.environ.get("HF_REPO_ID", "risk2/private-credit-canary")
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def main() -> int:
    if not HF_TOKEN:
        print("[INFO] HF_TOKEN 환경변수 없음 — HF push 건너뜀")
        print("  HF Settings → Variables and secrets 에 HF_TOKEN (Write 권한) 추가하세요")
        return 0

    if not DATA_DIR.exists():
        print(f"[WARN] {DATA_DIR} 폴더 없음 — push 할 데이터 없음")
        return 0

    try:
        from huggingface_hub import HfApi
    except ImportError:
        print("[ERROR] huggingface_hub 패키지가 필요합니다 — requirements.txt 확인")
        return 1

    print("=" * 50)
    print(f"📤 Hugging Face Space ({HF_REPO_ID}) 로 최종 데이터 push...")
    print("=" * 50)

    api = HfApi()

    # Rebuild loop 방지는 데이터 dedup 으로 처리 (뉴스/공시 idempotent).
    # 동일 batch 결과 → CSV 동일 → huggingface_hub 자동 no-op (변경 없으면 commit 안 함).
    try:
        api.upload_folder(
            folder_path=str(DATA_DIR),
            path_in_repo="data",
            repo_id=HF_REPO_ID,
            repo_type="space",
            token=HF_TOKEN,
            commit_message=f"Auto data update {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
            # 중간 산출물 제외: today CSV, snippet JSON, zip 파일
            ignore_patterns=["*_today*.csv", "*.zip", "sec_filings_json/*", "*.backup.csv"],
        )
        print("✅ HF push 완료 — 데이터/요약/점수 모두 git 에 누적됨")
        return 0
    except Exception as e:
        print(f"[WARN] HF push 실패: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
