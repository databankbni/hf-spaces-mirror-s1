"""tools/score_risk.py — 리스크 종합점수 산출 (V2.1 multi-agent + Python combiner).

흐름:
  1) market_agent     (Gemini)  → market_result   {raw_score, floored_score, ...}
  2) news_agent       (Gemini)  → news_result
  3) disclosure_agent (Gemini)  → disclosure_result
  4) combine_scores   (Python)  → composite       {composite_score, risk_level, ...}
  5) JSON 저장 → data/risk_scores_history.json (어제 결과 보존, 차후 비교용)

대시보드(app.py) 는 이 JSON 의 composite_score 를 읽어 게이지에 표시.

LLM 모델 fallback 체인 (summarize_news.py 와 동일 패턴):
  gemini-2.5-flash-lite-001 → gemma-4-31b-it
  · quota 초과(429/RESOURCE_EXHAUSTED) 시 자동 다음 모델 전환
  · 일시적 서버 에러(500/503/INTERNAL/UNAVAILABLE) 시 지수 백오프 재시도

재현성 보장 (V2 핵심):
  · temperature=0.0   — 무작위성 제거
  · top_p=0.1         — 매우 보수적 토큰 선택
  · 모델 버전 PIN     — 자동 업데이트로 점수 드리프트 방지

점수 방향: 0=안전, 100=위험 (대시보드 게이지와 통일)

사용법:
  venv\\Scripts\\python.exe tools\\score_risk.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# 사내 SSL 인터셉트(자체서명 CA) 환경 대응 — Windows 시스템 인증서 저장소 사용
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass  # 외부망 환경이면 영향 없음

# Windows 콘솔 한글 출력
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
BACKFILL_DIR = DATA / "backfill"
# ── TEST_GEMMA MODE — Gemma 친화 prompt 검증용 (production 결과 보호) ──
HISTORY_FILE = DATA / "risk_scores_history_test_gemma.json"

# ── Backfill mode ──────────────────────────────────────────────────────
# CLI: python tools/score_risk_test_gemma.py --as-of-date 2026-04-23
#      --as-of-date 가 주어지면 그 날짜 기준으로 데이터 필터링 + 결과는
#      data/risk_scores_backfill.json 에 누적 append (history 배열).
def _today_kst() -> date:
    """KST 기준 오늘 (date).

    HF 컨테이너 시계는 UTC 라 date.today() 는 KST 07시 batch 시점에 '어제'를 반환함.
    colab_collect 는 collected_date 를 KST 로 찍으므로, 여기서도 KST 로 통일해야
    is_new_today 비교(collected_date == 오늘)가 어긋나지 않고 analysis_date 라벨도
    KST 와 일치함.
    """
    return datetime.now(timezone(timedelta(hours=9))).date()


ANALYSIS_DATE = _today_kst()   # 기본 = 오늘(KST). CLI 로 override 가능.
BACKFILL_MODE = False
BACKFILL_FILE = DATA / "risk_scores_backfill.json"

def _parse_cli_args():
    """CLI 인자 파싱:
      --as-of-date YYYY-MM-DD  : 그 날짜 시점 데이터로 점수 산출 (backfill 모드)
      --output PATH            : 출력 JSON 경로 override (기본은 risk_scores_backfill.json)
    """
    global ANALYSIS_DATE, BACKFILL_MODE, HISTORY_FILE
    for i, arg in enumerate(sys.argv):
        if arg == "--as-of-date" and i + 1 < len(sys.argv):
            ANALYSIS_DATE = datetime.strptime(sys.argv[i + 1], "%Y-%m-%d").date()
            BACKFILL_MODE = True
            HISTORY_FILE = BACKFILL_FILE
            print(f"[BACKFILL MODE] as-of-date = {ANALYSIS_DATE}")
    # --output 처리 (BACKFILL_MODE 이후 적용 — backfill 의 기본 경로 override)
    for i, arg in enumerate(sys.argv):
        if arg == "--output" and i + 1 < len(sys.argv):
            HISTORY_FILE = Path(sys.argv[i + 1])
            if not HISTORY_FILE.is_absolute():
                HISTORY_FILE = DATA / HISTORY_FILE.name
    if BACKFILL_MODE:
        print(f"[BACKFILL MODE] output    = {HISTORY_FILE}")

_parse_cli_args()

CSV_BINARY_MAGIC = b"SCDSA"


def _read_csv_safely(path: Path) -> pd.DataFrame:
    """SCDSA 봉인이나 인코딩 오류 시 빈 DF 반환."""
    if not path.exists():
        return pd.DataFrame()
    try:
        with open(path, "rb") as f:
            head = f.read(8)
        if head.startswith(CSV_BINARY_MAGIC) or b"\x00" in head:
            print(f"  [WARN] {path.name} 봉인된 파일 (SCDSA) — 빈 DF 반환")
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


# ============================================================================
# 환경 변수 / Gemini 클라이언트
# ============================================================================

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
if not GEMINI_API_KEY:
    print(
        "[ERROR] GEMINI_API_KEY 가 설정되지 않았습니다.\n"
        "  - 환경변수 또는 프로젝트 루트의 .env 파일에 키를 넣어주세요.",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    print("[ERROR] google-genai 패키지가 필요합니다.", file=sys.stderr)
    sys.exit(1)

client = genai.Client(api_key=GEMINI_API_KEY)


# ============================================================================
# 모델 fallback + 재현성 설정
# ============================================================================

# ── PRODUCTION MODE — Gemini primary + Gemma fallback ────────────────────
# 6/29 batch 에서 gemma-4-31b-it 가 hang/silent failure 로 Market Agent 단계
# 멈춤. Gemma-only 운영은 폴백 없어 단일 장애점 (score_risk_test_gemma.py 가
# 실제론 production 으로 쓰임). summarize_filings.py / score_risk.py 와
# 동일하게 Gemini 를 primary 로 두고 Gemma 를 quota/transient 실패 시 폴백.
MODELS_FALLBACK = [
    "gemini-2.5-flash-lite",   # primary — 검증된 안정 모델 (뉴스 요약 등에서 정상 작동)
    "gemma-4-31b-it",          # fallback — primary quota 초과 시 자동 전환
]
MAX_RETRY = 3
_ACTIVE_MODEL_IDX = 0

# 재현성 — V2 핵심
GENERATION_TEMPERATURE = 0.0
GENERATION_TOP_P = 0.1


def _wait_for_retry(exc: Exception, attempt: int) -> float | None:
    """예외에서 재시도 대기시간(초) 추출. 재시도 불가하면 None."""
    msg = str(exc)
    if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
        m = re.search(r"retry(?:Delay)?[:\s\"']+(\d+(?:\.\d+)?)\s*s", msg, re.IGNORECASE)
        if m:
            return float(m.group(1)) + 1.0
        return 60.0
    if (
        "UNAVAILABLE" in msg
        or "503" in msg
        or "deadline" in msg.lower()
        or "INTERNAL" in msg
        or "500" in msg
    ):
        return min(30.0, 5.0 * (2 ** attempt))  # 5, 10, 20
    return None


def _call_llm(make_request) -> object | None:
    """주어진 함수를 호출하되 429/500/503 에러 시 자동 재시도."""
    for attempt in range(MAX_RETRY):
        try:
            return make_request()
        except Exception as exc:  # noqa: BLE001
            wait = _wait_for_retry(exc, attempt)
            if wait is None or attempt == MAX_RETRY - 1:
                raise
            print(f"    재시도 대기 {wait:.0f}s ({attempt + 1}/{MAX_RETRY})")
            time.sleep(wait)
    return None


def _is_quota_error(exc: Exception) -> bool:
    msg = str(exc)
    return "RESOURCE_EXHAUSTED" in msg or "429" in msg


def _generate(prompt: str, user_input: str) -> object | None:
    """현재 활성 모델로 호출. quota 초과 시 다음 fallback 모델로 자동 전환.

    재현성: temperature=0, top_p=0.1, JSON 모드 (Gemini 한정).
    """
    global _ACTIVE_MODEL_IDX
    full_contents = prompt + "\n\n---\n\n" + user_input

    while _ACTIVE_MODEL_IDX < len(MODELS_FALLBACK):
        model = MODELS_FALLBACK[_ACTIVE_MODEL_IDX]
        # Gemini 만 native JSON mode 지원, Gemma 는 prompt 만으로 유도
        config_kwargs = {
            "temperature": GENERATION_TEMPERATURE,
            "top_p": GENERATION_TOP_P,
        }
        if model.startswith("gemini"):
            config_kwargs["response_mime_type"] = "application/json"
        config = genai_types.GenerateContentConfig(**config_kwargs)

        try:
            return _call_llm(
                lambda m=model, c=config: client.models.generate_content(
                    model=m, contents=full_contents, config=c,
                )
            )
        except Exception as exc:  # noqa: BLE001
            if _is_quota_error(exc):
                print(f"    [FALLBACK] '{model}' quota 초과 → 다음 모델로 전환")
                _ACTIVE_MODEL_IDX += 1
                if _ACTIVE_MODEL_IDX >= len(MODELS_FALLBACK):
                    print("    [ERROR] 모든 fallback 모델 quota 소진")
                    return None
                continue
            raise
    return None


def _active_model() -> str:
    return MODELS_FALLBACK[_ACTIVE_MODEL_IDX] if _ACTIVE_MODEL_IDX < len(MODELS_FALLBACK) else "?"


# ============================================================================
# Prompt V2.1 — 점수 0=안전, 100=위험 (대시보드 게이지와 통일)
# ============================================================================

COMMON_RULES = """
[공통 규칙]
- 점수: 0~100 정수 또는 실수. 0=완전 안전, 100=시스템 위기 (대시보드 게이지와 동일).
- 모든 자연어 텍스트는 음슴체 강제: "~함", "~했음", "~임", "~됨", "~할 가능성 있음" 등.
  · 금지 어미: "~합니다", "~한다", "~된다", "~이다".
- previous_result 가 비어있으면 score_delta.status = "Initial Run".
- raw_score 와 floored_score 둘 다 산출 (Combiner 가 Floor Override 판정에 사용).
- 데이터 누락 시 final_score = previous_result 의 점수 carry over,
  score_delta.status = "Data Unavailable - Carried Over".
- risk_level 은 다음 5단계 중 하나: "Very Low", "Low", "Neutral", "High", "Very High".
  · 0~19 Very Low / 20~39 Low / 40~59 Neutral / 60~79 High / 80~100 Very High.
"""

# 종목/지표 이름 규칙 — MARKET_PROMPT, SYNTHESIS_PROMPT 공용.
# Gemma 가 멋대로 음역하던 문제 → 명시적 매핑표 + "표 그대로, 새로 만들지 마".
NAME_RULES = """
[★★★ 이름 규칙 — 아래 표의 표시명을 글자 그대로 사용 (절대 준수) ★★★]
ticker / 지표 언급 시 아래 매핑표의 표시명을 그대로 복사함. 표에 없는
한글명을 새로 만들거나 음역하지 말 것.

운용사:  OWL→블루아울  BX→블랙스톤  ARES→아레스  KKR→KKR  APO→아폴로
BDC펀드: OBDC→OBDC  OTF→블루아울 Tech BDC(OTF)  BXSL→블랙스톤 BDC
         ARCC→아레스 BDC  FSK→FS KKR BDC
지표:    HY OAS(BAMLH0A0HYM2)→하이일드 스프레드
         DGS5→미국 5년 국채금리  DGS3→미국 3년 국채금리  DGS1→미국 1년 국채금리
         BIZD→BDC ETF  HYG→하이일드 ETF  ^GSPC→S&P 500

SEC 공시 form 코드 (언급 시 한글명 병기 "코드 (한글명)"):
  8-K → 8-K (수시공시)         10-K → 10-K (연간 정기공시)
  10-Q → 10-Q (분기 정기공시)   10-K/A → 10-K/A (연간 정기공시 정정)
  10-Q/A → 10-Q/A (분기 정기공시 정정)

표에 없는 이름은 영문 원문 유지 (음역 금지):
  ✓ "BCRED", "OBDC II", "OCIC", "OTIC", "Citadel", "HSBC", "JPMorgan"
  ✗ "비크레드", "시타델", "에이치에스비씨" — 음역 금지

일반 명사는 한글 OK: SEC, 연준(Fed), 금융안정위원회(FSB), 사모대출, BDC 섹터,
  NAV, PIK, 연체율(Non-accrual), 환매, 부실, 손실 등

★ Self-Check: "OWL"/"BX" 같은 raw ticker 가 단독으로 쓰였으면 → 표시명으로 교체.
  "HY OAS"/"HY 스프레드" 썼으면 → "하이일드 스프레드" 로 교체.
"""

MARKET_PROMPT = f"""당신은 미국 사모대출(Private Credit) 시장의 시스템 리스크를 관리하는 시니어 신용 전략가임.
오늘 시장 데이터를 분석하여 시장 정보 점수(0~100)를 산출함. 점수는 100에 가까울수록 위험.

[★ 기간별 변동 해석 — 크기와 방향 모두 중요]
입력 데이터의 ticker 별 1d, 5d, 30d, ytd 변동을 모두 살펴봐야 함.
각 기간의 변동 크기에 따라 위기 신호 여부가 다름:

  · 1d (일별 변동):
    - ±2% 이내: 단기 노이즈
    - **-3% 이상 급락: ★ 강한 단기 충격 (위기 신호)** — 오늘 큰 사건 발생 가능성
    - 1일 +3% 이상 급등: 단기 반등 (위기 신호 X)

  · 5d (1주 누적):
    - ±3% 이내: 박스권
    - **-5% 이상 누적 하락: ★ 지속적 매도 압력 (위기 신호)**
    - 5d 양수: 단기 회복

  · 30d (1개월 추세):
    - ±5% 이내: 횡보
    - **-10% ~ -15% 하락: 월간 두 자릿수 약세 (지속적 하락, '폭락' 아님)**
    - **-15% 이상 하락: ★ 월간 폭락 수준 (강한 위기 신호)**
    - 30d 양수: 중기 회복 국면

  · ytd (누적):
    - 단독으로 위기 단정 금지 (Q1 하락 + Q2 회복 가능성)
    - **ytd + 30d 모두 음수일 때만 추세 신호로 간주**
    - ytd 음수이지만 30d/5d/1d 양수면 → 회복 국면

