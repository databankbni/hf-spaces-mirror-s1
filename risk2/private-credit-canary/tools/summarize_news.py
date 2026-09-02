"""뉴스 본문 크롤링 + Gemini 2.5 Flash 한국어 2문장 요약.

- 국내 뉴스 (private_credit_news_korea_history.csv) → summary_kr 채움
- 해외 뉴스 (private_credit_news_global_history.csv) → title_kr + summary_kr 채움
- 이미 채워진 행은 스킵 (idempotent)
- 본문 추출 실패 시 title 만으로 요약 폴백

사용법
------
1) Gemini API 키 발급: https://aistudio.google.com/apikey
2) 키 설정 (둘 중 하나):
     - 환경변수: GEMINI_API_KEY=xxxxxxxxxx
     - 또는 프로젝트 루트에 .env 파일 생성:
         GEMINI_API_KEY=xxxxxxxxxx
3) 실행 (프로젝트 루트에서):
     venv\\Scripts\\python.exe tools\\summarize_news.py
"""

from __future__ import annotations

import html as html_lib
import json
import os
import re as _re_top
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# 사내 SSL 인터셉트(자체서명 CA) 환경 대응 — Windows 시스템 인증서 저장소 사용
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass  # 외부망 환경이면 영향 없음

# Windows 콘솔(cp949)에서 유니코드 출력 가능하도록 stdout 재구성
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

CSV_BINARY_MAGIC = b"SCDSA"   # SoftCamp DRM 봉인 매직 — CSV 가 아니므로 거른다.


