"""
utils/anomaly_grid.py — live spatial anomaly small-multiples for ONE water year.

Renders a 1×4 panel (Soil moisture · SWE · Precipitation · Runoff) as a PNG
data-URI, each cell coloured by its value as a % of that cell's own 1984–2024
mean (red = below the long-term mean / dry, blue = above / wet), with sub-basin
outlines. This is the interactive, year-selectable version of the static
spatial-anomaly grid — the user picks any water year with a slider.

Per-cell baselines (the 1984–2024 mean grid for each variable) are loaded and
cached once on first use, so switching years afterwards is fast.
"""
import io
import base64
import json
from pathlib import Path

import numpy as np
import pandas as pd

from utils.data_loader import load_spatial

ASSETS = Path(__file__).parent.parent / "assets"
NAVY = "#0D2137"

# (variable, column title, vmin%, vmax%)
PANELS = [
    ("OUT_SOIL_MOIST", "Soil moisture",      50, 150),
    ("OUT_SWE",        "Snow water equiv.",   0, 200),
    ("OUT_PREC",       "Precipitation",       0, 200),
    ("OUT_RUNOFF",     "Runoff",             50, 150),
]

# cached at first use: {var: (lons, lats, baseline_grid, {year: value_grid})}
_CACHE = {}
_BASINS_GJ = None
_YEARS = None


def _basins():
    global _BASINS_GJ
    if _BASINS_GJ is None:
        p = ASSETS / "crb_basins.geojson"
        _BASINS_GJ = json.load(open(p)) if p.exists() else {"features": []}
    return _BASINS_GJ


def _ring_xy(geom):
    t, c = geom.get("type"), geom.get("coordinates")
    if t == "LineString":
        yield [p[0] for p in c], [p[1] for p in c]
    elif t in ("MultiLineString", "Polygon"):
        for r in c:
            yield [p[0] for p in r], [p[1] for p in r]
    elif t == "MultiPolygon":
        for poly in c:
            for r in poly:
                yield [p[0] for p in r], [p[1] for p in r]


def _prep(var):
    """Load a variable's spatial cache, pivot per year, and cache the baseline."""
    if var in _CACHE:
        return _CACHE[var]
    df = load_spatial(var)
    if df is None or df.empty:
        _CACHE[var] = None
        return None
    piv = df.pivot_table(index="lat", columns="lon", values="value", aggfunc="mean")
    lons = piv.columns.values.astype(float)
    lats = piv.index.values.astype(float)
    # per-year grids
    by_year = {}
    for yr, g in df.groupby("water_year"):
        gp = g.pivot_table(index="lat", columns="lon", values="value", aggfunc="mean")
        gp = gp.reindex(index=piv.index, columns=piv.columns)
        by_year[int(yr)] = gp.values.astype(float)
    # Per-cell 1984–2024 mean, computed without nanmean so all-NaN cells (outside the
    # basin) never raise a "Mean of empty slice" warning.
    stack = np.dstack(list(by_year.values()))
    with np.errstate(invalid="ignore", divide="ignore"):
        count = np.sum(~np.isnan(stack), axis=2)
        total = np.nansum(stack, axis=2)
        baseline = np.where(count > 0, total / np.maximum(count, 1), np.nan)
    _CACHE[var] = (lons, lats, baseline, by_year)
    return _CACHE[var]


def available_years():
    global _YEARS
    if _YEARS is None:
        d = _prep("OUT_RUNOFF")
        _YEARS = sorted(d[3].keys()) if d else []
    return _YEARS


