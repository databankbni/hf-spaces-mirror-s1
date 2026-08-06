"""Shared user-configurable metric picker (S&P Capital IQ comp-set style).

Lets the user choose which metric columns appear in the Screener results table,
the Sector aggregate / contribution tables, and the Compare aggregate tables.

Design:
  * ``CURATED_METRICS`` is an ordered list of ``(label, column)`` pairs — the
    user-facing menu. Labels are display names; columns are ``metrics_panel``
    column names.
  * ``available_metrics(db_path)`` reflects the live ``metrics_panel`` schema
    and DROPS any curated metric whose column doesn't exist (so the picker can
    never offer a column the DB can't serve). Pure resolution lives in
    :func:`resolve_available` so it is unit-testable without a DB.
  * ``render_metric_picker(...)`` renders one ``st.multiselect`` and returns the
    chosen *column* list. Session-only persistence via the widget's own state.

Persistence / Sprint-26 safety: the multiselect's session_state key is only
ever written BEFORE the widget instantiates (defaults are passed via the
``default=`` parameter on first render; Streamlit keeps the user's choice in
session_state thereafter). We never write the widget key in the same run after
the widget is created.
"""
from __future__ import annotations

import sqlite3

import streamlit as st

from lib.ui import safe_key

# ---------------------------------------------------------------------------
# Curated, ordered metric catalogue: (display label, metrics_panel column).
# Order here = order shown in the picker AND the order columns appear in tables.
# Every column is verified against the live schema by ``available_metrics``;
# unknown columns are silently dropped so this list can stay aspirational.
# ---------------------------------------------------------------------------
CURATED_METRICS: list[tuple[str, str]] = [
    # --- Size (raw GEL) ---
    ("Revenue", "Revenue"),
    ("Gross profit", "GrossProfit"),
    ("EBITDA", "EBITDA"),
    ("EBIT", "EBIT"),
    ("Net profit", "NetProfit"),
    ("Total assets", "TotalAssets"),
    ("Total equity", "TotalEquity"),
    ("Total cash", "TotalCash"),
    ("Total debt", "TotalDebt"),
    ("Net debt", "NetDebt"),
    # --- Margins / returns (decimals -> rendered as %) ---
    ("Gross margin", "GrossMargin"),
    ("EBITDA margin", "EBITDAMargin"),
    ("Net margin", "NetMargin"),
    ("ROE", "ROE"),
    ("ROA", "ROA"),
    ("ROIC", "ROIC"),
    # --- Leverage / efficiency (pure ratios) ---
    ("Net debt / EBITDA", "NetDebtToEBITDA"),
    ("Asset turnover", "AssetTurnover"),
    # --- Growth (decimals -> rendered as %) ---
    ("Revenue YoY", "Revenue_YoY"),
    ("Revenue 3yr CAGR", "Revenue_3yrCAGR"),
    ("Revenue 5yr CAGR", "Revenue_5yrCAGR"),
    ("EBITDA YoY", "EBITDA_YoY"),
    ("EBITDA 3yr CAGR", "EBITDA_3yrCAGR"),
    ("Net profit YoY", "NetProfit_YoY"),
    ("Net profit 3yr CAGR", "NetProfit_3yrCAGR"),
]

# Reverse map column -> label, used to render multiselect entries by label.
_COLUMN_TO_LABEL: dict[str, str] = {col: label for label, col in CURATED_METRICS}

# ---------------------------------------------------------------------------
# Formatting classification (mirrors lib.screener) — consumers use these to
# decide how to render a value: percent (decimal), ratio (×), or money (K GEL).
# ---------------------------------------------------------------------------
PERCENT_COLUMNS: frozenset[str] = frozenset(
    {"GrossMargin", "EBITDAMargin", "NetMargin", "ROE", "ROA", "ROIC"}
    | {col for _label, col in CURATED_METRICS if col.endswith("_YoY") or "CAGR" in col}
)
RATIO_COLUMNS: frozenset[str] = frozenset({"NetDebtToEBITDA", "AssetTurnover"})


def is_percent_column(col: str) -> bool:
    return col in PERCENT_COLUMNS


def is_ratio_column(col: str) -> bool:
    return col in RATIO_COLUMNS


def is_money_column(col: str) -> bool:
    return col not in PERCENT_COLUMNS and col not in RATIO_COLUMNS


def label_for(col: str) -> str:
    """Display label for a metrics_panel column (falls back to the column name)."""
    return _COLUMN_TO_LABEL.get(col, col)


# ---------------------------------------------------------------------------
# Available-metric resolution (pure — unit-testable without Streamlit/DB)
# ---------------------------------------------------------------------------
def resolve_available(
    existing_columns: set[str] | frozenset[str] | list[str],
) -> list[tuple[str, str]]:
    """Filter ``CURATED_METRICS`` down to those whose column actually exists.

    Pure function: pass the set of column names present in ``metrics_panel`` and
    get back the curated (label, column) pairs that can be served, in curated
    order. Unknown columns are dropped.
    """
    present = set(existing_columns)
    return [(label, col) for label, col in CURATED_METRICS if col in present]


