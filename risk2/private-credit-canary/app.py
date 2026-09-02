"""사모신용 카나리아 모니터링 — Streamlit 대시보드.

Phase 6 (UI 골격) + Phase 2.1 수정사항 반영. 데이터는 data/ 폴더의 CSV 를 읽으며,
점수/총평 등 일부 영역은 추후 Phase 7~8 에서 채워진다.
"""

from __future__ import annotations

import contextlib
import io
import sys
import warnings
from datetime import date, timedelta
from pathlib import Path

# Plotly/Streamlit 의 deprecation 경고가 UI 박스로 노출되는 것 차단
# (배포 환경에서 사용자 화면에 노란색 경고 박스가 나오지 않도록)
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*keyword arguments have been deprecated.*")
warnings.filterwarnings("ignore", message=".*config.*Plotly.*")

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

# ─── Plotly deprecation 경고 차단 (Python 레벨, DOM 추가 없음) ───
# Streamlit 1.50 이 내부 Plotly 호출 시 "keyword arguments have been deprecated..."
# 경고를 st.warning(...) 으로 차트 박스 안에 띄우는 것을 monkey-patch 로 silently drop.
# 사용자 의도적 st.warning ("가격 데이터 없음" 등) 은 그대로 작동.
_PCC_BLOCKED_WARNING_PATTERNS = (
    "keyword arguments have been deprecated",
    "use config instead to specify plotly configuration",
)


def _pcc_filter_streamlit_msg(orig_fn):
    def _wrapped(body=None, *args, **kwargs):
        msg = str(body) if body is not None else ""
        low = msg.lower()
        if any(p in low for p in _PCC_BLOCKED_WARNING_PATTERNS):
            return None
        return orig_fn(body, *args, **kwargs)
    return _wrapped


# st.warning + st.info + st.error 모두 패치 (어디로 들어올지 몰라 방어적으로)
for _fn_name in ("warning", "info", "error"):
    _orig = getattr(st, _fn_name, None)
    if _orig is not None:
        setattr(st, _fn_name, _pcc_filter_streamlit_msg(_orig))


# ─── 서버 로그(stdout) 스팸 차단 — Streamlit logger 가 deprecation 을 매 차트마다 찍음 ───
# st.warning monkey-patch 는 UI 만 막음. logger 출력은 별개라 logging.Filter 로 따로 차단.
import logging as _logging


class _PccLogFilter(_logging.Filter):
    def filter(self, record):  # noqa: A003
        try:
            msg = record.getMessage().lower()
        except Exception:  # noqa: BLE001
            return True
        return not any(p in msg for p in _PCC_BLOCKED_WARNING_PATTERNS)


_pcc_log_filter = _PccLogFilter()
# streamlit logger 본체 + 그 핸들러 + root 핸들러 모두에 부착 (전파 경로 어디든 차단)
_st_logger = _logging.getLogger("streamlit")
_st_logger.addFilter(_pcc_log_filter)
for _h in list(_st_logger.handlers) + list(_logging.getLogger().handlers):
    _h.addFilter(_pcc_log_filter)


# =============================================================================
# 전역 설정
# =============================================================================

DATA_DIR = Path(__file__).resolve().parent / "data"

# tools/ 의 sync_data 모듈을 import 가능하게 path 추가
_TOOLS_DIR = Path(__file__).resolve().parent / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


@st.cache_data(ttl=600, show_spinner=False)
def _auto_sync_downloads() -> int:
    """data/ 폴더 정리 자동화 (10분 캐시).

    매 새로고침마다 돌리면 부담되므로 ttl=600s 캐시. 그 이내엔 캐시 결과 재사용.
    sync_data.main() 의 stdout 은 콘솔로 가지 않게 캡처.
    오류가 나도 앱은 계속 동작 (try/except).
    """
    try:
        from sync_data import main as sync_main  # type: ignore[import-not-found]
        with contextlib.redirect_stdout(io.StringIO()):
            return sync_main()
    except SystemExit:
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[auto_sync] 실패: {exc}")
        return 0


# 앱 시작 시 한 번 (10분 안엔 캐시) — 다운로드 폴더 자동 정리
_auto_sync_downloads()


def _load_risk_score() -> dict:
    """data/risk_scores_history.json 에서 종합 점수 로드. 없으면 빈 dict."""
    import json as _json
    path = DATA_DIR / "risk_scores_history.json"
    if not path.exists():
        return {}
    try:
        return _json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"[load_risk] 실패: {exc}")
        return {}


# NOTE: 점수 산출은 start_dashboard.bat 의 [4/5] 단계 (tools/score_risk.py) 에서만 실행됨.
# streamlit 단독 실행 시 자동 LLM 재호출하지 않음 — 이전 산출 결과를 그대로 표시.
# (자동 재호출이 매번 JSON 을 덮어써서 직전 점수 / 요약이 손실되는 문제 방지)

COLOR_MAP = {
    # BDC (5개) — 옅은 파스텔 톤 (기존 유지).
    "OBDC": "#BBDAF6",     # Blue Owl BDC      → 옅은 블루
    "OTF":  "#B7EAD9",     # Blue Owl Tech BDC → 옅은 그린
    "BXSL": "#DCCEFC",     # Blackstone BDC    → 옅은 보라
    "ARCC": "#FCC5CF",     # Ares BDC          → 옅은 핑크
    "FSK":  "#FCE2B6",     # FS KKR BDC        → 옅은 오렌지

    # 운용사 (5개) — BDC 와 동일한 옅은 톤.
    # BDC ↔ 운용사 mutex 로 동시 표시 안 됨 → 같은 색 충돌 없음.
    # 모/자 매칭: OWL→OBDC, BX→BXSL, ARES→ARCC, KKR→FSK. APO 는 BDC 매핑 없어 OTF 의 그린 차용.
    "OWL":  "#BBDAF6",     # Blue Owl   — 옅은 블루   (OBDC 와 동일)
    "BX":   "#DCCEFC",     # Blackstone — 옅은 보라   (BXSL 와 동일)
    "ARES": "#FCC5CF",     # Ares       — 옅은 핑크   (ARCC 와 동일)
    "APO":  "#B7EAD9",     # Apollo     — 옅은 그린   (OTF 색 차용 — APO 는 BDC 매핑 없음)
    "KKR":  "#FCE2B6",     # KKR        — 옅은 오렌지 (FSK 와 동일)

    # 벤치마크 — 중간 채도 톤 (이전 다크 톤 살짝 밝게 → 3색 구분 강화).
    # 3색 모두 hue 가 확실히 다름 (blue/brown/green) + 채도 적절히 높임.
    "BIZD":  "#3A6EA5",   # 미디엄 블루 — BDC ETF
    "^GSPC": "#8B6240",   # 미디엄 웜 브라운 — S&P 500
    "HYG":   "#2D6A4F",   # 미디엄 포레스트 그린 — 하이일드 ETF
    # FRED 지표
    "BAMLH0A0HYM2": "#FFD54F",   # HY 스프레드 — 옅은 노랑
    "DGS1": "#5B92FF",           # 미국 1Y 금리 — 밝은 파랑
    "DGS3": "#003BB0",           # 미국 3Y 금리 — 진한 파랑
    "DGS5": "#002060",           # 미국 5Y 금리 — 매우 진한 파랑
}

FORM_KR_NAMES = {
    # 정기 / 수시
    "10-K":     "연간 정기공시",
    "10-K/A":   "연간 정기공시 정정",
    "10-Q":     "분기 정기공시",
    "10-Q/A":   "분기 정기공시 정정",
    "20-F":     "외국기업 연간보고서",
    "20-F/A":   "외국기업 연간보고서 정정",
    "6-K":      "외국기업 수시공시",
    "6-K/A":    "외국기업 수시공시 정정",
    "8-K":      "수시공시",
    "8-K/A":    "수시공시 정정",
    # 증권 등록
    "S-1":      "증권 등록신고서",
    "S-1/A":    "증권 등록신고서 정정",
    "S-3":      "간이 증권 등록",
    "S-3/A":    "간이 증권 등록 정정",
    "S-4":      "합병 관련 증권 등록",
    "S-4/A":    "합병 관련 증권 등록 정정",
    "F-1":      "외국기업 증권 등록",
    "F-1/A":    "외국기업 증권 등록 정정",
    "F-3":      "외국기업 간이 등록",
    "F-3/A":    "외국기업 간이 등록 정정",
    # 투자설명서 / 자유형
    "424B1":    "투자설명서",
    "424B2":    "투자설명서 보충",
    "424B3":    "투자설명서 정정",
    "424B4":    "투자설명서",
    "424B5":    "최종 투자설명서",
    "424B7":    "재판매 투자설명서",
    "FWP":      "자유형 투자설명서",
    "425":      "합병 관련 공시",
    # 위임장 / 주주총회
    "DEF 14A":  "주주총회 소집공시",
    "DEFA14A":  "추가 주주총회 공시",
    "DEFR14A":  "정정 주주총회 공시",
    "PRE 14A":  "예비 주주총회 공시",
    "PREM14A":  "합병 관련 예비 위임장",
    "DEFM14A":  "확정 합병 위임장",
    "DEF 14C":  "주주 정보 공시",
    "PRE 14C":  "예비 주주 정보 공시",
    "PREC14A":  "예비 contested 위임장",
    "DEFC14A":  "확정 contested 위임장",
    "DFAN14A":  "비경영진 추가 권유 자료",
    "DEFN14A":  "비경영진 위임장",
    # 대량보유 / 내부자 — SC / SCHEDULE 두 prefix 모두 EDGAR 에서 발생 가능
    "SC 13D":         "대량보유 - 경영참여 목적",
    "SC 13D/A":       "대량보유 - 경영참여 목적 (정정)",
    "SC 13G":         "대량보유 - 일반투자 목적",
    "SC 13G/A":       "대량보유 - 일반투자 목적 (정정)",
    "SCHEDULE 13D":   "대량보유 - 경영참여 목적",
    "SCHEDULE 13D/A": "대량보유 - 경영참여 목적 (정정)",
    "SCHEDULE 13G":   "대량보유 - 일반투자 목적",
    "SCHEDULE 13G/A": "대량보유 - 일반투자 목적 (정정)",
    "SC TO-T":  "공개매수신고",
    "SC TO-I":  "자기주식 공개매수신고",
    "SC TO-T/A":"공개매수신고 정정",
    "SC TO-I/A":"자기주식 공개매수신고 정정",
    "SC 14D9":  "공개매수 의견서",
    "SC 14D9/A":"공개매수 의견서 정정",
    "3":        "내부자 최초 지분 신고",
    "3/A":      "내부자 최초 지분 정정",
    "4":        "내부자 지분 변동 공시",
    "4/A":      "내부자 지분 변동 정정",
    "5":        "내부자 연간 지분 보고",
    "5/A":      "내부자 연간 지분 정정",
    # 직원 복지 / 144 / 지연
    "11-K":     "직원 복지계획 보고서",
    "144":      "제한주식 매도 예정 공시",
    "144/A":    "제한주식 매도 정정",
    "NT 10-K":  "연간보고서 제출 지연",
    "NT 10-Q":  "분기보고서 제출 지연",
    "NT 20-F":  "외국기업 연간보고 지연",
    # 특수 / 서신
    "SD":       "특수 공시 (분쟁광물 등)",
    "CORRESP":  "SEC 서신",
    "UPLOAD":   "기타 제출 문서",
    # 펀드
    "N-CSR":    "펀드 연간보고서",
    "N-CSR/A":  "펀드 연간보고 정정",
    "N-CSRS":   "펀드 반기보고서",
    "N-CSRS/A": "펀드 반기보고 정정",
    "N-PORT":   "펀드 포트폴리오 공시",
    "N-PORT/A": "펀드 포트폴리오 정정",
    "N-CEN":    "펀드 정보 보고",
    "N-CEN/A":  "펀드 정보 보고 정정",
    "N-PX":     "의결권 행사 기록",
    "N-23C-2":  "환매 의사 공시",
    "ARS":      "주주용 연차보고서",
    "497":      "펀드 투자설명서",
    "497K":     "요약 투자설명서",
    "497AD":    "투자권유서",
    "497J":     "펀드 보고 인증",
    "485BPOS":  "투자설명서 사후 정정",
    "485APOS":  "투자설명서 사전 정정",
    "486BPOS":  "486(b) 효력발생 후 정정",
    "486APOS":  "486(a) 효력발생 전 정정",
    # 등록 사후
    "POS AM":   "등록신고서 사후 정정",
    "POS EX":   "등록 서류 정정",
    "POS 8C":   "투자회사 사후 정정",
    "EFFECT":   "등록 효력 발생",
    "RW":       "등록 철회 요청",
    "RW WD":    "철회 요청 철회",
    "40-APP":   "투자회사 신청서",
    "40-APP/A": "투자회사 신청서 정정",
    "40-OIP":   "투자회사 면제 신청",
    "40-17G":   "연간 보증보험 공시",
    "40-33":    "주주 대위소송 보고",
    "40-33/A":  "주주 대위소송 보고 (정정)",
    "N-2":      "투자회사 등록",
    "N-2/A":    "투자회사 등록 정정",
    # 직원 복지 / 공개매수 통신
    "S-8":      "직원 복지 등록",
    "S-8 POS":  "직원 복지 등록 사후 정정",
    "SC TO-C":  "공개매수 관련 통신",
    "SC 13E3":  "비공개 전환 거래 공시",
    "PX14A6G":  "비요청 위임 권유 통지",
}

TICKER_KR_NAMES = {
    # 상장형 BDC
    "OBDC":  "블루아울",
    "OTF":   "블루아울 Tech",
    "BXSL":  "블랙스톤",
    "ARCC":  "아레스",
    "FSK":   "FS KKR",
    # 운용사
    "OWL":   "블루아울",
    "BX":    "블랙스톤",
    "ARES":  "아레스",
    "KKR":   "KKR",
    "APO":   "아폴로",
    # 벤치마크
    "BIZD":  "BDC ETF",
    "^GSPC": "S&P 500",
    "HYG":   "하이일드 ETF",
    # FRED 지표
    "BAMLH0A0HYM2": "HY 스프레드",
    "DGS1":         "미국 1Y 금리",
    "DGS3":         "미국 3Y 금리",
    "DGS5":         "미국 5Y 금리",
}

CATEGORY_TICKERS: dict[str, list[str]] = {
    "BDC": ["OBDC", "OTF", "BXSL", "ARCC", "FSK"],
    "운용사": ["OWL", "BX", "ARES", "KKR", "APO"],
    "벤치마크": ["BIZD", "^GSPC", "HYG"],
}

PERIOD_DAYS = {
    "전일대비": 1,
    "1주": 7,
    "1개월": 31,
    "3개월": 92,
    "6개월": 183,
    "1년": 365,
}
PERIOD_OPTIONS = ["3개월", "1년", "연초이후"]

# 기간 토글 표시 언어 — "EN" (1D/1W/1M...) 또는 "KR" (전일대비/1주/1개월...)
# 국문 원복 원하면 "KR" 로 변경
PERIOD_LANG = "EN"

# 기간 ID(Korean) → 영문 약어 매핑
PERIOD_LABEL_EN = {
    "전일대비": "1D",
    "1주": "1W",
    "1개월": "1M",
    "3개월": "3M",
    "6개월": "6M",
    "1년": "1Y",
    "연초이후": "YTD",
}


