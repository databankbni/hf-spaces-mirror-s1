"""Resolve annual-report PDF URLs (and download bytes) from reportal.ge.

The portal's old JSON API (`/api/reports/search`) was retired — it now
returns HTTP 404. The current flow used by the portal's own
`/ka/Reports/Report?q=<code>` page is:

  1. GET `/ka/Reports/OrgReports?q=<idcode>`
     → HTML partial listing available years as buttons.
  2. GET `/ka/Reports/OrgReportsByYear?q=<idcode>&year=<year>`
     → HTML partial containing a table of all filings for that year
       (semi-annual + annual × individual + consolidated × KA + EN, plus
       any updated revisions). PDFs live at `/ka/Reports/GetFile/<id>`.

We parse the HTML in step 2 and pick the best ANNUAL PDF: prefer
consolidated over individual, prefer the Georgian filing, prefer an
``(განახლებული)`` ("updated") revision when there are multiple.

Both steps require a logged-in session cookie, read from:
  - environment variable ``REPORTAL_COOKIE`` (HF Space secret pattern)
  - Streamlit secrets ``REPORTAL_COOKIE`` (local dev)

Public surface:
  - ``cookie_available()`` — bool, whether a cookie is configured
  - ``get_pdf_url(idcode, year)`` — direct PDF URL on reportal.ge, or None
  - ``get_pdf_urls_for_years(idcode, years)`` — dict {year: url|None}
  - ``fetch_report_pdf(idcode, year)`` — (bytes|None, status_message)

The direct PDF URL is meant to be opened in the user's browser. The
browser needs its own reportal.ge session for the actual download to
succeed; otherwise reportal redirects to its login page. The PDF URLs
themselves don't expire.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import requests
import streamlit as st

BASE_URL = "https://reportal.ge"
TIMEOUT_META = 15
TIMEOUT_PDF = 30

# Georgian markers used to classify rows in the reports table.
ANNUAL_KA = "წლიური"           # annual (vs. ნახევარწლიური = semi-annual)
SEMIANNUAL_KA = "ნახევარწლიური"
CONSOLIDATED_KA = "კონსოლიდირებული"
INDIVIDUAL_KA = "ინდივიდუალური"
LANG_KA = "ქართული"             # Georgian (filed-in-Georgia language)
LANG_EN = "English"
UPDATED_MARKER = "განახლებული"   # "(updated)" — newer revision of same filing


def _secrets_file_exists() -> bool:
    """True only if a Streamlit secrets.toml actually exists.

    Same defensive pattern as `lib/sector_store.py` — touching ``st.secrets``
    when no secrets.toml is present surfaces a red banner that try/except
    can't suppress.
    """
    candidates = (
        Path("/root/.streamlit/secrets.toml"),
        Path("/app/.streamlit/secrets.toml"),
        Path.home() / ".streamlit" / "secrets.toml",
        Path.cwd() / ".streamlit" / "secrets.toml",
        Path(__file__).parent.parent / ".streamlit" / "secrets.toml",
    )
    for p in candidates:
        try:
            if p.exists():
                return True
        except Exception:
            pass
    return False


def _get_cookie() -> str | None:
    """Read REPORTAL_COOKIE. Env var first (HF Space secret pattern),
    Streamlit secrets only if a secrets.toml exists (local dev)."""
    env = os.environ.get("REPORTAL_COOKIE")
    if env:
        return env.strip()
    if _secrets_file_exists():
        try:
            val = st.secrets.get("REPORTAL_COOKIE")
            if val:
                return str(val).strip()
        except Exception:
            pass
    return None


def cookie_available() -> bool:
    """Is REPORTAL_COOKIE configured? UI uses this to decide whether to
    attempt PDF URL resolution."""
    return _get_cookie() is not None


def _session_for_cookie(cookie: str, idcode: str = "") -> requests.Session:
    s = requests.Session()
    headers = {
        "Cookie": cookie,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
        # The endpoint is fired as an AJAX call by the portal's own page;
        # adding these headers makes our request indistinguishable from a
        # browser request and tends to be friendlier to anti-bot middleware.
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "text/html, */*; q=0.01",
    }
    if idcode:
        headers["Referer"] = f"{BASE_URL}/ka/Reports/Report?q={idcode}"
    s.headers.update(headers)
    return s


# Match a <tr>...</tr> block inside the reports tbody.
# Re-DOTALL because rows span multiple lines.
_ROW_RE = re.compile(r"<tr>\s*(.*?)\s*</tr>", re.DOTALL)
# Capture <td>…</td> content (allowing attributes, e.g. <td style="...">).
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
# Capture each <a href="..."> ...text... </a> inside the last cell.
_LINK_RE = re.compile(
    r'<a\b[^>]*href="(/ka/Reports/GetFile/\d+)"[^>]*>\s*([^<]*)</a>',
    re.IGNORECASE,
)


def _strip_tags(s: str) -> str:
    """Quick tag-strip for cell text — only for classification by Georgian
    keyword, so robustness to malformed HTML isn't critical here."""
    return re.sub(r"<[^>]+>", "", s).strip()


