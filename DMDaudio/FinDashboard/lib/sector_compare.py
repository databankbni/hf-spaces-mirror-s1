"""Pure aggregation logic for the Sector-vs-Sector comparison (feat/sector-vs-sector).

This is the "Compare view, but the entities are sectors / sub-sectors instead of
companies". Given the per-company × per-year ``metrics_panel`` slice for a group
of companies (one sector or sub-sector), it computes a single aggregate row per
year, applying the right rule per metric kind:

* **money / size**  (Revenue, EBITDA, NetProfit, TotalAssets, …) → **sum**
  across the member companies.
* **derived margins** (Gross / EBITDA / Net Margin) → recomputed from the
  **summed numerator and denominator** (so the sector margin is the weighted
  margin, NOT the naive mean of per-company margins).
* **ratios / returns / growth** (ROE, ROA, ROIC, NetDebtToEBITDA,
  AssetTurnover, *_YoY, *_CAGR) → **mean** across the member companies that
  reported the metric that year (NaN-skipping).

No Streamlit / DB dependencies — every function takes a plain pandas DataFrame
shaped like a slice of ``metrics_panel`` (columns ``IdCode``, ``FVYear`` + the
metric columns). That keeps the rules unit-testable in isolation and guarantees
the numbers stay consistent with the Sector view's own sum-based aggregate.
"""
from __future__ import annotations

import pandas as pd

from lib.metric_picker import is_percent_column as _picker_is_percent
from lib.metric_picker import is_ratio_column as _picker_is_ratio
from views.shared import DERIVABLE_MARGINS

# ---------------------------------------------------------------------------
# Metric-kind classification (by metrics_panel column name).
#
# Column-kind decisions (money / percent / ratio) are sourced from the shared
# metric picker (`lib.metric_picker`) below so this view classifies columns
# exactly like the Screener / Sector views — no duplicated catalogue here. The
# derivable margins come from `views.shared.DERIVABLE_MARGINS`, the single
# source of truth for which margins are recomputed from summed bases.
# ---------------------------------------------------------------------------

# Derived margins — recomputed from the summed numerator / denominator rather
# than read straight or averaged. Maps the panel column → (numerator,
# denominator) money columns. Built from the shared DERIVABLE_MARGINS tuple so
# Sector View and Compare agree on which margins are weighted.
DERIVED_MARGIN_BASES: dict[str, tuple[str, str]] = {
    margin: (num, den) for margin, num, den in DERIVABLE_MARGINS
}


def metric_kind(column: str) -> str:
    """Classify a ``metrics_panel`` column into one aggregation rule.

    Returns one of ``"sum"`` (money/size), ``"derived_margin"`` (Gross/EBITDA/
    Net margin recomputed from summed bases) or ``"mean"`` (ratios, returns,
    growth — anything else, including ``*_YoY`` / ``*_CAGR``).

    Money vs. non-money is decided by :func:`is_money_column`, which delegates
    to the shared metric-picker classification.
    """
    if column in DERIVED_MARGIN_BASES:
        return "derived_margin"
    if is_money_column(column):
        return "sum"
    return "mean"


# ---------------------------------------------------------------------------
# Aggregation.
# ---------------------------------------------------------------------------

def aggregate_group_by_year(
    panel_slice: pd.DataFrame,
    metric_columns: list[str],
) -> pd.DataFrame:
    """Aggregate one group's per-company panel into one row per year.

    ``panel_slice`` must have ``IdCode`` + ``FVYear`` columns plus every metric
    column referenced in ``metric_columns`` (extra columns are ignored). For
    each ``FVYear`` it produces one aggregate row applying :func:`metric_kind`
    per requested column:

    * sum money columns,
    * recompute derived margins from the *summed* numerator / denominator
      (NaN when the summed denominator is 0),
    * mean (NaN-skipping) ratio / return / growth columns.

    Always adds an ``n`` column = number of distinct member companies
    contributing that year. Returns a DataFrame sorted by ``FVYear`` with
    columns ``["FVYear", "n", *metric_columns]``. Empty input → empty frame
    with that column shape.
    """
    out_cols = ["FVYear", "n"] + list(metric_columns)
    if panel_slice is None or panel_slice.empty:
        return pd.DataFrame(columns=out_cols)

    # Money columns we must sum — include the bases needed by any requested
    # derived margin even if the margin's own column wasn't requested directly.
    needed_money: set[str] = {c for c in metric_columns if metric_kind(c) == "sum"}
    for col in metric_columns:
        if metric_kind(col) == "derived_margin":
            num, den = DERIVED_MARGIN_BASES[col]
            needed_money.update({num, den})

    records: list[dict] = []
    for year, grp in panel_slice.groupby("FVYear"):
        rec: dict = {"FVYear": int(year), "n": int(grp["IdCode"].nunique())}

        # Summed money bases (used both for direct money metrics and margins).
        sums: dict[str, float] = {}
        for col in needed_money:
            sums[col] = float(grp[col].sum()) if col in grp.columns else 0.0

        for col in metric_columns:
            kind = metric_kind(col)
            if kind == "sum":
                rec[col] = sums.get(col, 0.0)
            elif kind == "derived_margin":
                num, den = DERIVED_MARGIN_BASES[col]
                denom = sums.get(den, 0.0)
                rec[col] = (sums.get(num, 0.0) / denom) if denom else float("nan")
            else:  # mean
                if col in grp.columns:
                    val = grp[col].mean(skipna=True)  # NaN if all-NaN
                    rec[col] = float(val) if pd.notna(val) else float("nan")
                else:
                    rec[col] = float("nan")
        records.append(rec)

    df = pd.DataFrame(records, columns=out_cols)
    return df.sort_values("FVYear").reset_index(drop=True)