def _period_label(opt: str) -> str:
    """st.pills format_func — 내부 ID(국문) 유지하되 표시 언어 전환 가능."""
    if PERIOD_LANG == "EN":
        return PERIOD_LABEL_EN.get(opt, opt)
    return opt

# 대시보드 표시 제외 SEC form — 코랩 SKIP_FORMS 와 동일한 목록.
# 기존 history.csv 에 누적된 옛 데이터도 화면에서는 안 보이도록 필터.
SEC_SKIP_FORMS = {
    "10-K", "10-Q", "10-K/A", "10-Q/A",  # 정기공시 (별도 처리)
    "S-8", "S-8 POS",                    # 직원 보상
    "RW", "RW WD",                       # 등록 철회
    "FWP",                               # 자유 작성 투자설명서
    "ARS",                               # 주주용 연차보고서 PDF
    "N-CSR", "N-CSRS",                   # 펀드 연·반기 보고서
    "486APOS", "486BPOS",                # 486 효력발생 전·후 정정 (장문 등록서류)
    "N-CEN",                             # 펀드 연차 통계
    "N-PX",                              # 의결권 행사 기록
    "DEF 14A", "PRE 14A",
    "DEFA14A", "DEFR14A",                # 정기 주주총회 위임장 (장문, 형식적)
}


def get_form_label(form: str) -> str:
    """SEC form 코드를 한글명 병기 형태로 반환. 예: '8-K (수시공시)'. 매핑 없으면 원본."""
    if not isinstance(form, str) or not form.strip():
        return ""
    code = form.strip()
    kr = FORM_KR_NAMES.get(code)
    return f"{code} ({kr})" if kr else code


def truncate_text(text: str, limit: int = 140) -> str:
    """공백 포함 limit 자 이내로 절단. 절단 시 마지막 공백 경계에서 자르고 ellipsis."""
    if not isinstance(text, str):
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    # 너무 앞에서 자르면 정보 손실이 크니 70% 이후의 공백만 사용
    if space > limit * 0.7:
        cut = cut[:space]
    return cut.rstrip() + "…"


def get_ticker_label(ticker: str) -> str:
    """티커를 '한글명(영문)' 형태로 반환. 매핑 없으면 영문만."""
    if not isinstance(ticker, str) or not ticker:
        return ticker
    kr = TICKER_KR_NAMES.get(ticker)
    return f"{kr}({ticker})" if kr else ticker


# =============================================================================
# 페이지 설정 및 스타일
# =============================================================================

# Plotly 차트 공통 폰트 — Manrope (영문/숫자, 기하학적) 우선, SUIT (한글) 폴백
# update_layout 시 font=PLOTLY_FONT 로 적용
PLOTLY_FONT = dict(
    family="'Manrope', 'SUIT Variable', -apple-system, BlinkMacSystemFont, sans-serif",
    size=17,
    color="#374151",
)

