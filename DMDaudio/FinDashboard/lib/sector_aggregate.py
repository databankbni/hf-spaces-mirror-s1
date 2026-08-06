"""Pure aggregation core for the redesigned Sector View (2026-07-20 spec §2/§4).

Given a de-duplicated ``metrics_panel``-shaped slice for a pool of companies
(one row per ``(IdCode, FVYear)``), this module produces a single aggregate row
per year applying the correct rule per metric kind:

* **money / size** (Revenue, GrossProfit, EBITDA, EBIT, NetProfit, TotalAssets,
  TotalEquity, TotalCash, TotalDebt, NetDebt) → **Σ** across member companies,
  skipping NULLs (bank/insurer EBITDA/EBIT/GrossProfit are NULL in the panel).
  ``NetDebt`` is summed directly when the column is present, else derived as
  ``Σ TotalDebt − Σ TotalCash``.
* **weighted ratios** (margins, ROE/ROA/ROIC, Net Debt / EBITDA, Asset
  Turnover) → recomputed from the *summed* money bases, NOT averaged. The return
  ratios delegate to :mod:`lib.finratios` (the ratio SSOT) so ROE/ROA/ROIC and
  their None-guards agree with the Screener and Single-Company Ratios tabs;
  margins / turnover / leverage use a local :func:`safe_div`.
* **growth** (``*_YoY`` / ``*_NyrCAGR``) → computed on the *aggregate* summed
  series, NOT read from the panel's per-company growth columns. Those are
  per-year and correct as of 2026-07-30, but they are per-*company* growth: a
  sector's growth is the growth of the summed series, not any average of member
  growth rates. YoY / CAGR conventions mirror ``lib.screener`` exactly (YoY
  denominator = ``abs(prior)``; CAGR only defined when both endpoints > 0).

**De-dup contract:** ``aggregate_by_year`` assumes ``deduped_df`` has ALREADY
had consolidation shadows removed by the caller
(``lib.consolidation.dedup_panel_df``); it does not de-dup itself. Summing
before de-dup would double-count a consolidating parent's subsidiaries.

Pure module — no Streamlit / DB dependencies; pandas is imported lazily inside
:func:`aggregate_by_year`. :mod:`lib.finratios` is stdlib-only, so it is safe to
import at module load. Unit-testable in isolation like :mod:`lib.sectors`.
"""
from __future__ import annotations

import math

from lib import finratios

# ---------------------------------------------------------------------------
# Column vocabulary (metrics_panel column names).
# ---------------------------------------------------------------------------

# Money / size columns recognised as summable. NetDebt is summable directly when
# the panel carries the column, else derived from Σ TotalDebt − Σ TotalCash.
MONEY_COLUMNS: tuple[str, ...] = (
    "Revenue",
    "GrossProfit",
    "EBITDA",
    "EBIT",
    "NetProfit",
    "TotalAssets",
    "TotalEquity",
    "TotalCash",
    "TotalDebt",
    "NetDebt",
)

# Ratio column -> the money base columns it is derived from (spec §2). The
# aggregate ratio is computed from the SUMMED bases, never averaged.
#   * margins:      Σ numerator / Σ Revenue
#   * ROE/ROA/ROIC: finratios.<fn>(Σ bases…) with their canonical guards
#   * NetDebtToEBITDA: Σ NetDebt / Σ EBITDA (None when Σ EBITDA ≤ 0)
#   * AssetTurnover:   Σ Revenue / Σ TotalAssets
RATIO_BASES: dict[str, tuple[str, ...]] = {
    "GrossMargin": ("GrossProfit", "Revenue"),
    "EBITDAMargin": ("EBITDA", "Revenue"),
    "NetMargin": ("NetProfit", "Revenue"),
    "ROE": ("NetProfit", "TotalEquity"),
    "ROA": ("NetProfit", "TotalAssets"),
    "ROIC": ("EBIT", "TotalEquity", "NetDebt"),
    "NetDebtToEBITDA": ("NetDebt", "EBITDA"),
    "AssetTurnover": ("Revenue", "TotalAssets"),
}