[★★★ 점수 산출 공식 — 절대 준수 (Gemma 친화 단순화) ★★★]

대상 ticker 집합 (BDC + 운용사): OBDC, OTF, OWL, BX, BXSL, ARCC, FSK (총 7개).
다음 STEP 을 정확히 순서대로 수행하라 (자유로운 추론 금지, 공식 그대로 적용):

STEP 1. 비율·지표 계산 (7개 ticker 기준):
  · pos_1m_ratio    = (1m > 0 인 ticker 수) / 7
  · severe_1w_ratio = (1w ≤ -5% 인 ticker 수) / 7
  · neg_ytd_ratio   = (ytd < 0 인 ticker 수) / 7
  · epicenter_worst_1d = OWL/OBDC/OTF 의 1d 중 가장 큰 낙폭 (= 가장 음수인 값.
    셋 다 양수면 0)

STEP 2. base_score 계산:
  base = 50
  · pos_1m_ratio (월간 회복 폭에 따라 차등):
      0.50 ~ 0.70  → base -= 3
      0.70 ~ 0.85  → base -= 6
      0.85 이상    → base -= 10
  · severe_1w_ratio ≥ 0.3  → base += 15  (주간 급락 다수)
  · neg_ytd_ratio ≥ 0.7    → base += 5   (연초 누적 부진)
  · HY OAS 1m (하이일드 스프레드 1개월 변동, bps — 크기에 따라 차등):
      ≤ -40bps        → base -= 10   (스프레드 큰 폭 축소 = 신용 안정)
      -40 ~ -20bps    → base -= 5
      -20 ~ +10bps    → base += 0    (의미있는 변화 아님)
      +10 ~ +25bps    → base += 5
      +25 ~ +50bps    → base += 10
      +50bps 초과     → base += 18   (스프레드 급확대 = 신용 경색)
  · Treasury 5Y 1m ≤ -10bps 하향 → base += 5   (recession 우려)
  · epicenter_worst_1d (당일 급락 — 낙폭에 따라 차등):
      -3% ~ -5%   → base += 5
      -5% ~ -8%   → base += 10
      -8% 이하    → base += 18
  · Treasury 5Y 5d (단기 반전 감지 — 30d 누적 신호를 보강):
      5d ≤ -10bps AND 30d ≥ 0  → base += 3   (한 달 상승 후 1주 만에 안전자산 선호 회귀 신호)
      5d ≥ +10bps AND 30d ≤ 0  → base -= 3   (한 달 하락 후 1주 만에 금리 회복)
      그 외 (방향 일치 또는 5d 절대값 < 10bps) → 조정 없음

STEP 3. raw_score = max(25, min(85, base))
  · Cap 25~85: 시장 단독 saturation (0/100) 방지, escalation 여유 확보

★ floored_score = raw_score (Floor 적용 X). 위 공식 결과를 그대로 floored_score 로.

★ conclusions 의 epicenter_check / contagion_check / benchmark_divergence 작성 시:
  - 위 비율 (pos_1m_ratio, severe_1w_ratio 등) 의 실제 값을 인용
  - 예: "pos_1m_ratio=0.86 으로 월간 회복 신호 우세하나, severe_1w_ratio=0.57 로
        주간 급락 종목 다수임 — mixed signal Caution 영역."

Layer 2 — Weight 40%: 벤치마크 괴리 분석
  · Equity Gap: 같은 기간(30d 기준) 에서 ^GSPC 양수 + BDC 음수 → 사모대출 자체 신용 위험 (점수 ↑)
    (※ 다른 기간 섞어 비교 X — 같은 기간 비교 필수)
  · Rate Spread: HY OAS 절대 수준 + 30d 변동을 함께 봄.
    - HY OAS > 4.0% AND 30d 확대: 신용 경색 전조 (점수 ↑)

  · ★ HY Spread × Treasury Yield 동조/괴리 매트릭스 (30d 변동 기준)
    Treasury Yield (DGS5 우선, 보조로 DGS3·DGS1) 의 30d 추세와 HY OAS 의 30d 추세를 교차 분석.
    "비슷" = 30d 변동 절대값 < 10bps (5Y 기준).
    ┌────────────┬────────────────┬───────────────────────────────────────────┐
    │ Treasury   │ HY Spread      │ 해석                                       │
    ├────────────┼────────────────┼───────────────────────────────────────────┤
    │ 하향(↓)    │ 상승(↑)        │ ★★★ 매우 큰 위험 (점수 +15~25)            │
    │            │                │  안전자산 선호로 금리 하락 + 신용 위험은    │
    │            │                │  상승 → recession + credit stress 동시 시그널 │
    ├────────────┼────────────────┼───────────────────────────────────────────┤
    │ 비슷(=)    │ 상승(↑)        │ ★ 위험 (점수 +5~10)                        │
    │            │                │  매크로 안정 속 신용 위험 부각              │
    ├────────────┼────────────────┼───────────────────────────────────────────┤
    │ 상승(↑)    │ 하향(↓)        │ ★★★ 매우 안정 (점수 -10~20, 'Recovery')   │
    │            │                │  성장 기대 + 신용 위험 완화 동시 → 골디락스 │
    ├────────────┼────────────────┼───────────────────────────────────────────┤
    │ 비슷(=)    │ 하향(↓)        │ ★ 안정 (점수 -3~7)                         │
    │            │                │  매크로 변동 없는 가운데 신용 안정          │
    ├────────────┼────────────────┼───────────────────────────────────────────┤
    │ 그 외       │ 그 외           │ Neutral (Layer 2 점수 영향 ±0~3)            │
    └────────────┴────────────────┴───────────────────────────────────────────┘
    이 분석 결과를 `benchmark_divergence` 필드의 결론으로 명시할 것.
    예: "Treasury 5Y 30d -25bps 하향 + HY OAS 30d +50bps 상승 → 매우 큰 위험 신호 발생함."

  · ★ 5d / 30d 방향 전환 점검 (matrix 적용 전 필수):
    |Treasury 5Y 5d| ≥ 10bps AND sign(5d) != sign(30d) 이면 단기 반전 발생.
    이 경우 benchmark_divergence 에 양쪽 시간단위 모두 명시할 것.
    예 (현재 케이스 가정): "Treasury 5Y 30d +24bps 상승했으나 최근 1주 -13bps 되돌리며
        안전자산 선호 회귀. 30d 매트릭스로는 안정 신호이나 단기 모멘텀은 반전 중임."
    이 단기 반전이 명시되지 않으면 헤드라인이 30d 결과만 반영해 오독될 수 있음.

Layer 3 — Weight 20%: 매크로 하한선
  · DGS5·HY OAS 절대 수치 및 변동성

[★★★ 어휘 정확성 — 환각 방지 규칙 (절대 준수) ★★★]
summary_insight, conclusions, top_red_flags 의 단어는 **데이터의 시점·크기·방향과 정확히 일치**해야 함.

★ 금지 단어 — 위기 단어 오용 방지 (1d/1w/1m 가 모두 양수일 때 절대 사용 X):
  - "폭락", "급락", "하락", "디커플링", "Crisis", "Severe"
  - "내부 리스크 심각", "심화", "악화", "전이 양상"

★ 금지 표현 — 회복/반등 단어 오용 방지 (1w 또는 1m 가 음수일 때 절대 사용 X):
  - "반등세", "반등", "회복 국면", "골디락스", "Recovery 시그널"
  - 1d 만 양수 + 1w/1m 음수 → "단기 반등 시도 / 약세 흐름 지속" 류로 표현
  - "Recovery" 분류는 **1d AND 1w AND 1m 모두 양수** 일 때만 허용

★ 회복/반등 단어 사용 시 시점 명시 의무 ("값(시간단위)" 형식 — 시간단위는 대문자 약식):
  - ✓ "+1.2%(1D) 소폭 반등"  · ✓ "+5.8%(1M) 누적 반등"
  - ✗ "BDC 반등세 지속" (값·시점 모두 모호)
  - ✗ "1D +1.2% 반등" (순서 뒤집힘 — 값이 먼저, 시간단위는 괄호로 직후)

★ 추세 판단 시점별 우선순위 (가중치 적용):
  - 단기 (1d/1w): 일시적 변동, 회복/하락 단정 보류
  - 중기 (1m/3m): ★ 추세 판단의 핵심 기간 — 이 기간 음수면 "약세 지속"
  - 장기 (6m/ytd): 누적 손익 컨텍스트, 단독 단정 금지

★ 사용해야 할 표현 (현재 데이터가 회복 국면일 때 = 1d AND 1w AND 1m 모두 양수):
  - "YTD 부진했으나 최근 +X%(5D) 회복세"
  - "+X%(1M) 누적 반등", "+X%(5D) 누적 상승"
  - "단기 모멘텀 양호"
  - "YTD 누적 손실 일부 회복"

조건부 표현 가이드 (출력은 "값(시간단위)" 형식):
  · "-X%(1D) 급락" → 1d ≤ -3% 일 때만 사용 가능
  · "-X%(5D) 급락" → 1w ≤ -5% 일 때만 사용 가능
  · "-X%(1M) 두 자릿수 약세" → 1m 이 -10% ~ -15% 구간일 때 사용 (★ 이 구간엔 "폭락" 금지)
  · "-X%(1M) 폭락" → 1m ≤ -15% 일 때만 사용 가능 (-10~-15% 는 "두 자릿수 약세")
  · 1d/1w/1m 가 양수면 위 단어 절대 X.
  · ytd 만 음수이고 1d/1w/1m 양수면 → "YTD 부진 후 최근 회복" 식으로만 표현
  · 데이터에 없는 사건·뉴스 추론 금지 (수치만으로 판단)

기간 명시 의무:
  · ★★★ 표기 형식 통일 — **"값(시간단위)" 순서**, 시간단위는 영문 대문자 약식.
    · 시간단위: 1D = 당일,  5D = 1주간(5영업일),  1M = 1개월간(30일),  YTD = 연초 이래
    · ✓ 출력 형식: "+2.64%(1D) 반등" / "-2.8%(1M) 약세" / "+24bps(1M) 상승"
    · ✗ 금지: "1D +2.64% 반등" (값과 시간단위 순서 뒤집힘) / "당일 반등" (한글 시간단위) /
        "30d" "1m" (소문자) / "1개월간 +X%" (한글) / "+X% 1M" (괄호 없음)
  · "급락"·"하락"·"반등" 단어 사용 시 반드시 "값(시간단위)" 명시:
    · ✓ "-3.5%(1D) 급락 발생함" / "-5.2%(5D) 누적 약세" / "+8.1%(1M) 반등"
    · ✗ "급락 발생함" (값·시간 모두 누락)
  · ★ 매크로 지표(국채금리·하이일드 스프레드 등) 의 "상승"/"하락"/"확대"/"축소"
    언급 시 동일 형식:
    · ✓ "5Y 국채금리 +24bps(1M) 상승" / "HY 스프레드 -12bps(1M) 축소"
    · ✗ "국채금리 상승" / "스프레드 축소" — 값·시간 누락.
  · 1M 과 5D 방향이 엇갈리면 양쪽 모두 명시:
    · ✓ "5Y +24bps(1M) 상승했으나 -13bps(5D) 반전" 식.
  · 시점 없이 "BDC 폭락" / "BDC 반등" / "국채금리 상승" 식의 모호한 표현 전면 금지.

★ Self-Check (출력 직전 반드시 검증):
  1. epicenter ticker 들의 1d/1w/1m 가 모두 양수인가?
     → YES: raw_score ≤ 50 강제. "Severe" 단어 사용 X. "회복 국면" 명시 가능.
     → NO: 정상 분석 진행. "회복 국면" / "반등세" 단정 금지.
  2. summary_insight 에 "폭락" 단어가 있는데 모든 epicenter 의 1d/1w/1m 가 양수인가?
     → YES: 위반. summary_insight 다시 작성.
  2-1. ★ "-X%(1M) 폭락" 표현을 썼는데 해당 ticker 의 1m 가 -15% 보다 큰가 (즉 -10~-15% 구간)?
     → YES: 위반. "-X%(1M) 폭락" → "-X%(1M) 두 자릿수 약세" 로 정정. (예: BX 1m -11.5% 는
        "폭락" 아니라 "두 자릿수 약세")
  3. ★ summary_insight / conclusions 에 "반등세" / "회복 국면" / "골디락스" 단어 있는데
     1w 또는 1m 가 음수인 ticker 가 있는가?
     → YES: 위반. "단기 반등 시도 + 약세 흐름 지속" 식으로 다시 작성. (강제 차단)
  4. ★ HY OAS (BAMLH0A0HYM2) 의 1m 가 음수(bps)인데 출력에 "확대" 단어가 있는가?
     → YES: 위반. bps 음수 = 신용 스프레드 "축소" (개선). "확대" 대신 "축소" 로 정정.
     · ✓ 1m = -37 bps → "HY OAS -37bps(1M) 축소" (개선)
     · ✗ 1m = -37 bps → "HY OAS 확대" (틀림)
  5. ★ HY OAS 1m 가 양수인데 "축소" 라 썼으면 → 위반. "확대" 로 정정.