def _parse_reports_table(html: str) -> list[dict]:
    """Parse the reports HTML partial into a list of report rows.

    Each entry: ``{period, form, links: [{href, text, lang, updated}]}``.
    Skips rows that don't have all 7 cells (defensive against template
    drift).
    """
    out: list[dict] = []
    # Restrict to the reports tab — there are similar <tr> blocks in the
    # audit / group-structure tabs we want to ignore.
    #
    # The reports tbody id has changed over time on reportal.ge (it was
    # ``reportData-tbody``; the portal now names tab tbodies like
    # ``reports-<tab>-tbody``). Rather than hard-code a brittle id, scope to
    # the stable ``id="reports-reports"`` tab panel, stop before the next tab
    # panel (``reports-audit``), and take the first <tbody> inside that slice.
    start = html.find('id="reports-reports"')
    if start == -1:
        return out
    end = html.find('id="reports-audit"', start)
    segment = html[start:end] if end != -1 else html[start:]
    tbody_match = re.search(r"<tbody[^>]*>(.*?)</tbody>", segment, re.DOTALL)
    if not tbody_match:
        return out
    tbody = tbody_match.group(1)
    for row_match in _ROW_RE.finditer(tbody):
        row_html = row_match.group(1)
        cells = _TD_RE.findall(row_html)
        if len(cells) < 7:
            continue
        period = _strip_tags(cells[2])
        form = _strip_tags(cells[3])
        last_cell = cells[6]
        links: list[dict] = []
        for href, text in _LINK_RE.findall(last_cell):
            text_clean = text.strip()
            links.append({
                "href": href,
                "text": text_clean,
                "lang": (
                    "ka" if LANG_KA in text_clean
                    else ("en" if LANG_EN in text_clean else "other")
                ),
                "updated": UPDATED_MARKER in text_clean,
            })
        if not links:
            continue
        out.append({"period": period, "form": form, "links": links})
    return out


def _pick_best_pdf(rows: list[dict]) -> str | None:
    """From parsed rows, return the absolute URL of the preferred PDF.

    Priority:
      1. ANNUAL (წლიური) only — semi-annuals are skipped (no audited yearly
         numbers in those).
      2. Consolidated > Individual — groups file both; the consolidated
         report is the one with audited group-level numbers and is what
         our data layer reconciles against. Falls back to individual when
         only individual exists.
      3. Within the chosen row, Georgian filing > English > anything else,
         updated revision > original.

    Returns None if no annual row exists at all.
    """
    annual = [r for r in rows if r["period"] == ANNUAL_KA]
    if not annual:
        return None

    consolidated = [r for r in annual if r["form"] == CONSOLIDATED_KA]
    pick_row = consolidated[0] if consolidated else annual[0]

    def link_rank(link: dict) -> tuple:
        # Lower is better. Sort key: (lang_priority, not_updated).
        lang_priority = {"ka": 0, "en": 1}.get(link["lang"], 2)
        return (lang_priority, 0 if link["updated"] else 1)

    best = sorted(pick_row["links"], key=link_rank)[0]
    href = best["href"]
    return href if href.startswith("http") else BASE_URL + href


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_year_html(idcode: str, year: int) -> tuple[int, str]:
    """Raw response for the year's reports HTML partial.

    Cached for 1h per (idcode, year). Returns ``(status_code, text)``;
    callers handle parsing. Errors return ``(0, error_message)``.
    """
    cookie = _get_cookie()
    if not cookie:
        return (0, "REPORTAL_COOKIE not configured")
    session = _session_for_cookie(cookie, idcode=str(idcode))
    try:
        resp = session.get(
            f"{BASE_URL}/ka/Reports/OrgReportsByYear",
            params={"q": str(idcode), "year": int(year)},
            timeout=TIMEOUT_META,
        )
    except requests.exceptions.Timeout:
        return (0, "timeout")
    except requests.exceptions.ConnectionError:
        return (0, "connection error")
    except Exception as e:
        return (0, f"{type(e).__name__}")
    return (resp.status_code, resp.text)


