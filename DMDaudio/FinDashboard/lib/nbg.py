"""Client for the National Bank of Georgia (NBG) public data gateway.

Three of the macro-page indicators are NBG's, not Geostat's: the **monetary
policy (refinancing) rate**, **remittances / money transfers by country**, and
**balance-of-payments / current-account** components. NBG serves them from a
JSON gateway at ``https://nbg.gov.ge/gw/api/ct/`` (the same backend its Next.js
site calls). This module is a thin, pure client over it — no DB, no Streamlit.

Quirks (same family as Geostat's PxWeb):
  * responses carry a UTF-8 BOM → decode ``utf-8-sig``;
  * a browser-ish User-Agent + Referer are needed or some routes 401/empty;
  * ``MonetaryPolicy/Rates`` is paginated with ``take`` capped below 100.
"""
from __future__ import annotations

import json
import time

GATEWAY = "https://nbg.gov.ge/gw/api/ct/"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ReportalMacroBot/1.0)",
    "Accept": "application/json",
    "Referer": "https://nbg.gov.ge/en/statistics/statistics-data",
}


class NbgError(RuntimeError):
    pass


def make_session():
    import requests

    s = requests.Session()
    s.headers.update(_HEADERS)
    return s


def _get_json(session, url: str, *, retries: int = 3, timeout: float = 45.0):
    import requests

    last: Exception | None = None
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=timeout)
            r.raise_for_status()
            return json.loads(r.content.decode("utf-8-sig"))
        except (requests.RequestException, json.JSONDecodeError) as exc:
            last = exc
            time.sleep(1.0 + attempt)
    raise NbgError(f"GET failed after {retries} tries: {url} ({last})")


# ---------------------------------------------------------------------------
# Monetary policy (refinancing) rate
# ---------------------------------------------------------------------------

def fetch_policy_rate_decisions(session=None) -> list[dict]:
    """Return every NBG monetary-policy-rate decision, newest first.

    Each item: ``{"date": ISO-datetime, "rate": float, "change": float}``. The
    endpoint paginates with ``take`` < 100, so we walk pages until exhausted.
    """
    session = session or make_session()
    out: list[dict] = []
    page, take = 1, 99
    while True:
        payload = _get_json(
            session, f"{GATEWAY}MonetaryPolicy/Rates?page={page}&take={take}"
        )
        data = payload.get("data", []) if isinstance(payload, dict) else []
        for d in data:
            try:
                out.append({
                    "date": str(d["date"]),
                    "rate": float(d["rate"]),
                    "change": float(d.get("change") or 0.0),
                })
            except (KeyError, TypeError, ValueError):
                continue
        meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
        total = int(meta.get("total", len(out)))
        if len(out) >= total or not data:
            break
        page += 1
        if page > 50:  # safety backstop
            break
    if not out:
        raise NbgError("No policy-rate decisions returned.")
    return out


def fetch_annual_inflation(session=None) -> dict:
    """Current headline annual-inflation reading + NBG's target (snapshot)."""
    session = session or make_session()
    j = _get_json(session, f"{GATEWAY}MonetaryPolicy/AnnualInflation")
    return {
        "annual_inflation": _f(j.get("annualInflationValue")),
        "target": _f(j.get("targetedAnnualInflationValue")),
        "next_update": j.get("furtherUpdateValue"),
    }


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Money transfers (remittances) by country
# ---------------------------------------------------------------------------

# Cookie-free workbook on the NBG file server (folder = "სტატისტიკა", URL-encoded).
REMITTANCES_XLSX_URL = (
    "https://nbg.gov.ge/fm/"
    "%E1%83%A1%E1%83%A2%E1%83%90%E1%83%A2%E1%83%98%E1%83%A1%E1%83%A2%E1%83%98%E1%83%99%E1%83%90"
    "/external_sector/eng/money-transfers-by-countries-eng.xlsx"
)
REMITTANCES_SHEET = "2012-2026 (eng) "  # note the trailing space in the sheet name


def download_remittances_xlsx(session=None, *, timeout: float = 90.0) -> bytes:
    session = session or make_session()
    import requests

    try:
        r = session.get(REMITTANCES_XLSX_URL, timeout=timeout)
        r.raise_for_status()
    except requests.RequestException as exc:
        raise NbgError(f"remittances download failed: {exc}") from exc
    if not r.content:
        raise NbgError("remittances download returned empty body")
    return r.content


