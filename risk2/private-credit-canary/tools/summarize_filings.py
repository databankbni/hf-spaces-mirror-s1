"""SEC 공시 extracted_json → 음슴체 짧은 요약 (summary_kr / summary_en) 생성.

전제:
  - 코랩이 `extracted_json` 컬럼에 Gemini(Gemma) 의 5문장 EN + 5문장 KR(음슴체) 원본 요약을
    저장한 상태로 Drive 에 업로드.
  - 본 스크립트는 그 컬럼을 입력으로 받아 짧은 정제 요약을 생성.

처리 내용:
  - private_credit_sec_filings_history.csv 의 각 행에 대해:
    · summary_kr / summary_en 둘 다 비어있고 extracted_json 이 채워져 있으면 처리 대상
    · Gemini 2.5 Flash-Lite 로 음슴체 한국어 2문장 (~140자) + 영문 1-2문장 출력
    · summary_kr, summary_en 컬럼 갱신
  - 이미 채워진 행은 스킵 (idempotent — 재실행해도 안전)
  - 매 행 CSV 저장 → 중단되어도 진행 보존, 재시작 시 이어감

사용법
------
1) Gemini API 키: 프로젝트 루트의 .env 에 GEMINI_API_KEY=xxxx (이미 있을 것)
2) 의존성: google-genai, truststore (이미 설치됨)
3) 실행:
     venv\\Scripts\\python.exe tools\\summarize_filings.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

# 사내 SSL 인터셉트(자체서명 CA) 환경 대응
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

# Windows 콘솔 한글 출력
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

# 모델 fallback 체인 — 첫 모델 일일 quota 소진 시 다음 모델로 자동 전환
# .env 의 GEMINI_MODELS_FALLBACK="gemini-2.5-flash-lite,gemma-3-27b-it" 형태로 override 가능
MODELS_FALLBACK = [
    "gemini-2.5-flash-lite",
    "gemma-4-31b-it",         # quota 초과 시 fallback (사용자 코랩과 동일)
]
MAX_INPUT_CHARS = 8000          # extracted_json 입력 최대 길이
SLEEP_BETWEEN_CALLS = 13.0      # 무료 티어 RPM=5 → 12초/건 + 여유
MAX_RETRY = 3
MAX_OUTPUT_CHARS = 180          # SEC 요약은 뉴스(140)보다 약간 길게

FILINGS_FILE = DATA / "private_credit_sec_filings_history.csv"

CSV_BINARY_MAGIC = b"SCDSA"   # SoftCamp DRM 봉인 매직 — CSV 가 아니므로 거른다.


def _read_csv_safely(path):
    """SCDSA 봉인이나 인코딩 오류 시 빈 DF 반환 (스크립트 죽지 않게)."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
        if head.startswith(CSV_BINARY_MAGIC) or b"\x00" in head:
            print(f"  [WARN] {path.name} 봉인된 파일 (SCDSA) — 처리 스킵", flush=True)
            return pd.DataFrame()
    except OSError:
        return pd.DataFrame()

    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return pd.read_csv(path, encoding=enc)
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
        except Exception:  # noqa: BLE001
            return pd.DataFrame()
    return pd.DataFrame()


# 정기공시는 별도 (Claude 지표 추출) → summary_*는 채울 필요 없음
PERIODIC_FORMS = {"10-K", "10-Q", "10-K/A", "10-Q/A"}

# 입력이 무의미한 표시값들
EMPTY_SENTINELS = {"", "LLM_OUTPUT_EMPTY"}


# ---------------------------------------------------------------------------
# 환경 변수 로딩 (.env 단순 파서)
# ---------------------------------------------------------------------------

def _load_env_file() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k.strip(), v)


_load_env_file()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# .env 에 GEMINI_MODELS_FALLBACK 가 있으면 override
_env_fallback = os.environ.get("GEMINI_MODELS_FALLBACK", "").strip()
if _env_fallback:
    MODELS_FALLBACK = [m.strip() for m in _env_fallback.split(",") if m.strip()]

# 현재 활성 모델 인덱스 (호출 중 quota 초과 발생 시 +1 로 fallback)
_ACTIVE_MODEL_IDX = 0
if not GEMINI_API_KEY:
    print(
        "[ERROR] GEMINI_API_KEY 가 설정되지 않았습니다.\n"
        "  - 환경변수 또는 프로젝트 루트의 .env 파일에 키를 넣어주세요.\n"
        "  - 키 발급: https://aistudio.google.com/apikey",
        file=sys.stderr,
    )
    sys.exit(1)


try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    print(
        "[ERROR] google-genai 패키지가 필요합니다.\n"
        "  venv\\Scripts\\pip.exe install google-genai",
        file=sys.stderr,
    )
    sys.exit(1)

client = genai.Client(api_key=GEMINI_API_KEY)


# ---------------------------------------------------------------------------
# LLM 호출
# ---------------------------------------------------------------------------

