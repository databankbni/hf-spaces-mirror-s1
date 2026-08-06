"""Generic client for the Geostat PxWeb API v1 (``pc-axis.geostat.ge``).

Geostat exposes its whole statistical database through a standard **PxWeb**
JSON API — the same protocol Statistics Sweden and other NSIs use. This module
is a thin, *pure* client over it: navigate the table tree, read a table's
metadata (dimensions + their value codes/labels), and POST a value selection to
pull the actual numbers back as tidy rows. No DB, no Streamlit, no app globals —
callers inject a ``requests.Session`` (or let the module make one) so the whole
thing is unit-testable against recorded fixtures.

Why generic: the macro pipeline pulls ~15 different Geostat tables (GDP, labour,
trade, FDI, CPI …). Rather than a bespoke parser per table, every dataset is a
declarative spec (see ``scripts/import_macro_geostat.py``) that names a table
path + which dimension values to keep; this client does the fetching/parsing.

Key quirks handled here (learned the hard way against the live API):
  * **UTF-8 BOM** — every response is prefixed with a BOM; ``requests``' ``.json()``
    chokes on it, so we decode ``utf-8-sig`` by hand.
  * **Provisional markers** — period labels for not-yet-final data carry a
    trailing ``*`` (e.g. ``"2025*"``, ``"I 26*"``); the period parser strips it.
  * **Mixed time granularity in one dimension** — National-Accounts tables put
    quarters *and* annual totals in a single "Period" dimension (``"I 24"`` next
    to ``"2024"``); other tables split Year/Month into separate dimensions. The
    client stays agnostic: it returns every dimension's *label* per row and
    exposes :func:`parse_period` / :func:`combine_year_period` helpers so each
    spec normalises time however its table encodes it.
  * **Cell caps** — PxWeb rejects oversized selections; :func:`fetch` transparently
    chunks the request across the largest dimension and concatenates.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Iterable, Sequence
from urllib.parse import quote

DEFAULT_BASE = "https://pc-axis.geostat.ge/PXWeb/api/v1/en/Database"
_USER_AGENT = "Mozilla/5.0 (compatible; ReportalMacroBot/1.0)"

# PxWeb refuses selections above a per-call cell cap. The Geostat instance
# tolerates large pulls, but we chunk defensively well under any plausible cap.
_MAX_CELLS_PER_CALL = 40_000


class PxWebError(RuntimeError):
    """Raised on any navigation / metadata / query / parse failure."""


# ---------------------------------------------------------------------------
# HTTP plumbing
# ---------------------------------------------------------------------------

def make_session() -> "requests.Session":  # noqa: F821 (requests imported lazily)
    import requests

    s = requests.Session()
    s.headers["User-Agent"] = _USER_AGENT
    return s


def _url(base: str, parts: Sequence[str]) -> str:
    return base + "/" + "/".join(quote(p) for p in parts)


def _decode_json(content: bytes) -> object:
    """Decode a PxWeb response body, tolerating the leading UTF-8 BOM."""
    try:
        return json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PxWebError(f"Could not decode PxWeb JSON: {exc}") from exc


def _get(session, url: str, *, retries: int = 3, timeout: float = 60.0):
    import requests

    last: Exception | None = None
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=timeout)
            r.raise_for_status()
            return _decode_json(r.content)
        except requests.RequestException as exc:  # network / HTTP
            last = exc
            time.sleep(1.0 + attempt)
    raise PxWebError(f"GET failed after {retries} tries: {url} ({last})")


def _post(session, url: str, payload: dict, *, retries: int = 3, timeout: float = 120.0):
    import requests

    last: Exception | None = None
    for attempt in range(retries):
        try:
            r = session.post(url, json=payload, timeout=timeout)
            r.raise_for_status()
            return _decode_json(r.content)
        except requests.RequestException as exc:
            last = exc
            time.sleep(1.0 + attempt)
    raise PxWebError(f"POST failed after {retries} tries: {url} ({last})")


# ---------------------------------------------------------------------------
# Metadata model
# ---------------------------------------------------------------------------

@dataclass
class Variable:
    """One dimension of a PxWeb table (its code + parallel value/label lists)."""

    code: str
    text: str
    values: list[str]
    value_texts: list[str]
    time: bool = False
    elimination: bool = False

    def label_for(self, value_code: str) -> str:
        try:
            return self.value_texts[self.values.index(value_code)]
        except ValueError:
            return value_code

    def select(self, matchers: "Selector") -> list[str]:
        """Resolve ``matchers`` to concrete value codes (order preserved).

        ``matchers`` is one of:
          * ``"*"`` / ``ALL`` — every value.
          * an iterable of matcher specs, each either
              - a plain string → an **exact** value *code* or an **exact**
                value *label* (case-insensitive, whitespace-trimmed), or
              - a compiled ``re.Pattern`` → *searched* against labels (use this
                for prefix/substring matching).
        Exact-by-default avoids a short label accidentally capturing a longer
        one (e.g. "Employed" also hitting "Self-employed"/"Unemployed", or
        "Core Inflation" also hitting "Core Inflation without tobacco").
        Matching by label (not a hard-coded index) keeps specs robust to Geostat
        re-indexing a table's rows between releases.
        """
        if matchers is ALL or matchers == "*":
            return list(self.values)
        picked: list[str] = []
        for m in matchers:  # type: ignore[union-attr]
            picked.extend(self._match_one(m))
        # de-dupe, preserve order
        seen: set[str] = set()
        out: list[str] = []
        for c in picked:
            if c not in seen:
                seen.add(c)
                out.append(c)
        return out

    def _match_one(self, m) -> list[str]:
        if isinstance(m, re.Pattern):
            return [
                code
                for code, lab in zip(self.values, self.value_texts)
                if m.search(lab)
            ]
        s = str(m)
        # Exact value code first, then exact label (case-insensitive, trimmed).
        if s in self.values:
            return [s]
        target = s.strip().lower()
        return [
            code
            for code, lab in zip(self.values, self.value_texts)
            if lab.strip().lower() == target
        ]


class _All:
    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return "ALL"


ALL = _All()
Selector = object  # documentation alias: "*" | _All | Iterable[str | re.Pattern]


@dataclass
class Table:
    title: str
    variables: list[Variable]
    path: list[str] = field(default_factory=list)

    def var(self, code_or_text: str) -> Variable:
        for v in self.variables:
            if v.code == code_or_text or v.text == code_or_text:
                return v
        # loose contains match on text
        low = code_or_text.lower()
        for v in self.variables:
            if low in v.text.lower():
                return v
        raise PxWebError(
            f"No dimension {code_or_text!r} in table (have "
            f"{[v.code for v in self.variables]})"
        )

    def time_var(self) -> Variable:
        for v in self.variables:
            if v.time:
                return v
        # Fall back: many Geostat tables omit the time flag but name it Period/Year.
        for v in self.variables:
            if re.search(r"period|year|month|quarter", v.text, re.I):
                return v
        raise PxWebError("Table has no identifiable time dimension.")


# ---------------------------------------------------------------------------
# Tree navigation + metadata
# ---------------------------------------------------------------------------

def list_node(parts: Sequence[str], *, base: str = DEFAULT_BASE, session=None) -> list[dict]:
    """List child nodes/tables under ``parts`` (``[]`` for the DB root)."""
    session = session or make_session()
    data = _get(session, _url(base, parts))
    if not isinstance(data, list):
        raise PxWebError(f"Expected a node list at {parts!r}, got {type(data)}")
    return data


def get_table(parts: Sequence[str], *, base: str = DEFAULT_BASE, session=None) -> Table:
    """Fetch a table's metadata (its dimensions and value codes/labels)."""
    session = session or make_session()
    meta = _get(session, _url(base, parts))
    return parse_table_meta(meta, list(parts))


