"""Google Drive 다운로드 정리 스크립트 (옵션 B).

전제: 브라우저 다운로드 위치를 data/ 폴더로 설정해 둔 상태.

매일 오전 워크플로우:
  1) 코랩 실행 → Google Drive 에 CSV 7개 갱신
  2) Drive 웹에서 사모대출_카나리아 폴더 또는 개별 파일 다운로드
     → 자동으로 data/ 폴더에 저장됨
  3) 이 스크립트 실행 (또는 sync_data.bat 더블클릭)
  4) streamlit 새로고침

처리 내용 (모두 data/ 폴더 안에서):
  - ZIP 파일이 있으면 안의 CSV 만 추출 → ZIP 삭제
  - " (1)", " (2)" 등 브라우저 suffix 가 붙은 CSV → 원래 이름으로 rename (덮어쓰기)
"""

from __future__ import annotations

import fnmatch
import re
import shutil
import sys
import zipfile

import pandas as pd
from pathlib import Path

# Windows 콘솔 한글 출력
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DATA_DIR.mkdir(exist_ok=True)
# 다운로드 위치 = data 폴더 (브라우저 다운로드 경로를 미리 설정해 둔 상태)
WORK_DIR = DATA_DIR

# 정리 대상 CSV 패턴
CSV_PATTERNS = [
    "private_credit_*.csv",
    "private_credit_sec_periodic_history*.csv",
]

# Drive 폴더 ZIP 다운로드 시 파일명 패턴 (한글·영문 모두 대응)
ZIP_PATTERNS = [
    "사모*.zip",
    "private_credit*.zip",
    "*카나리아*.zip",
]


def clean_filename(name: str) -> str:
    """' (1)', ' (2)' 같은 브라우저 다운로드 suffix 제거."""
    return re.sub(r" \(\d+\)", "", name)


def is_target_csv(name: str) -> bool:
    return any(fnmatch.fnmatch(name, p) for p in CSV_PATTERNS)


# 새 CSV 가 어제 CSV 를 덮어쓰기 직전에, 어제의 LLM 작업 결과를 새 CSV 에 매핑.
# pk 키로 매칭되는 행의 LLM 컬럼이 새 CSV 에서 비어있으면 어제 값을 미리 채움.
LLM_PRESERVE_CONFIG = {
    "private_credit_news_korea_history.csv":   ("link",             ["title_kr", "summary_kr"]),
    "private_credit_news_global_history.csv":  ("link",             ["title_kr", "summary_kr"]),
    "private_credit_sec_filings_history.csv":  ("accession_number", ["summary_kr", "summary_en"]),
}

# ★ today CSV → history CSV append 매핑 (append-only 모드)
# 코랩이 만드는 _today.csv 파일을 history.csv 에 추가만 하고 기존 LLM 결과는 절대 안 건드림.
# pk 충돌 시: 기존 (history) 우선 유지 → summary_kr 등 LLM 결과 보존됨.
TODAY_TO_HISTORY_MAP = {
    "private_credit_news_korea_today.csv":    ("private_credit_news_korea_history.csv",  "link"),
    "private_credit_news_global_today.csv":   ("private_credit_news_global_history.csv", "link"),
    "private_credit_sec_filings_today.csv":   ("private_credit_sec_filings_history.csv", "accession_number"),
    "private_credit_price_today.csv":         ("private_credit_price_history.csv",       None),  # 가격은 LLM 컬럼 없음
    # 정기공시 metrics 는 today/history 분리 안 함 — 코랩이 자체 dedup-merge 후
    # private_credit_sec_periodic_history.csv 한 파일을 그대로 누적해 내려보냄.
}

# ★ (1) suffix 파일을 단순 덮어쓰기 대신 append-only merge 로 처리할 파일들.
# Colab 이 cumulative history 를 통째로 내려보내는데, 로컬에서 수기 추가한
# 과거 데이터 (예: '25년 3분기 수기 입력) 가 덮어쓰기로 사라지는 것 방지.
# 값: 복합 키 (pk_cols) 튜플 — 이 키로 dedup 하여 새 행만 append.
SUFFIXED_MERGE_MAP = {
    "private_credit_sec_periodic_history.csv": ("cik", "form", "period_end"),
}

