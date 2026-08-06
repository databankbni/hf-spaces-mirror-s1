"""
utils/basin_map.py — static cartographic map IMAGE of the CRB.

Renders, as a PNG (base64 data-URI), a publication-style map:
  · gridded VIC ("satellite") data raster inside the basin
  · sub-basin boundaries with bold black labels (name · value · rank)
  · the Colorado River + tributaries
  · approximate US state boundaries (Four-Corners meridians/parallels) + state names
  · north-arrow compass + colour-bar legend  ·  ASU-maroon accents

No map tiles or web access required — pure matplotlib, so it renders identically
in any browser and offline.
"""
import io
import base64
import json
from pathlib import Path

import numpy as np
import pandas as pd

# matplotlib is imported lazily inside render_basin_map() so that a missing
# matplotlib never crashes the whole app at import time (the map simply
# falls back to a blank image until matplotlib is installed).

ASSETS = Path(__file__).parent.parent / "assets"
MAROON = "#8C1D40"
NAVY = "#0D2137"

BASIN_LABELS = {
    "Green": "Green River", "SanJuan": "San Juan", "UpperColo": "Upper Colorado",
    "GlenCanyon": "Glen Canyon", "Gila": "Gila River", "GrandCanyon": "Grand Canyon",
    "LittleColo": "Little Colorado", "LowerColo": "Lower Colorado",
}
LEAF = list(BASIN_LABELS.keys())

# Four-Corners state borders are straight meridians / parallels → accurate as lines
STATE_LINES = [
    # (lon0, lat0, lon1, lat1)
    (-109.045, 31.3, -109.045, 41.0),   # UT|CO  &  AZ|NM
    (-114.05, 37.0, -114.05, 42.0),     # NV|UT (and NV|AZ upper)
    (-114.05, 37.0, -103.0, 37.0),      # UT|AZ  &  CO|NM  (37°N)
    (-114.05, 41.0, -102.0, 41.0),      # UT,CO | WY  (41°N)
    (-111.05, 41.0, -111.05, 42.1),     # UT|WY short
]
STATE_NAMES = [
    ("UTAH", -111.7, 39.4), ("COLORADO", -106.4, 39.1),
    ("ARIZONA", -111.9, 34.2), ("NEW MEXICO", -106.0, 34.2),
    ("WYOMING", -108.7, 42.6), ("NEVADA", -115.2, 39.6),
    ("CALIFORNIA", -115.4, 34.2),
]


def _gj(path):
    p = ASSETS / path
    if p.exists():
        return json.load(open(p))
    return None


def _ring_xy(geom):
    """Yield (xs, ys) for each ring/line in a geometry."""
    t, c = geom.get("type"), geom.get("coordinates")
    if t == "LineString":
        yield [p[0] for p in c], [p[1] for p in c]
    elif t == "MultiLineString":
        for ls in c:
            yield [p[0] for p in ls], [p[1] for p in ls]
    elif t == "Polygon":
        for r in c:
            yield [p[0] for p in r], [p[1] for p in r]
    elif t == "MultiPolygon":
        for poly in c:
            for r in poly:
                yield [p[0] for p in r], [p[1] for p in r]


