"""사모신용 카나리아 모니터링 — Streamlit 대시보드.

Phase 6 (UI 골격) + Phase 2.1 수정사항 반영. 데이터는 data/ 폴더의 CSV 를 읽으며,
점수/총평 등 일부 영역은 추후 Phase 7~8 에서 채워진다.
"""

from __future__ import annotations

import contextlib
import io
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

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


@st.cache_data(ttl=86400, show_spinner=False)
def _auto_score_risk() -> dict:
    """리스크 종합점수 자동 산출 (24시간 캐시 — LLM 호출 비용 절약).

    매 새로고침마다 LLM 호출하면 quota 빨리 소진되므로 24h 캐시.
    start_dashboard.bat 에서 [4/5] 단계로 정식 실행되며,
    이 함수는 streamlit 만 단독 실행 시의 안전망 역할.
    """
    try:
        from score_risk import daily_pipeline  # type: ignore[import-not-found]
        with contextlib.redirect_stdout(io.StringIO()):
            return daily_pipeline()
    except Exception as exc:  # noqa: BLE001
        print(f"[auto_score] 실패: {exc}")
        return {}


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


# Preview: score_risk 자동 호출 비활성화 — JSON 의 기존 점수만 읽어 표시 (LLM 재호출 X)
# _auto_score_risk()

COLOR_MAP = {
    # BDC (5개) — 운용사 색상의 옅은 톤. 실제 모/자 관계로 매칭.
    "OBDC": "#BBDAF6",     # Blue Owl BDC      → 옅은 블루   (OWL 모회사와 같은 톤)
    "OTF":  "#B7EAD9",     # Blue Owl Tech BDC → 옅은 그린   (OBDC 와 시각적 구분)
    "BXSL": "#DCCEFC",     # Blackstone BDC    → 옅은 보라   (BX 모회사와 같은 톤)
    "ARCC": "#FCC5CF",     # Ares BDC          → 옅은 핑크   (ARES 모회사와 같은 톤)
    "FSK":  "#FCE2B6",     # FS KKR BDC        → 옅은 오렌지 (KKR 모회사와 같은 톤)

    # 운용사 (5개) — 짙은 톤
    "OWL":  "#479BE7",     # Blue Owl       — 블루
    "BX":   "#A079F7",     # Blackstone     — 보라
    "ARES": "#F65473",     # Ares           — 핑크/레드
    "APO":  "#5ED0AA",     # Apollo         — 그린
    "KKR":  "#F8B74E",     # KKR            — 오렌지

    # 벤치마크 — 기존 톤 유지
    "BIZD": "#808080", "^GSPC": "#bdbdbd", "HYG": "#525252",
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
    "424B3":    "투자설명서 수정",
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
    # 대량보유 / 내부자
    "SC 13D":   "대량보유 보고 (적극적)",
    "SC 13D/A": "대량보유 보고 정정",
    "SC 13G":   "대량보유 보고 (수동)",
    "SC 13G/A": "대량보유 보고 정정",
    "SC TO-T":  "공개매수신고",
    "SC TO-I":  "자기주식 공개매수신고",
    "SC TO-T/A":"공개매수신고 정정",
    "SC TO-I/A":"자기주식 공개매수신고 정정",
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
    "485BPOS":  "투자설명서 사후 수정",
    "485APOS":  "투자설명서 사전 수정",
    "486BPOS":  "486(b) 사후 발효 수정",
    "486APOS":  "486(a) 사전 발효 수정",
    # 등록 사후
    "POS AM":   "등록신고서 사후 수정",
    "POS EX":   "등록 서류 정정",
    "POS 8C":   "투자회사 사후 수정",
    "EFFECT":   "등록 효력 발생",
    "RW":       "등록 철회 요청",
    "RW WD":    "철회 요청 철회",
    "40-APP":   "투자회사 신청서",
    "40-APP/A": "투자회사 신청서 정정",
    "40-OIP":   "투자회사 면제 신청",
    "40-17G":   "연간 보증보험 공시",
    "40-33":    "주주 대위소송 보고",
    "N-2":      "투자회사 등록",
    "N-2/A":    "투자회사 등록 정정",
    # 직원 복지 / 공개매수 통신
    "S-8":      "직원 복지 등록",
    "S-8 POS":  "직원 복지 등록 사후 수정",
    "SC TO-C":  "공개매수 관련 통신",
    "SC 13E3":  "비공개 전환 거래 공시",
    "PX14A6G":  "비요청 위임 권유 통지",
}