PROMPT = """You are reading a draft SEC filing summary that was produced by another LLM
(it may contain reasoning notes, format markers like 'Summary (EN):', 'Summary (KR):',
or stray tokens). Your job is to produce a clean, concise final summary as JSON.

Output JSON with exactly two fields:

- "summary_kr": Korean 1-3 sentence summary in 음슴체 (concise written style).
  STYLE RULES (MUST FOLLOW):
    * End each sentence with -음 / -했음 / -임 / -됨 forms.
    * Examples: "발표함.", "하락했음.", "예정임.", "확대됨.", "공시함."
    * NEVER use polite forms like "-습니다", "-합니다" or formal "-한다", "-된다", "-이다".
  NAME RULES (CRITICAL):
    * Keep ALL asset manager / fund / BDC / ticker names in their ORIGINAL English form.
      Do NOT translate, transliterate, or hangul-ize them.
    * Examples (correct — leave as-is): "Blue Owl", "Blackstone", "Ares", "Apollo", "KKR",
      "Blue Owl Capital Corp", "Blackstone Private Credit Fund", "Ares Capital Corporation",
      "OBDC", "OBDC II", "OCIC", "OTIC", "BCRED", "ARCC", "FSK", "BXSL", "OTF", "BIZD".
    * Examples (wrong — never produce these): "블루아울", "블랙스톤", "아레스", "아폴로",
      "케이케이알", "아레스 캐피탈 코퍼레이션".
    * Other proper nouns (regulators like SEC/Fed, country names, generic terms) may follow
      normal Korean conventions.
  LENGTH RULES (CRITICAL):
    * Total under 180 characters including spaces — count carefully.
    * Each sentence MUST end with a period — NEVER cut mid-sentence.
    * If 3 sentences exceed 180 chars, use fewer (1-2) complete sentences.
  CONTENT RULES:
    * Factual; preserve numbers, names, key actions.
    * Remove opinion / embellishment / drafting notes.

- "summary_en": English 1-2 sentence summary.
  LENGTH RULES (CRITICAL):
    * Total under 220 characters including spaces.
    * Each sentence MUST end with a period — complete sentences only.
  CONTENT RULES:
    * Factual, concise; preserve numbers/names/key actions.

Source draft (from prior LLM):
---
{draft}
---

Output JSON only — no other text."""


def _wait_for_retry(exc: Exception, attempt: int) -> float | None:
    msg = str(exc)
    if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
        m = re.search(r"retry(?:Delay)?[:\s\"']+(\d+(?:\.\d+)?)\s*s", msg, re.IGNORECASE)
        if m:
            return float(m.group(1)) + 1.0
        return 60.0
    if "UNAVAILABLE" in msg or "503" in msg or "deadline" in msg.lower():
        return min(30.0, 5.0 * (2 ** attempt))
    # SSL / 네트워크 단절 — 일시적 transport 에러로 재시도 (사내망 TLS 검사 충돌 등)
    msg_lower = msg.lower()
    if (
        "ssl" in msg_lower
        or "eof occurred" in msg_lower
        or "connection reset" in msg_lower
        or "connection aborted" in msg_lower
        or "remotedisconnected" in msg_lower
        or "read timed out" in msg_lower
        or "broken pipe" in msg_lower
        or "transport closing" in msg_lower
    ):
        return min(20.0, 3.0 * (2 ** attempt))  # 3, 6, 12
    return None


def _call_llm(make_request):
    """주어진 함수를 호출하되 429/503 에러 시 자동 재시도."""
    for attempt in range(MAX_RETRY):
        try:
            result = make_request()
            if attempt > 0:
                print(f"    재시도 성공 (시도 {attempt + 1}/{MAX_RETRY})", flush=True)
            return result
        except Exception as exc:  # noqa: BLE001
            wait = _wait_for_retry(exc, attempt)
            if wait is None or attempt == MAX_RETRY - 1:
                raise
            print(f"    재시도 대기 {wait:.0f}s ({attempt + 1}/{MAX_RETRY})", flush=True)
            time.sleep(wait)
    return None


def _log(msg: str) -> None:
    print(msg, flush=True)


def _is_quota_error(exc: Exception) -> bool:
    """일일 quota 초과(RESOURCE_EXHAUSTED) 여부."""
    msg = str(exc)
    return "RESOURCE_EXHAUSTED" in msg or "429" in msg


def _generate_with_model(prompt: str, model: str):
    """모델별로 호출. Gemma 는 JSON 모드 미지원 가능 → 텍스트 모드로."""
    config = None
    if model.startswith("gemini"):
        config = genai_types.GenerateContentConfig(
            response_mime_type="application/json",
        )
    return client.models.generate_content(
        model=model, contents=prompt, config=config,
    )


def _parse_json_response(raw: str) -> tuple[str, str]:
    """LLM 응답을 JSON 으로 파싱 → (summary_kr, summary_en)."""
    if not raw:
        return "", ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        l, r = raw.find("{"), raw.rfind("}")
        if l == -1 or r == -1:
            return "", ""
        try:
            data = json.loads(raw[l : r + 1])
        except json.JSONDecodeError:
            return "", ""
    if isinstance(data, list):
        data = next((x for x in data if isinstance(x, dict)), {})
    if not isinstance(data, dict):
        return "", ""
    return (data.get("summary_kr") or "").strip(), (data.get("summary_en") or "").strip()