# ★ history 데이터 보관 기간 — 최근 20영업일 외 옛 데이터 자동 삭제.
# 대시보드 14일치 표시보다 약간 여유 둠 (실 영업일 기준 약 4주 ≈ 28일).
# (date_column, business_days) 매핑. price/periodic 은 차트 1년치 필요해서 제외.
RETENTION_CONFIG = {
    "private_credit_news_korea_history.csv":   ("published_at", 20),
    "private_credit_news_global_history.csv":  ("published_at", 20),
    "private_credit_sec_filings_history.csv":  ("filing_date",  20),
}


def preserve_llm_columns_on_overwrite(new_path: Path, target_path: Path,
                                       pk_col: str, llm_cols: list[str]) -> None:
    """new_path (예: '...history (1).csv') 를 target_path (예: '...history.csv') 로 덮어쓰기 전,
    target 의 LLM 컬럼 값을 pk 로 매핑해 new 에 미리 채움. new 에는 자체적으로 LLM 컬럼이 없거나
    비어있는 경우만 채움. target 이 없으면 (첫 실행 등) 아무 작업 안 함.
    """
    if not target_path.exists() or not new_path.exists():
        return
    try:
        old_df = pd.read_csv(target_path, encoding="utf-8-sig")
        new_df = pd.read_csv(new_path, encoding="utf-8-sig")
    except Exception as exc:  # noqa: BLE001
        print(f"  [WARN] LLM 보존 — CSV 읽기 실패 ({exc})")
        return

    if pk_col not in old_df.columns or pk_col not in new_df.columns:
        return

    # 신규 df 에 LLM 컬럼이 없으면 빈 컬럼으로 추가
    for col in llm_cols:
        if col not in new_df.columns:
            new_df[col] = ""

    old_df[pk_col] = old_df[pk_col].fillna("").astype(str).str.strip()
    new_df[pk_col] = new_df[pk_col].fillna("").astype(str).str.strip()

    preserved_count = 0
    for col in llm_cols:
        if col not in old_df.columns:
            continue
        # 어제 채워진 값만 매핑 대상
        old_filled = old_df[old_df[col].fillna("").astype(str).str.strip() != ""]
        mapping = old_filled.set_index(pk_col)[col].to_dict()
        if not mapping:
            continue

        # new_df 의 LLM 값이 비어있을 때만 mapping 적용
        def _fill(row, c=col, m=mapping):
            cur = row[c]
            if isinstance(cur, str) and cur.strip():
                return cur
            return m.get(row[pk_col], cur)

        before = new_df[col].fillna("").astype(str).str.strip().ne("").sum()
        new_df[col] = new_df.apply(_fill, axis=1)
        after = new_df[col].fillna("").astype(str).str.strip().ne("").sum()
        preserved_count += (after - before)

    if preserved_count > 0:
        new_df.to_csv(new_path, index=False, encoding="utf-8-sig")
        print(f"  [PRESERVE] {target_path.name}: 어제 LLM 결과 {preserved_count} 컬럼 값 보존")


def rename_to_clean(src: Path) -> bool:
    """src 파일명에 (1) 같은 suffix 가 있으면 원래 이름으로 rename (덮어쓰기)."""
    clean_name = clean_filename(src.name)
    if clean_name == src.name:
        return False  # 이미 깨끗
    dst = src.parent / clean_name
    if dst.exists():
        dst.unlink()  # 기존 파일 덮어쓰기
    src.rename(dst)
    print(f"  rename: {src.name} → {clean_name}")
    return True


def trim_old_rows(history_path: Path, date_col: str, business_days: int) -> int:
    """history.csv 에서 최근 N영업일 데이터만 남기고 옛 행 삭제.

    기준: 파일 내 최신 날짜(max) 에서 N영업일 거슬러간 시점.
    (영업일 기준 — 주말 제외해서 실 거래일 N일치 보장. 캘린더 ≈ N×7/5 일)
    (오늘 날짜가 아닌 max 사용 — 배치 며칠 안 돌렸어도 최근 데이터는 보존)

    반환: 삭제된 행 수.
    """
    if not history_path.exists():
        return 0
    try:
        df = pd.read_csv(history_path, encoding="utf-8-sig")
    except Exception as exc:  # noqa: BLE001
        print(f"  [WARN] {history_path.name} 읽기 실패: {exc}")
        return 0
    if df.empty or date_col not in df.columns:
        return 0

    # 날짜 컬럼 파싱 — 잘못된 값은 dropna 로 버림
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    before_total = len(df)
    df = df.dropna(subset=[date_col]).copy()
    if df.empty:
        return 0

    # 영업일 기준 cutoff — pandas BDay offset 사용 (주말 제외)
    from pandas.tseries.offsets import BDay
    latest = df[date_col].max()
    cutoff = latest - BDay(business_days)
    df_kept = df[df[date_col] >= cutoff].copy()
    removed = before_total - len(df_kept)

    if removed > 0:
        df_kept.to_csv(history_path, index=False, encoding="utf-8-sig")
        print(f"  [TRIM] {history_path.name}: 최근 {business_days}영업일 외 {removed}건 삭제 "
              f"(남은 {len(df_kept)}건, cutoff={cutoff.strftime('%Y-%m-%d')})")
    return removed