def _read_csv_safely(path):
    """SCDSA 봉인이나 인코딩 오류 시 빈 DF 반환 (스크립트 죽지 않게)."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
        if head.startswith(CSV_BINARY_MAGIC) or b"\x00" in head:
            print(f"  [WARN] {path.name} 봉인된 파일 (SCDSA) — 처리 스킵")
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

# 모델 fallback 체인 — quota 초과 시 자동 전환
MODELS_FALLBACK = [
    "gemini-2.5-flash-lite",
    "gemma-4-31b-it",
]
MAX_BODY_CHARS = 6000           # LLM 입력 본문 최대 길이
# 본문 길이 임계값 2단계
# - FULL ≥ 500자: 정상 본문 (2-3 문단 이상)
# - PARTIAL ≥ 200자: lead paragraph 정도 (페이월 미리보기 등) — 가치 있음, 사용
# - <200자: 너무 짧음, 폴백
MIN_BODY_CHARS = 500            # 정상 본문 기준
PARTIAL_BODY_CHARS = 200        # 부분 본문 최소 길이 (lead paragraph)
SLEEP_BETWEEN_CALLS = 13.0      # 무료 티어 RPM=5 → 12초/건 + 여유 1초
MAX_RETRY = 3
_ACTIVE_MODEL_IDX = 0

# summary_source 컬럼 값 — 어떤 소스로 요약됐는지 추적
SOURCE_BODY = "body"            # 본문 ≥ 500자 (정상)
SOURCE_PARTIAL = "partial_body" # 본문 200-499자 (페이월 lead paragraph 등)
SOURCE_WAYBACK = "wayback"      # Wayback Machine 캐시 본문 ≥500자
SOURCE_RSS = "rss_summary"      # RSS preview 사용 (Naver 같이 진짜 미리보기)
SOURCE_TITLE = "title_only"     # title 만으로 요약 (최후 폴백)

KR_FILE = DATA / "private_credit_news_korea_history.csv"
EN_FILE = DATA / "private_credit_news_global_history.csv"


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
if not GEMINI_API_KEY:
    print(
        "[ERROR] GEMINI_API_KEY 가 설정되지 않았습니다.\n"
        "  - 환경변수 또는 프로젝트 루트의 .env 파일에 키를 넣어주세요.\n"
        "  - 키 발급: https://aistudio.google.com/apikey",
        file=sys.stderr,
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Gemini 클라이언트 (지연 import — 의존성 누락 시 명확히 안내)
# ---------------------------------------------------------------------------

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

try:
    import trafilatura
except ImportError as _e:
    # trafilatura 자체 또는 그 sub-dep (lxml, htmldate, justext 등) import 실패 모두 catch.
    # HF Linux slim 환경에서 lxml 등이 system lib 부재로 import 실패할 수 있어 실제 메시지 노출.
    print(
        f"[ERROR] trafilatura 또는 그 의존성 import 실패: {type(_e).__name__}: {_e}\n"
        "  - 로컬: venv\\Scripts\\pip.exe install trafilatura\n"
        "  - HF: requirements.txt 의 trafilatura 핀 확인. lxml/htmldate 등 sub-dep 호환성 의심.",
        file=sys.stderr,
    )
    sys.exit(1)

client = genai.Client(api_key=GEMINI_API_KEY)


# ---------------------------------------------------------------------------
# 본문 추출
# ---------------------------------------------------------------------------

# 일부 매체(Reuters, Cloudflare 적용 사이트 등) 가 단순 봇 User-Agent 를 차단함.
# 진짜 크롬 처럼 보이는 헤더로 재시도하면 일부 사이트는 통과.
# 단, Bloomberg / FT / WSJ 같은 강력한 페이월은 여전히 본문 미수신 (fallback to title).
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}


def _extract_body(html_or_text) -> str:
    """trafilatura 로 본문 추출. 입력은 str(HTML) 또는 bytes 일 수 있음."""
    if not html_or_text:
        return ""
    try:
        text = trafilatura.extract(
            html_or_text,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )
        return (text or "").strip()
    except Exception:  # noqa: BLE001
        return ""


# og:title > twitter:title > <title> 순으로 페이지 제목 추출.
# 네이버 RSS 가 약 80자에서 "..." 로 잘라 보내는 제목을 원본 페이지에서 복원하는 용도.
_OG_TITLE_RE = _re_top.compile(
    r'<meta\s+[^>]*?property\s*=\s*["\']og:title["\'][^>]*?content\s*=\s*["\']([^"\']+)["\']',
    _re_top.IGNORECASE,
)
_OG_TITLE_RE_REV = _re_top.compile(
    r'<meta\s+[^>]*?content\s*=\s*["\']([^"\']+)["\'][^>]*?property\s*=\s*["\']og:title["\']',
    _re_top.IGNORECASE,
)
_TW_TITLE_RE = _re_top.compile(
    r'<meta\s+[^>]*?name\s*=\s*["\']twitter:title["\'][^>]*?content\s*=\s*["\']([^"\']+)["\']',
    _re_top.IGNORECASE,
)
_TITLE_TAG_RE = _re_top.compile(r"<title[^>]*>([^<]+)</title>", _re_top.IGNORECASE | _re_top.DOTALL)
# 페이지 <title> 끝의 흔한 사이트명 접미사 — " - 한국경제", " | 머니투데이" 등
_SITE_SUFFIX_RE = _re_top.compile(r"\s*[-|―–—]\s*[^-|―–—]{1,30}$")


def _decode_if_bytes(raw) -> str:
    """trafilatura.fetch_url() 가 bytes 를 반환할 수도 있어 안전하게 str 변환."""
    if isinstance(raw, bytes):
        try:
            return raw.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return ""
    return raw if isinstance(raw, str) else ""


def _extract_page_title(html_text) -> str:
    """HTML 에서 og:title → twitter:title → <title> 순으로 페이지 제목 추출.

    Naver 검색 RSS 는 ~80자에서 ...로 잘라 보내므로 원본 페이지의 og:title 로 복원하면
    "...[ASK 2026]" 같은 컨퍼런스 태그까지 살릴 수 있음.
    """
    text = _decode_if_bytes(html_text)
    if not text:
        return ""
    for pat in (_OG_TITLE_RE, _OG_TITLE_RE_REV, _TW_TITLE_RE):
        m = pat.search(text)
        if m:
            return html_lib.unescape(m.group(1)).strip()
    m = _TITLE_TAG_RE.search(text)
    if m:
        title = html_lib.unescape(m.group(1)).strip()
        # "기사 제목 - 한국경제" 같은 사이트명 꼬리 제거
        return _SITE_SUFFIX_RE.sub("", title).strip()
    return ""


def _is_truncated_title(t) -> bool:
    """RSS 가 잘라 보낸 제목인지 — 끝이 ... 또는 … 로 끝나면 True."""
    if not isinstance(t, str):
        return False
    s = t.rstrip()
    return s.endswith("...") or s.endswith("…")


def _fetch_with_browser_headers(url: str, timeout: int = 12) -> str:
    """브라우저 헤더로 직접 fetch. gzip 자동 압축 해제."""
    import gzip

    req = urllib.request.Request(url, headers=BROWSER_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        encoding = resp.headers.get("Content-Encoding", "").lower()
        if "gzip" in encoding:
            raw = gzip.decompress(raw)
        elif "br" in encoding:
            try:
                import brotli
                raw = brotli.decompress(raw)
            except ImportError:
                pass  # brotli 없으면 그대로 시도
        # 인코딩 추정
        charset = resp.headers.get_content_charset() or "utf-8"
        try:
            return raw.decode(charset, errors="replace")
        except (LookupError, TypeError):
            return raw.decode("utf-8", errors="replace")


def _fetch_via_wayback(url: str, timeout: int = 12) -> str:
    """Internet Archive Wayback Machine 캐시에서 본문 가져오기 — 페이월 일부 우회.

    1) availability API 로 가장 가까운 스냅샷 조회
    2) 스냅샷이 있으면 그 URL 을 다시 fetch
    """
    api = f"https://archive.org/wayback/available?url={urllib.parse.quote(url, safe=':/?=&')}"
    req = urllib.request.Request(api, headers=BROWSER_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    snap = (data.get("archived_snapshots", {}) or {}).get("closest", {}) or {}
    if not snap.get("available") or not snap.get("url"):
        return ""
    snap_url = snap["url"]
    # https 강제 (스냅샷 URL 이 http 로 오는 경우 있음)
    if snap_url.startswith("http://"):
        snap_url = "https://" + snap_url[len("http://"):]
    return _fetch_with_browser_headers(snap_url, timeout=timeout)


def fetch_body(url: str) -> tuple[str, str, str]:
    """URL → (본문 텍스트, 소스 라벨, 페이지 제목). 4단계 fallback.

    페이지 제목은 어떤 tier 든 HTML 을 받자마자 og:title 로 추출해 보존 —
    body 가 ≥500자가 안 돼도 제목만은 살림 (RSS truncation 복원에 사용).

    1차: trafilatura 기본
    2차: 브라우저 헤더 위장
    3차: Wayback Machine 캐시
    → ≥500자 못 얻으면 가장 긴 partial(≥200자) 반환
    → 그것도 없으면 ("", "", title) — title 은 잡힐 수도 있음
    """
    if not isinstance(url, str) or not url.strip():
        return "", "", ""

    best_partial = ""
    best_partial_source = ""
    fetched_title = ""   # tier 중 가장 먼저 잡힌 og:title 보존

    def _consider_partial(text: str, source: str) -> None:
        nonlocal best_partial, best_partial_source
        if PARTIAL_BODY_CHARS <= len(text) < MIN_BODY_CHARS and len(text) > len(best_partial):
            best_partial = text
            best_partial_source = source

    def _remember_title(html_or_text) -> None:
        nonlocal fetched_title
        if fetched_title:
            return
        t = _extract_page_title(html_or_text)
        if t:
            fetched_title = t

    # 1차 — trafilatura 기본 fetcher
    try:
        downloaded = trafilatura.fetch_url(url)
        _remember_title(downloaded)
        text = _extract_body(downloaded)
        if len(text) >= MIN_BODY_CHARS:
            return text, SOURCE_BODY, fetched_title
        _consider_partial(text, SOURCE_PARTIAL)
    except Exception as exc:  # noqa: BLE001
        print(f"    fetch fail (trafilatura): {exc}")

    # 2차 — 브라우저 헤더 위장 + urllib
    try:
        html = _fetch_with_browser_headers(url)
        _remember_title(html)
        text = _extract_body(html)
        if len(text) >= MIN_BODY_CHARS:
            print(f"    [retry OK] 브라우저 헤더로 본문 {len(text)}자 추출")
            return text, SOURCE_BODY, fetched_title
        _consider_partial(text, SOURCE_PARTIAL)
    except Exception as exc:  # noqa: BLE001
        print(f"    fetch fail (browser headers): {exc}")

    # 3차 — Wayback Machine 캐시
    try:
        html = _fetch_via_wayback(url)
        _remember_title(html)
        text = _extract_body(html)
        if len(text) >= MIN_BODY_CHARS:
            print(f"    [wayback OK] Internet Archive 캐시에서 본문 {len(text)}자 추출")
            return text, SOURCE_WAYBACK, fetched_title
        _consider_partial(text, SOURCE_PARTIAL)
    except Exception as exc:  # noqa: BLE001
        print(f"    fetch fail (wayback): {exc}")

    if best_partial:
        print(f"    [partial OK] 부분 본문 {len(best_partial)}자 사용 (lead paragraph)")
        return best_partial, best_partial_source, fetched_title

    return "", "", fetched_title


# ---------------------------------------------------------------------------
# LLM 호출
# ---------------------------------------------------------------------------

KR_PROMPT = """다음 한국어 뉴스를 읽고 JSON 으로 답하세요.