[Daily Momentum Alert]
  · Stable: 변동 ±2점 이내
  · Caution: 1일 +5점 이상 상승 또는 epicenter 1d ≤ -3% / 5d ≤ -5% / 30d ≤ -10%
  · Critical Alert: 1일 +10점 이상 상승 또는 3일 연속 상승

[Floor Logic — 시장 가격 과매도 방어]
  · BDC 1d ≤ -5% 또는 30d ≤ -30% 이라도 HY OAS < 4.0% AND ^GSPC 전고점 -10% 이내 → 시장 점수 ≤ 60
  · 즉, 매크로 펀더멘털이 안정적이면 'High' 진입 차단.

[Floor Override — 시스템 붕괴 강제 인지]
  · raw_score(Floor 적용 전) ≥ 75 인 상태로 floored_score 도 함께 산출 → Combiner 가 판단함.

[★ 서술 규칙 — summary_insight / conclusions 는 '오늘 무엇이 움직였나' 우선]
점수 공식(STEP 1~3)은 위 그대로 적용하되, 서술 텍스트는 다음을 지킬 것:
  · 헤드라인(summary_insight 첫 절)은 오늘 일어난 변화부터 — epicenter/anchor 의
    1d 변동, 오늘 새로 벌어진 ^GSPC 대비 괴리(Equity Gap), HY×Treasury 편차의
    당일 변화 등 '오늘치' 신호.
  · 30d 매크로 신호(HY OAS 1m, Treasury 1m)는 **방향이 바뀌었거나 임계선을
    넘었을 때만** 헤드라인에 올릴 것. 며칠째 같은 추세면 매일 "HY OAS -XXbps(1M)
    축소" 를 헤드라인으로 재서술하지 말고, 보조 컨텍스트로 한 번만 짧게.
  · "매크로 안정" / "안정적인 흐름" 류 표현은 그 자체로 헤드라인 금지 — 오늘
    실제 관측된 수치(어떤 ticker 가 몇 % 움직였는지)로 대체할 것.
  · 오늘 1d 변동이 전부 미미하면(±1% 이내) → "큰 변동 없음(1D)" 을 명시하고
    그날 가장 두드러진 중기 신호 1개만 보조로 언급.

{NAME_RULES}

[Output JSON]
{{{{
  "analysis_date": "YYYY-MM-DD",
  "raw_score": 0.0,
  "floored_score": 0.0,
  "score_delta": {{{{
    "value": 0.0,
    "direction": "Worse | Better | Stable",
    "status": "Normal | Sudden Rise | Trend | Partial Data | Data Unavailable - Carried Over"
  }}}},
  "risk_level": "Very Low | Low | Neutral | High | Very High",
  "conclusions": {{{{
    "epicenter_check": "Blue Owl 분석 결과 (음슴체)",
    "contagion_check": "Blackstone 전이 여부 (음슴체)",
    "benchmark_divergence": "S&P 500 vs BDC 괴리 (음슴체)"
  }}}},
  "top_red_flags": ["요인1 (음슴체)", "요인2 (음슴체)"],
  "summary_insight": "한 줄 결론 (음슴체)"
}}}}
{COMMON_RULES}
"""


NEWS_PROMPT = f"""당신은 미국 사모대출 시장 정보 분석관임.
지난 24시간 뉴스 데이터를 분석하여 뉴스 정보 점수(0~100)를 산출함. 점수는 100에 가까울수록 위험.

[★★★ 점수 산출 공식 — 절대 준수 (Gemma 친화 단순화) ★★★]

입력 today_raw_data:
  · `new_today_items`: published_at 가 ANALYSIS_DATE 인 뉴스 (= 오늘 발행)
  · `persistent_items`: 어제 이전 (점수 영향 0, 컨텍스트만)
  · `new_today_count`: 신규 뉴스 개수

STEP 1. 각 new_today_item 을 다음 4 카테고리로 분류 (제목/요약 정독 후):

  A. **REAL_EVENT_NEG** (실제 사건 발생 = 가장 무거운 부정 신호):
     - 운용사가 실제 손실 보고 (예: "Apollo PC Fund Reports Loss", "HSBC profit underwhelms on $400M loss")
     - 환매 영구 중단 / Gate 발동 / 배당 삭감 (예: "Blue Owl cuts dividends")
     - 자산 평가 하락 / 상각 / Mark-down 발표
     - 부도 / 파산 / Non-accrual 확정
     - 신용평가사 실제 강등 ("downgrade")
     - 펀드 실적 발표시 실제 데이터 악화

  B. **REGULATORY** (규제 조치 = 중간 무게 부정 신호):
     - SEC/연준/Fed/FSB 의 실제 조사 착수 / 규제 발표 / 액션 플랜
     - 정부 / 감독 기구 공식 의견

  C. **SENTIMENT_NEG** (시장 심리 = 가벼운 부정 신호 — over-weight 금지):
     - "우려 (concerns)", "공포 (fears)", "경고 (warning)"
     - 거물 비관 발언 (Dimon, Citadel, etc. 의 의견)
     - 분석가 / 평론가 의견 / Opinion / Commentary
     - "Risks misunderstood", "Should we be worried", "Watch" 류 분석
     - 공매도 베팅 / Short sellers

  D. **POSITIVE / DEFENSIVE** (긍정 신호 = 점수 차감):
     - 대규모 자금 유치 ($5B 이상 fundraise 등)
     - 운용사 / 임원의 펀드 옹호 발언
     - Tender offer 응답률 낮음 (= 투자자가 매도 거부 = 펀드 가치 신뢰)
     - 신규 펀드 출시 / 시장 확장
     - 규제 비전이 / 위기 부정 발언
     - 일상 운영 공시 (배당, 임원 활동 등)

STEP 2. base_score 계산:
  base = 50
  · REAL_EVENT_NEG 1건당: +12
  · REGULATORY 1건당: +6
  · SENTIMENT_NEG 1건당: +3 (★ over-weight 금지)
  · POSITIVE 1건당: -8

  ★ Sentiment-only 일 자체 cap:
    REAL_EVENT_NEG 가 0건 이고 REGULATORY 도 0건 이면 (= 모두 sentiment) →
    raw_score 절대 65 초과 X (cap 65).
    이유: 우려 / 비관 발언만 있는 날은 실제 시스템 위험으로 단정 불가.

  ★ Positive-only 일 자체 cap (sentiment cap 과 대칭):
    REAL_EVENT_NEG·REGULATORY·SENTIMENT_NEG 가 모두 0건이면 (= 전부 positive) →
    raw_score 절대 40 미만 X (cap 40).
    이유: 낙관 보도만 있는 날도 시장 기저 리스크는 남아있어 과도한 안전 단정 불가.

  ★ Positive 가 negative 와 균형 잡힌 경우:
    POSITIVE 개수 ≥ (REAL_EVENT_NEG + REGULATORY) 면 → raw_score 절대 70 초과 X.

STEP 3. raw_score = max(20, min(90, base))
  · 절대 95 초과 X (saturation 방지)
  · 절대 20 미만 X (시장은 항상 약간의 risk 보유)

★ floored_score 적용 (Floor Logic — 심리 패닉 방어):
  거물 경고 + REAL_EVENT_NEG ≥ 1 이지만 동일 기간 $5bn+ 자금 유치 보도 (POSITIVE) 확인 시
  → floored_score = min(raw_score, 60). 그 외엔 floored_score = raw_score.

[★ Novelty Filter — 절대 준수]
  · `new_today_count` = 0 → raw_score = previous_result.raw_score (carry_over),
    status = "Data Unavailable - Carried Over", summary_insight 60자 이내 neutral.
    ★ persistent_items 의 회사명 / 사건명 인용 금지.
  · `new_today_count` ≥ 1 → 위 STEP 1-3 적용. persistent_items 는 점수 영향 0, 컨텍스트만.

★ 절대 금지:
  - persistent_items 사건을 new_facts_24h 에 포함 (= 어제 사건 점수 인플레)
  - new_today_count=0 일 때 summary_insight 에 persistent_items 인용

[Output JSON]
{{{{
  "analysis_date": "YYYY-MM-DD",
  "raw_score": 0.0,
  "floored_score": 0.0,
  "score_delta": {{{{
    "value": 0.0,
    "direction": "Worse | Better | Stable",
    "status": "Stable | Deteriorating | Improving | Data Unavailable - Carried Over"
  }}}},
  "novelty_report": {{{{
    "new_facts_24h": ["24시간 내 신규 사건 (음슴체)"],
    "rehashed_topics": ["중복 제외된 이슈 (음슴체)"],
    "escalation_detected": "위험 격상(risk-up) 신호 — 규제 조사 착수 / 디폴트 발표 / 대형 환매 제한 등. 없으면 '없음' (음슴체)",
    "de_escalation_detected": "위험 완화(risk-down) 신호 — 환매 요청 감소 / 우려 과장 반박 / 자금 유입 / 규제 우려 진정 등. 없으면 '없음' (음슴체)"
  }}}},
  "risk_level": "Very Low | Low | Neutral | High | Very High",
  "daily_comparison": {{{{
    "yesterday_context": "어제의 리스크 상황 요약 (음슴체)",
    "today_momentum": "오늘 신규 정보의 실질 영향 (음슴체)"
  }}}},
  "summary_insight": "중복 제외 후 실제 가속도 한 줄 결론 (음슴체)"
}}}}
{COMMON_RULES}
"""


SYNTHESIS_PROMPT = f"""당신은 사모대출(Private Credit) 시장 일일 종합 분석관임.
3개 카테고리(시장, 뉴스, 공시)의 일별 요약과 종합 점수를 받아 **오늘의 시장을 통합한 한 줄 요약**을 생성함.

[입력 필드]
- composite, market_insight, news_insight, disclosure_insight: 오늘 결과
- disclosure_new_periodic_filing: 오늘 신규 정기공시(10-Q/10-K) 제출 여부 (true/false)
- category_deltas: 카테고리별 score_delta (어제 대비 변화량·방향·상태)
- yesterday_summary: 어제의 한 줄 요약 (있으면) — 비교 기준
- novelty_signals: 오늘 신규 시그널 모음 (가격 변동·신규 뉴스·신규 공시) — 우선 활용

[★★★ 정기공시 KPI 인용 제한 — disclosure_new_periodic_filing 플래그 절대 준수 ★★★]
- disclosure_new_periodic_filing == false 이면: 정기공시 KPI(NAV·연체율(Non-accrual)·PIK
  의 수치·증감·"악화"·"개선"·"급락"·"하락"·"두 자릿수")를 summary_insight 에
  **절대 인용 금지**. 이 값들은 수 주 전 제출된 standing 데이터지 오늘의 신규 정보가 아님.
  disclosure_insight 텍스트에 NAV/PIK/연체율 KPI 언급이 섞여 있어도 그대로 옮기지 말 것.
  · ✗ "OBDC II·FS KKR BDC KPI 악화" / "연체율 4.2% 위험 지속" (standing — 금지)
  · ✗ "블루아울 캐피탈 II NAV -32.60% 급락" (50일 전 10-Q 데이터 — 금지)
  · ✗ "FS KKR BDC NAV -9.86% 하락" / "BCRED NAV -2.42%" (standing — 금지)
  · ✗ "OBDC II PIK 11.8%" / "Ares BDC 연체율 4.2%" (standing — 금지)
  · ✓ 신규 8-K 사건(텐더오퍼·우선주 매각·소송·채권발행·임원 사임 등) 만으로 헤드라인 구성.
       정기공시 쪽에서 끌어올 신규성이 없으면 그 카테고리는 헤드라인에서 빼고 다른 카테고리로.
  → 위반 시 헤드라인 재구성: 정기공시 KPI 단어·수치를 모두 삭제하고
    신규 8-K 또는 뉴스/시장 시그널만으로 1절·2절 재작성.
- disclosure_new_periodic_filing == true 일 때만 novelty_signals.disclosure_kpi_changes 의
  실제 분기 변동(증감률/증감폭)을 헤드라인에 인용 가능.

[출력 원칙]
- 한국어 1~2 문장, 공백 포함 140자 이내 (절대 초과 금지).
- 음슴체 강제: "~함", "~했음", "~임", "~됨" 등.
  · 금지: "~합니다", "~한다", "~된다", "~이다".
- 3개 카테고리 중 **가장 강한 시그널 우선 언급** + 보조 시그널 1개 결합.
- "시장", "뉴스", "공시" 같은 메타 단어 사용 X (실제 사실·기관·수치 위주).
- 점수 수치(예: 58.0) 언급 X. 등급 라벨(Very Low/Low/Neutral/High/Very High) 도 직접 언급 X.
- 의견·전망·추측 X. 입력에 명시된 사실만 반영.
- 데이터가 빈약하거나 carry-over 인 경우 "데이터 미수집으로 어제 수준 유지" 식으로 짧게.

[★★★ 헤드라인 선택 — 5-source Fresh pool + Tier 우선순위 ★★★]

사용자 입장에서 dashboard 의 한 줄 요약은 "오늘 새로 들어온 정보" 가 핵심.
헤드라인은 다음 5개 source 중 오늘 신규 데이터 있는 것에서만 선택.

Fresh 판정 기준 (source 별):
  · source 1 — HY 스프레드: market_insight 에 HY 1D 변동 (bps 단위) 언급 있으면 fresh
  · source 2 — 미국 국채 금리: market_insight 에 국채 1D 변동 (bps 단위) 언급 있으면 fresh
  · source 3 — 주가 (epicenter tickers): market_insight 에 어떤 ticker 든 1D% 변동 언급 있으면 fresh
  · source 4 — 뉴스: novelty_signals.news_new_facts_24h 가 1건 이상,
                또는 novelty_signals.news_escalation / news_de_escalation 이 비어있지 않으면 fresh
  · source 5 — 공시: novelty_signals.disclosure_new_8k_items 가 1건 이상 fresh