def merge_today_into_history(today_path: Path, history_path: Path,
                              pk_col: str | tuple | list | None) -> int:
    """today CSV 의 신규 행을 history CSV 에 append. LLM 컬럼은 절대 덮어쓰지 않음.

    동작:
      1. history 가 없으면 today 를 그대로 history 로 복사
      2. history 가 있으면:
         - pk_col 기준으로 history 에 없는 행만 append (단일 컬럼 또는 복합 키 지원)
         - history 의 기존 행은 그대로 (summary_kr 등 LLM 결과 보존)
      3. today 파일은 처리 후 삭제 (다음날 다시 받기 위함)

    pk_col 이 None 이면 단순 concat 후 (base_dt, ticker) 같은 추측 키로 dedup.
    pk_col 이 tuple/list 면 해당 컬럼들의 값을 "|" 로 join 한 복합 키로 dedup.

    반환: append 된 신규 행 수.
    """
    if not today_path.exists():
        return 0

    try:
        today_df = pd.read_csv(today_path, encoding="utf-8-sig")
    except Exception as exc:  # noqa: BLE001
        print(f"  [WARN] today 읽기 실패: {today_path.name} ({exc})")
        return 0

    if today_df.empty:
        print(f"  [SKIP] {today_path.name} 비어있음")
        today_path.unlink()
        return 0

    # Unnamed 컬럼 제거
    today_df = today_df.loc[:, ~today_df.columns.str.contains("^Unnamed", case=False)]

    if not history_path.exists():
        # history 없으면 today 를 그대로 history 로
        today_df.to_csv(history_path, index=False, encoding="utf-8-sig")
        added = len(today_df)
        print(f"  [INIT] {history_path.name} 생성 — {added}건")
        today_path.unlink()
        return added

    try:
        history_df = pd.read_csv(history_path, encoding="utf-8-sig")
        history_df = history_df.loc[:, ~history_df.columns.str.contains("^Unnamed", case=False)]
    except Exception as exc:  # noqa: BLE001
        print(f"  [WARN] history 읽기 실패 ({exc}) → today 로 덮어씀")
        today_df.to_csv(history_path, index=False, encoding="utf-8-sig")
        today_path.unlink()
        return len(today_df)

    # 복합 키 → 컬럼 리스트로 정규화 (단일 키도 동일 처리)
    pk_cols: list[str] = []
    if isinstance(pk_col, (tuple, list)):
        pk_cols = [c for c in pk_col]
    elif isinstance(pk_col, str):
        pk_cols = [pk_col]

    # pk 가 있고 양쪽 모두 컬럼 보유 → 복합 키 문자열 ("|" join) 로 dedup
    if pk_cols and all(c in history_df.columns and c in today_df.columns for c in pk_cols):
        for c in pk_cols:
            history_df[c] = history_df[c].fillna("").astype(str).str.strip()
            today_df[c] = today_df[c].fillna("").astype(str).str.strip()
        history_keys = history_df[pk_cols].agg("|".join, axis=1)
        today_keys = today_df[pk_cols].agg("|".join, axis=1)
        existing = set(history_keys)
        new_rows = today_df[~today_keys.isin(existing)]
    else:
        # pk 없거나 컬럼 누락 → 합치고 (base_dt, ticker) 같은 추측 키로 dedup
        new_rows = today_df

    if new_rows.empty:
        print(f"  [SKIP] {today_path.name} — 모두 이미 history 에 있음")
        today_path.unlink()
        return 0

    # 합치기 — concat (LLM 컬럼은 history 의 기존 값 그대로)
    merged = pd.concat([history_df, new_rows], ignore_index=True)

    # 가격 데이터 (pk 가 None) 인 경우 (base_dt, ticker) dedup
    if pk_col is None and {"base_dt", "ticker"}.issubset(merged.columns):
        merged = merged.drop_duplicates(subset=["base_dt", "ticker"], keep="first")

    merged.to_csv(history_path, index=False, encoding="utf-8-sig")
    added = len(new_rows)
    print(f"  [APPEND] {today_path.name} → {history_path.name}: {added}건 신규 추가 "
          f"(history 총 {len(merged)}건)")

    # today 파일 삭제 — 다음 날 새로 받기 위함
    today_path.unlink()
    return added


