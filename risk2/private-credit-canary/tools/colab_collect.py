# -*- coding: utf-8 -*-
"""사모대출 카나리아 — 데이터 수집 batch 스크립트.

Colab 에서 export 한 코드를 로컬/HF 양쪽에서 동작하도록 정리.
- 환경변수에서 API 키 로드 (.env 또는 HF Secrets)
- 결과 CSV 는 ./data/ 폴더에 저장
- 마지막에 HF Space repo 로 자동 git push (HF_TOKEN 있을 때)

실행:
    python tools/colab_collect.py
"""

# ============================================
# 0) import + 경로 설정
# ============================================
# 라이브러리 설치는 requirements.txt 로 관리 (이전 !pip install ... 제거)
# ★ 사내 네트워크 TLS inspection 우회 — Windows 인증서 저장소 사용 (회사 CA 자동 인식).
# Naver/SEC/Gemini 등 외부 HTTPS 호출 모두에 적용됨. requests/urllib3 import 전에 호출 필수.
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import os
import base64
import requests
import datetime
import re
import html
import pandas as pd
from pathlib import Path

import yfinance as yf
import feedparser
import json

from urllib.parse import urlparse, quote
from difflib import SequenceMatcher

import time
from googlenewsdecoder import gnewsdecoder

# google.genai SDK — SEC 공시 요약 LLM 호출용. raw requests.post 보다 안정적
# (gemma-4-31b-it 의 transient 500 빈발 방지). summarize_filings.py / summarize_news.py
# 와 동일 패턴.
try:
    from google import genai as _genai
except ImportError:
    _genai = None


# ============================================
# 0-a) collected_date 스탬프 — KST 기준 수집일
# ============================================
# 데이터 행의 filing_date / published_at 은 SEC EDGAR / 뉴스 발행 시점(미국·UTC 기준)이라
# KR 배치가 수집한 "오늘"과 어긋날 수 있음 (예: 5/14 US 공시가 KR 5/15 batch 에 처음 잡힘).
# 점수 산출에선 "오늘 처음 들어온 데이터"가 신규 이벤트 여부의 진실 — 그래서 별도 컬럼으로
# 수집일(KST)을 스탬프. score_risk_test_gemma 의 _load_* 가 이 컬럼을 우선 사용하고,
# 없으면(기존 누적분) filing_date/published_at 으로 fallback.
KST_TZ = datetime.timezone(datetime.timedelta(hours=9))
KST_TODAY = datetime.datetime.now(KST_TZ).strftime("%Y-%m-%d")


def _stamp_collected_date(df):
    """신규 수집 DataFrame 에 collected_date(KST) 컬럼 추가.

    merge_and_dedup 은 keep='first' 로 기존 행을 우선 유지 — 그래서 이 stamp 는
    "오늘 처음 들어온 행" 에만 박힘. 기존 누적분의 collected_date 는 NaN 으로 남고,
    로더에서 fallback 으로 filing_date / published_at 사용함.
    """
    if df is None or df.empty:
        return df
    df = df.copy()
    if "collected_date" not in df.columns:
        df["collected_date"] = KST_TODAY
    else:
        df["collected_date"] = df["collected_date"].fillna(KST_TODAY)
    return df


# ============================================
# 0-b) Colab 전용 함수 stub (로컬/HF 에서 no-op)
# ============================================
def display(*args, **kwargs):  # noqa: A001 — Colab/IPython display 호환
    """DataFrame 등을 print 로 대체."""
    for arg in args:
        try:
            if hasattr(arg, "to_string"):
                print(arg.to_string())
            else:
                print(arg)
        except Exception:
            print(repr(arg))


class _FilesStub:
    """Colab files.download / files.upload 무력화 stub."""
    @staticmethod
    def download(path):
        print(f"[INFO] (skip) files.download 호출됨 — 로컬/HF 환경에서는 자동 push 로 처리: {path}")

    @staticmethod
    def upload(*args, **kwargs):
        print("[INFO] (skip) files.upload — 비활성")
        return {}


files = _FilesStub()


# HTML 표시 (Colab IPython.display.HTML) stub — 로컬에서는 무시
class HTML:  # noqa: N801 — Colab IPython.display.HTML 호환
    def __init__(self, _content):
        pass


# ============================================
# 1) 사용자 설정 (환경변수에서 API 키 로드)
# ============================================
# 로컬: .env 또는 셸 환경변수 / HF: Settings → Variables and secrets
# 로컬 .env 자동 로드 (python-dotenv 가 있으면)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 데이터 저장 경로 — 프로젝트 루트의 data/ 폴더
# 로컬: c:/Users/.../private-credit-canary/data
# HF Docker 컨테이너: /app/data
SAVE_DIR = str(Path(__file__).resolve().parent.parent / "data")
os.makedirs(SAVE_DIR, exist_ok=True)

NEWS_DAYS_BACK  = 4   # ★ 일시 4일 (백필 catch-up). 평소엔 2.
SEC_DAYS_BACK   = 4   # ★ 일시 4일 (백필 catch-up). 평소엔 2.
PRICE_DAYS_BACK = 20  # 20일치 값 불러오고, 8)에서 최근 2일치만 출력

SEC_HEADERS = {"User-Agent": "USPrivateCreditProject spark@kiwoom.com"}


# API 키 — 환경변수에서 로드
NAVER_CLIENT_ID     = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")
GEMINI_API_KEY      = os.environ.get("GEMINI_API_KEY")
FRED_API_KEY        = os.environ.get("FRED_API_KEY")
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY")

_missing = [k for k, v in {
    "NAVER_CLIENT_ID": NAVER_CLIENT_ID,
    "NAVER_CLIENT_SECRET": NAVER_CLIENT_SECRET,
    "GEMINI_API_KEY": GEMINI_API_KEY,
    "FRED_API_KEY": FRED_API_KEY,
    "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
}.items() if not v]
if _missing:
    print(f"[WARN] 누락된 환경변수: {_missing}")
    print("로컬: 프로젝트 루트의 .env 파일에 추가 / HF: Settings → Variables and secrets")

# LLM 모델 설정
# 수시공시/기타공시 요약 — fallback 체인 (다른 스크립트와 동일하게 gemini → gemma 순서)
# .env 의 GEMINI_FILING_MODELS_FALLBACK="gemini-2.5-flash-lite,gemma-4-31b-it" 형태로 override 가능
FILING_MODELS_FALLBACK = [
    "gemini-2.5-flash-lite",     # primary — 다른 batch 스크립트 (news/filings/score_risk) 와 통일
    "gemma-4-31b-it",            # fallback — primary 가 일시 실패 / quota / prompt echo 시 전환
]
_env_filing_fallback = os.environ.get("GEMINI_FILING_MODELS_FALLBACK", "").strip()
if _env_filing_fallback:
    FILING_MODELS_FALLBACK = [m.strip() for m in _env_filing_fallback.split(",") if m.strip()]
# 호환성용 — 다른 코드 경로에서 단일 모델 이름 참조 시 첫 번째 사용
GEMINI_MODEL = FILING_MODELS_FALLBACK[0]

# LLM 호출 간 최소 sleep — Gemini 2.5 Flash Lite 무료 티어 RPM 제약 대응
# (한도 ~20/min 가정, 여유 두고 4초)
SLEEP_BETWEEN_LLM_CALLS = 4.0

# google.genai SDK 클라이언트 (lazy init — 패키지/키 없으면 None)
_genai_client = None
if _genai is not None and GEMINI_API_KEY:
    try:
        _genai_client = _genai.Client(api_key=GEMINI_API_KEY)
    except Exception as _e:  # noqa: BLE001
        print(f"[WARN] google.genai Client 초기화 실패: {_e}")

CLAUDE_MODEL = "claude-sonnet-4-6"       # 정기공시 지표 추출용 (신규)

# FRED 시리즈
FRED_SERIES_MAP = {
    "BAMLH0A0HYM2": "ICE BofA US HY OAS",
    "DGS1":         "US Treasury 1Y",
    "DGS3":         "US Treasury 3Y",
    "DGS5":         "US Treasury 5Y",
}

# BDC CIK 매핑
BDC_CIK_MAP = {
    "0001655888": "Blue Owl Capital Corp (OBDC)",
    "0001655887": "Blue Owl Capital Corp II (OBDC II)",
    "0001812554": "Blue Owl Credit Income Corp (OCIC)",
    "0001869453": "Blue Owl Technology Income Corp (OTIC)",
    "0001803498": "Blackstone Private Credit Fund (BCRED)",
    "0001287750": "Ares Capital Corp (ARCC)",
    "0001422183": "FS KKR Capital Corp (FSK)",
}

# API 키 로드 확인
print("✅ 설정 로드 완료:")
print(f"   NAVER:     {'설정됨' if NAVER_CLIENT_ID else '❌ 누락'}")
print(f"   GEMINI:    {'설정됨' if GEMINI_API_KEY else '❌ 누락'}")
print(f"   FRED:      {'설정됨' if FRED_API_KEY else '❌ 누락'}")
print(f"   ANTHROPIC: {'설정됨' if ANTHROPIC_API_KEY else '❌ 누락'}")
print(f"   Gemma 모델: {GEMINI_MODEL}")
print(f"   Claude 모델: {CLAUDE_MODEL}")
print(f"   저장 경로: {SAVE_DIR}")


# ============================================
# 2-1) 뉴스 키워드 (KR)
# ============================================
PRIMARY_KEYWORDS = ["사모대출", "사모신용", "사모신용펀드"]

SECONDARY_KEYWORDS = [
    "블루아울", "OBDC", "OBDC II", "OBDCII", "OCIC", "OTIC", "BCRED",
    "블랙스톤", "아레스", "아폴로", "BDC",
    "환매", "환매 제한", "환매 급증", "환매 요구", "환매 요청",
    "대규모 환매", "인출 한도", "출금 제한", "자금 이탈", "펀드런", "유동성",
    "PIK", "NAV 감소", "NAV 하락", "불안", "공포", "부실", "위기", "손실",
]

SEARCH_KEYWORDS = ["사모대출", "사모신용", "사모신용펀드"]

KEYWORD_TAG_MAP = {
    "운용사_블루아울":  ["블루아울", "OBDC", "OBDC II", "OBDCII", "OCIC", "OTIC"],
    "운용사_블랙스톤":  ["블랙스톤", "BCRED"],
    "운용사_기타":      ["아레스", "아폴로", "BDC"],
    "유동성_환매":      ["환매", "환매 제한", "환매 급증", "환매 요구", "환매 요청",
                        "대규모 환매", "인출 한도", "출금 제한", "자금 이탈", "펀드런", "유동성"],
    "평가_NAV":         ["NAV 감소", "NAV 하락"],
    "신용부실":         ["PIK", "부실", "손실", "신용등급", "하락"],
    "시장심리":         ["불안", "공포", "위기", "우려"],
}

ENTITY_KEYWORD_MAP = {
    "Blue Owl":            ["블루아울", "OBDC", "OBDC II", "OBDCII", "OCIC", "OTIC"],
    "Blackstone":          ["블랙스톤", "BCRED"],
    "Ares":                ["아레스"],
    "Apollo":              ["아폴로"],
    "BDC Sector":          ["BDC"],
    "Private Credit Market": ["사모대출", "사모신용", "사모신용펀드"],
}

ALLOWED_SOURCES = [
    "연합인포맥스", "연합뉴스", "한국경제", "매일경제", "서울경제",
    "이데일리", "머니투데이", "아시아경제", "파이낸셜뉴스", "조선비즈",
    "뉴스1", "뉴시스", "헤럴드경제", "한경비즈니스", "한국금융신문", "더벨",
]

DOMAIN_SOURCE_MAP = {
    "yna.co.kr":      "연합뉴스",
    "newsis.com":     "뉴시스",
    "news1.kr":       "뉴스1",
    "hankyung.com":   "한국경제",
    "mk.co.kr":       "매일경제",
    "sedaily.com":    "서울경제",
    "edaily.co.kr":   "이데일리",
    "mt.co.kr":       "머니투데이",
    "asiae.co.kr":    "아시아경제",
    "fnnews.com":     "파이낸셜뉴스",
    "biz.chosun.com": "조선비즈",
    "heraldcorp.com": "헤럴드경제",
    "fntimes.com":    "한국금융신문",
    "thebell.co.kr":  "더벨",
    "infomax.co.kr":  "연합인포맥스",
}


# ============================================
# 2-2) 뉴스 키워드 (EN)
# ============================================
PRIMARY_KEYWORDS_EN = [
    "private credit", "private credit fund", "private credit funds",
    "private debt", "direct lending",
]

SECONDARY_KEYWORDS_EN = [
    "Blue Owl", "OBDC", "OBDC II", "OCIC", "OTIC", "BCRED",
    "Blackstone", "Ares", "Apollo", "BDC",
    "redemption", "redemptions", "redemption request", "redemption requests",
    "redemption pressure", "cap", "withdrawal", "withdraw",
    "liquidity", "liquidity stress", "fund outflow", "capital outflow", "fund run",
    "PIK", "NAV", "rating", "valuation", "valuations",
    "drop", "discount", "discounts", "decline", "declines",
    "loss", "default", "defaults", "bankruptcy", "distress", "stress",
    "credit risk", "concern", "concerns", "fear", "crisis",
]

SEARCH_KEYWORDS_EN = ["private credit", "private credit fund", "private credit funds"]

KEYWORD_TAG_MAP_EN = {
    "Captial_BlueOwl":       ["Blue Owl", "OBDC", "OBDC II", "OBDCII", "OCIC", "OTIC"],
    "Captial_Blackstone":    ["Blackstone", "BCRED"],
    "Captial_Others":        ["Ares", "Apollo", "BDC"],
    "Liquidity_Redemption":  ["redemption", "redemptions", "redemption request", "redemption requests",
                               "redemption pressure", "cap", "withdrawal", "withdraw",
                               "liquidity", "liquidity stress", "fund outflow", "capital outflow", "fund run"],
    "Valuation_NAV":         ["NAV", "valuation", "valuations"],
    "Credit_Risk":           ["PIK", "rating", "drop", "discount", "discounts", "decline", "declines",
                               "loss", "default", "defaults", "bankruptcy", "distress", "stress", "credit risk"],
    "Market_Sentiment":      ["concern", "concerns", "fear", "crisis"],
}

ENTITY_KEYWORD_MAP_EN = {
    "Blue Owl":               ["Blue Owl", "OBDC", "OBDC II", "OBDCII", "OCIC", "OTIC"],
    "Blackstone":             ["Blackstone", "BCRED"],
    "Ares":                   ["Ares"],
    "Apollo":                 ["Apollo"],
    "BDC Sector":             ["BDC"],
    "Private Credit Industry": ["private credit", "private credit fund", "private credit funds"],
}

# Financial Times 제외 — 하드 페이월이라 원문 링크를 눌러도 비구독자는 본문 0줄.
# 요약도 본문 fetch 실패로 부실해질 가능성이 커 수집 대상에서 제외 (publisher 미허용).
# (ft.com 은 DOMAIN_SOURCE_MAP_EN 에 남겨 두되 allowlist 에서 빠져 자동 필터됨)
ALLOWED_SOURCES_EN  = ["Reuters", "Bloomberg", "Bloomberg.com", "WSJ", "CNBC", "MarketWatch"]
DOMAIN_SOURCE_MAP_EN = {
    "reuters.com":    "Reuters",
    "bloomberg.com":  "Bloomberg",
    "ft.com":         "Financial Times",  # 매핑은 유지하되 allowlist 제외 → 수집 안 됨
    "wsj.com":        "WSJ",
    "cnbc.com":       "CNBC",
    "marketwatch.com": "MarketWatch",
}

def infer_source_google(item):
    try:
        if hasattr(item, "source"):
            source_name = item.source.get("title", "")
            if source_name:
                return source_name
    except:
        pass
    try:
        domain = urlparse(item.link).netloc.lower()
        for key, name in DOMAIN_SOURCE_MAP_EN.items():
            if key in domain:
                return name
    except:
        pass
    return "Unknown"


# ============================================
# 3) 주가 모니터링 대상
# ============================================
BDC_TICKERS     = ["OBDC", "OTF", "BXSL", "ARCC", "FSK"]
CAPITAL_TICKERS = ["OWL", "BX", "ARES", "APO", "KKR"]
BM_TICKERS      = ["BIZD", "^GSPC", "HYG"]
PRICE_TICKERS   = BDC_TICKERS + CAPITAL_TICKERS + BM_TICKERS

TICKER_ENTITY_MAP = {
    "OBDC": "Blue Owl BDC",   "OTF":  "Blue Owl Tech BDC",
    "BXSL": "Blackstone BDC", "ARCC": "Ares BDC",
    "FSK":  "KKR BDC",        "OWL":  "Blue Owl",
    "BX":   "Blackstone",     "ARES": "Ares",
    "APO":  "Apollo",         "KKR":  "KKR",
    "BIZD": "BDC Sector",     "^GSPC": "US Equity Market",
    "HYG":  "High Yield Bond ETF",
}


# ============================================
# 4) 공통 유틸 함수
# ============================================
def clean_text(text): #HTML 엔티티 디코딩/태그 제거/깔끔한 평문 반환
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def normalize_title(title): #제목을 비교 가능한 형태로 만듦(소문자/괄호/따옴표 등 기호 공백처리)
    title = title.lower()
    # 단위 접미사 통일 — "56조원" vs "56조" 가 다른 토큰으로 갈라지지 않게
    title = title.replace("조원", "조").replace("억원", "억").replace("만원", "만")
    # 숫자 내부 . 제거 — "30.5조" → "305조", "0.4%" → "04%" (소수점이 토큰을 쪼개는 문제 해소)
    title = re.sub(r"(\d)\.(\d)", r"\1\2", title)
    title = re.sub(r"[\[\]\(\)\-–—:·,…\"'""'']", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title

def similarity(a, b): #문자 단위 유사도(0~1) 반환
    return SequenceMatcher(None, a, b).ratio()

def extract_core_tokens(text):#한글/영문/숫자만 남기고 2글자 이상인 토큰을 SET로 반환
    tokens = re.findall(r"[가-힣A-Za-z0-9]+", text.lower())
    return set(t for t in tokens if len(t) >= 2)

def token_overlap_score(title_a, title_b): #두 제목의 유사도 계산(어순이 달라도 동 단어면 높게 나옴)
    set_a, set_b = extract_core_tokens(title_a), extract_core_tokens(title_b)
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)

# 숫자+단위 토큰 패턴 — 56조 / 305조 / 04% / 12bp 등
_NUM_UNIT_RE = re.compile(r"^\d+(조|억|만|%|배|bp|bps)$", re.IGNORECASE)

def numeric_anchors(tokens): #토큰셋에서 '숫자+단위' 패턴만 추출
    return {t for t in tokens if _NUM_UNIT_RE.match(t)}

def is_similar_news(title_a, title_b, sim_threshold=0.75, token_threshold=0.45):
    # ① 문자 유사도 OR ② 토큰 Jaccard 겹침 OR ③ 같은 숫자+단위 토큰 공유
    # 수집 단계에서 PRIMARY_KEYWORDS 로 사모대출/사모신용 도메인이 이미 보장되므로,
    # 같은 수치 (예: 56조, 305조) 공유 시 거의 확실히 같은 보도자료의 재가공.
    if similarity(title_a, title_b) >= sim_threshold:
        return True
    toks_a = extract_core_tokens(title_a)
    toks_b = extract_core_tokens(title_b)
    if toks_a and toks_b and len(toks_a & toks_b) / len(toks_a | toks_b) >= token_threshold:
        return True
    if numeric_anchors(toks_a) & numeric_anchors(toks_b):
        return True
    return False

def deduplicate_similar_titles(df, sim_threshold=0.75, token_threshold=0.45,
                                recent_seen_titles=None):
    """유사한 기사 건너뛰고 새로운 것만 keep_rows 에 저장.

    recent_seen_titles 가 주어지면 cross-batch 중복도 차단 — 최근 N일 동안 이미
    수집된 정규화 제목들을 seen_titles 에 prefill 해서 batch 경계를 넘어선 같은
    스토리 (예: 어제 batch + 오늘 batch 에 같은 보도자료 다른 매체) 도 잡힘.
    """
    if df.empty:
        return df
    seen_titles = list(recent_seen_titles or [])
    keep_rows = []
    for idx, row in df.iterrows():
        current_title = row["normalized_title"]
        if any(is_similar_news(current_title, t, sim_threshold, token_threshold) for t in seen_titles):
            continue
        keep_rows.append(idx)
        seen_titles.append(current_title)
    return df.loc[keep_rows].copy()