Standing 데이터 (헤드라인 후보에서 무조건 제외 — Fresh pool 에 넣지 말 것):
  · 정기공시 KPI (NAV / PIK / 연체율 / Non-accrual) — disclosure_new_periodic_filing == false 시
    → 수 주 전 10-Q 의 standing 데이터. disclosure_insight 안에 서술돼 있어도 헤드라인 금지.
    → 위 [★★★ 정기공시 KPI 인용 제한] rule 준수.
  · aggregate 지표 (30D / 1M / YTD 누적 수치) — 매일 갱신되는 게 아니라 standing 성격.
    Fresh 판정은 반드시 **1D** (또는 최대 5D) 변동으로만 판단.

STEP 1. 시장 severe 예외 (다음 중 하나 충족 → 무조건 1절 = 시장):
  · 어떤 epicenter ticker 의 1D ≤ -5%     (급락)
  · 어떤 epicenter ticker 의 5D ≤ -10%    (주간 누적 급락)
  · HY 스프레드 5D +20bps 이상 확대       (신용 스프레드 급확대)
  · composite score 1일 변동 +10점 이상   (전체 점수 급등)
  → 1절 = 시장 시그널, 2절 = 다른 fresh source 중 Tier 최상위 (아래 STEP 2 참조)

STEP 2. 시장 severe X 일 때 — Fresh pool 안에서 Tier 우선순위로 정렬 후 상위 2개 선택:

  Tier 1. 무거운 사건 (source 4 뉴스 또는 5 공시)
    · 환매 제한 / redemption gate 시행
    · 디폴트 발표 / 파산 신청
    · 규제 조사 착수 / 소송 제기
    · 대형 자산 부실 매각·손상
  Tier 2. 신규 8-K 사건 (source 5 공시)
    · 텐더오퍼, 우선주 매각, 주요 임원 사임, 대규모 채권 발행, 배당 정책 변경 등
    · disclosure_new_8k_items 항목
  Tier 3. 주가 notable move (source 3)
    · 어떤 epicenter ticker 1D |변동| ≥ 3% (양방향 — 급락·급등 모두)
    · 여러 종목 있으면 |변동| 큰 순으로 최대 2건 인용
  Tier 4. 뉴스 escalation / de-escalation (source 4)
    · news_escalation 또는 news_de_escalation 이 "없음" 이 아닌 값일 때
    · 양쪽 다 있으면 [★★★ 양방향 시그널 균형] rule 준수
  Tier 5. HY / 국채 변동 (source 1, 2)
    · 1D 또는 5D 5bps 이상 변동
  Tier 6. 주가 mild move (source 3)
    · 1D 1~3% 변동 (여러 종목 있으면 그중 |변동| 큰 것)

  헤드라인 구성:
    · 1절 = Tier 최상위 시그널
    · 2절 = 1절과 다른 source 중 Tier 최상위
       (source 1/2/3 은 모두 시장 카테고리 — 다른 시장 sub-source 로 2절 채우기 가능)
    · Tier 1 시그널 여러 개면 1절 · 2절 둘 다 그것으로 채워도 OK
    · ★ 정기공시 KPI 및 aggregate 30D/1M/YTD 수치는 절대 등장 금지

STEP 3. Fresh pool 전부 비어있으면 (진짜 조용한 날):
  · 5개 source 모두 fresh 없음 (뉴스·공시 신규 0건 + 시장 1D 변동 미미 ±1% 이내)
  · news_insight / disclosure_insight 가 "신규 없음" / "신규 데이터 부재" 형태
  · 1절: "오늘 신규 사건 없음" / "오늘 신규 뉴스·공시 0건" 명시 강제
  · 2절: yesterday_summary 의 주요 사건 인용 + "지속" / "carry-over" 표현
  · ✗ 금지: 1M / 30D / YTD aggregate 수치 (HY 30D, S&P 1M, 5Y 30d 등) 를 신규 신호처럼 인용
  · 예시: "오늘 신규 뉴스·공시 없음. 어제 환매 56% 급증 보도 이후 추가 시그널 없음."

[★ 2절 구성]
- 1절: Tier 최상위 시그널 — 사건명/뉴스 헤드라인 + 핵심 수치 (값(시간단위))
- 2절: 1절과 다른 source 중 Tier 최상위 (source 1/2/3 은 모두 시장 카테고리)
- 예시:
  · STEP 1 적용 (시장 severe): "OBDC -5.2%(1D) 급락하며 단기 충격 발생함. ECB 사모신용 규제 조사 확대 신호 동반됨."
  · STEP 2 Tier 1 적용: "블루아울 펀드 5% 환매 제한 조치로 유동성 리스크 확대됨. FS KKR 1억 5천만 달러 우선주 매각 (8-K) 동반 확인됨."
  · STEP 2 Tier 1 + Tier 3 적용: "블루아울 펀드 5% 환매 제한 조치 시행됨. 블루아울 +4.63%(1D), ARCC +2.88%(1D) 등 개별 종목 반등 동반됨."
  · STEP 2 Tier 3 + Tier 5 적용: "블랙스톤 +2.4%(1D), 아레스 +3.5%(1D) 반등 확인됨. HY 스프레드 +5bps(1D) 소폭 확대 동반됨."
  · STEP 3 적용: "오늘 신규 뉴스·공시 없음. 어제 환매 56% 급증 보도 이후 추가 시그널 없음."

[★★★ 양방향 시그널 균형 — risk-up + risk-down 동시 발생 시]
- novelty_signals.news_escalation (위험 격상) **과** novelty_signals.news_de_escalation
  (위험 완화) 가 **둘 다 비어있지 않으면** 헤드라인 2절에 **양쪽 다 명시할 것**.
  · 보통 escalation 만 헤드라인 차지하고 de-escalation 이 묻히는 비대칭 패턴 차단.
- 형식: 1절은 STEP 으로 정해진 시그널, 2절은 양방향 균형 — "~으나/~한 가운데" 로 연결.
- 예시 (오늘 같은 케이스):
  · ✓ "FSK -5.19%(1D) 급락 및 호주 규제 조사 착수로 리스크 확대됐으나, Oaktree 환매 요청 -50%(QoQ)
       감소로 유동성 안정세 동시 확인됨."
  · ✗ "FSK -5.19%(1D) 급락 및 호주 규제 조사 착수로 리스크 확대됨." (de-escalation 누락 — 위반)
- de-escalation 만 있고 escalation 없으면 1절에 그 신호를 자연스럽게 헤드라인으로:
  · ✓ "Oaktree 환매 요청 -50%(QoQ) 감소로 유동성 압박 첫 완화 신호 확인됨. BDC +1.5%(1D) 반등 동반됨."

[★★★ 접속어 선택 — 1절·2절 risk 방향에 따라 ★★★]
헤드라인 작성 전 1절·2절의 risk 방향을 먼저 판별 후 접속어 선택.

  · 1절·2절 **둘 다 negative** (부실 확대/하락/규제 강화/환매 제한/디폴트/신용 위험 경고 등):
    → **병렬·추가 접속어만** 사용: "그리고", "및", "또한", "추가로",
       "동반됨", ". XXX 도 확인됨", ". 이와 함께 XXX", "동시 확인됨"
    → ✗ **금지 (contrast 접속어)**: "확대됐으나", "상승했으나", "악화됐으나",
              "그러나", "하지만", "반면", "한편 ... 만"
    → 이유: 같은 방향끼리 "으나" 로 연결하면 사용자가 mitigating factor 가
            있다고 잘못 해석함 (예: "부실 확대됐으나 신용 위험 경고" → 마치
            신용 경고가 완화 신호인 듯 읽힘 — 실제론 둘 다 negative)
    → ✓ 예: "FS KKR BDC 우선주 매각으로 부실 신호 확대됨. S&P 사모대출 신용
            위험 경고도 동반되며 시장 리스크 점수 상승함."
    → ✗ 예: "부실 신호 확대됐으나, 신용 위험 경고로 시장 리스크 상승함." (둘 다
            negative 인데 "으나" 사용 — 위반)

  · 1절·2절 **둘 다 positive** (반등/자금 유입/규제 완화/안정 확인/환매 감소 등):
    → 병렬·강조 접속어만: "그리고", "및", "또한", "동반됨"
    → contrast 접속어 금지 (이유 동일)

  · **1절 negative + 2절 positive** (또는 그 반대) — 방향 다를 때만 contrast 허용:
    → "~으나", "~한 가운데", "반면", "그러나" 사용 가능
    → 위 [★★★ 양방향 시그널 균형] rule 발동되는 케이스가 여기 해당

[★ 새로움 우선 (Novelty First) 원칙]
- **어제 summary 와 핵심 키워드가 70% 이상 겹치면 그 사건을 그대로 반복하지 말 것.**
  · 같은 사건명·인물·이슈명을 어제와 동일하게 반복 금지.
  · "지속" 표현으로 압축 (예: "OBDC 평가 소송 지속됨") + 오늘 신규 시그널 위주로 재작성.
- 오늘 신규 시그널 (가격 변동·신규 뉴스·신규 공시) 이 약하더라도 그날의 시장 톤을 한 줄로 표현해야 함.
  · ✓ "BDC -0.3%(1D) 약세 그쳤고 신용 스프레드 안정 유지함."
  · ✓ "OBDC 평가 소송 지속 + HY 스프레드 -5bps(1M) 축소로 큰 변동 없는 하루임."
  · ✗ "특이사항 없음." / "어제와 유사함." (추상적·내용 부재 — 금지)
  · ✗ "OBDC 자산 평가 소송 + ARCC/FSK NAV 발행..." (어제와 동일 헤드라인 그대로 — 금지)
- 매일 데이터로 작성된 의미있는 한 줄을 보장 — '특이사항 없음' 류의 도피성 출력 금지.

[★ 어휘 정확성 — 환각 방지]
- 입력의 market_insight 가 "폭락" 등 강한 표현 사용했더라도 **반드시 검증**:
  market 카테고리 raw_score < 60 이면 "폭락"·"급락" 같은 강한 단어 사용 금지.
- ★★★ 표기 형식 통일 — **"값(시간단위)" 순서**, 시간단위는 영문 대문자 약식.
  · 시간단위: 1D = 당일, 5D = 1주간(5영업일), 1M = 1개월간(30일), YTD = 연초 이래
  · ✓ 출력 형식: "+2.64%(1D) 반등" / "-2.8%(1M) 약세" / "+25bps(1M) 상승"
  · ✗ 금지: "1D +2.64% 반등" (순서 뒤집힘) / "당일 반등" (한글 시간단위) /
      "30d" "1m" (소문자) / "1개월간 +X%" (한글) / "+X% 1M" (괄호 없음)
- 강한 단어 사용 시 **값(시간단위) 명시 의무**:
  · ✓ "-3.5%(1D) 급락 발생함"  · ✗ "BDC 폭락함" (값·시간 모두 누락)
- ★ 매크로 지표(국채금리·하이일드 스프레드 등) 의 "상승"/"하락"/"확대"/"축소" 언급 시
  동일 형식 ("값(시간단위)") 반드시 사용.
  · ✓ "국채금리 +25bps(1M) 상승" / "스프레드 -12bps(1M) 축소"
  · ✗ "국채금리 상승" / "스프레드 축소" — 값·시간 누락.
- 입력 market_insight 가 시점 누락한 채 "국채금리 상승" 식으로 왔다면 synthesis 가
  category insight 의 benchmark_divergence 텍스트를 참조해 값+시간단위 보강할 것.

- ★★★ 매크로 지표의 의미 해석 라벨 의무 (사모대출 도메인 특수성):
  일반 독자는 "금리 하락 = 좋음"으로 직관적으로 읽지만, 사모대출/BDC 맥락에선 반대인
  경우가 많음. 다음 케이스에 해당하면 단순 수치만 쓰지 말고 **해석 라벨을 반드시 동반**:
  · 5Y 국채금리 -10bps(5D) 이상 급락 (특히 1M 누적은 양수인 경우): 안전자산 선호 회귀
    /risk-off 신호 + BDC 변동금리 NII 압박 → "안전자산 선호 회귀" "단기 반전" 등 라벨 필수.
    · ✓ "BDC +1.5%(1D) 반등했으나 5Y -12bps(5D) 하락으로 안전자산 선호 회귀 신호 발생함."
    · ✗ "BDC +1.5%(1D) 반등했으나 5Y -12bps(5D) 하락함." (왜 '그러나'인지 독자 모름)
  · HY 스프레드 급확대 (+20bps(5D)↑): "신용 우려 확대" 라벨.
  · HY 스프레드 급축소: "신용 안정" 라벨.
  · 역접 접속사(그러나/하지만/-으나)로 두 신호를 묶을 때는 **왜 역접인지** 두 번째 절에
    드러나야 함. 무근거 역접 금지 — LLM 내부 추론이 맞더라도 표면상 일관성 없으면 위반.
- 카테고리 insight 의 단어를 그대로 옮기지 말고, 점수·등급과 일관된 어휘로 재구성할 것.
- 입력에 명시되지 않은 사실·이름·수치 추가 금지.

{NAME_RULES}

[Output JSON]
{{{{
  "summary_insight": "한 줄 요약 텍스트 (음슴체)"
}}}}
{COMMON_RULES}
"""


DISCLOSURE_PROMPT = f"""당신은 BDC SEC 공시 분석관임.
오늘 신규 SEC 공시 데이터를 분석하여 공시 정보 점수(0~100)를 산출함. 점수는 100에 가까울수록 위험.