@st.cache_data(show_spinner=False, ttl=3600)
def _metrics_panel_columns(db_path: str) -> list[str]:
    """Return the live ``metrics_panel`` column names (cached, read-only)."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute("PRAGMA table_info(metrics_panel)")
        return [row[1] for row in cur.fetchall()]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def available_metrics(db_path: str) -> list[tuple[str, str]]:
    """Curated (label, column) pairs whose column exists in this DB's panel.

    Falls back to the full curated list if the schema can't be read (e.g. the
    panel table is missing) so the picker still renders something sensible.
    """
    cols = _metrics_panel_columns(db_path)
    if not cols:
        return list(CURATED_METRICS)
    return resolve_available(cols)


def sanitize_defaults(
    default_columns: list[str], available_columns: list[str]
) -> list[str]:
    """Keep only defaults that are available, preserving the given order.

    Used to make sure a per-view default set never references a column the DB
    dropped (which would make st.multiselect raise on an out-of-range default).
    """
    avail = set(available_columns)
    return [c for c in default_columns if c in avail]


# ---------------------------------------------------------------------------
# Streamlit component
# ---------------------------------------------------------------------------
def render_metric_picker(
    db_path: str,
    context_key: str,
    default_metrics: list[str],
    *,
    container=None,
    label: str = "Metrics to display",
    help: str | None = None,
) -> list[str]:
    """Render the metric multiselect and return the chosen *column* list.

    Parameters
    ----------
    db_path:
        Path to the DB — used to resolve which curated metrics are available.
    context_key:
        A per-view discriminator (e.g. ``"screener"``, ``"sector"``,
        ``"compare"``) so each view keeps its own independent selection in
        session state.
    default_metrics:
        Ordered list of *column* names to pre-select on first render. Columns
        not available in this DB are dropped.
    container:
        Optional Streamlit container to render into (e.g. ``st.sidebar``).
        Defaults to the main area.
    label / help:
        Passed through to the multiselect.

    Returns
    -------
    list[str]
        Chosen metric *columns*, returned in CURATED order (stable table
        column order regardless of selection click order).

    Session-only persistence: Streamlit stores the chosen value under the
    widget key, so the selection survives reruns within the session. We never
    write that key after the widget renders (Sprint-26 safe).
    """
    target = container if container is not None else st
    available = available_metrics(db_path)
    available_cols = [col for _label, col in available]
    label_by_col = {col: lbl for lbl, col in available}

    defaults = sanitize_defaults(default_metrics, available_cols)
    if not defaults and available_cols:
        # Never start fully empty — that would render an empty table.
        defaults = available_cols[: min(4, len(available_cols))]

    widget_key = safe_key("metric_picker", context_key)
    chosen = target.multiselect(
        label,
        options=available_cols,
        default=defaults,
        format_func=lambda c: label_by_col.get(c, c),
        key=widget_key,
        help=help
        or (
            "Choose which metric columns appear in the table below. "
            "Your selection is remembered for this session."
        ),
    )
    # Return in curated order so columns are stable regardless of pick order.
    chosen_set = set(chosen)
    ordered = [col for col in available_cols if col in chosen_set]
    # Guard: if the user cleared everything, fall back to the defaults so the
    # consuming table is never column-less.
    return ordered or defaults


# Per-view sensible defaults (column names). Kept here so all three views share
# one source of truth and tests can assert on them.
SCREENER_DEFAULT_COLUMNS: list[str] = ["Revenue", "EBITDA", "EBITDAMargin", "NetProfit"]
SECTOR_DEFAULT_COLUMNS: list[str] = ["Revenue", "EBITDA", "NetProfit", "TotalAssets"]
COMPARE_DEFAULT_COLUMNS: list[str] = ["Revenue", "EBITDA", "NetProfit", "TotalAssets"]


# ---------------------------------------------------------------------------
# Peer-percentile ranking (Feature 4 — pure, unit-testable; no Streamlit/DB)
# ---------------------------------------------------------------------------
def percentile_within_group(df, value_col: str, group_col: str):
    """Percentile rank (0–1) of each row's ``value_col`` within its ``group_col``.

    ``metrics_panel`` holds the full per-year cross-section, so a peer percentile
    (e.g. "EBITDA margin in the 78th pct of its sector") is a cheap
    ``groupby(group_col)[value_col].rank(pct=True)``. Higher value -> higher
    percentile (``ascending=False`` is NOT used; 1.0 is the top of the group).

    NaN values stay NaN (they don't get a percentile and don't shift the ranks
    of the real values — pandas ``rank`` skips them by default). Returned Series
    is aligned to ``df``'s index so the caller can assign it back as a column.
    """
    import pandas as pd  # local import keeps the module import light

    if df is None or len(df) == 0:
        return pd.Series(dtype=float)
    if value_col not in df.columns or group_col not in df.columns:
        # Aligned all-NaN series so the caller can assign it back without
        # raising or misaligning when a column is absent.
        return pd.Series(float("nan"), index=df.index, dtype=float)
    return df.groupby(group_col)[value_col].rank(pct=True)


def fmt_percentile(p) -> str:
    """Render a 0–1 percentile as a friendly ordinal-ish string ('78th pct').

    Blank for NaN/None. Rounds to the nearest whole percentile; clamps to the
    1–100 readable range so 0.0 doesn't read as "0th".
    """
    import math

    if p is None:
        return ""
    try:
        f = float(p)
    except (TypeError, ValueError):
        return ""
    if f != f:  # NaN
        return ""
    pct = int(round(max(0.0, min(1.0, f)) * 100))
    pct = max(1, pct)  # 0th percentile is not a useful label
    # English ordinal suffix.
    if 10 <= pct % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(pct % 10, "th")
    return f"{pct}{suf} pct"