def summarize(draft: str) -> tuple[str, str]:
    """extracted_json (raw draft) → (summary_kr, summary_en) 튜플.

    현재 활성 모델로 시도 → quota 초과(429) 면 다음 fallback 모델로 자동 전환.
    한 번 전환된 활성 모델은 같은 실행 내내 유지 (전역 _ACTIVE_MODEL_IDX).
    """
    global _ACTIVE_MODEL_IDX
    prompt = PROMPT.format(draft=(draft or "")[:MAX_INPUT_CHARS])

    while _ACTIVE_MODEL_IDX < len(MODELS_FALLBACK):
        model = MODELS_FALLBACK[_ACTIVE_MODEL_IDX]
        try:
            resp = _call_llm(lambda: _generate_with_model(prompt, model))
            if not resp:
                return "", ""
            return _parse_json_response((resp.text or "").strip())

        except Exception as exc:  # noqa: BLE001
            if _is_quota_error(exc):
                _log(f"[FALLBACK] '{model}' quota 초과 → 다음 모델로 전환")
                _ACTIVE_MODEL_IDX += 1
                if _ACTIVE_MODEL_IDX >= len(MODELS_FALLBACK):
                    _log("[ERROR] 모든 fallback 모델 quota 소진")
                    return "", ""
                # 다음 모델로 즉시 재시도 (같은 행)
                continue
            # quota 외 다른 에러는 호출자에게 전파
            raise

    return "", ""


# ---------------------------------------------------------------------------
# 처리 파이프라인
# ---------------------------------------------------------------------------

def _is_filled(v) -> bool:
    return isinstance(v, str) and bool(v.strip()) and v.strip() not in EMPTY_SENTINELS


def main() -> int:
    if not FILINGS_FILE.exists():
        _log(f"[ERROR] 파일 없음: {FILINGS_FILE}")
        return 0

    _log(f"모델 fallback 체인: {' → '.join(MODELS_FALLBACK)}")
    _log(f"시작 활성 모델:    {MODELS_FALLBACK[_ACTIVE_MODEL_IDX]}\n")

    df = _read_csv_safely(FILINGS_FILE)
    if df.empty:
        _log(f"[ERROR] CSV 읽기 실패 또는 데이터 없음 (봉인된 파일일 가능성) → 처리 스킵")
        return 0
    _log(f"전체 공시: {len(df)}건")

    # 컬럼 보강 + dtype 통일 (pandas FutureWarning: float64 ↔ str 충돌 회피)
    for col in ("summary_kr", "summary_en", "extracted_json", "form"):
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str)

    # 처리 대상 — extracted_json 채워져 있고 summary_kr 또는 summary_en 비어있는 행 (정기공시 제외)
    has_draft     = df["extracted_json"].apply(_is_filled)
    needs_summary = (~df["summary_kr"].apply(_is_filled)) | (~df["summary_en"].apply(_is_filled))
    not_periodic  = ~df["form"].astype(str).isin(PERIODIC_FORMS)
    target_idx    = df.index[has_draft & needs_summary & not_periodic].tolist()

    if not target_idx:
        _log("처리할 행이 없습니다 (모두 이미 요약되었거나 extracted_json 비어있음).")
        return 0

    _log(f"처리 대상: {len(target_idx)}건 (정기공시 제외, extracted_json 있는 것만)")
    _log("-" * 50)

    updated = 0
    for n, idx in enumerate(target_idx, 1):
        row       = df.loc[idx]
        fund      = str(row.get("fund_name") or "")
        form      = str(row.get("form") or "")
        accession = str(row.get("accession_number") or "")
        draft     = str(row.get("extracted_json") or "")

        _log(f"[{n}/{len(target_idx)}] {fund} | {form} | {accession[:20]}")

        try:
            s_kr, s_en = summarize(draft)
        except Exception as exc:  # noqa: BLE001
            _log(f"    LLM 호출 실패: {exc}")
            time.sleep(SLEEP_BETWEEN_CALLS)
            continue

        if not s_kr and not s_en:
            _log("    [SKIP] 빈 응답")
            continue

        if s_kr:
            df.at[idx, "summary_kr"] = s_kr
        if s_en:
            df.at[idx, "summary_en"] = s_en
        updated += 1

        active_model = MODELS_FALLBACK[_ACTIVE_MODEL_IDX]
        _log(f"    ✓ 갱신 (model={active_model})")

        # 매 행 저장 — 중단되어도 진행 보존
        df.to_csv(FILINGS_FILE, index=False, encoding="utf-8-sig")
        time.sleep(SLEEP_BETWEEN_CALLS)

    _log(f"\n완료: {updated} 건 갱신됨")
    return updated


if __name__ == "__main__":
    main()