def _recent_normalized_titles(history_csv_path, ref_date, days_window=7):
    """기존 누적 CSV 에서 최근 N일 발행된 기사들의 normalized_title 리스트 반환.

    cross-batch 중복 제거용 — 새 batch 가 어제~N일 전 batch 에 이미 들어간 비슷한
    제목을 다시 추가하지 않도록 한다. days_window=7 은 시장 휴장 (주말 + 공휴일)
    까지 끼면 같은 사건의 보도가 4~5일 간격으로 재가공돼 들어오는 경우까지 커버.
    """
    if not os.path.exists(history_csv_path):
        return []
    try:
        df_old = pd.read_csv(history_csv_path, encoding="utf-8-sig")
    except Exception:
        return []
    if df_old.empty or "published_at" not in df_old.columns:
        return []
    pub = pd.to_datetime(df_old["published_at"], errors="coerce")
    cutoff = pd.Timestamp(ref_date) - pd.Timedelta(days=days_window)
    mask = pub >= cutoff
    titles = []
    if "normalized_title" in df_old.columns:
        titles = df_old.loc[mask, "normalized_title"].dropna().astype(str).tolist()
    elif "title" in df_old.columns:
        titles = [normalize_title(t) for t in df_old.loc[mask, "title"].dropna().astype(str)]
    return [t for t in titles if t.strip()]

def infer_source(item): #기사 언론사를 3단계로 추정
    title = clean_text(item.get("title", ""))
    desc  = clean_text(item.get("description", ""))
    link  = item.get("originallink") or item.get("link") or ""
    combined_text = f"{title} {desc}"
    for source in ALLOWED_SOURCES:
        if source in combined_text:
            return source
    try:
        domain = urlparse(link).netloc.lower()
        for key, source_name in DOMAIN_SOURCE_MAP.items():
            if key in domain:
                return source_name
    except:
        pass
    return "미확인"

def contains_primary_and_secondary(title, summary, #키워드 매핑
                                   primary_kw=None, secondary_kw=None):
    primary_kw   = primary_kw   if primary_kw   is not None else PRIMARY_KEYWORDS
    secondary_kw = secondary_kw if secondary_kw is not None else SECONDARY_KEYWORDS
    text = f"{title} {summary}".lower()
    return ([kw for kw in primary_kw   if kw.lower() in text],
            [kw for kw in secondary_kw if kw.lower() in text])

def tag_article(title, summary, tag_map=None): #태그 매핑
    tag_map = tag_map if tag_map is not None else KEYWORD_TAG_MAP
    text = f"{title} {summary}".lower()
    matched_tags, matched_keywords = [], []
    for tag, keywords in tag_map.items():
        tag_hit = False
        for kw in keywords:
            if kw.lower() in text:
                matched_keywords.append(kw)
                tag_hit = True
        if tag_hit:
            matched_tags.append(tag)
    return sorted(set(matched_tags)), sorted(set(matched_keywords))

def detect_entity(title, summary, entity_map=None, first_only=False): #엔티티 매핑
    entity_map = entity_map if entity_map is not None else ENTITY_KEYWORD_MAP
    text = f"{title} {summary}".lower()
    matched_entities = []
    for entity, keywords in entity_map.items():
        for kw in keywords:
            if kw.lower() in text:
                matched_entities.append(entity)
                if first_only:
                    return entity
                break
    return ", ".join(sorted(set(matched_entities))) if matched_entities else "Unknown"

def safe_float(x): #수치(숫자) 컬럼 정제
    try:
        return None if pd.isna(x) else float(x)
    except:
        return None

def decode_google_links(df, link_col="link"):
    """df 의 google rss 링크를 원문 URL 로 교체. 실패 시 원본 유지."""
    if df.empty or link_col not in df.columns:
        return df
    df = df.copy()
    out, fail = [], 0
    for url in df[link_col]:
        if isinstance(url, str) and "news.google.com" in url:
            try:
                r = gnewsdecoder(url, interval=1)
                if r.get("status"):
                    out.append(r["decoded_url"])
                else:
                    out.append(url); fail += 1
            except Exception:
                out.append(url); fail += 1
            time.sleep(1)
        else:
            out.append(url)
    print(f"[decode] {len(df)}건 중 실패 {fail}건")
    df[link_col] = out
    return df

# ============================================
# 5) 네이버 API 호출 함수
# ============================================
def get_naver_news_by_keyword(keyword, display=100, start=1): #API 호출해 기사 목록 가져옴(display는 한번에 가져올 기사 개수로 네이버는 최대 100)
    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
    params  = {"query": keyword, "display": display, "start": start, "sort": "date"}
    response = requests.get(url, headers=headers, params=params)
    if response.status_code != 200:
        print(f"[ERROR] 키워드 '{keyword}' 호출 실패: {response.status_code}")
        return []
    return response.json().get("items", []) #성공하면 items 리스트 반환


# ============================================
# 6-1) 네이버 원본 기사 → 표준 레코드 변환
# ============================================
def transform_naver_item_to_record(item, search_keyword):
    title     = clean_text(item.get("title", ""))
    summary   = clean_text(item.get("description", ""))
    link      = item.get("originallink") or item.get("link") or "" #링크보다 원본 언론사 url 선호
    publisher = infer_source(item)
    try: #"Mon, 21 Apr 2026 10:30:00 +0900" 형식)을 "YYYY-MM-DD HH:MM:SS"로 변환
        pub_date_obj = datetime.datetime.strptime(item["pubDate"], "%a, %d %b %Y %H:%M:%S +0900")
        published_at = pub_date_obj.strftime("%Y-%m-%d %H:%M:%S")
    except:
        published_at = ""
    matched_tags, matched_keywords = tag_article(title, summary) #태그 매칭
    #primary는 제목에서만, secondary는 제목+요약에서 검사
    title_lower = title.lower()
    primary_hits = [kw for kw in PRIMARY_KEYWORDS if kw.lower() in title_lower]
    _, secondary_hits = contains_primary_and_secondary(title, summary)
    entity = detect_entity(title, summary) #entity 매칭
    return { #고정 메타데이터(language/region/source_system)와 함께 딕셔너리 반환
        "record_type": "news", "source_system": "naver_news",
        "publisher": publisher, "entity": entity,
        "title": title, "summary": summary, "link": link,
        "published_at": published_at, "search_keyword": search_keyword,
        "matched_tags": ", ".join(matched_tags),
        "primary_hits": ", ".join(primary_hits),
        "secondary_hits": ", ".join(secondary_hits),
        "language": "ko", "region": "KR",
        "normalized_title": normalize_title(title),
    }


# ============================================
# 6-2) Google RSS → 표준 레코드 변환
# ============================================
def transform_google_item_to_record(item, search_keyword):
    title     = clean_text(item.get("title", ""))
    summary   = clean_text(item.get("summary", ""))
    link  = item.get("link", "")
    publisher = infer_source_google(item)

    try:
        pp = item.get("published_parsed")
        published_at = datetime.datetime(*pp[:6]).strftime("%Y-%m-%d %H:%M:%S") if pp else ""
    except:
        published_at = ""
    # primary는 제목에서만, secondary는 제목+요약에서 검사
    title_lower = title.lower()
    primary_hits = [kw for kw in PRIMARY_KEYWORDS_EN if kw.lower() in title_lower]
    _, secondary_hits = contains_primary_and_secondary(
        title, summary, PRIMARY_KEYWORDS_EN, SECONDARY_KEYWORDS_EN
    )
    matched_tags, _ = tag_article(title, summary, KEYWORD_TAG_MAP_EN)
    entity = detect_entity(title, summary, ENTITY_KEYWORD_MAP_EN, first_only=False)
    return {
        "record_type": "news", "source_system": "google_rss",
        "publisher": publisher, "entity": entity,
        "title": title, "summary": summary,
        "link": link,
        "published_at": published_at, "search_keyword": search_keyword,
        "matched_tags": ", ".join(set(matched_tags)),
        "primary_hits": ", ".join(primary_hits),
        "secondary_hits": ", ".join(secondary_hits),
        "language": "en", "region": "US",
        "normalized_title": normalize_title(title),
    }


# ============================================
# 7-1) 국내뉴스 수집 메인 함수
# ============================================
def collect_private_credit_news_kr(days_back=2):
    all_rows = []
    kst_now = datetime.datetime.utcnow() + datetime.timedelta(hours=9) #기간 설정
    target_dates = [(kst_now - datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days_back)]

    for keyword in SEARCH_KEYWORDS:
        print(f"뉴스 수집 중: {keyword}")
        for item in get_naver_news_by_keyword(keyword, display=100, start=1): #transform_naver_item_to_record로 표준화한 뒤, 다섯 가지 조건을 모두 통과한 기사만 all_rows에 담음
            record = transform_naver_item_to_record(item, keyword)
            if not record["published_at"]:
                continue
            if record["published_at"][:10] not in target_dates:
                continue
            if record["publisher"] not in ALLOWED_SOURCES:
                continue
            if (not record["primary_hits"]) or (not record["secondary_hits"]):
                continue
            if not record["matched_tags"]:
                continue
            all_rows.append(record)

    expected_cols = [
        "record_type", "source_system", "publisher", "entity", "title", "summary",
        "link", "published_at", "search_keyword",
        "primary_hits", "matched_tags", "secondary_hits", "language", "region",
    ]
    if not all_rows:
        return pd.DataFrame(columns=expected_cols)

    df = pd.DataFrame(all_rows) #dataframe 변환 및 중복제거
    df = df.drop_duplicates(subset=["link"], keep="first").copy()
    df = df.drop_duplicates(subset=["normalized_title"], keep="first").copy()

    def count_items(x):
        if pd.isna(x) or str(x).strip() == "":
            return 0
        return len([i for i in str(x).split(",") if i.strip()])

    df["matched_tag_count"] = df["matched_tags"].apply(count_items)
    df["published_at_dt"]   = pd.to_datetime(df["published_at"], errors="coerce")
    df = df.sort_values(by=["published_at_dt", "matched_tag_count"], ascending=[False, False]).copy() #published_at(최신 우선) → matched_tag_count(태그 많이 매칭된 것 우선)
    # cross-batch 중복 제거 — 최근 7일 누적 CSV 의 normalized_title 을 prefill 해서
    # 어제 batch 가 잡은 같은 보도자료의 다른 매체 버전 (예: 8시 발행 - 다음날 batch 가
    # 잡음) 도 차단. 7일로 잡아 주말·공휴일 끼인 재수집까지 커버.
    recent_seen = _recent_normalized_titles(
        f"{SAVE_DIR}/private_credit_news_korea_history.csv",
        ref_date=pd.Timestamp.now(), days_window=7,
    )
    df = deduplicate_similar_titles(df, sim_threshold=0.75, token_threshold=0.45,
                                     recent_seen_titles=recent_seen)
    df = df.drop(columns=["normalized_title", "published_at_dt", "matched_tag_count"], errors="ignore")
    df = df[expected_cols].copy()
    df = df.reset_index(drop=True)
    df.index = df.index + 1
    return df


# ============================================
# 7-2) Google RSS 뉴스 수집
# ============================================
def collect_private_credit_news_en(days_back=2):
    all_rows = []
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    target_dates = [(utc_now - datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days_back)]

    for keyword in SEARCH_KEYWORDS_EN:
        print(f"[EN] RSS 수집 중: {keyword}")
        rss_url = f"https://news.google.com/rss/search?q={quote(keyword)}&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(rss_url)

        for item in feed.entries:
            record = transform_google_item_to_record(item, keyword)
            if not record["published_at"]:
                continue
            if record["published_at"][:10] not in target_dates:
                continue
            if record["publisher"] not in ALLOWED_SOURCES_EN:
                continue
            if not record["primary_hits"]:
                continue
            if not record["matched_tags"]:
                continue
            all_rows.append(record)

    expected_cols = [
        "record_type", "source_system", "publisher", "entity", "title", "summary",
        "link", "published_at", "search_keyword",
        "primary_hits", "matched_tags", "secondary_hits", "language", "region",
    ]
    if not all_rows:
        return pd.DataFrame(columns=expected_cols)

    df = pd.DataFrame(all_rows)
    df = df.drop_duplicates(subset=["link"], keep="first").copy()
    df = df.drop_duplicates(subset=["normalized_title"], keep="first").copy()

    def count_items(x):
        if pd.isna(x) or str(x).strip() == "":
            return 0
        return len([i for i in str(x).split(",") if i.strip()])

    df["matched_tag_count"] = df["matched_tags"].apply(count_items)
    df["published_at_dt"]   = pd.to_datetime(df["published_at"], errors="coerce")
    df = df.sort_values(by=["published_at_dt", "matched_tag_count"], ascending=[False, False]).copy()
    # cross-batch 중복 제거 (KR 과 동일 — 최근 7일 누적 CSV 의 normalized_title prefill)
    recent_seen = _recent_normalized_titles(
        f"{SAVE_DIR}/private_credit_news_global_history.csv",
        ref_date=pd.Timestamp.now(), days_window=7,
    )
    df = deduplicate_similar_titles(df, sim_threshold=0.75, token_threshold=0.45,
                                     recent_seen_titles=recent_seen)
    df = df.drop(columns=["normalized_title", "published_at_dt", "matched_tag_count"], errors="ignore")
    df = df[expected_cols].copy()
    df = decode_google_links(df)
    df = df.reset_index(drop=True)
    df.index = df.index + 1
    return df


# ============================================
# 8-1) Yahoo Finance 주가 조회
# ============================================
# yfinance 는 기본적으로 curl_cffi 를 써서 Python SSL 우회.
# - 사내망 (로컬): TLS inspection 때문에 requests.Session() (truststore) 필요
# - HF Space: 일반 인터넷이라 yfinance 기본 동작 (curl_cffi) 이 정상 — session 넘기면 거부됨
# SPACE_ID 환경변수로 HF 환경 감지 → 분기 처리.
_IS_ON_HF = bool(os.environ.get("SPACE_ID"))
_yf_session = None if _IS_ON_HF else requests.Session()


def get_yahoo_price_history(ticker, days_back=20): #days_back일만큼의 일별 OHLC 데이터를 요청(주말/공휴일 때문에 넉넉히 불러와서 최근 2일치만 아래에서 추출)
    try:
        if _yf_session is not None:
            tk = yf.Ticker(ticker, session=_yf_session)
        else:
            tk = yf.Ticker(ticker)   # HF: yfinance 기본 curl_cffi 사용
        hist = tk.history(period=f"{days_back}d", interval="1d", auto_adjust=False) #auto_adjust=False는 배당·주식분할 조정 전 원시 종가를 받겠다는 뜻
        if hist.empty:
            print(f"[WARN] 데이터 없음: {ticker}")
            return pd.DataFrame()
        df = hist[["Close"]].copy().reset_index()
        if "Date" not in df.columns:
            df = df.rename(columns={df.columns[0]: "Date"})
        try:
            df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None)
        except:
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.sort_values("Date").tail(2) #최근 2일만 추출
        df["base_dt"] = df["Date"].dt.strftime("%Y-%m-%d")
        df["ticker"]  = ticker
        df["entity"]  = TICKER_ENTITY_MAP.get(ticker, "Unknown")
        df["close"]   = df["Close"].apply(safe_float)
        df = df[["base_dt", "ticker", "entity", "close"]].dropna(subset=["base_dt", "close"])
        return df
    except Exception as e: #한 티커가 실패해도 빈 DataFrame을 반환(여러 티커를 돌리므로, 한 종목 실패가 전체 파이프라인을 멈추지 않게 해주는 안전장치)
        print(f"[ERROR] Yahoo Finance 조회 실패 - {ticker}: {e}")
        return pd.DataFrame()


# ============================================
# 8-2) FRED 지표 조회
# ============================================
def get_fred_series(series_id, days_back=20):
    """FRED API에서 최근 N일치 데이터 조회 후 최근 2영업일만 반환.

    - 500/502/503 일시 오류는 자동 재시도 (백오프 1·3·5·7초, 최대 4회)
    - 호출 끝에 짧은 sleep(0.3s)으로 burst rate-limit 회피
    """
    import time

    try:
        end_date   = datetime.date.today()
        start_date = end_date - datetime.timedelta(days=days_back)

        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {
            "series_id":         series_id,
            "api_key":           FRED_API_KEY,
            "file_type":         "json",
            "observation_start": start_date.strftime("%Y-%m-%d"),
            "observation_end":   end_date.strftime("%Y-%m-%d"),
            "sort_order":        "asc",
        }

        # 일시 오류(5xx) 재시도 — 1, 3, 5, 7초 백오프
        res = None
        for attempt in range(4):
            res = requests.get(url, params=params, timeout=(10, 30))
            if res.status_code == 200:
                break
            if res.status_code in (500, 502, 503, 504) and attempt < 3:
                wait = 1 + attempt * 2   # 1, 3, 5, 7초
                print(f"  [INFO] FRED 재시도 {attempt + 1}/4 (status={res.status_code}, {wait}s 대기)")
                time.sleep(wait)
                continue
            break

        if res is None or res.status_code != 200:
            status = res.status_code if res is not None else "no-response"
            print(f"[WARN] FRED API 실패: {series_id} (status={status})")
            return pd.DataFrame()

        data = res.json()
        observations = data.get("observations", [])
        if not observations:
            print(f"[WARN] FRED 데이터 없음: {series_id}")
            return pd.DataFrame()

        df = pd.DataFrame(observations)
        df = df[["date", "value"]].copy()

        # FRED 결측치는 "."으로 반환 → NaN 변환 후 제거
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.dropna(subset=["value"])

        # 최근 2영업일만 추출
        df = df.sort_values("date").tail(2)

        df["base_dt"] = df["date"]
        df["ticker"]  = series_id
        df["entity"]  = FRED_SERIES_MAP.get(series_id, "Unknown")
        df["close"]   = df["value"].astype(float)

        df = df[["base_dt", "ticker", "entity", "close"]].copy()

        # 호출 간격 — burst rate-limit 회피용 짧은 sleep
        time.sleep(0.3)
        return df

    except Exception as e:
        print(f"[ERROR] FRED 조회 실패 - {series_id}: {e}")
        return pd.DataFrame()


# ============================================
# 9) 주가 등 수집 메인 함수
# ============================================
def collect_private_credit_prices(days_back=20):
    all_dfs = []
    for ticker in PRICE_TICKERS:
        print(f"주가 수집 중: {ticker}")
        df_ticker = get_yahoo_price_history(ticker, days_back=days_back)
        if not df_ticker.empty:
            all_dfs.append(df_ticker)

    for series_id in FRED_SERIES_MAP.keys():
        print(f"FRED 수집 중: {series_id}")
        df_fred = get_fred_series(series_id, days_back=days_back)
        if not df_fred.empty:
            all_dfs.append(df_fred)

    expected_cols = ["base_dt", "ticker", "entity", "close"]
    if not all_dfs:
        return pd.DataFrame(columns=expected_cols)

    df = pd.concat(all_dfs, ignore_index=True) #모든 티커 데이터 합치기
    df["base_dt_dt"] = pd.to_datetime(df["base_dt"], errors="coerce") #날짜 문자열을 datetime으로 변환해 정렬용 보조 컬럼 생성
    df = df.sort_values(by=["base_dt_dt", "ticker"], ascending=[True, True]).copy() #날짜 오름차순, 티커 오름차순으로 정렬
    df = df.drop(columns=["base_dt_dt"], errors="ignore")
    df = df.drop_duplicates(subset=["base_dt", "ticker"], keep="last").copy() #같은 날짜·티커 조합 중복 시 마지막 것만 유지
    df = df.reset_index(drop=True) #보조 컬럼 제거
    df.index = df.index + 1 # 인덱스 1부터 시작
    return df