- "summary_kr": 1~2문장의 한국어 요약
- "keywords": 기사 주제를 나타내는 한국어 명사 1~3개 (배열)

[summary_kr 문체 규칙 — 반드시 따를 것]
- 종결어미는 '~음', '~했음', '~임' 등 음슴체(개조식)
  · 예: "발표함.", "하락했음.", "예정임.", "확대됨."
- 다음 어미는 절대 사용 금지: "~습니다", "~합니다", "~한다", "~된다", "~이다"

[summary_kr 길이 규칙 — 매우 중요]
- 공백 포함 총 140자 이내 (반드시 준수, 글자 수 직접 세서 확인)
- 각 문장은 반드시 마침표로 끝맺어 완결된 문장
- 절대 중간에 잘리지 말 것 — 2문장이 140자를 넘으면 1문장으로 줄일 것

[summary_kr 내용 규칙]
- 사실/수치/고유명사 정확히 보존
- 의견·수식어·감상 제거

[keywords 규칙]
- 기사의 주제(topic)를 나타내는 1~3개의 짧은 명사
- 고유명사(기관·펀드·인물·국가)는 영문 원형 유지 (예: "ECB", "Blue Owl", "BCRED")
- 일반 토픽어는 한국어 명사 (예: "유동성", "환매", "디폴트", "유로존")
- 제외: "사모대출", "사모신용", "사모신용펀드" — 모든 기사가 공유하는 도메인 공통어이므로 키워드로 쓰지 말 것
- 부정문 여부와 무관하게 주제 자체를 뽑을 것 (예: "신용리스크 아니다" 도 주제는 "신용리스크")