def safe_div(num: float | None, den: float | None) -> float | None:
    """Plain guarded division: ``None`` when the denominator is falsy/zero.

    Local mirror of :func:`lib.finratios.safe_div`, used for the margins /
    turnover / leverage ratios (ROE/ROA/ROIC delegate straight to finratios).
    """
    if not den:
        return None
    return num / den


def _parse_growth(col: str) -> tuple[str, int] | None:
    """Return ``(base_column, n)`` for a growth column, else ``None``.

    ``"Revenue_YoY"`` -> ``("Revenue", 1)``;
    ``"EBITDA_3yrCAGR"`` -> ``("EBITDA", 3)``. Mirrors ``lib.screener``'s
    ``_growth_column`` naming (base tokens have no underscores).
    """
    if col.endswith("_YoY"):
        return col[: -len("_YoY")], 1
    if "yrCAGR" in col:
        base, _sep, tail = col.partition("_")
        try:
            n = int(tail.replace("yrCAGR", ""))
        except ValueError:
            return None
        if n < 1 or not base:
            return None
        return base, n
    return None


def bases_needed(metric_cols) -> set[str]:
    """Money-base columns a picker selection needs summed.

    Union of, over ``metric_cols``:
      * the ratio bases (:data:`RATIO_BASES`) for each picked ratio,
      * each picked money column itself,
      * the growth base (Revenue / EBITDA / NetProfit / …) for each picked
        ``*_YoY`` / ``*_CAGR`` column.

    The view uses this to know which panel columns to pull (via
    ``panel_columns_for_idcodes``) so every requested ratio's bases are present
    before aggregating. ``NetDebt`` is returned as its own base (a real panel
    column); its Σ TotalDebt − Σ TotalCash fallback is handled inside
    :func:`aggregate_by_year`, not expanded here.
    """
    needed: set[str] = set()
    for col in metric_cols:
        if col in RATIO_BASES:
            needed.update(RATIO_BASES[col])
        elif col in MONEY_COLUMNS:
            needed.add(col)
        else:
            parsed = _parse_growth(col)
            if parsed is not None:
                needed.add(parsed[0])
    return needed


def _finite(x) -> bool:
    """True when ``x`` is a finite real number (not None / NaN / inf)."""
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _series_growth(summed_by_year: dict[int, float], n: int) -> dict[int, float]:
    """Year -> growth of the aggregate summed series, matching screener rules.

    For each year ``y`` present, compares ``Σ[y]`` against ``Σ[y-n]`` (the value
    ``n`` calendar years earlier):

    * **n == 1 (YoY):** ``(Σ[y] − Σ[y-1]) / abs(Σ[y-1])``. Skipped when the prior
      year is missing or its sum is 0. ``abs(prior)`` keeps a negative→positive
      swing from flipping the sign (mirrors ``lib.screener``).
    * **n > 1 (CAGR):** ``(Σ[y] / Σ[y-n]) ** (1/n) − 1``, only when BOTH
      endpoints are > 0 (CAGR is undefined for non-positive endpoints).

    Years with no valid look-back simply don't appear in the returned dict.
    Non-finite sums are treated as missing.
    """
    out: dict[int, float] = {}
    for y, cur in summed_by_year.items():
        prev = summed_by_year.get(y - n)
        if prev is None or not _finite(prev) or not _finite(cur):
            continue
        if prev == 0:
            continue
        if n == 1:
            out[y] = (cur - prev) / abs(prev)
        else:
            if prev <= 0 or cur <= 0:
                continue
            out[y] = (cur / prev) ** (1.0 / n) - 1.0
    return out


def _ratio_value(col: str, sums: dict[str, float]) -> float:
    """Weighted ratio from summed money bases; ``nan`` when guarded to None."""
    nan = float("nan")

    def g(key: str) -> float:
        return sums.get(key, 0.0)

    if col == "ROE":
        r = finratios.roe(g("NetProfit"), g("TotalEquity"))
    elif col == "ROA":
        r = finratios.roa(g("NetProfit"), g("TotalAssets"))
    elif col == "ROIC":
        r = finratios.roic(g("EBIT"), g("TotalEquity"), g("NetDebt"))
    elif col == "NetDebtToEBITDA":
        ebitda = g("EBITDA")
        r = (g("NetDebt") / ebitda) if ebitda > 0 else None
    elif col == "GrossMargin":
        r = safe_div(g("GrossProfit"), g("Revenue"))
    elif col == "EBITDAMargin":
        r = safe_div(g("EBITDA"), g("Revenue"))
    elif col == "NetMargin":
        r = safe_div(g("NetProfit"), g("Revenue"))
    elif col == "AssetTurnover":
        r = safe_div(g("Revenue"), g("TotalAssets"))
    else:
        r = None
    return r if r is not None else nan