def parse_remittances(xlsx_bytes: bytes, *, flow: str = "Inflow") -> list[dict]:
    """Parse the money-transfers workbook into tidy rows.

    Layout (``header=None``): row 2 carries the monthly period date for each
    2-column period block; row 3 labels the two columns ``Inflow`` / ``Outflow``;
    col 0 from row 4 down holds "Money transfers, total" then country names.

    ``flow`` selects Inflow (money received into Georgia — the usual "remittances"
    reading) or Outflow. Returns ``[{"country", "period" (YYYY-MM), "value"}]``
    for every non-null cell (value in thousand USD). "Money transfers, total" is
    surfaced as country ``"TOTAL"``.
    """
    import io
    from datetime import datetime

    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), data_only=True, read_only=True)
    try:
        ws = wb[REMITTANCES_SHEET] if REMITTANCES_SHEET in wb.sheetnames else _pick_sheet(wb)
        grid = [list(r) for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()
    if len(grid) < 6:
        raise NbgError("remittances sheet too short — layout changed?")

    date_row, sub_row = grid[2], grid[3]
    want = flow.strip().lower()
    # Map each period's date to the column carrying the requested flow.
    period_cols: dict[int, str] = {}
    for col, cell in enumerate(date_row):
        if isinstance(cell, datetime):
            ym = f"{cell.year}-{cell.month:02d}"
            # Inflow sits at this col, Outflow at col+1 (per the sub-header row).
            for c in (col, col + 1):
                lab = sub_row[c] if c < len(sub_row) else None
                if isinstance(lab, str) and lab.strip().lower() == want:
                    period_cols[c] = ym
    if not period_cols:
        raise NbgError(f"no '{flow}' columns found — layout changed?")

    rows: list[dict] = []
    for r in range(4, len(grid)):
        label = grid[r][0] if grid[r] else None
        if not isinstance(label, str) or not label.strip():
            continue
        name = label.strip()
        country = "TOTAL" if name.lower().startswith("money transfers, total") else name
        for col, ym in period_cols.items():
            val = grid[r][col] if col < len(grid[r]) else None
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                rows.append({"country": country, "period": ym, "value": float(val)})
    if not rows:
        raise NbgError("parsed zero remittance rows")
    return rows


def _pick_sheet(wb):
    for name in wb.sheetnames:
        if name.strip().lower().startswith("2012"):
            return wb[name]
    return wb[wb.sheetnames[0]]


# ---------------------------------------------------------------------------
# Balance of payments — current account (BPM5 analytical presentation)
# ---------------------------------------------------------------------------

BOP_XLSX_URL = (
    "https://nbg.gov.ge/fm/"
    "%E1%83%A1%E1%83%A2%E1%83%90%E1%83%A2%E1%83%98%E1%83%A1%E1%83%A2%E1%83%98%E1%83%99%E1%83%90"
    "/external_sector/eng/bop-bpm5-eng.xlsx"
)
BOP_SHEET = "BOP-anlt"  # quarterly analytical presentation, million USD

# Current-account decomposition (BPM5). Each output component is the NET of the
# listed source rows (debit rows are already negative in the sheet). They sum to
# the current-account balance (the TOTAL component).
_CA_COMPONENTS = [
    ("TOTAL", ["A. Current Account"]),               # current-account balance
    ("Goods", ["Balance on Goods"]),
    ("Services", ["Services: credit", "Services: debit"]),
    ("Primary income", ["Income: credit", "Income: debit"]),        # BPM5 "Income"
    ("Secondary income", ["Current transfers: credit", "Current transfers: debit"]),
]


def download_bop_xlsx(session=None, *, timeout: float = 120.0) -> bytes:
    session = session or make_session()
    import requests

    try:
        r = session.get(BOP_XLSX_URL, timeout=timeout)
        r.raise_for_status()
    except requests.RequestException as exc:
        raise NbgError(f"BoP download failed: {exc}") from exc
    if not r.content:
        raise NbgError("BoP download returned empty body")
    return r.content


def parse_bop_current_account(xlsx_bytes: bytes) -> list[dict]:
    """Parse the BPM5 analytical BoP sheet into current-account component rows.

    Returns ``[{"component", "period" (YYYY-Qn), "value"}]`` in million USD, for
    the current-account balance (component ``"TOTAL"``) and its Goods / Services /
    Primary-income / Secondary-income nets (which sum to the balance).
    """
    import io
    import re

    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), data_only=True, read_only=True)
    try:
        ws = wb[BOP_SHEET] if BOP_SHEET in wb.sheetnames else wb[wb.sheetnames[0]]
        grid = [list(r) for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()

    qre = re.compile(r"^(\d{4})Q([1-4])$")
    # Header = the row with the most "YYYYQn" cells.
    hdr_idx, best = 0, 0
    for i, row in enumerate(grid[:8]):
        cnt = sum(1 for c in row if isinstance(c, str) and qre.match(c.strip()))
        if cnt > best:
            best, hdr_idx = cnt, i
    if best == 0:
        raise NbgError("BoP: no quarter header found — layout changed?")
    qcols: dict[int, str] = {}
    for ci, c in enumerate(grid[hdr_idx]):
        if isinstance(c, str):
            m = qre.match(c.strip())
            if m:
                qcols[ci] = f"{m.group(1)}-Q{m.group(2)}"

    def _row(label: str):
        for row in grid:
            if row and isinstance(row[0], str) and row[0].strip() == label:
                return row
        return None

    out: list[dict] = []
    for comp, labels in _CA_COMPONENTS:
        srcs = [_row(l) for l in labels]
        if any(s is None for s in srcs):
            raise NbgError(f"BoP: missing row(s) for {comp} ({labels}) — layout changed?")
        for ci, period in qcols.items():
            nums = [s[ci] for s in srcs
                    if ci < len(s) and isinstance(s[ci], (int, float)) and not isinstance(s[ci], bool)]
            if not nums:
                continue
            out.append({"component": comp, "period": period, "value": round(sum(nums), 2)})
    if not out:
        raise NbgError("parsed zero BoP current-account rows")
    return out