def parse_table_meta(meta: dict, path: list[str] | None = None) -> Table:
    """Parse a PxWeb metadata dict into a :class:`Table` (pure — no network)."""
    if not isinstance(meta, dict) or "variables" not in meta:
        raise PxWebError("Malformed PxWeb metadata (no 'variables').")
    variables = [
        Variable(
            code=v["code"],
            text=v.get("text", v["code"]),
            values=list(v.get("values", [])),
            value_texts=list(v.get("valueTexts", v.get("values", []))),
            time=bool(v.get("time")),
            elimination=bool(v.get("elimination")),
        )
        for v in meta["variables"]
    ]
    return Table(title=meta.get("title", ""), variables=variables, path=path or [])


# ---------------------------------------------------------------------------
# Data query
# ---------------------------------------------------------------------------

def _build_query(selection: dict[str, list[str]]) -> dict:
    return {
        "query": [
            {"code": code, "selection": {"filter": "item", "values": vals}}
            for code, vals in selection.items()
        ],
        "response": {"format": "json"},
    }


def _parse_data_response(resp: dict) -> tuple[list[str], list[dict]]:
    """Turn a PxWeb ``format=json`` response into (dim_codes, rows).

    Each row is ``{dim_code: value_code, ..., "value": float | None}`` — the raw
    dimension *value codes*, not labels (caller maps to labels via the Table).
    """
    if not isinstance(resp, dict) or "columns" not in resp or "data" not in resp:
        raise PxWebError("Malformed PxWeb data response (no columns/data).")
    dim_codes = [c["code"] for c in resp["columns"] if c.get("type") != "c"]
    rows: list[dict] = []
    for item in resp["data"]:
        key = item.get("key", [])
        raw_vals = item.get("values", [])
        row = {dim_codes[i]: key[i] for i in range(min(len(dim_codes), len(key)))}
        row["value"] = _to_float(raw_vals[0]) if raw_vals else None
        rows.append(row)
    return dim_codes, rows