def extract_zip(zip_path: Path) -> int:
    """ZIP 안의 대상 CSV 만 추출해서 data/ 로 풀고 ZIP 삭제."""
    extracted = 0
    print(f"unzip: {zip_path.name}")
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            if not member.lower().endswith(".csv"):
                continue
            name = Path(member).name
            if not is_target_csv(name):
                continue
            target = DATA_DIR / clean_filename(name)
            with zf.open(member) as src_f, open(target, "wb") as dst_f:
                shutil.copyfileobj(src_f, dst_f)
            print(f"  추출: {target.name}")
            extracted += 1
    zip_path.unlink()
    print(f"  ZIP 삭제: {zip_path.name}")
    return extracted


def main() -> int:
    """다운로드 폴더 정리. 처리한 파일 수 반환. 함수형으로 호출 가능 (sys.exit 안 함)."""
    print(f"data 폴더: {DATA_DIR}\n")

    if not WORK_DIR.exists():
        print(f"[ERROR] 폴더가 없습니다: {WORK_DIR}")
        return 0

    processed = 0

    # 1) ZIP 풀기 (먼저 — 풀린 CSV 도 같은 폴더에 떨어짐)
    for pattern in ZIP_PATTERNS:
        for zip_path in WORK_DIR.glob(pattern):
            processed += extract_zip(zip_path)

    # 2) (1), (2) suffix 가 붙은 CSV 정리
    #    rename 직전에 어제 CSV 의 LLM 컬럼 값을 새 CSV 에 매핑해 보존 (LLM 재호출 방지)
    for pattern in CSV_PATTERNS:
        for src in WORK_DIR.glob(pattern):
            if " (" not in src.name:
                continue
            clean_name = clean_filename(src.name)
            target = src.parent / clean_name

            # ★ SUFFIXED_MERGE_MAP 에 등록된 파일 — 덮어쓰기 대신 append-only merge.
            #   Colab 이 cumulative 로 내려보낸 신규 (1) 파일과 기존 history 를 복합 키로
            #   합쳐, 기존 행 (수기 입력 포함) 보존하고 신규 행만 추가.
            if clean_name in SUFFIXED_MERGE_MAP:
                pk_col = SUFFIXED_MERGE_MAP[clean_name]
                added = merge_today_into_history(src, target, pk_col)
                if added > 0:
                    processed += 1
                continue  # merge_today_into_history 가 src 삭제까지 처리

            # ★ LLM 컬럼 보존 — 덮어쓰기 전에 어제 값 미리 적용
            if clean_name in LLM_PRESERVE_CONFIG:
                pk_col, llm_cols = LLM_PRESERVE_CONFIG[clean_name]
                preserve_llm_columns_on_overwrite(src, target, pk_col, llm_cols)

            if rename_to_clean(src):
                processed += 1

    # 3) ★ today CSV → history CSV append (append-only 모드)
    #    코랩이 만든 _today.csv 를 받았을 때, 기존 history 의 LLM 결과를 절대 안 건드리고 신규만 추가
    for today_name, (history_name, pk_col) in TODAY_TO_HISTORY_MAP.items():
        today_path = WORK_DIR / today_name
        if not today_path.exists():
            continue
        history_path = WORK_DIR / history_name
        added = merge_today_into_history(today_path, history_path, pk_col)
        if added > 0:
            processed += 1

    # 4) ★ history 보관 기간 정리 — 최근 20영업일 외 옛 데이터 자동 삭제
    #    (대시보드는 14일치 표시 — 영업일 20일이면 캘린더 ~28일로 안전 마진 확보)
    for fname, (date_col, business_days) in RETENTION_CONFIG.items():
        history_path = WORK_DIR / fname
        trim_old_rows(history_path, date_col, business_days)

    if processed == 0:
        print("(처리할 파일이 없습니다 — data/ 폴더에 ZIP, (1) 붙은 CSV, 또는 _today.csv 가 있어야 함)")
    else:
        print(f"\n완료: {processed} 건 정리됨")

    return processed


if __name__ == "__main__":
    main()