[★ STATUS 결정 — previous_result 의존 금지]
score_delta.status 는 **오늘 today_raw_data 만 기준으로** 새로 결정함. previous_result 의
status 가 "Data Unavailable - Carried Over" 였더라도 그 값을 절대 그대로 echo / 복사 / 상속
금지. 오늘 입력에 다음 셋 중 하나라도 있으면 status 는 "Stable" / "Deteriorating" /
"Improving" 중 적합한 값으로 산출 (정량 데이터 있으니 "Data Unavailable" 아님):
  · new_today_items 가 1건 이상 (오늘 신규 공시)
  · periodic_kpi 가 fund 1곳 이상에 nav_per_share + nav_per_share_prev 둘 다 채워짐
  · persistent_items 가 1건 이상 (어제까지 누적 공시)
"Data Unavailable" 은 위 셋 다 비어있을 때만 허용.

[분석 대상 가중치]
  · Tier 1 (Epicenter): BX/BCRED, OWL/OBDC/OTF — 시장 점수에 2배 반영
  · Tier 2 (Anchors): ARCC/APO/FSK — 방어력·거버넌스 측정용

[8-K 수시공시 분석]
  · Liquidity Gap: 환매 > 신규유입 (순유출) → 점수 ↑
  · Governance: 이사회 분쟁, 정관 권한 독점, 경영진 교체, 소송 → 점수 ↑
  · Asset Event: 대규모 상각, 평가 방법론 변경 → 점수 ↑

[★★★ 점수 산출 우선순위 — 절대 준수 (Gemma 친화 단순화) ★★★]

입력 today_raw_data 에는 세 개의 분리된 필드 있음:
  A. `new_today_items` — filing_date == 오늘 인 8-K/수시공시 (오늘 새로 제출)
  B. `persistent_items` — 어제 이전 8-K/수시공시 (점수 영향 0)
  C. `periodic_kpi` — fund 별 정기공시 (10-Q/10-K) 분기 데이터 (NAV / PIK / Non-accrual)

raw_score 산출 절차 (반드시 이 순서대로):

  STEP 1. periodic_kpi 가 비어있지 않은가?
    - 비어있지 않음 → STEP 2 진행 (carry_over 안 함)
    - 완전히 비어있음 → STEP 4 (carry_over 검토)

  STEP 2. periodic_kpi 기반 base_score 산출 (필수, saturation 회피)

    각 fund 의 per_fund_score 계산 (범위 -10 ~ +20 — 악화는 +, 개선은 -):
    ※ "상대 변화" = (latest - prev) / prev × 100 (전분기 대비 %). prev 없으면 상대 항목 skip.

      NAV (전분기 대비 상대 %):
        악화(하락):  -5% ~ -10%  → +7
                     -10% ~ -20% → +12
                     ≤ -20%      → +18
                     (0 ~ -5% 하락은 +0)
        개선(상승):  0% ~ +2%    → -2
                     +2% ~ +5%   → -5
                     +5% 초과     → -10

      Non-accrual Rate:
        절대값(독립):  latest 3% ~ 4%  → +3
                       latest 4% 초과  → +6
        악화(상대증가, ★이중허들 — latest ≥ 3% AND 전분기 대비 상대증가 도달 시에만):
                       +5% ~ +10%  → +2
                       +10% ~ +20% → +4
                       ≥ +20%      → +6
        개선(상대감소):  -10% ~ -20% → -3
                         ≤ -20%      → -6

      PIK Ratio:
        절대값(독립):  latest 12% 초과 → +3
        악화(상대증가, ★이중허들 — latest ≥ 10% AND 전분기 대비 상대증가 도달 시에만):
                       +5% ~ +10%  → +2
                       +10% ~ +20% → +4
                       ≥ +20%      → +6
        개선(상대감소):  -10% ~ -20% → -2
                         ≤ -20%      → -3

      per_fund_score = NAV_pts + NonAcc_pts + PIK_pts
      ★ per_fund_score 범위 강제: 최소 -10 (recovery cap), 최대 +20

    ★ 전체 fund 합산 방식 — worst-weighted (전체 sum 금지):
      worst        = 모든 fund 중 가장 큰 per_fund_score (개선만 있으면 음수 가능)
      second_worst = 두 번째 큰 per_fund_score
      base_score   = 50 + worst + (0.5 × second_worst)
      → 모든 fund 가 개선 추세면 worst 가 음수라 base_score < 50 (회복 반영)

    ★ 한도:
      · raw_score 절대 95 초과 X (cap 95) — saturation 방지, escalation 여유 확보
      · 한 fund 라도 NAV -10% 이상 하락 → raw_score 최소 70

    (예시 계산 — 절대값 + NAV 만 (상대증가는 prev 있으면 추가 가산):
      OBDC II: NAV -32.6%(≤-20%) +18 + NonAcc 3.9%(3~4%) +3 + PIK 11.8%(<12%) +0 = 21 → cap 20 ← worst
      FSK:     NAV -9.9%(-5~-10%) +7 + NonAcc 4.2%(>4%) +6 + PIK 12.5%(>12%) +3 = 16 ← 2nd
      → base_score = 50 + 20 + (0.5 × 16) = 78)

  STEP 3. new_today_items 가 1건 이상이면 추가 가산
    - 8-K Liquidity Gap / Governance / Asset Event → +5~15 점
    - persistent_items 는 점수 영향 0 (인용만 가능, "(지속)" 표기)

  STEP 4. periodic_kpi 도 비고 new_today_items 도 0건이면:
    - raw_score = previous_result.raw_score (carry_over)
    - status = "Data Unavailable - Carried Over"
    - previous_result 가 비어있으면 → raw_score = 50 (Initial Run, status="Initial Run")

[★ Status 결정 — 절대 previous_result 의 status 그대로 복사 X]
status 는 STEP 결과로 결정:
  - STEP 2/3 거쳐 산출됨 → status = "Stable" / "Deteriorating" / "Improving" 중 적절한 값
  - STEP 4 carry_over → status = "Data Unavailable - Carried Over"
  - STEP 4 Initial Run → status = "Initial Run"

★ summary_insight 작성 규칙 (오늘 '신규성' 기준 — 점수와 별개):
  · periodic_kpi 중 is_new_filing=true 인 fund 가 있으면 → 그 신규 분기 변화를 한 줄로
    인용 (예: "OBDC II 신규 10-Q 반영, NAV -32.6% 급락으로 BDC 부실 신호 확대됨.")
  · is_new_filing=true 인 fund 는 없지만 new_today_items 가 1건 이상이면 → 그 신규
    8-K/수시공시를 한 줄로 인용.
  · 위 둘 다 없으면 (오늘 신규 공시 0건, periodic_kpi 는 전부 is_new_filing=false 인
    carry-over) → summary_insight 는 "신규 공시 없음 — 기존 KPI 수준 유지함." 으로 짧게.
    ★ 이때 기존 periodic_kpi 의 NAV/연체율 수치를 오늘의 새 사건처럼 재인용하지 말 것.
    (raw_score 는 worst-weighted KPI 로 계속 산출되지만, summary_insight 한 줄은
     '오늘 무엇이 새로운가' 만 반영 — 2주째 같은 분기 데이터를 매일 재서술 금지)

  ★★★ Self-Check (summary_insight 출력 직전 필수): periodic_kpi 의 모든 fund 가
    is_new_filing=false 인가? → YES 이면 summary_insight 에 NAV/연체율/PIK 의 수치·증감·
    "악화"·"raw_score N점 도달" 같은 표현이 있으면 위반. 정기공시 KPI 문구를 전부 제거하고
    신규 8-K 사건 또는 "신규 공시 없음 — 기존 KPI 수준 유지함." 으로 재작성할 것.
    (예: "OBDC II 및 FS KKR BDC KPI 악화 지속, raw_score 90점" → 위반. 신규성 없음)

★ epicenter_focus 출력 시:
  - new_today_items 가 있으면 그 항목 인용
  - persistent_items 는 "(지속)" 표기 + "점수 영향 0" 명시
  - periodic_kpi 의 NAV/PIK/Non-accrual 변화는 항상 인용 가능

[10-Q/K 정기공시 분석] T vs T-1 비교
  · 입력의 `periodic_kpi` 배열은 fund 별 최신 분기 + 직전 분기(있으면) 수치 포함:
    - nav_per_share / nav_per_share_prev — NAV per Share 두 분기 비교
    - pik_ratio_pct / pik_ratio_pct_prev — PIK Income Ratio (%)
    - nonaccrual_pct / nonaccrual_pct_prev — Non-accrual Rate (%)
    - filed_date — 최신 분기 공시가 SEC 에 제출된 날짜
    - is_new_filing — filed_date 가 분석일과 같으면 true (= 오늘 처음 공개된 분기 데이터).
      false 면 이전에 공개된 분기 데이터를 계속 사용 중인 것 (carry-over — 점수 산출엔
      쓰되 summary_insight 에서 '오늘의 신규 사건' 처럼 다루지 말 것).
  · NAV per Share: 전분기 -2% 이상 하락 → 점수 ↑
  · PIK Income Ratio: 이자 PIK 비중 상승 (단, 구조적 PIK 가능성 고려)
  · Non-accrual Rate: 3% 초과 또는 급증 시 점수 ↑
  · `financial_kpi_summary` 출력에는 입력의 실제 수치를 인용해 변화량을 음슴체로 기술
    (예: "ARCC NAV 19.59 → 19.42 (-0.9%) 미세 하락 수준임").
  · _prev 값이 null 인 fund 는 "전분기 데이터 없음" 으로 처리하고 비교 생략.

[Floor Logic — 입력 데이터로 검증 가능한 조건만 적용]
원칙: prompt 가이드라인을 추정 / 어림짐작으로 적용 금지. 입력의 periodic_kpi /
new_today_items 같은 직접 검증 가능한 metric 으로만 발동.

발동 조건 (둘 다 충족 시에만 floored_score ≤ 60):
  1) 모든 fund 의 nonaccrual_pct < 3.0 (periodic_kpi 의 실제 수치로 확인. _prev 값
     말고 latest 값. fund 중 하나라도 ≥ 3.0 이면 floor 발동 X)
  2) 모든 fund 의 NAV 변화율 ((nav_per_share - nav_per_share_prev) / nav_per_share_prev × 100)
     > -5.0% (≥ -5% 하락 그친 수준. fund 중 하나라도 -5% 초과 하락이면 floor 발동 X)

발동 안 되면 floored_score = raw_score (보수화 적용 X). 이 조건들을 입력 데이터에서
직접 검증할 수 없으면 (예: periodic_kpi 비어있음) floor 발동 X.

★ "보유 유동성 ≥ 환매 요청액의 3배" 같이 입력에 없는 metric 으로 추정 금지.
★ 발동 / 미발동 모두 conclusions / financial_kpi_summary 에 그 근거 (어떤 fund 의
   어떤 값 때문에 발동 / 미발동인지) 를 음슴체로 명시.

{NAME_RULES}