# ============================================
# 10-1) 파일 병합 + 중복 제거 함수 (누적 저장, Unnamed 방지)
# ============================================
def merge_and_dedup(existing_path, new_df, pk_cols, date_cols=None):
    """
    기존 CSV + 신규 DataFrame 병합 후 중복 제거.
    - Unnamed 컬럼 자동 제거 (누적 재저장 시 쌓이는 것 방지)
    - pk_cols 기준 중복 제거 (기존 행 우선 keep="first")
    - date_cols: 날짜 컬럼은 YYYY-MM-DD 앞 10자만으로 비교 (time 차이 무관)
    - published_at/base_dt/filing_date 기준 자동 정렬
    """
    # 1) 기존 파일 읽기
    if os.path.exists(existing_path):
        try:
            old_df = pd.read_csv(existing_path, encoding="utf-8-sig")
            old_df = old_df.loc[:, ~old_df.columns.str.contains("^Unnamed", case=False)]
            merged = pd.concat([old_df, new_df], ignore_index=True)
        except Exception as e:
            print(f"  [WARN] 기존 파일 읽기 실패: {e}")
            merged = new_df.copy()
    else:
        merged = new_df.copy()

    if merged.empty:
        return merged

    # 2) 신규에 있을 수 있는 Unnamed도 제거
    merged = merged.loc[:, ~merged.columns.str.contains("^Unnamed", case=False)]

    # 3) pk_cols 정규화 — date_cols 는 임시 컬럼으로 YYYY-MM-DD 만 추출해 dedup,
    #    title 같은 text 컬럼은 공백/특수문자 미세 차이로 dedup 실패 방지 위해 정규화.
    #    원본 값은 보존 (예: published_at = "2026-05-11 20:57:36" 그대로).
    date_cols = set(date_cols or [])
    temp_cols = []
    dedup_keys = []
    for col in pk_cols:
        if col not in merged.columns:
            continue
        if col in date_cols:
            tmp = f"_dedup_{col}"
            merged[tmp] = merged[col].fillna("").astype(str).str.slice(0, 10)
            temp_cols.append(tmp)
            dedup_keys.append(tmp)
        elif col == "title":
            # title 정규화: 연속 공백 → 단일, 양끝 공백 trim (특수문자/대소문자는 보존)
            tmp = f"_dedup_{col}"
            merged[tmp] = (
                merged[col].fillna("").astype(str)
                .str.replace(r"\s+", " ", regex=True)
                .str.strip()
            )
            temp_cols.append(tmp)
            dedup_keys.append(tmp)
        else:
            merged[col] = merged[col].fillna("").astype(str).str.strip()
            dedup_keys.append(col)

    merged = merged.drop_duplicates(subset=dedup_keys, keep="first").copy()

    # 임시 컬럼 제거
    if temp_cols:
        merged = merged.drop(columns=temp_cols)

    # 4) 정렬
    if "published_at" in merged.columns:
        merged["_sort_dt"] = pd.to_datetime(merged["published_at"], errors="coerce")
        merged = merged.sort_values("_sort_dt", ascending=False).copy()
        merged = merged.drop(columns=["_sort_dt"], errors="ignore")
    elif "base_dt" in merged.columns:
        merged["_sort_dt"] = pd.to_datetime(merged["base_dt"], errors="coerce")
        if "ticker" in merged.columns:
            merged = merged.sort_values(["_sort_dt", "ticker"], ascending=[True, True]).copy()
        else:
            merged = merged.sort_values("_sort_dt", ascending=True).copy()
        merged = merged.drop(columns=["_sort_dt"], errors="ignore")
    elif "filing_date" in merged.columns:
        merged["_sort_dt"] = pd.to_datetime(merged["filing_date"], errors="coerce")
        merged = merged.sort_values("_sort_dt", ascending=False).copy()
        merged = merged.drop(columns=["_sort_dt"], errors="ignore")

    merged = merged.reset_index(drop=True)
    return merged


# ============================================
# 10-2) SEC 공시 수집 함수
# ============================================

# 정기공시 HTML → 구조화 JSON
from bs4 import BeautifulSoup

_SUBMISSIONS_CACHE = {} #submissions API 캐시

def get_submissions_data(cik):
    """SEC submissions API 호출 결과를 캐싱. 같은 CIK는 처음 한 번만 네트워크 호출."""
    if cik in _SUBMISSIONS_CACHE:
        return _SUBMISSIONS_CACHE[cik]

    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    try:
        res = requests.get(url, headers=SEC_HEADERS, timeout=(10, 30))
        if res.status_code != 200:
            print(f"[ERROR] submissions 조회 실패: {cik} (status={res.status_code})")
            _SUBMISSIONS_CACHE[cik] = None
            return None
        data = res.json()
        _SUBMISSIONS_CACHE[cik] = data
        return data
    except Exception as e:
        print(f"[ERROR] submissions 조회 예외: {cik} ({e})")
        _SUBMISSIONS_CACHE[cik] = None
        return None

def extract_context_map(html_str):
    """
    iXBRL의 xbrli:context에서 contextRef ID → 시점/기간 날짜 매핑 추출
    """
    from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
    import warnings
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

    soup        = BeautifulSoup(html_str, "lxml")
    context_map = {}

    for ctx in soup.find_all("xbrli:context"): #태그 순회하며 날짜 정보 수집
        ctx_id = ctx.get("id")
        if not ctx_id:
            continue

        instant = ctx.find("xbrli:instant") #instant 있으면 시점형
        if instant:
            context_map[ctx_id] = {
                "type": "instant",
                "date": instant.get_text(strip=True)
            }
            continue

        start = ctx.find("xbrli:startdate") #start,enddate 있으면 기간형
        end   = ctx.find("xbrli:enddate")
        if start and end:
            context_map[ctx_id] = {
                "type":       "duration",
                "start_date": start.get_text(strip=True),
                "end_date":   end.get_text(strip=True)
            }

    return context_map

def compress_tables(tables):
    """
    빈 셀 제거 + 필요한 필드만 유지해서 파일 크기 축소
    """
    compressed = []
    for table in tables:
        rows_out = []
        for row in table.get("rows", []):
            cells_out = []
            for cell in row.get("cells", []):
                #빈 셀 제거
                if not cell.get("raw_text", "").strip():
                    continue
                #기본 필드
                c = {
                    "cell_id":   cell["cell_id"],
                    "row_index": cell["row_index"],
                    "col_index": cell["col_index"],
                    "raw_text":  cell["raw_text"],
                }
                # 숫자값 있을 때만 추가
                if cell.get("numeric_value") is not None:
                    c["numeric_value"] = cell["numeric_value"]
                # ix 메타(concept/contextRef) 있을 때만 추가
                if cell.get("concept"):
                    c["concept"]    = cell["concept"]
                    c["contextRef"] = cell.get("contextRef")
                    c["unitRef"]    = cell.get("unitRef")
                    c["decimals"]   = cell.get("decimals")
                cells_out.append(c)
            if cells_out: #결과가 비었으면 빈 행 통째로 버림
                rows_out.append({
                    "row_index": row["row_index"],
                    "cells":     cells_out,
                })
        if rows_out: #결과가 비었으면 빈 테이블 통째로 버림
            compressed.append({
                "table_id": table["table_id"],
                "rows":     rows_out,
            })
    return compressed


def html_to_structured_json(html_str: str, filing_id: str = "filing"): #SEC 공시 HTML을 통째로 텍스트 + 테이블 구조의 JSON으로 변환

    # 1) iXBRL header 메타데이터 제거(서문 오염 방지)
    from bs4 import XMLParsedAsHTMLWarning
    import warnings
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

    html_str = re.sub(
        r"<ix:header[^>]*>.*?</ix:header>",
        "",
        html_str,
        flags=re.IGNORECASE | re.DOTALL
    )

    soup = BeautifulSoup(html_str, "lxml")

    # 2) script / style 제거
    for tag in soup(["script", "style"]):
        tag.decompose()

    # 3) 테이블 추출 (colspan/rowspan + ix 메타 보존)
    tables = []

    def extract_ix_meta(cell_tag): #concept(회계 개념명), contextRef(날짜 맥락), unitRef(통화·단위), decimals(소수점 자릿수) 등을 추출
        meta = {}
        for ix in cell_tag.find_all("ix:nonfraction"):
            meta["concept"]    = ix.get("name")
            meta["contextRef"] = ix.get("contextref")
            meta["unitRef"]    = ix.get("unitref")
            meta["decimals"]   = ix.get("decimals")
            meta["scale"]      = ix.get("scale")
            meta["sign"]       = ix.get("sign")
            break
        if not meta:
            for ix in cell_tag.find_all("ix:nonnumeric"):
                meta["concept"]    = ix.get("name")
                meta["contextRef"] = ix.get("contextref")
                meta["unitRef"]    = None
                meta["decimals"]   = None
                break
        return meta

    def parse_number(s, scale=None, sign=None): #문자열을 float로 변환. 회계 표기의 괄호=음수 반영
        if not s:
            return None
        s = s.strip()
        neg = s.startswith("(") and s.endswith(")")
        if neg:
            s = s[1:-1]
        s = re.sub(r"[^0-9.\-]", "", s.replace(",", ""))
        try:
            val = float(s)
            if scale:
                try:
                    val = val * (10 ** int(scale))
                except:
                    pass
            if sign == "-":
                val = -val
            elif neg:
                val = -val
            return val
        except:
            return None

    for t_idx, tbl in enumerate(soup.find_all("table")):
        table_id  = f"{filing_id}__t{t_idx}"
        grid      = []
        rows_out  = []

        for r_idx, tr in enumerate(tbl.find_all("tr")):
            while len(grid) <= r_idx:
                grid.append([])

            col_pos   = 0
            row_cells = []

            for cell in tr.find_all(["th", "td"]):
                while col_pos < len(grid[r_idx]) and grid[r_idx][col_pos] is not None:
                    col_pos += 1

                colspan  = int(cell.get("colspan", 1)) #셀병합(colspan, rowspan) 처리 고려, 2차원 그리드 배열 생성
                rowspan  = int(cell.get("rowspan", 1))
                raw_text = cell.get_text(" ", strip=True)
                ix_meta  = extract_ix_meta(cell)
                num_val  = parse_number(
                    raw_text,
                    scale=ix_meta.get("scale"),
                    sign=ix_meta.get("sign")
                )
                cell_id  = f"{table_id}__r{r_idx}__c{col_pos}"

                row_cells.append({
                    "cell_id":       cell_id,
                    "row_index":     r_idx,
                    "col_index":     col_pos,
                    "rowspan":       rowspan,
                    "colspan":       colspan,
                    "raw_text":      raw_text,
                    "numeric_value": num_val,
                    "concept":       ix_meta.get("concept"),
                    "contextRef":    ix_meta.get("contextRef"),
                    "unitRef":       ix_meta.get("unitRef"),
                    "decimals":      ix_meta.get("decimals"),
                })

                for dr in range(rowspan):
                    ri = r_idx + dr
                    while len(grid) <= ri:
                        grid.append([])
                    need = col_pos + colspan - len(grid[ri])
                    if need > 0:
                        grid[ri].extend([None] * need)
                    for dc in range(colspan):
                        grid[ri][col_pos + dc] = cell_id

                col_pos += colspan

            if row_cells:
                rows_out.append({"row_index": r_idx, "cells": row_cells})

        if rows_out:
            tables.append({"table_id": table_id, "rows": rows_out})

    # 4) 텍스트 추출 (테이블 제거 후 나머지)
    for tbl in soup.find_all("table"):
        tbl.replace_with("\n__TABLE_EXTRACTED__\n")

    for ix in soup.find_all(
        lambda t: t.name and t.name.lower().startswith("ix:")
    ):
        ix.replace_with(ix.get_text())

    plain_text = soup.get_text(separator="\n")
    plain_text = re.sub(r"\n{3,}", "\n\n", plain_text).strip()

    return {
        "filing_id": filing_id,
        "tables":    tables,
        "text":      plain_text,
    }