def _to_float(v) -> float | None:
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    # PxWeb uses these tokens for "no data" / "not applicable".
    if s in ("", "..", "...", ":", "-", "N/A", "x"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _chunks_over_largest(selection: dict[str, list[str]]) -> list[dict[str, list[str]]]:
    """Split a selection into sub-queries under the cell cap.

    Chunks along whichever dimension has the most selected values, keeping every
    other dimension whole. Good enough for our tables (worst case a handful of
    calls); avoids ever tripping the PxWeb cell limit.
    """
    sizes = {k: max(1, len(v)) for k, v in selection.items()}
    total = 1
    for n in sizes.values():
        total *= n
    if total <= _MAX_CELLS_PER_CALL:
        return [selection]

    split_dim = max(sizes, key=lambda k: sizes[k])
    other = total // sizes[split_dim]
    per_chunk = max(1, _MAX_CELLS_PER_CALL // max(1, other))
    vals = selection[split_dim]
    chunks: list[dict[str, list[str]]] = []
    for i in range(0, len(vals), per_chunk):
        sub = dict(selection)
        sub[split_dim] = vals[i : i + per_chunk]
        chunks.append(sub)
    return chunks


def fetch(
    table: Table,
    selections: dict[str, "Selector"],
    *,
    base: str = DEFAULT_BASE,
    session=None,
    label_rows: bool = True,
) -> list[dict]:
    """Pull data for ``table`` and return tidy rows.

    ``selections`` maps dimension code (or text) → a selector (``"*"``/``ALL`` or
    an iterable of label/code matchers). Any dimension omitted defaults to ALL.

    Each returned row maps **dimension text → value label** (when ``label_rows``)
    plus ``{"value": float | None}``. Example row::

        {"Activity": "(=) GDP at market prices", "Period": "2024", "value": 93022.28}
    """
    session = session or make_session()

    # Resolve selectors → concrete value codes, keyed by dimension code.
    resolved: dict[str, list[str]] = {}
    for var in table.variables:
        sel = selections.get(var.code, selections.get(var.text, ALL))
        codes = var.select(sel)
        if not codes:
            raise PxWebError(
                f"Selection for dimension {var.code!r} matched nothing "
                f"(selector={sel!r})."
            )
        resolved[var.code] = codes

    url = _url(base, table.path)
    all_rows: list[dict] = []
    for chunk in _chunks_over_largest(resolved):
        resp = _post(session, url, _build_query(chunk))
        _dim_codes, rows = _parse_data_response(resp)
        all_rows.extend(rows)

    if not label_rows:
        return all_rows

    by_code = {v.code: v for v in table.variables}
    labelled: list[dict] = []
    for r in all_rows:
        out = {"value": r.get("value")}
        for code, var in by_code.items():
            if code in r:
                out[var.text] = var.label_for(r[code])
        labelled.append(out)
    return labelled


# ---------------------------------------------------------------------------
# Period parsing helpers (time labels vary table-to-table)
# ---------------------------------------------------------------------------

_ROMAN_Q = {"I": 1, "II": 2, "III": 3, "IV": 4}
# CPI/core-inflation tables index months by roman numeral I…XII (I = January).
_ROMAN_MONTH = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6,
    "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12,
}
_MONTHS = {
    m.lower(): i
    for i, m in enumerate(
        [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ],
        start=1,
    )
}
# Common Geostat abbreviations / alt spellings.
_MONTHS.update({"sept": 9})


def _yy_to_year(yy: int) -> int:
    """Two-digit Geostat year → four digits (data starts 1995)."""
    return 1900 + yy if yy >= 90 else 2000 + yy


def parse_period(text: str) -> tuple[str | None, str | None]:
    """Normalise a single PxWeb period label.

    Returns ``(normalised, kind)`` where *kind* ∈ {"annual","quarter","month"}
    and *normalised* is ``"YYYY"`` / ``"YYYY-Qn"`` / ``"YYYY-MM"``. Returns
    ``(None, None)`` for labels we don't treat as a plottable period (cumulative
    ``"I_II 24"``, half-years, etc.). Trailing ``*`` provisional markers and
    stray whitespace are stripped.
    """
    if text is None:
        return None, None
    t = str(text).strip().rstrip("*").strip()

    # Plain annual: "2024"
    m = re.fullmatch(r"(\d{4})", t)
    if m:
        return m.group(1), "annual"

    # Quarter: "I 24", "I  06", "IV 2024"
    m = re.fullmatch(r"(I|II|III|IV)\s+(\d{2}|\d{4})", t)
    if m:
        q = _ROMAN_Q[m.group(1)]
        yr = int(m.group(2))
        yr = yr if yr > 100 else _yy_to_year(yr)
        return f"{yr}-Q{q}", "quarter"

    # Quarter alt: "2024 I", "2024-Q1", "Q1 2024"
    m = re.fullmatch(r"(\d{4})[\s\-]*Q?(1|2|3|4)", t)
    if m:
        return f"{m.group(1)}-Q{m.group(2)}", "quarter"
    m = re.fullmatch(r"Q(1|2|3|4)[\s\-]*(\d{4})", t)
    if m:
        return f"{m.group(2)}-Q{m.group(1)}", "quarter"

    # Month name + year: "January 2024", "Jan 2024"
    m = re.fullmatch(r"([A-Za-z]+)\.?\s+(\d{4})", t)
    if m and _month_num(m.group(1)):
        return f"{m.group(2)}-{_month_num(m.group(1)):02d}", "month"

    # Numeric month: "2024-03", "2024/03", "03.2024", "2024 3"
    m = re.fullmatch(r"(\d{4})[\-/\s](\d{1,2})", t)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(1)}-{int(m.group(2)):02d}", "month"
    m = re.fullmatch(r"(\d{1,2})[\.\-/](\d{4})", t)
    if m and 1 <= int(m.group(1)) <= 12:
        return f"{m.group(2)}-{int(m.group(1)):02d}", "month"

    return None, None