def render_anomaly_grid(year):
    """1×4 anomaly panel for `year` as a base64 PNG data-URI (None if no data/mpl)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    fig, axes = plt.subplots(1, 4, figsize=(14.4, 5.0), dpi=120)
    any_data = False
    for ax, (var, title, vmin, vmax) in zip(axes, PANELS):
        ax.set_facecolor("white")
        ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)
        d = _prep(var)
        if d is None or int(year) not in d[3]:
            ax.text(0.5, 0.5, "no data", ha="center", va="center",
                    transform=ax.transAxes, color="#90a4ae", fontsize=9)
            ax.set_title(f"{title}", fontsize=10, weight="bold", color=NAVY)
            continue
        lons, lats, baseline, by_year = d
        with np.errstate(divide="ignore", invalid="ignore"):
            pct = by_year[int(year)] / baseline * 100.0
        Z = np.ma.masked_invalid(pct)
        mesh = ax.pcolormesh(lons, lats, Z, cmap="RdBu", vmin=vmin, vmax=vmax,
                             shading="nearest", zorder=1)
        for f in _basins()["features"]:
            if f["properties"].get("basin_id") == "CRB":
                continue
            for xs, ys in _ring_xy(f["geometry"]):
                ax.plot(xs, ys, color="#37474f", lw=0.7, zorder=3)
        ax.set_xlim(-117.2, -102.8); ax.set_ylim(29.4, 45.2)
        ax.set_aspect(1.0 / np.cos(np.deg2rad(37.5)))
        ax.set_title(f"{title}", fontsize=10, weight="bold", color=NAVY)
        cb = fig.colorbar(mesh, ax=ax, fraction=0.046, pad=0.02,
                          orientation="horizontal")
        cb.ax.tick_params(labelsize=7)
        cb.set_label("% of mean", fontsize=8)
        any_data = True

    fig.suptitle(f"Spatial anomalies — Water Year {year}  (% of the 1984–2024 mean, "
                 "red = dry, blue = wet)", fontsize=11.5, weight="bold", color=NAVY, y=1.02)
    fig.tight_layout()
    if not any_data:
        plt.close(fig)
        return None
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return "data:image/png;base64," + base64.b64encode(buf.read()).decode("ascii")


_CRB_SERIES = {}


def _crb_series():
    """CRB basin-average value as % of its 1984–2024 mean, per panel variable (cached)."""
    global _CRB_SERIES
    if not _CRB_SERIES:
        try:
            from utils.data_loader import load_vic_annual
            a = load_vic_annual()
            crb = a[a["basin"] == "CRB"].set_index("water_year").sort_index()
            for var, _, _, _ in PANELS:
                if var in crb.columns:
                    s = crb[var]
                    base = s.loc[1984:2024].mean()
                    _CRB_SERIES[var] = (s.index.values.astype(int), (s / base * 100).values)
        except Exception:
            pass
    return _CRB_SERIES


def render_mapchart_grid(year):
    """Top row = the 4 spatial anomaly maps (soil moisture, SWE, precip, runoff); bottom row =
    the 4 matching basin-average trend charts, each with a dot marking `year`. For the chosen
    water year, so a scientist can freeze on any year. Returns a base64 PNG data-URI."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    year = int(year)
    ser = _crb_series()
    yrs = available_years()
    fig, axes = plt.subplots(2, 4, figsize=(14.0, 7.4), dpi=92,
                             gridspec_kw={"height_ratios": [1.25, 1]})
    for c, (var, title, vmin, vmax) in enumerate(PANELS):
        axm, axg = axes[0, c], axes[1, c]
        # ── top: map ──
        axm.set_xticks([]); axm.set_yticks([])
        for sp in axm.spines.values():
            sp.set_visible(False)
        d = _prep(var)
        if d is not None and year in d[3]:
            lons, lats, base, by = d
            with np.errstate(divide="ignore", invalid="ignore"):
                pct = by[year] / base * 100.0
            axm.pcolormesh(lons, lats, np.ma.masked_invalid(pct), cmap="RdBu",
                           vmin=vmin, vmax=vmax, shading="nearest")
            for f in _basins()["features"]:
                if f["properties"].get("basin_id") == "CRB":
                    continue
                for xs, ys in _ring_xy(f["geometry"]):
                    axm.plot(xs, ys, color="#37474f", lw=0.6)
            axm.set_xlim(-117.2, -102.8); axm.set_ylim(29.4, 45.2)
            axm.set_aspect(1.0 / np.cos(np.deg2rad(37.5)))
        axm.set_title(f"{title}", fontsize=11, weight="bold", color=NAVY)
        # ── bottom: chart (full line + dot on current year) ──
        if var in ser:
            xs, ys = ser[var]
            axg.axhline(100, ls="--", color="#b0bec5", lw=1)
            axg.plot(xs, ys, color="#c9a3b0", lw=1.4, zorder=2)
            m = xs <= year
            axg.plot(xs[m], ys[m], color="#8C1D40", lw=2.2, zorder=3)
            if year in xs:
                axg.scatter([year], [ys[list(xs).index(year)]], s=70, color="#8C1D40",
                            zorder=5, edgecolors="white", linewidths=1.3)
            axg.set_xlim(yrs[0] - 0.5, yrs[-1] + 0.5)
            axg.set_ylim(float(np.nanmin(ys)) * 0.9, float(np.nanmax(ys)) * 1.1)
            axg.tick_params(labelsize=7.5)
            if c == 0:
                axg.set_ylabel("% of 1984–2024 mean", fontsize=9)
        for sp in axg.spines.values():
            sp.set_edgecolor("#cfd8dc")
        axg.set_title("basin-average trend", fontsize=9.5, color="#546e7a")
    fig.suptitle(f"Water Year {year}   ·   % of 1984–2024 mean (red = dry, blue = wet)",
                 fontsize=13, weight="bold", color=NAVY, y=0.99)
    fig.tight_layout(rect=[0, 0, 0.88, 0.965])
    add_anomaly_legend(fig)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return "data:image/png;base64," + base64.b64encode(buf.read()).decode("ascii")


def add_anomaly_legend(fig):
    """A shared RdBu legend on the right: blue = wetter (above mean), red = drier (below mean).
    Qualitative because each variable's % range differs (SM/Q 50–150, SWE/P 0–200)."""
    import numpy as _np
    cax = fig.add_axes([0.895, 0.33, 0.013, 0.40])
    cax.imshow(_np.linspace(0, 1, 256).reshape(-1, 1), aspect="auto", cmap="RdBu",
               origin="lower", extent=[0, 1, 0, 1])
    cax.set_xticks([]); cax.set_yticks([])
    for sp in cax.spines.values():
        sp.set_edgecolor("#cfd8dc")
    fig.text(0.912, 0.715, "wetter\n(above mean)", fontsize=8.5, color="#01579B",
             weight="bold", va="center")
    fig.text(0.912, 0.53, "≈ mean\n(100 %)", fontsize=8.5, color="#546e7a", va="center")
    fig.text(0.912, 0.345, "drier\n(below mean)", fontsize=8.5, color="#8C1D40",
             weight="bold", va="center")
