"""디자인 미리보기 — 모든 박스 동일 크기 + 큰 폰트 버전.

본 app.py 는 그대로 두고 시각 비교용으로만 사용. 데이터는 mock.
실행:
    venv\\Scripts\\streamlit.exe run app_preview.py --server.port 8503
"""

from __future__ import annotations

import random
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

# ============================================================================
# 페이지 + 모던 테마 CSS  (★ 폰트 전반 확대, 박스 동일 사이즈)
# ============================================================================

st.set_page_config(
    page_title="사모신용 카나리아 모니터링 (Preview)",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# 전체 박스 공통 사이즈
BOX_HEIGHT = 460

st.markdown(
    """
    <style>
        /* ─── Google Fonts ─── */
        @import url('https://cdn.jsdelivr.net/gh/spoqa/spoqa-han-sans@latest/css/SpoqaHanSansNeo.css');
        @import url('https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;500;600;700&display=swap');

        /* ─── 전역 폰트·배경 ─── (버전 4: Spoqa Han Sans Neo + Source Sans 3 — 부드러운 컨설팅) */
        html, body, [class*="css"], [class*="st-"] {
            font-family: 'Source Sans 3', 'Spoqa Han Sans Neo', sans-serif !important;
        }
        body { background: #f6f7f9; }
        .block-container {
            padding-top: 1.6rem;
            padding-bottom: 2.5rem;
            padding-left: 1.5rem !important;
            padding-right: 1.5rem !important;
            max-width: 100% !important;
        }
        /* 좌우 컬럼 간격 좁히기 */
        [data-testid="stHorizontalBlock"] {
            gap: 0.75rem !important;
        }

        /* ─── 헤더 ─── */
        .pv-header {
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            padding: 6px 0 18px 0;
            margin-bottom: 28px;
            border-bottom: 1px solid #e5e7eb;
        }
        .pv-header .pv-title {
            font-size: 2.0rem;
            font-weight: 700;
            color: #0f172a;
            letter-spacing: -0.025em;
        }
        .pv-header .pv-update {
            color: #6b7280;
            font-size: 1.1rem;
            font-weight: 500;
        }

        /* ─── 카드 (st.container border=True) ─── */
        [data-testid="stVerticalBlockBorderWrapper"] {
            background: #ffffff !important;
            border: 1px solid #e5e7eb !important;
            border-radius: 16px !important;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04),
                        0 12px 28px -16px rgba(0, 0, 0, 0.10) !important;
            padding: 16px 18px !important;
        }

        /* ─── 섹션 제목 (h5) — 카드 내부 ─── */
        h5, .pv-section-title {
            font-size: 1.25rem !important;
            font-weight: 700 !important;
            color: #0f172a !important;
            margin: 4px 0 14px 0 !important;
            letter-spacing: -0.01em;
        }

        /* ─── 본문 글씨 전체 키움 ─── */
        p, span, div, label {
            font-size: 1.05rem;
            line-height: 1.65;
            color: #1f2937;
        }

        /* ─── Risk Level 카드 ─── */
        .pv-risk-title {
            font-size: 1.25rem;
            font-weight: 700;
            color: #0f172a;
            text-align: center;
            margin: 4px 0 4px 0;
        }
        .pv-risk-pill {
            display: inline-block;
            padding: 12px 44px;
            border-radius: 999px;
            font-weight: 700;
            font-size: 1.4rem;
            color: #fff;
            background: #DC2626;
            box-shadow: 0 4px 14px -4px rgba(220, 38, 38, 0.45);
        }
        .pv-risk-score {
            margin-top: 14px;
            color: #4b5563;
            font-weight: 600;
            font-size: 1.2rem;
        }

        /* ─── 한 줄 요약 박스 ─── */
        .pv-summary-line {
            font-size: 1.15rem;
            color: #1f2937;
            line-height: 1.7;
            font-weight: 500;
        }

        /* ─── 뉴스 / SEC 항목 ─── */
        .pv-date-header {
            display: inline-block;
            font-size: 1.0rem;
            font-weight: 700;
            color: #4338ca;
            background: #eef2ff;
            padding: 7px 16px;
            border-radius: 999px;
            margin: 4px 0 12px 0;
        }
        .pv-news-item {
            display: grid;
            grid-template-columns: 70px 1fr auto;
            gap: 16px;
            padding: 14px 0;
            border-bottom: 1px solid #f3f4f6;
            align-items: start;
        }
        .pv-news-item:last-child { border-bottom: none; }
        .pv-news-time {
            background: #f3f4f6;
            color: #6b7280;
            font-size: 0.95rem; font-weight: 700;
            padding: 7px 0;
            border-radius: 8px;
            text-align: center; height: fit-content;
        }
        .pv-news-body .pv-headline {
            font-weight: 700;
            color: #111827;
            font-size: 1.1rem;
            line-height: 1.45;
        }
        .pv-news-body .pv-desc {
            color: #4b5563;
            font-size: 1.0rem;
            margin-top: 8px;
            line-height: 1.65;
        }
        .pv-tag {
            display: inline-block;
            background: #f3f4f6;
            color: #6b7280;
            font-size: 0.85rem;
            font-weight: 600;
            padding: 4px 12px;
            border-radius: 999px;
            margin: 10px 6px 0 0;
        }
        .pv-news-link {
            font-size: 0.95rem;
            white-space: nowrap;
            padding-top: 4px;
        }
        .pv-news-link a {
            color: #6366f1;
            text-decoration: none;
            font-weight: 600;
        }
        .pv-news-link a:hover { text-decoration: underline; }

        /* ─── SEC 항목 ─── */
        .pv-sec-item {
            display: grid;
            grid-template-columns: max-content 1fr;
            column-gap: 16px;
            row-gap: 8px;
            padding: 14px 0;
            border-bottom: 1px solid #f3f4f6;
            align-items: center;
        }
        .pv-sec-item:last-child { border-bottom: none; }
        .pv-sec-name {
            background: #eef2ff;
            color: #4338ca;
            border-radius: 8px;
            padding: 6px 14px;
            font-size: 0.95rem; font-weight: 700;
            white-space: nowrap;
        }
        .pv-sec-item .pv-headline {
            font-size: 1.1rem;
            font-weight: 700;
            color: #111827;
        }
        .pv-sec-item .pv-desc {
            grid-column: 1 / -1;
            color: #4b5563;
            font-size: 1.0rem;
            line-height: 1.65;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================================
# Mock 데이터
# ============================================================================

TODAY = date(2026, 4, 30)
LAST_UPDATE = date(2026, 4, 29)


def mock_indicator_df() -> pd.DataFrame:
    rng = random.Random(7)
    dates = pd.bdate_range(end=pd.Timestamp(LAST_UPDATE), periods=252)
    rows = []
    starts = {"BAMLH0A0HYM2": 3.2, "DGS1": 4.6, "DGS3": 4.3, "DGS5": 4.2}
    for ticker, base in starts.items():
        v = base
        for d in dates:
            v += rng.gauss(0, 0.04)
            rows.append({"base_dt": d, "ticker": ticker, "close": round(v, 3)})
    return pd.DataFrame(rows)


def mock_returns_df() -> pd.DataFrame:
    rng = random.Random(9)
    dates = pd.bdate_range(end=pd.Timestamp(LAST_UPDATE), periods=252)
    tickers = {
        "OBDC": 18.5, "OTF": 22.0, "BXSL": 30.0, "ARCC": 21.0, "FSK": 19.0,
        "BIZD": 17.0,
    }
    rows = []
    for tk, base in tickers.items():
        v = base
        for d in dates:
            v *= 1 + rng.gauss(0, 0.012)
            rows.append({"base_dt": d, "ticker": tk, "close": round(v, 4)})
    return pd.DataFrame(rows)


COLOR_MAP = {
    "OBDC": "#7AAFD4", "OTF": "#A8CDE5",
    "BXSL": "#B79BD3",
    "ARCC": "#E88688",
    "FSK":  "#FFAE6F",
    "BIZD": "#9ca3af",
    "BAMLH0A0HYM2": "#FFD54F",
    "DGS1": "#5B92FF", "DGS3": "#003BB0", "DGS5": "#002060",
}

TICKER_KR = {
    "OBDC": "Blue Owl(OBDC)", "OTF": "Blue Owl Tech(OTF)", "BXSL": "블랙스톤(BXSL)",
    "ARCC": "아레스(ARCC)", "FSK": "FS KKR(FSK)",
    "BIZD": "BDC ETF(BIZD)",
}


# ============================================================================
# Plotly 공통
# ============================================================================

PLOTLY_FONT = dict(
    family="'Source Sans 3', 'Spoqa Han Sans Neo', sans-serif",
    size=14,
    color="#374151",
)


def chart_indicator(df: pd.DataFrame) -> go.Figure:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    hy = df[df["ticker"] == "BAMLH0A0HYM2"].sort_values("base_dt")
    fig.add_trace(
        go.Scatter(
            x=hy["base_dt"], y=hy["close"], name="HY 스프레드 (%)",
            line=dict(color=COLOR_MAP["BAMLH0A0HYM2"], width=2.4),
            hovertemplate="%{x|%y.%m.%d}<br>HY 스프레드 · %{y:.2f}%<extra></extra>",
        ),
        secondary_y=False,
    )
    for tk, label in [("DGS1", "1Y"), ("DGS3", "3Y"), ("DGS5", "5Y")]:
        df_t = df[df["ticker"] == tk].sort_values("base_dt")
        fig.add_trace(
            go.Scatter(
                x=df_t["base_dt"], y=df_t["close"], name=label,
                line=dict(color=COLOR_MAP[tk], width=2.4),
                hovertemplate="%{x|%y.%m.%d}<br>" + label + " · %{y:.2f}%<extra></extra>",
            ),
            secondary_y=True,
        )
    fig.update_yaxes(
        title=dict(text="HY 스프레드 (%)", font=dict(size=14, color="#6b7280")),
        secondary_y=False, gridcolor="#f3f4f6", tickfont=dict(color="#6b7280", size=13),
    )
    fig.update_yaxes(
        title=dict(text="미국 국채 금리 (%)", font=dict(size=14, color="#6b7280")),
        secondary_y=True, tickfont=dict(color="#6b7280", size=13),
    )
    fig.update_xaxes(
        showgrid=False, tickformat="%y.%m.%d",
        tickfont=dict(color="#9ca3af", size=13),
    )
    fig.update_layout(
        height=370,
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.04, xanchor="right", x=1,
                    font=dict(size=14, color="#374151")),
        hovermode="x unified",
        plot_bgcolor="white",
        paper_bgcolor="rgba(0,0,0,0)",
        font=PLOTLY_FONT,
    )
    return fig


def chart_returns(df: pd.DataFrame) -> go.Figure:
    end = df["base_dt"].max()
    start = end - timedelta(days=365)
    df = df[df["base_dt"] >= start]
    tickers = ["OBDC", "OTF", "BXSL", "ARCC", "FSK", "BIZD"]

    fig = go.Figure()
    for t in tickers:
        df_t = df[df["ticker"] == t].sort_values("base_dt")
        if df_t.empty:
            continue
        base = float(df_t.iloc[0]["close"])
        pct = (df_t["close"] / base - 1.0) * 100.0
        label = TICKER_KR.get(t, t)
        fig.add_trace(
            go.Scatter(
                x=df_t["base_dt"], y=pct, mode="lines", name=label,
                line=dict(color=COLOR_MAP.get(t, "#9ca3af"), width=2.4),
                hovertemplate="%{x|%y.%m.%d}<br>" + label + " · %{y:+.2f}%<extra></extra>",
            )
        )
    fig.add_hline(y=0, line=dict(color="#e5e7eb", width=0.8, dash="dot"))
    fig.update_layout(
        height=370,
        margin=dict(l=10, r=10, t=30, b=10),
        yaxis=dict(
            title=dict(text="누적 수익률 (%)", font=dict(size=14, color="#6b7280")),
            ticksuffix="%", gridcolor="#f3f4f6",
            tickfont=dict(color="#6b7280", size=13),
            hoverformat=".2f",
        ),
        xaxis=dict(showgrid=False, tickformat="%y.%m.%d",
                   tickfont=dict(color="#9ca3af", size=13)),
        legend=dict(orientation="h", yanchor="bottom", y=1.04, xanchor="right", x=1,
                    font=dict(size=14, color="#374151")),
        hovermode="x unified",
        plot_bgcolor="white",
        paper_bgcolor="rgba(0,0,0,0)",
        font=PLOTLY_FONT,
    )
    return fig


def risk_gauge(value: float) -> go.Figure:
    seg_width = 34
    centers = [162, 126, 90, 54, 18]
    outer = ["#1B7C3A", "#86C39C", "#D1D5DB", "#F2A6A4", "#DC2626"]
    inner = ["#93C9A4", "#CCE7D6", "#E5E7EB", "#F8D5D3", "#F08F8F"]
    labels = ["Very Low", "Low", "Neutral", "High", "Very High"]

    fig = go.Figure()
    fig.add_trace(go.Barpolar(
        r=[0.30] * 5, theta=centers, width=[seg_width] * 5, base=0.70,
        marker=dict(color=outer, line=dict(width=0)),
        hoverinfo="skip", showlegend=False,
    ))
    fig.add_trace(go.Barpolar(
        r=[0.18] * 5, theta=centers, width=[seg_width] * 5, base=0.48,
        marker=dict(color=inner, line=dict(width=0)),
        hoverinfo="skip", showlegend=False,
    ))
    needle_angle = 180 - (max(0, min(100, value)) / 100) * 180
    fig.add_trace(go.Scatterpolar(
        r=[0, 0.65], theta=[needle_angle, needle_angle], mode="lines",
        line=dict(color="#374151", width=2.6),
        hoverinfo="skip", showlegend=False,
    ))
    fig.add_trace(go.Scatterpolar(
        r=[0], theta=[0], mode="markers",
        marker=dict(color="#374151", size=11),
        hoverinfo="skip", showlegend=False,
    ))
    fig.update_layout(
        height=240,
        margin=dict(l=30, r=30, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        font=PLOTLY_FONT,
        polar=dict(
            sector=[0, 180],
            bgcolor="rgba(0,0,0,0)",
            radialaxis=dict(visible=False, range=[0, 1.05]),
            angularaxis=dict(
                tickvals=centers, ticktext=labels,
                tickfont=dict(color="#374151", size=14),
                showgrid=False, showline=False, ticks="",
                direction="counterclockwise",
            ),
        ),
    )
    return fig


def risk_trend(score: float) -> go.Figure:
    rng = random.Random(7)
    end = pd.Timestamp(LAST_UPDATE)
    dates = [end - timedelta(days=i) for i in range(29, -1, -1)]
    val = 55.0
    series = []
    for _ in range(29):
        val += rng.gauss(0, 4.5)
        val = max(20, min(95, val))
        series.append(round(val, 1))
    series.append(score)
    fig = go.Figure(go.Scatter(
        x=dates, y=series, mode="lines",
        line=dict(color="#DC2626", width=2.4),
        fill="tozeroy",
        fillcolor="rgba(220, 38, 38, 0.12)",
        hovertemplate="%{x|%y.%m.%d} · %{y:.0f}점<extra></extra>",
    ))
    fig.update_layout(
        height=240,
        margin=dict(l=8, r=8, t=10, b=10),
        plot_bgcolor="white",
        paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False, tickformat="%y.%m.%d",
                   tickfont=dict(color="#9ca3af", size=13)),
        yaxis=dict(range=[0, 100], tickvals=[0, 20, 40, 60, 80, 100],
                   gridcolor="#f3f4f6", tickfont=dict(color="#6b7280", size=13),
                   zeroline=False),
        showlegend=False,
        font=PLOTLY_FONT,
    )
    return fig


# ============================================================================
# UI 구성  ─ 2열 × 3행 균등 그리드, 모든 박스 동일 사이즈
# ============================================================================

# 헤더
st.markdown(
    f"""
    <div class="pv-header">
      <div class="pv-title">사모신용 카나리아 모니터링 <span style="color:#9ca3af; font-weight:500; font-size:1.1rem;">· Preview</span></div>
      <div class="pv-update">Last Update · {LAST_UPDATE.strftime("%y.%m.%d")}</div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────────────
# Row 1 ·  Risk Level  |  Risk 추이 + 한 줄 요약
# ─────────────────────────────────────────────────────
score = 85
r1c1, r1c2 = st.columns(2, gap="small")

with r1c1:
    with st.container(border=True, height=BOX_HEIGHT):
        st.markdown('<div class="pv-risk-title">Risk Level</div>', unsafe_allow_html=True)
        st.plotly_chart(risk_gauge(score), width="stretch", config={"displayModeBar": False})
        st.markdown(
            f'<div style="text-align:center; margin-top:-4px;">'
            f'<span class="pv-risk-pill">Very High</span>'
            f'<div class="pv-risk-score">{int(score)} / 100</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

with r1c2:
    with st.container(border=True, height=BOX_HEIGHT):
        st.markdown("##### 최근 1개월 리스크 종합점수 추이")
        st.plotly_chart(risk_trend(score), width="stretch", config={"displayModeBar": False})
        st.markdown("##### 오늘의 시장 한 줄 요약")
        st.markdown(
            """
            <div class="pv-summary-line">
              하이일드 스프레드 확대와 BDC NAV 하락 신호가 겹치며 단기 리스크 점진 상승. 환매 지표 확대 추세.
            </div>
            """,
            unsafe_allow_html=True,
        )

st.write("")

# ─────────────────────────────────────────────────────
# Row 2 ·  HY 스프레드  |  국내외 뉴스
# ─────────────────────────────────────────────────────
ind_df = mock_indicator_df()
ret_df = mock_returns_df()

r2c1, r2c2 = st.columns(2, gap="small")

with r2c1:
    with st.container(border=True, height=BOX_HEIGHT):
        st.markdown("##### 하이일드 스프레드 vs 미국 국채 금리")
        st.plotly_chart(chart_indicator(ind_df), width="stretch", config={"displayModeBar": False})

with r2c2:
    with st.container(border=True, height=BOX_HEIGHT):
        st.markdown("##### 국내외 뉴스")
        st.markdown('<div class="pv-date-header">오늘 · 4월 30일 (목)</div>', unsafe_allow_html=True)
        news_items = [
            ("13:42", "연합뉴스",
             "BDC 펀드 1분기 실적 부진… 환매 요청 증가",
             "블랙스톤 BCRED 등 주요 사모대출 펀드의 1분기 NAV 하락 추세가 이어졌음. 환매 한도 도달 사례 증가함.",
             ["유동성", "BDC"]),
            ("11:05", "한국경제",
             "美 SEC, 사모대출 시장 모니터링 강화",
             "SEC 가 사모신용 운용사의 NAV 산정 방식에 대한 추가 공시 의무 검토 중임을 발표함.",
             ["규제"]),
        ]
        for tm, pub, title, desc, tags in news_items:
            tag_html = "".join(f'<span class="pv-tag">{t}</span>' for t in tags)
            st.markdown(
                f"""
                <div class="pv-news-item">
                  <div class="pv-news-time">{tm}</div>
                  <div class="pv-news-body">
                    <div class="pv-headline">{title}</div>
                    <div class="pv-desc">{desc}</div>
                    <div>{tag_html}</div>
                  </div>
                  <div class="pv-news-link"><a href="#">원문 ↗</a></div>
                </div>
                """,
                unsafe_allow_html=True,
            )

st.write("")

# ─────────────────────────────────────────────────────
# Row 3 ·  BDC 주가  |  SEC 공시
# ─────────────────────────────────────────────────────
r3c1, r3c2 = st.columns(2, gap="small")

with r3c1:
    with st.container(border=True, height=BOX_HEIGHT):
        st.markdown("##### BDC 및 운용사 주가")
        st.plotly_chart(chart_returns(ret_df), width="stretch", config={"displayModeBar": False})

with r3c2:
    with st.container(border=True, height=BOX_HEIGHT):
        st.markdown("##### 미국 SEC 공시")
        st.markdown('<div class="pv-date-header">어제 · 4월 29일 (수)</div>', unsafe_allow_html=True)
        sec_items = [
            ("FS KKR Capital Corp (FSK)", "8-K (수시공시)",
             "FSK 가 1분기 실적 발표함. NII 0.78달러로 전기 대비 소폭 개선. 비수익여신 비중 1.9%로 30bp 상승함."),
            ("Ares Capital Corp (ARCC)", "424B2 (투자설명서 보충)",
             "ARCC 가 6억 달러 규모 무담보 회사채 발행 공시함. 만기 2031년, 표면금리 6.875%."),
            ("Blue Owl Capital Corp II (OBDC II)", "SC TO-T/A (공개매수신고 정정)",
             "Saba Capital 의 OBDC II 공개매수 가격을 NAV 의 65%에서 67%로 상향함. 마감일 5월 12일로 연기됨."),
        ]
        for fund, form, desc in sec_items:
            st.markdown(
                f"""
                <div class="pv-sec-item">
                  <div class="pv-sec-name">{fund}</div>
                  <div class="pv-headline">{form}</div>
                  <div class="pv-desc">{desc}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