st.set_page_config(
    page_title="사모신용 카나리아 모니터링",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
        /* ★ @import 는 stylesheet 의 가장 앞에 와야 브라우저가 인정함 (CSS spec).
              어떤 CSS 룰이라도 @import 보다 위에 있으면 모든 @import 가 silently 무시됨. */
        /* SUIT (한글 본문 — 모던 variable font, sun-typeface) */
        @import url('https://cdn.jsdelivr.net/gh/sun-typeface/SUIT@2/fonts/variable/woff2/SUIT-Variable.css');
        /* Manrope (영문/숫자 — 기하학적, contemporary) — Google Fonts */
        @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap');
        /* Material Symbols (픽토그램) — variable font 로드 (weight 100~700 가변) */
        @import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200&display=swap');

        /* 모든 rem 기반 폰트 +20% 확대 (≈ 2단계) */
        html { font-size: 19.2px; }
        .material-symbols-rounded {
            font-family: 'Material Symbols Rounded';
            font-weight: normal;
            font-style: normal;
            line-height: 1;
            letter-spacing: normal;
            text-transform: none;
            display: inline-block;
            white-space: nowrap;
            word-wrap: normal;
            direction: ltr;
            font-feature-settings: 'liga';
            -webkit-font-smoothing: antialiased;
        }
        /* 제목 옆 픽토그램 — 텍스트와 baseline 정렬, 색상 약간 옅게 */
        .pcc-title-icon {
            font-size: 1.1em !important;
            vertical-align: -3px;
            color: #475569;
            margin-right: 2px;
        }
        /* 메인 헤더 픽토그램 — 두껍게 (weight 700) */
        .pcc-main-icon {
            font-size: 1.3em !important;
            color: #0f172a;
            font-variation-settings: 'wght' 700;
        }
        /* 제목 div 내부에서 픽토그램과 텍스트 수평 정렬 (flex center) */
        .pcc-header .pcc-title {
            display: flex !important;
            align-items: center;
            gap: 8px;
        }

        /* 전역 폰트 — Manrope (영문/숫자) 우선, SUIT (한글) 폴백.
           Manrope 가 기하학적 sans 라 영문·숫자 부분이 distinctive 하게 바뀌고,
           한글은 SUIT 가 받아 처리함 (Manrope 에 한글 글리프 없으므로 자동 폴백). */
        html, body, [class*="css"], [class*="st-"] {
            font-family: 'Manrope', 'SUIT Variable', -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
            font-feature-settings: "tnum", "ss01";
            font-variant-numeric: tabular-nums;
            letter-spacing: -0.005em;
        }
        /* 큰 숫자 (gauge 점수, KPI 등) — Manrope 강제로 더 sharp tabular */
        .pcc-score,
        .pcc-news-time {
            font-family: 'Manrope', sans-serif !important;
            font-variant-numeric: tabular-nums;
            letter-spacing: -0.01em;
            font-weight: 700;
        }
        /* Last Update 라벨 — 같은 Manrope/tabular 톤이지만 굵기는 normal */
        .pcc-update {
            font-family: 'Manrope', sans-serif !important;
            font-variant-numeric: tabular-nums;
            letter-spacing: -0.01em;
            font-weight: 400;
        }
        /* 한글 헤딩 — SUIT 강제 (Manrope 가 한글 못 받아도 명시적으로 폴백 보장) */
        h1, h2, h3, h4, h5, h6 {
            font-family: 'SUIT Variable', 'Manrope', sans-serif !important;
            letter-spacing: -0.015em;
        }

        /* 상단 여백 (3rem → 3.5rem) — 헤더가 약간 아래에서 시작 */
        .block-container {
            padding-top: 3.5rem;
            padding-bottom: 2rem;
            padding-left: 1.5rem !important;
            padding-right: 1.5rem !important;
            max-width: 100% !important;
        }
        /* Streamlit "Source file changed" 토스트 숨기기 (Material Symbols 미렌더 시 "info" 글자 노출 회피) */
        [data-testid="stStatusWidget"] {
            display: none !important;
        }
        /* 좌·우 컬럼 간격 좁혀 박스가 화면 중앙으로 모이도록 */
        [data-testid="stHorizontalBlock"] {
            gap: 0.75rem !important;
        }
        /* Plotly modebar (홈/줌 아이콘) — 박스 맨 상단 우측에 항상 표시 (top-right) */
        .js-plotly-plot .modebar {
            opacity: 1 !important;
        }
        /* 뉴스/공시 텍스트 자동 줄바꿈 — 한글 단어가 어절 중간에서 잘리지 않게 keep-all.
           긴 영문/URL 은 break-word 로 폴백. */
        .pcc-headline, .pcc-news-body .pcc-desc, .pcc-sec-item .pcc-desc,
        .pcc-news-title, .pcc-news-summary {
            word-break: keep-all;
            overflow-wrap: break-word;
            white-space: normal;
        }
        .pcc-header {
            display: flex; align-items: center; justify-content: space-between;
            gap: 16px; padding: 0 0 2px 0;
        }
        /* divider 의 위·아래 여백 압축 */
        [data-testid="stMainBlockContainer"] hr,
        [data-testid="stHorizontalRule"] {
            margin: 4px 0 !important;
        }
        .pcc-header .pcc-title {
            font-size: 1.6rem; font-weight: 700; color: #0f172a;
            white-space: nowrap; flex: 0 0 auto;
        }
        .pcc-header .pcc-update {
            /* 다른 폰트는 +20% 확대됐지만 last update 만은 기존 픽셀 크기 유지 (18.4px = 1.15rem × 16) */
            color: #475569; font-size: 18.4px; white-space: nowrap; flex: 0 0 auto;
            transform: translateY(6px);   /* 살짝 아래로 */
        }
        .pcc-card {
            background: #f8f9fb; border: 1px solid #e6e8ec; border-radius: 12px;
            padding: 18px 22px; height: 100%;
        }
        .pcc-card h4 { margin: 0 0 8px 0; color: #475569; font-weight: 600; font-size: 0.92rem; }
        .pcc-score { font-size: 3rem; font-weight: 700; color: #0f172a; line-height: 1.1; }
        .pcc-muted { color: #64748b; font-size: 1.05rem; }
        .pcc-summary { font-size: 1.22rem; color: #1e293b; line-height: 1.5; }

        /* SEC 공시 카드 (기존 유지) */
        .pcc-news-row { padding: 10px 4px; border-bottom: 1px solid #eef0f3; }
        .pcc-news-row:last-child { border-bottom: none; }
        .pcc-news-meta { color: #64748b; font-size: 1.0rem; }
        .pcc-news-title { font-weight: 600; color: #0f172a; margin: 2px 0; }
        .pcc-news-summary { color: #334155; font-size: 1.1rem; }
        .pcc-news-flag { color: #94a3b8; font-size: 0.95rem; margin-left: 6px; }

        /* 뉴스 카드 — 시계열 형태 (날짜 그룹 + HH:MM + 제목 + 요약 + 태그)
           preview 디자인 적용: 날짜·BDC명 indigo, 시간만 gray (반복 정보라 차분) */
        .pcc-date-header {
            font-size: 1.05rem; color: #4338ca; background: #eef2ff;
            padding: 6px 12px; border-radius: 6px; margin: 14px 0 4px 0;
            display: inline-block; font-weight: 700;
        }
        .pcc-news-item {
            display: grid;
            grid-template-columns: 64px 1fr auto;
            gap: 14px;
            padding: 12px 4px;
            border-bottom: 1px solid #eef0f3;
            align-items: start;
        }
        .pcc-news-item:last-child { border-bottom: none; }
        .pcc-news-time {
            background: #f3f4f6; border-radius: 4px;
            padding: 4px 0; font-size: 0.98rem; color: #6b7280; font-weight: 700;
            text-align: center; height: fit-content;
        }
        /* 헤드라인 — 뉴스 제목 / SEC form 라벨 모두 볼드. SEC 만 사이즈 살짝 작게 (아래 override) */
        .pcc-headline { font-weight: 600; color: #0f172a; font-size: 1.13rem; line-height: 1.45; }
        .pcc-sec-item .pcc-headline { font-size: 0.95rem; }
        .pcc-news-body .pcc-desc { color: #475569; font-size: 1.03rem; margin-top: 6px; line-height: 1.5; }
        .pcc-tag {
            display: inline-block;
            background: #f1f5f9; color: #64748b;
            font-size: 0.92rem; padding: 3px 10px; border-radius: 4px;
            margin: 8px 4px 0 0;
        }
        .pcc-news-link { font-size: 0.98rem; align-self: start; padding-top: 2px; white-space: nowrap; }
        .pcc-news-link a { color: #00AEFF; text-decoration: none; }
        .pcc-news-link a:hover { text-decoration: underline; }

        /* Risk Level 제목 — 다른 ##### h5 들과 동일 사이즈로 명시 + 가운데 정렬 (컨테이너·자식 모두) */
        .st-key-risk_level_title,
        .st-key-risk_level_title > div,
        .st-key-risk_level_title [data-testid="stVerticalBlock"],
        .st-key-risk_level_title [data-testid="stMarkdown"] {
            text-align: center !important;
        }
        .st-key-risk_level_title h5 {
            text-align: center !important;
            margin: 0 0 6px 0;
            font-weight: 600;
            display: block;
            width: 100%;
            font-size: 1.2rem;
            transform: translateX(11px);     /* 우측 11px 이동 (= 좌측 공백 효과) */
        }

        /* SEC 공시 — 1행: BDC명(박스) + form (headline)
                       2행: 요약 (좌측 정렬, BDC 박스부터 풀 폭)
           padding 좌우 0 — 날짜 헤더·BDC명·요약 모두 같은 left edge 정렬 */
        .pcc-sec-item {
            display: grid;
            grid-template-columns: max-content 1fr;
            column-gap: 14px;
            row-gap: 6px;
            padding: 12px 0;
            border-bottom: 1px solid #eef0f3;
            align-items: center;
        }
        .pcc-sec-item:last-child { border-bottom: none; }
        .pcc-sec-name {
            background: #f3f4f6;
            border-radius: 4px;
            padding: 4px 12px;
            font-size: 0.98rem;
            color: #6b7280;
            font-weight: 700;
            height: fit-content;
            white-space: nowrap;
        }
        /* 요약은 두 컬럼을 모두 차지. 좌측 4px 들여쓰기로 BDC명 박스와 시각적 구분 */
        .pcc-sec-item .pcc-desc {
            grid-column: 1 / -1;
            text-align: left;
            padding-left: 4px;
        }
        /* 정기공시 — KPI 한 줄(NAV · PIK · 연체율) + 직전 분기 대비 ▲/▼ */
        .pcc-sec-periodic .pcc-headline { color: #4338ca; }
        .pcc-kpi-desc { color: #334155 !important; }
        .pcc-kpi-item { display: inline-block; }
        .pcc-kpi-item b {
            color: #0f172a;
            font-weight: 700;
            margin-left: 4px;
        }
        .pcc-kpi-sep {
            color: #cbd5e1;
            margin: 0 8px;
        }
        .pcc-kpi-delta {
            color: #64748b;
            font-size: 0.85rem;
            margin-left: 2px;
            font-weight: 500;
        }

        /* 카테고리 pills — 좌측 "모니터링 대상:" 라벨 inline 배치 (한 줄 강제)
           padding-left: 10px 로 박스 좌측과 첫 글자 사이 공백을 적용기간 우측 padding 과 대칭 */
        .st-key-returns_category_box {
            display: flex !important;
            flex-direction: row !important;
            align-items: center !important;
            flex-wrap: nowrap !important;
            gap: 10px;
            padding-left: 10px;
        }
        .st-key-returns_category_box::before {
            content: "모니터링 대상";
            font-weight: 600;
            color: #475569;
            font-size: 0.88rem;
            white-space: nowrap;
            flex-shrink: 0;
            order: -1;
        }
        .st-key-returns_category_box > div {
            width: auto !important;
            flex: 0 1 auto !important;
            min-width: 0;
        }

        /* 기간 pills — 좌측 "적용기간:" 라벨 inline + 전체 우정렬 */
        .st-key-returns_period_box {
            display: flex !important;
            flex-direction: row !important;
            justify-content: flex-end !important;
            align-items: center !important;
            flex-wrap: wrap;
            gap: 10px;
            text-align: right;
        }
        .st-key-returns_period_box::before {
            content: "적용기간";
            font-weight: 600;
            color: #475569;
            font-size: 0.88rem;
            white-space: nowrap;
            order: -1;
        }
        .st-key-returns_period_box > div {
            width: auto !important;
            flex: 0 1 auto !important;
        }
        .st-key-returns_period_box [data-testid="stPills"] > div,
        .st-key-returns_period_box [data-testid="stButtonGroup"],
        .st-key-returns_period_box [role="radiogroup"],
        .st-key-returns_period_box [role="group"] {
            display: flex !important;
            justify-content: flex-end !important;
            flex-wrap: wrap !important;
            padding-right: 10px;
        }

        /* ★ pills 토글의 선택된 상태 색상 — AI 분석 뱃지와 동일 (indigo-50 bg + indigo-700 text)
           Streamlit pills 의 selected button 은 다양한 attribute 사용 — 모두 커버 */
        .st-key-news_region_box button[kind="primary"],
        .st-key-returns_category_box button[kind="primary"],
        .st-key-returns_period_box button[kind="primary"],
        .st-key-news_region_box button[aria-pressed="true"],
        .st-key-returns_category_box button[aria-pressed="true"],
        .st-key-returns_period_box button[aria-pressed="true"],
        .st-key-news_region_box button[aria-checked="true"],
        .st-key-returns_category_box button[aria-checked="true"],
        .st-key-returns_period_box button[aria-checked="true"],
        .st-key-news_region_box button[data-baseweb="button"][aria-pressed="true"],
        .st-key-returns_category_box button[data-baseweb="button"][aria-pressed="true"],
        .st-key-returns_period_box button[data-baseweb="button"][aria-pressed="true"],
        .st-key-news_region_box [data-testid="stBaseButton-pillsActive"],
        .st-key-returns_category_box [data-testid="stBaseButton-pillsActive"],
        .st-key-returns_period_box [data-testid="stBaseButton-pillsActive"],
        .st-key-news_region_box button.st-emotion-cache-pillsActive,
        .st-key-returns_category_box button.st-emotion-cache-pillsActive,
        .st-key-returns_period_box button.st-emotion-cache-pillsActive {
            background-color: #eef2ff !important;
            color: #4338ca !important;
            border-color: #c7d2fe !important;
        }
        /* selected pill 안의 텍스트 (p / span) 색상도 강제 */
        .st-key-news_region_box button[aria-pressed="true"] *,
        .st-key-returns_category_box button[aria-pressed="true"] *,
        .st-key-returns_period_box button[aria-pressed="true"] *,
        .st-key-news_region_box button[aria-checked="true"] *,
        .st-key-returns_category_box button[aria-checked="true"] *,
        .st-key-returns_period_box button[aria-checked="true"] *,
        .st-key-news_region_box button[kind="primary"] *,
        .st-key-returns_category_box button[kind="primary"] *,
        .st-key-returns_period_box button[kind="primary"] * {
            color: #4338ca !important;
        }

        /* ★ 4개 박스 (HY / BDC / 뉴스 / SEC) 의 제목 행 — 동일 40px 고정 height + flex center.
           각 박스의 시작 위치를 정확히 정렬. 뉴스는 추가로 region pills 도 같은 row 에 inline. */
        .st-key-hy_title_row,
        .st-key-returns_title_row,
        .st-key-news_title_row,
        .st-key-sec_title_row {
            display: flex !important;
            flex-direction: row !important;
            align-items: center !important;
            gap: 8px !important;
            flex-wrap: nowrap !important;
            height: 40px !important;
        }
        /* 중간 wrapper(stVerticalBlock 등) 투명화 → grandchild 가 직접 flex 자식이 됨 */
        .st-key-hy_title_row > div,
        .st-key-returns_title_row > div,
        .st-key-news_title_row > div,
        .st-key-sec_title_row > div {
            display: contents !important;
        }
        .st-key-hy_title_row h5,
        .st-key-returns_title_row h5,
        .st-key-news_title_row h5,
        .st-key-sec_title_row h5 {
            margin: 0 !important;
            white-space: nowrap;
        }
        /* SEC title row 만 — 내부 markdown wrapper 들을 100% width 로 펼침.
           render_sec_box() 가 markdown 안에 display:flex div 를 두어
           제목(좌) + "미국 현지시간 기준" 주석(우정렬) 을 한 줄에 배치하기 위함. */
        .st-key-sec_title_row [data-testid="stElementContainer"],
        .st-key-sec_title_row [data-testid="stMarkdown"],
        .st-key-sec_title_row [data-testid="stMarkdownContainer"] {
            width: 100% !important;
        }
        /* HY 와 News 제목만 살짝 위로 (BDC/SEC 와 베이스라인은 유지하지 않고 두 개만 미세 조정) */
        .st-key-hy_title_row,
        .st-key-news_title_row {
            margin-top: -8px !important;
        }
        /* 중간 wrapper (stVerticalBlock 등) 를 투명화 → grandchild 들이 직접 flex 자식이 됨 */
        .st-key-news_title_row > div,
        .st-key-news_title_row > [data-testid="stVerticalBlock"] {
            display: contents !important;
        }
        /* pills 컨테이너 — flex center 정렬. transform 으로 시각적 위치만 살짝 아래로 (레이아웃 영향 X) */
        .st-key-news_region_box {
            flex-shrink: 0;
            transform: translateY(4px);
        }
        /* pills 내부 wrapper */
        .st-key-news_region_box [data-testid="stPills"] {
            margin: 0 !important;
            width: fit-content !important;
        }
        .st-key-news_region_box [data-testid="stPills"] > div,
        .st-key-news_region_box [data-testid="stButtonGroup"],
        .st-key-news_region_box [role="radiogroup"],
        .st-key-news_region_box [role="group"] {
            display: flex !important;
            flex-wrap: nowrap !important;
            padding: 0 !important;
            margin: 0 !important;
        }

        /* ─── "더보기" 모달 버튼 — AI 분석 뱃지 톤 (indigo pill, 박스 X축 가운데) ─── */
        .st-key-sec_more_wrap,
        .st-key-news_more_wrap {
            width: 100% !important;
            margin-top: 14px !important;
            margin-bottom: 4px !important;
        }
        /* 모든 중간 wrapper 도 100% 폭으로 펴서 flex 가운데 정렬이 박스 전체 기준이 되게 함 */
        .st-key-sec_more_wrap > div,
        .st-key-news_more_wrap > div,
        .st-key-sec_more_wrap [data-testid="stVerticalBlock"],
        .st-key-news_more_wrap [data-testid="stVerticalBlock"],
        .st-key-sec_more_wrap [data-testid="stElementContainer"],
        .st-key-news_more_wrap [data-testid="stElementContainer"] {
            width: 100% !important;
        }
        /* stButton wrapper 를 flex row + center 로 만들어 버튼을 X축 가운데에 위치 */
        .st-key-sec_more_wrap [data-testid="stButton"],
        .st-key-news_more_wrap [data-testid="stButton"] {
            display: flex !important;
            flex-direction: row !important;
            justify-content: center !important;
            width: 100% !important;
        }
        .st-key-sec_more_wrap button,
        .st-key-news_more_wrap button {
            background-color: #eef2ff !important;
            color: #4338ca !important;
            border: 1px solid #c7d2fe !important;
            border-radius: 999px !important;
            font-size: 1rem !important;   /* SEC 요약 본문 (.pcc-desc) 과 동일 사이즈 */
            font-weight: 600 !important;
            padding: 5px 16px !important;
            min-height: 0 !important;
            width: auto !important;
            flex: 0 0 auto !important;
            transition: background-color 0.15s ease, border-color 0.15s ease;
        }
        /* 더보기 버튼 안 텍스트 (Streamlit 이 button 내부 p/span 으로 감싸는 경우 포함) */
        .st-key-sec_more_wrap button *,
        .st-key-news_more_wrap button * {
            font-size: 1rem !important;
        }
        .st-key-sec_more_wrap button:hover,
        .st-key-news_more_wrap button:hover,
        .st-key-sec_more_wrap button:focus,
        .st-key-news_more_wrap button:focus,
        .st-key-sec_more_wrap button:active,
        .st-key-news_more_wrap button:active {
            background-color: #e0e7ff !important;
            border-color: #a5b4fc !important;
            color: #3730a3 !important;
            box-shadow: none !important;
        }

        /* ─── grid_charts_events (rows 2-3 wrapper) — PC 에서 행 간격 ─── */
        .st-key-grid_charts_events [data-testid="stHorizontalBlock"]:not(:first-child) {
            margin-top: 0.75rem;
        }

        /* ─── HY/BDC 차트 viewport 별 토글 ─── */
        /* 기본 (데스크톱): 모바일용 차트 숨김 */
        .st-key-hy_chart_mobile,
        .st-key-returns_chart_mobile {
            display: none !important;
        }
        /* ─── Streamlit Settings 다이얼로그 — Theme(Light/Dark) 토글만 숨김 ───
           햄버거 → Settings 진입은 그대로 (Rerun, Clear cache 등 사용 가능),
           Settings 안의 "Choose app theme" 셀렉트박스 영역만 안 보이게 처리.
           Streamlit 버전별 DOM 변경에 대비해 여러 selector 를 fallback 으로 함께 사용. */
        div[role="dialog"] label[for*="theme" i],
        div[role="dialog"] label[for*="theme" i] + div,
        div[role="dialog"] [data-testid="stSelectbox"]:has(label[for*="theme" i]),
        div[role="dialog"] section:has(> label[for*="theme" i]) {
            display: none !important;
        }

        /* ─── 한 줄 요약 박스 / AI 뱃지 — 라이트 모드 고정 ─── */
        .pcc-summary-body {
            background: #eef2ff !important;
            color: #1e293b !important;
            border-left: 4px solid #818cf8 !important;
        }
        .pcc-ai-badge {
            background: #ffffff !important;
            color: #4338ca !important;
            border: 1px solid #c7d2fe !important;
        }

        /* 데스크톱 BDC 박스 — Python 에서 height 제거했으니 CSS 로 데스크톱만 460 강제 */
        @media (min-width: 769px) {
            .st-key-box_returns,
            .st-key-box_returns [data-testid="stVerticalBlockBorderWrapper"] {
                height: 460px !important;
            }
        }

        /* ─── 모바일 (≤768px) — 컬럼 강제 세로 스택 + 글자 크기 / 레이아웃 최적화 ─── */
        @media (max-width: 768px) {
            /* HY/BDC 차트 viewport 토글 — 데스크톱 숨기고 모바일 노출 */
            .st-key-hy_chart_desktop,
            .st-key-returns_chart_desktop {
                display: none !important;
            }
            .st-key-hy_chart_mobile,
            .st-key-returns_chart_mobile {
                display: block !important;
            }
            /* BDC 모바일 차트 컨테이너 — 위로 12px 당김 (legend 는 아래 compensate 로 같은 자리 유지) */
            .st-key-returns_chart_mobile {
                margin-top: -12px !important;
            }
            /* HY 박스 내부 — chart, legend 사이 gap 최소화 + 박스 하단 padding 축소 */
            .st-key-box_hy [data-testid="stVerticalBlock"] {
                gap: 0 !important;
            }
            .st-key-box_hy [data-testid="stVerticalBlockBorderWrapper"],
            .st-key-box_hy {
                padding-bottom: 8px !important;
            }
            /* BDC 박스 — 모바일에서 카테고리(위)/기간(아래) 토글 수직 스택.
               flex 방식이 iPhone Safari 에서 안 먹혀서 grid 1열 로 강제.
               grid + display: block 으로 어떤 flex 도 우회. */
            body div.st-key-box_returns div[data-testid="stHorizontalBlock"],
            body div.st-key-box_returns div[class*="stHorizontalBlock"] {
                display: grid !important;
                grid-template-columns: 1fr !important;
                gap: 8px !important;
                width: 100% !important;
            }
            body div.st-key-box_returns div[data-testid="stColumn"],
            body div.st-key-box_returns div[class*="stColumn"] {
                display: block !important;
                width: 100% !important;
                max-width: 100% !important;
                min-width: 0 !important;
                flex: unset !important;
                padding: 0 !important;
            }
            /* 카테고리 박스 — 라벨 ("모니터링 대상:") + pills 한 줄 유지 (data 토글 줄바꿈 방지) */
            .st-key-returns_category_box {
                flex-wrap: nowrap !important;
            }
            /* 모바일 — 라벨 ("모니터링 대상" / "적용기간") 폰트 = 범례 폰트(0.78rem) 동일 */
            div.st-key-returns_category_box::before,
            div.st-key-returns_period_box::before {
                font-size: 0.78rem !important;
            }
            /* 모바일 — pills 버튼 + 내부 모든 자손 텍스트 폰트 = 범례 폰트(0.78rem) 동일.
               Streamlit pills 의 button 안 p / span / div / 텍스트 노드 모두 강제 */
            div.st-key-box_returns button,
            div.st-key-box_returns button p,
            div.st-key-box_returns button span,
            div.st-key-box_returns button div,
            div.st-key-box_returns [data-testid="stPills"],
            div.st-key-box_returns [data-testid="stPills"] *,
            div.st-key-box_returns [role="radiogroup"] *,
            div.st-key-box_returns [role="group"] * {
                font-size: 0.78rem !important;
                line-height: 1.3 !important;
            }
            /* ★ news region 토글 (전체/국내/해외) — BDC 카테고리 pills 와 동일 크기 (0.78rem) */
            div.st-key-news_region_box button,
            div.st-key-news_region_box button p,
            div.st-key-news_region_box button span,
            div.st-key-news_region_box button div,
            div.st-key-news_region_box [data-testid="stPills"] * {
                font-size: 0.78rem !important;
                line-height: 1.3 !important;
            }
            /* ★ news region 토글 위치 — 모바일 전용: 왼쪽 8px 당기고 아래로 2px */
            .st-key-news_region_box {
                transform: translate(-8px, 2px) !important;
            }
            /* 토글 버튼 — 높이/너비 컴팩트 (padding/line-height/min-width 축소) */
            div.st-key-box_returns [data-testid="stPills"] button {
                padding: 1px 6px !important;
                min-height: 0 !important;
                height: auto !important;
                min-width: 0 !important;
                line-height: 1.2 !important;
            }
            /* 기간 pills (3M/1Y/YTD 3개) — 한 줄에 들어가도록 nowrap + 작은 gap */
            div.st-key-returns_period_box [data-testid="stPills"] [role="radiogroup"],
            div.st-key-returns_period_box [data-testid="stPills"] [role="group"],
            div.st-key-returns_period_box [data-testid="stPills"] > div {
                flex-wrap: nowrap !important;
                gap: 3px !important;
                justify-content: flex-start !important;
            }
            /* 라벨 ↔ pills 사이 간격 — ::before 의사요소 자체에 margin-right 추가 (가장 확실) */
            div.st-key-returns_category_box {
                gap: 0 !important;
            }
            div.st-key-returns_period_box {
                gap: 0 !important;
            }
            div.st-key-returns_category_box::before {
                margin-right: 16px !important;
            }
            div.st-key-returns_period_box::before {
                margin-right: 12px !important;
            }
            /* 기간 박스 — 데스크톱 flex-end 를 모바일에선 좌측 정렬로 + pills 줄바꿈 허용 */
            div.st-key-returns_period_box {
                justify-content: flex-start !important;
                padding-left: 10px !important;
                padding-right: 0 !important;
                text-align: left !important;
                flex-wrap: nowrap !important;
                margin-left: 0 !important;
                margin-right: auto !important;
            }
            /* stPills wrapper 의 좌측 여백은 위 margin-left:12px 룰에서 처리 */
            /* stPills wrapper / stElementContainer 가 grow 해서 pills 를 우측으로 밀지 않도록
               flex: 0 0 auto 로 콘텐츠 크기 fit */
            div.st-key-returns_period_box > [data-testid="stElementContainer"],
            div.st-key-returns_period_box [data-testid="stPills"] {
                flex: 0 0 auto !important;
                width: auto !important;
                margin-left: 0 !important;
                margin-right: auto !important;
            }
            div.st-key-returns_period_box [data-testid="stPills"] > div,
            div.st-key-returns_period_box [data-testid="stButtonGroup"],
            div.st-key-returns_period_box [role="radiogroup"],
            div.st-key-returns_period_box [role="group"] {
                justify-content: flex-start !important;
                flex-wrap: nowrap !important;
                padding-right: 0 !important;
                margin-left: 0 !important;
                margin-right: auto !important;
                width: auto !important;
            }
            /* PERIOD_OPTIONS 가 3개(3M/1Y/YTD)로 축소돼 별도 숨김 규칙 불필요 */
            /* BDC 박스 내부 — 토글/차트 간격 최소화 (0px, 차트 더 위로) */
            .st-key-box_returns [data-testid="stVerticalBlock"] {
                gap: 0px !important;
            }
            /* BDC 박스 — 모바일에서만 박스 자체의 height 고정 해제 (콘텐츠에 맞춰 expand).
               SVG 내부 요소까지 height:auto 강제하면 Plotly 렌더링이 깨지므로 박스 wrapper만 target. */
            div.st-key-box_returns,
            div.st-key-box_returns > [data-testid="stVerticalBlockBorderWrapper"],
            div.st-key-box_returns > [data-testid="stLayoutWrapper"] {
                height: auto !important;
                max-height: none !important;
                min-height: 0 !important;
            }
            div.st-key-box_returns {
                padding-bottom: 12px !important;
            }

            /* 0) 모든 rem 기반 폰트 한 단계 축소 (19.2px → 16.5px, 약 -14%) — 메인 제목만 예외 처리 */
            html { font-size: 16.5px !important; }
            /* 메인 제목 "사모신용 카나리아 모니터링" 은 데스크톱 시각 사이즈 (≈ 23px) 유지 */
            .pcc-header .pcc-title {
                font-size: 23px !important;
            }

            /* 더보기 버튼 — 모바일 전용 컴팩트 (버튼/텍스트 모두 축소) */
            .st-key-sec_more_wrap button,
            .st-key-news_more_wrap button {
                font-size: 0.78rem !important;
                padding: 3px 12px !important;
            }
            .st-key-sec_more_wrap button *,
            .st-key-news_more_wrap button * {
                font-size: 0.78rem !important;
            }

            /* 1) 컬럼 세로 스택 */
            [data-testid="stHorizontalBlock"] {
                flex-direction: column !important;
                gap: 12px !important;
            }
            [data-testid="stColumn"] {
                width: 100% !important;
                flex: 1 1 100% !important;
                min-width: 0 !important;
                /* 모바일 세로 스택 시 stColumn 내부 padding/margin 모두 제거 — 박스 간격이
                   stHorizontalBlock 의 gap: 12px 만으로 정확히 결정되도록 */
                padding: 0 !important;
                margin: 0 !important;
            }
            /* stHorizontalBlock(컬럼 컨테이너) 도 마진 0 — 위·아래로 간격이 새지 않도록 */
            [data-testid="stHorizontalBlock"] {
                margin: 0 !important;
            }
            .block-container {
                padding-left: 0.75rem !important;
                padding-right: 0.75rem !important;
            }

            /* 2) 박스 높이 — 콘텐츠 자동 (고정 460 해제).
               Streamlit 1.50 은 st.container(height=460) 의 height 를 wrapper 가 아닌
               안쪽 scrollable div (inline `height: 460px` + `overflow: auto`) 에 박음.
               inline style 매칭으로 그 div 를 직접 풀어줌. Plotly 차트는 height: 340/220
               등 다른 값 + overflow: visible 이라 이 selector 에 안 걸려 안전. */
            [data-testid="stVerticalBlockBorderWrapper"] {
                height: auto !important;
                min-height: 360px;
                padding: 12px 14px !important;
            }
            [data-testid="stVerticalBlockBorderWrapper"] [style*="height: 460px"],
            [data-testid="stVerticalBlockBorderWrapper"] [style*="height:460px"],
            [data-testid="stVerticalBlockBorderWrapper"] [style*="overflow: auto"],
            [data-testid="stVerticalBlockBorderWrapper"] [style*="overflow:auto"],
            [data-testid="stVerticalBlockBorderWrapper"] [style*="overflow-y: auto"],
            [data-testid="stVerticalBlockBorderWrapper"] [style*="overflow-y:auto"] {
                height: auto !important;
                max-height: none !important;
                overflow: visible !important;
            }
            /* ★ HY / BDC 박스 — 모바일 전용 박스 높이 명시. 값 조절로 박스 크기 변경 가능. */
            .st-key-box_hy [data-testid="stVerticalBlockBorderWrapper"] {
                min-height: 420px !important;   /* ← HY 박스 높이 조절 (차트 360 + padding/범례 여유) */
            }
            .st-key-box_returns [data-testid="stVerticalBlockBorderWrapper"] {
                min-height: 470px !important;   /* ← BDC 박스 높이 조절 (chart 축소 + 범례 fit) */
                padding-bottom: 2px !important; /* 범례 ↔ 박스 하단 사이 2px 여유 */
            }

            /* 3) 헤더 */
            .pcc-header {
                flex-wrap: wrap;
                gap: 6px;
                padding: 4px 0 6px 0;
            }
            /* .pcc-header .pcc-title 의 font-size 는 위 0) 블록에서 23px 로 고정 */
            .pcc-header .pcc-title {
                white-space: normal !important;
            }
            .pcc-header .pcc-update {
                font-size: 0.88rem;
                white-space: normal !important;
            }

            /* 4) 섹션 제목 (h5 모두) — 모바일에선 약간 작게 */
            h5 { font-size: 1.05rem !important; }

            /* 5) Risk Level pill / score / 한 줄 요약 */
            .pcc-summary { font-size: 1rem !important; }

            /* 6) 뉴스 카드 — 시간 박스 작게, 본문 폰트 축소 */
            .pcc-news-item {
                grid-template-columns: 50px 1fr auto !important;
                gap: 10px !important;
                padding: 10px 2px !important;
            }
            .pcc-news-time { font-size: 0.85rem !important; }
            .pcc-headline { font-size: 1rem !important; }
            .pcc-news-body .pcc-desc { font-size: 0.92rem !important; }
            .pcc-tag { font-size: 0.78rem !important; padding: 2px 8px !important; }
            .pcc-news-link { font-size: 0.85rem !important; }
            .pcc-date-header { font-size: 0.92rem !important; padding: 5px 10px !important; }

            /* 7) SEC 공시 카드 — 모바일에선 BDC명(위) + form(아래) 세로 스택 */
            .pcc-sec-item {
                grid-template-columns: 1fr !important;   /* 단일 컬럼 */
                row-gap: 4px !important;
                padding: 10px 2px !important;
            }
            .pcc-sec-name {
                font-size: 0.85rem !important;
                padding: 3px 10px !important;
                width: fit-content;
            }
            .pcc-sec-item .pcc-headline { font-size: 0.95rem !important; }
            .pcc-sec-item .pcc-desc { font-size: 0.92rem !important; }

            /* 8) Plotly 차트 — 여백·폰트 축소, 틱 라벨 듬성듬성 (CSS 한계 — Plotly 자체 width 는 자동 반응) */
            .js-plotly-plot .xtick text,
            .js-plotly-plot .ytick text {
                font-size: 11px !important;
            }
            .js-plotly-plot .legendtext {
                font-size: 11px !important;
            }
            /* 기간 pills 는 항목 많아 줄바꿈 허용 (전일대비/1주/1개월/3개월/6개월/1년/연초이후 7개) */
            .st-key-returns_period_box {
                flex-wrap: wrap !important;
            }

            /* 9) ★ 모바일 column-major 순서 (1, 2, 3, 5, 4, 6)
               · 행 1 (gauge, trend) 은 자연 순서 1, 2 그대로
               · 행 2-3 (HY, news, BDC, SEC) 은 wrapper(grid_charts_events) 안에서 재배치:
                 - HY    → 3
                 - BDC   → 4 (원래 5번이었음)
                 - News  → 5 (원래 4번이었음)
                 - SEC   → 6 */
            .st-key-grid_charts_events {
                display: flex !important;
                flex-direction: column !important;
                gap: 12px !important;
            }
            /* stColumn 이 grid_charts_events 의 직접 flex 자식이 되어야 :has() + order 가 동작.
               단, stColumn 내부의 stVerticalBlock 까지 투명화하면 박스 자체가 깨지므로
               grid_charts_events 의 "직계 경로" 만 정확히 타겟. */
            .st-key-grid_charts_events > [data-testid="stVerticalBlock"],
            .st-key-grid_charts_events > div:not([data-testid="stColumn"]) {
                display: contents !important;
            }
            .st-key-grid_charts_events > [data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"],
            .st-key-grid_charts_events > div > [data-testid="stHorizontalBlock"] {
                display: contents !important;
            }
            /* margin-top 해제 (PC 용) */
            .st-key-grid_charts_events [data-testid="stHorizontalBlock"]:not(:first-child) {
                margin-top: 0 !important;
            }
            /* ─── Risk Level 박스 (모바일) ─── 데스크톱 레이아웃 그대로 유지. 가로만 모바일 폭에 맞춤.
               차트 사이즈/pill 위치/title 등 별도 override 안 함 — 데스크톱 기본값 그대로 사용. 단,
               일반 모바일 룰(min-height: 360, height: auto)이 Risk Level 박스에도 적용되면 데스크톱
               460 높이가 유지 안 되므로 명시적 high-specificity 룰로 460 강제. */
            .st-key-risk_level_box,
            .st-key-risk_level_box [data-testid="stVerticalBlockBorderWrapper"] {
                height: 460px !important;
                min-height: 460px !important;
            }
            /* Risk Level 제목 — 모바일에서 1.25rem */
            .st-key-risk_level_box .st-key-risk_level_title h5 {
                font-size: 1.25rem !important;
            }
            /* 게이지 라벨 (Very Low ~ Very High) — 11.25px */
            .st-key-risk_level_box .js-plotly-plot text,
            .st-key-risk_level_box .js-plotly-plot .angular-axis text,
            .st-key-risk_level_box .js-plotly-plot g.angular-axis text,
            .st-key-risk_level_box .js-plotly-plot .angularaxistick text {
                font-size: 11.25px !important;
            }
            /* "오늘의 시장 한 줄 요약" 제목 — 모바일에서 살짝 아래로 */
            .pcc-summary-title-row h5 {
                margin-top: 6px !important;
            }

            /* AI 분석 뱃지 — 모바일에서 적당히 작게 + 살짝 아래 */
            .pcc-summary-title-row span[style*="background:#eef2ff"],
            .pcc-summary-title-row > span:last-child,
            .pcc-summary-title-row span[style*="display:inline-flex"] {
                font-size: 0.6rem !important;
                padding: 2px 8px !important;
                gap: 2px !important;
                transform: translate(-4px, -2px) !important;
            }
            .pcc-summary-title-row span[style*="background:#eef2ff"] > span,
            .pcc-summary-title-row > span:last-child > span,
            .pcc-summary-title-row span[style*="display:inline-flex"] > span {
                font-size: 0.65rem !important;
            }


            /* ─── 박스↔박스 간격 모바일 통일 (12px) ─── */
            /* Row 1 (Risk Level + Trend) ↔ grid_charts_events 사이의 빈 markdown 스페이서 제거 */
            .block-container [data-testid="stMarkdown"]:empty,
            .block-container [data-testid="stMarkdown"]:has(div:empty),
            .block-container [data-testid="stElementContainer"]:has([data-testid="stMarkdown"]:empty),
            .block-container [data-testid="stElementContainer"]:has([data-testid="stMarkdown"] > div:empty) {
                display: none !important;
                margin: 0 !important;
                padding: 0 !important;
                height: 0 !important;
            }
            /* Row 1 stHorizontalBlock ↔ grid_charts_events 사이 = 12px */
            /* 박스 사이 간격 — RL↔Trend, HY↔BDC↔News↔SEC 는 24px, Trend↔HY 만 4px */
            .st-key-grid_charts_events {
                gap: 24px !important;          /* HY ↔ BDC ↔ News ↔ SEC */
                margin-top: 4px !important;    /* Trend ↔ HY (시각적으로 좁게) */
            }
            .st-key-summary_row [data-testid="stHorizontalBlock"] {
                gap: 24px !important;          /* RL ↔ Trend */
            }
            /* 모든 stHorizontalBlock 의 위·아래 마진 0 (gap 만으로 간격 제어) */
            [data-testid="stHorizontalBlock"] {
                margin-top: 0 !important;
                margin-bottom: 0 !important;
            }

            /* ─── Risk Trend / 한 줄 요약 박스 (모바일) ─── */
            /* (5) 한 줄 요약 본문 폰트 축소 + 제목과의 간격 12px (인라인 0 override) */
            .pcc-summary-body {
                font-size: 0.95rem !important;
                line-height: 1.55 !important;
                margin-top: 12px !important;
            }
            /* (6) AI 분석 뱃지 좌측 여백(gap) 축소 */
            .pcc-summary-title-row {
                gap: 0 !important;
            }
            .pcc-summary-title-row span[style*="background:#eef2ff"] {
                margin-left: -4px !important;
            }
            /* (7) 추이 차트 제목 ↔ 차트 사이 간격 축소 */
            .st-key-risk_trend_box h5 {
                margin-bottom: -10px !important;
            }
            .st-key-risk_trend_box [data-testid="stPlotlyChart"] {
                margin-top: 0 !important;
            }

            /* :has() 로 박스 식별해서 order 지정 (Chrome 105+, 2022~) */
            .st-key-grid_charts_events [data-testid="stColumn"]:has(.st-key-box_hy)      { order: 1; }
            .st-key-grid_charts_events [data-testid="stColumn"]:has(.st-key-box_returns) { order: 2; }
            .st-key-grid_charts_events [data-testid="stColumn"]:has(.st-key-box_news)    { order: 3; }
            .st-key-grid_charts_events [data-testid="stColumn"]:has(.st-key-box_sec)     { order: 4; }
        }

        /* ─── 태블릿~소형노트북 (769~1366px) — box_returns 토글 2개 세로 스택 ───
           iPad 는 세로 810~1024 / 가로 1080~1366 으로 폭이 넓어 1024 상한으론 부족.
           이 폭 구간에선 box_returns 가 화면 절반이라 columns([2,3]) 가 항상 좁음 →
           모바일(≤768px) 의 grid 1열 강제 기법을 차용해 스택. 차트는 데스크톱 버전 유지. */
        @media (min-width: 769px) and (max-width: 1366px) {
            body div.st-key-box_returns div[data-testid="stHorizontalBlock"],
            body div.st-key-box_returns div[class*="stHorizontalBlock"] {
                display: grid !important;
                grid-template-columns: 1fr !important;
                gap: 8px !important;
                width: 100% !important;
            }
            body div.st-key-box_returns div[data-testid="stColumn"],
            body div.st-key-box_returns div[class*="stColumn"] {
                display: block !important;
                width: 100% !important;
                max-width: 100% !important;
                min-width: 0 !important;
                flex: unset !important;
                padding: 0 !important;
            }
            /* 적용기간 박스 — 데스크톱 flex-end(우정렬) 해제, 모니터링대상과 좌측 정렬 맞춤 */
            .st-key-returns_period_box {
                justify-content: flex-start !important;
                text-align: left !important;
                padding-left: 10px !important;
                padding-right: 0 !important;
            }
            /* 게이지 라벨 — iPad 폭에서 17px 는 양끝 라벨(Very Low/Very High)이 잘림 → 13px */
            .st-key-risk_level_box .js-plotly-plot text,
            .st-key-risk_level_box .js-plotly-plot .angular-axis text,
            .st-key-risk_level_box .js-plotly-plot g.angular-axis text,
            .st-key-risk_level_box .js-plotly-plot .angularaxistick text {
                font-size: 13px !important;
            }
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# =============================================================================
# 데이터 로딩 (1시간 캐시)
# =============================================================================

CSV_BINARY_MAGIC = b"SCDSA"  # 사내 바이너리 포맷 — CSV 가 아니므로 거른다.


def _read_csv_safely(path: Path) -> pd.DataFrame:
    """다양한 인코딩의 CSV 를 안전하게 로드. 실패 시 빈 DF 반환 (앱 죽지 않게)."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
        if head.startswith(CSV_BINARY_MAGIC) or b"\x00" in head:
            return pd.DataFrame()
    except OSError:
        return pd.DataFrame()

    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return pd.read_csv(path, encoding=enc)
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


@st.cache_data(ttl=86400)
def load_price_history() -> pd.DataFrame:
    """가격 시계열 로딩.

    1) private_credit_price_history.csv 가 정상 CSV 면 우선 사용
    2) 실패하면 private_credit_returns_ytd_series.csv 의 (ticker, base_dt, close)
       컬럼만 골라 폴백으로 사용 — 동일한 종목별 일별 종가 시계열을 담고 있다.
    """
    needed = {"base_dt", "ticker", "close"}
    cols = ["base_dt", "ticker", "close"]

    candidates = [
        DATA_DIR / "private_credit_price_history.csv",
        DATA_DIR / "price_history.csv",  # 구버전 파일명 호환
        DATA_DIR / "private_credit_returns_ytd_series.csv",  # 폴백
    ]
    for path in candidates:
        if not path.exists():
            continue
        df = _read_csv_safely(path)
        if df.empty or not needed.issubset(df.columns):
            continue
        df = df[cols].copy()
        df["base_dt"] = pd.to_datetime(df["base_dt"], errors="coerce")
        df = df.dropna(subset=["base_dt"])
        if not df.empty:
            return df

    return pd.DataFrame(columns=cols)


@st.cache_data(ttl=86400)
def load_sec_filings() -> pd.DataFrame:
    path = DATA_DIR / "private_credit_sec_filings_history.csv"
    if not path.exists():
        return pd.DataFrame()
    df = _read_csv_safely(path)
    if df.empty or "filing_date" not in df.columns:
        return pd.DataFrame()
    df["filing_date"] = pd.to_datetime(df["filing_date"], errors="coerce")
    return df.dropna(subset=["filing_date"]).sort_values("filing_date", ascending=False).reset_index(drop=True)


@st.cache_data(ttl=3600)
def load_periodic_kpi() -> pd.DataFrame:
    """정기공시 (10-K/10-Q) 누적 — fund 별 분기 NAV/PIK/Non-accrual.

    화면에선 filed_date 기준으로 8-K 등과 함께 SEC 박스에 표시.
    같은 fund 의 직전 분기 값을 _prev_* 컬럼으로 미리 계산해두어 ▲/▼ 표시에 사용.
    컬럼: cik, fund_name, form, period_end, filed_date,
          nav_per_share, pik_ratio_pct, nonaccrual_pct,
          _prev_nav_per_share, _prev_pik_ratio_pct, _prev_nonaccrual_pct
    """
    path = DATA_DIR / "private_credit_sec_periodic_history.csv"
    if not path.exists():
        return pd.DataFrame()
    df = _read_csv_safely(path)
    if df.empty or "filed_date" not in df.columns:
        return pd.DataFrame()
    df["filed_date"] = pd.to_datetime(df["filed_date"], errors="coerce")
    if "period_end" in df.columns:
        df["period_end"] = pd.to_datetime(df["period_end"], errors="coerce")
    df = df.dropna(subset=["filed_date"])

    # 펀드별 직전 분기 값 — period_end 오름차순 정렬 후 그룹 shift(1)
    if "period_end" in df.columns and "fund_name" in df.columns:
        df = df.sort_values(["fund_name", "period_end"]).reset_index(drop=True)
        for col in ("nav_per_share", "pik_ratio_pct", "nonaccrual_pct"):
            if col in df.columns:
                df[f"_prev_{col}"] = df.groupby("fund_name", sort=False)[col].shift(1)

    return df.sort_values("filed_date", ascending=False).reset_index(drop=True)


@st.cache_data(ttl=86400)
def load_news() -> pd.DataFrame:
    """국내+해외 뉴스를 통합. 해외 CSV 에 title_kr/summary_kr 가 있으면 그대로 보존."""
    frames = []
    for region, fname in [
        ("국내", "private_credit_news_korea_history.csv"),
        ("해외", "private_credit_news_global_history.csv"),
    ]:
        path = DATA_DIR / fname
        if not path.exists():
            continue
        df = _read_csv_safely(path)
        if df.empty or "published_at" not in df.columns:
            continue
        df["region"] = region
        frames.append(df)
    cols = ["published_at", "publisher", "title", "summary", "url", "region"]
    if not frames:
        return pd.DataFrame(columns=cols)
    df = pd.concat(frames, ignore_index=True)
    df["published_at"] = pd.to_datetime(df["published_at"], errors="coerce")
    return df.dropna(subset=["published_at"]).sort_values("published_at", ascending=False).reset_index(drop=True)


# =============================================================================
# 1) 헤더
# =============================================================================

def _last_update_date(
    price_df: pd.DataFrame | None = None,
    news_df: pd.DataFrame | None = None,
    filings_df: pd.DataFrame | None = None,
) -> date | None:
    """주가(price) 데이터의 가장 최근 base_dt 를 기준일로 반환.

    뉴스/공시는 미국 시간 기준이라 KR 수집 시점과 어긋날 수 있어, 헤더 '기준일'은
    가장 안정적인 주가 데이터의 최신 영업일로 통일. news_df / filings_df 인자는
    하위 호환 유지용으로 남기되 사용하지 않음.
    """
    if price_df is not None and not price_df.empty and "base_dt" in price_df.columns:
        return price_df["base_dt"].max().date()
    return None


def render_header(
    price_df: pd.DataFrame,
    news_df: pd.DataFrame | None = None,
    filings_df: pd.DataFrame | None = None,
) -> None:
    last_update = _last_update_date(price_df, news_df, filings_df)
    last_str = f"기준일: {last_update.strftime('%y.%m.%d')}" if last_update is not None else "데이터 없음"

    # flex 레이아웃 + white-space:nowrap 으로 어떤 폭에서도 제목이 잘리지 않도록.
    st.markdown(
        f"""
        <div class="pcc-header">
          <div class="pcc-title">
            <span class="material-symbols-rounded pcc-main-icon">dashboard_2_gear</span>
            사모신용 카나리아 모니터링
          </div>
          <div class="pcc-update">{last_str}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if price_df.empty:
        st.warning("가격 시계열을 불러오지 못했습니다. data/ 폴더의 CSV 형식을 확인하세요.")

    # ─── 관리자 모드: URL 에 ?admin=true 추가 시 데이터 다운로드 섹션 표시 ───
    _is_admin = st.query_params.get("admin") == "true"
    if _is_admin:
        _render_admin_downloads()

    st.divider()


def _render_admin_downloads() -> None:
    """관리자 전용 데이터 다운로드 — data/ 폴더의 모든 CSV + JSON 을 ZIP 으로 묶어 제공.

    URL 에 ?admin=true 가 있을 때만 표시. 외부 사용자에겐 보이지 않음.
    """
    import io
    import zipfile

    with st.expander("📥 데이터 다운로드 (관리자)", expanded=False):
        st.caption("HF Space 컨테이너 안의 최신 데이터를 ZIP 으로 다운로드.")

        # ZIP 생성 — data/ 폴더 안의 모든 CSV + JSON
        buf = io.BytesIO()
        files_added = 0
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fp in sorted(DATA_DIR.glob("*.csv")):
                zf.write(fp, arcname=fp.name)
                files_added += 1
            for fp in sorted(DATA_DIR.glob("*.json")):
                zf.write(fp, arcname=fp.name)
                files_added += 1
        buf.seek(0)

        col1, col2 = st.columns([3, 2])
        with col1:
            from datetime import datetime as _dt
            stamp = _dt.now().strftime("%Y%m%d_%H%M%S")
            st.download_button(
                label=f"📦 전체 ZIP 다운로드 ({files_added}개 파일)",
                data=buf,
                file_name=f"private_credit_data_{stamp}.zip",
                mime="application/zip",
                use_container_width=True,
            )
        with col2:
            zip_size_kb = len(buf.getvalue()) / 1024
            st.caption(f"파일 수: {files_added} · ZIP 크기: {zip_size_kb:.0f} KB")


# =============================================================================
# 2) 요약 (리스크 점수 / 일일 총평)
# =============================================================================

# 첨부 이미지의 5단계 색상 팔레트 — 외측(진한)·내측(연한)·pill 표시색
_RISK_PALETTE = [
    # (상한 미만, 라벨, 외측, 내측, pill) — pill 은 외측과 동일 색 사용
    (20,  "Very Low",  "#1B7C3A", "#93C9A4", "#1B7C3A"),
    (40,  "Low",       "#86C39C", "#CCE7D6", "#86C39C"),
    (60,  "Moderate",  "#F2D88A", "#FAEFC7", "#F2D88A"),
    (80,  "High",      "#F2A6A4", "#F8D5D3", "#F2A6A4"),
    (101, "Very High", "#DC2626", "#F08F8F", "#DC2626"),
]


def _risk_level(value: float) -> tuple[str, str]:
    """value → (label, pill color)."""
    for upper, label, _, _, pill in _RISK_PALETTE:
        if value < upper:
            return label, pill
    return "Very High", "#DC2626"


def _risk_gauge(value: float) -> go.Figure:
    """반원형 리스크 게이지 — 외측·내측 두 개의 띠 + 중앙 회전축의 바늘."""
    seg_width = 34  # 36도 세그먼트에서 양쪽 1도씩 갭
    centers = [162, 126, 90, 54, 18]  # Very Low → Very High (좌→우)
    # 게이지 라벨만 단어별 줄바꿈 — 좁은 화면에서 잘림 방지 ("Very Low" → "Very\nLow").
    # _RISK_PALETTE 원본은 pill 등에서 한 줄로 사용되므로 건드리지 않음.
    labels = [p[1].replace(" ", "<br>") for p in _RISK_PALETTE]
    outer_colors = [p[2] for p in _RISK_PALETTE]
    inner_colors = [p[3] for p in _RISK_PALETTE]

    fig = go.Figure()

    # 외측 띠
    fig.add_trace(
        go.Barpolar(
            r=[0.30] * 5, theta=centers, width=[seg_width] * 5, base=0.70,
            marker=dict(color=outer_colors, line=dict(width=0)),
            hoverinfo="skip", showlegend=False,
        )
    )
    # 내측 띠
    fig.add_trace(
        go.Barpolar(
            r=[0.18] * 5, theta=centers, width=[seg_width] * 5, base=0.48,
            marker=dict(color=inner_colors, line=dict(width=0)),
            hoverinfo="skip", showlegend=False,
        )
    )

    # 바늘 — value(0-100)을 angle(180-0)로 매핑
    needle_angle = 180 - (max(0, min(100, value)) / 100) * 180
    fig.add_trace(
        go.Scatterpolar(
            r=[0, 0.65], theta=[needle_angle, needle_angle], mode="lines",
            line=dict(color="#475569", width=2), hoverinfo="skip", showlegend=False,
        )
    )
    # 회전축
    fig.add_trace(
        go.Scatterpolar(
            r=[0], theta=[0], mode="markers",
            marker=dict(color="#475569", size=10),
            hoverinfo="skip", showlegend=False,
        )
    )

    fig.update_layout(
        # Neutral (theta=90 상단) 라벨이 차트 상단에 잘리지 않도록 t 마진 확대
        # 게이지 살짝 축소 (305 → 270) → 하단 "xx / 100점" 표시 공간 확보
        height=270,
        margin=dict(l=20, r=20, t=24, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="white",
        showlegend=False,
        font=PLOTLY_FONT,
        polar=dict(
            sector=[0, 180],
            bgcolor="rgba(0,0,0,0)",
            radialaxis=dict(visible=False, range=[0, 1.05]),
            angularaxis=dict(
                tickvals=centers,
                ticktext=labels,
                tickfont=dict(color="#64748b", size=17),
                showgrid=False,
                showline=False,
                ticks="",
                direction="counterclockwise",
            ),
        ),
    )
    return fig


def _risk_trend(
    score_today: float,
    end_date: date | None = None,
    history: list[dict] | None = None,
) -> go.Figure:
    """최근 1개월 리스크 종합점수 추이 — 그라데이션 영역 차트.

    history (score_risk.py 가 누적 저장한 일별 결과) 가 있으면 실데이터로 그림.
    비어있으면 오늘 점수 1점만 표시 (누적 시작 시점).
    """
    if end_date is None:
        end_date = date.today()

    # history 에서 (date, composite_score) 쌍을 추출 — 최근 1개월(30일) 만 표시
    cutoff = end_date - timedelta(days=30)
    dates: list[date] = []
    series: list[float] = []
    if history:
        for h in history:
            d_str = h.get("date")
            s = h.get("composite_score")
            if not d_str or s is None:
                continue
            try:
                d = pd.to_datetime(d_str).date()
            except Exception:
                continue
            if d < cutoff:
                continue
            dates.append(d)
            series.append(float(s))

    # history 가 비어있거나 파싱 실패 → 오늘 점수 1점만
    if not dates:
        dates = [end_date]
        series = [float(score_today)]

    fig = go.Figure()

    # ── 글로우 효과 (3 layer) — 강한 네온 빛 표현
    # 가장 큰 (가장 옅은) 외곽 글로우
    fig.add_trace(go.Scatter(
        x=dates, y=series, mode="markers",
        marker=dict(symbol="circle", size=20, color="rgba(255,255,255,0.4)"),
        hoverinfo="skip", showlegend=False,
    ))
    # 중간 글로우 (더 진함)
    fig.add_trace(go.Scatter(
        x=dates, y=series, mode="markers",
        marker=dict(symbol="circle", size=14, color="rgba(255,255,255,0.7)"),
        hoverinfo="skip", showlegend=False,
    ))

    # 메인 라인 + 마커 (붉은 채움 + 두꺼운 흰 테두리)
    fig.add_trace(go.Scatter(
        x=dates, y=series,
        mode="lines+markers",
        # ① 곡선 (spline 스무딩)
        line=dict(color="#DC2626", width=2.5, shape="spline", smoothing=1.0),
        # ② 붉은 채움 + 두꺼운 흰 테두리 마커
        marker=dict(
            symbol="circle",
            size=8,
            color="#DC2626",
            line=dict(color="white", width=3),
        ),
        fill="tozeroy",
        fillcolor="rgba(220, 38, 38, 0.12)",
        # ③ hover: 날짜 + "리스크 점수: XX점"
        hovertemplate="<b>%{x|%y.%m.%d}</b><br>리스크 점수: %{y:.0f}점<extra></extra>",
    ))
    fig.update_layout(
        # 박스 460 - 제목 30 - "한줄요약" 영역(110) - padding 30 ≈ 290 가용 → 차트 190
        height=190,
        margin=dict(l=8, r=8, t=0, b=10),
        dragmode=False,   # zoom box / pan 차단 (hover 는 유지)
        plot_bgcolor="white",
        paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(
            showgrid=False,
            tickformat="%y.%m.%d",
            tickfont=dict(size=17),
            # ④ hover 시 수직 회색 점선 (spike line) — 데이터 포인트에 snap (tooltip 과 일치)
            showspikes=True,
            spikemode="across",
            spikesnap="data",
            spikedash="dot",
            spikethickness=1,
            spikecolor="#9ca3af",
            # 데이터에 없는 날짜 (주말·미국 휴일) 모두 숨김 — 영업일만 x축 표시
            rangebreaks=[dict(values=_missing_dates_from(pd.Series(dates)))],
            # 균등 간격 tick 강제
            tickmode="array",
            tickvals=_evenly_spaced_ticks(dates, n=6),
        ),
        yaxis=dict(
            range=[0, 100],
            tickvals=[0, 20, 40, 60, 80, 100],
            gridcolor="#eef0f3",
            tickfont=dict(size=17),
            zeroline=False,
        ),
        showlegend=False,
        font=PLOTLY_FONT,
        # ⑤ 데이터 포인트 세로 column 단위로 hover — cursor 가 column 안 어디든 그 포인트 값 표시
        hovermode="x",
        hoverlabel=dict(
            bgcolor="white",
            bordercolor="#e5e7eb",
            font=dict(family="'Manrope', 'SUIT Variable', sans-serif", size=16, color="#1e293b"),
        ),
    )
    return fig


# 모든 박스 동일 사이즈 — 2열 × 3행 그리드 공통 높이
BOX_HEIGHT = 460
_SUMMARY_CARD_HEIGHT = BOX_HEIGHT


def render_summary(price_df: pd.DataFrame | None = None) -> None:
    # 좌·우 1:1 균등 (preview 레이아웃과 동일).
    # st.container(key="summary_row") 로 감싸 모바일에서 RL↔Trend 사이 gap 만 별도로 조정 가능하게 함.
    summary_row = st.container(key="summary_row")
    with summary_row:
        left, right = st.columns(2, gap="small")

    # 종합 점수 — score_risk.py 가 만든 JSON 에서 로드. 없으면 중립 50.
    risk_data = _load_risk_score()
    composite = risk_data.get("composite", {})
    score = float(composite.get("composite_score", 50.0))
    # 한 줄 요약 — Synthesis Agent 가 3 카테고리 통합한 결과 (음슴체)
    composite_insight = composite.get("summary_insight", "").strip()
    # 일별 점수 history (추이 차트용) — 매 산출마다 누적 저장됨
    score_history = risk_data.get("history", [])

    # 추이 차트 마지막 점 = 시스템 today (점수 자체가 오늘 산출이므로 차트 x축도 오늘로 통일)
    end_date = date.today()

    with left:
        with st.container(border=True, height=_SUMMARY_CARD_HEIGHT, key="risk_level_box"):
            # h5 마크다운으로 다른 카드 제목과 사이즈 통일, 가운데 정렬은 CSS 로
            with st.container(key="risk_level_title"):
                st.markdown("##### Risk Level")
            st.plotly_chart(
                _risk_gauge(score),
                width="stretch",
                config={
                    "displayModeBar": False,
                    "doubleClick": False,   # 더블탭 줌인/리셋 비활성 (모바일에서 의도치 않은 zoom 방지)
                    "scrollZoom": False,
                    "staticPlot": True,     # 모든 interactive 동작 차단 (gauge 는 표시만 하면 됨)
                },
            )
            level, color = _risk_level(score)
            # pill 박스 살짝 줄임 (padding·font 축소) → 게이지 위쪽 여유 확보
            st.markdown(
                f'<div class="pcc-risk-pillwrap" style="text-align:center; margin-top:-4px;">'
                f'<span style="display:inline-block; background:{color}; color:white; '
                f'padding:6px 32px; border-radius:20px; font-weight:600; font-size:1.1rem;">'
                f'{level}</span>'
                f'<div style="margin-top:8px; color:#475569; font-weight:600; font-size:1.1rem;">'
                f'{int(round(score))} / 100</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    with right:
        with st.container(border=True, height=_SUMMARY_CARD_HEIGHT, key="risk_trend_box"):
            st.markdown(
                '<h5 style="margin:-6px 0 -26px 0; font-size:1.1rem;">'
                '<span class="material-symbols-rounded pcc-title-icon">insights</span> '
                '리스크 종합점수 추이</h5>',
                unsafe_allow_html=True,
            )
            st.plotly_chart(
                _risk_trend(score, end_date=end_date, history=score_history),
                width="stretch",
                config={"displayModeBar": False, "doubleClick": False, "scrollZoom": False},
            )
            # 추이 차트 ↔ 한 줄 요약 간격
            st.markdown('<div style="height: 2px;"></div>', unsafe_allow_html=True)

            # 제목 + AI 분석 뱃지 (제목 우측 3px 공백 후, baseline 동일 라인)
            st.markdown(
                """
                <div class="pcc-summary-title-row" style="display:flex; align-items:baseline; gap:1px; margin-bottom:0;">
                    <h5 style="margin:0; font-size:1.1rem;">
                      <span class="material-symbols-rounded pcc-title-icon">lightbulb</span>
                      오늘의 시장 한 줄 요약
                    </h5>
                    <span class="pcc-ai-badge" style="display:inline-flex; align-items:center; gap:4px;
                                 font-size:0.78rem; font-weight:600;
                                 padding:3px 10px; border-radius:999px;
                                 transform: translateY(-3px);">
                        <span style="font-size:0.85rem;">✨</span>
                        <span>AI 분석</span>
                    </span>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # Synthesis Agent 가 시장·뉴스·공시 통합해 만든 한 줄 (음슴체)
            # 색상 (배경/글자) 은 CSS 클래스 .pcc-summary-body 에서 지정
            if composite_insight:
                st.markdown(
                    f'<div class="pcc-summary-body" style="font-size:1.1rem; line-height:1.65; '
                    f'padding:12px 16px; border-radius:8px; margin-top:0; '
                    f'word-break:keep-all; overflow-wrap:break-word;">'
                    f'{composite_insight}</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    """
                    <div style="font-size: 1.25rem; color:#1e293b;">아직 산출된 점수 없음</div>
                    <div style="color:#64748b; font-size:1.05rem; margin-top:14px;">
                      start_dashboard.bat 의 [4/5] 단계 실행 시 자동으로 채워짐.
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


# =============================================================================
# 3-A) 좌측: 시장 보드
# =============================================================================

def _missing_dates_from(date_series: pd.Series) -> list[str]:
    """date_series 의 min~max 사이에서 데이터가 없는 모든 날짜 반환 (rangebreaks 용).

    가격 CSV 는 거래일에만 데이터 — 그 외 날짜(주말·미국 휴일)는 모두 missing.
    이 missing 리스트를 rangebreaks values 로 넣으면 x축에서 자동 숨김.
    """
    if date_series.empty:
        return []
    dates = pd.to_datetime(date_series).dt.normalize().unique()
    if len(dates) == 0:
        return []
    full_range = pd.date_range(dates.min(), dates.max(), freq="D")
    missing = full_range.difference(dates)
    return [d.strftime("%Y-%m-%d") for d in missing]


def _evenly_spaced_ticks(date_list, n: int = 6) -> list:
    """sorted date_list 에서 n 개 균등 간격 dates 선택 (x축 tick 균등 배치용).

    가장 최근 영업일 (= sorted_dates[-1]) 은 어떤 토글 선택이든 무조건 마지막 tick 으로 포함됨.
    rangebreaks 적용 후 Plotly 자동 tick 이 들쭉날쭉할 때 명시적으로 지정해서 일정 간격 확보.
    """
    sorted_dates = sorted(date_list)
    if not sorted_dates:
        return []
    if len(sorted_dates) <= n:
        return sorted_dates
    step = (len(sorted_dates) - 1) / (n - 1)
    ticks = [sorted_dates[round(i * step)] for i in range(n)]
    # 안전망 — round 결과가 어떤 이유로 last index 와 어긋나도 마지막 날짜 강제 포함
    if ticks[-1] != sorted_dates[-1]:
        ticks[-1] = sorted_dates[-1]
    return ticks


def chart_indicator(price_df: pd.DataFrame, days: int = 365, mobile: bool = False) -> go.Figure:
    # 화면 표시는 최근 N일만 (CSV 자체는 누적 그대로 보존)
    if not price_df.empty:
        cutoff = price_df["base_dt"].max() - pd.Timedelta(days=days)
        price_df = price_df[price_df["base_dt"] >= cutoff]

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    hy = price_df[price_df["ticker"] == "BAMLH0A0HYM2"].sort_values("base_dt")

    if not hy.empty:
        # FRED 의 BAMLH0A0HYM2 는 percent 단위(예: 2.86 = 2.86%) — 표시도 % 로 통일
        hy_color = COLOR_MAP["BAMLH0A0HYM2"]
        fig.add_trace(
            go.Scatter(
                x=hy["base_dt"], y=hy["close"],
                name="HY 스프레드",
                mode="lines",
                line=dict(color=hy_color, width=2, shape="spline", smoothing=1.0),
                hovertemplate="HY 스프레드 %{y:.2f}%<extra></extra>",
            ),
            secondary_y=False,
        )

    # 미국 국채 금리 — 1Y / 5Y 만 우측 Y축에 표시 (3Y 제외, 범례 단순화). 범례명은 짧게.
    # HY 스프레드(실선) 와 시각적 구분을 위해 모두 짧은 점선(dot) 으로 통일. 색상 톤으로 만기 구분.
    for tk, label in [("DGS1", "1Y"), ("DGS5", "5Y")]:
        df_t = price_df[price_df["ticker"] == tk].sort_values("base_dt")
        if df_t.empty:
            continue
        tk_color = COLOR_MAP.get(tk, "#999999")
        fig.add_trace(
            go.Scatter(
                x=df_t["base_dt"], y=df_t["close"],
                name=label,
                mode="lines",
                line=dict(
                    color=tk_color, width=2, shape="spline", smoothing=1.0,
                    dash="dot",
                ),
                hovertemplate=label + " %{y:.2f}%<extra></extra>",
            ),
            secondary_y=True,
        )

    # 양쪽 y축 모두 소수점 1자리 강제 (3 → 3.0, 4 → 4.0). 모바일은 폰트 축소.
    yaxis_tickfont = dict(size=10) if mobile else None
    yaxis_titlefont = dict(size=11) if mobile else None
    fig.update_yaxes(
        title_text="HY 스프레드 (%)", secondary_y=False,
        color=COLOR_MAP["BAMLH0A0HYM2"], tickformat=".1f",
        tickfont=yaxis_tickfont, title_font=yaxis_titlefont,
    )
    fig.update_yaxes(
        title_text="미국 국채 금리 (%)", secondary_y=True, tickformat=".1f",
        tickfont=yaxis_tickfont, title_font=yaxis_titlefont,
    )
    # 범례 — 데스크톱은 원본(상단 우측), 모바일은 차트 하단 중앙 + 테두리.
    # 모바일: 폭/위치 하드코딩 없이 Plotly auto-size 에 맡김. xanchor=center 로 화면 중앙 정렬.
    if mobile:
        # 모바일은 Plotly 범례 끄고 HTML 범례를 render_hy_box 에서 별도 렌더 (BDC 차트와 동일 스타일)
        legend_cfg = dict()
        mobile_showlegend = False
        top_margin = 24
        bottom_margin = 20
    else:
        legend_cfg = dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        mobile_showlegend = True
        top_margin = 24
        bottom_margin = 10
    l_margin = 10
    r_margin = 30
    hover_font_size = 11 if mobile else 16
    fig.update_layout(
        # 박스 460 - 제목 38(타이틀 row) - padding 30 ≈ 392 가용 → 차트 380 (모바일 360)
        height=360 if mobile else 380,
        margin=dict(l=l_margin, r=r_margin, t=top_margin, b=bottom_margin),
        dragmode=False,   # zoom box / pan 차단 (hover 는 유지)
        legend=legend_cfg,
        showlegend=mobile_showlegend,
        hovermode="x unified",
        plot_bgcolor="white",
        font=PLOTLY_FONT,
        hoverlabel=dict(
            bgcolor="white",
            bordercolor="#e5e7eb",
            font=dict(family="'Manrope', 'SUIT Variable', sans-serif", size=hover_font_size, color="#1e293b"),
        ),
    )
    # CSV 데이터에 없는 날짜 (주말 + 미국 휴일) 자동 추출 → x축에서 모두 숨김
    indicator_dates = price_df[
        price_df["ticker"].isin(["BAMLH0A0HYM2", "DGS1", "DGS3", "DGS5"])
    ]["base_dt"]
    missing = _missing_dates_from(indicator_dates)
    # 균등 간격 tick — rangebreaks 적용 후 Plotly 자동 tick 이 들쭉날쭉한 것 보정
    sorted_unique = sorted(pd.to_datetime(indicator_dates).dt.normalize().unique())
    tickvals = _evenly_spaced_ticks(sorted_unique, n=6)
    fig.update_xaxes(
        showgrid=False, tickformat="%y.%m.%d",
        # automargin — 마지막 tick 라벨이 차트 우측 가장자리에서 잘리지 않도록 보장
        automargin=True,
        # unified hover 상단의 날짜 표시 — HTML <b> 태그로 굵게
        hoverformat="<b>%y.%m.%d</b>",
        # spike line 이 데이터 포인트에 snap — cursor 좌우 이동 시 다음 포인트로 점프
        showspikes=True, spikemode="across", spikesnap="data",
        spikedash="dot", spikethickness=1, spikecolor="#9ca3af",
        # 데이터에 없는 날짜 (주말·휴일) 모두 숨김
        rangebreaks=[dict(values=missing)] if missing else [],
        # 균등 간격 tick 강제
        tickmode="array", tickvals=tickvals,
    )
    fig.update_yaxes(gridcolor="#eef0f3")
    return fig


def _period_start(end: pd.Timestamp, period: str) -> pd.Timestamp:
    if period == "연초이후":
        return pd.Timestamp(year=end.year, month=1, day=1)
    if period == "전일대비":
        # 직전 영업일 (주말·휴일이 끼어도 가장 최근 거래일을 뽑도록 US 영업일 캘린더 사용)
        from pandas.tseries.holiday import USFederalHolidayCalendar
        from pandas.tseries.offsets import CustomBusinessDay
        us_bd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
        return end - us_bd
    return end - timedelta(days=PERIOD_DAYS[period])


def chart_returns(price_df: pd.DataFrame, tickers: list[str], period: str,
                   mobile: bool = False) -> go.Figure:
    """선택 기간 동안의 누적 수익률(%) 차트. 시작일=0%."""
    end = price_df["base_dt"].max()
    start = _period_start(end, period)

    benchmark_set = set(CATEGORY_TICKERS["벤치마크"])

    fig = go.Figure()
    for t in tickers:
        df_t = price_df[(price_df["ticker"] == t) & (price_df["base_dt"] >= start)].sort_values("base_dt")
        if df_t.empty:
            continue
        base = float(df_t.iloc[0]["close"])
        if base == 0:
            continue
        pct = (df_t["close"] / base - 1.0) * 100.0
        label = get_ticker_label(t)
        color = COLOR_MAP.get(t, "#999999")
        # ★ 부동소수점 정밀도 (16자리) 가 hover 에 그대로 노출되는 것을 방지 —
        #   pct 값을 사전 포맷팅 후 customdata 로 전달, hovertemplate 에서 customdata 사용
        pct_formatted = [f"{v:+.2f}" for v in pct]
        # 벤치마크 (BIZD, ^GSPC, HYG) 는 솔리드 + 얇은 라인 — BDC/운용사보다 가늘게.
        # BDC + 운용사는 솔리드 + 굵은 라인 → 시각적으로 카테고리 구분.
        is_benchmark = t in benchmark_set
        line_dash = "solid"
        line_width = 2 if is_benchmark else 2.5
        # 곡선(spline) — 깔끔하게 lines 만 (markers 제거)
        fig.add_trace(
            go.Scatter(
                x=df_t["base_dt"], y=pct, mode="lines", name=label,
                customdata=pct_formatted,
                line=dict(color=color, width=line_width, shape="spline", smoothing=1.0, dash=line_dash),
                hovertemplate=label + " %{customdata}%<extra></extra>",
            )
        )

    # 0% 기준선 — 라인보다 가늘게
    fig.add_hline(y=0, line=dict(color="#cbd5e1", width=0.8, dash="dot"))

    # CSV 데이터에 없는 날짜 (주말 + 미국 휴일) 자동 추출 → x축에서 모두 숨김
    shown_data = price_df[
        price_df["ticker"].isin(tickers) & (price_df["base_dt"] >= start)
    ]
    missing = _missing_dates_from(shown_data["base_dt"])
    # 균등 간격 tick
    sorted_unique = sorted(pd.to_datetime(shown_data["base_dt"]).dt.normalize().unique())
    tickvals = _evenly_spaced_ticks(sorted_unique, n=6)

    # 범례 — 데스크톱은 Plotly 내장(상단 우측, 원본). 모바일은 Plotly 범례 끄고 HTML 로 외부 렌더.
    if mobile:
        legend_cfg = dict()   # 사용 안 함
        showlegend = False
        top_margin = 0        # 8 → 0 (chart 더 위로)
        bottom_margin = 10
        yaxis_extra = dict(title_font=dict(size=11), tickfont=dict(size=10))
        chart_height = 220   # 모바일에서 chart + 범례까지 한 viewport 에 들어오도록 축소
    else:
        legend_cfg = dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        showlegend = True
        top_margin = 40
        bottom_margin = 10
        yaxis_extra = {}
        chart_height = 305   # 340 → 305 — iPad 폭에서 토글이 2행 스택되므로 차트 추가 축소
    hover_font_size = 11 if mobile else 16   # HY 차트와 동일
    fig.update_layout(
        height=chart_height,
        margin=dict(l=10, r=30, t=top_margin, b=bottom_margin),
        dragmode=False,   # zoom box / pan 차단 (hover 는 유지)
        showlegend=showlegend,
        yaxis=dict(
            title="수익률 (%)", ticksuffix="%", gridcolor="#eef0f3",
            autorange=True, hoverformat=".2f",
            **yaxis_extra,
        ),
        xaxis=dict(
            showgrid=False, tickformat="%y.%m.%d",
            automargin=True,
            hoverformat="<b>%y.%m.%d</b>",
            showspikes=True, spikemode="across", spikesnap="data",
            spikedash="dot", spikethickness=1, spikecolor="#9ca3af",
            rangebreaks=[dict(values=missing)] if missing else [],
            tickmode="array", tickvals=tickvals,
        ),
        legend=legend_cfg,
        hovermode="x unified",
        plot_bgcolor="rgba(0,0,0,0)",
        font=PLOTLY_FONT,
        hoverlabel=dict(
            bgcolor="white",
            bordercolor="#e5e7eb",
            font=dict(family="'Manrope', 'SUIT Variable', sans-serif", size=hover_font_size, color="#1e293b"),
        ),
    )
    return fig


def _resolve_returns_tickers(categories: list[str]) -> list[str]:
    """선택된 카테고리에 해당하는 티커 목록을 반환한다.

    벤치마크가 명시 선택되지 않은 경우, 비교를 위해 BDC→BIZD, 운용사→^GSPC 를 자동 보조 추가.
    """
    tickers: list[str] = []
    for cat in categories:
        tickers.extend(CATEGORY_TICKERS[cat])

    if "벤치마크" not in categories:
        if "BDC" in categories and "BIZD" not in tickers:
            tickers.append("BIZD")
        if "운용사" in categories and "^GSPC" not in tickers:
            tickers.append("^GSPC")
    return tickers


def render_hy_box(price_df: pd.DataFrame) -> None:
    """차트 1 — HY 스프레드 vs 미국 국채 금리 (단일 박스, 높이 BOX_HEIGHT)."""
    # 4개 박스 모두 동일 container wrapper 로 DOM 구조 통일
    with st.container(key="hy_title_row"):
        st.markdown(
            '<h5 style="margin:0;">'
            '<span class="material-symbols-rounded pcc-title-icon">percent</span> '
            '하이일드 스프레드 vs 미국 국채 금리</h5>',
            unsafe_allow_html=True,
        )
    with st.container(border=True, height=BOX_HEIGHT, key="box_hy"):
        if price_df.empty:
            st.info("가격 데이터가 없어 차트를 표시할 수 없습니다.")
            return
        has_indicators = price_df["ticker"].isin(
            ["BAMLH0A0HYM2", "DGS1", "DGS3", "DGS5"]
        ).any()
        if has_indicators:
            # 데스크톱(>768px) 1년치, 모바일(≤768px) 1개월치 두 버전을 렌더하고
            # CSS @media 로 viewport 에 맞는 것만 보이도록 토글.
            with st.container(key="hy_chart_desktop"):
                st.plotly_chart(
                    chart_indicator(price_df, days=365, mobile=False),
                    width="stretch", key="hy_chart_365",
                    config={"displayModeBar": False, "doubleClick": False, "scrollZoom": False},
                )
            with st.container(key="hy_chart_mobile"):
                st.plotly_chart(
                    chart_indicator(price_df, days=92, mobile=True),
                    width="stretch", key="hy_chart_92",
                    config={"displayModeBar": False, "doubleClick": False, "scrollZoom": False},
                )
                # 모바일 HTML 범례 — BDC 차트와 동일 스타일 (둥근 모서리, max-content 자동 폭, 중앙 정렬).
                # HY 스프레드: 솔리드 라인 / 1Y, 5Y: 점선 (chart_indicator 와 동일 시각 패턴)
                hy_color = COLOR_MAP["BAMLH0A0HYM2"]
                color_1y = COLOR_MAP.get("DGS1", "#5B92FF")
                color_5y = COLOR_MAP.get("DGS5", "#002060")
                st.markdown(
                    f"""
                    <div style="display:grid; grid-template-columns:max-content max-content max-content;
                                gap:6px 18px; justify-items:start; align-items:center;
                                width:max-content; margin:0 auto 0;
                                padding:6px 12px;
                                background:rgba(255,255,255,0.9);
                                border:1px solid #e5e7eb; border-radius:8px;
                                font-size:0.78rem; color:#374151;">
                      <span style="display:inline-flex; align-items:center; gap:6px; white-space:nowrap;">
                        <span style="display:inline-block; width:18px; height:2px; background:{hy_color}; flex:0 0 auto;"></span>
                        HY 스프레드
                      </span>
                      <span style="display:inline-flex; align-items:center; gap:6px; white-space:nowrap;">
                        <span style="display:inline-block; width:18px; height:0;
                                     border-top:2px dotted {color_1y}; flex:0 0 auto;"></span>
                        1Y
                      </span>
                      <span style="display:inline-flex; align-items:center; gap:6px; white-space:nowrap;">
                        <span style="display:inline-block; width:18px; height:0;
                                     border-top:2px dotted {color_5y}; flex:0 0 auto;"></span>
                        5Y
                      </span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.caption("거시지표 데이터(BAMLH0A0HYM2 / DGS1·3·5Y)가 아직 없습니다.")


def render_returns_box(price_df: pd.DataFrame) -> None:
    """차트 2 — BDC·운용사 누적 수익률 (단일 박스, 높이 BOX_HEIGHT).

    박스 안에 카테고리/기간 pills 토글 + 차트가 모두 들어감.
    """
    # 4개 박스 모두 동일 container wrapper 로 DOM 구조 통일
    with st.container(key="returns_title_row"):
        st.markdown(
            '<h5 style="margin:0;">'
            '<span class="material-symbols-rounded pcc-title-icon">trending_up</span> '
            'BDC 및 운용사 주가</h5>',
            unsafe_allow_html=True,
        )
    # 데스크톱은 BOX_HEIGHT(460) — News/SEC/HY 와 동일. 모바일은 CSS 로 height: auto 강제
    with st.container(border=True, height=BOX_HEIGHT, key="box_returns"):
        if price_df.empty:
            st.info("가격 데이터가 없어 차트를 표시할 수 없습니다.")
            return
        # 카테고리(좌) + 기간(우) 토글. 모바일은 CSS 로 stacked 강제.
        # ★ 카테고리 단일 선택 — BDC / 운용사 / 벤치마크 셋 중 하나만 활성.
        #   selection_mode="single" 로 Streamlit 이 자동으로 단일 선택 강제.
        ctrl_l, ctrl_r = st.columns([2, 3])
        with ctrl_l:
            with st.container(key="returns_category_box"):
                _category_selected = st.pills(
                    "카테고리",
                    options=list(CATEGORY_TICKERS.keys()),
                    selection_mode="single",
                    default="BDC",
                    key="returns_categories",
                    label_visibility="collapsed",
                )
                # downstream 함수들은 list 를 기대 — 단일 선택을 길이 1 리스트로 정규화
                categories = [_category_selected] if _category_selected else []
        with ctrl_r:
            with st.container(key="returns_period_box"):
                period = st.pills(
                    "기간",
                    options=PERIOD_OPTIONS,
                    selection_mode="single",
                    default="3개월",
                    key="returns_period",
                    label_visibility="collapsed",
                    format_func=_period_label,
                )

        period = period or "3개월"

        if not categories:
            st.warning("최소 한 그룹은 선택해야 합니다.")
            return

        tickers = _resolve_returns_tickers(categories)
        if not tickers:
            st.warning("최소 한 그룹은 선택해야 합니다.")
            return

        # 데스크톱·모바일 dual-render — CSS 로 viewport 별 노출 토글
        with st.container(key="returns_chart_desktop"):
            st.plotly_chart(
                chart_returns(price_df, tickers, period, mobile=False),
                width="stretch",
                config={"displayModeBar": False, "doubleClick": False, "scrollZoom": False},
                key="returns_chart_pc",
            )
        with st.container(key="returns_chart_mobile"):
            st.plotly_chart(
                chart_returns(price_df, tickers, period, mobile=True),
                width="stretch",
                height=240,
                config={"displayModeBar": False, "doubleClick": False, "scrollZoom": False},
                key="returns_chart_mb",
            )
            # 모바일 HTML 범례 — grid 2열 (각 컬럼 max-content 로 자동 폭), 중앙 정렬, 박스 폭도 콘텐츠에 맞춤
            legend_items = "".join([
                f'<span style="display:inline-flex; align-items:center; gap:6px; white-space:nowrap;">'
                f'<span style="display:inline-block; width:18px; height:2px; '
                f'background:{COLOR_MAP.get(t, "#999999")}; flex:0 0 auto;"></span>'
                f'<span>{get_ticker_label(t)}</span>'
                f'</span>'
                for t in tickers[:6]
            ])
            st.markdown(
                f"""
                <div style="display:grid; grid-template-columns:max-content max-content;
                            gap:6px 18px; justify-items:start;
                            width:max-content; margin:8px auto 0;
                            padding:6px 12px;
                            background:rgba(255,255,255,0.9);
                            border:1px solid #e5e7eb; border-radius:8px;
                            font-size:0.78rem; color:#374151;">
                  {legend_items}
                </div>
                """,
                unsafe_allow_html=True,
            )


# =============================================================================
# 3-B) 우측: 이벤트 보드
# =============================================================================

_PROMPT_ECHO_MARKERS = (
    "role: financial analyst",
    "financial analyst.",
    "task: extract",
    "extract key facts",
    "constraint 1:",
    "constraint 2:",
    "no reasoning, drafts",
    "summary (en):",
    "summary (kr):",
    "summary (en) and summary (kr)",
)


def _is_prompt_echo_head(s: str, n: int = 250) -> bool:
    """문자열 앞 n자가 colab 1차 LLM 의 prompt echo 패턴인지 검사."""
    if not s:
        return False
    head = s[:n].lower()
    return any(m in head for m in _PROMPT_ECHO_MARKERS)


def _filing_summary(row: pd.Series) -> str:
    """공시 요약: summary_kr → summary_en → extracted_json 순으로 폴백.

    한도 = LLM 목표(180) + 약 10% 여유. LLM 이 살짝 초과해도 잘리지 않게.
    extracted_json 폴백은 raw 라 길게 잘릴 수 있으므로 보다 작은 한도(180)로 cap.
    또한 raw 가 "LLM_OUTPUT_EMPTY" sentinel 이거나 prompt-echo 헤더로 시작하면
    빈 문자열 반환 — UI 에 garbage 노출 방지.
    """
    LIMIT_LLM_OUTPUT = 200
    LIMIT_RAW_FALLBACK = 180
    for col in ("summary_kr", "summary_en"):
        v = row.get(col)
        if isinstance(v, str) and v.strip():
            return truncate_text(v, LIMIT_LLM_OUTPUT)
    raw = row.get("extracted_json")
    if isinstance(raw, str) and raw.strip():
        raw_clean = raw.strip()
        if raw_clean == "LLM_OUTPUT_EMPTY":
            return ""
        if _is_prompt_echo_head(raw_clean):
            return ""
        return truncate_text(raw_clean, LIMIT_RAW_FALLBACK)
    return ""


# 박스 안에 미리보기로 노출할 항목 수 — 나머지는 "더보기" 모달에서 확인
SEC_PREVIEW_COUNT = 5
NEWS_PREVIEW_COUNT = 5


def _fmt_kpi(v, suffix: str = "", prefix: str = "") -> str:
    """KPI 값 포맷팅 — None/NaN 은 '—', 숫자는 prefix+소수 2자리+suffix."""
    if v is None:
        return "—"
    try:
        if pd.isna(v):
            return "—"
    except (TypeError, ValueError):
        pass
    try:
        return f"{prefix}{float(v):.2f}{suffix}"
    except (TypeError, ValueError):
        return str(v)


def _fmt_kpi_delta(curr, prev) -> str:
    """직전 분기 대비 증감 — '(▲ X.XX)' / '(▼ X.XX)' / '(—)' (변화 없음).
    prev 가 없으면 빈 문자열 (예: 첫 분기 데이터).
    """
    if curr is None or prev is None:
        return ""
    try:
        c = float(curr); p = float(prev)
        if pd.isna(c) or pd.isna(p):
            return ""
        d = c - p
    except (TypeError, ValueError):
        return ""
    if abs(d) < 0.005:
        return ' <span class="pcc-kpi-delta">(—)</span>'
    arrow = "▲" if d > 0 else "▼"
    return f' <span class="pcc-kpi-delta">({arrow} {abs(d):.2f})</span>'


def _render_sec_items(filings: pd.DataFrame) -> None:
    """SEC 공시 항목을 날짜 그룹 헤더와 함께 렌더 (박스/모달 공용).

    행에 `_periodic_kpi` (dict) 가 있으면 정기공시로 분기 — NAV/PIK/연체율을
    summary 자리에 표시. 없으면 기존 8-K 등의 LLM 요약 그대로.
    """
    is_first = True
    for d, group in filings.groupby(filings["filing_date"].dt.date, sort=False):
        header_style = ' style="margin-top:0"' if is_first else ''
        st.markdown(
            f'<div class="pcc-date-header"{header_style}>{_date_group_label(d)}</div>',
            unsafe_allow_html=True,
        )
        is_first = False
        for _, row in group.iterrows():
            form_label = get_form_label(row.get("form", ""))
            fund = row.get("fund_name", "")
            kpi = row.get("_periodic_kpi")
            if isinstance(kpi, dict):
                # 정기공시 — NAV / PIK / 연체율 표시
                pe = kpi.get("period_end")
                pe_str = pe.strftime("%Y-%m-%d") if hasattr(pe, "strftime") and pd.notna(pe) else ""
                title = form_label + (f" | {pe_str} 기준" if pe_str else "")
                desc = (
                    f"<span class='pcc-kpi-item'>주당 NAV "
                    f"<b>{_fmt_kpi(kpi.get('nav'), prefix='$')}</b>"
                    f"{_fmt_kpi_delta(kpi.get('nav'), kpi.get('nav_prev'))}</span>"
                    f"<span class='pcc-kpi-sep'>|</span>"
                    f"<span class='pcc-kpi-item'>PIK 지급 비중 "
                    f"<b>{_fmt_kpi(kpi.get('pik'), '%')}</b>"
                    f"{_fmt_kpi_delta(kpi.get('pik'), kpi.get('pik_prev'))}</span>"
                    f"<span class='pcc-kpi-sep'>|</span>"
                    f"<span class='pcc-kpi-item'>이자 미계상 자산 비율 "
                    f"<b>{_fmt_kpi(kpi.get('nonaccrual'), '%')}</b>"
                    f"{_fmt_kpi_delta(kpi.get('nonaccrual'), kpi.get('nonaccrual_prev'))}</span>"
                )
                st.markdown(
                    f"""
                    <div class="pcc-sec-item pcc-sec-periodic">
                      <div class="pcc-sec-name">{fund}</div>
                      <div class="pcc-headline">{title}</div>
                      <div class="pcc-desc pcc-kpi-desc">{desc}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                continue
            # 일반 (8-K 등)
            summary = _filing_summary(row)
            st.markdown(
                f"""
                <div class="pcc-sec-item">
                  <div class="pcc-sec-name">{fund}</div>
                  <div class="pcc-headline">{form_label}</div>
                  <div class="pcc-desc">{summary}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


@st.dialog("미국 SEC 공시 — 전체", width="large")
def _sec_modal(filings: pd.DataFrame) -> None:
    _render_sec_items(filings)


def render_sec_box(filings: pd.DataFrame, periodic: pd.DataFrame | None = None) -> None:
    # 4개 박스 모두 동일 container wrapper 로 DOM 구조 통일
    # markdown wrapper 들이 width:100% 로 펼쳐지도록 CSS 보조 (위 CSS 블록 참조).
    # 내부 div 를 display:flex 로 두어 h5(좌) + span(margin-left:auto, 우) 배치.
    with st.container(key="sec_title_row"):
        st.markdown(
            '<div style="display:flex; align-items:flex-end; width:100%;">'
            '<h5 style="margin:0;">'
            '<span class="material-symbols-rounded pcc-title-icon">account_balance</span> '
            '미국 SEC 공시</h5>'
            '<span style="margin-left:auto; font-size:0.95rem; color:#475569; '
            'transform:translateY(-11px);">미국 현지시간 기준</span>'
            '</div>',
            unsafe_allow_html=True,
        )
    # 화면 표시는 최근 14일만 (CSV 자체는 누적 그대로 보존)
    if not filings.empty and "filing_date" in filings.columns:
        max_date = filings["filing_date"].max()
        cutoff = max_date - pd.Timedelta(days=14)
        filings = filings[filings["filing_date"] >= cutoff]
    else:
        max_date = pd.Timestamp.now()
        cutoff = max_date - pd.Timedelta(days=14)

    # SEC_SKIP_FORMS 에 해당하는 form 은 화면 표시 제외 (옛 history 누적분 차단).
    # 정기공시(10-K/10-Q) 는 여기서 빠지지만 아래에서 periodic CSV 로 재주입 — KPI 와 함께.
    if not filings.empty and "form" in filings.columns:
        filings = filings[~filings["form"].astype(str).str.strip().isin(SEC_SKIP_FORMS)]

    # 정기공시 (10-K/10-Q) — filed_date 기준으로 8-K 등과 같은 박스에 KPI 와 함께 표시
    if periodic is not None and not periodic.empty:
        per = periodic[periodic["filed_date"] >= cutoff].copy()
        if not per.empty:
            per["filing_date"] = per["filed_date"]
            per["_periodic_kpi"] = per.apply(
                lambda r: {
                    "period_end": r.get("period_end"),
                    "nav": r.get("nav_per_share"),
                    "nav_prev": r.get("_prev_nav_per_share"),
                    "pik": r.get("pik_ratio_pct"),
                    "pik_prev": r.get("_prev_pik_ratio_pct"),
                    "nonaccrual": r.get("nonaccrual_pct"),
                    "nonaccrual_prev": r.get("_prev_nonaccrual_pct"),
                },
                axis=1,
            )
            filings = pd.concat([filings, per], ignore_index=True, sort=False)
            filings = filings.sort_values("filing_date", ascending=False).reset_index(drop=True)

    total = len(filings)
    preview = filings.head(SEC_PREVIEW_COUNT)
    remaining = total - len(preview)

    box = st.container(height=BOX_HEIGHT, border=True, key="box_sec")
    with box:
        if filings.empty:
            st.caption("표시할 공시가 없습니다.")
            return
        # 박스 안에는 최신 SEC_PREVIEW_COUNT 건만 — 전체는 "더보기" 모달
        _render_sec_items(preview)
        if remaining > 0:
            with st.container(key="sec_more_wrap"):
                if st.button(f"더보기 (+{remaining}건)", key="sec_more"):
                    _sec_modal(filings)


def _news_translated_or_original(row: pd.Series, kr_col: str, orig_col: str) -> tuple[str, bool]:
    """한국어 번역 컬럼이 있으면 그것을, 없으면 원문을 반환.

    TODO: 매일 파이프라인에 LLM 번역 추가 시 title_kr / summary_kr 컬럼이 채워지면
    별도 코드 변경 없이 자동으로 한국어가 표시된다.
    """
    val = row.get(kr_col)
    if isinstance(val, str) and val.strip():
        return val, True
    return (row.get(orig_col) or ""), False


_WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일"]


def _date_group_label(d: date) -> str:
    # 날짜만 표시 (오늘/어제 상대 표현 없이) — 배치 실행일과 표시일이 어긋날 수 있어 혼동 방지
    return f"{d.month}월 {d.day}일 ({_WEEKDAY_KR[d.weekday()]})"


def _news_tags(row: pd.Series, max_tags: int = 3) -> list[str]:
    """뉴스 태그 추출 — LLM 추출 llm_keywords 우선, 비어있으면 기존 matched_tags fallback.

    matched_tags 는 regex 기반 키워드 매칭이라 "stress" 같은 일반어가 과매칭되는 한계가
    있어 LLM 추출본으로 대체. 백필 안 된 과거 뉴스는 fallback 으로 매끄럽게 표시.
    """
    tags: list[str] = []
    llm_v = row.get("llm_keywords")
    if isinstance(llm_v, str) and llm_v.strip():
        for tok in llm_v.split(","):
            tok = tok.strip()
            if not tok or tok in tags:
                continue
            tags.append(tok)
            if len(tags) >= max_tags:
                return tags
        if tags:
            return tags

    # fallback: 구 matched_tags
    v = row.get("matched_tags")
    if not isinstance(v, str) or not v.strip():
        return tags
    for tok in v.split(","):
        tok = tok.strip().strip("_").replace("_", " ")
        if not tok or tok in tags:
            continue
        tags.append(tok)
        if len(tags) >= max_tags:
            return tags
    return tags


def _render_news_items(filtered: pd.DataFrame) -> None:
    """뉴스 항목을 날짜 그룹 헤더와 함께 렌더 (박스/모달 공용)."""
    is_first = True
    for d, group in filtered.groupby(filtered["published_at"].dt.date, sort=False):
        header_style = ' style="margin-top:0"' if is_first else ''
        st.markdown(
            f'<div class="pcc-date-header"{header_style}>{_date_group_label(d)}</div>',
            unsafe_allow_html=True,
        )
        is_first = False
        for _, row in group.iterrows():
            hhmm = row["published_at"].strftime("%H:%M")
            # 실데이터는 'link', 일부 샘플은 'url'
            url = row.get("link") or row.get("url") or ""

            is_overseas = row.get("region") == "해외"
            # 해외 뉴스: 영문 제목 그대로 + 국문 번역 요약
            # 국내 뉴스: 원래대로 (KR 컬럼 있으면 KR, 없으면 원문)
            if is_overseas:
                title = (row.get("title") or "").strip()
            else:
                title, _ = _news_translated_or_original(row, "title_kr", "title")
            summary, _ = _news_translated_or_original(row, "summary_kr", "summary")
            # 한도 = LLM 목표(140) + 10% 여유 — LLM 출력이 살짝 초과해도 잘리지 않게
            summary = truncate_text(summary, 160)

            tag_html = "".join(
                f'<span class="pcc-tag">{t}</span>' for t in _news_tags(row)
            )
            # 해외 뉴스 → "🌐 원문" (번역 적용 여부 무관), 국내 → "원문 ↗"
            link_text = "🌐 원문" if is_overseas else "원문 ↗"
            link_html = (
                f'<div class="pcc-news-link"><a href="{url}" target="_blank">{link_text}</a></div>'
                if isinstance(url, str) and url else '<div class="pcc-news-link"></div>'
            )
            st.markdown(
                f"""
                <div class="pcc-news-item">
                  <div class="pcc-news-time">{hhmm}</div>
                  <div class="pcc-news-body">
                    <div class="pcc-headline">{title}</div>
                    <div class="pcc-desc">{summary}</div>
                    <div>{tag_html}</div>
                  </div>
                  {link_html}
                </div>
                """,
                unsafe_allow_html=True,
            )


@st.dialog("국내외 뉴스 — 전체", width="large")
def _news_modal(filtered: pd.DataFrame) -> None:
    _render_news_items(filtered)


def render_news_box(news: pd.DataFrame) -> None:
    # 화면 표시는 최근 14일만 (CSV 자체는 누적 그대로 보존)
    if not news.empty and "published_at" in news.columns:
        cutoff = news["published_at"].max() - pd.Timedelta(days=14)
        news = news[news["published_at"] >= cutoff]

    # 제목 + region pills 를 같은 flex row 에 배치 — 제목 바로 옆에 토글 (AI 분석 뱃지 패턴)
    with st.container(key="news_title_row"):
        st.markdown("##### :material/newspaper: 국내외 뉴스")
        with st.container(key="news_region_box"):
            region = st.pills(
                "지역",
                options=["전체", "국내", "해외"],
                selection_mode="single",
                default="전체",
                key="news_region",
                label_visibility="collapsed",
            )
    region = region or "전체"
    filtered = news if region == "전체" else news[news["region"] == region]

    total = len(filtered)
    preview = filtered.head(NEWS_PREVIEW_COUNT)
    remaining = total - len(preview)

    # 박스 높이 — 모든 박스 동일 (BOX_HEIGHT)
    box = st.container(height=BOX_HEIGHT, border=True, key="box_news")
    with box:
        if filtered.empty:
            st.caption("표시할 뉴스가 없습니다.")
            return
        # 박스 안에는 최신 NEWS_PREVIEW_COUNT 건만 — 전체는 "더보기" 모달
        _render_news_items(preview)
        if remaining > 0:
            with st.container(key="news_more_wrap"):
                # region 필터에 따라 button key 도 달라야 재클릭이 동작
                if st.button(f"더보기 (+{remaining}건)", key=f"news_more_{region}"):
                    _news_modal(filtered)


def render_event_board(filings: pd.DataFrame, news: pd.DataFrame) -> None:
    render_news_box(news)
    render_sec_box(filings)


# =============================================================================
# 페이지 조립
# =============================================================================

def main() -> None:
    price_df = load_price_history()
    filings = load_sec_filings()
    periodic = load_periodic_kpi()
    news = load_news()

    render_header(price_df, news, filings)

    # ─── Plotly hover (모바일 툴팁 박스) 전역 dismiss 리스너 ───
    # 차트 안 탭: Plotly 기본 동작 (hover 표시) 유지.
    # 차트 박스 밖 다른 영역 탭 또는 스크롤: hover 자동 dismiss.
    import streamlit.components.v1 as components
    components.html(
        """
        <script>
        (function() {
            try {
                var p = parent;
                var doc = p.document;
                if (p.__plotlyDismissInstalled) return;
                p.__plotlyDismissInstalled = true;
                function dismissAllCharts() {
                    var charts = doc.querySelectorAll('.js-plotly-plot');
                    charts.forEach(function(c) {
                        if (p.Plotly && p.Plotly.Fx && p.Plotly.Fx.hover) {
                            try { p.Plotly.Fx.hover(c, []); } catch(_) {}
                        }
                    });
                }
                function onTap(e) {
                    var t = e.target;
                    // 탭이 어떤 차트 컨테이너 안이면 native 동작 유지 (간섭 X)
                    if (t && t.closest && t.closest('.js-plotly-plot')) return;
                    // 차트 밖이면 모든 hover dismiss
                    dismissAllCharts();
                }
                doc.addEventListener('click', onTap, true);
                doc.addEventListener('touchend', onTap, true);
                doc.addEventListener('scroll', dismissAllCharts, true);
            } catch (err) { /* cross-origin 등 — 무시 */ }
        })();
        </script>
        """,
        height=0,
    )

    # ─── Row 1 · Risk Level | Risk 추이 + 한 줄 요약 ───
    render_summary(price_df)
    st.markdown("")  # spacing

    # ─── Rows 2-3 wrapper · 모바일에서 column-major 재배치 가능 (HY → BDC → News → SEC) ───
    with st.container(key="grid_charts_events"):
        # ─── Row 2 · 하이일드 스프레드 vs 국채 금리 | 국내외 뉴스 ───
        r2c1, r2c2 = st.columns(2, gap="small")
        with r2c1:
            render_hy_box(price_df)
        with r2c2:
            render_news_box(news)

        # ─── Row 3 · BDC 및 운용사 주가 | 미국 SEC 공시 ───
        r3c1, r3c2 = st.columns(2, gap="small")
        with r3c1:
            render_returns_box(price_df)
        with r3c2:
            render_sec_box(filings, periodic)

if __name__ == "__main__":
    main()