def save_periodic_filing_by_sections(cik, fund_name, filing_info):
    accession  = filing_info.get("accession_number", "")
    form_type  = filing_info.get("form", "")
    period_end = filing_info.get("period_end", "")
    filed_date = filing_info.get("filed_date", "")

    # primaryDocument 찾기(공시 문서 파일명 찾기)
    data = get_submissions_data(cik)
    if data is None:
        return ""
    filings  = data.get("filings", {}).get("recent", {})
    acc_list = filings.get("accessionNumber", [])
    doc_list = filings.get("primaryDocument", [])

    primary_doc = ""
    for acc, doc in zip(acc_list, doc_list):
        if acc == accession:
            primary_doc = doc
            break

    if not primary_doc:
        print(f"[WARN] primaryDocument 없음: {cik}")
        return ""

    acc_clean  = accession.replace("-", "")
    base_url   = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}" #HTML 본문 다운로드
    target_doc = primary_doc

    print(f"  [INFO] 사용 문서: {target_doc}")
    res = requests.get(f"{base_url}/{target_doc}", headers=SEC_HEADERS)
    if res.status_code != 200:
        print(f"[ERROR] 본문 다운로드 실패: {cik} / {target_doc}")
        return ""

    raw_html   = res.text
    filing_id  = f"{cik}__{form_type}__{period_end}"
    print(f"  [INFO] HTML {len(raw_html):,}자")

    # 구조화
    structured = html_to_structured_json(raw_html, filing_id=filing_id)
    structured["tables"] = compress_tables(structured["tables"])
    print(f"  [INFO] 테이블 수: {len(structured['tables'])}개")

    # context_map 추출 (신규 추가)
    context_map = extract_context_map(raw_html)
    print(f"  [INFO] context 수: {len(context_map)}개")

    # JSON 저장
    output = {
        "meta": {
            "cik":         cik,
            "fund_name":   fund_name,
            "form":        form_type,
            "period_end":  period_end,
            "filed_date":  filed_date,
            "table_count": len(structured["tables"]),
        },
        "context_map": context_map,
        "text":   structured["text"],
        "tables": structured["tables"],
    }

    safe_name  = re.sub(r"[^\w\s-]", "", fund_name).strip().replace(" ", "_")
    file_name  = f"{safe_name}_{form_type}_{period_end}.json"
    drive_dir  = f"{SAVE_DIR}/sec_filings_json"
    drive_path = f"{drive_dir}/{file_name}"
    local_path = drive_path   # 로컬 = drive 경로 동일하게 처리 (Colab /content 의존성 제거)

    os.makedirs(drive_dir, exist_ok=True)
    with open(local_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    with open(drive_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"  [저장] {drive_path} ({os.path.getsize(local_path)/1024/1024:.1f}MB)")
    return local_path


# 수시공시 관련 함수

def get_latest_periodic_filing_info(cik): #가장 최신의 정기공시 하나의 메타정보를 반환
    data = get_submissions_data(cik)
    if data is None:
        return {}
    filings = data.get("filings", {}).get("recent", {})
    df = pd.DataFrame({
        "form":            filings.get("form", []),
        "filingDate":      filings.get("filingDate", []),
        "reportDate":      filings.get("reportDate", []),
        "accessionNumber": filings.get("accessionNumber", []),
    })
    if df.empty:
        return {}
    df_periodic = df[df["form"].isin(["10-K", "10-Q","10-K/A", "10-Q/A"])].sort_values("filingDate", ascending=False)
    if df_periodic.empty:
        return {}
    latest = df_periodic.iloc[0]
    return {
        "form":             latest["form"],
        "period_end":       latest["reportDate"],
        "filed_date":       latest["filingDate"],
        "accession_number": latest["accessionNumber"],
    }


def get_recent_filings(cik, days_back=2): #최근 N영업일 공시 전부 조회
    data = get_submissions_data(cik)
    if data is None:
        return pd.DataFrame()
    filings = data.get("filings", {}).get("recent", {})
    df = pd.DataFrame({
        "form":            filings.get("form", []),
        "filingDate":      filings.get("filingDate", []),
        "accessionNumber": filings.get("accessionNumber", []),
        "primaryDocument": filings.get("primaryDocument", []),
    })
    if df.empty:
        return df
    df["filingDate"] = pd.to_datetime(df["filingDate"])
    today         = pd.Timestamp.now(tz="UTC").normalize().tz_localize(None)
    business_days = pd.bdate_range(end=today - pd.Timedelta(days=1), periods=days_back)
    return df[df["filingDate"].isin(business_days)].copy()


def get_filing_text(cik, accession, doc): #HTML 태그를 걷어낸 평문 텍스트로 반환 ## 수시공시는 표·XBRL 구조가 없는 단순 텍스트가 대부분이라 "html_to_structured_json" 대신 "get_filing_text"
    acc = accession.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc}"
    res = requests.get(url, headers=SEC_HEADERS)
    if res.status_code != 200:
        return ""
    text = html.unescape(res.text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+",     " ", text)
    return text


# 8-K Item 추출
ITEM_DESC_MAP = {
    "1.01": "Entry into a Material Definitive Agreement",
    "1.02": "Termination of a Material Definitive Agreement",
    "1.03": "Bankruptcy or Receivership",
    "1.04": "Mine Safety - Reporting of Shutdowns and Patterns of Violations",
    "1.05": "Material Cybersecurity Incidents",
    "2.01": "Completion of Acquisition or Disposition of Assets",
    "2.02": "Results of Operations and Financial Condition",
    "2.03": "Creation of a Direct Financial Obligation or an Obligation under an Off-Balance Sheet Arrangement",
    "2.04": "Triggering Events That Accelerate or Increase a Direct Financial Obligation",
    "2.05": "Cost Associated with Exit or Disposal Activities",
    "2.06": "Material Impairments",
    "3.01": "Notice of Delisting or Failure to Satisfy a Continued Listing Rule or Standard",
    "3.02": "Unregistered Sales of Equity Securities",
    "3.03": "Material Modification to Rights of Security Holders",
    "4.01": "Changes in Registrant's Certifying Accountant",
    "4.02": "Non-Reliance on Previously Issued Financial Statements",
    "5.01": "Changes in Control of Registrant",
    "5.02": "Departure of Directors or Certain Officers; Election of Directors; Appointment of Certain Officers",
    "5.03": "Amendments to Articles of Incorporation or Bylaws",
    "5.04": "Temporary Suspension of Trading Under Registrant's Employee Benefit Plans",
    "5.05": "Amendments to the Registrant's Code of Ethics",
    "5.06": "Change in Shell Company Status",
    "5.07": "Submission of Matters to a Vote of Security Holders",
    "5.08": "Shareholder Nominations",
    "6.01": "ABS Informational and Computational Material",
    "6.02": "Change of Servicer or Trustee",
    "6.03": "Change in Credit Enhancement or Other External Support",
    "6.04": "Failure to Make a Required Distribution",
    "6.05": "Securities Act Updating Disclosure",
    "7.01": "Regulation FD Disclosure",
    "8.01": "Other Events",
    "9.01": "Financial Statements and Exhibits",
}

def extract_8k_items(text): #8-K 공시에서 Item 번호·설명 추출
    found = re.findall(r'[Ii]tem\s+(\d+\.\d+)', text)
    seen  = []
    for item_no in found:
        if item_no not in seen:
            seen.append(item_no)
    if not seen:
        return "", ""
    return ", ".join(seen), ", ".join([ITEM_DESC_MAP.get(no, "Unknown Item") for no in seen])


# 응답 품질 검증 — LLM 이 본문 요약 대신 prompt 자체를 echo 한 경우 감지
def _looks_like_prompt_echo(resp: str) -> bool:
    """LLM 응답이 실제 요약이 아니라 instruction echo / 빈 응답인지 판별.

    True 면 응답 거부하고 다음 fallback 모델로 전환. False 면 정상 응답.
    """
    if not resp or not resp.strip():
        return True
    s = resp.strip()
    # 1) 너무 짧으면 fail (정상 요약은 최소 ~150자)
    if len(s) < 100:
        return True
    low = s.lower()
    # 2) 본문 없는 prompt instruction 의 핵심 키워드 동시 출현 → echo
    echo_markers = [
        "role: financial analyst",
        "role:financial analyst",
        "task: extract key facts",
        "extract key facts from an sec",
        "constraint 1:",
        "constraint 2:",
        "no reasoning, drafts",
        "no reasoning, no drafts",
        "summary (en): <",
        "summary (kr): <",
        "summary (en) and summary (kr)",
        "음슴체 style",
        "max 5 sentences",
    ]
    hits = sum(1 for m in echo_markers if m in low)
    # 2개 이상 동시 출현 → 거의 확실히 prompt echo
    if hits >= 2:
        return True
    # 3) 응답 첫 200자 안에 1개라도 + Summary 본문 흔적이 없으면 echo
    head = low[:300]
    if any(m in head for m in echo_markers):
        # 본문 흔적 (회사명/금액/Item 번호 등) 이 거의 없으면 echo
        body_signals = [
            "$",                # 금액
            "million",
            "billion",
            "item 1.01", "item 2.03", "item 5.02", "item 8.01", "item 9.01",
            "공시함", "발표함", "예정임", "체결함", "확대됨",  # 음슴체 본문
        ]
        if not any(sig in low for sig in body_signals):
            return True
    return False


# 수시/기타공시 요약
def summarize_filing_with_gemini(text, form="", item_nos_str="", item_descs_str=""):
    """모든 SEC 공시 요약 (수시·기타) — 음슴체 한국어 출력.

    매 공시마다 primary 부터 fallback chain 을 순회. Sticky 없음 (전역 상태 없음).

    재시도 (단순화):
      - 429 (RPM 한도) → 60 / 90 / 120s 대기 후 재시도. 모두 실패면 다음 모델로.
      - 5xx (서버 transient) → 5 / 10 / 15s 대기 후 재시도. 모두 실패면 다음 모델로.
      - 그 외 (4xx 인증 등) → 즉시 다음 모델로.
      - 호출 후 SLEEP_BETWEEN_LLM_CALLS (4s) 대기로 RPM window 안에서 burst 방지.

    google.genai SDK 사용 — raw requests.post 의 gemma 500 빈발 회피.
    """
    import time

    cleaned = " ".join(text.split())[:20000]

    # 8-K 인 경우에만 item context 추가
    if form == "8-K" and item_nos_str:
        item_block = f"""
This 8-K filing contains the following Items:
- Item Numbers: {item_nos_str}
- Item Descriptions: {item_descs_str}
Please reflect these items in your summary.
"""
    else:
        item_block = ""

    prompt = f"""You are a financial analyst reviewing an SEC filing. Extract key facts from the SEC filing below and output ONLY the fields specified in the exact format. Do not include any reasoning, drafts, or explanations.
{item_block}
Output format (fill in each field, keep it concise):
Summary (EN): <5-sentence summary in English>
Summary (KR): <5-sentence Korean summary in 음슴체 style — see rules below>

[KR Style Rules — MUST FOLLOW]
- End each sentence with -음 / -했음 / -임 / -됨 forms.
- Examples: "발표함.", "하락했음.", "예정임.", "확대됨.", "공시함."
- NEVER use polite forms ("-습니다", "-합니다") or formal declarative ("-한다", "-된다", "-이다").

Do NOT output anything else. No drafts, no sentence-by-sentence breakdown, no verification checks.

TEXT:
{cleaned}
"""

    def _call_one_model(model_name: str) -> str:
        """단일 모델 SDK 호출 — 단순 backoff 재시도. 응답 텍스트 or ''."""
        if _genai_client is None:
            print(f"  [ERROR] google.genai SDK 클라이언트 없음 — {model_name} 호출 불가")
            return ""
        for attempt in range(3):
            try:
                resp = _genai_client.models.generate_content(
                    model=model_name, contents=prompt
                )
                if attempt > 0:
                    print(f"  [INFO] {model_name} 재시도 성공 (시도 {attempt + 1}/3)")
                return (resp.text or "").strip()
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                msg_low = msg.lower()
                # 429 (RPM/RPD) — 60s+ 대기 후 재시도
                if "429" in msg or "resource_exhausted" in msg_low or "quota" in msg_low:
                    wait = [60, 90, 120][attempt]
                    if attempt < 2:
                        print(f"  [INFO] {model_name} 429 — {wait}s 대기 후 재시도 ({attempt + 1}/3)")
                        time.sleep(wait)
                        continue
                    print(f"  [ERROR] {model_name} 429 누적 — 다음 모델로")
                    return ""
                # 5xx (서버 transient) — 짧은 backoff
                if any(c in msg for c in ("500", "502", "503", "504")) or "internal" in msg_low:
                    wait = [5, 10, 15][attempt]
                    if attempt < 2:
                        print(f"  [INFO] {model_name} 5xx — {wait}s 대기 후 재시도 ({attempt + 1}/3): {msg[:120]}")
                        time.sleep(wait)
                        continue
                    print(f"  [ERROR] {model_name} 5xx 누적 — 다음 모델로: {msg[:200]}")
                    return ""
                # 그 외 (4xx 인증, 모델명 오타 등) — 즉시 포기
                print(f"  [ERROR] {model_name} 비재시도 에러: {msg[:200]}")
                return ""
        return ""

    # Fallback chain 순회. 매 공시 fresh start (전역 상태 없음).
    for model_name in FILING_MODELS_FALLBACK:
        result = _call_one_model(model_name)
        time.sleep(SLEEP_BETWEEN_LLM_CALLS)  # RPM window 안에서 burst 방지
        if result and not _looks_like_prompt_echo(result):
            return result
        reason = "빈 응답" if not result else "prompt echo / 품질 저하"
        print(f"  [FALLBACK] {model_name} {reason} → 다음 모델로")

    print(f"  [ERROR] 모든 fallback 모델 실패 — extracted_json 빈 값 기록")
    return ""


# ============================================
# 10-3) 정기공시 전체 JSON + 스니펫 + Claude 지표 추출 함수
# ============================================

# 스니펫 JSON 생성
def save_relevant_snippets(json_path, output_dir=None):
    """전체 JSON → 키워드 관련 부분만 추려서 스니펫 저장"""

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    meta        = data.get("meta", {})
    text        = data.get("text", "")
    tables      = data.get("tables", [])
    context_map = data.get("context_map", {})

    KEYWORDS = [
        "pik interest income",
        "pik dividend income",
        "payment-in-kind interest income",
        "payment-in-kind dividend income",
        "total investment income",
        "loans on non-accrual status",
        "percentage of assets on non-accrual",
        "amortized cost of our performing and non-accrual debt instruments",
        "% of investments on non-accrual (based on fair value)",
        "at amortized cost, loans on non-accrual status",
        #"performing",
        "non-accrual",
        "net asset value per share",
        "net asset value per class",
        "net asset value per class s",
        "net asset value per class d",
        "net asset value per class i",
    ]

    def resolve_context(ctx_id):
        if not ctx_id or ctx_id not in context_map:
            return ctx_id
        info = context_map[ctx_id]
        if info.get("type") == "instant":
            return info.get("date", ctx_id)
        return f"{info.get('start_date')}~{info.get('end_date')}"

    def matches_keyword(s):
        s_lower = s.lower()
        return any(kw in s_lower for kw in KEYWORDS)

    relevant_texts = [p.strip() for p in text.split("\n\n") if matches_keyword(p)]

    relevant_tables = []
    for table in tables:
        all_cells  = [c for r in table["rows"] for c in r["cells"]]
        table_text = " ".join(c.get("raw_text", "") for c in all_cells)

        if not matches_keyword(table_text):
            continue

        rows_out = []
        for row in table["rows"]:
            cells_out = []
            for cell in row["cells"]:
                c = dict(cell)
                if c.get("contextRef"):
                    c["contextRef"] = resolve_context(c["contextRef"])
                cells_out.append(c)
            rows_out.append({
                "row_index": row["row_index"],
                "cells":     cells_out,
            })

        relevant_tables.append({
            "table_id": table["table_id"],
            "rows":     rows_out,
        })

    output = {
        "meta":   meta,
        "texts":  relevant_texts,
        "tables": relevant_tables,
    }

    if output_dir is None:
        output_dir = os.path.dirname(json_path)
    os.makedirs(output_dir, exist_ok=True)

    base_name   = os.path.basename(json_path).replace(".json", "_snippet.json")
    output_path = os.path.join(output_dir, base_name)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    size_kb = os.path.getsize(output_path) / 1024
    print(f"      스니펫 JSON: 텍스트 {len(relevant_texts)}개 | "
          f"테이블 {len(relevant_tables)}개 | {size_kb:.0f}KB")

    return output_path


# Claude 지표 추출
def load_snippet_content(snippet_path):
    """스니펫 JSON을 LLM 입력용 텍스트로 변환 (테이블 + Non-accrual 텍스트 우선)"""

    with open(snippet_path, encoding="utf-8") as f:
        data = json.load(f)

    meta   = data.get("meta", {})
    texts  = data.get("texts", [])
    tables = data.get("tables", [])

    parts = []
    parts.append(f"Company: {meta.get('fund_name', '')}")
    parts.append(f"Form: {meta.get('form', '')}")
    parts.append(f"Period End: {meta.get('period_end', '')}")
    parts.append(f"Filed Date: {meta.get('filed_date', '')}")
    parts.append("")

    # 1) 테이블 우선 (NAV, PIK, Non-accrual 표 형태)
    if tables:
        parts.append("=== RELEVANT TABLES ===")
        for i, tbl in enumerate(tables, 1):
            parts.append(f"\n[Table {i}] {tbl['table_id']}")
            for row in tbl["rows"]:
                cells_txt = []
                for cell in row["cells"]:
                    raw = cell.get("raw_text", "")
                    ctx = cell.get("contextRef", "")
                    concept = cell.get("concept", "")
                    if ctx or concept:
                        cells_txt.append(f"{raw} [date={ctx}, concept={concept}]")
                    else:
                        cells_txt.append(raw)
                parts.append(" | ".join(cells_txt))

    # 2) Non-accrual 키워드 있는 텍스트는 통째로 (우선)
    NONACCRUAL_KEYWORDS = ["non-accrual", "nonaccrual", "non accrual"]

    priority_texts = []
    other_texts = []

    for t in texts:
        t_lower = t.lower()
        if any(kw in t_lower for kw in NONACCRUAL_KEYWORDS):
            priority_texts.append(t)
        else:
            other_texts.append(t)

    if priority_texts:
        parts.append("\n=== NON-ACCRUAL TEXT SECTIONS (priority) ===")
        for t in priority_texts:
            parts.append(t)
            parts.append("")

    # 3) 나머지 텍스트는 짧게 (각 500자)
    if other_texts:
        parts.append("\n=== OTHER RELEVANT TEXT (truncated) ===")
        for t in other_texts:
            parts.append(t[:500])
            parts.append("")

    return "\n".join(parts)


def extract_metrics_from_snippet_with_claude(snippet_text, period_end):
    """Claude Sonnet 4.6으로 스니펫에서 3개 지표 추출 (rate limit 대응)"""

    MAX_SNIPPET_CHARS = 150_000
    if len(snippet_text) > MAX_SNIPPET_CHARS:
        print(f"      [WARN] 스니펫 큼 ({len(snippet_text):,}자), {MAX_SNIPPET_CHARS:,}자로 제한")
        snippet_text = snippet_text[:MAX_SNIPPET_CHARS]

    prompt = f"""You are a financial analyst extracting specific quantitative metrics from a BDC's SEC filing snippet.

The snippet contains relevant text sections and tables. Tables include resolved date context (e.g., [date=2025-12-31]).

Extract the following THREE metrics for period ending {period_end}. Output ONLY the values in the exact format. Do NOT include explanations or drafts.

Output format:
NAV per Share: <dollar amount>
NAV per Share Basis: <single | class_i>
PIK Ratio Pct: <percentage>
Non-accrual Pct: <percentage>
Non-accrual Basis: <amortized_cost | fair_value>

Extraction rules:

1. NAV per Share (as of {period_end}):
   - If the filing shows ONE class of shares: extract that value, output "single" as basis
   - If the filing shows MULTIPLE classes (e.g., Class I, S, D): extract Class I value, output "class_i" as basis
   - Output in dollars (e.g., 15.30)

2. PIK Ratio Pct:
   - Find PIK Interest Income AND PIK Dividend Income for {period_end}
   - Find Total Investment Income for {period_end}
   - Calculate: (PIK Interest + PIK Dividend) / Total Investment Income * 100
   - Output as percentage (e.g., 3.5)
   - If only one of PIK Interest/Dividend exists, use only the available one

3. Non-accrual Pct:
   - PREFERRED: non-accrual as percentage based on AMORTIZED COST
   - FALLBACK: if amortized cost not available, use FAIR VALUE
   - Output as percentage (e.g., 1.8)
   - Indicate which basis was used in "Non-accrual Basis"

If any value cannot be determined, output "N/A".

SNIPPET:
{snippet_text}
"""

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key":         ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type":      "application/json",
    }
    body = {
        "model":      CLAUDE_MODEL,
        "max_tokens": 500,
        "messages":   [{"role": "user", "content": prompt}]
    }

    # 429 대응: 최대 3회 재시도, 각 재시도 시 60초 대기
    for attempt in range(3):
        try:
            res = requests.post(url, headers=headers, json=body, timeout=(30, 180))

            if res.status_code == 200:
                data = res.json()
                if "content" not in data or not data["content"]:
                    return {}
                raw = data["content"][0]["text"]

                # 디버깅 로그 (None 발생 시 원인 파악용)
                parsed = parse_three_metrics_output(raw)
                none_count = sum(1 for v in parsed.values() if v is None)
                if none_count >= 3:  # 거의 다 None이면
                    print(f"      [DEBUG] Claude 응답:")
                    print(f"      {raw[:500]}")

                return parsed

            elif res.status_code == 429:

                # rate limit 에러 → 60초 대기 후 재시도
                if attempt < 2:
                    print(f"      [INFO] Rate limit (429), 60초 대기 후 재시도 ({attempt + 1}/3)")
                    time.sleep(60)
                    continue
                else:
                    print(f"      [ERROR] Rate limit (3회 실패)")
                    return {}

            elif res.status_code in (500, 502, 503, 504):
                # 서버 오류 → 짧게 대기 후 재시도
                if attempt < 2:
                    wait = 10 + attempt * 10
                    print(f"      [INFO] 서버 오류 ({res.status_code}), {wait}초 대기 후 재시도")
                    time.sleep(wait)
                    continue
                else:
                    print(f"      [ERROR] Claude API: {res.status_code}")
                    return {}

            else:
                print(f"      [ERROR] Claude API: {res.status_code}")
                print(f"              응답: {res.text[:300]}")
                return {}

        except Exception as e:
            if attempt < 2:
                print(f"      [INFO] 예외 ({e}), 10초 대기 후 재시도")
                time.sleep(10)
                continue
            print(f"      [ERROR] Claude 호출 실패: {e}")
            return {}

    return {}


def parse_three_metrics_output(raw):
    """LLM 출력에서 지표 파싱"""
    fields_map = {
        "NAV per Share":       ("nav_per_share",    "float"),
        "NAV per Share Basis": ("nav_basis",        "str"),
        "PIK Ratio Pct":       ("pik_ratio_pct",    "float"),
        "Non-accrual Pct":     ("nonaccrual_pct",   "float"),
        "Non-accrual Basis":   ("nonaccrual_basis", "str"),
    }

    result = {}
    for label, (key, dtype) in fields_map.items():
        pattern = rf"{re.escape(label)}:\s*([^\n]+)"
        match = re.search(pattern, raw, re.IGNORECASE)
        if not match:
            result[key] = None
            continue

        value_str = match.group(1).strip()

        if "n/a" in value_str.lower():
            result[key] = None
            continue

        if dtype == "float":
            num_match = re.search(r"[-+]?\d*\.?\d+", value_str.replace(",", ""))
            if num_match:
                try:
                    result[key] = float(num_match.group(0))
                except:
                    result[key] = None
            else:
                result[key] = None
        else:
            val_lower = value_str.lower()
            if "class_i" in val_lower or "class i" in val_lower:
                result[key] = "class_i"
            elif "single" in val_lower:
                result[key] = "single"
            elif "amortized" in val_lower:
                result[key] = "amortized_cost"
            elif "fair" in val_lower:
                result[key] = "fair_value"
            else:
                result[key] = value_str

    return result


# 매일 신규 감지 + 처리 메인 함수
def get_recent_periodic_filings(cik, days_back=2):
    """최근 N영업일 이내 제출된 정기공시(10-K/10-Q, /A 포함) 반환"""
    data = get_submissions_data(cik)
    if data is None:
        return []

    filings = data.get("filings", {}).get("recent", {})
    df = pd.DataFrame({
        "form":            filings.get("form", []),
        "filingDate":      filings.get("filingDate", []),
        "reportDate":      filings.get("reportDate", []),
        "accessionNumber": filings.get("accessionNumber", []),
        "primaryDocument": filings.get("primaryDocument", []),
    })

    if df.empty:
        return []

    df = df[df["form"].isin(["10-K", "10-Q", "10-K/A", "10-Q/A"])].copy()
    if df.empty:
        return []

    df["filingDate"] = pd.to_datetime(df["filingDate"])
    today = pd.Timestamp.now(tz="UTC").normalize().tz_localize(None)
    business_days = pd.bdate_range(end=today - pd.Timedelta(days=1), periods=days_back)
    df = df[df["filingDate"].isin(business_days)].copy()

    return df.to_dict("records")


def _normalize_cik(v) -> str:
    """CIK 비교용 정규화 — '0001655887' / '1655887' / 1655887 모두 동일 키로."""
    s = str(v).strip().lstrip("0")
    return s if s else "0"


def _normalize_date(v) -> str:
    """날짜 비교용 정규화 — 'YYYY-MM-DD' 앞 10자만 추출.
    'YYYY-MM-DD' / 'YYYY-MM-DD HH:MM:SS' / Timestamp 객체 모두 동일 키로."""
    return str(v).strip()[:10]


def is_already_processed(cik, form, period_end, metrics_csv_path):
    """private_credit_sec_periodic_history.csv에 이미 있는 공시인지 확인.

    CIK + period_end 정규화 — CSV round-trip 시 앞 0 손실 / datetime 변환 문제 우회.
    """
    if not os.path.exists(metrics_csv_path):
        return False

    try:
        # 인코딩 fallback (수기 입력 CSV 호환)
        df = None
        for enc in ("utf-8-sig", "utf-8", "cp1252", "cp949", "latin-1"):
            try:
                df = pd.read_csv(metrics_csv_path, encoding=enc, dtype=str)
                break
            except UnicodeDecodeError:
                continue
        if df is None:
            return False

        target_cik = _normalize_cik(cik)
        target_form = str(form).strip()
        target_period = _normalize_date(period_end)

        match = df[
            (df["cik"].apply(_normalize_cik) == target_cik) &
            (df["form"].astype(str).str.strip() == target_form) &
            (df["period_end"].apply(_normalize_date) == target_period)
        ]
        return not match.empty
    except Exception:
        return False