[제목]
{title}

[본문]
{body}

JSON 만 출력:"""


EN_PROMPT = """Read the English news article below and produce JSON.

- "title_kr": Korean translation of the title (natural Korean, financial register; declarative form OK).
- "summary_kr": 1-2 sentence Korean summary in 음슴체 (concise written style).
- "keywords": 1-3 short topic nouns describing what the article is ABOUT (array of strings).

  STYLE RULES (MUST FOLLOW for summary_kr):
    * End each sentence with -음 / -했음 / -임 / -됨 forms.
    * Examples: "발표함.", "하락했음.", "예정임.", "확대됨."
    * NEVER use polite forms like "-습니다", "-합니다" or formal "-한다", "-된다", "-이다".
  NAME RULES (CRITICAL — applies to title_kr, summary_kr, AND keywords):
    * Keep ALL asset manager / fund / BDC / ticker / institution names in their ORIGINAL English form.
      Do NOT translate, transliterate, or hangul-ize them.
    * Examples (correct — leave as-is): "Blue Owl", "Blackstone", "Ares", "Apollo", "KKR", "ECB", "Fed", "SEC",
      "Blue Owl Capital Corp", "Blackstone Private Credit Fund", "Ares Capital",
      "OBDC", "OBDC II", "OCIC", "OTIC", "BCRED", "ARCC", "FSK", "BXSL", "OTF", "BIZD".
    * Examples (wrong — never produce these): "블루아울", "블랙스톤", "아레스", "아폴로",
      "케이케이알", "블루아울 캐피탈 코프".
    * Country / region names may follow normal Korean conventions ("유로존", "미국", "한국").
  LENGTH RULES (CRITICAL for summary_kr):
    * Total under 140 characters including spaces — count carefully.
    * Each sentence MUST end with a period — NEVER cut mid-sentence.
    * If 2 sentences exceed 140 chars, use 1 complete sentence only.
  CONTENT RULES:
    * Use ONLY information explicitly present in the Title and Body below.
    * If Body is empty or identical to Title, only paraphrase the Title in Korean — DO NOT add details, numbers, or context not present in the source.
    * NEVER infer or speculate based on prior knowledge of the company / industry.
    * Factual, concise; preserve numbers/names/key actions; remove opinion/embellishment.
  KEYWORDS RULES:
    * 1 to 3 short Korean nouns (proper nouns stay in English per NAME RULES above).
    * Topic / subject only — not sentiment or conclusion. A "no systemic risk" article's
      topic is still "systemic risk" or "credit risk".
    * EXCLUDE these domain-common terms (every article shares them, zero info value):
      "사모대출", "사모신용", "사모신용펀드", "private credit", "private credit fund".
    * Examples of GOOD keywords: ["ECB", "유로존", "시스템리스크"], ["Blue Owl", "환매", "유동성"],
      ["BCRED", "NAV", "redemption"].