def aggregate_value_for_year(
    panel_slice: pd.DataFrame,
    metric_columns: list[str],
    year: int,
) -> dict[str, float]:
    """Convenience: aggregate one group and return the metric dict for one year.

    Returns ``{column: value}`` for each requested metric in ``year`` (plus
    ``"n"``), or an empty dict when the group has no data for that year.
    """
    agg = aggregate_group_by_year(panel_slice, metric_columns)
    if agg.empty:
        return {}
    row = agg[agg["FVYear"] == int(year)]
    if row.empty:
        return {}
    r = row.iloc[0]
    out: dict[str, float] = {"n": float(r["n"])}
    for col in metric_columns:
        out[col] = float(r[col]) if pd.notna(r[col]) else float("nan")
    return out


# ---------------------------------------------------------------------------
# Formatting / labelling helpers (keyed on metrics_panel column names).
#
# Column-kind classification is delegated to ``lib.metric_picker`` (the single
# source of truth shared with the Screener and Sector views) so a column is
# treated as money / percent / ratio identically everywhere. The only addition
# here is the suffix rule for growth columns (``*_YoY`` / ``*CAGR``) that the
# sector-compare picker offers beyond the picker's curated set — those store
# decimals and render as percentages. Percent columns store decimals
# (0.20 == 20%).
# ---------------------------------------------------------------------------

# Human labels for the curated columns. Growth columns get labelled by rule.
_COLUMN_LABELS: dict[str, str] = {
    "Revenue": "Revenue",
    "GrossProfit": "Gross Profit",
    "NetProfit": "Net Profit",
    "EBITDA": "EBITDA",
    "EBIT": "EBIT",
    "TotalAssets": "Total Assets",
    "TotalCash": "Total Cash",
    "TotalDebt": "Total Debt",
    "NetDebt": "Net Debt",
    "TotalEquity": "Total Equity",
    "GrossMargin": "Gross Margin",
    "EBITDAMargin": "EBITDA Margin",
    "NetMargin": "Net Margin",
    "ROE": "ROE",
    "ROA": "ROA",
    "ROIC": "ROIC",
    "NetDebtToEBITDA": "Net Debt / EBITDA",
    "AssetTurnover": "Asset Turnover",
}

_GROWTH_BASE_LABELS: dict[str, str] = {
    "Revenue": "Revenue",
    "EBITDA": "EBITDA",
    "NetProfit": "Net Profit",
    "GrossProfit": "Gross Profit",
    "TotalAssets": "Total Assets",
}


def is_percent_column(column: str) -> bool:
    """True for decimal-percent columns (margins, returns, growth/CAGR).

    Margins/returns come from the shared metric-picker classification; the
    suffix rule extends it to every growth column this view offers (the picker
    only lists a curated subset of ``*_YoY`` / ``*CAGR`` columns).
    """
    return _picker_is_percent(column) or column.endswith("_YoY") or "CAGR" in column


def is_ratio_column(column: str) -> bool:
    """True for pure-ratio columns rendered as "x" multiples.

    Delegates to the shared metric-picker classification.
    """
    return _picker_is_ratio(column)


def is_money_column(column: str) -> bool:
    """True for GEL-thousands money/size columns.

    A column is money iff it is neither a percent nor a ratio column — the same
    rule the shared metric picker uses.
    """
    return not is_percent_column(column) and not is_ratio_column(column)


def label_for(column: str) -> str:
    """Human-readable label for a ``metrics_panel`` column."""
    if column in _COLUMN_LABELS:
        return _COLUMN_LABELS[column]
    # Growth / CAGR columns: "<Base>_YoY" or "<Base>_NyrCAGR".
    if column.endswith("_YoY"):
        base = column[: -len("_YoY")]
        return f"{_GROWTH_BASE_LABELS.get(base, base)} YoY"
    if "yrCAGR" in column:
        base, _, tail = column.partition("_")
        n = tail.replace("yrCAGR", "")
        return f"{_GROWTH_BASE_LABELS.get(base, base)} {n}yr CAGR"
    return column


def format_metric_value(column: str, value, decimals: int = 0) -> str:
    """Format an aggregated value for display, keyed on the column's kind.

    * money → GEL thousands with comma grouping, parens for negatives, blank
      for 0 / NaN (mirrors ``lib.format.fmt_k_gel``);
    * percent → ``value * 100`` with a ``%`` sign (1 decimal min for readability);
    * ratio → ``"<n>x"``.

    ``decimals`` controls money decimal places (matches the dashboard's global
    precision selector). Percent/ratio use a sensible fixed precision.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)

    if is_percent_column(column):
        if f == 0:
            return ""
        return f"{f * 100:,.1f}%"
    if is_ratio_column(column):
        return f"{f:,.1f}x"
    # Money → thousands.
    t = f / 1000.0
    if t == 0:
        return ""
    if t < 0:
        return f"({abs(t):,.{decimals}f})"
    return f"{t:,.{decimals}f}"