def _centroid(geom):
    pts = []
    def walk(x):
        if isinstance(x, (list, tuple)):
            if len(x) >= 2 and isinstance(x[0], (int, float)) and isinstance(x[1], (int, float)):
                pts.append((x[0], x[1]))
            else:
                for y in x:
                    walk(y)
    walk(geom.get("coordinates"))
    if not pts:
        return None
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def render_basin_map(grid_df, basin_vals, ranks, var_label, units, year, cmap="viridis",
                     mode_label="", fill_vals=None, label_map=None, diverging=False,
                     cbar_label=None):
    """Static CRB map (PNG data-URI).
       grid_df  : DataFrame[lat,lon,value] → draw gridded raster (Grid mode).
       fill_vals: {basin_id: value} → colour the leaf sub-basins (Basin/Trend/Period modes).
       label_map: {basin_id: 'second line'} → in-basin label text; else uses basin_vals/ranks.
       diverging: symmetric red↔blue scale centred on 0 (for trend / % change)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors
    except ImportError:
        return None   # matplotlib not installed → caller shows a blank placeholder

    basins_gj = _gj("crb_basins.geojson")
    rivers_gj = _gj("crb_rivers.geojson")
    if basins_gj is None:
        return None

    fig, ax = plt.subplots(figsize=(7.6, 7.6), dpi=115)
    ax.set_facecolor("#ffffff")

    # ── 1a · gridded "satellite" data raster (Grid mode) ──
    mesh = None
    if grid_df is not None and not grid_df.empty:
        piv = grid_df.pivot_table(index="lat", columns="lon", values="value")
        lons = piv.columns.values.astype(float)
        lats = piv.index.values.astype(float)
        Z = np.ma.masked_invalid(piv.values)
        # Robust, skew-aware normalisation so the full colour range is used.
        # Many hydrologic fields (runoff, SWE, baseflow) are extremely right-skewed
        # — most cells near zero, a few mountain cells very high — which makes a plain
        # linear scale render the whole basin one flat colour. We clip to the 2nd–98th
        # percentile and, when the field is right-skewed, apply a power stretch that
        # opens up the low end (magnitude ordering is preserved — this is not a rank map).
        valid = Z.compressed()
        norm = None
        if valid.size:
            vmin = float(np.percentile(valid, 2))
            vmax = float(np.percentile(valid, 98))
            if vmax <= vmin:
                vmax = vmin + 1.0
            if vmin < 0:                       # diverging-capable fields (e.g. temperature)
                norm = mcolors.Normalize(vmin, vmax)
            else:
                med = float(np.median(valid))
                rel = (med - vmin) / (vmax - vmin)   # where the median sits in the range
                if rel < 0.15:                 # very right-skewed → strong low-end stretch
                    norm = mcolors.PowerNorm(0.35, vmin=max(vmin, 0.0), vmax=vmax)
                elif rel < 0.35:               # moderately right-skewed
                    norm = mcolors.PowerNorm(0.55, vmin=max(vmin, 0.0), vmax=vmax)
                else:                          # roughly symmetric → linear
                    norm = mcolors.Normalize(vmin, vmax)
        mesh = ax.pcolormesh(lons, lats, Z, cmap=cmap, norm=norm,
                             shading="nearest", zorder=1)

    # ── 1b · filled sub-basins (Basin / Trend / Period Δ modes) ──
    sm = None
    if mesh is None and fill_vals:
        good = [v for v in fill_vals.values() if v is not None and np.isfinite(v)]
        if good:
            if diverging:
                m = max(abs(min(good)), abs(max(good))) or 1.0
                norm = mcolors.Normalize(-m, m)
                cmap_obj = plt.get_cmap("RdBu")
            else:
                lo, hi = min(good), max(good)
                norm = mcolors.Normalize(lo, hi if hi > lo else lo + 1)
                cmap_obj = plt.get_cmap(cmap)
            for f in basins_gj["features"]:
                bid = f["properties"]["basin_id"]
                if bid not in LEAF:
                    continue
                v = fill_vals.get(bid)
                fc = cmap_obj(norm(v)) if (v is not None and np.isfinite(v)) else "#dddddd"
                for xs, ys in _ring_xy(f["geometry"]):
                    ax.fill(xs, ys, facecolor=fc, edgecolor="none", zorder=1.5, alpha=0.9)
            sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap_obj)
            sm.set_array([])

    # ── 2 · state boundaries (under) + names ──
    for lo0, la0, lo1, la1 in STATE_LINES:
        ax.plot([lo0, lo1], [la0, la1], color="#7a7a7a", lw=1.0, ls=(0, (6, 4)),
                zorder=2, alpha=0.8)
    for nm, lo, la in STATE_NAMES:
        ax.text(lo, la, nm, fontsize=11, color="#5f6368", weight="bold",
                ha="center", va="center", alpha=0.65, zorder=2,
                family="DejaVu Sans")

    # ── 3 · sub-basin outlines (ASU maroon) ──
    for f in basins_gj["features"]:
        bid = f["properties"]["basin_id"]
        if bid == "CRB":
            for xs, ys in _ring_xy(f["geometry"]):
                ax.plot(xs, ys, color=NAVY, lw=2.4, zorder=5)
        elif bid in LEAF:
            for xs, ys in _ring_xy(f["geometry"]):
                ax.plot(xs, ys, color=MAROON, lw=1.4, zorder=4)

    # ── 4 · Colorado River + tributaries ──
    if rivers_gj:
        for f in rivers_gj["features"]:
            for xs, ys in _ring_xy(f["geometry"]):
                ax.plot(xs, ys, color="#0b4f9c", lw=2.0, zorder=6, alpha=0.9,
                        solid_capstyle="round")

    # ── 5 · BIG black labels inside each sub-basin (name · value · rank) ──
    for f in basins_gj["features"]:
        bid = f["properties"]["basin_id"]
        if bid not in LEAF:
            continue
        c = _centroid(f["geometry"])
        if not c:
            continue
        nm = BASIN_LABELS.get(bid, bid)
        if label_map is not None and bid in label_map and label_map[bid]:
            txt = f"{nm}\n{label_map[bid]}"
        else:
            v = basin_vals.get(bid)
            rk = ranks.get(bid)
            if v is not None and np.isfinite(v):
                line2 = f"{v:.1f}" + (f"  ·  {rk:.0f}th" if rk is not None else "")
                txt = f"{nm}\n{line2}"
            else:
                txt = nm
        ax.text(c[0], c[1], txt, fontsize=11.5, weight="bold", color="#000000",
                ha="center", va="center", zorder=8, linespacing=1.25,
                path_effects=None,
                bbox=dict(boxstyle="round,pad=0.18", fc="white", ec="none", alpha=0.72))

    # ── 6 · north-arrow compass ──
    x0, y0 = 0.945, 0.93   # axes-fraction
    ax.annotate("", xy=(x0, y0 + 0.045), xytext=(x0, y0 - 0.03),
                xycoords="axes fraction",
                arrowprops=dict(facecolor=NAVY, edgecolor=NAVY, width=3.2,
                                headwidth=11, headlength=11))
    ax.text(x0, y0 + 0.062, "N", transform=ax.transAxes, ha="center", va="bottom",
            fontsize=12, weight="bold", color=NAVY)

    # ── extent / cosmetics + lat–long graticule ──
    # Wider extent so the basin sits within visible context (margin on all sides);
    # data itself stays masked to the CRB.
    ax.set_xlim(-117.2, -102.8)
    ax.set_ylim(29.4, 45.2)
    ax.set_aspect(1.0 / np.cos(np.deg2rad(37.5)))   # rough geographic aspect
    lon_ticks = np.arange(-116, -102, 2)
    lat_ticks = np.arange(30, 46, 2)
    ax.set_xticks(lon_ticks); ax.set_yticks(lat_ticks)
    ax.set_xticklabels([f"{abs(t):.0f}°W" for t in lon_ticks], fontsize=8, color="#444")
    ax.set_yticklabels([f"{t:.0f}°N" for t in lat_ticks], fontsize=8, color="#444")
    ax.grid(True, color="#d6d6d6", lw=0.5, ls=":", zorder=0.5)
    ax.tick_params(length=3, color="#999")
    for s in ax.spines.values():
        s.set_edgecolor("#9aa0a6")

    # ── simple scale bar (~100 km) bottom-left ──
    km = 100.0
    deg = km / (111.0 * np.cos(np.deg2rad(37.5)))   # ° longitude for 100 km at ~37.5°N
    xb, yb = -114.9, 31.5
    ax.plot([xb, xb + deg], [yb, yb], color=NAVY, lw=3, solid_capstyle="butt", zorder=9)
    ax.text(xb + deg / 2, yb + 0.18, "100 km", ha="center", va="bottom",
            fontsize=8, color=NAVY, weight="bold", zorder=9)

    # ── colour-bar legend ──
    mappable = mesh if mesh is not None else sm
    if mappable is not None:
        cb = fig.colorbar(mappable, ax=ax, fraction=0.035, pad=0.015)
        cb.set_label(cbar_label or (f"{var_label}  ({units})" if units else var_label),
                     fontsize=10, color="#111111")
        cb.ax.tick_params(labelsize=9, color="#111111")

    ttl = f"Colorado River Basin — {var_label}"
    if mode_label:
        ttl += f"  ({mode_label})"
    ttl += f", WY{year}"
    ax.set_title(ttl, fontsize=13, weight="bold", color=MAROON, pad=10)

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("ascii")
    return "data:image/png;base64," + b64