[Title]
{title}

[Body]
{body}

Output JSON only."""


import re


def _wait_for_retry(exc: Exception, attempt: int) -> float | None:
    """예외에서 재시도 대기시간(초) 추출. 재시도 불가하면 None."""
    msg = str(exc)
    if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
        # 메시지의 retryDelay 또는 'Please retry in N.NNNs' 추출
        m = re.search(r"retry(?:Delay)?[:\s\"']+(\d+(?:\.\d+)?)\s*s", msg, re.IGNORECASE)
        if m:
            return float(m.group(1)) + 1.0
        return 60.0
    # 503 UNAVAILABLE / deadline / 500 INTERNAL — 일시적 서버 에러로 재시도
    if (
        "UNAVAILABLE" in msg
        or "503" in msg
        or "deadline" in msg.lower()
        or "INTERNAL" in msg
        or "500" in msg
    ):
        return min(30.0, 5.0 * (2 ** attempt))  # 5, 10, 20
    # SSL / 네트워크 단절 — 일시적 transport 에러로 재시도
    # 사내망의 TLS inspection / WebKeeper 같은 보안 솔루션과 충돌할 때 흔히 발생
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


def _call_llm(make_request) -> object | None:
    """주어진 함수를 호출하되 429/503 에러 시 자동 재시도."""
    for attempt in range(MAX_RETRY):
        try:
            result = make_request()
            if attempt > 0:
                print(f"    재시도 성공 (시도 {attempt + 1}/{MAX_RETRY})")
            return result
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


def _generate(prompt: str, json_mode: bool = False):
    """현재 활성 모델로 호출. quota 초과 시 다음 fallback 모델로 자동 전환."""
    global _ACTIVE_MODEL_IDX
    while _ACTIVE_MODEL_IDX < len(MODELS_FALLBACK):
        model = MODELS_FALLBACK[_ACTIVE_MODEL_IDX]
        config = None
        if json_mode and model.startswith("gemini"):
            config = genai_types.GenerateContentConfig(
                response_mime_type="application/json",
            )
        try:
            return _call_llm(
                lambda: client.models.generate_content(
                    model=model, contents=prompt, config=config,
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


_DOMAIN_STOPWORDS = {
    "사모대출", "사모신용", "사모신용펀드",
    "private credit", "private credit fund", "private credit funds",
}


def _normalize_keywords(raw) -> str:
    """LLM 응답의 keywords 필드(list/str/None) → 표시용 ", " 구분 문자열.

    - 도메인 공통어(사모대출/사모신용/private credit) 는 LLM 이 실수로 넣어도 제거
    - 빈 값·중복 제거, 최대 3개 유지
    """
    if not raw:
        return ""
    if isinstance(raw, str):
        items = [s.strip() for s in raw.split(",")]
    elif isinstance(raw, (list, tuple)):
        items = [str(s).strip() for s in raw]
    else:
        return ""
    seen, out = set(), []
    for kw in items:
        if not kw:
            continue
        if kw.lower() in _DOMAIN_STOPWORDS:
            continue
        if kw.lower() in seen:
            continue
        seen.add(kw.lower())
        out.append(kw)
        if len(out) >= 3:
            break
    return ", ".join(out)


def _parse_json_response(raw: str) -> dict:
    """Gemini/Gemma JSON 응답을 안전하게 파싱 — 코드펜스·앞뒤 잡음 허용."""
    if not raw:
        return {}
    raw = raw.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        l, r = raw.find("{"), raw.rfind("}")
        if l == -1 or r == -1:
            return {}
        try:
            data = json.loads(raw[l : r + 1])
        except json.JSONDecodeError:
            return {}
    if isinstance(data, list):
        data = next((x for x in data if isinstance(x, dict)), {})
    return data if isinstance(data, dict) else {}


def summarize_kr(title: str, body: str) -> tuple[str, str]:
    """국내 뉴스 요약 + 키워드 추출. 반환: (summary_kr, keywords_str)."""
    prompt = KR_PROMPT.format(title=title, body=body[:MAX_BODY_CHARS])
    resp = _generate(prompt, json_mode=True)
    if not resp:
        return "", ""
    data = _parse_json_response(resp.text or "")
    summary = (data.get("summary_kr") or "").strip()
    keywords = _normalize_keywords(data.get("keywords"))
    return summary, keywords


def summarize_en(title: str, body: str) -> tuple[str, str, str]:
    """해외 뉴스 번역+요약+키워드. 반환: (title_kr, summary_kr, keywords_str)."""
    prompt = EN_PROMPT.format(title=title, body=body[:MAX_BODY_CHARS])
    resp = _generate(prompt, json_mode=True)
    if not resp:
        return "", "", ""
    data = _parse_json_response(resp.text or "")
    return (
        (data.get("title_kr") or "").strip(),
        (data.get("summary_kr") or "").strip(),
        _normalize_keywords(data.get("keywords")),
    )


# ---------------------------------------------------------------------------
# 처리 파이프라인
# ---------------------------------------------------------------------------

def _is_filled(v) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _log(msg: str) -> None:
    print(msg, flush=True)


def _is_rss_summary_useful(title: str, rss_summary: str) -> bool:
    """RSS summary 가 실제로 새 정보를 담고 있는지 판정.

    Google News RSS 는 summary = "title 매체명" 형태로 title 의 반복일 뿐이라 무의미.
    Naver RSS 는 100-200자의 실제 기사 미리보기를 담고 있어 매우 유용.

    판정 기준: title 에 없는 단어가 4개 이상이면 진짜 본문 미리보기로 간주.
    """
    if not rss_summary or len(rss_summary) < 80:
        return False

    # 정규화 — 영숫자·한글만 남기고 비교
    import re

    def _tokens(s: str) -> set:
        # 단어 분리 (한국어는 공백·구두점 기준, 영어는 공백 기준)
        s = re.sub(r"[^\w\s]", " ", s.lower())
        return {tok for tok in s.split() if len(tok) >= 2}

    title_tokens = _tokens(title)
    summary_tokens = _tokens(rss_summary)
    new_tokens = summary_tokens - title_tokens
    # title 에 없는 단어 4개 이상 → 진짜 새 정보
    return len(new_tokens) >= 4


def _build_body_with_fallback(row: pd.Series, fetched_body: str, fetched_source: str
                               ) -> tuple[str, str]:
    """fetch_body() 결과 (body / partial_body / wayback / 빈값) 에 따라 LLM 입력 구성.

    fetch_body() 가 본문(full or partial)을 반환했으면 그대로 사용.
    빈값이면 RSS summary (스마트 휴리스틱) → title 순으로 폴백.

    반환: (LLM 입력용 body, summary_source 라벨)
    """
    title = str(row.get("title") or "").strip()
    rss_summary = str(row.get("summary") or "").strip()

    # full body / partial body / wayback — 모두 본문 기반이라 그대로 사용
    if fetched_body and fetched_source:
        return fetched_body, fetched_source

    # 본문 fetch 완전 실패 → RSS summary 가 실제 새 정보를 담고 있을 때만 사용
    # (Google News 의 "title 매체명" 형태는 자동으로 걸러짐)
    if _is_rss_summary_useful(title, rss_summary):
        _log(f"    [fallback] body 추출 실패 → RSS summary({len(rss_summary)}자, 실 정보 있음) 사용")
        return rss_summary, SOURCE_RSS

    # RSS summary 도 무의미 → title 만 (최후의 수단)
    _log("    [fallback] body·RSS summary 모두 부족 → title 만으로 요약")
    return title, SOURCE_TITLE


def process_korean() -> int:
    if not KR_FILE.exists():
        _log(f"[KR] 파일 없음: {KR_FILE}")
        return 0
    df = _read_csv_safely(KR_FILE)
    if df.empty:
        _log(f"[KR] CSV 읽기 실패 또는 데이터 없음 → 처리 스킵")
        return 0
    for col in ("summary_kr", "summary_source", "llm_keywords"):
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str)

    todo = df.index[~df["summary_kr"].apply(_is_filled)].tolist()
    if not todo:
        _log("[KR] 모든 행이 이미 요약되어 있음.")
        return 0

    _log(f"[KR] 대상 {len(todo)} / 전체 {len(df)} 건 처리 시작")
    updated = 0
    for n, i in enumerate(todo, 1):
        row = df.loc[i]
        title = str(row.get("title") or "").strip()
        url = str(row.get("link") or "").strip()
        if not title:
            continue
        _log(f"  [{n}/{len(todo)}] {title[:60]}")
        fetched_body, fetched_source, fetched_title = fetch_body(url) if url else ("", "", "")
        # 네이버 RSS 가 잘라 보낸 제목("...[A..." 같은 형태) 을 원본 페이지의 og:title 로 복원
        if fetched_title and _is_truncated_title(title) and not _is_truncated_title(fetched_title):
            _log(f"    [title-fix] RSS 잘림 → og:title 로 복원: {fetched_title[:70]}")
            df.at[i, "title"] = fetched_title
            title = fetched_title
        body, source = _build_body_with_fallback(row, fetched_body, fetched_source)
        try:
            summary, keywords = summarize_kr(title, body)
        except Exception as exc:  # noqa: BLE001
            _log(f"    LLM 호출 실패: {exc}")
            time.sleep(SLEEP_BETWEEN_CALLS)
            continue
        if not summary:
            _log("    [SKIP] 빈 응답")
            continue
        df.at[i, "summary_kr"] = summary
        df.at[i, "summary_source"] = source
        if keywords:
            df.at[i, "llm_keywords"] = keywords
        updated += 1
        active_model = MODELS_FALLBACK[_ACTIVE_MODEL_IDX] if _ACTIVE_MODEL_IDX < len(MODELS_FALLBACK) else "?"
        _log(f"    ✓ 갱신 (model={active_model}, source={source})")
        # 매 행 저장 — 중단되어도 진행 상황 보존, 재실행 시 멱등 처리
        df.to_csv(KR_FILE, index=False, encoding="utf-8-sig")
        time.sleep(SLEEP_BETWEEN_CALLS)

    _log(f"[KR] 완료: {updated} 건 갱신")
    return updated


def process_global() -> int:
    if not EN_FILE.exists():
        _log(f"[EN] 파일 없음: {EN_FILE}")
        return 0
    df = _read_csv_safely(EN_FILE)
    if df.empty:
        _log(f"[EN] CSV 읽기 실패 또는 데이터 없음 → 처리 스킵")
        return 0
    for col in ("title_kr", "summary_kr", "summary_source", "llm_keywords"):
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str)

    needs_title = ~df["title_kr"].apply(_is_filled)
    needs_summary = ~df["summary_kr"].apply(_is_filled)
    todo = df.index[needs_title | needs_summary].tolist()
    if not todo:
        _log("[EN] 모든 행이 이미 번역·요약되어 있음.")
        return 0

    _log(f"[EN] 대상 {len(todo)} / 전체 {len(df)} 건 처리 시작")
    updated = 0
    for n, i in enumerate(todo, 1):
        row = df.loc[i]
        title = str(row.get("title") or "").strip()
        url = str(row.get("link") or "").strip()
        if not title:
            continue
        _log(f"  [{n}/{len(todo)}] {title[:60]}")
        fetched_body, fetched_source, fetched_title = fetch_body(url) if url else ("", "", "")
        # Google News RSS 도 가끔 제목을 잘라 보냄 — og:title 로 복원 (해외 뉴스도 동일 처리)
        if fetched_title and _is_truncated_title(title) and not _is_truncated_title(fetched_title):
            _log(f"    [title-fix] RSS 잘림 → og:title 로 복원: {fetched_title[:70]}")
            df.at[i, "title"] = fetched_title
            title = fetched_title
        body, source = _build_body_with_fallback(row, fetched_body, fetched_source)
        try:
            t_kr, s_kr, keywords = summarize_en(title, body)
        except Exception as exc:  # noqa: BLE001
            _log(f"    LLM 호출 실패: {exc}")
            time.sleep(SLEEP_BETWEEN_CALLS)
            continue
        if not t_kr and not s_kr:
            _log("    [SKIP] 빈 응답")
            continue
        if t_kr:
            df.at[i, "title_kr"] = t_kr
        if s_kr:
            df.at[i, "summary_kr"] = s_kr
        df.at[i, "summary_source"] = source
        if keywords:
            df.at[i, "llm_keywords"] = keywords
        updated += 1
        active_model = MODELS_FALLBACK[_ACTIVE_MODEL_IDX] if _ACTIVE_MODEL_IDX < len(MODELS_FALLBACK) else "?"
        _log(f"    ✓ 갱신 (model={active_model}, source={source})")
        df.to_csv(EN_FILE, index=False, encoding="utf-8-sig")
        time.sleep(SLEEP_BETWEEN_CALLS)

    _log(f"[EN] 완료: {updated} 건 갱신")
    return updated


def main() -> None:
    kr = process_korean()
    en = process_global()
    print(f"\n완료. KR {kr} 건, EN {en} 건 갱신.")


if __name__ == "__main__":
    main()