def process_new_periodic_filings_daily(days_back=2):
    """
    매일 파이프라인용: 신규 정기공시 감지 → JSON → 스니펫 → Claude 지표 추출 → CSV 누적.
    """
    if not ANTHROPIC_API_KEY:
        print("[WARN] ANTHROPIC_API_KEY 없음 — 정기공시 지표 추출 건너뜀")
        return pd.DataFrame()

    metrics_csv_path = f"{SAVE_DIR}/private_credit_sec_periodic_history.csv"
    snippet_dir = f"{SAVE_DIR}/sec_filings_json/snippets"
    os.makedirs(snippet_dir, exist_ok=True)

    print("\n" + "=" * 50)
    print(f"📋 정기공시 신규 감지 (최근 {days_back}영업일)")
    print("=" * 50)

    rows = []

    for cik, fund_name in BDC_CIK_MAP.items():
        filings = get_recent_periodic_filings(cik, days_back=days_back)
        if not filings:
            continue

        for f in filings:
            form       = f["form"]
            period_end = f["reportDate"]
            filed_date = f["filingDate"].strftime("%Y-%m-%d") if hasattr(f["filingDate"], "strftime") else str(f["filingDate"])[:10]
            accession  = f["accessionNumber"]

            if is_already_processed(cik, form, period_end, metrics_csv_path):
                print(f"  [{fund_name}] {form} ({period_end}) 이미 처리됨 — 스킵")
                continue

            print(f"\n  [{fund_name}] 🆕 신규 정기공시 감지!")
            print(f"    {form} | period_end {period_end} | filed {filed_date}")

            filing_info = {
                "form":             form,
                "period_end":       period_end,
                "filed_date":       filed_date,
                "accession_number": accession,
            }

            # 기존 함수 재사용 (섹션 10-2에 이미 있음)
            try:
                json_path = save_periodic_filing_by_sections(cik, fund_name, filing_info)
                if not json_path:
                    print(f"    [SKIP] JSON 저장 실패")
                    continue
            except Exception as e:
                print(f"    [ERROR] JSON: {e}")
                continue

            try:
                snippet_path = save_relevant_snippets(json_path, output_dir=snippet_dir)
                if not snippet_path:
                    print(f"    [SKIP] 스니펫 저장 실패")
                    continue
            except Exception as e:
                print(f"    [ERROR] 스니펫: {e}")
                continue

            snippet_text = load_snippet_content(snippet_path)
            print(f"    스니펫 크기: {len(snippet_text):,}자")

            metrics = extract_metrics_from_snippet_with_claude(snippet_text, period_end)
            if not metrics or not any(v is not None for v in metrics.values()):
                print(f"    [SKIP] 지표 추출 실패")
                continue

            row = {
                "cik":                cik,
                "fund_name":          fund_name,
                "form":               form,
                "period_end":         period_end,
                "filed_date":         filed_date,
                "nav_per_share":      metrics.get("nav_per_share"),
                "nav_basis":          metrics.get("nav_basis"),
                "pik_ratio_pct":      metrics.get("pik_ratio_pct"),
                "nonaccrual_pct":     metrics.get("nonaccrual_pct"),
                "nonaccrual_basis":   metrics.get("nonaccrual_basis"),
            }
            rows.append(row)

            print(f"    → NAV: {metrics.get('nav_per_share')} ({metrics.get('nav_basis')})")
            print(f"      PIK: {metrics.get('pik_ratio_pct')}% | Non-accrual: {metrics.get('nonaccrual_pct')}% ({metrics.get('nonaccrual_basis')})")

            time.sleep(0.5)

    if not rows:
        print("\n  [INFO] 신규 정기공시 없음")
        return pd.DataFrame()

    df_new = pd.DataFrame(rows)

    # A안 — 오늘 새로 수집된 정기공시에 collected_date(KST) 스탬프
    df_new = _stamp_collected_date(df_new)

    # 1) 기존 파일 읽어서 신규와 concat (없으면 신규만)
    if os.path.exists(metrics_csv_path):
        # 수기 입력 파일이 utf-8 가 아닌 경우 fallback 인코딩 시도 (Windows ANSI/cp1252/cp949)
        df_existing = None
        for enc in ("utf-8-sig", "utf-8", "cp1252", "cp949", "latin-1"):
            try:
                df_existing = pd.read_csv(metrics_csv_path, encoding=enc)
                break
            except UnicodeDecodeError:
                continue
        if df_existing is None:
            print(f"  [WARN] {metrics_csv_path} 모든 인코딩 시도 실패 — 신규 데이터만 사용")
            df_merged = df_new.copy()
        else:
            df_merged = pd.concat([df_existing, df_new], ignore_index=True)
    else:
        df_merged = df_new.copy()

    # 2) pk 컬럼 정규화 + period_end 는 YYYY-MM-DD 만 비교 (datetime 변환 차이 무관)
    df_merged["_cik_norm"] = df_merged["cik"].astype(str).str.strip().str.lstrip("0")
    df_merged["_form_norm"] = df_merged["form"].astype(str).str.strip()
    df_merged["_period_norm"] = df_merged["period_end"].astype(str).str.slice(0, 10)

    # 3) 복합 키 기준 dedup — 기존 행 우선 (keep="first") — LLM 비결정성으로 인한 갱신 차단
    df_merged = df_merged.drop_duplicates(
        subset=["_cik_norm", "_form_norm", "_period_norm"],
        keep="first"
    ).reset_index(drop=True)
    df_merged = df_merged.drop(columns=["_cik_norm", "_form_norm", "_period_norm"])

    # 3-1) 정렬 — cik 오름차순, 그 안에서 period_end 오름차순
    df_merged = df_merged.sort_values(
        ["cik", "period_end"],
        ascending=[True, True]
    ).reset_index(drop=True)

    # 4) 저장
    df_merged.to_csv(metrics_csv_path, index=False, encoding="utf-8-sig")

    print(f"\n  ✅ 정기공시 지표 누적: {len(df_new)}건 신규 / 총 {len(df_merged)}건")
    return df_new



# ============================================
# 10-4) 전체 SEC 파이프라인 → 앞서 정의된 여러 함수들을 순서대로 호출해 BDC 7개 공시를 한번에 수집
# ============================================
# 모니터링 제외 Form
SKIP_FORMS = {
    "10-K", "10-Q", "10-K/A", "10-Q/A",  # 정기공시 (별도 처리)
    "S-8", "S-8 POS",                    # 직원 보상
    "RW", "RW WD",                       # 등록 철회
    "FWP",                               # 자유 작성 투자설명서
    "ARS",                               # 주주용 연차보고서 PDF
    "N-CSR", "N-CSRS",                   # 펀드 연·반기 보고서
    "486APOS",                           # 486(a) 사전 발효 수정
    "N-CEN",                             # 펀드 연차 통계
    "N-PX",                              # 의결권 행사 기록
    "DEF 14A", "PRE 14A",
    "DEFA14A", "DEFR14A",                # 정기 주주총회 위임장 (장문, 형식적)
    "CT ORDER",                          # SEC 기밀 처리 명령 — 본문이 이미지 PDF 라 텍스트 추출 불가 + 형식 문서라 신용 신호 가치 낮음
}


def collect_sec_data():
    # ============================================
    # 1) 정기공시 자동화 (신규 감지 + Claude 지표 추출)
    # ============================================
    df_periodic_new = process_new_periodic_filings_daily(days_back=SEC_DAYS_BACK)

    # ============================================
    # 2) 수시·기타공시 처리
    # ============================================
    print("\n" + "=" * 50)
    print("📄 수시·기타공시 처리")
    print("=" * 50)

    # ★ 이미 처리된 accession_number 로드 (LLM 재호출 방지)
    processed_accessions = set()
    if os.path.exists(filings_drive_path):
        try:
            old_df = pd.read_csv(filings_drive_path, encoding="utf-8-sig")
            if "accession_number" in old_df.columns:
                processed_accessions = set(
                    old_df["accession_number"]
                    .dropna()
                    .astype(str)
                    .str.strip()
                )
                print(f"  [INFO] 이미 처리된 공시: {len(processed_accessions)}건 (LLM 호출 스킵)")
        except Exception as e:
            print(f"  [WARN] 누적 CSV 읽기 실패: {e}")

    filing_results = []

    for cik, fund_name in BDC_CIK_MAP.items():
        print(f"\nSEC 수집 중: {cik} ({fund_name})")

        filings = get_recent_filings(cik, days_back=SEC_DAYS_BACK)
        for _, row in filings.iterrows():
            form      = row["form"]
            accession = row["accessionNumber"]

            # 스킵 대상 form (정기공시·직원보상·등록철회 등)
            if form in SKIP_FORMS:
                continue

            # ★ 이미 처리된 공시 → LLM 재호출 안 함
            if accession in processed_accessions:
                print(f"  [SKIP] {fund_name} {form} {accession} (이미 처리됨)")
                continue

            # 본문 가져오기
            text = get_filing_text(cik, accession, row["primaryDocument"])
            if not text:
                continue

            # 8-K 만 item 추출 (다른 form 은 빈 값)
            if form == "8-K":
                item_nos_str, item_descs_str = extract_8k_items(text)
            else:
                item_nos_str, item_descs_str = "", ""

            # ★ 통합 함수 1회 호출 (8-K / 기타공시 모두 동일 함수)
            extracted = summarize_filing_with_gemini(
                text, form, item_nos_str, item_descs_str
            )

            # summary_en / summary_kr 은 비워둠 — VS Code 측 summarize_filings.py 가 후처리
            filing_results.append({
                "cik":              cik,
                "fund_name":        fund_name,
                "form":             form,
                "filing_date":      str(row["filingDate"].date()),
                "accession_number": accession,
                "item_nos":         item_nos_str,
                "item_descs":       item_descs_str,
                "summary_en":       "",
                "summary_kr":       "",
                "extracted_json":   extracted if extracted else "LLM_OUTPUT_EMPTY",
            })

    # DataFrame 생성 + 컬럼 정렬
    df_filings = pd.DataFrame(filing_results) if filing_results else pd.DataFrame()
    if not df_filings.empty:
        df_filings = df_filings[[
            "cik", "fund_name", "form", "filing_date", "accession_number",
            "item_nos", "item_descs",
            "summary_en", "summary_kr",
            "extracted_json",
        ]]

    return df_filings


# ============================================
# 11) 실행 - 국내뉴스 / 해외뉴스 수집
# ============================================
df_news_kr = collect_private_credit_news_kr(days_back=NEWS_DAYS_BACK)
print(f"\n[KR] 최종 수집 기사 수: {len(df_news_kr)}건")
if not df_news_kr.empty:
    display(df_news_kr[["publisher","published_at","title","entity","primary_hits","matched_tags","secondary_hits","link"]].head(50))
else:
    print("[WARN] 수집된 국내 뉴스 데이터가 없습니다")

df_news_en = collect_private_credit_news_en(days_back=NEWS_DAYS_BACK)
print(f"\n[EN] 최종 수집 기사 수: {len(df_news_en)}건")
if not df_news_en.empty:
    display(df_news_en[["publisher","published_at","title","entity","primary_hits","matched_tags","secondary_hits","link"]].head(50))
else:
    print("[WARN] 수집된 해외 뉴스 데이터가 없습니다")


# ============================================
# 12) 실행 - Yahoo Finance 주가 수집
# ============================================
df_price = collect_private_credit_prices(days_back=PRICE_DAYS_BACK)
print(f"\n최종 수집 주가 건수: {len(df_price)}건")
if not df_price.empty:
    display(df_price[["base_dt","ticker","entity","close"]].tail(50))
else:
    print("[WARN] 수집된 주가 데이터가 없습니다.")


# ============================================
# 13) 실행 - SEC 공시 수집
# ============================================
filings_drive_path = f"{SAVE_DIR}/private_credit_sec_filings_history.csv"

df_sec_filings = collect_sec_data()

print(f"\n[수시공시] LLM 요약 수집 건수: {len(df_sec_filings)}")
if not df_sec_filings.empty:
    display(df_sec_filings)
else:
    print("[WARN] 직전 2영업일 수시공시 없음")


# ============================================
# 14) CSV 저장 (누적 방식)
# ============================================
import shutil

# 누적 저장본 파일명
news_kr_file_name = "private_credit_news_korea_history.csv"
news_en_file_name = "private_credit_news_global_history.csv"
price_file_name   = "private_credit_price_history.csv"
filings_file_name = "private_credit_sec_filings_history.csv"
returns_latest_file_name = "private_credit_returns_latest.csv"
returns_series_file_name = "private_credit_returns_ytd_series.csv"
periodic_file_name       = "private_credit_sec_periodic_history.csv"

# 오늘 신규 수집분 파일명 (누적본과 구분)
news_kr_today_name = "private_credit_news_korea_today.csv"
news_en_today_name = "private_credit_news_global_today.csv"
price_today_name   = "private_credit_price_today.csv"
filings_today_name = "private_credit_sec_filings_today.csv"

# Drive 경로 (누적분)
news_kr_drive_path    = f"{SAVE_DIR}/{news_kr_file_name}"
news_en_drive_path    = f"{SAVE_DIR}/{news_en_file_name}"
price_drive_file_path = f"{SAVE_DIR}/{price_file_name}"
filings_drive_path    = f"{SAVE_DIR}/{filings_file_name}"
returns_latest_path   = f"{SAVE_DIR}/{returns_latest_file_name}"
returns_series_path   = f"{SAVE_DIR}/{returns_series_file_name}"
periodic_path         = f"{SAVE_DIR}/{periodic_file_name}"


# Drive 경로 (오늘분)
news_kr_today_drive_path = f"{SAVE_DIR}/{news_kr_today_name}"
news_en_today_drive_path = f"{SAVE_DIR}/{news_en_today_name}"
price_today_drive_path   = f"{SAVE_DIR}/{price_today_name}"
filings_today_drive_path = f"{SAVE_DIR}/{filings_today_name}"


def finalize_df(df):
    if df.empty:
        return df
    df = df.loc[:, ~df.columns.str.contains("^Unnamed", case=False)]
    df = df.drop(columns=["normalized_title"], errors="ignore")
    df = df.reset_index(drop=True)
    return df


df_news_kr_final     = finalize_df(df_news_kr.copy())
df_news_en_final     = finalize_df(df_news_en.copy())
df_price_final       = finalize_df(df_price.copy())
df_sec_filings_final = finalize_df(df_sec_filings.copy())

# A안 — 오늘 새로 수집된 행에만 collected_date(KST) 스탬프.
# 점수 산출 시 "오늘 처음 들어온 데이터" 신규성 판정 기준.
# price 는 신규/지속 구분 안 쓰니 스탬프 생략.
df_news_kr_final     = _stamp_collected_date(df_news_kr_final)
df_news_en_final     = _stamp_collected_date(df_news_en_final)
df_sec_filings_final = _stamp_collected_date(df_sec_filings_final)


# Drive에 누적 저장 (기존 파일 + 신규 데이터 병합)
df_news_kr_merged     = merge_and_dedup(
    news_kr_drive_path, df_news_kr_final,
    pk_cols=["title", "published_at", "publisher"],
    date_cols=["published_at"],
)
df_news_en_merged     = merge_and_dedup(
    news_en_drive_path, df_news_en_final,
    pk_cols=["title", "published_at", "publisher"],
    date_cols=["published_at"],
)
df_price_merged       = merge_and_dedup(price_drive_file_path, df_price_final,       ["base_dt", "ticker"])
df_sec_filings_merged = merge_and_dedup(filings_drive_path,    df_sec_filings_final, ["accession_number"])

df_news_kr_merged.to_csv(news_kr_drive_path,     index=False, encoding="utf-8-sig")
df_news_en_merged.to_csv(news_en_drive_path,     index=False, encoding="utf-8-sig")
df_price_merged.to_csv(price_drive_file_path,    index=False, encoding="utf-8-sig")
df_sec_filings_merged.to_csv(filings_drive_path, index=False, encoding="utf-8-sig")


# Drive에 오늘 신규 수집분 저장 (자동 다운로드 X)
df_news_kr_final.to_csv(news_kr_today_drive_path,     index=False, encoding="utf-8-sig")
df_news_en_final.to_csv(news_en_today_drive_path,     index=False, encoding="utf-8-sig")
df_price_final.to_csv(price_today_drive_path,         index=False, encoding="utf-8-sig")
df_sec_filings_final.to_csv(filings_today_drive_path, index=False, encoding="utf-8-sig")


# 로그 출력
print(f"\n[KR]    누적 저장: {news_kr_drive_path} (총 {len(df_news_kr_merged)}건)")
print(f"[EN]    누적 저장: {news_en_drive_path} (총 {len(df_news_en_merged)}건)")
print(f"[PRICE] 누적 저장: {price_drive_file_path} (총 {len(df_price_merged)}건)")
print(f"[공시]  누적 저장: {filings_drive_path} (총 {len(df_sec_filings_merged)}건)")

print(f"\n[KR]    오늘분 저장: {news_kr_today_drive_path} ({len(df_news_kr_final)}건)")
print(f"[EN]    오늘분 저장: {news_en_today_drive_path} ({len(df_news_en_final)}건)")
print(f"[PRICE] 오늘분 저장: {price_today_drive_path} ({len(df_price_final)}건)")
print(f"[공시]  오늘분 저장: {filings_today_drive_path} ({len(df_sec_filings_final)}건)")


print(f"\n[KR]    누적 저장: {news_kr_drive_path} (총 {len(df_news_kr_merged)}건)")
# ... 기존 print들 ...

print(f"\n💾 Drive 저장 완료. 자동 다운로드는 마지막 셀에서 일괄 처리.")


# ============================================
# 15-1) 수익률 계산 함수 정의 → price_history.csv 기반 / FRED 지표는 제외 (절대값 추이만 대시보드에서 사용)
# ============================================

# 티커 카테고리 매핑 (주가만)
TICKER_CATEGORY_MAP = {
    # 상장 BDC
    "OBDC": "BDC", "OTF": "BDC", "BXSL": "BDC", "ARCC": "BDC", "FSK": "BDC",
    # 운용사
    "OWL": "Capital", "BX": "Capital", "ARES": "Capital", "APO": "Capital", "KKR": "Capital",
    # 벤치마크
    "BIZD": "BM", "^GSPC": "BM", "HYG": "BM",
}

# 기준 영업일 수
PERIOD_DAYS_MAP = {
    "1d":  1,
    "1w":  5,
    "1m":  21,
    "3m":  63,
    "6m":  126,
    "1y":  252,
}


