"""
utils/data_loader.py
====================
Centralised data loading with caching.
All modules import from here — never read parquet directly in module files.
"""

import pandas as pd
import functools
from pathlib import Path

CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"


@functools.lru_cache(maxsize=None)
def load_vic_annual() -> pd.DataFrame:
    """Annual basin means — VIC historical (all basins, all variables)."""
    return pd.read_parquet(CACHE_DIR / "vic_annual_basin.parquet")


@functools.lru_cache(maxsize=None)
def load_vic_monthly() -> pd.DataFrame:
    """Monthly climatology — VIC historical."""
    return pd.read_parquet(CACHE_DIR / "vic_monthly_basin.parquet")


@functools.lru_cache(maxsize=None)
def load_vic_future() -> pd.DataFrame:
    """Annual basin means — VIC future to 2100."""
    f = CACHE_DIR / "vic_future_basin.parquet"
    if f.exists():
        return pd.read_parquet(f)
    return pd.DataFrame()


@functools.lru_cache(maxsize=None)
def load_snotel_annual() -> pd.DataFrame:
    return pd.read_parquet(CACHE_DIR / "snotel_annual.parquet")


@functools.lru_cache(maxsize=None)
def load_snotel_monthly() -> pd.DataFrame:
    return pd.read_parquet(CACHE_DIR / "snotel_monthly.parquet")


@functools.lru_cache(maxsize=None)
def load_grace() -> pd.DataFrame:
    df = pd.read_parquet(CACHE_DIR / "grace_basin.parquet").copy()
    # tws_mm = lwe_cm × 10  (convert cm → mm for all module compatibility)
    if "lwe_cm" in df.columns and "tws_mm" not in df.columns:
        df["tws_mm"] = df["lwe_cm"] * 10.0
    # carry the measurement uncertainty (cm → mm) for error bars
    if "uncertainty_cm" in df.columns and "tws_unc_mm" not in df.columns:
        df["tws_unc_mm"] = df["uncertainty_cm"] * 10.0
    return df


@functools.lru_cache(maxsize=None)
def load_smap() -> pd.DataFrame:
    """SMAP soil moisture — returns WIDE format with sm_surface/sm_rootzone/sm_profile columns."""
    df = pd.read_parquet(CACHE_DIR / "smap_basin.parquet")
    # If already wide, return as-is
    if "sm_surface" in df.columns:
        return df
    # Pivot from long (basin, date, variable, value) → wide per basin×date
    if "variable" in df.columns and "value" in df.columns:
        df = df.pivot_table(index=["basin","date","year","month"],
                            columns="variable", values="value").reset_index()
        df.columns.name = None
    return df


@functools.lru_cache(maxsize=None)
def load_snotel_stations() -> pd.DataFrame:
    """Per-station SNOTEL data with MK trend slopes and lat/lon."""
    f = CACHE_DIR / "snotel_stations.parquet"
    if f.exists():
        return pd.read_parquet(f)
    return pd.DataFrame()


@functools.lru_cache(maxsize=None)
def load_snotel_annual_station() -> pd.DataFrame:
    """Station × water_year × peak_swe_mm (with metadata + MK slope)."""
    f = CACHE_DIR / "snotel_annual_station.parquet"
    if f.exists():
        return pd.read_parquet(f)
    return pd.DataFrame()


def load_spatial(varname: str) -> pd.DataFrame:
    """Annual gridded values for one VIC variable. Not LRU-cached (too large)."""
    f = CACHE_DIR / "spatial" / f"spatial_{varname}.parquet"
    if f.exists():
        return pd.read_parquet(f)
    return pd.DataFrame()


# ── Quick stats helpers ───────────────────────────────────────
def basin_label(basin_id: str) -> str:
    labels = {
        "CRB":         "Colorado River Basin",
        "UpperBasin":  "Upper Basin",
        "LowerBasin":  "Lower Basin",
        "Green":       "Green River",
        "SanJuan":     "San Juan",
        "GrandCanyon": "Grand Canyon",
        "Gila":        "Gila River",
    }
    return labels.get(basin_id, basin_id)


def trend_slope(series: pd.Series, years: pd.Series) -> dict:
    """Mann-Kendall trend test + Sen's slope (non-parametric, standard for hydrology).
    Falls back to OLS if pymannkendall unavailable."""
    mask = series.notna() & years.notna()
    if mask.sum() < 5:
        return {"slope": None, "pvalue": None}
    try:
        import pymannkendall as mk
        result = mk.original_test(series[mask].values)
        # Sen's slope (per year)
        return {
            "slope": float(result.slope),
            "pvalue": float(result.p),
            "tau": float(result.Tau),
            "trend": result.trend,   # 'increasing', 'decreasing', 'no trend'
        }
    except ImportError:
        from scipy import stats
        slope, _, r, p, _ = stats.linregress(years[mask], series[mask])
        return {"slope": float(slope), "pvalue": float(p), "r2": float(r**2)}


def trend_ci(series: pd.Series, years: pd.Series) -> dict:
    """Linear trend with a 95% confidence interval on the slope (OLS), plus a
    Mann-Kendall significance test. Returns per-year slope and CI bounds so a
    view can show the estimate together with its uncertainty consistently."""
    mask = series.notna() & years.notna()
    if int(mask.sum()) < 5:
        return {"slope": None, "lo": None, "hi": None, "pvalue": None, "sig": False, "n": int(mask.sum())}
    from scipy import stats
    x = years[mask].astype(float).values
    y = series[mask].astype(float).values
    res = stats.linregress(x, y)
    n = int(mask.sum())
    half = float(stats.t.ppf(0.975, n - 2) * res.stderr)
    p = float(res.pvalue)
    try:
        import pymannkendall as mk
        p = float(mk.original_test(y).p)
    except Exception:
        pass
    return {"slope": float(res.slope), "lo": float(res.slope - half),
            "hi": float(res.slope + half), "pvalue": p, "sig": bool(p < 0.05), "n": n}
