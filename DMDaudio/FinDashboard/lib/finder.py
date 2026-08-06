"""Pure filtering/sorting logic for the Home company finder (T0.5).

CapIQ-style browse over the whole universe: free-text query, sector /
sub-sector rail, latest-revenue size buckets, and a sort order — all applied
to the DataFrame ``lib.cache.finder_universe`` loads (one row per company:
``company_search`` joined to that company's latest ``metrics_panel`` year).

Pure module — no Streamlit / DB dependencies (pandas passed in), so the
filter semantics are unit-testable and portable (the new.gfin.ge front-end
can reimplement from this file + tests as the spec).
"""
from __future__ import annotations

UNCLASSIFIED = "(unclassified)"

#: Ordered size buckets on latest Revenue, in ABSOLUTE GEL (panel convention).
#: ``None`` bounds are open. Companies with NULL revenue only match "Any".
SIZE_BUCKETS: list[tuple[str, float | None, float | None]] = [
    ("Any size", None, None),
    ("Micro — under ₾1m", None, 1_000_000.0),
    ("Small — ₾1–10m", 1_000_000.0, 10_000_000.0),
    ("Mid — ₾10–50m", 10_000_000.0, 50_000_000.0),
    ("Large — ₾50–250m", 50_000_000.0, 250_000_000.0),
    ("Major — over ₾250m", 250_000_000.0, None),
]

#: Sort label -> (column, ascending). Money sorts put NULLs last.
SORT_OPTIONS: dict[str, tuple[str, bool]] = {
    "Revenue (largest first)": ("Revenue", False),
    "Total assets (largest first)": ("TotalAssets", False),
    "Net profit (largest first)": ("NetProfit", False),
    "Name (A→Z)": ("CompanyName", True),
}


def sector_of(value) -> str:
    """Canonical sector bucket for filtering: NULL/NaN/blank → ``(unclassified)``.

    The universe frame comes through pandas, so a missing sector arrives as
    float ``nan`` — which stringifies to ``"nan"``, not empty. Guard it.
    """
    if value is None or value != value:  # None or NaN
        return UNCLASSIFIED
    s = str(value).strip()
    return s if s else UNCLASSIFIED


def filter_universe(
    df,
    query: str = "",
    sectors: list[str] | tuple = (),
    subsectors: list[str] | tuple = (),
    size_bucket: str = "Any size",
    latest_year_min: int | None = None,
):
    """Apply the finder's filters to the universe frame; returns a copy.

    * ``query`` — case-insensitive substring over CompanyName OR IdCode prefix.
    * ``sectors`` / ``subsectors`` — empty means no filter; ``(unclassified)``
      matches NULL/blank values.
    * ``size_bucket`` — a :data:`SIZE_BUCKETS` label; bounds are
      lo ≤ Revenue < hi on the latest filed year.
    * ``latest_year_min`` — keep only companies whose latest filed year is at
      least this (the "current filers only" switch).
    """
    out = df
    q = (query or "").strip().lower()
    if q:
        name_hit = out["CompanyName"].astype(str).str.lower().str.contains(
            q, regex=False, na=False)
        id_hit = out["IdCode"].astype(str).str.startswith(q)
        out = out[name_hit | id_hit]
    if sectors:
        wanted = set(sectors)
        out = out[out["Sector"].map(sector_of).isin(wanted)]
    if subsectors:
        wanted = set(subsectors)
        out = out[out["SubSector"].map(sector_of).isin(wanted)]
    lo, hi = next(
        ((lo, hi) for label, lo, hi in SIZE_BUCKETS if label == size_bucket),
        (None, None),
    )
    if lo is not None:
        out = out[out["Revenue"] >= lo]
    if hi is not None:
        out = out[out["Revenue"] < hi]
    if latest_year_min is not None:
        out = out[out["LatestFVYear"] >= latest_year_min]
    return out.copy()


def sort_universe(df, sort_by: str):
    """Sort by a :data:`SORT_OPTIONS` label; unknown labels fall back to Revenue."""
    col, asc = SORT_OPTIONS.get(sort_by, SORT_OPTIONS["Revenue (largest first)"])
    return df.sort_values(col, ascending=asc, na_position="last")


def subsector_options(df, sectors: list[str] | tuple) -> list[str]:
    """Sub-sector choices for the current sector selection, by frequency.

    Empty ``sectors`` pools the whole universe. ``(unclassified)`` appears only
    when blank sub-sectors exist in the pool.
    """
    pool = df
    if sectors:
        wanted = set(sectors)
        pool = pool[pool["Sector"].map(sector_of).isin(wanted)]
    counts = pool["SubSector"].map(sector_of).value_counts()
    return sorted(counts.index.tolist(), key=lambda s: (-int(counts[s]), s))