[Output JSON]
{{{{
  "analysis_date": "YYYY-MM-DD",
  "raw_score": 0.0,
  "floored_score": 0.0,
  "score_delta": {{{{
    "value": 0.0,
    "direction": "Worse | Better | Stable",
    "status": "Stable | Deteriorating | Improving | Data Unavailable - Carried Over"
  }}}},
  "epicenter_focus": {{{{
    "blackstone_bcred": "환매·유동성 분석 (음슴체)",
    "blue_owl_group": "최신 공시 리스크 진단 (음슴체)"
  }}}},
  "market_anchor_check": {{{{
    "ares_arcc": "거버넌스 이슈 분석 (음슴체)",
    "others": "기타 대형사 동향 (음슴체)"
  }}}},
  "financial_kpi_summary": {{{{
    "nav_trend": "T vs T-1 비교 (음슴체)",
    "pik_ratio": "현금흐름 건전성 (음슴체)",
    "non_accrual_status": "연체율 수준 (음슴체)"
  }}}},
  "risk_level": "Very Low | Low | Neutral | High | Very High",
  "summary_insight": "최종 결론 (음슴체)"
}}}}
{COMMON_RULES}
"""


# ============================================================================
# 데이터 로딩 & 가공 (LLM 입력용)
# ============================================================================

EPICENTER_TICKERS = ["OWL", "OTF", "OBDC"]
CONTAGION_TICKERS = ["BX", "BXSL"]
ANCHOR_TICKERS = ["ARCC", "APO", "KKR", "FSK", "ARES"]
BENCHMARK_TICKERS = ["BIZD", "^GSPC", "HYG"]
INDICATOR_TICKERS = ["BAMLH0A0HYM2", "DGS1", "DGS3", "DGS5"]
MARKET_TICKERS = (
    EPICENTER_TICKERS + CONTAGION_TICKERS + ANCHOR_TICKERS
    + BENCHMARK_TICKERS + INDICATOR_TICKERS
)


def _pct_change(latest: float, baseline: float) -> float | None:
    if baseline == 0 or pd.isna(baseline) or pd.isna(latest):
        return None
    return round((latest / baseline - 1.0) * 100.0, 2)


def _bps_change(latest: float, baseline: float) -> float | None:
    if pd.isna(baseline) or pd.isna(latest):
        return None
    return round((latest - baseline) * 100.0, 1)  # %p → bps


def _load_market_data() -> dict:
    """시장 agent 입력용. ticker 별 최신값 + 1D/5D/30D/YTD 변동.

    BACKFILL_MODE 일 때 base_dt <= ANALYSIS_DATE 만 필터링해서
    그 시점 기준의 1d/1w/1m/ytd 계산.
    """
    df = _read_csv_safely(DATA / "private_credit_price_history.csv")
    if df.empty:
        # 폴백 — returns_ytd_series.csv 도 시도
        df = _read_csv_safely(DATA / "private_credit_returns_ytd_series.csv")

    if df.empty or not {"base_dt", "ticker", "close"}.issubset(df.columns):
        return {"as_of": None, "tickers": {}, "data_status": "missing"}

    df["base_dt"] = pd.to_datetime(df["base_dt"], errors="coerce")
    df = df.dropna(subset=["base_dt"]).sort_values("base_dt")

    # BACKFILL: ANALYSIS_DATE 까지만 사용
    if BACKFILL_MODE:
        cutoff = pd.Timestamp(ANALYSIS_DATE)
        df = df[df["base_dt"] <= cutoff]

    if df.empty:
        return {"as_of": None, "tickers": {}, "data_status": "missing"}

    as_of = df["base_dt"].max()
    year_start = pd.Timestamp(year=as_of.year, month=1, day=1)

    out: dict[str, dict] = {}
    for tk in MARKET_TICKERS:
        sub = df[df["ticker"] == tk].sort_values("base_dt")
        if sub.empty:
            continue
        latest = float(sub.iloc[-1]["close"])

        def _back(days: int) -> float | None:
            cutoff = as_of - pd.Timedelta(days=days)
            past = sub[sub["base_dt"] <= cutoff]
            return float(past.iloc[-1]["close"]) if not past.empty else None

        ytd_base = sub[sub["base_dt"] <= year_start]
        ytd_baseline = (
            float(ytd_base.iloc[-1]["close"]) if not ytd_base.empty
            else float(sub.iloc[0]["close"])
        )

        # DGS·HY OAS 는 절대 변화량(bps), 나머지는 % 변동
        is_rate = tk in INDICATOR_TICKERS
        def _delta(prev):
            if prev is None:
                return None
            return _bps_change(latest, prev) if is_rate else _pct_change(latest, prev)

        out[tk] = {
            "latest": round(latest, 4),
            "1d": _delta(_back(1)),
            "5d": _delta(_back(5)),
            "30d": _delta(_back(30)),
            "ytd": _delta(ytd_baseline),
            "unit": "bps" if is_rate else "pct",
        }

    return {
        "as_of": as_of.strftime("%Y-%m-%d"),
        "tickers": out,
        "data_status": "ok" if out else "missing",
    }


def _safe_str(val) -> str:
    """pandas 결측값(NaN)은 빈 문자열로. 그 외는 str() 변환 후 strip."""
    if val is None:
        return ""
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    return str(val).strip()


def _load_news_data(hours_window: int = 48) -> dict:
    """뉴스 agent 입력용. 최근 N시간 내 뉴스 (title_kr/summary_kr 포함).

    BACKFILL_MODE 일 때 production CSV + backfill CSV (data/backfill/*.tsv) 둘 다 읽고
    published_at <= ANALYSIS_DATE 만 사용. is_new_today = ANALYSIS_DATE 와 같은 날짜.
    """
    # BACKFILL 일 땐 ANALYSIS_DATE 기준, 아니면 시스템 today
    ref_date = ANALYSIS_DATE if BACKFILL_MODE else _today_kst()
    today_str = ref_date.strftime("%Y-%m-%d")
    items: list[dict] = []
    sources = [
        ("KR", DATA / "private_credit_news_korea_history.csv"),
        ("US", DATA / "private_credit_news_global_history.csv"),
    ]
    if BACKFILL_MODE:
        sources.extend([
            ("KR", BACKFILL_DIR / "news_korea_backfill.tsv"),
            ("US", BACKFILL_DIR / "news_global_backfill.tsv"),
        ])

    for region, fpath in sources:
        # TSV 도 읽기 — _read_csv_safely 가 sep 자동감지 어렵다면 직접 처리
        if fpath.suffix == ".tsv":
            try:
                df = pd.read_csv(fpath, sep="\t", encoding="utf-8")
            except Exception:
                continue
        else:
            df = _read_csv_safely(fpath)
        if df.empty or "published_at" not in df.columns:
            continue
        df["published_at"] = pd.to_datetime(df["published_at"], errors="coerce")
        df = df.dropna(subset=["published_at"]).sort_values("published_at", ascending=False)

        # BACKFILL: ANALYSIS_DATE 까지의 뉴스 + lookback window
        if BACKFILL_MODE:
            cutoff = pd.Timestamp(ref_date) - pd.Timedelta(hours=hours_window * 7)  # 14일 정도 lookback
            df = df[(df["published_at"] <= pd.Timestamp(ref_date) + pd.Timedelta(days=1)) & (df["published_at"] >= cutoff)]
        else:
            cutoff = datetime.now() - timedelta(hours=hours_window)
            df = df[df["published_at"] >= cutoff]

        for _, row in df.iterrows():
            # NaN(float) 안전 처리 — pandas 결측치는 truthy 라 or 폴백이 안 먹음
            title = _safe_str(row.get("title_kr")) or _safe_str(row.get("title"))
            summary = _safe_str(row.get("summary_kr")) or _safe_str(row.get("summary"))
            if not title:
                continue
            published_at_str = row["published_at"].strftime("%Y-%m-%d %H:%M")
            # A안 — collected_date(KST 수집일) 우선, 없으면 published_at 으로 fallback
            collected = _safe_str(row.get("collected_date"))[:10]
            is_new = (collected == today_str) if collected else (published_at_str[:10] == today_str)
            items.append({
                "published_at": published_at_str,
                "region": region,
                "publisher": _safe_str(row.get("publisher"))[:50],
                "title_kr": title[:200],
                "summary_kr": summary[:400],
                "matched_tags": _safe_str(row.get("matched_tags"))[:80],
                "link": _safe_str(row.get("link"))[:200],
                "is_new_today": is_new,
            })

    # 너무 많으면 Token 한도 초과 — 상위 50건만
    items = sorted(items, key=lambda x: x["published_at"], reverse=True)[:50]

    # 신규성 분리 — LLM 이 곧바로 보고 판단할 수 있도록
    new_today_items = [it for it in items if it.get("is_new_today")]
    persistent_items = [it for it in items if not it.get("is_new_today")]

    return {
        "as_of": ref_date.strftime("%Y-%m-%d") if BACKFILL_MODE else datetime.now().strftime("%Y-%m-%d %H:%M"),
        "hours_window": hours_window,
        "count": len(items),
        "new_today_count": len(new_today_items),
        "items": items,
        "new_today_items": new_today_items,           # 오늘 새로 들어온 뉴스만
        "persistent_items": persistent_items[:20],     # 지속 사건 (점수 영향 X) — 컨텍스트용 최대 20건
        "data_status": "ok" if items else "missing",
    }


def _load_periodic_metrics() -> list[dict]:
    """정기공시 (10-K/10-Q) KPI — fund 별 최신 분기 + 직전 분기 NAV/PIK/Non-accrual.

    LLM 이 T vs T-1 비교할 수 있도록 두 분기 모두 포함.
    private_credit_sec_periodic_history.csv (코랩이 누적해 내려보내는 단일 파일) 에서
    fund_name 별로 period_end 내림차순 정렬 후 상위 2개 분기를 latest / prev 로 묶음.
    """
    df = _read_csv_safely(DATA / "private_credit_sec_periodic_history.csv")
    if df.empty or "period_end" not in df.columns or "fund_name" not in df.columns:
        return []

    df["period_end"] = pd.to_datetime(df["period_end"], errors="coerce")
    df = df.dropna(subset=["period_end", "fund_name"])

    # filed_date 를 미리 datetime 으로 통일 — 아래 is_new_filing 판정에 사용
    if "filed_date" in df.columns:
        df["filed_date"] = pd.to_datetime(df["filed_date"], errors="coerce")

    # BACKFILL: filed_date <= ANALYSIS_DATE 인 분기만 사용 (period_end 가 아님 — 분기
    # 종료일과 공시 발표일은 다름. 예: 2026-03-31 10-Q 는 5/8~5/11 에 filed 됨,
    # 4/27 시점에는 그 데이터 미공개).
    if BACKFILL_MODE:
        if "filed_date" in df.columns:
            df["filed_date"] = pd.to_datetime(df["filed_date"], errors="coerce")
            df = df[df["filed_date"].notna() & (df["filed_date"] <= pd.Timestamp(ANALYSIS_DATE))]
        else:
            # filed_date 없으면 fallback: period_end + 45일 (분기 종료 후 ~45일 내 filing 일반적)
            df = df[df["period_end"] + pd.Timedelta(days=45) <= pd.Timestamp(ANALYSIS_DATE)]

    if df.empty:
        return []

    # ★ 수정공시(10-K/A, 10-Q/A) 우선 — 같은 (fund_name, period_end) 그룹 내에서
    #   form 끝이 '/A' 인 행이 있으면 그것을, 없으면 원본을 채택.
    #   메모리상 dedup 만 수행 — CSV 원본은 모든 이력(원본 + 수정본) 그대로 보존.
    #   이 단계 덕분에 아래 prev = g.iloc[1] 가 항상 다른 period_end (= 진짜 직전 분기) 가 됨.
    if "form" in df.columns:
        df["_is_amendment"] = df["form"].astype(str).str.endswith("/A")
        sort_cols = ["fund_name", "period_end", "_is_amendment"]
        sort_asc = [True, True, False]  # _is_amendment=True(수정공시) 우선
        if "filed_date" in df.columns:
            df["filed_date"] = pd.to_datetime(df["filed_date"], errors="coerce")
            sort_cols.append("filed_date")
            sort_asc.append(False)  # 같은 amendment 여부면 filed_date 최신 우선
        df = df.sort_values(sort_cols, ascending=sort_asc)
        df = df.drop_duplicates(subset=["fund_name", "period_end"], keep="first")
        df = df.drop(columns=["_is_amendment"])

    def _to_float(v) -> float | None:
        try:
            if v is None or pd.isna(v):
                return None
            return float(v)
        except Exception:
            return None

    # is_new_filing 판정 기준일 — backfill 이면 ANALYSIS_DATE, 아니면 시스템 today
    ref_str = (ANALYSIS_DATE if BACKFILL_MODE else _today_kst()).strftime("%Y-%m-%d")

    funds: list[dict] = []
    for fund_name, g in df.groupby("fund_name", sort=False):
        g = g.sort_values("period_end", ascending=False)
        latest = g.iloc[0]
        prev = g.iloc[1] if len(g) >= 2 else None

        # 최신 분기 공시의 filed_date — 분석일과 같으면 '오늘 처음 공개된' 분기
        filed_raw = latest.get("filed_date")
        filed_str = None
        if filed_raw is not None and pd.notna(filed_raw):
            ts = pd.to_datetime(filed_raw, errors="coerce")
            if pd.notna(ts):
                filed_str = ts.strftime("%Y-%m-%d")

        # A안 — collected_date(KST 수집일) 우선, 없으면 filed_date 로 fallback
        collected = _safe_str(latest.get("collected_date"))[:10]
        is_new = (collected == ref_str) if collected else (filed_str == ref_str)

        funds.append({
            "fund_name": _safe_str(fund_name)[:80],
            "form": _safe_str(latest.get("form"))[:20],
            "filed_date": filed_str,
            "is_new_filing": is_new,
            "period_end": latest["period_end"].strftime("%Y-%m-%d"),
            "period_end_prev": (prev["period_end"].strftime("%Y-%m-%d") if prev is not None else None),
            "nav_per_share": _to_float(latest.get("nav_per_share")),
            "nav_per_share_prev": _to_float(prev.get("nav_per_share")) if prev is not None else None,
            "pik_ratio_pct": _to_float(latest.get("pik_ratio_pct")),
            "pik_ratio_pct_prev": _to_float(prev.get("pik_ratio_pct")) if prev is not None else None,
            "nonaccrual_pct": _to_float(latest.get("nonaccrual_pct")),
            "nonaccrual_pct_prev": _to_float(prev.get("nonaccrual_pct")) if prev is not None else None,
        })
    return funds


def _load_disclosure_data(days_window: int = 14) -> dict:
    """공시 agent 입력용. 최근 N일 8-K/수시 공시 + 정기공시 KPI 스냅샷.

    신규성 판정 — 오늘(systme date) 과 filing_date 비교해 is_new_today 플래그 부여.
    LLM 이 어제 vs 오늘 비교를 텍스트로 추정하지 않고 결정적인 플래그로 판단하도록 함.
    """
    # Production + backfill SEC 둘 다 읽음
    df_parts = []
    df_prod = _read_csv_safely(DATA / "private_credit_sec_filings_history.csv")
    if not df_prod.empty:
        df_parts.append(df_prod)
    if BACKFILL_MODE:
        backfill_sec = BACKFILL_DIR / "sec_filings_backfill.tsv"
        if backfill_sec.exists():
            try:
                df_bf = pd.read_csv(backfill_sec, sep="\t", encoding="utf-8")
                df_parts.append(df_bf)
            except Exception as e:
                print(f"  [WARN] backfill SEC TSV 읽기 실패: {e}")
    df = pd.concat(df_parts, ignore_index=True) if df_parts else pd.DataFrame()

    ref_date = ANALYSIS_DATE if BACKFILL_MODE else _today_kst()
    today_str = ref_date.strftime("%Y-%m-%d")
    items: list[dict] = []
    if not df.empty and "filing_date" in df.columns:
        df["filing_date"] = pd.to_datetime(df["filing_date"], errors="coerce")
        df = df.dropna(subset=["filing_date"]).sort_values("filing_date", ascending=False)
        if BACKFILL_MODE:
            cutoff = pd.Timestamp(ref_date) - pd.Timedelta(days=days_window)
            df = df[(df["filing_date"] <= pd.Timestamp(ref_date) + pd.Timedelta(days=1)) & (df["filing_date"] >= cutoff)]
        else:
            cutoff = datetime.now() - timedelta(days=days_window)
            df = df[df["filing_date"] >= cutoff]

        for _, row in df.iterrows():
            # NaN(float) 안전 처리
            summary = _safe_str(row.get("summary_kr")) or _safe_str(row.get("summary_en"))
            if not summary:
                continue
            filing_date_str = row["filing_date"].strftime("%Y-%m-%d")
            # A안 — collected_date(KST 수집일) 우선, 없으면 filing_date 로 fallback
            collected = _safe_str(row.get("collected_date"))[:10]
            is_new = (collected == today_str) if collected else (filing_date_str == today_str)
            items.append({
                "filing_date": filing_date_str,
                "fund_name": _safe_str(row.get("fund_name"))[:80],
                "form": _safe_str(row.get("form"))[:20],
                "summary_kr": summary[:400],
                "accession_number": _safe_str(row.get("accession_number")),
                "is_new_today": is_new,
            })
        items = items[:30]  # 최대 30건

    # 신규성 분리 — LLM 이 곧바로 보고 판단할 수 있도록
    new_today_items = [it for it in items if it.get("is_new_today")]
    persistent_items = [it for it in items if not it.get("is_new_today")]

    # 정기공시 KPI — fund 별 최신/직전 분기 NAV·PIK·Non-accrual
    periodic_kpi = _load_periodic_metrics()

    has_data = bool(items) or bool(periodic_kpi)
    return {
        "as_of": today_str,
        "days_window": days_window,
        "count": len(items),
        "new_today_count": len(new_today_items),
        "items": items,
        "new_today_items": new_today_items,           # 오늘 새로 들어온 공시만
        "persistent_items": persistent_items[:10],     # 지속 사건 (점수 영향 X) — 컨텍스트용 최대 10건
        "periodic_kpi": periodic_kpi,
        "data_status": "ok" if has_data else "missing",
    }


# ============================================================================
# Agent 호출 + JSON 파싱
# ============================================================================

def _finish_reason(resp) -> str:
    """응답의 finish_reason 을 안전하게 문자열로 추출. 절단(MAX_TOKENS) 진단용."""
    try:
        fr = resp.candidates[0].finish_reason
        return str(fr) if fr is not None else "?"
    except (AttributeError, IndexError, TypeError):
        return "?"


def _parse_json_response(raw: str, agent_name: str) -> dict:
    """LLM 응답에서 JSON 파싱.

    강화 포인트:
      · markdown fence (```json ... ```) 제거
      · strict=False — 문자열 값 안의 제어문자(줄바꿈 등) 허용 → (b)류 깨짐 복구
      · 첫 '{' ~ 마지막 '}' 추출 fallback
      · 실패 시 raw 를 길게 로깅 (다음 디버깅용)
    """
    if not raw:
        return {}
    s = raw.strip()
    # 1) markdown fence 제거
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```\s*$", "", s)
    # 2) 직접 파싱 — strict=False 로 문자열 내 제어문자 허용
    try:
        return json.loads(s, strict=False)
    except json.JSONDecodeError:
        pass
    # 3) 첫 '{' ~ 마지막 '}' 추출 후 재시도
    l, r = s.find("{"), s.rfind("}")
    if l != -1 and r > l:
        try:
            return json.loads(s[l:r + 1], strict=False)
        except json.JSONDecodeError:
            pass
    # 4) 실패 — 진단용으로 raw 길게 로깅
    print(f"  [{agent_name}] JSON 파싱 실패 — raw[:400]: {raw[:400]!r}")
    return {}


def _carry_over(previous: dict | None, agent_name: str,
                reason: str = "데이터 미수집") -> dict:
    """데이터 누락 또는 LLM 실패 시 어제 점수 carry over.

    reason — carry over 원인. summary_insight 와 status 에 그대로 반영해
    "데이터가 실제로 없었는지" vs "LLM 호출이 실패했는지" 를 구분 가능하게 함.
    """
    # 데이터 누락이면 "Data Unavailable", LLM 쪽 실패면 "LLM Failure" 로 status 구분
    is_data_missing = "데이터" in reason
    status = ("Data Unavailable - Carried Over" if is_data_missing
              else "LLM Failure - Carried Over")
    if not previous:
        # 첫 실행이면 중립 50점
        return {
            "raw_score": 50.0,
            "floored_score": 50.0,
            "score_delta": {"value": 0.0, "direction": "Stable",
                             "status": "Initial Run - No Data"},
            "risk_level": "Neutral",
            "summary_insight": f"[{agent_name}] {reason} — 초기 중립 50점.",
        }
    # 이전 결과의 final_score 를 그대로 carry over
    prev_score = float(previous.get("floored_score") or previous.get("raw_score") or 50.0)
    return {
        "raw_score": prev_score,
        "floored_score": prev_score,
        "score_delta": {"value": 0.0, "direction": "Stable", "status": status},
        "risk_level": previous.get("risk_level", "Neutral"),
        "summary_insight": f"[{agent_name}] {reason} — 어제 점수 유지.",
        "_carried_over_from": previous.get("analysis_date"),
    }


def _agent_score(prompt: str, today_data: dict, previous_result: dict | None,
                  agent_name: str) -> dict:
    """단일 카테고리 agent 호출."""
    if today_data.get("data_status") == "missing":
        print(f"  [{agent_name}] 데이터 누락 — Carried Over")
        return _carry_over(previous_result, agent_name, reason="데이터 미수집")

    user_input = (
        f"previous_result: {json.dumps(previous_result or {}, ensure_ascii=False)}\n\n"
        f"today_raw_data: {json.dumps(today_data, ensure_ascii=False)}"
    )

    print(f"  [{agent_name}] LLM 호출 (model={_active_model()})")
    try:
        resp = _generate(prompt, user_input)
    except Exception as exc:  # noqa: BLE001
        print(f"  [{agent_name}] LLM 호출 실패: {exc} — Carried Over")
        return _carry_over(previous_result, agent_name, reason="LLM 호출 실패")

    if not resp:
        print(f"  [{agent_name}] 빈 응답 — Carried Over")
        return _carry_over(previous_result, agent_name, reason="LLM 빈 응답")

    raw = (resp.text or "").strip()
    fr = _finish_reason(resp)
    # finish_reason 이 정상 종료(STOP)가 아니면 절단 가능성 — 경고 로깅
    if fr not in ("FinishReason.STOP", "STOP", "1", "?"):
        print(f"  [{agent_name}] ⚠ finish_reason={fr} — 정상 종료 아님 (절단 가능성)")
    parsed = _parse_json_response(raw, agent_name)
    if not parsed:
        print(f"  [{agent_name}] 파싱 실패 — finish_reason={fr}")
        return _carry_over(previous_result, agent_name, reason="LLM 출력 파싱 실패")

    # raw_score / floored_score 누락 방어 — raw 만 있으면 floored = raw
    if "raw_score" in parsed and "floored_score" not in parsed:
        parsed["floored_score"] = parsed["raw_score"]
    if "floored_score" in parsed and "raw_score" not in parsed:
        parsed["raw_score"] = parsed["floored_score"]

    return parsed


# ============================================================================
# Python Combiner — Floor Override + 가중평균
# ============================================================================

# 가중치 (잠정 — 1-2주 운영 후 calibration 권장)
WEIGHTS = {"market": 0.45, "news": 0.20, "disclosure": 0.35}

# Floor Override 임계값 — 모든 카테고리 raw ≥ 75 시 Floor 무효화 (시스템 위기 가림막 방지)
FLOOR_OVERRIDE_THRESHOLD = 75.0


def _cut_at_sentence(text: str, limit: int) -> str:
    """limit 자 이내에서 마지막 문장 경계(마침표·음슴체 종결)에서 컷.

    단어/문장 중간 자르기 방지. 적절한 경계가 limit 의 50% 위치보다 앞이면
    (= 너무 많이 잘림) 그냥 limit 그대로 컷.
    """
    if len(text) <= limit:
        return text
    cut = text[:limit]
    # 음슴체 종결 + 일반 마침표 위치 — 가장 마지막 경계
    last = max(cut.rfind(s) for s in ("함.", "됨.", "임.", "음.", "없음.", "."))
    if last > limit * 0.5:
        return cut[:last + 1]
    return cut


def _disclosure_kpi_deltas(periodic_kpi: list | None) -> list:
    """신규 정기공시(is_new_filing=True) fund 의 전분기 대비 KPI '변동'만 추출.

    carry-over fund(매 batch 같은 분기 데이터)는 이미 옛 뉴스라 제외 → 신규 공시 없는
    날엔 빈 리스트가 되어 Synthesis 가 연체율/NAV 절대값을 헤드라인으로 끌어쓰지 못함.
    신규 공시가 있으면 그날의 실제 분기 변동(증감률/증감폭)이 들어가 헤드라인 가능.
    """
    out = []
    for f in periodic_kpi or []:
        if not f.get("is_new_filing"):
            continue
        nav, nav_p = f.get("nav_per_share"), f.get("nav_per_share_prev")
        na, na_p = f.get("nonaccrual_pct"), f.get("nonaccrual_pct_prev")
        pik, pik_p = f.get("pik_ratio_pct"), f.get("pik_ratio_pct_prev")
        item = {"fund": f.get("fund_name")}
        if nav is not None and nav_p:
            item["nav_change_pct"] = round((nav - nav_p) / nav_p * 100, 1)
        if na is not None and na_p is not None:
            item["nonaccrual_change_pp"] = round(na - na_p, 1)
        if pik is not None and pik_p is not None:
            item["pik_change_pp"] = round(pik - pik_p, 1)
        if len(item) > 1:  # 변동값이 하나라도 있으면 포함
            out.append(item)
    return out


# ── standing KPI post-processing ────────────────────────────────────────
# disclosure_new_periodic_filing == False 인데 LLM 이 disclosure_insight 안의
# NAV/PIK/연체율 을 헤드라인에 그대로 옮기는 사례가 반복돼 (prompt rule 로도
# 완전 차단 안 됨) 코드 레벨 방어선 추가.
_STANDING_KPI_PATTERNS = [
    re.compile(r"NAV\s*[-+]?\d"),                    # "NAV -32.60"
    re.compile(r"NAV.*?(?:급락|폭락|하락|악화|급감)"),  # "NAV -32.60% 급락"
    re.compile(r"(?:연체율|Non[-\s]?accrual)\s*\d", re.IGNORECASE),  # "연체율 4.2%"
    re.compile(r"PIK\s*(?:비율|ratio)?\s*\d", re.IGNORECASE),        # "PIK 11.8%" / "PIK ratio 11.8%"
]


def _contains_standing_kpi(text: str) -> bool:
    """정기공시 KPI (NAV/PIK/연체율) 표현 검출."""
    return any(p.search(text) for p in _STANDING_KPI_PATTERNS)


def _strip_standing_kpi_sentences(text: str) -> str:
    """문장 단위로 쪼갠 뒤 standing KPI 문장만 제거."""
    # 한국어 종결어미 (음/함/됨/임/했음 등) 뒤 or 마침표 뒤에서 분리
    sentences = re.split(r"(?<=[.!?])\s+|(?<=[음됨함임했])\s*[,.]?\s+", text)
    kept = [s for s in sentences if s.strip() and not _contains_standing_kpi(s)]
    return " ".join(kept).strip()


def synthesize_insight(market_r: dict, news_r: dict, disclosure_r: dict,
                        composite: dict, prev_composite: dict | None = None,
                        periodic_kpi: list | None = None,
                        new_8k_items: list | None = None) -> str:
    """3개 카테고리 + composite 결과 → 통합 한 줄 요약 (음슴체).

    1차 호출 → summary_insight 비어있으면 nudge prompt 로 1회 재시도 (temp=0 에선
    plain 재시도가 같은 결과 내므로 prompt 변경이 필요). 그래도 실패 시 카테고리별
    insight 단순 결합 후 문장 경계에서 컷.
    """
    # 신규 시그널 모음 — 새로움 우선 원칙용.
    # disclosure_kpi_changes 는 standing 절대값이 아니라 '신규 공시된 분기 변동'만 (carry-over 제외).
    # disclosure_new_8k_items 는 오늘 신규 제출된 8-K/수시공시 (헤드라인 후보).
    novelty_signals = {
        "news_new_facts_24h": (news_r.get("novelty_report") or {}).get("new_facts_24h", []),
        "news_escalation": (news_r.get("novelty_report") or {}).get("escalation_detected", ""),
        "news_de_escalation": (news_r.get("novelty_report") or {}).get("de_escalation_detected", ""),
        "market_top_red_flags": market_r.get("top_red_flags", []),
        "disclosure_kpi_changes": _disclosure_kpi_deltas(periodic_kpi),
        "disclosure_new_8k_items": [
            {
                "fund": (it.get("fund_name") or "")[:60],
                "form": (it.get("form") or "")[:20],
                "summary": (it.get("summary_kr") or it.get("summary_en") or "")[:200],
            }
            for it in (new_8k_items or [])
        ],
    }
    # 오늘 신규로 제출된 정기공시(10-Q/10-K)가 있는지 — 결정론적 플래그.
    # false 면 정기공시 KPI(NAV·연체율·PIK)는 수 주 전 제출된 standing 데이터이므로
    # synthesis 가 헤드라인에 끌어쓰지 못하게 막는다 (carry-over KPI 재서술 차단).
    disclosure_new_periodic_filing = any(
        f.get("is_new_filing") for f in (periodic_kpi or [])
    )
    payload = {
        "composite": {
            "composite_score": composite.get("composite_score"),
            "risk_level": composite.get("risk_level"),
            "score_delta_vs_yesterday": composite.get("score_delta_vs_yesterday", {}),
            "floor_override_triggered": composite.get("floor_override_triggered", False),
        },
        "market_insight": market_r.get("summary_insight", ""),
        "news_insight": news_r.get("summary_insight", ""),
        "disclosure_insight": disclosure_r.get("summary_insight", ""),
        "disclosure_new_periodic_filing": disclosure_new_periodic_filing,
        "category_deltas": {
            "market": market_r.get("score_delta", {}),
            "news": news_r.get("score_delta", {}),
            "disclosure": disclosure_r.get("score_delta", {}),
        },
        "yesterday_summary": (prev_composite or {}).get("summary_insight", ""),
        "novelty_signals": novelty_signals,
    }
    user_input = json.dumps(payload, ensure_ascii=False)

    def _try(prompt_text: str, tag: str) -> str:
        """한 번 호출해서 summary_insight 텍스트 추출. 실패 시 빈 문자열."""
        print(f"  [{tag}] LLM 호출 (model={_active_model()})")
        try:
            resp = _generate(prompt_text, user_input)
        except Exception as exc:  # noqa: BLE001
            print(f"  [{tag}] LLM 호출 실패: {exc}")
            return ""
        if not resp:
            print(f"  [{tag}] 빈 응답")
            return ""
        raw = (resp.text or "").strip()
        parsed = _parse_json_response(raw, tag)
        return (parsed.get("summary_insight") or "").strip()

    def _enforce_kpi_ban(text_in: str) -> str:
        """정기공시 KPI 인용 방어선 — disclosure_new_periodic_filing == false 일 때
        LLM 이 NAV/PIK/연체율 을 헤드라인에 넣으면 재생성 → 실패 시 문장 삭제."""
        if not text_in or disclosure_new_periodic_filing:
            return text_in
        if not _contains_standing_kpi(text_in):
            return text_in
        print("  [Synthesis] ⚠ 응답에 standing KPI (NAV/PIK/연체율) 감지 — 재생성")
        kpi_nudge = (
            "\n\n[★★★ 재시도 — 이전 응답이 rule 위반] "
            f'이전 draft: "{text_in}"\n'
            "위 draft 에 정기공시 KPI (NAV/PIK/연체율/Non-accrual) 표현 포함됨. "
            "오늘 disclosure_new_periodic_filing == false 이므로 이 표현들은 "
            "수 주 전 10-Q 의 standing 데이터 — 오늘의 신규 사건 아님. "
            "NAV/연체율/PIK/Non-accrual 단어와 그에 딸린 수치·급락/하락/악화 표현을 "
            "모두 삭제하고, 신규 8-K 사건 / 뉴스 / 시장 (주가·HY·국채) 시그널 만으로 재작성할 것."
        )
        retry = _try(SYNTHESIS_PROMPT + kpi_nudge, "Synthesis(kpi-strip)")
        if retry and not _contains_standing_kpi(retry):
            print("  [Synthesis] ✓ 재생성 성공 — KPI 제거됨")
            return retry
        # 재시도도 위반이면 문장 단위 삭제 폴백
        stripped = _strip_standing_kpi_sentences(retry or text_in)
        if stripped.strip():
            print("  [Synthesis] ⚠ 재시도 실패 — standing KPI 문장 강제 삭제")
            return stripped
        print("  [Synthesis] ⚠ 삭제 후 텍스트 없음 — 최종 폴백 메시지")
        return "오늘 신규 공시 KPI 변동 없음 — 이전 흐름 지속함."

    # 1차 시도
    text = _try(SYNTHESIS_PROMPT, "Synthesis")
    if text:
        return _enforce_kpi_ban(text)

    # 2차 시도 — nudge 추가 (temp=0 에선 같은 prompt 면 같은 답이라 prompt 를 바꿔야 함)
    print("  [Synthesis] ⚠ 1차 응답의 summary_insight 비어있음 — nudge 재시도")
    nudge = ("\n\n[★ 재시도 — 이전 시도에서 summary_insight 필드가 비어있었음] "
             "summary_insight 필드를 반드시 한국어 1~2 문장, 80~140자 분량으로 채워서 답하라. "
             "절대 빈 문자열로 두지 말 것. 입력의 market_insight / news_insight / "
             "disclosure_insight 중 가장 큰 변화를 한 줄로 표현하라.")
    text = _try(SYNTHESIS_PROMPT + nudge, "Synthesis(retry)")
    if text:
        print("  [Synthesis] ✓ 재시도 성공")
        return _enforce_kpi_ban(text)
    print("  [Synthesis] ⚠ 재시도도 실패 — 카테고리 단순 결합 폴백")

    # 폴백 — 카테고리 insight 단순 결합, 문장 경계에서 컷
    parts = [
        market_r.get("summary_insight", "").strip(),
        news_r.get("summary_insight", "").strip(),
        disclosure_r.get("summary_insight", "").strip(),
    ]
    parts = [p for p in parts if p]
    if not parts:
        return "오늘 데이터 미수집으로 어제 수준 유지함."
    return _cut_at_sentence(" ".join(parts), 120)


def combine_scores(market_r: dict, news_r: dict, disclosure_r: dict,
                    previous_composite: dict | None) -> dict:
    """3 카테고리 결과 → 종합 점수. Floor Override 판정 + 가중평균."""
    raws = {
        "market": float(market_r.get("raw_score", 50)),
        "news": float(news_r.get("raw_score", 50)),
        "disclosure": float(disclosure_r.get("raw_score", 50)),
    }

    # Floor Override: 3개 카테고리 raw 가 모두 임계값 이상이면 Floor 무효화
    override = all(s >= FLOOR_OVERRIDE_THRESHOLD for s in raws.values())

    def _pick(r: dict) -> float:
        if override:
            return float(r.get("raw_score", 50))
        return float(r.get("floored_score", r.get("raw_score", 50)))

    finals = {
        "market": _pick(market_r),
        "news": _pick(news_r),
        "disclosure": _pick(disclosure_r),
    }

    composite = (
        finals["market"] * WEIGHTS["market"]
        + finals["news"] * WEIGHTS["news"]
        + finals["disclosure"] * WEIGHTS["disclosure"]
    )
    composite = round(composite, 1)

    # 등급 분류 (100=위험)
    risk_level = (
        "Very Low" if composite < 20 else
        "Low" if composite < 40 else
        "Neutral" if composite < 60 else
        "High" if composite < 80 else
        "Very High"
    )

    # 어제 대비 변화량
    prev_score = (
        float(previous_composite.get("composite_score", composite))
        if previous_composite else composite
    )
    delta = round(composite - prev_score, 1)
    direction = "Worse" if delta > 1 else "Better" if delta < -1 else "Stable"

    # 데이터 가용성 진단 — "Data Unavailable"(데이터 누락) + "LLM Failure"(LLM 실패) 둘 다 carry-over
    def _is_carried(r: dict) -> bool:
        status = r.get("score_delta", {}).get("status", "")
        return "Carried Over" in status

    carried = []
    if _is_carried(market_r):
        carried.append("market")
    if _is_carried(news_r):
        carried.append("news")
    if _is_carried(disclosure_r):
        carried.append("disclosure")

    return {
        "analysis_date": ANALYSIS_DATE.isoformat() if BACKFILL_MODE else _today_kst().isoformat(),
        "composite_score": composite,
        "category_scores": {
            "market": {"raw": round(raws["market"], 1), "final": round(finals["market"], 1)},
            "news": {"raw": round(raws["news"], 1), "final": round(finals["news"], 1)},
            "disclosure": {"raw": round(raws["disclosure"], 1), "final": round(finals["disclosure"], 1)},
        },
        "weights": WEIGHTS,
        "floor_override_triggered": override,
        "score_delta_vs_yesterday": {
            "value": delta,
            "direction": direction,
        },
        "risk_level": risk_level,
        "data_health": {
            "categories_with_fresh_data": 3 - len(carried),
            "categories_carried_over": carried,
        },
    }


# ============================================================================
# 메인 파이프라인
# ============================================================================

def daily_pipeline() -> dict:
    print("=" * 60)
    print("리스크 종합점수 산출 파이프라인 (V2.1)")
    print("=" * 60)

    # 0) 이전 결과 로드
    prev_all = {}
    if HISTORY_FILE.exists():
        try:
            prev_all = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"[WARN] {HISTORY_FILE.name} 파싱 실패 — 빈 prev 로 시작")

    # 1) 데이터 로딩
    print("\n[1/6] 데이터 로딩")
    today = {
        "market": _load_market_data(),
        "news": _load_news_data(),
        "disclosure": _load_disclosure_data(),
    }
    print(f"  · market    tickers: {len(today['market']['tickers'])} ({today['market'].get('data_status')})")
    print(f"  · news      items:   {today['news']['count']} ({today['news'].get('data_status')})")
    print(f"  · disclosure items:  {today['disclosure']['count']} ({today['disclosure'].get('data_status')})")

    # 2) Market Agent
    print("\n[2/6] Market Agent")
    market_r = _agent_score(MARKET_PROMPT, today["market"],
                             prev_all.get("market"), "Market")

    # 3) News Agent
    print("\n[3/6] News Agent")
    news_r = _agent_score(NEWS_PROMPT, today["news"],
                           prev_all.get("news"), "News")

    # 4) Disclosure Agent
    print("\n[4/6] Disclosure Agent")
    disclosure_r = _agent_score(DISCLOSURE_PROMPT, today["disclosure"],
                                 prev_all.get("disclosure"), "Disclosure")

    # 5) Python Combiner
    print("\n[5/6] Combiner — Floor Override 판정 + 가중평균")
    composite = combine_scores(market_r, news_r, disclosure_r,
                                prev_all.get("composite"))

    # 6) Synthesis Agent — 3 카테고리 + composite 결과를 통합 한 줄로 요약
    #    어제 composite 도 같이 전달 → 새로움 우선 (어제와 동일 헤드라인 반복 방지)
    print("\n[6/6] Synthesis — 통합 한 줄 요약 생성")
    composite["summary_insight"] = synthesize_insight(
        market_r, news_r, disclosure_r, composite,
        prev_composite=prev_all.get("composite"),
        periodic_kpi=today["disclosure"].get("periodic_kpi"),
        new_8k_items=today["disclosure"].get("new_today_items"),
    )

    # 점수 히스토리 누적 — 이전 history 에 오늘 결과 append (같은 날짜면 덮어쓰기).
    # 매일 추이 차트가 실데이터로 채워지도록 보존.
    # reasoning 필드 — 각 카테고리 LLM 의 사고 과정 (구조화된 근거) 도 일별로 보존
    prev_history = list(prev_all.get("history", []))
    today_entry = {
        "date": composite.get("analysis_date"),
        "composite_score": composite.get("composite_score"),
        "risk_level": composite.get("risk_level"),
        "summary_insight": composite.get("summary_insight"),
        "category_scores": composite.get("category_scores"),
        "floor_override_triggered": composite.get("floor_override_triggered", False),
        # ★ 일별 LLM 사고 과정 보존 — 점수 산출 근거가 된 구조화 출력 (current top-level 와 동일 깊이)
        "reasoning": {
            "market": {
                "summary_insight": market_r.get("summary_insight"),
                "top_red_flags": market_r.get("top_red_flags"),
                "conclusions": market_r.get("conclusions"),
            },
            "news": {
                "summary_insight": news_r.get("summary_insight"),
                "novelty_report": news_r.get("novelty_report"),
                "daily_comparison": news_r.get("daily_comparison"),
            },
            "disclosure": {
                "summary_insight": disclosure_r.get("summary_insight"),
                "epicenter_focus": disclosure_r.get("epicenter_focus"),
                "market_anchor_check": disclosure_r.get("market_anchor_check"),
                "financial_kpi_summary": disclosure_r.get("financial_kpi_summary"),
            },
        },
    }
    prev_history = [h for h in prev_history if h.get("date") != today_entry["date"]]
    prev_history.append(today_entry)
    prev_history.sort(key=lambda h: h.get("date", ""))

    # 저장 — 기존 top-level 키(market/news/disclosure/composite) 는 latest 스냅샷 그대로 유지,
    # history 는 신규 추가 (app.py 추이 차트가 이 배열을 읽음).
    history_out = {
        "market": market_r,
        "news": news_r,
        "disclosure": disclosure_r,
        "composite": composite,
        "history": prev_history,
    }
    DATA.mkdir(exist_ok=True)
    HISTORY_FILE.write_text(
        json.dumps(history_out, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 출력 요약
    print("\n" + "=" * 60)
    print(f"종합 점수: {composite['composite_score']:.1f} ({composite['risk_level']})")
    delta_info = composite["score_delta_vs_yesterday"]
    print(f"전일 대비: {delta_info['value']:+.1f} ({delta_info['direction']})")
    cs = composite["category_scores"]
    print(f"  · 시장:   raw {cs['market']['raw']:.1f} → final {cs['market']['final']:.1f}")
    print(f"  · 뉴스:   raw {cs['news']['raw']:.1f} → final {cs['news']['final']:.1f}")
    print(f"  · 공시:   raw {cs['disclosure']['raw']:.1f} → final {cs['disclosure']['final']:.1f}")
    if composite["floor_override_triggered"]:
        print("Floor Override: 발동 (raw ≥ 75 동시) — 시스템 위기 신호")
    if composite["data_health"]["categories_carried_over"]:
        print(f"⚠  Carry Over: {composite['data_health']['categories_carried_over']}")
    print(f"\n저장: {HISTORY_FILE}")
    print("=" * 60)

    return composite


if __name__ == "__main__":
    daily_pipeline()
