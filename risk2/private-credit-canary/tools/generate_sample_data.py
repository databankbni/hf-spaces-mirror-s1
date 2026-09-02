"""개발용 샘플 데이터 생성기.

실제 데이터 파이프라인이 구축되기 전, UI를 렌더링할 수 있도록
data/ 폴더에 mock CSV 를 만든다. 실제 데이터가 들어오면 동일 스키마로
파일만 교체하면 app.py 는 그대로 동작한다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA.mkdir(parents=True, exist_ok=True)

PRICE_TICKERS = {
    "OBDC": 18.0,
    "OTF": 22.0,
    "BXSL": 30.0,
    "ARCC": 21.0,
    "FSK": 19.0,
    "OWL": 19.0,
    "BX": 130.0,
    "ARES": 150.0,
    "KKR": 105.0,
    "APO": 145.0,
    "BIZD": 17.0,
    "^GSPC": 5200.0,
    "HYG": 78.0,
}

INDICATOR_TICKERS = {
    "BAMLH0A0HYM2": 380.0,  # HY OAS bp
    "DGS1": 4.7,            # UST 1Y %
}


def _business_days(end: datetime, n: int) -> pd.DatetimeIndex:
    return pd.bdate_range(end=end, periods=n)


def build_price_history() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    end = datetime(2026, 4, 24)
    dates = _business_days(end, 180)

    rows = []
    for ticker, start in PRICE_TICKERS.items():
        steps = rng.normal(0, start * 0.012, len(dates))
        path = start + np.cumsum(steps)
        path = np.clip(path, start * 0.5, start * 1.6)
        for d, p in zip(dates, path):
            rows.append({"base_dt": d.date().isoformat(), "ticker": ticker, "close": round(float(p), 4)})

    for ticker, start in INDICATOR_TICKERS.items():
        vol = 6.0 if ticker == "BAMLH0A0HYM2" else 0.05
        steps = rng.normal(0, vol, len(dates))
        path = start + np.cumsum(steps)
        if ticker == "BAMLH0A0HYM2":
            path = np.clip(path, 250, 700)
        else:
            path = np.clip(path, 3.5, 5.8)
        for d, p in zip(dates, path):
            rows.append({"base_dt": d.date().isoformat(), "ticker": ticker, "close": round(float(p), 4)})

    return pd.DataFrame(rows)


def build_sec_filings() -> pd.DataFrame:
    base = datetime(2026, 4, 25)
    samples = [
        ("10-Q", "Blackstone Private Credit Fund (BCRED)", "분기 NAV 1.2% 하락, non-accrual 비중 1.7%로 상승. 신규 약정 둔화."),
        ("8-K", "Blue Owl Capital Corp (OBDC)", "회사채 6억달러 발행 결정. 만기 2031년, 표면금리 6.875%."),
        ("N-CSR", "Apollo Debt Solutions BDC", "분기 환매 한도(5%) 도달, 비례 배분 적용. 배당 정책 유지."),
        ("10-K", "Ares Capital Corp (ARCC)", "연간 NII $1.83B, 비수익 여신 1.9%로 전년比 30bp 상승."),
        ("8-K", "Owl Rock Technology Finance Corp", "주요 차주 1건 채무재조정 합의, 충당금 $42M 인식."),
        ("10-Q", "FS KKR Capital Corp (FSK)", "스프레드 압축 지속, NIM 9.4bp 하락. 헤지 비용 증가."),
        ("8-K", "Carlyle Secured Lending", "분기 배당 $0.40 유지. NAV $16.78 (-0.6%)."),
        ("N-CSR", "Golub Capital BDC", "차주별 헤드라인 위험 제한적. PIK 수익 비중 8% → 9%."),
        ("10-Q", "Sixth Street Specialty Lending", "신규 투자 $310M, 평균 EBITDA 레버리지 5.1x로 상승."),
        ("8-K", "Morgan Stanley Direct Lending Fund", "유동성 라인 한도 $250M 추가 확보, 만기 2028년."),
    ]
    rows = []
    for i, (form, fund, summary) in enumerate(samples):
        d = (base - timedelta(days=i)).date()
        rows.append({
            "filing_date": d.isoformat(),
            "form": form,
            "fund_name": fund,
            "summary_kr": summary,
            "extracted_json": json.dumps({"headline": summary[:60]}, ensure_ascii=False),
            "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=000000{i:04d}",
        })
    return pd.DataFrame(rows)


def build_news_kr() -> pd.DataFrame:
    base = datetime(2026, 4, 26, 9, 0)
    samples = [
        ("연합뉴스", "사모신용 시장에 경고등…국내 운용사도 NAV 점검 강화", "국내 주요 운용사들이 사모대출 익스포저 NAV 평가 주기를 단축하고 있다."),
        ("매일경제", "美 BDC 주가 약세에 BIZD ETF 1주 -2.3%", "스프레드 확대와 default rate 상승 우려가 동시에 부각됐다."),
        ("한국경제", "국민연금, 사모대출 비중 확대 검토 보류", "시장 변동성 확대를 이유로 비중 확대 결정을 다음 분기로 미뤘다."),
        ("이데일리", "사모신용 펀드 환매 한도 도달 사례 증가", "분기 환매 한도(5%)에 도달한 펀드가 잇따라 비례 배분을 적용하고 있다."),
        ("서울경제", "금감원, 사모신용 익스포저 점검 착수", "은행·증권사의 간접 익스포저까지 포함한 일제 점검이 시작됐다."),
        ("머니투데이", "美 하이일드 OAS 400bp 재돌파", "신용 프리미엄 확대가 사모신용 시장에도 영향을 미치고 있다."),
    ]
    rows = []
    for i, (publisher, title, summary) in enumerate(samples):
        ts = base - timedelta(hours=i * 5)
        rows.append({
            "published_at": ts.isoformat(timespec="minutes"),
            "publisher": publisher,
            "title": title,
            "summary": summary,
            "url": f"https://example.com/news/kr/{i}",
        })
    return pd.DataFrame(rows)


def build_news_en() -> pd.DataFrame:
    base = datetime(2026, 4, 26, 8, 30)
    samples = [
        ("Bloomberg", "Private credit defaults edge higher in Q1 as covenants weaken", "Recovery rates also slipped, with senior secured paper averaging 58c on the dollar."),
        ("Reuters", "BDC NAVs slip as floating-rate income compresses", "Several listed BDCs reported sequential NAV declines on tighter spreads."),
        ("Financial Times", "Investors keep piling into private credit despite warnings", "Inflows into BDC funds reached a record despite rising stress signals."),
        ("WSJ", "Regulators eye private credit liquidity disclosures", "The SEC is reviewing whether quarterly redemption gates are adequately disclosed."),
        ("Bloomberg", "Apollo, KKR see higher non-accrual ratios in latest filings", "Both reported sequential rises in non-accrual loans, though levels remain below 2%."),
        ("Reuters", "HY OAS widens past 400bps as rate-cut hopes fade", "High-yield credit spreads widened sharply on hawkish Fed commentary."),
    ]
    rows = []
    for i, (publisher, title, summary) in enumerate(samples):
        ts = base - timedelta(hours=i * 4)
        rows.append({
            "published_at": ts.isoformat(timespec="minutes"),
            "publisher": publisher,
            "title": title,
            "summary": summary,
            "url": f"https://example.com/news/en/{i}",
        })
    return pd.DataFrame(rows)


def main() -> None:
    files = {
        "price_history.csv": build_price_history(),
        "private_credit_sec_filings_history.csv": build_sec_filings(),
        "private_credit_news_korea_history.csv": build_news_kr(),
        "private_credit_news_global_history.csv": build_news_en(),
    }
    for name, df in files.items():
        path = DATA / name
        df.to_csv(path, index=False, encoding="utf-8-sig")
        print(f"wrote {path}  ({len(df)} rows)")


if __name__ == "__main__":
    main()