TICKER_KR_NAMES = {
    # 상장형 BDC
    "OBDC":  "Blue Owl",
    "OTF":   "Blue Owl Tech",
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
    "1주": 7,
    "1개월": 31,
    "3개월": 92,
    "6개월": 183,
    "1년": 365,
}
PERIOD_OPTIONS = ["1주", "1개월", "3개월", "6개월", "1년", "연초이후"]

# 대시보드 표시 제외 SEC form — 코랩 SKIP_FORMS 와 동일한 목록.
# 기존 history.csv 에 누적된 옛 데이터도 화면에서는 안 보이도록 필터.
SEC_SKIP_FORMS = {
    "10-K", "10-Q", "10-K/A", "10-Q/A",  # 정기공시 (별도 처리)
    "S-8", "S-8 POS",                    # 직원 보상
    "RW", "RW WD",                       # 등록 철회
    "FWP",                               # 자유 작성 투자설명서
    "ARS",                               # 주주용 연차보고서 PDF
    "N-CSR", "N-CSRS",                   # 펀드 연·반기 보고서
    "486APOS", "486BPOS",                # 486 사전·사후 발효 수정 (장문 등록서류)
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

# Plotly 차트 공통 폰트 (Pretendard) — update_layout 시 font=PLOTLY_FONT 로 적용
# Preview: size 14 → 17 (+3, ≈ 2단계 확대)
PLOTLY_FONT = dict(
    family="'Pretendard', -apple-system, BlinkMacSystemFont, sans-serif",
    size=17,
    color="#374151",
)

st.set_page_config(
    page_title="사모신용 카나리아 모니터링 (Preview — 더보기 모달)",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
        /* ★ Preview — 모든 rem 기반 폰트 +20% 확대 (≈ 2단계 키움) */
        html { font-size: 19.2px; }

        /* Pretendard 웹폰트 — jsDelivr CDN */
        @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css');

        /* Material Symbols (픽토그램) — 제목 옆 라인 아이콘 */
        @import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@24,400,0,0&display=swap');
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

        /* 전역 폰트 — Pretendard 단독 (모던 핀테크) */
        html, body, [class*="css"], [class*="st-"] {
            font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
        }

        /* Preview: 상단 여백 (3rem → 3.5rem) — 헤더가 약간 아래에서 시작 */
        .block-container {
            padding-top: 3.5rem;
            padding-bottom: 2rem;
            padding-left: 1.5rem !important;
            padding-right: 1.5rem !important;
            max-width: 100% !important;
        }
        /* 좌·우 컬럼 간격 좁혀 박스가 화면 중앙으로 모이도록 */
        [data-testid="stHorizontalBlock"] {
            gap: 0.75rem !important;
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
        /* Preview: divider 의 위·아래 여백 압축 */
        [data-testid="stMainBlockContainer"] hr,
        [data-testid="stHorizontalRule"] {
            margin: 4px 0 !important;
        }
        .pcc-header .pcc-title {
            font-size: 1.6rem; font-weight: 700; color: #0f172a;
            white-space: nowrap; flex: 0 0 auto;
        }
        .pcc-header .pcc-update {
            /* Preview: 다른 폰트는 +20% 확대됐지만 last update 만은 app.py 와 동일 (18.4px = 1.15rem × 16) */
            color: #475569; font-size: 18.4px; white-space: nowrap; flex: 0 0 auto;
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
        /* 헤드라인 — 뉴스 제목 / SEC form 라벨 모두 동일 양식 (볼드) */
        .pcc-headline { font-weight: 600; color: #0f172a; font-size: 1.13rem; line-height: 1.45; }
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
            font-size: 1.35rem;
            transform: translateX(3px);     /* 우측 3px 이동 */
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
            content: "모니터링 대상:";
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
            content: "적용기간:";
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
        /* 중간 wrapper (stVerticalBlock 등) 를 투명화 → grandchild 들이 직접 flex 자식이 됨 */
        .st-key-news_title_row > div,
        .st-key-news_title_row > [data-testid="stVerticalBlock"] {
            display: contents !important;
        }
        /* pills 컨테이너 — flex center 정렬 (translateY 제거) */
        .st-key-news_region_box {
            flex-shrink: 0;
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

        /* ─── "더보기" 모달 버튼 — AI 분석 뱃지 톤 (indigo pill, 박스 가운데) ─── */
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
        /* stButton wrapper 를 flex row + center 로 만들어 버튼을 박스 X축 가운데에 위치 */
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
            font-size: 0.85rem !important;
            font-weight: 600 !important;
            padding: 5px 16px !important;
            min-height: 0 !important;
            width: auto !important;
            flex: 0 0 auto !important;
            transition: background-color 0.15s ease, border-color 0.15s ease;
        }
        .st-key-sec_more_wrap button:hover,
        .st-key-news_more_wrap button:hover {
            background-color: #e0e7ff !important;
            border-color: #a5b4fc !important;
            color: #3730a3 !important;
        }
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

        /* ─── 모바일 (≤768px) — 컬럼 강제 세로 스택 + 글자 크기 / 레이아웃 최적화 ─── */
        @media (max-width: 768px) {
            /* 1) 컬럼 세로 스택 */
            [data-testid="stHorizontalBlock"] {
                flex-direction: column !important;
                gap: 12px !important;
            }
            [data-testid="stColumn"] {
                width: 100% !important;
                flex: 1 1 100% !important;
                min-width: 0 !important;
            }
            .block-container {
                padding-left: 0.75rem !important;
                padding-right: 0.75rem !important;
            }

            /* 2) 박스 높이 — 콘텐츠 자동 (고정 460 해제) */
            [data-testid="stVerticalBlockBorderWrapper"] {
                height: auto !important;
                min-height: 360px;
                padding: 12px 14px !important;
            }

            /* 3) 헤더 */
            .pcc-header {
                flex-wrap: wrap;
                gap: 6px;
                padding: 4px 0 6px 0;
            }
            .pcc-header .pcc-title {
                font-size: 1.2rem;
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
            /* BDC 차트 카테고리·기간 pills — 모바일에선 줄바꿈 허용 */
            .st-key-returns_period_box,
            .st-key-returns_category_box {
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
            /* 행 컨테이너를 투명하게 — 자식(stColumn) 이 wrapper 의 직접 flex 자식으로 동작 */
            .st-key-grid_charts_events [data-testid="stHorizontalBlock"] {
                display: contents !important;
            }
            /* margin-top 해제 (PC 용) */
            .st-key-grid_charts_events [data-testid="stHorizontalBlock"]:not(:first-child) {
                margin-top: 0 !important;
            }
            /* :has() 로 박스 식별해서 order 지정 (Chrome 105+, 2022~) */
            .st-key-grid_charts_events [data-testid="stColumn"]:has(.st-key-box_hy)      { order: 1; }
            .st-key-grid_charts_events [data-testid="stColumn"]:has(.st-key-box_returns) { order: 2; }
            .st-key-grid_charts_events [data-testid="stColumn"]:has(.st-key-box_news)    { order: 3; }
            .st-key-grid_charts_events [data-testid="stColumn"]:has(.st-key-box_sec)     { order: 4; }
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
    """모든 데이터 소스의 최신 날짜 중 가장 늦은 값 (= 파이프라인 마지막 실행 시점).

    가격(주가/지표)은 직전 영업일까지, 뉴스/공시는 당일 오전까지 수집되는 경우가 많아
    파이프라인 갱신 시점을 한눈에 보여주려면 이 셋의 max 가 자연스럽다.
    """
    candidates: list[date] = []
    if price_df is not None and not price_df.empty and "base_dt" in price_df.columns:
        candidates.append(price_df["base_dt"].max().date())
    if news_df is not None and not news_df.empty and "published_at" in news_df.columns:
        candidates.append(news_df["published_at"].max().date())
    if filings_df is not None and not filings_df.empty and "filing_date" in filings_df.columns:
        candidates.append(filings_df["filing_date"].max().date())
    return max(candidates) if candidates else None


def render_header(
    price_df: pd.DataFrame,
    news_df: pd.DataFrame | None = None,
    filings_df: pd.DataFrame | None = None,
) -> None:
    last_update = _last_update_date(price_df, news_df, filings_df)
    last_str = last_update.strftime("%y.%m.%d") if last_update is not None else "데이터 없음"

    # flex 레이아웃 + white-space:nowrap 으로 어떤 폭에서도 제목이 잘리지 않도록.
    st.markdown(
        f"""
        <div class="pcc-header">
          <div class="pcc-title">사모신용 카나리아 모니터링</div>
          <div class="pcc-update">Last Update: {last_str}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if price_df.empty:
        st.warning("가격 시계열을 불러오지 못했습니다. data/ 폴더의 CSV 형식을 확인하세요.")
    st.divider()


# =============================================================================
# 2) 요약 (리스크 점수 / 일일 총평)
# =============================================================================

# 첨부 이미지의 5단계 색상 팔레트 — 외측(진한)·내측(연한)·pill 표시색
_RISK_PALETTE = [
    # (상한 미만, 라벨, 외측, 내측, pill)
    (20,  "Very Low",  "#1B7C3A", "#93C9A4", "#1B7C3A"),
    (40,  "Low",       "#86C39C", "#CCE7D6", "#5BAE76"),
    (60,  "Moderate",  "#D1D5DB", "#E5E7EB", "#94A3B8"),
    (80,  "High",      "#F2A6A4", "#F8D5D3", "#E26B6B"),
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
    labels = [p[1] for p in _RISK_PALETTE]
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
        # pill+score 줄여서 게이지 높이 확보 (290 → 305)
        height=305,
        margin=dict(l=20, r=20, t=24, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
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


def _risk_trend(score_today: float, end_date: date | None = None) -> go.Figure:
    """최근 1개월 리스크 종합점수 추이 — 그라데이션 영역 차트.

    end_date 기준으로 미국 영업일 30일 시계열 생성 (주말 + 미국 연방 휴일 제외).
    None 이면 시스템 today 사용.

    TODO: Phase 8 — 실제 일별 점수 시계열 연결. 현재는 시각 확인용 mock.
    """
    import random
    from pandas.tseries.holiday import USFederalHolidayCalendar
    from pandas.tseries.offsets import CustomBusinessDay

    if end_date is None:
        end_date = date.today()
    # 미국 영업일 30일치 dates 생성 (주말 + 연방 휴일 모두 제외)
    end = pd.Timestamp(end_date)
    us_bd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
    bdates = pd.date_range(end=end, periods=30, freq=us_bd)
    dates = [d.date() for d in bdates]

    rng = random.Random(7)
    val = 55.0
    series: list[float] = []
    for _ in range(29):
        val += rng.gauss(0, 4.5)
        val = max(20.0, min(95.0, val))
        series.append(round(val, 1))
    series.append(float(score_today))  # 마지막 점 = 오늘 점수 (게이지와 동일 값)

    fig = go.Figure(
        go.Scatter(
            x=dates, y=series,
            mode="lines+markers",
            # ① 곡선 (spline 스무딩)
            line=dict(color="#DC2626", width=2.5, shape="spline", smoothing=1.0),
            # ② 흰색 채움 + 테두리 컬러 마커
            marker=dict(
                symbol="circle",
                size=7,
                color="white",
                line=dict(color="#DC2626", width=2),
            ),
            fill="tozeroy",
            fillcolor="rgba(220, 38, 38, 0.12)",
            # ③ hover: 날짜 + "리스크 점수: XX점"
            hovertemplate="<b>%{x|%y.%m.%d}</b><br>리스크 점수: %{y:.0f}점<extra></extra>",
        )
    )
    fig.update_layout(
        # 박스 460 - 제목 30 - "한줄요약" 영역(110) - padding 30 ≈ 290 가용 → 차트 220
        height=220,
        margin=dict(l=8, r=8, t=10, b=10),
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
            font=dict(family="'Pretendard', sans-serif", size=16, color="#1e293b"),
        ),
    )
    return fig


# 모든 박스 동일 사이즈 — 2열 × 3행 그리드 공통 높이
BOX_HEIGHT = 460
_SUMMARY_CARD_HEIGHT = BOX_HEIGHT


def render_summary(price_df: pd.DataFrame | None = None) -> None:
    # 좌·우 1:1 균등 (preview 레이아웃과 동일)
    left, right = st.columns(2, gap="small")

    # 종합 점수 — score_risk.py 가 만든 JSON 에서 로드. 없으면 중립 50.
    risk_history = _load_risk_score()
    composite = risk_history.get("composite", {})
    score = float(composite.get("composite_score", 50.0))
    # 한 줄 요약 — Synthesis Agent 가 3 카테고리 통합한 결과 (음슴체)
    composite_insight = composite.get("summary_insight", "").strip()

    # 추이 차트 마지막 점 = 시스템 today (점수 자체가 오늘 산출이므로 차트 x축도 오늘로 통일)
    end_date = date.today()

    with left:
        with st.container(border=True, height=_SUMMARY_CARD_HEIGHT):
            # h5 마크다운으로 다른 카드 제목과 사이즈 통일, 가운데 정렬은 CSS 로
            with st.container(key="risk_level_title"):
                st.markdown("##### Risk Level")
            st.plotly_chart(
                _risk_gauge(score),
                width="stretch",
                config={"displayModeBar": False},
            )
            level, color = _risk_level(score)
            # pill 박스 살짝 줄임 (padding·font 축소) → 게이지 위쪽 여유 확보
            st.markdown(
                f'<div style="text-align:center; margin-top:-4px;">'
                f'<span style="display:inline-block; background:{color}; color:white; '
                f'padding:6px 32px; border-radius:20px; font-weight:600; font-size:1.1rem;">'
                f'{level}</span>'
                f'<div style="margin-top:8px; color:#475569; font-weight:600; font-size:1.1rem;">'
                f'{int(round(score))} / 100</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    with right:
        with st.container(border=True, height=_SUMMARY_CARD_HEIGHT):
            st.markdown("##### :material/insights: 최근 1개월 리스크 종합점수 추이")
            st.plotly_chart(
                _risk_trend(score, end_date=end_date),
                width="stretch",
                config={"displayModeBar": False},
            )
            # 추이 차트 ↔ 한 줄 요약 간격
            st.markdown('<div style="height: 20px;"></div>', unsafe_allow_html=True)

            # 제목 + AI 분석 뱃지 (제목 우측 3px 공백 후, baseline 동일 라인)
            st.markdown(
                """
                <div style="display:flex; align-items:baseline; gap:1px; margin-bottom:6px;">
                    <h5 style="margin:0;">
                      <span class="material-symbols-rounded pcc-title-icon">lightbulb</span>
                      오늘의 시장 한 줄 요약
                    </h5>
                    <span style="display:inline-flex; align-items:center; gap:4px;
                                 background:#eef2ff; color:#4338ca;
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
            if composite_insight:
                st.markdown(
                    f'<div style="font-size:1.25rem; color:#1e293b; line-height:1.65; '
                    f'padding:0 0 0 8px; word-break:keep-all; overflow-wrap:break-word;">'
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

    rangebreaks 적용 후 Plotly 자동 tick 이 들쭉날쭉할 때 명시적으로 지정해서 일정 간격 확보.
    """
    sorted_dates = sorted(date_list)
    if len(sorted_dates) <= n:
        return sorted_dates
    step = (len(sorted_dates) - 1) / (n - 1)
    return [sorted_dates[round(i * step)] for i in range(n)]


def chart_indicator(price_df: pd.DataFrame) -> go.Figure:
    # 화면 표시는 최근 1년만 (CSV 자체는 누적 그대로 보존)
    if not price_df.empty:
        cutoff = price_df["base_dt"].max() - pd.Timedelta(days=365)
        price_df = price_df[price_df["base_dt"] >= cutoff]

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    hy = price_df[price_df["ticker"] == "BAMLH0A0HYM2"].sort_values("base_dt")

    if not hy.empty:
        # FRED 의 BAMLH0A0HYM2 는 percent 단위(예: 2.86 = 2.86%) — 표시도 % 로 통일
        hy_color = COLOR_MAP["BAMLH0A0HYM2"]
        fig.add_trace(
            go.Scatter(
                x=hy["base_dt"], y=hy["close"],
                name="HY 스프레드 (%)",
                mode="lines",
                line=dict(color=hy_color, width=2, shape="spline", smoothing=1.0),
                hovertemplate="HY 스프레드 · %{y:.2f}%<extra></extra>",
            ),
            secondary_y=False,
        )

    # 미국 국채 금리 — 1Y / 3Y / 5Y 모두 우측 Y축에 표시. 범례명은 짧게.
    for tk, label in [("DGS1", "1Y"), ("DGS3", "3Y"), ("DGS5", "5Y")]:
        df_t = price_df[price_df["ticker"] == tk].sort_values("base_dt")
        if df_t.empty:
            continue
        tk_color = COLOR_MAP.get(tk, "#999999")
        fig.add_trace(
            go.Scatter(
                x=df_t["base_dt"], y=df_t["close"],
                name=label,
                mode="lines",
                line=dict(color=tk_color, width=2, shape="spline", smoothing=1.0),
                hovertemplate=label + " · %{y:.2f}%<extra></extra>",
            ),
            secondary_y=True,
        )

    # 양쪽 y축 모두 소수점 1자리 강제 (3 → 3.0, 4 → 4.0)
    fig.update_yaxes(title_text="HY 스프레드 (%)", secondary_y=False,
                      color=COLOR_MAP["BAMLH0A0HYM2"], tickformat=".1f")
    fig.update_yaxes(title_text="미국 국채 금리 (%)", secondary_y=True, tickformat=".1f")
    fig.update_layout(
        # 박스 460 - 제목 38(타이틀 row) - padding 30 ≈ 392 가용 → 차트 380
        height=380,
        margin=dict(l=10, r=10, t=24, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        plot_bgcolor="white",
        font=PLOTLY_FONT,
        hoverlabel=dict(
            bgcolor="white",
            bordercolor="#e5e7eb",
            font=dict(family="'Pretendard', sans-serif", size=16, color="#1e293b"),
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
    return end - timedelta(days=PERIOD_DAYS[period])


def chart_returns(price_df: pd.DataFrame, tickers: list[str], period: str) -> go.Figure:
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
        # 곡선(spline) — 깔끔하게 lines 만 (markers 제거)
        fig.add_trace(
            go.Scatter(
                x=df_t["base_dt"], y=pct, mode="lines", name=label,
                customdata=pct_formatted,
                line=dict(color=color, width=2.5, shape="spline", smoothing=1.0),
                hovertemplate=label + " · %{customdata}%<extra></extra>",
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

    fig.update_layout(
        # 박스 460 - 카테고리 pills(40) - 기간 pills(40) - padding(30) ≈ 350 가용 → 차트 320
        # top 마진 늘려서 unified tooltip 이 spike 에 너무 붙지 않게 여유 확보 (HY 차트와 통일)
        height=320,
        margin=dict(l=10, r=10, t=40, b=10),
        # autorange 가 데이터 min/max 에 맞춰 자동 조정 → 기간 토글 시 y축 변화
        yaxis=dict(title="누적 수익률 (%)", ticksuffix="%", gridcolor="#eef0f3", autorange=True, hoverformat=".2f"),
        xaxis=dict(
            showgrid=False, tickformat="%y.%m.%d",
            # unified hover 상단의 날짜 표시 — HTML <b> 태그로 굵게
            hoverformat="<b>%y.%m.%d</b>",
            # spike line 이 데이터 포인트에 snap — cursor 좌우 이동 시 다음 포인트로 점프
            showspikes=True, spikemode="across", spikesnap="data",
            spikedash="dot", spikethickness=1, spikecolor="#9ca3af",
            # 데이터에 없는 날짜 (주말·휴일) 모두 숨김
            rangebreaks=[dict(values=missing)] if missing else [],
            # 균등 간격 tick 강제
            tickmode="array", tickvals=tickvals,
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        plot_bgcolor="white",
        font=PLOTLY_FONT,
        hoverlabel=dict(
            bgcolor="white",
            bordercolor="#e5e7eb",
            font=dict(family="'Pretendard', sans-serif", size=16, color="#1e293b"),
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
            st.plotly_chart(chart_indicator(price_df), width="stretch")
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
    with st.container(border=True, height=BOX_HEIGHT, key="box_returns"):
        if price_df.empty:
            st.info("가격 데이터가 없어 차트를 표시할 수 없습니다.")
            return
        # 카테고리(좌) + 기간(우) 토글. 기본 표시 기간은 차트 1과 동일하게 1년.
        ctrl_l, ctrl_r = st.columns([2, 3])
        with ctrl_l:
            with st.container(key="returns_category_box"):
                categories = st.pills(
                    "카테고리",
                    options=list(CATEGORY_TICKERS.keys()),
                    selection_mode="multi",
                    default=["BDC"],
                    key="returns_categories",
                    label_visibility="collapsed",
                )
        with ctrl_r:
            with st.container(key="returns_period_box"):
                period = st.pills(
                    "기간",
                    options=PERIOD_OPTIONS,
                    selection_mode="single",
                    default="1개월",
                    key="returns_period",
                    label_visibility="collapsed",
                )

        period = period or "1개월"

        if not categories:
            st.warning("최소 한 그룹은 선택해야 합니다.")
            return

        tickers = _resolve_returns_tickers(categories)
        if not tickers:
            st.warning("최소 한 그룹은 선택해야 합니다.")
            return

        st.plotly_chart(chart_returns(price_df, tickers, period), width="stretch")


# =============================================================================
# 3-B) 우측: 이벤트 보드
# =============================================================================

def _filing_summary(row: pd.Series) -> str:
    """공시 요약: summary_kr → summary_en → extracted_json 순으로 폴백.

    한도 = LLM 목표(180) + 약 10% 여유. LLM 이 살짝 초과해도 잘리지 않게.
    extracted_json 폴백은 raw 라 길게 잘릴 수 있으므로 보다 작은 한도(180)로 cap.
    """
    LIMIT_LLM_OUTPUT = 200
    LIMIT_RAW_FALLBACK = 180
    for col in ("summary_kr", "summary_en"):
        v = row.get(col)
        if isinstance(v, str) and v.strip():
            return truncate_text(v, LIMIT_LLM_OUTPUT)
    raw = row.get("extracted_json")
    if isinstance(raw, str) and raw.strip():
        return truncate_text(raw, LIMIT_RAW_FALLBACK)
    return ""


# 박스 안에 미리보기로 노출할 항목 수 — 나머지는 "더보기" 모달에서 확인
SEC_PREVIEW_COUNT = 5
NEWS_PREVIEW_COUNT = 5


def _render_sec_items(filings: pd.DataFrame) -> None:
    """SEC 공시 항목을 날짜 그룹 헤더와 함께 렌더 (박스/모달 공용)."""
    for d, group in filings.groupby(filings["filing_date"].dt.date, sort=False):
        st.markdown(
            f'<div class="pcc-date-header">{_date_group_label(d)}</div>',
            unsafe_allow_html=True,
        )
        for _, row in group.iterrows():
            form_label = get_form_label(row.get("form", ""))
            fund = row.get("fund_name", "")
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


def render_sec_box(filings: pd.DataFrame) -> None:
    # 4개 박스 모두 동일 container wrapper 로 DOM 구조 통일
    with st.container(key="sec_title_row"):
        st.markdown(
            '<h5 style="margin:0;">'
            '<span class="material-symbols-rounded pcc-title-icon">account_balance</span> '
            '미국 SEC 공시</h5>',
            unsafe_allow_html=True,
        )
    # 화면 표시는 최근 14일만 (CSV 자체는 누적 그대로 보존)
    if not filings.empty and "filing_date" in filings.columns:
        cutoff = filings["filing_date"].max() - pd.Timedelta(days=14)
        filings = filings[filings["filing_date"] >= cutoff]

    # SEC_SKIP_FORMS 에 해당하는 form 은 화면 표시 제외 (옛 history 누적분 차단)
    if not filings.empty and "form" in filings.columns:
        filings = filings[~filings["form"].astype(str).str.strip().isin(SEC_SKIP_FORMS)]

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
    today = date.today()
    diff = (today - d).days
    body = f"{d.month}월 {d.day}일 ({_WEEKDAY_KR[d.weekday()]})"
    if diff == 0:
        return f"오늘 · {body}"
    if diff == 1:
        return f"어제 · {body}"
    return body


def _news_tags(row: pd.Series, max_tags: int = 2) -> list[str]:
    """matched_tags / search_keyword 에서 짧은 토큰 추출."""
    tags: list[str] = []
    for col in ("matched_tags", "search_keyword"):
        v = row.get(col)
        if not isinstance(v, str) or not v.strip():
            continue
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
    for d, group in filtered.groupby(filtered["published_at"].dt.date, sort=False):
        st.markdown(
            f'<div class="pcc-date-header">{_date_group_label(d)}</div>',
            unsafe_allow_html=True,
        )
        for _, row in group.iterrows():
            hhmm = row["published_at"].strftime("%H:%M")
            # 실데이터는 'link', 일부 샘플은 'url'
            url = row.get("link") or row.get("url") or ""

            title, _ = _news_translated_or_original(row, "title_kr", "title")
            summary, _ = _news_translated_or_original(row, "summary_kr", "summary")
            # 한도 = LLM 목표(140) + 10% 여유 — LLM 출력이 살짝 초과해도 잘리지 않게
            summary = truncate_text(summary, 160)

            tag_html = "".join(
                f'<span class="pcc-tag">{t}</span>' for t in _news_tags(row)
            )
            # 해외 뉴스 → "🌐 원문" (번역 적용 여부 무관), 국내 → "원문 ↗"
            is_overseas = row.get("region") == "해외"
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
    news = load_news()

    render_header(price_df, news, filings)

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
            render_sec_box(filings)


if __name__ == "__main__":
    main()