def aggregate_by_year(deduped_df, metric_cols):
    """Aggregate a de-duped panel slice into one row per ``FVYear``.

    ``deduped_df`` must have ``IdCode`` + ``FVYear`` columns plus the money bases
    that back the requested metrics (pull them via :func:`bases_needed`). It is
    assumed to be **already de-duped** by the caller
    (``lib.consolidation.dedup_panel_df``) — summing before de-dup double-counts
    consolidating parents. Extra columns are ignored.

    For each year it emits, in order, ``FVYear``, ``n`` (distinct member
    companies contributing that year), then one column per entry in
    ``metric_cols`` applying the §2 rule:

    * money → Σ (NULLs skipped; NetDebt derived from Σ TotalDebt − Σ TotalCash
      when the column is absent),
    * ratio → weighted value from summed bases (``nan`` when guarded to None),
    * growth → :func:`_series_growth` value for that year (``nan`` when undefined).

    Returns a pandas DataFrame sorted ascending by ``FVYear`` with columns
    ``["FVYear", "n", *metric_cols]``. Empty / None input → an empty frame with
    that column shape.
    """
    import pandas as pd

    out_cols = ["FVYear", "n", *metric_cols]
    if deduped_df is None or getattr(deduped_df, "empty", True):
        return pd.DataFrame(columns=out_cols)

    columns = set(deduped_df.columns)
    # Which money bases must be summed for the requested metrics.
    sum_targets = bases_needed(metric_cols)
    # NetDebt fallback: if a metric needs NetDebt but the column is absent,
    # derive it from Σ TotalDebt − Σ TotalCash instead.
    need_netdebt_fallback = "NetDebt" in sum_targets and "NetDebt" not in columns
    if need_netdebt_fallback:
        sum_targets = set(sum_targets) | {"TotalDebt", "TotalCash"}

    # Per-year money sums (skipping NULLs via pandas' default skipna).
    year_rows: list[tuple[int, int, dict[str, float]]] = []
    for year, grp in deduped_df.groupby("FVYear"):
        sums: dict[str, float] = {}
        for base in sum_targets:
            if base == "NetDebt" and need_netdebt_fallback:
                continue  # derived below, not summed directly
            sums[base] = float(grp[base].sum()) if base in grp.columns else 0.0
        if need_netdebt_fallback:
            sums["NetDebt"] = sums.get("TotalDebt", 0.0) - sums.get("TotalCash", 0.0)
        year_rows.append((int(year), int(grp["IdCode"].nunique()), sums))

    year_rows.sort(key=lambda r: r[0])

    # Growth series per (base, n) — computed once over the full aggregate series.
    growth_cache: dict[tuple[str, int], dict[int, float]] = {}
    for col in metric_cols:
        parsed = _parse_growth(col)
        if parsed is None:
            continue
        base, n = parsed
        key = (base, n)
        if key not in growth_cache:
            series = {yr: sums.get(base, 0.0) for yr, _n, sums in year_rows}
            growth_cache[key] = _series_growth(series, n)

    nan = float("nan")
    records: list[dict] = []
    for year, ncos, sums in year_rows:
        rec: dict = {"FVYear": year, "n": ncos}
        for col in metric_cols:
            if col in MONEY_COLUMNS:
                rec[col] = sums.get(col, 0.0)
            elif col in RATIO_BASES:
                rec[col] = _ratio_value(col, sums)
            else:
                parsed = _parse_growth(col)
                if parsed is None:
                    rec[col] = nan
                else:
                    base, n = parsed
                    val = growth_cache.get((base, n), {}).get(year)
                    rec[col] = val if val is not None else nan
        records.append(rec)

    return pd.DataFrame(records, columns=out_cols)