def get_pdf_url(idcode: str, year: int) -> str | None:
    """Resolve the direct PDF URL for one company-year on reportal.ge.

    Returns an absolute URL like ``https://reportal.ge/ka/Reports/GetFile/74033``
    pointing to the preferred annual-report PDF, or ``None`` when:
      - no REPORTAL_COOKIE is configured
      - reportal.ge has no annual filing for this company-year
      - the HTTP / parse step fails

    The URL is meant to be opened in the user's browser. Their browser
    needs its own reportal.ge session cookie for the download to succeed.

    Indirectly cached for 1h via ``_fetch_year_html`` — the HTML fetch is
    the expensive step; parsing is fast.
    """
    status, text = _fetch_year_html(idcode, year)
    if status != 200:
        return None
    rows = _parse_reports_table(text)
    return _pick_best_pdf(rows)


def get_pdf_urls_for_years(idcode: str, years: list[int]) -> dict[int, str | None]:
    """Batch-resolve direct PDF URLs for many years of one company.

    Returns ``{year: url_or_None}``. Each year's HTML is cached for 1h, so
    repeat invocations within an hour are free.
    """
    return {int(y): get_pdf_url(idcode, int(y)) for y in years}


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_report_pdf(idcode: str, year: int) -> tuple[bytes | None, str]:
    """Download the preferred annual-report PDF for one company-year.

    Returns ``(pdf_bytes, status_message)``. ``pdf_bytes`` is ``None`` on
    any failure (cookie missing, cookie expired, no annual report on file,
    download error). The status message is short and user-facing — surface
    it directly in the UI.

    Cached for 1 hour per (idcode, year).
    """
    cookie = _get_cookie()
    if not cookie:
        return None, (
            "REPORTAL_COOKIE secret not configured. PDF downloads need a "
            "reportal.ge session cookie set as the `REPORTAL_COOKIE` env var "
            "(local) or Space secret (deployment)."
        )

    status, text = _fetch_year_html(idcode, year)
    if status in (401, 403):
        return None, (
            f"reportal.ge returned HTTP {status} — the REPORTAL_COOKIE has "
            "expired. Refresh it from browser DevTools "
            "(Application → Cookies → reportal.ge)."
        )
    if status == 0:
        return None, f"reportal.ge fetch failed: {text}"
    if status != 200:
        return None, f"reportal.ge returned HTTP {status} for the {year} metadata."

    rows = _parse_reports_table(text)
    pdf_url = _pick_best_pdf(rows)
    if not pdf_url:
        return None, f"No annual report on reportal.ge for {year}."

    session = _session_for_cookie(cookie, idcode=str(idcode))
    try:
        pdf_resp = session.get(pdf_url, timeout=TIMEOUT_PDF)
    except requests.exceptions.Timeout:
        return None, f"Timed out downloading the {year} PDF (reportal.ge may be slow)."
    except Exception as e:
        return None, f"PDF download failed: {type(e).__name__}"
    if pdf_resp.status_code != 200:
        return None, f"PDF endpoint returned HTTP {pdf_resp.status_code}."

    return pdf_resp.content, f"{len(pdf_resp.content) / 1024:.0f} KB"