def _month_num(name: str) -> int | None:
    key = name.strip().lower().rstrip(".")
    if key in _MONTHS:
        return _MONTHS[key]
    for full, num in _MONTHS.items():
        if full.startswith(key) and len(key) >= 3:
            return num
    return None


def _year_of(year_label: str) -> str | None:
    y = str(year_label).strip().rstrip("*").strip()
    m = re.fullmatch(r"(\d{4})", y)
    return m.group(1) if m else None


def combine_year_period(year_label: str, sub_label: str) -> tuple[str | None, str | None]:
    """Normalise a table that splits time across two dimensions (Year + Quarter).

    Handles labour/FDI tables whose "Years" and "Quarters" live in separate
    dimensions. ``sub_label`` may be an annual-total sentinel (``"annual"``,
    ``"Total"``, ``"Q I-IV"``) → the plain year, a roman quarter (optionally
    ``"Q "``-prefixed, e.g. ``"Q II"``) → ``YYYY-Qn``, or a numeric/named month.
    Returns ``(None, None)`` if it can't classify the sub-label.
    """
    year = _year_of(year_label)
    if year is None:
        return None, None
    s = str(sub_label).strip().rstrip("*").strip()
    s = re.sub(r"^Q\s*", "", s, flags=re.I).strip()  # drop a leading "Q " prefix

    # Annual sentinels: "annual", "Total", "year", "" and the full-year span "I-IV".
    if s == "" or re.search(r"annual|total|year", s, re.I) or re.fullmatch(r"I[\-_ ]?IV", s, re.I):
        return year, "annual"
    if s.upper() in _ROMAN_Q:
        return f"{year}-Q{_ROMAN_Q[s.upper()]}", "quarter"
    mn = _month_num(s)
    if mn:
        return f"{year}-{mn:02d}", "month"
    m = re.fullmatch(r"(\d{1,2})", s)
    if m and 1 <= int(m.group(1)) <= 12:
        return f"{year}-{int(m.group(1)):02d}", "month"
    return None, None


def combine_year_roman_month(year_label: str, month_label: str) -> tuple[str | None, str | None]:
    """Normalise Year + roman-numeral-month tables (CPI, core inflation: I…XII)."""
    year = _year_of(year_label)
    if year is None:
        return None, None
    mn = _ROMAN_MONTH.get(str(month_label).strip().rstrip("*").strip().upper())
    if mn is None:
        return None, None
    return f"{year}-{mn:02d}", "month"