def calculate_returns(price_history_path, output_path=None):
    """
    price_history.csv → 티커별 수익률 계산 (FRED 제외).

    Parameters
    ----------
    price_history_path : str
        price_history.csv 경로
    output_path : str, optional
        결과 저장 경로. None이면 저장 X

    Returns
    -------
    pd.DataFrame
        티커별 수익률 (주가 티커만, 1행씩)
    """
    # 1) 데이터 로드
    if not os.path.exists(price_history_path):
        print(f"[ERROR] 파일 없음: {price_history_path}")
        return pd.DataFrame()

    df = pd.read_csv(price_history_path, encoding="utf-8-sig")
    if df.empty:
        print("[WARN] 데이터 없음")
        return pd.DataFrame()

    # 2) 정리
    df["base_dt"] = pd.to_datetime(df["base_dt"], errors="coerce")
    df = df.dropna(subset=["base_dt", "close"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"])

    # 주가 티커만 필터 (FRED 제외)
    df = df[df["ticker"].isin(TICKER_CATEGORY_MAP.keys())].copy()
    df = df.sort_values(["ticker", "base_dt"]).reset_index(drop=True)

    if df.empty:
        print("[WARN] 주가 데이터 없음")
        return pd.DataFrame()

    print(f"📊 수익률 계산 시작")
    print(f"   데이터: {len(df):,}행 (주가만)")
    print(f"   기간: {df['base_dt'].min().date()} ~ {df['base_dt'].max().date()}")
    print(f"   티커: {df['ticker'].nunique()}개")
    print("-" * 50)

    # 3) 티커별 수익률 계산
    results = []

    for ticker in df["ticker"].unique():
        df_t = df[df["ticker"] == ticker].copy().reset_index(drop=True)

        if df_t.empty:
            continue

        category = TICKER_CATEGORY_MAP.get(ticker, "other")
        latest_row = df_t.iloc[-1]
        latest_dt  = latest_row["base_dt"]
        latest_val = latest_row["close"]
        entity     = latest_row["entity"]

        row = {
            "ticker":   ticker,
            "entity":   entity,
            "category": category,
            "base_dt":  latest_dt.strftime("%Y-%m-%d"),
            "close":    round(latest_val, 4),
        }

        # 1D, 1W, 1M, 3M, 6M 계산
        for period, days in PERIOD_DAYS_MAP.items():
            if len(df_t) <= days:
                row[f"return_{period}"] = None
                continue

            past_val = df_t.iloc[-1 - days]["close"]

            if past_val == 0:
                row[f"return_{period}"] = None
            else:
                ret = (latest_val - past_val) / past_val * 100
                row[f"return_{period}"] = round(ret, 2)

        # YTD 계산 (현재 연도 첫 영업일 대비)
        current_year = latest_dt.year
        df_ytd = df_t[df_t["base_dt"].dt.year == current_year]

        if len(df_ytd) > 0:
            ytd_start_val = df_ytd.iloc[0]["close"]
            if ytd_start_val == 0:
                row["return_ytd"] = None
            else:
                ret = (latest_val - ytd_start_val) / ytd_start_val * 100
                row["return_ytd"] = round(ret, 2)
        else:
            row["return_ytd"] = None

        results.append(row)

    if not results:
        print("[WARN] 수익률 계산 결과 없음")
        return pd.DataFrame()

    # 4) DataFrame 생성
    df_returns = pd.DataFrame(results)

    # 카테고리별 정렬
    category_order = {"BDC": 0, "Capital": 1, "BM": 2, "other": 3}
    df_returns["_order"] = df_returns["category"].map(category_order)
    df_returns = df_returns.sort_values(["_order", "ticker"]).drop(columns=["_order"])
    df_returns = df_returns.reset_index(drop=True)

    # 컬럼 순서
    cols = [
        "ticker", "entity", "category", "base_dt", "close",
        "return_1d", "return_1w", "return_1m",
        "return_3m", "return_6m", "return_1y","return_ytd",
    ]
    df_returns = df_returns[cols]

    # 5) 저장
    if output_path:
        df_returns.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"✅ 저장 완료: {output_path}")

    return df_returns


print("✅ 수익률 계산 함수 정의 완료")


# ============================================
# 15-2) 수익률 계산 (price_history.csv 기반)
# ============================================

# 티커 카테고리 매핑 (주가만, FRED 제외)
TICKER_CATEGORY_MAP = {
    "OBDC": "BDC", "OTF": "BDC", "BXSL": "BDC", "ARCC": "BDC", "FSK": "BDC",
    "OWL": "Capital", "BX": "Capital", "ARES": "Capital", "APO": "Capital", "KKR": "Capital",
    "BIZD": "BM", "^GSPC": "BM", "HYG": "BM",
}

# 기준 영업일 수
PERIOD_DAYS_MAP = {
    "1d":  1,
    "1w":  5,
    "1m":  21,
    "3m":  63,
    "6m":  126,
    "1y":  252,
}


def calculate_returns(price_history_path, output_path=None):
    """price_history.csv → 티커별 수익률 계산 (FRED 제외)"""

    if not os.path.exists(price_history_path):
        print(f"[ERROR] 파일 없음: {price_history_path}")
        return pd.DataFrame()

    df = pd.read_csv(price_history_path, encoding="utf-8-sig")
    if df.empty:
        print("[WARN] 데이터 없음")
        return pd.DataFrame()

    df["base_dt"] = pd.to_datetime(df["base_dt"], errors="coerce")
    df = df.dropna(subset=["base_dt", "close"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"])

    # 주가 티커만 필터 (FRED 제외)
    df = df[df["ticker"].isin(TICKER_CATEGORY_MAP.keys())].copy()
    df = df.sort_values(["ticker", "base_dt"]).reset_index(drop=True)

    if df.empty:
        print("[WARN] 주가 데이터 없음")
        return pd.DataFrame()

    print(f"📊 수익률 계산 시작")
    print(f"   데이터: {len(df):,}행 (주가만)")
    print(f"   기간: {df['base_dt'].min().date()} ~ {df['base_dt'].max().date()}")
    print(f"   티커: {df['ticker'].nunique()}개")
    print("-" * 50)

    results = []
    for ticker in df["ticker"].unique():
        df_t = df[df["ticker"] == ticker].copy().reset_index(drop=True)
        if df_t.empty:
            continue

        category = TICKER_CATEGORY_MAP.get(ticker, "other")
        latest_row = df_t.iloc[-1]
        latest_dt  = latest_row["base_dt"]
        latest_val = latest_row["close"]
        entity     = latest_row["entity"]

        row = {
            "ticker":   ticker,
            "entity":   entity,
            "category": category,
            "base_dt":  latest_dt.strftime("%Y-%m-%d"),
            "close":    round(latest_val, 4),
        }

        # 기간별 수익률
        for period, days in PERIOD_DAYS_MAP.items():
            if len(df_t) <= days:
                row[f"return_{period}"] = None
                continue
            past_val = df_t.iloc[-1 - days]["close"]
            if past_val == 0:
                row[f"return_{period}"] = None
            else:
                ret = (latest_val - past_val) / past_val * 100
                row[f"return_{period}"] = round(ret, 2)

        # YTD
        current_year = latest_dt.year
        df_ytd = df_t[df_t["base_dt"].dt.year == current_year]
        if len(df_ytd) > 0:
            ytd_start_val = df_ytd.iloc[0]["close"]
            if ytd_start_val == 0:
                row["return_ytd"] = None
            else:
                ret = (latest_val - ytd_start_val) / ytd_start_val * 100
                row["return_ytd"] = round(ret, 2)
        else:
            row["return_ytd"] = None

        results.append(row)

    if not results:
        print("[WARN] 수익률 계산 결과 없음")
        return pd.DataFrame()

    df_returns = pd.DataFrame(results)

    # 카테고리별 정렬
    category_order = {"BDC": 0, "Capital": 1, "BM": 2, "other": 3}
    df_returns["_order"] = df_returns["category"].map(category_order)
    df_returns = df_returns.sort_values(["_order", "ticker"]).drop(columns=["_order"])
    df_returns = df_returns.reset_index(drop=True)

    cols = [
        "ticker", "entity", "category", "base_dt", "close",
        "return_1d", "return_1w", "return_1m",
        "return_3m", "return_6m", "return_1y", "return_ytd",
    ]
    df_returns = df_returns[cols]

    if output_path:
        df_returns.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"✅ 저장 완료: {output_path}")

    return df_returns


# 실행 - 수익률 계산
returns_output_path = f"{SAVE_DIR}/private_credit_returns_latest.csv"

df_returns = calculate_returns(
    price_history_path = price_drive_file_path,  # 14번에서 정의된 변수 재사용
    output_path        = returns_output_path
)

if not df_returns.empty:
    print(f"\n📊 수익률 계산 결과: {len(df_returns)}개 티커")
    print("=" * 80)

    # 카테고리별 출력
    for cat, cat_name in [
        ("BDC",       "📊상장 BDC"),
        ("Capital",   "🏛️운용사"),
        ("BM", "📈벤치마크"),
    ]:
        df_sub = df_returns[df_returns["category"] == cat]
        if df_sub.empty:
            continue

        print(f"\n{cat_name}")
        print("-" * 80)
        display_cols = ["ticker", "entity", "base_dt", "close",
                         "return_1d", "return_1w", "return_1m",
                         "return_3m", "return_6m", "return_ytd"]
        print(df_sub[display_cols].to_string(index=False))



# ============================================
# 15-3) 연초부터 시계열 수익률 계산
# ============================================
def calculate_returns_timeseries(price_history_path,
                                   start_date=None,
                                   output_path=None):
    """
    특정 시점부터 오늘까지 각 영업일별 수익률 시계열 계산.

    Parameters
    ----------
    price_history_path : str
        price_history.csv 경로
    start_date : str or pd.Timestamp, optional
        시작일. None이면 YTD (현재 연도 시작)
    output_path : str, optional
        저장 경로

    Returns
    -------
    pd.DataFrame
        티커 × 영업일 수익률 시계열
    """
    # 1) 데이터 로드
    if not os.path.exists(price_history_path):
        print(f"[ERROR] 파일 없음: {price_history_path}")
        return pd.DataFrame()

    df = pd.read_csv(price_history_path, encoding="utf-8-sig")
    if df.empty:
        return pd.DataFrame()

    df["base_dt"] = pd.to_datetime(df["base_dt"], errors="coerce")
    df = df.dropna(subset=["base_dt", "close"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"])

    # 주가 티커만
    df = df[df["ticker"].isin(TICKER_CATEGORY_MAP.keys())].copy()
    df = df.sort_values(["ticker", "base_dt"]).reset_index(drop=True)

    if df.empty:
        print("[WARN] 주가 데이터 없음")
        return pd.DataFrame()

    # 2) 시작일 설정 (default: YTD)
    if start_date is None:
        latest_year = df["base_dt"].max().year
        start_date = pd.Timestamp(year=latest_year, month=1, day=1)
    else:
        start_date = pd.Timestamp(start_date)

    print(f"📊 시계열 수익률 계산")
    print(f"   시작일: {start_date.date()}")
    print(f"   종료일: {df['base_dt'].max().date()}")
    print(f"   티커: {df['ticker'].nunique()}개")
    print("-" * 50)

    # 3) 티커별로 시계열 계산
    all_rows = []

    for ticker in df["ticker"].unique():
        df_t = df[df["ticker"] == ticker].copy().sort_values("base_dt").reset_index(drop=True)
        if df_t.empty:
            continue

        category = TICKER_CATEGORY_MAP.get(ticker, "other")
        entity = df_t.iloc[0]["entity"]

        # YTD 기준점: 현재 연도 첫 영업일 (해당 연도 첫 데이터)
        latest_year = df_t["base_dt"].max().year
        df_current_year = df_t[df_t["base_dt"].dt.year == latest_year]
        if df_current_year.empty:
            continue
        ytd_base_val = df_current_year.iloc[0]["close"]

        # 시작일 이후 각 영업일별로 계산
        df_target = df_t[df_t["base_dt"] >= start_date].copy()

        for idx_t, row_t in df_target.iterrows():
            base_dt    = row_t["base_dt"]
            latest_val = row_t["close"]

            # 원래 df_t에서 현재 날짜의 인덱스 찾기
            current_idx = df_t.index[df_t["base_dt"] == base_dt][0]

            row_out = {
                "ticker":   ticker,
                "entity":   entity,
                "category": category,
                "base_dt":  base_dt.strftime("%Y-%m-%d"),
                "close":    round(latest_val, 4),
            }

            # 1D, 1W, 1M, 3M, 6M, 1y
            for period, days in PERIOD_DAYS_MAP.items():
                if current_idx < days:
                    # 해당 기간의 과거 데이터 없음
                    row_out[f"return_{period}"] = None
                    continue

                past_val = df_t.iloc[current_idx - days]["close"]
                if past_val == 0:
                    row_out[f"return_{period}"] = None
                else:
                    ret = (latest_val - past_val) / past_val * 100
                    row_out[f"return_{period}"] = round(ret, 2)

            # YTD (해당 연도 첫 영업일 대비)
            if ytd_base_val == 0:
                row_out["return_ytd"] = None
            else:
                ret = (latest_val - ytd_base_val) / ytd_base_val * 100
                row_out["return_ytd"] = round(ret, 2)

            all_rows.append(row_out)

    if not all_rows:
        print("[WARN] 계산 결과 없음")
        return pd.DataFrame()

    # 4) DataFrame 생성 및 정렬
    df_series = pd.DataFrame(all_rows)

    category_order = {"BDC": 0, "Capital": 1, "BM": 2, "other": 3}
    df_series["_order"] = df_series["category"].map(category_order)
    df_series["_dt"]    = pd.to_datetime(df_series["base_dt"])
    df_series = df_series.sort_values(["_order", "ticker", "_dt"])
    df_series = df_series.drop(columns=["_order", "_dt"])
    df_series = df_series.reset_index(drop=True)

    cols = [
        "ticker", "entity", "category", "base_dt", "close",
        "return_1d", "return_1w", "return_1m",
        "return_3m", "return_6m", "return_1y", "return_ytd",
    ]
    df_series = df_series[cols]

    # 5) 저장
    if output_path:
        df_series.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"✅ 저장 완료: {output_path}")
        print(f"   총 {len(df_series):,}행 ({df_series['ticker'].nunique()}개 티커 × 영업일)")

    return df_series


# 실행 - YTD 시계열 수익률 계산
returns_series_output_path = f"{SAVE_DIR}/private_credit_returns_ytd_series.csv"

df_returns_series = calculate_returns_timeseries(
    price_history_path = price_drive_file_path,
    start_date         = None,  # None = YTD (올해 1/1 이후)
    output_path        = returns_series_output_path
)

if not df_returns_series.empty:
    print(f"\n📊 YTD 시계열 수익률: {len(df_returns_series):,}행")

    # OBDC 샘플만 미리보기
    sample = df_returns_series[df_returns_series["ticker"] == "OBDC"].head(10)
    print("\n[샘플] OBDC 처음 10영업일:")
    print(sample[["base_dt", "close", "return_1d", "return_1w", "return_1m", "return_ytd"]].to_string(index=False))

    print("\n[샘플] OBDC 최근 5영업일:")
    sample_tail = df_returns_series[df_returns_series["ticker"] == "OBDC"].tail(5)
    print(sample_tail[["base_dt", "close", "return_1d", "return_1w", "return_1m", "return_ytd"]].to_string(index=False))


# ============================================
# 16) 모든 누적 파일 일괄 자동 다운로드
# ============================================
import shutil

# 자동 다운로드 대상 (today 4개 + 누적 periodic 1개)
download_targets = [
    news_kr_today_drive_path,
    news_en_today_drive_path,
    filings_today_drive_path,
    price_today_drive_path,
    periodic_path,
]

# Colab 전용 자동 다운로드 섹션 SKIP — 로컬/HF 환경에서는 파일이 이미 data/ 에 있음.
print("\n[INFO] Colab 'files.download' 섹션 SKIP — 로컬/HF 에선 불필요")

# (HF push 는 모든 batch 단계 끝난 후 entrypoint.sh 에서 일괄 실행 — 요약/점수까지 누적)

# ============================================
# 일회성 백필 섹션들 — 환경변수로 제어
# 기본 SKIP. 필요할 때만 RUN_BACKFILL=true 설정해 활성화.
# ============================================
_RUN_BACKFILL = os.environ.get("RUN_BACKFILL", "false").lower() == "true"
if not _RUN_BACKFILL:
    print("\n[INFO] 일회성 백필 섹션 SKIP (RUN_BACKFILL=true 로 활성)")
    print("        - 2025-09-30 정기공시 스니펫 추출 SKIP")
    print("        - BDC 7곳 가장 최근 정기공시 백필 SKIP")
    print("        - news_global 디코딩 백필 SKIP")
    print("        - sec_filings 합성 키 백필 SKIP")
    import sys as _sys
    _sys.exit(0)

# ============================================
# 일회성 — 2025-09-30 정기공시 스니펫 추출 + 다운로드
# (자체 완결형: 다른 셀 의존성 없음)
# ============================================

# --- 1) 라이브러리 (Drive 마운트 제거 — 위 0번 섹션에서 SAVE_DIR 이미 설정됨) ---
import os, re, json, requests, html  # noqa: F811 — Colab 셀 export 잔재, 재선언 무해
import pandas as pd  # noqa: F811
from bs4 import BeautifulSoup


# --- 2) 설정 — SAVE_DIR 은 상단 (Path 기반) 이미 설정됨 ---
SEC_HEADERS = {"User-Agent": "USPrivateCreditProject spark@kiwoom.com"}
TARGET_PERIOD_END = "2025-09-30"  # 원하는 분기 (변경 가능)

BDC_CIK_MAP = {
    "0001655888": "Blue Owl Capital Corp (OBDC)",
    "0001655887": "Blue Owl Capital Corp II (OBDC II)",
    "0001812554": "Blue Owl Credit Income Corp (OCIC)",
    "0001869453": "Blue Owl Technology Income Corp (OTIC)",
    "0001803498": "Blackstone Private Credit Fund (BCRED)",
    "0001287750": "Ares Capital Corp (ARCC)",
    "0001422183": "FS KKR Capital Corp (FSK)",
}


# --- 3) SEC submissions 조회 ---
def get_submissions_data(cik):
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    try:
        res = requests.get(url, headers=SEC_HEADERS, timeout=(10, 30))
        if res.status_code != 200:
            return None
        return res.json()
    except Exception as e:
        print(f"[ERROR] {cik}: {e}")
        return None


# --- 4) context_map 추출 (XBRL 날짜 매핑) ---
def extract_context_map(html_str):
    from bs4 import XMLParsedAsHTMLWarning
    import warnings
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

    soup = BeautifulSoup(html_str, "lxml")
    context_map = {}
    for ctx in soup.find_all("xbrli:context"):
        ctx_id = ctx.get("id")
        if not ctx_id:
            continue
        instant = ctx.find("xbrli:instant")
        if instant:
            context_map[ctx_id] = {"type": "instant", "date": instant.get_text(strip=True)}
            continue
        start = ctx.find("xbrli:startdate")
        end = ctx.find("xbrli:enddate")
        if start and end:
            context_map[ctx_id] = {
                "type": "duration",
                "start_date": start.get_text(strip=True),
                "end_date": end.get_text(strip=True),
            }
    return context_map


# --- 5) 테이블 압축 ---
def compress_tables(tables):
    compressed = []
    for table in tables:
        rows_out = []
        for row in table.get("rows", []):
            cells_out = []
            for cell in row.get("cells", []):
                if not cell.get("raw_text", "").strip():
                    continue
                c = {
                    "cell_id": cell["cell_id"],
                    "row_index": cell["row_index"],
                    "col_index": cell["col_index"],
                    "raw_text": cell["raw_text"],
                }
                if cell.get("numeric_value") is not None:
                    c["numeric_value"] = cell["numeric_value"]
                if cell.get("concept"):
                    c["concept"] = cell["concept"]
                    c["contextRef"] = cell.get("contextRef")
                    c["unitRef"] = cell.get("unitRef")
                    c["decimals"] = cell.get("decimals")
                cells_out.append(c)
            if cells_out:
                rows_out.append({"row_index": row["row_index"], "cells": cells_out})
        if rows_out:
            compressed.append({"table_id": table["table_id"], "rows": rows_out})
    return compressed


# --- 6) HTML → 구조화 JSON ---
def html_to_structured_json(html_str, filing_id="filing"):
    from bs4 import XMLParsedAsHTMLWarning
    import warnings
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

    html_str = re.sub(r"<ix:header[^>]*>.*?</ix:header>", "", html_str,
                       flags=re.IGNORECASE | re.DOTALL)
    soup = BeautifulSoup(html_str, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()

    tables = []

    def extract_ix_meta(cell_tag):
        meta = {}
        for ix in cell_tag.find_all("ix:nonfraction"):
            meta["concept"] = ix.get("name")
            meta["contextRef"] = ix.get("contextref")
            meta["unitRef"] = ix.get("unitref")
            meta["decimals"] = ix.get("decimals")
            meta["scale"] = ix.get("scale")
            meta["sign"] = ix.get("sign")
            break
        if not meta:
            for ix in cell_tag.find_all("ix:nonnumeric"):
                meta["concept"] = ix.get("name")
                meta["contextRef"] = ix.get("contextref")
                meta["unitRef"] = None
                meta["decimals"] = None
                break
        return meta

    def parse_number(s, scale=None, sign=None):
        if not s:
            return None
        s = s.strip()
        neg = s.startswith("(") and s.endswith(")")
        if neg:
            s = s[1:-1]
        s = re.sub(r"[^0-9.\-]", "", s.replace(",", ""))
        try:
            val = float(s)
            if scale:
                try:
                    val = val * (10 ** int(scale))
                except:
                    pass
            if sign == "-":
                val = -val
            elif neg:
                val = -val
            return val
        except:
            return None

    for t_idx, tbl in enumerate(soup.find_all("table")):
        table_id = f"{filing_id}__t{t_idx}"
        grid = []
        rows_out = []
        for r_idx, tr in enumerate(tbl.find_all("tr")):
            while len(grid) <= r_idx:
                grid.append([])
            col_pos = 0
            row_cells = []
            for cell in tr.find_all(["th", "td"]):
                while col_pos < len(grid[r_idx]) and grid[r_idx][col_pos] is not None:
                    col_pos += 1
                colspan = int(cell.get("colspan", 1))
                rowspan = int(cell.get("rowspan", 1))
                raw_text = cell.get_text(" ", strip=True)
                ix_meta = extract_ix_meta(cell)
                num_val = parse_number(raw_text, scale=ix_meta.get("scale"), sign=ix_meta.get("sign"))
                cell_id = f"{table_id}__r{r_idx}__c{col_pos}"
                row_cells.append({
                    "cell_id": cell_id, "row_index": r_idx, "col_index": col_pos,
                    "rowspan": rowspan, "colspan": colspan,
                    "raw_text": raw_text, "numeric_value": num_val,
                    "concept": ix_meta.get("concept"),
                    "contextRef": ix_meta.get("contextRef"),
                    "unitRef": ix_meta.get("unitRef"),
                    "decimals": ix_meta.get("decimals"),
                })
                for dr in range(rowspan):
                    ri = r_idx + dr
                    while len(grid) <= ri:
                        grid.append([])
                    need = col_pos + colspan - len(grid[ri])
                    if need > 0:
                        grid[ri].extend([None] * need)
                    for dc in range(colspan):
                        grid[ri][col_pos + dc] = cell_id
                col_pos += colspan
            if row_cells:
                rows_out.append({"row_index": r_idx, "cells": row_cells})
        if rows_out:
            tables.append({"table_id": table_id, "rows": rows_out})

    for tbl in soup.find_all("table"):
        tbl.replace_with("\n__TABLE_EXTRACTED__\n")
    for ix in soup.find_all(lambda t: t.name and t.name.lower().startswith("ix:")):
        ix.replace_with(ix.get_text())

    plain_text = soup.get_text(separator="\n")
    plain_text = re.sub(r"\n{3,}", "\n\n", plain_text).strip()

    return {"filing_id": filing_id, "tables": tables, "text": plain_text}


# --- 7) 정기공시 JSON 저장 ---
def save_periodic_filing(cik, fund_name, filing_info):
    accession = filing_info["accession_number"]
    form_type = filing_info["form"]
    period_end = filing_info["period_end"]
    filed_date = filing_info["filed_date"]

    data = get_submissions_data(cik)
    if data is None:
        return ""
    filings = data.get("filings", {}).get("recent", {})
    acc_list = filings.get("accessionNumber", [])
    doc_list = filings.get("primaryDocument", [])

    primary_doc = ""
    for acc, doc in zip(acc_list, doc_list):
        if acc == accession:
            primary_doc = doc
            break
    if not primary_doc:
        print(f"  [WARN] primaryDocument 없음")
        return ""

    acc_clean = accession.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/{primary_doc}"
    print(f"  [INFO] 문서 다운로드: {primary_doc}")
    res = requests.get(url, headers=SEC_HEADERS)
    if res.status_code != 200:
        print(f"  [ERROR] 본문 다운로드 실패")
        return ""

    raw_html = res.text
    print(f"  [INFO] HTML {len(raw_html):,}자")

    structured = html_to_structured_json(raw_html, filing_id=f"{cik}__{form_type}__{period_end}")
    structured["tables"] = compress_tables(structured["tables"])
    context_map = extract_context_map(raw_html)
    print(f"  [INFO] 테이블 {len(structured['tables'])}개, context {len(context_map)}개")

    output = {
        "meta": {
            "cik": cik, "fund_name": fund_name, "form": form_type,
            "period_end": period_end, "filed_date": filed_date,
            "table_count": len(structured["tables"]),
        },
        "context_map": context_map,
        "text": structured["text"],
        "tables": structured["tables"],
    }

    safe_name = re.sub(r"[^\w\s-]", "", fund_name).strip().replace(" ", "_")
    file_name = f"{safe_name}_{form_type}_{period_end}.json"
    drive_dir = f"{SAVE_DIR}/sec_filings_json"
    drive_path = f"{drive_dir}/{file_name}"
    os.makedirs(drive_dir, exist_ok=True)

    with open(drive_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"  [저장] {file_name} ({os.path.getsize(drive_path)/1024/1024:.1f}MB)")
    return drive_path


# --- 8) 스니펫 추출 ---
def save_relevant_snippets(json_path, output_dir):
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    meta = data.get("meta", {})
    text = data.get("text", "")
    tables = data.get("tables", [])
    context_map = data.get("context_map", {})

    KEYWORDS = [
        "pik interest income", "pik dividend income",
        "payment-in-kind interest income", "payment-in-kind dividend income",
        "total investment income",
        "loans on non-accrual status",
        "percentage of assets on non-accrual",
        "amortized cost of our performing and non-accrual debt instruments",
        "% of investments on non-accrual (based on fair value)",
        "at amortized cost, loans on non-accrual status",
        "non-accrual",
        "net asset value per share",
        "net asset value per class",
        "net asset value per class s",
        "net asset value per class d",
        "net asset value per class i",
    ]

    def resolve_context(ctx_id):
        if not ctx_id or ctx_id not in context_map:
            return ctx_id
        info = context_map[ctx_id]
        if info.get("type") == "instant":
            return info.get("date", ctx_id)
        return f"{info.get('start_date')}~{info.get('end_date')}"

    def matches_keyword(s):
        s_lower = s.lower()
        return any(kw in s_lower for kw in KEYWORDS)

    relevant_texts = [p.strip() for p in text.split("\n\n") if matches_keyword(p)]

    relevant_tables = []
    for table in tables:
        all_cells = [c for r in table["rows"] for c in r["cells"]]
        table_text = " ".join(c.get("raw_text", "") for c in all_cells)
        if not matches_keyword(table_text):
            continue
        rows_out = []
        for row in table["rows"]:
            cells_out = []
            for cell in row["cells"]:
                c = dict(cell)
                if c.get("contextRef"):
                    c["contextRef"] = resolve_context(c["contextRef"])
                cells_out.append(c)
            rows_out.append({"row_index": row["row_index"], "cells": cells_out})
        relevant_tables.append({"table_id": table["table_id"], "rows": rows_out})

    output = {"meta": meta, "texts": relevant_texts, "tables": relevant_tables}

    os.makedirs(output_dir, exist_ok=True)
    base_name = os.path.basename(json_path).replace(".json", "_snippet.json")
    output_path = os.path.join(output_dir, base_name)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    size_kb = os.path.getsize(output_path) / 1024
    print(f"  [스니펫] 텍스트 {len(relevant_texts)}개 | 테이블 {len(relevant_tables)}개 | {size_kb:.0f}KB")
    return output_path


# ============================================
# 메인 실행
# ============================================
import shutil

snippet_dir = f"{SAVE_DIR}/sec_filings_json/snippets"
os.makedirs(snippet_dir, exist_ok=True)

print("=" * 60)
print(f"📋 정기공시 스니펫 추출 ({TARGET_PERIOD_END})")
print("=" * 60)

snippet_files = []

for cik, fund_name in BDC_CIK_MAP.items():
    print(f"\n[{fund_name}]")

    data = get_submissions_data(cik)
    if data is None:
        print("  [SKIP] submissions 조회 실패")
        continue

    filings = data.get("filings", {}).get("recent", {})
    df = pd.DataFrame({
        "form": filings.get("form", []),
        "filingDate": filings.get("filingDate", []),
        "reportDate": filings.get("reportDate", []),
        "accessionNumber": filings.get("accessionNumber", []),
    })

    if df.empty:
        print("  [SKIP] 공시 데이터 없음")
        continue

    df_periodic = df[
        df["form"].isin(["10-K", "10-Q", "10-K/A", "10-Q/A"]) &
        (df["reportDate"] == TARGET_PERIOD_END)
    ].copy()

    if df_periodic.empty:
        print(f"  [SKIP] {TARGET_PERIOD_END} 정기공시 없음")
        continue

    df_periodic = df_periodic.sort_values("filingDate", ascending=False)
    target = df_periodic.iloc[0]

    print(f"  ✅ 발견: {target['form']} | filed {target['filingDate']}")

    filing_info = {
        "form": target["form"],
        "period_end": target["reportDate"],
        "filed_date": target["filingDate"],
        "accession_number": target["accessionNumber"],
    }

    try:
        json_path = save_periodic_filing(cik, fund_name, filing_info)
        if not json_path:
            continue
    except Exception as e:
        print(f"  [ERROR] JSON: {e}")
        continue

    try:
        snippet_path = save_relevant_snippets(json_path, output_dir=snippet_dir)
        snippet_files.append(snippet_path)
    except Exception as e:
        print(f"  [ERROR] 스니펫: {e}")
        continue

# ============================================
# 스니펫 자동 다운로드
# ============================================
print("\n" + "=" * 60)
print(f"📥 스니펫 다운로드 ({len(snippet_files)}개)")
print("=" * 60)

for drive_path in snippet_files:
    fname = os.path.basename(drive_path)
    local_copy = drive_path   # 로컬/HF 에서는 이미 data/ 에 저장돼 있음 (Colab /content 의존성 제거)

    if not os.path.exists(drive_path):
        print(f"  [SKIP] {fname}")
        continue

    try:
        shutil.copy(drive_path, local_copy)
        files.download(local_copy)
        print(f"  ✅ {fname}")
    except Exception as e:
        print(f"  [WARN] {fname}: {e}")

print(f"\n✅ 완료")
print(f"\n📝 LLM 직접 입력 가이드:")
print(f"   1. 다운로드된 *_snippet.json 파일 열기")
print(f"   2. 내용 복사 → Claude.ai 또는 ChatGPT에 붙여넣기")
print(f"   3. 프롬프트로 NAV/PIK/Non-accrual 추출")

import shutil  # noqa: F811

snippet_dir = f"{SAVE_DIR}/sec_filings_json/snippets"

# 9월말 분기 스니펫만 모아서 zip — 로컬 data/ 안에 저장 (Colab files.download 제거)
if os.path.isdir(snippet_dir):
    zip_path = f"{SAVE_DIR}/snippets_2025_09_30"
    shutil.make_archive(
        base_name=zip_path,
        format="zip",
        root_dir=snippet_dir,
        base_dir="."   # 현재 폴더 전체
    )
    zip_file = f"{zip_path}.zip"
    print(f"✅ 압축 완료: {zip_file}")
    print(f"   크기: {os.path.getsize(zip_file)/1024:.0f}KB")

# ============================================
# 17) 일회성 백필 — BDC 7곳의 가장 최근 정기공시 지표 추출
# ============================================
"""
매일 자동 파이프라인은 최근 2영업일만 처리하므로,
오래 전에 제출된 정기공시는 누락된 상태.
이 셀은 BDC 7곳의 가장 최근 정기공시 1건씩 처리해서
periodic_metrics.csv에 백필.

- 이미 처리된 공시는 스킵 (LLM 재호출 X)
- 처음 실행 시: 7건 처리 (BDC 7곳)
- 두 번째 실행 시: 0건 (모두 이미 처리됨)
"""

if not ANTHROPIC_API_KEY:
    print("[ERROR] ANTHROPIC_API_KEY 없음 — 백필 불가")
else:
    metrics_csv_path = f"{SAVE_DIR}/private_credit_sec_periodic_history.csv"
    snippet_dir      = f"{SAVE_DIR}/sec_filings_json/snippets"
    os.makedirs(snippet_dir, exist_ok=True)

    print("=" * 60)
    print("📋 정기공시 백필 — BDC 7곳 가장 최근 1건씩")
    print("=" * 60)

    backfill_rows = []

    for cik, fund_name in BDC_CIK_MAP.items():
        print(f"\n[{fund_name}]")

        # 1) 가장 최근 정기공시 정보 조회
        filing_info = get_latest_periodic_filing_info(cik)
        if not filing_info:
            print("  [SKIP] 정기공시 없음")
            continue

        form       = filing_info["form"]
        period_end = filing_info["period_end"]
        filed_date = filing_info["filed_date"]
        accession  = filing_info["accession_number"]

        print(f"  최근 정기공시: {form} | period_end {period_end} | filed {filed_date}")

        # 2) 이미 처리된 공시인지 확인 (LLM 재호출 방지)
        if is_already_processed(cik, form, period_end, metrics_csv_path):
            print(f"  [SKIP] 이미 private_credit_sec_periodic_history.csv에 있음")
            continue

        # 3) JSON 저장
        try:
            json_path = save_periodic_filing_by_sections(cik, fund_name, filing_info)
            if not json_path:
                print(f"  [SKIP] JSON 저장 실패")
                continue
        except Exception as e:
            print(f"  [ERROR] JSON 저장: {e}")
            continue

        # 4) 스니펫 추출
        try:
            snippet_path = save_relevant_snippets(json_path, output_dir=snippet_dir)
            if not snippet_path:
                print(f"  [SKIP] 스니펫 저장 실패")
                continue
        except Exception as e:
            print(f"  [ERROR] 스니펫: {e}")
            continue

        # 5) 스니펫 → Claude 호출 → 지표 추출
        snippet_text = load_snippet_content(snippet_path)
        print(f"  스니펫 크기: {len(snippet_text):,}자")

        metrics = extract_metrics_from_snippet_with_claude(snippet_text, period_end)
        if not metrics or not any(v is not None for v in metrics.values()):
            print(f"  [SKIP] 지표 추출 실패")
            continue

        # 6) 결과 저장
        row = {
            "cik":              cik,
            "fund_name":        fund_name,
            "form":             form,
            "period_end":       period_end,
            "filed_date":       filed_date,
            "nav_per_share":    metrics.get("nav_per_share"),
            "nav_basis":        metrics.get("nav_basis"),
            "pik_ratio_pct":    metrics.get("pik_ratio_pct"),
            "nonaccrual_pct":   metrics.get("nonaccrual_pct"),
            "nonaccrual_basis": metrics.get("nonaccrual_basis"),
        }
        backfill_rows.append(row)

        print(f"  ✅ NAV: {metrics.get('nav_per_share')} ({metrics.get('nav_basis')})")
        print(f"     PIK: {metrics.get('pik_ratio_pct')}% | "
              f"Non-accrual: {metrics.get('nonaccrual_pct')}% ({metrics.get('nonaccrual_basis')})")

        # API rate limit 회피
        time.sleep(30)

    # 7) periodic_metrics.csv 누적 저장
    if not backfill_rows:
        print("\n[INFO] 백필할 신규 데이터 없음 — 모두 이미 처리됨")
    else:
        df_new = pd.DataFrame(backfill_rows)
        df_new = _stamp_collected_date(df_new)   # KR 수집일 스탬프 — is_new 판정용
        df_merged = merge_and_dedup(
            existing_path = metrics_csv_path,
            new_df        = df_new,
            pk_cols       = ["cik", "form", "period_end"]
        )
        df_merged.to_csv(metrics_csv_path, index=False, encoding="utf-8-sig")

        print("\n" + "=" * 60)
        print(f"✅ 백필 완료: {len(df_new)}건 추가 / 총 {len(df_merged)}건")
        print("=" * 60)

        # 결과 미리보기
        display(df_new[["fund_name", "form", "period_end", "filed_date",
                         "nav_per_share", "nav_basis",
                         "pik_ratio_pct", "nonaccrual_pct", "nonaccrual_basis"]])

# ============================================
# [일회성] 옛 history CSV 의 google rss 링크 디코딩 백필 — 자체 완결형
# (Drive 마운트 제거 — SAVE_DIR 은 상단에서 이미 설정됨)
# ============================================
import time  # noqa: F811
import shutil  # noqa: F811
import pandas as pd  # noqa: F811
from pathlib import Path  # noqa: F811
from googlenewsdecoder import gnewsdecoder  # noqa: F811

# 0) 디코딩 함수 정의
def decode_google_links(df, link_col="link"):
    """df 의 google rss 링크를 원문 URL 로 교체. 실패 시 원본 유지."""
    if df.empty or link_col not in df.columns:
        return df
    df = df.copy()
    out, fail = [], 0
    for url in df[link_col]:
        if isinstance(url, str) and "news.google.com" in url:
            try:
                r = gnewsdecoder(url, interval=1)
                if r.get("status"):
                    out.append(r["decoded_url"])
                else:
                    out.append(url); fail += 1
            except Exception:
                out.append(url); fail += 1
            time.sleep(1)
        else:
            out.append(url)
    print(f"[decode] {len(df)}건 중 실패 {fail}건")
    df[link_col] = out
    return df


# ★ 경로 — SAVE_DIR 기반 (Path 자동 설정됨)
news_en_drive_path = f"{SAVE_DIR}/private_credit_news_global_history.csv"


# 1) 백업
backup_path = Path(news_en_drive_path).with_suffix(".backup.csv")
shutil.copy(news_en_drive_path, backup_path)
print(f"[1/4] 백업 완료 → {backup_path}")

# 2) 로드 + 대상 확인
hist = pd.read_csv(news_en_drive_path, encoding="utf-8-sig")
target_count = hist["link"].astype(str).str.contains("news.google.com", na=False).sum()
print(f"[2/4] 전체 {len(hist)}건 / 디코딩 대상 {target_count}건 "
      f"(예상 소요 약 {target_count // 60}분 {target_count % 60}초)")

# 3) 디코딩 실행
hist_decoded = decode_google_links(hist)
remaining = hist_decoded["link"].astype(str).str.contains("news.google.com", na=False).sum()
print(f"[3/4] 디코딩 완료 — 남은 google rss 링크: {remaining}건 (실패)")

# 4) 저장 (덮어쓰기)
hist_decoded.to_csv(news_en_drive_path, index=False, encoding="utf-8-sig")
print(f"[4/4] 저장 완료 → {news_en_drive_path}")

print(f"\n샘플 5건 (link 가 매체 도메인으로 바뀌었는지 확인):")
display(hist_decoded[["title", "link"]].head(5))

# IPython.display 제거 — 상단의 display() / HTML stub 함수 재사용
# from IPython.display import HTML, display

links_html = "<br>".join(
    f"{i}. <a href='{url}' target='_blank'>{url}</a>"
    for i, url in enumerate(hist_decoded["link"].head(10), 1)
)
display(HTML(links_html))

# ============================================
# [일회성] FRED 1년치 백필 — 신규 추가 시리즈만
# ============================================
import time
import requests
import datetime

BACKFILL_TICKERS = ["BAMLH0A0HYM2", "DGS1", "DGS3", "DGS5"]   # 누적 부족한 것 모두
DAYS_BACK = 400

end_date   = datetime.date.today()
start_date = end_date - datetime.timedelta(days=DAYS_BACK)

all_dfs = []
for series_id in BACKFILL_TICKERS:
    print(f"백필: {series_id}")
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id":         series_id,
        "api_key":           FRED_API_KEY,
        "file_type":         "json",
        "observation_start": start_date.strftime("%Y-%m-%d"),
        "observation_end":   end_date.strftime("%Y-%m-%d"),
        "sort_order":        "asc",
    }
    res = None
    for attempt in range(4):
        res = requests.get(url, params=params, timeout=(10, 30))
        if res.status_code == 200:
            break
        if res.status_code in (500, 502, 503, 504):
            time.sleep(1 + attempt * 2)
            continue
        break

    if res is None or res.status_code != 200:
        print(f"  실패: {series_id} (status={res.status_code if res else 'no-response'})")
        continue

    obs = res.json().get("observations", [])
    df = pd.DataFrame(obs)
    df["value"]   = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])
    df["base_dt"] = df["date"]
    df["ticker"]  = series_id
    df["entity"]  = FRED_SERIES_MAP.get(series_id, "Unknown")
    df["close"]   = df["value"].astype(float)
    df = df[["base_dt", "ticker", "entity", "close"]].copy()
    print(f"  → {len(df)}건")
    all_dfs.append(df)
    time.sleep(0.5)

if all_dfs:
    df_backfill = pd.concat(all_dfs, ignore_index=True)
    print(f"\n백필 데이터: {len(df_backfill)}건")

    # 기존 누적 CSV 와 합치기
    df_merged = merge_and_dedup(price_drive_file_path, df_backfill, ["base_dt", "ticker"])
    df_merged.to_csv(price_drive_file_path, index=False, encoding="utf-8-sig")
    print(f"✅ 저장: {price_drive_file_path} (총 {len(df_merged)}건)")

import pandas as pd  # noqa: F811
# (Drive 마운트 제거 — SAVE_DIR 은 상단에서 설정됨)

filings_drive_path = f"{SAVE_DIR}/private_credit_sec_filings_history.csv"

# 1) CSV 로드
df = pd.read_csv(filings_drive_path, encoding="utf-8-sig")

# 2) 기존 중복 제거 (cik+form+filing_date 기준)
df = df.drop_duplicates(subset=["cik", "form", "filing_date"], keep="last")

# 3) accession_number 컬럼이 없으면 추가
if "accession_number" not in df.columns:
    df["accession_number"] = ""

# 4) 비어있는 accession_number 자리에 합성 키 채워서 미래 merge 시 NaN 충돌 방지
mask = df["accession_number"].isna() | (df["accession_number"].astype(str).str.strip() == "")
df.loc[mask, "accession_number"] = df.loc[mask].apply(
    lambda r: f"OLD_{r['cik']}_{r['form']}_{r['filing_date']}",
    axis=1,
)

# 5) 저장
df.to_csv(filings_drive_path, index=False, encoding="utf-8-sig")
print(f"✅ 정리 완료: {len(df)}건")

"""##수익률 계산 함수"""

# ============================================
# 15-1) 수익률 계산 함수 정의 → price_history.csv 기반 / FRED 지표는 제외 (절대값 추이만 대시보드에서 사용)
# ============================================

# 티커 카테고리 매핑 (주가만)
TICKER_CATEGORY_MAP = {
    # 상장 BDC
    "OBDC": "BDC", "OTF": "BDC", "BXSL": "BDC", "ARCC": "BDC", "FSK": "BDC",
    # 운용사
    "OWL": "Capital", "BX": "Capital", "ARES": "Capital", "APO": "Capital", "KKR": "Capital",
    # 벤치마크
    "BIZD": "BM", "^GSPC": "BM", "HYG": "BM",
}

# 기준 영업일 수
PERIOD_DAYS_MAP = {
    "1d":  1,
    "1w":  5,
    "1m":  21,
    "3m":  63,
    "6m":  126,
    "1y":  252,
}


def calculate_returns(price_history_path, output_path=None):
    """
    price_history.csv → 티커별 수익률 계산 (FRED 제외).

    Parameters
    ----------
    price_history_path : str
        price_history.csv 경로
    output_path : str, optional
        결과 저장 경로. None이면 저장 X

    Returns
    -------
    pd.DataFrame
        티커별 수익률 (주가 티커만, 1행씩)
    """
    # 1) 데이터 로드
    if not os.path.exists(price_history_path):
        print(f"[ERROR] 파일 없음: {price_history_path}")
        return pd.DataFrame()

    df = pd.read_csv(price_history_path, encoding="utf-8-sig")
    if df.empty:
        print("[WARN] 데이터 없음")
        return pd.DataFrame()

    # 2) 정리
    df["base_dt"] = pd.to_datetime(df["base_dt"], errors="coerce")
    df = df.dropna(subset=["base_dt", "close"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"])

    # 주가 티커만 필터 (FRED 제외)
    df = df[df["ticker"].isin(TICKER_CATEGORY_MAP.keys())].copy()
    df = df.sort_values(["ticker", "base_dt"]).reset_index(drop=True)

    if df.empty:
        print("[WARN] 주가 데이터 없음")
        return pd.DataFrame()

    print(f"📊 수익률 계산 시작")
    print(f"   데이터: {len(df):,}행 (주가만)")
    print(f"   기간: {df['base_dt'].min().date()} ~ {df['base_dt'].max().date()}")
    print(f"   티커: {df['ticker'].nunique()}개")
    print("-" * 50)

    # 3) 티커별 수익률 계산
    results = []

    for ticker in df["ticker"].unique():
        df_t = df[df["ticker"] == ticker].copy().reset_index(drop=True)

        if df_t.empty:
            continue

        category = TICKER_CATEGORY_MAP.get(ticker, "other")
        latest_row = df_t.iloc[-1]
        latest_dt  = latest_row["base_dt"]
        latest_val = latest_row["close"]
        entity     = latest_row["entity"]

        row = {
            "ticker":   ticker,
            "entity":   entity,
            "category": category,
            "base_dt":  latest_dt.strftime("%Y-%m-%d"),
            "close":    round(latest_val, 4),
        }

        # 1D, 1W, 1M, 3M, 6M 계산
        for period, days in PERIOD_DAYS_MAP.items():
            if len(df_t) <= days:
                row[f"return_{period}"] = None
                continue

            past_val = df_t.iloc[-1 - days]["close"]

            if past_val == 0:
                row[f"return_{period}"] = None
            else:
                ret = (latest_val - past_val) / past_val * 100
                row[f"return_{period}"] = round(ret, 2)

        # YTD 계산 (현재 연도 첫 영업일 대비)
        current_year = latest_dt.year
        df_ytd = df_t[df_t["base_dt"].dt.year == current_year]

        if len(df_ytd) > 0:
            ytd_start_val = df_ytd.iloc[0]["close"]
            if ytd_start_val == 0:
                row["return_ytd"] = None
            else:
                ret = (latest_val - ytd_start_val) / ytd_start_val * 100
                row["return_ytd"] = round(ret, 2)
        else:
            row["return_ytd"] = None

        results.append(row)

    if not results:
        print("[WARN] 수익률 계산 결과 없음")
        return pd.DataFrame()

    # 4) DataFrame 생성
    df_returns = pd.DataFrame(results)

    # 카테고리별 정렬
    category_order = {"BDC": 0, "Capital": 1, "BM": 2, "other": 3}
    df_returns["_order"] = df_returns["category"].map(category_order)
    df_returns = df_returns.sort_values(["_order", "ticker"]).drop(columns=["_order"])
    df_returns = df_returns.reset_index(drop=True)

    # 컬럼 순서
    cols = [
        "ticker", "entity", "category", "base_dt", "close",
        "return_1d", "return_1w", "return_1m",
        "return_3m", "return_6m", "return_ytd",
    ]
    df_returns = df_returns[cols]

    # 5) 저장
    if output_path:
        df_returns.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"✅ 저장 완료: {output_path}")

    return df_returns


print("✅ 수익률 계산 함수 정의 완료")

# ============================================
# 15-2) 수익률 계산 (price_history.csv 기반)
# ============================================

# 티커 카테고리 매핑 (주가만, FRED 제외)
TICKER_CATEGORY_MAP = {
    "OBDC": "BDC", "OTF": "BDC", "BXSL": "BDC", "ARCC": "BDC", "FSK": "BDC",
    "OWL": "Capital", "BX": "Capital", "ARES": "Capital", "APO": "Capital", "KKR": "Capital",
    "BIZD": "BM", "^GSPC": "BM", "HYG": "BM",
}

# 기준 영업일 수
PERIOD_DAYS_MAP = {
    "1d":  1,
    "1w":  5,
    "1m":  21,
    "3m":  63,
    "6m":  126,
    "1y":  252,
}


def calculate_returns(price_history_path, output_path=None):
    """price_history.csv → 티커별 수익률 계산 (FRED 제외)"""

    if not os.path.exists(price_history_path):
        print(f"[ERROR] 파일 없음: {price_history_path}")
        return pd.DataFrame()

    df = pd.read_csv(price_history_path, encoding="utf-8-sig")
    if df.empty:
        print("[WARN] 데이터 없음")
        return pd.DataFrame()

    df["base_dt"] = pd.to_datetime(df["base_dt"], errors="coerce")
    df = df.dropna(subset=["base_dt", "close"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"])

    # 주가 티커만 필터 (FRED 제외)
    df = df[df["ticker"].isin(TICKER_CATEGORY_MAP.keys())].copy()
    df = df.sort_values(["ticker", "base_dt"]).reset_index(drop=True)

    if df.empty:
        print("[WARN] 주가 데이터 없음")
        return pd.DataFrame()

    print(f"📊 수익률 계산 시작")
    print(f"   데이터: {len(df):,}행 (주가만)")
    print(f"   기간: {df['base_dt'].min().date()} ~ {df['base_dt'].max().date()}")
    print(f"   티커: {df['ticker'].nunique()}개")
    print("-" * 50)

    results = []
    for ticker in df["ticker"].unique():
        df_t = df[df["ticker"] == ticker].copy().reset_index(drop=True)
        if df_t.empty:
            continue

        category = TICKER_CATEGORY_MAP.get(ticker, "other")
        latest_row = df_t.iloc[-1]
        latest_dt  = latest_row["base_dt"]
        latest_val = latest_row["close"]
        entity     = latest_row["entity"]

        row = {
            "ticker":   ticker,
            "entity":   entity,
            "category": category,
            "base_dt":  latest_dt.strftime("%Y-%m-%d"),
            "close":    round(latest_val, 4),
        }

        # 기간별 수익률
        for period, days in PERIOD_DAYS_MAP.items():
            if len(df_t) <= days:
                row[f"return_{period}"] = None
                continue
            past_val = df_t.iloc[-1 - days]["close"]
            if past_val == 0:
                row[f"return_{period}"] = None
            else:
                ret = (latest_val - past_val) / past_val * 100
                row[f"return_{period}"] = round(ret, 2)

        # YTD
        current_year = latest_dt.year
        df_ytd = df_t[df_t["base_dt"].dt.year == current_year]
        if len(df_ytd) > 0:
            ytd_start_val = df_ytd.iloc[0]["close"]
            if ytd_start_val == 0:
                row["return_ytd"] = None
            else:
                ret = (latest_val - ytd_start_val) / ytd_start_val * 100
                row["return_ytd"] = round(ret, 2)
        else:
            row["return_ytd"] = None

        results.append(row)

    if not results:
        print("[WARN] 수익률 계산 결과 없음")
        return pd.DataFrame()

    df_returns = pd.DataFrame(results)

    # 카테고리별 정렬
    category_order = {"BDC": 0, "Capital": 1, "BM": 2, "other": 3}
    df_returns["_order"] = df_returns["category"].map(category_order)
    df_returns = df_returns.sort_values(["_order", "ticker"]).drop(columns=["_order"])
    df_returns = df_returns.reset_index(drop=True)

    cols = [
        "ticker", "entity", "category", "base_dt", "close",
        "return_1d", "return_1w", "return_1m",
        "return_3m", "return_6m", "return_1y", "return_ytd",
    ]
    df_returns = df_returns[cols]

    if output_path:
        df_returns.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"✅ 저장 완료: {output_path}")

    return df_returns


# 실행 - 수익률 계산
returns_output_path = f"{SAVE_DIR}/private_credit_returns_latest.csv"

df_returns = calculate_returns(
    price_history_path = price_drive_file_path,  # 14번에서 정의된 변수 재사용
    output_path        = returns_output_path
)

if not df_returns.empty:
    print(f"\n📊 수익률 계산 결과: {len(df_returns)}개 티커")
    print("=" * 80)

    # 카테고리별 출력
    for cat, cat_name in [
        ("BDC",       "📊상장 BDC"),
        ("Capital",   "🏛️운용사"),
        ("BM", "📈벤치마크"),
    ]:
        df_sub = df_returns[df_returns["category"] == cat]
        if df_sub.empty:
            continue

        print(f"\n{cat_name}")
        print("-" * 80)
        display_cols = ["ticker", "entity", "base_dt", "close",
                         "return_1d", "return_1w", "return_1m",
                         "return_3m", "return_6m", "return_ytd"]
        print(df_sub[display_cols].to_string(index=False))

# ============================================
# 15-3) 연초부터 시계열 수익률 계산
# ============================================
def calculate_returns_timeseries(price_history_path,
                                   start_date=None,
                                   output_path=None):
    """
    특정 시점부터 오늘까지 각 영업일별 수익률 시계열 계산.

    Parameters
    ----------
    price_history_path : str
        price_history.csv 경로
    start_date : str or pd.Timestamp, optional
        시작일. None이면 YTD (현재 연도 시작)
    output_path : str, optional
        저장 경로

    Returns
    -------
    pd.DataFrame
        티커 × 영업일 수익률 시계열
    """
    # 1) 데이터 로드
    if not os.path.exists(price_history_path):
        print(f"[ERROR] 파일 없음: {price_history_path}")
        return pd.DataFrame()

    df = pd.read_csv(price_history_path, encoding="utf-8-sig")
    if df.empty:
        return pd.DataFrame()

    df["base_dt"] = pd.to_datetime(df["base_dt"], errors="coerce")
    df = df.dropna(subset=["base_dt", "close"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"])

    # 주가 티커만
    df = df[df["ticker"].isin(TICKER_CATEGORY_MAP.keys())].copy()
    df = df.sort_values(["ticker", "base_dt"]).reset_index(drop=True)

    if df.empty:
        print("[WARN] 주가 데이터 없음")
        return pd.DataFrame()

    # 2) 시작일 설정 (default: YTD)
    if start_date is None:
        latest_year = df["base_dt"].max().year
        start_date = pd.Timestamp(year=latest_year, month=1, day=1)
    else:
        start_date = pd.Timestamp(start_date)

    print(f"📊 시계열 수익률 계산")
    print(f"   시작일: {start_date.date()}")
    print(f"   종료일: {df['base_dt'].max().date()}")
    print(f"   티커: {df['ticker'].nunique()}개")
    print("-" * 50)

    # 3) 티커별로 시계열 계산
    all_rows = []

    for ticker in df["ticker"].unique():
        df_t = df[df["ticker"] == ticker].copy().sort_values("base_dt").reset_index(drop=True)
        if df_t.empty:
            continue

        category = TICKER_CATEGORY_MAP.get(ticker, "other")
        entity = df_t.iloc[0]["entity"]

        # YTD 기준점: 현재 연도 첫 영업일 (해당 연도 첫 데이터)
        latest_year = df_t["base_dt"].max().year
        df_current_year = df_t[df_t["base_dt"].dt.year == latest_year]
        if df_current_year.empty:
            continue
        ytd_base_val = df_current_year.iloc[0]["close"]

        # 시작일 이후 각 영업일별로 계산
        df_target = df_t[df_t["base_dt"] >= start_date].copy()

        for idx_t, row_t in df_target.iterrows():
            base_dt    = row_t["base_dt"]
            latest_val = row_t["close"]

            # 원래 df_t에서 현재 날짜의 인덱스 찾기
            current_idx = df_t.index[df_t["base_dt"] == base_dt][0]

            row_out = {
                "ticker":   ticker,
                "entity":   entity,
                "category": category,
                "base_dt":  base_dt.strftime("%Y-%m-%d"),
                "close":    round(latest_val, 4),
            }

            # 1D, 1W, 1M, 3M, 6M, 1y
            for period, days in PERIOD_DAYS_MAP.items():
                if current_idx < days:
                    # 해당 기간의 과거 데이터 없음
                    row_out[f"return_{period}"] = None
                    continue

                past_val = df_t.iloc[current_idx - days]["close"]
                if past_val == 0:
                    row_out[f"return_{period}"] = None
                else:
                    ret = (latest_val - past_val) / past_val * 100
                    row_out[f"return_{period}"] = round(ret, 2)

            # YTD (해당 연도 첫 영업일 대비)
            if ytd_base_val == 0:
                row_out["return_ytd"] = None
            else:
                ret = (latest_val - ytd_base_val) / ytd_base_val * 100
                row_out["return_ytd"] = round(ret, 2)

            all_rows.append(row_out)

    if not all_rows:
        print("[WARN] 계산 결과 없음")
        return pd.DataFrame()

    # 4) DataFrame 생성 및 정렬
    df_series = pd.DataFrame(all_rows)

    category_order = {"BDC": 0, "Capital": 1, "BM": 2, "other": 3}
    df_series["_order"] = df_series["category"].map(category_order)
    df_series["_dt"]    = pd.to_datetime(df_series["base_dt"])
    df_series = df_series.sort_values(["_order", "ticker", "_dt"])
    df_series = df_series.drop(columns=["_order", "_dt"])
    df_series = df_series.reset_index(drop=True)

    cols = [
        "ticker", "entity", "category", "base_dt", "close",
        "return_1d", "return_1w", "return_1m",
        "return_3m", "return_6m", "return_1y", "return_ytd",
    ]
    df_series = df_series[cols]

    # 5) 저장
    if output_path:
        df_series.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"✅ 저장 완료: {output_path}")
        print(f"   총 {len(df_series):,}행 ({df_series['ticker'].nunique()}개 티커 × 영업일)")

    return df_series


# 실행 - YTD 시계열 수익률 계산
returns_series_output_path = f"{SAVE_DIR}/private_credit_returns_ytd_series.csv"

df_returns_series = calculate_returns_timeseries(
    price_history_path = price_drive_file_path,
    start_date         = None,  # None = YTD (올해 1/1 이후)
    output_path        = returns_series_output_path
)

if not df_returns_series.empty:
    print(f"\n📊 YTD 시계열 수익률: {len(df_returns_series):,}행")

    # OBDC 샘플만 미리보기
    sample = df_returns_series[df_returns_series["ticker"] == "OBDC"].head(10)
    print("\n[샘플] OBDC 처음 10영업일:")
    print(sample[["base_dt", "close", "return_1d", "return_1w", "return_1m", "return_ytd"]].to_string(index=False))

    print("\n[샘플] OBDC 최근 5영업일:")
    sample_tail = df_returns_series[df_returns_series["ticker"] == "OBDC"].tail(5)
    print(sample_tail[["base_dt", "close", "return_1d", "return_1w", "return_1m", "return_ytd"]].to_string(index=False))

# ============================================
# 16) 모든 누적 파일 일괄 자동 다운로드
# ============================================
import shutil

# 자동 다운로드 대상 (모든 누적 파일)
download_targets = [
    news_kr_drive_path,
    news_en_drive_path,
    price_drive_file_path,
    filings_drive_path,
    returns_output_path,            # 셀 15-2에서 정의된 변수
    returns_series_output_path,     # 셀 15-3에서 정의된 변수
    f"{SAVE_DIR}/periodic_metrics.csv",  # 셀 13의 정기공시 자동화에서 만들어짐
]

# Colab 전용 자동 다운로드 섹션 SKIP — 로컬/HF 환경에서는 파일이 이미 data/ 에 있음.
print("\n[INFO] Colab 'files.download' 섹션 SKIP — 로컬/HF 에선 불필요")

"""##공시 sentiment 분석 시도"""

# sentiment 분포 체크
df_filings = pd.read_csv(
    f"{SAVE_DIR}/private_credit_sec_filings_history.csv",
    encoding="utf-8-sig"
)

print(f"총 공시: {len(df_filings)}건\n")
print("Sentiment 분포:")
print(df_filings["sentiment"].value_counts(dropna=False))
print()

# 샘플 출력
for s in ["negative", "neutral", "positive"]:
    sub = df_filings[df_filings["sentiment"] == s].head(2)
    print(f"\n=== {s.upper()} 샘플 ===")
    for _, row in sub.iterrows():
        print(f"  [{row['form']}] {row.get('one_liner_kr', '')}")
        print(f"  fund: {row['fund_name']}")

#삭제# ## 원본 JSON에서 키워드 관련 텍스트/테이블만 추려서 별도 JSON 파일로 저장
def save_relevant_snippets(json_path, output_dir=None):
    with open(json_path) as f:
        data = json.load(f)

    meta        = data.get("meta", {})
    text        = data.get("text", "")
    tables      = data.get("tables", [])
    context_map = data.get("context_map", {})

    KEYWORDS = [
        # PIK 관련
        "pik interest income",
        "pik dividend income",
        "payment-in-kind interest income",
        "payment-in-kind dividend income",

        # Total investment income
        "total investment income",

        # Non-accrual 관련
        "loans on non-accrual status",
        "percentage of assets on non-accrual",
        "amortized cost of our performing and non-accrual debt instruments",
        "% of investments on non-accrual (based on fair value)",
        "at amortized cost, loans on non-accrual status",
        "performing",
        "non-accrual",

        # NAV
        "net asset value per share",
        "net asset value per class",
        "net asset value per clase s",
        "net asset value per class d",
        "net asset value per class i"
    ]

    def resolve_context(ctx_id):
        if not ctx_id or ctx_id not in context_map:
            return ctx_id
        info = context_map[ctx_id]
        if info.get("type") == "instant":
            return info.get("date", ctx_id)
        return f"{info.get('start_date')}~{info.get('end_date')}"

    def matches_keyword(s):
        s_lower = s.lower()
        return any(kw in s_lower for kw in KEYWORDS)

    # ============================================
    # 1) 텍스트 필터링
    # ============================================
    relevant_texts = []
    for para in text.split("\n\n"):
        if matches_keyword(para):
            relevant_texts.append(para.strip())

    # ============================================
    # 2) 테이블 필터링 + contextRef 날짜 변환
    # ============================================
    relevant_tables = []
    for table in tables:
        all_cells  = [c for r in table["rows"] for c in r["cells"]]
        table_text = " ".join(c.get("raw_text", "") for c in all_cells)

        if not matches_keyword(table_text):
            continue

        # contextRef를 실제 날짜로 변환
        rows_out = []
        for row in table["rows"]:
            cells_out = []
            for cell in row["cells"]:
                c = dict(cell)
                if c.get("contextRef"):
                    c["contextRef"] = resolve_context(c["contextRef"])
                cells_out.append(c)
            rows_out.append({
                "row_index": row["row_index"],
                "cells":     cells_out,
            })

        relevant_tables.append({
            "table_id": table["table_id"],
            "rows":     rows_out,
        })

    # ============================================
    # 3) 저장
    # ============================================
    output = {
        "meta":   meta,
        "texts":  relevant_texts,
        "tables": relevant_tables,
    }

    if output_dir is None:
        output_dir = os.path.dirname(json_path)

    os.makedirs(output_dir, exist_ok=True)

    base_name   = os.path.basename(json_path).replace(".json", "_snippet.json")
    output_path = os.path.join(output_dir, base_name)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    size_kb = os.path.getsize(output_path) / 1024
    print(f"  [저장] {base_name}")
    print(f"         텍스트 {len(relevant_texts)}개 | "
          f"테이블 {len(relevant_tables)}개 | "
          f"크기 {size_kb:.0f}KB")

    return output_path


# ============================================
# 전체 실행
# ============================================
import glob

snippet_dir = f"{SAVE_DIR}/sec_filings_json/snippets"
os.makedirs(snippet_dir, exist_ok=True)

sec_json_dir = f"{SAVE_DIR}/sec_filings_json"
json_files = sorted(glob.glob(f"{sec_json_dir}/*.json"))
print(f"처리할 JSON 파일 수: {len(json_files)}개")

snippet_files = []
for path in json_files:
    print(f"\n처리 중: {os.path.basename(path)}")
    snippet_path = save_relevant_snippets(path, output_dir=snippet_dir)
    snippet_files.append(snippet_path)
    files.download(snippet_path)  # ← 여기서 다운로드

print(f"\n총 {len(snippet_files)}개 스니펫 파일 저장 완료")
print(f"저장 위치: {snippet_dir}")
# (HF push 는 백필 섹션 시작 전 위쪽에서 이미 실행됨)
