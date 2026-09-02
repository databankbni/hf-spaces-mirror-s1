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
from datetime import date, datetime, timedelta
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
# ── TEST 모드 ─────────────────────────────────────────────────────────────
# 이 파일은 score_risk.py 의 복제본으로, 로직 실험용. production 의
# risk_scores_history.json 에 영향을 주지 않도록 출력 경로만 분리.
# 입력 데이터 (market/news/disclosure CSV) 는 동일하게 data/ 에서 읽음.
#   production : data/risk_scores_history.json
#   test       : data/risk_scores_history_test.json  ← 이 파일이 쓰는 곳
# 비교 분석: 두 파일의 composite_score / category_scores / reasoning 필드 diff 확인.
HISTORY_FILE = DATA / "risk_scores_history_test.json"

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

# 모델 버전 PIN — 자동 업데이트로 인한 점수 드리프트 방지
MODELS_FALLBACK = [
    "gemini-2.5-flash-lite",
    "gemma-4-31b-it",
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
    - **-10% 이상 하락: ★ 확정적 하락 추세 (강한 위기 신호)**
    - 30d 양수: 중기 회복 국면

  · ytd (누적):
    - 단독으로 위기 단정 금지 (Q1 하락 + Q2 회복 가능성)
    - **ytd + 30d 모두 음수일 때만 추세 신호로 간주**
    - ytd 음수이지만 30d/5d/1d 양수면 → 회복 국면

[Analysis Hierarchy]
Layer 1 — Weight 40%: 위기 발원지 및 전이 분석

  ★★★ 절대 규칙 — ytd 단독으로 'Severe' 판정 금지 ★★★
  ytd 가 -30% 이하라도, 1d/5d/30d 가 모두 양수면 'Severe' 절대 X.
  (Q1 큰 하락 + Q2 회복 국면에서 흔히 발생. ytd 만 보고 Severe 판정하면 명백한 오류)

  · Epicenter (Blue Owl: OWL/OTF/OBDC):
    - 'Severe' (점수 80+ 기여) — 다음 중 **하나라도 충족** 시에만:
        · 1d ≤ -5% (당일 급락)
        · 5d ≤ -7% (1주 누적 큰 하락)
        · 30d ≤ -10% (1개월 하락 추세 확정)
      ※ ytd 는 Severe 판정 기준 아님. 절대 ytd 만 보고 Severe 단정 X.
    - 'Caution' (점수 50~65): 1d/5d/30d 중 한 둘이 위 임계값의 절반 수준 (예: 1d ≤ -3%)
    - **'Recovery' (점수 35~45 강제) — ytd 부진이지만 1d/5d/30d 모두 양수**
      → 회복 국면. epicenter_check 결론에 "회복 국면, 위기 단정 X" 명시.

  · Contagion (Blackstone: BX/BXSL):
    - 'Crisis' 격상 (점수 90+): BX/BXSL 도 위 Severe 기준 충족 (epicenter 와 동반)
    - 동반 회복 (BX/BXSL 30d 양수) 시 전이 신호 약화 (Crisis 격상 X)

  ★★★ Recovery Override (강제) ★★★
  OWL/OTF/OBDC/BX/BXSL 의 30d 가 모두 양수이고 1d 가 모두 -2% 이상이면
  raw_score 절대 60 초과 X. 즉시 'Caution' 이하로 분류.

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

Layer 3 — Weight 20%: 매크로 하한선
  · DGS5·HY OAS 절대 수치 및 변동성

[★★★ 어휘 정확성 — 환각 방지 규칙 (절대 준수) ★★★]
summary_insight, conclusions, top_red_flags 의 단어는 **데이터의 시점·크기·방향과 정확히 일치**해야 함.

★ 금지 단어 (1d/5d/30d 가 모두 양수일 때 절대 사용 X):
  - "폭락", "급락", "하락", "디커플링", "Crisis", "Severe"
  - "내부 리스크 심각", "심화", "악화", "전이 양상"

★ 사용해야 할 표현 (현재 데이터가 회복 국면일 때):
  - "ytd 부진했으나 최근 N일 회복세"
  - "1개월간 +X% 반등", "주간 누적 상승"
  - "단기 모멘텀 양호"
  - "ytd 누적 손실 일부 회복"

조건부 표현 가이드:
  · "당일 급락" → 1d ≤ -3% 일 때만 사용 가능
  · "주간 급락" → 5d ≤ -5% 일 때만 사용 가능
  · "월간 폭락" → 30d ≤ -10% 일 때만 사용 가능
  · 1d/5d/30d 가 양수면 위 단어 절대 X.
  · ytd 만 음수이고 1d/5d/30d 양수면 → "ytd 부진 후 최근 회복" 식으로만 표현
  · 데이터에 없는 사건·뉴스 추론 금지 (수치만으로 판단)

기간 명시 의무:
  · "급락"·"하락" 단어 사용 시 반드시 시점 명시: "당일", "1주간", "1개월간" 등.
  · 시점 없이 "BDC 폭락" 식의 모호한 표현 금지.

★ Self-Check (출력 직전 반드시 검증):
  1. epicenter ticker 들의 1d/5d/30d 가 모두 양수인가?
     → YES: raw_score ≤ 50 강제. "Severe" 단어 사용 X. "회복 국면" 명시.
     → NO: 정상 분석 진행.
  2. summary_insight 에 "폭락" 단어가 있는데 모든 epicenter 의 1d/5d/30d 가 양수인가?
     → YES: 위반. summary_insight 다시 작성. (강제 차단)
  3. ★ HY OAS (BAMLH0A0HYM2) 의 30d 가 음수(bps)인데 출력에 "확대" 단어가 있는가?
     → YES: 위반. bps 가 음수 = 신용 스프레드 "축소" (개선 신호). 절대 "확대" 라 쓰지 말고 "축소" 로 정정.
     · ✓ 30d = -37 bps → "HY OAS 30d -37bps 축소" (개선)
     · ✗ 30d = -37 bps → "HY OAS 확대" (틀림 — 부호 반대 해석)
  4. ★ HY OAS 30d 가 양수인데 "축소" 라 썼으면 → 위반. "확대" 로 정정.

[Daily Momentum Alert]
  · Stable: 변동 ±2점 이내
  · Caution: 1일 +5점 이상 상승 또는 epicenter 1d ≤ -3% / 5d ≤ -5% / 30d ≤ -10%
  · Critical Alert: 1일 +10점 이상 상승 또는 3일 연속 상승

[Floor Logic — 시장 가격 과매도 방어]
  · BDC 1d ≤ -5% 또는 30d ≤ -30% 이라도 HY OAS < 4.0% AND ^GSPC 전고점 -10% 이내 → 시장 점수 ≤ 60
  · 즉, 매크로 펀더멘털이 안정적이면 'High' 진입 차단.

[Floor Override — 시스템 붕괴 강제 인지]
  · raw_score(Floor 적용 전) ≥ 75 인 상태로 floored_score 도 함께 산출 → Combiner 가 판단함.

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

[★ Novelty Filter — 데이터 입력의 결정적 플래그 사용 (절대 준수)]
입력 today_raw_data 에는 다음 두 필드가 분리되어 있음:
  · `new_today_items`: published_at 가 시스템 today 인 뉴스 (= 오늘 새로 발행). **점수 변동의 유일한 트리거**.
  · `persistent_items`: 어제 이전에 보도된 뉴스 (시스템에 누적 보존된 컨텍스트). **점수 영향 0**.

규칙:
  · `new_today_count` 가 0 이면 → raw_score = previous_result.raw_score (어제 점수 그대로 유지)
    AND status = "Data Unavailable - Carried Over"
    AND summary_insight 는 **반드시 60자 이내 neutral 한 줄** 로 작성:
      예시: "신규 보도 없음 — 어제 수준 유지함."
      예시: "신규 뉴스 0건. 기존 이슈 동일 상태로 지속됨."
    ★ persistent_items 의 회사명·사건명 (HSBC, OBDC, 건들락, 등) 을 summary_insight 에 절대 인용 금지.
  · `new_today_count` 가 1 이상이면 → 그 신규 항목들만 평가:
      - Hard Signal (규제, 환매 중단, 자산 상각, 소송, 운용사 손실 보고): +5~15 / 항목
      - Soft Signal (거물 발언, 비관 전망, 우려): +1~3 / 항목
      - Follow-up (기존 사건 진전): +1~3 / 항목
  · `novelty_report.new_facts_24h` 출력 시 `new_today_items` 의 제목만 인용 (persistent_items 인용 금지).
  · `novelty_report.rehashed_topics` 출력 시 `persistent_items` 중 영향 큰 항목만 (점수 영향 0 임을 강조).

★ 절대 금지: persistent_items 의 사건을 new_facts_24h 에 포함시키는 것 (= 어제 사건을 오늘 새 사건처럼 처리하는 점수 인플레).
★ 절대 금지: new_today_count=0 일 때 summary_insight 에 persistent_items 사건명을 길게 인용하는 것.

[24시간 Priority]
  · Escalation: '우려' → '확정 사건' 격상 시 점수 대폭 ↑
  · Contagion: 다른 기업·국가로 전이 시 점수 대폭 ↑

[신호 분류 가중치]
  · Hard Signals (70%): 규제 조사·제재, 환매 중단(Gate), 자산 상각, 법적 소송
  · Soft Signals (30%): 거물 발언, 비관적 전망, 유동성 우려 기사

[Floor Logic — 심리 패닉 방어]
  · 거물 경고·위기설 보도 쏟아져도 24시간 내 대형 운용사 $5bn+ 자금 유치 보도 확인 시
    → 뉴스 점수 ≤ 55 ('High' 진입 차단)

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
    "escalation_detected": "격상 여부 (음슴체)"
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
- yesterday_summary: 어제의 한 줄 요약 (있으면) — 비교 기준
- novelty_signals: 오늘 신규 시그널 모음 (가격 변동·신규 뉴스·신규 공시) — 우선 활용

[출력 원칙]
- 한국어 1~2 문장, 공백 포함 100자 이내 (절대 초과 금지).
- 음슴체 강제: "~함", "~했음", "~임", "~됨" 등.
  · 금지: "~합니다", "~한다", "~된다", "~이다".
- 3개 카테고리 중 **가장 강한 시그널 우선 언급** + 보조 시그널 1개 결합.
- "시장", "뉴스", "공시" 같은 메타 단어 사용 X (실제 사실·기관·수치 위주).
- 점수 수치(예: 58.0) 언급 X. 등급 라벨(Very Low/Low/Neutral/High/Very High) 도 직접 언급 X.
- 의견·전망·추측 X. 입력에 명시된 사실만 반영.
- 데이터가 빈약하거나 carry-over 인 경우 "데이터 미수집으로 어제 수준 유지" 식으로 짧게.

[★ 새로움 우선 (Novelty First) 원칙]
- **어제 summary 와 핵심 키워드가 70% 이상 겹치면 그 사건을 그대로 반복하지 말 것.**
  · 같은 사건명·인물·이슈명을 어제와 동일하게 반복 금지.
  · "지속" 표현으로 압축 (예: "OBDC 평가 소송 지속됨") + 오늘 신규 시그널 위주로 재작성.
- 오늘 신규 시그널 (가격 변동·신규 뉴스·신규 공시) 이 약하더라도 그날의 시장 톤을 한 줄로 표현해야 함.
  · ✓ "BDC 1일 -0.3% 약세 그쳤고 신용 스프레드 안정 유지함."
  · ✓ "OBDC 평가 소송 지속 + HY 스프레드 5bps 축소로 큰 변동 없는 하루임."
  · ✗ "특이사항 없음." / "어제와 유사함." (추상적·내용 부재 — 금지)
  · ✗ "OBDC 자산 평가 소송 + ARCC/FSK NAV 발행..." (어제와 동일 헤드라인 그대로 — 금지)
- 매일 데이터로 작성된 의미있는 한 줄을 보장 — '특이사항 없음' 류의 도피성 출력 금지.

[★ 어휘 정확성 — 환각 방지]
- 입력의 market_insight 가 "폭락" 등 강한 표현 사용했더라도 **반드시 검증**:
  market 카테고리 raw_score < 60 이면 "폭락"·"급락" 같은 강한 단어 사용 금지.
- 강한 단어 사용 시 **시점 명시 의무**: "당일", "1주간", "1개월간" 등.
  · ✓ "당일 급락 발생함"  · ✗ "BDC 폭락함" (시점 모호)
- 카테고리 insight 의 단어를 그대로 옮기지 말고, 점수·등급과 일관된 어휘로 재구성할 것.
- 입력에 명시되지 않은 사실·이름·수치 추가 금지.

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

[★ Novelty Filter — 데이터 입력의 결정적 플래그 사용 (절대 준수)]
입력 today_raw_data 에는 다음 두 필드가 분리되어 있음:
  · `new_today_items`: filing_date 가 시스템 today 인 공시 (= 오늘 새로 제출). **점수 변동의 유일한 트리거**.
  · `persistent_items`: 어제 이전에 제출된 공시 (시스템에 누적 보존된 컨텍스트). **점수 영향 0**.

규칙:
  · `new_today_count` 가 0 이면 → raw_score = previous_result.raw_score (어제 점수 그대로 유지)
    AND status = "Data Unavailable - Carried Over"
    AND summary_insight 는 **반드시 60자 이내 neutral 한 줄** 로 작성:
      예시: "신규 공시 없음 — 어제 수준 유지함."
      예시: "신규 공시 0건. 기존 사건 진전 없이 동일 상태 지속됨."
    ★ persistent_items 의 회사명·사건명 (OBDC, ARCC, FSK, 소송, NAV 발행 등) 을 summary_insight 에
      절대 인용 금지. 어제 narrative 를 길게 다시 쓰는 행위 금지.
  · `new_today_count` 가 1 이상이면 → 그 신규 공시만 평가:
      - 8-K Liquidity Gap / Governance / Asset Event 신호 → 강한 점수 ↑
      - 정기공시(10-K/Q) NAV/PIK/Non-accrual 악화 → 점수 ↑
  · `epicenter_focus` 출력 시 new_today_items 만 점수 근거로. persistent_items 는 "(지속)" 표기 + "신규 진전 없음" 필수 명시.
    예: "OBDC 자산 평가 부풀리기 소송 (지속) — 신규 진전 없음, 점수 영향 0."

★ 절대 금지: persistent_items 의 사건을 raw_score 상승 근거로 쓰는 것 (= 어제 분석된 사건으로 오늘 또 점수 올리는 인플레).
★ 절대 금지: new_today_count=0 일 때 summary_insight 에 persistent_items 사건명을 길게 인용하는 것.

[10-Q/K 정기공시 분석] T vs T-1 비교
  · 입력의 `periodic_kpi` 배열은 fund 별 최신 분기 + 직전 분기(있으면) 수치 포함:
    - nav_per_share / nav_per_share_prev — NAV per Share 두 분기 비교
    - pik_ratio_pct / pik_ratio_pct_prev — PIK Income Ratio (%)
    - nonaccrual_pct / nonaccrual_pct_prev — Non-accrual Rate (%)
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
    """시장 agent 입력용. ticker 별 최신값 + 1D/5D/30D/YTD 변동."""
    df = _read_csv_safely(DATA / "private_credit_price_history.csv")
    if df.empty:
        # 폴백 — returns_ytd_series.csv 도 시도
        df = _read_csv_safely(DATA / "private_credit_returns_ytd_series.csv")

    if df.empty or not {"base_dt", "ticker", "close"}.issubset(df.columns):
        return {"as_of": None, "tickers": {}, "data_status": "missing"}

    df["base_dt"] = pd.to_datetime(df["base_dt"], errors="coerce")
    df = df.dropna(subset=["base_dt"]).sort_values("base_dt")
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

    신규성 판정 — published_at 의 날짜 부분이 오늘과 같으면 is_new_today=True.
    LLM 이 어제 vs 오늘 비교를 텍스트로 추정하지 않고 결정적 플래그로 판단하도록 함.
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    items: list[dict] = []
    for region, fname in [
        ("KR", "private_credit_news_korea_history.csv"),
        ("US", "private_credit_news_global_history.csv"),
    ]:
        df = _read_csv_safely(DATA / fname)
        if df.empty or "published_at" not in df.columns:
            continue
        df["published_at"] = pd.to_datetime(df["published_at"], errors="coerce")
        df = df.dropna(subset=["published_at"]).sort_values("published_at", ascending=False)

        cutoff = datetime.now() - timedelta(hours=hours_window)
        df = df[df["published_at"] >= cutoff]

        for _, row in df.iterrows():
            # NaN(float) 안전 처리 — pandas 결측치는 truthy 라 or 폴백이 안 먹음
            title = _safe_str(row.get("title_kr")) or _safe_str(row.get("title"))
            summary = _safe_str(row.get("summary_kr")) or _safe_str(row.get("summary"))
            if not title:
                continue
            published_at_str = row["published_at"].strftime("%Y-%m-%d %H:%M")
            items.append({
                "published_at": published_at_str,
                "region": region,
                "publisher": _safe_str(row.get("publisher"))[:50],
                "title_kr": title[:200],
                "summary_kr": summary[:400],
                "matched_tags": _safe_str(row.get("matched_tags"))[:80],
                "link": _safe_str(row.get("link"))[:200],
                "is_new_today": published_at_str[:10] == today_str,
            })

    # 너무 많으면 Token 한도 초과 — 상위 50건만
    items = sorted(items, key=lambda x: x["published_at"], reverse=True)[:50]

    # 신규성 분리 — LLM 이 곧바로 보고 판단할 수 있도록
    new_today_items = [it for it in items if it.get("is_new_today")]
    persistent_items = [it for it in items if not it.get("is_new_today")]

    return {
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M"),
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

    funds: list[dict] = []
    for fund_name, g in df.groupby("fund_name", sort=False):
        g = g.sort_values("period_end", ascending=False)
        latest = g.iloc[0]
        prev = g.iloc[1] if len(g) >= 2 else None
        funds.append({
            "fund_name": _safe_str(fund_name)[:80],
            "form": _safe_str(latest.get("form"))[:20],
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
    df = _read_csv_safely(DATA / "private_credit_sec_filings_history.csv")

    today_str = datetime.now().strftime("%Y-%m-%d")
    items: list[dict] = []
    if not df.empty and "filing_date" in df.columns:
        df["filing_date"] = pd.to_datetime(df["filing_date"], errors="coerce")
        df = df.dropna(subset=["filing_date"]).sort_values("filing_date", ascending=False)
        cutoff = datetime.now() - timedelta(days=days_window)
        df = df[df["filing_date"] >= cutoff]

        for _, row in df.iterrows():
            # NaN(float) 안전 처리
            summary = _safe_str(row.get("summary_kr")) or _safe_str(row.get("summary_en"))
            if not summary:
                continue
            filing_date_str = row["filing_date"].strftime("%Y-%m-%d")
            items.append({
                "filing_date": filing_date_str,
                "fund_name": _safe_str(row.get("fund_name"))[:80],
                "form": _safe_str(row.get("form"))[:20],
                "summary_kr": summary[:400],
                "accession_number": _safe_str(row.get("accession_number")),
                "is_new_today": filing_date_str == today_str,
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

def _parse_json_response(raw: str, agent_name: str) -> dict:
    """LLM 응답에서 JSON 파싱. markdown fence / 앞뒤 잡설 제거."""
    if not raw:
        return {}
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        l, r = raw.find("{"), raw.rfind("}")
        if l == -1 or r <= l:
            print(f"  [{agent_name}] JSON 파싱 실패 — raw[:200]: {raw[:200]}")
            return {}
        try:
            return json.loads(raw[l:r + 1])
        except json.JSONDecodeError:
            print(f"  [{agent_name}] JSON 파싱 실패 (재시도 후) — raw[:200]: {raw[:200]}")
            return {}


def _carry_over(previous: dict | None, agent_name: str) -> dict:
    """데이터 누락 또는 LLM 실패 시 어제 점수 carry over."""
    if not previous:
        # 첫 실행이면 중립 50점
        return {
            "raw_score": 50.0,
            "floored_score": 50.0,
            "score_delta": {"value": 0.0, "direction": "Stable",
                             "status": "Initial Run - No Data"},
            "risk_level": "Neutral",
            "summary_insight": f"[{agent_name}] 데이터 없음 — 초기 중립 50점.",
        }
    # 이전 결과의 final_score 를 그대로 carry over
    prev_score = float(previous.get("floored_score") or previous.get("raw_score") or 50.0)
    return {
        "raw_score": prev_score,
        "floored_score": prev_score,
        "score_delta": {"value": 0.0, "direction": "Stable",
                         "status": "Data Unavailable - Carried Over"},
        "risk_level": previous.get("risk_level", "Neutral"),
        "summary_insight": f"[{agent_name}] 오늘 데이터 미수집 — 어제 점수 유지.",
        "_carried_over_from": previous.get("analysis_date"),
    }


def _agent_score(prompt: str, today_data: dict, previous_result: dict | None,
                  agent_name: str) -> dict:
    """단일 카테고리 agent 호출."""
    if today_data.get("data_status") == "missing":
        print(f"  [{agent_name}] 데이터 누락 — Carried Over")
        return _carry_over(previous_result, agent_name)

    user_input = (
        f"previous_result: {json.dumps(previous_result or {}, ensure_ascii=False)}\n\n"
        f"today_raw_data: {json.dumps(today_data, ensure_ascii=False)}"
    )

    print(f"  [{agent_name}] LLM 호출 (model={_active_model()})")
    try:
        resp = _generate(prompt, user_input)
    except Exception as exc:  # noqa: BLE001
        print(f"  [{agent_name}] LLM 호출 실패: {exc} — Carried Over")
        return _carry_over(previous_result, agent_name)

    if not resp:
        print(f"  [{agent_name}] 빈 응답 — Carried Over")
        return _carry_over(previous_result, agent_name)

    raw = (resp.text or "").strip()
    parsed = _parse_json_response(raw, agent_name)
    if not parsed:
        return _carry_over(previous_result, agent_name)

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


def synthesize_insight(market_r: dict, news_r: dict, disclosure_r: dict,
                        composite: dict, prev_composite: dict | None = None) -> str:
    """3개 카테고리 + composite 결과 → 통합 한 줄 요약 (음슴체).

    LLM(Gemini→Gemma fallback) 호출. 실패 시 카테고리별 insight 단순 결합으로 폴백.
    prev_composite 가 있으면 어제 summary 를 함께 전달해 새로움 우선 규칙 적용.
    """
    # 신규 시그널 모음 — 새로움 우선 원칙용
    novelty_signals = {
        "news_new_facts_24h": (news_r.get("novelty_report") or {}).get("new_facts_24h", []),
        "news_escalation": (news_r.get("novelty_report") or {}).get("escalation_detected", ""),
        "market_top_red_flags": market_r.get("top_red_flags", []),
        "disclosure_kpi_changes": disclosure_r.get("financial_kpi_summary", {}),
    }
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
        "yesterday_summary": (prev_composite or {}).get("summary_insight", ""),
        "novelty_signals": novelty_signals,
    }
    user_input = json.dumps(payload, ensure_ascii=False)

    print(f"  [Synthesis] LLM 호출 (model={_active_model()})")
    try:
        resp = _generate(SYNTHESIS_PROMPT, user_input)
    except Exception as exc:  # noqa: BLE001
        print(f"  [Synthesis] LLM 호출 실패: {exc} — 카테고리 단순 결합으로 폴백")
        resp = None

    if resp:
        raw = (resp.text or "").strip()
        parsed = _parse_json_response(raw, "Synthesis")
        text = (parsed.get("summary_insight") or "").strip()
        if text:
            return text

    # 폴백 — 카테고리 insight 단순 결합 (LLM 실패 시)
    parts = [
        market_r.get("summary_insight", "").strip(),
        news_r.get("summary_insight", "").strip(),
        disclosure_r.get("summary_insight", "").strip(),
    ]
    parts = [p for p in parts if p]
    return " ".join(parts)[:120] if parts else "오늘 데이터 미수집으로 어제 수준 유지함."


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

    # 데이터 가용성 진단
    carried = []
    if market_r.get("score_delta", {}).get("status", "").startswith("Data Unavailable"):
        carried.append("market")
    if news_r.get("score_delta", {}).get("status", "").startswith("Data Unavailable"):
        carried.append("news")
    if disclosure_r.get("score_delta", {}).get("status", "").startswith("Data Unavailable"):
        carried.append("disclosure")

    return {
        "analysis_date": date.today().isoformat(),
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
    print("리스크 종합점수 산출 파이프라인 (V2.1) [TEST MODE]")
    print("=" * 60)

    # 0) 이전 결과 로드 — test 파일 우선, 없으면 production 파일 fallback
    #    (첫 실행 시 production 의 어제 점수를 그대로 previous_result 로 사용 →
    #     production 과 같은 출발선에서 로직 비교 가능)
    prev_all = {}
    _prod_file = DATA / "risk_scores_history.json"
    _src = HISTORY_FILE if HISTORY_FILE.exists() else _prod_file
    if _src.exists():
        try:
            prev_all = json.loads(_src.read_text(encoding="utf-8"))
            print(f"  · prev 로드: {_src.name}")
        except json.JSONDecodeError:
            print(f"[WARN] {_src.name} 파싱 실패 — 빈 prev 로 시작")

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
