"""Macro view — Georgia macro-economics dashboard.

Reads the cached ``macro_series`` / ``macro_dataset`` tables (API-sourced from
Geostat + NBG; see docs/macro-data-runbook.md) and renders a tabbed dashboard:
Overview · GDP · Labour · External sector · Prices & money. All charts are Plotly
with the app's transparent, theme-aware layout; data comes through ``lib.cache``
(mtime-invalidated). Degrades gracefully if the macro tables aren't in the DB.

Interactivity: a page-level **year-range** slider (pick start & end year) clips
every time-series chart; each **snapshot** chart (top-N rankings, shares, weights)
has a compact **year picker** defaulting to the latest complete year.

Colour: single-/few-series charts use semantic hues; multi-category stacks and the
basket-weights pie use a CVD-validated 8-hue categorical palette (dataviz skill
reference), stepped for the dark surface. Text, gridlines and neutral overlay
lines follow the active light/dark theme (``lib.theme``) so nothing goes invisible
in dark mode.
"""
from __future__ import annotations

import datetime as _dt
import re

import pandas as pd
import streamlit as st

from lib import cache
from lib import theme as _theme
from views.shared import ViewContext

# CVD-validated categorical palette (dataviz skill reference), light + dark steps.
# Slots: blue, orange, aqua, yellow, magenta, green, violet, red.
_CAT_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
_CAT_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]

# Year-range slider: earliest selectable year (floor — most series start ~2010;
# only FDI/unemployment reach further back) and the default span in years.
_HZ_FLOOR = 2010
_HZ_DEFAULT_SPAN = 5

# Our source country names → the names Plotly's "country names" geo expects.
_GEO_NAME_FIX = {
    "Russian Federation": "Russia", "United States of America": "United States",
    "Iran, Islamic Republic Of": "Iran", "Iran, Islamic Republic of": "Iran",
    "Korea, Republic of": "South Korea", "Moldova, Republic of": "Moldova",
    "Syrian Arab Republic": "Syria", "Viet Nam": "Vietnam", "Czechia": "Czech Republic",
    "Tanzania, United Republic of": "Tanzania", "Türkiye": "Turkey",
    "Congo, The Democratic Republic of the": "Democratic Republic of the Congo",
}

# COICOP long names (differ slightly between the weights and the CPI series) →
# one short label, so weights and inflation join for the contribution decomposition.
_COICOP_SHORT = {
    "Food and non-alcoholic beverages": "Food & non-alc. drinks",
    "Alcoholic beverages and tobacco": "Alcohol & tobacco",
    "Clothing and footwear": "Clothing & footwear",
    "Housing, water, electricity, gas and other fuels": "Housing & utilities",
    "Furnishings, household equipment and routine household maintenance": "Furnishings & hh equip.",
    "Furnishings, household equipment and routine maintenance of the house": "Furnishings & hh equip.",
    "Health": "Health",
    "Transport": "Transport",
    "Communication": "Communication",
    "Recreation and culture": "Recreation & culture",
    "Education": "Education",
    "Restaurants and hotels": "Restaurants & hotels",
    "Miscellaneous goods and services": "Miscellaneous",
}

# Tourism spend categories → short legend labels.
_SPEND_SHORT = {
    "Holiday, leisure, recreation, cultural and sporting activities": "Leisure & recreation",
    "Foods and drinks": "Food & drink",
    "Other expenditure": "Other",
}

# Region buckets for grouping visitor arrivals (keyed on the ISO-2 country code
# carried in ``sub_breakdown``). Russia is kept separate from the rest of the CIS.
_EU27 = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU",
         "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"}
_CIS_EXR = {"AM", "AZ", "BY", "KZ", "KG", "MD", "TJ", "TM", "UZ", "UA"}
_MIDEAST = {"IR", "IL", "SA", "AE", "IQ", "JO", "LB", "KW", "QA", "BH", "OM", "YE", "SY", "PS"}

_FONT = "Inter, 'Segoe UI', system-ui, sans-serif"
_H = 380  # one chart height for the whole page (kept consistent across every chart)


# ---------------------------------------------------------------------------
# Theme-aware palette
# ---------------------------------------------------------------------------

def _pal():
    """Resolve the theme-aware colour set used across the macro charts.

    Returns a dict with neutral ink/grid/surface tokens (from ``lib.theme``) plus
    the CVD-validated categorical hues and named semantic handles into them.
    """
    mode = _theme.active_theme()
    t = _theme.tokens(mode)
    cat = _CAT_DARK if mode == "dark" else _CAT_LIGHT
    return {
        "mode": mode, "ink": t["ink"], "muted": t["ink_muted"], "faint": t["ink_faint"],
        "grid": t["grid"], "zero": t["zero"], "surface": t["surface"], "cat": cat,
        "blue": cat[0], "orange": cat[1], "teal": cat[2], "gold": cat[3],
        "magenta": cat[4], "green": cat[5], "violet": cat[6], "red": cat[7],
    }


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _ser(db, dataset, ptype, breakdown="TOTAL") -> pd.DataFrame:
    df = cache.macro_series(db, dataset, ptype)
    if df.empty:
        return df
    return df[df["breakdown"] == breakdown].sort_values("period")


def _clip(df, rng, ptype=None):
    """Keep only rows whose year falls within the (start, end) ``rng`` tuple.

    Works for any period_type — the year is the first four chars of ``period``
    ('YYYY', 'YYYY-Qn', 'YYYY-MM'). ``ptype`` is accepted for call-site symmetry.
    """
    if not rng or df is None or df.empty:
        return df
    lo, hi = rng
    yrs = df["period"].astype(str).str.slice(0, 4).astype(int)
    return df[(yrs >= lo) & (yrs <= hi)]


def _clip_years(years, rng):
    """From a list of 'YYYY' strings, keep those inside the (start, end) ``rng``."""
    ys = sorted(set(years))
    if not rng:
        return ys
    lo, hi = rng
    return [y for y in ys if lo <= int(str(y)[:4]) <= hi]


def _year_bounds(db):
    """(floor, latest) years spanned by the macro data, floored at ``_HZ_FLOOR``."""
    cat = cache.macro_catalog(db)
    yrs = []
    for col in ("min_period", "max_period"):
        if col in cat:
            for p in cat[col].dropna():
                s = str(p)[:4]
                if s.isdigit():
                    yrs.append(int(s))
    if not yrs:
        return (_HZ_FLOOR, _dt.date.today().year)
    return (max(_HZ_FLOOR, min(yrs)), max(yrs))


def _latest(db, dataset, ptype, breakdown="TOTAL", complete=False):
    df = _ser(db, dataset, ptype, breakdown)
    if df.empty:
        return None, None
    if complete and ptype == "annual":
        yr = _dt.date.today().year
        full = df[df["period"].str.fullmatch(r"\d{4}") & (df["period"].astype(int) < yr)]
        if not full.empty:
            df = full
    row = df.iloc[-1]
    return row["period"], row["value"]


def _top(db, dataset, period, ptype, n=12, exclude=("TOTAL",)):
    df = cache.macro_series(db, dataset, ptype)
    df = df[(df["period"] == period) & (~df["breakdown"].isin(exclude))]
    return df.sort_values("value", ascending=False).head(n)


def _latest_period_with_data(db, dataset, ptype=None):
    df = cache.macro_series(db, dataset, ptype)
    return df["period"].max() if not df.empty else None


def _annual_years(db, dataset):
    """Sorted list of 4-digit years that ``dataset`` has annual data for."""
    df = cache.macro_series(db, dataset, "annual")
    if df.empty:
        return []
    return sorted(p for p in df["period"].unique() if re.fullmatch(r"\d{4}", str(p)))


def _complete_year(db, dataset):
    df = cache.macro_series(db, dataset, "annual")
    if df.empty:
        return None
    yr = _dt.date.today().year
    ann = df[df["period"].str.fullmatch(r"\d{4}")]
    full = ann[ann["period"].astype(int) < yr]
    return (full if not full.empty else ann)["period"].max()


def _fold_other(df, cat_col, val_col, keep=7, other="Other"):
    """Collapse all but the ``keep`` largest categories (by total) into ``other``.

    Keeps stacks within the validated 8-hue cap. ``df`` is long (period × cat).
    """
    totals = df.groupby(cat_col)[val_col].sum().sort_values(ascending=False)
    if len(totals) <= keep + 1:
        return df, list(totals.index)
    top = list(totals.index[:keep])
    d = df.copy()
    d[cat_col] = d[cat_col].where(d[cat_col].isin(top), other)
    d = d.groupby([c for c in d.columns if c != val_col], as_index=False)[val_col].sum()
    return d, top + [other]


def _region_of(iso, name):
    iso = (iso or "").upper()
    if iso == "RU" or str(name).startswith("Russia"):
        return "Russia"
    if iso == "TR":
        return "Turkey"
    if iso in _EU27:
        return "EU"
    if iso in _CIS_EXR:
        return "CIS excl. Russia"
    if iso in _MIDEAST:
        return "Middle East"
    return "Other"


def _partial_year(db):
    """(year:int, months:int) for the latest incomplete year of tourism data, else
    (None, None). Coverage is read from the quarterly-visits series (quarters × 3)."""
    vq = cache.macro_series(db, "tourism_visits_quarterly", "quarter")
    if vq.empty:
        return None, None
    ymax = int(vq["period"].str.slice(0, 4).astype(int).max())
    nq = vq[vq["period"].str.startswith(str(ymax))]["period"].nunique()
    return (ymax, nq * 3) if nq < 4 else (None, None)


def _yr_label(year, partial_year, months):
    """'2026' → '3m26' for the partial year, plain string otherwise."""
    if partial_year and int(year) == partial_year:
        return f"{months}m{str(int(year))[2:]}"
    return str(int(year))


def _arrivals_by_region(db):
    """Visitor arrivals grouped into regions → (long df [period, year, region, value],
    region order by total). Uses the per-country annual arrivals + ISO-2 codes."""
    arr = cache.macro_series(db, "tourism_arrivals_by_country", "annual")
    if arr.empty:
        return pd.DataFrame(), []
    d = arr[(arr["breakdown"] != "TOTAL") & (arr["breakdown"] != "Georgia")].copy()
    d["region"] = [_region_of(i, n) for i, n in zip(d["sub_breakdown"], d["breakdown"])]
    g = d.groupby(["period", "region"])["value"].sum().reset_index()
    g["year"] = g["period"].astype(int)
    order = g.groupby("region")["value"].sum().sort_values(ascending=False).index.tolist()
    return g, order


def _year_picker(title, years, default, key):
    """Render a chart title with a compact year selectbox under it; return the year."""
    st.markdown(f"##### {title}")
    if not years:
        return default
    idx = years.index(default) if default in years else len(years) - 1
    return st.selectbox("Period", years, index=idx, key=key, label_visibility="collapsed")


def _head_row(left, right, years=None, default=None, key=None):
    """Titles for a side-by-side chart pair, as their OWN columns row.

    Only one chart in a pair usually needs a year picker, and rendering that picker
    inside the chart's column pushed its chart a picker's height (~89px) below its
    neighbour. Titles live in a separate row instead: the row is as tall as the taller
    header, so the charts row below always starts both charts on the same line — no
    pixel padding to keep in sync with Streamlit's own spacing. Returns the picked year.
    """
    h1, h2 = st.columns(2)
    with h1:
        st.markdown(f"##### {left}")
    with h2:
        return _year_picker(right, years, default, key)


def _ca_pct_gdp(db) -> pd.DataFrame:
    """Annual current-account balance as % of GDP (both in USD)."""
    ca = cache.macro_series(db, "current_account", "quarter")
    gdp = _ser(db, "gdp_usd", "annual")
    if ca.empty or gdp.empty:
        return pd.DataFrame(columns=["period", "value"])
    ca = ca[ca["breakdown"] == "TOTAL"].copy()
    ca["yr"] = ca["period"].str.slice(0, 4)
    full = ca.groupby("yr").filter(lambda g: len(g) == 4)
    ca_ann = full.groupby("yr")["value"].sum()
    gdp_map = gdp.set_index("period")["value"]
    rows = [(yr, round(100.0 * v / gdp_map[yr], 1)) for yr, v in ca_ann.items()
            if yr in gdp_map.index and gdp_map[yr]]
    return pd.DataFrame(rows, columns=["period", "value"]).sort_values("period")


def _annual_cpi_inflation(db) -> dict:
    """{year: mean of the 12 monthly YoY headline-CPI readings}."""
    y = cache.macro_series(db, "cpi_yoy", "month")
    if y.empty:
        return {}
    y = y[y["breakdown"] == "TOTAL"].copy()
    y["yr"] = y["period"].str.slice(0, 4)
    return y.groupby("yr")["value"].mean().to_dict()


def _real_wage_growth(db) -> pd.DataFrame:
    """Annual real wage growth = nominal wage growth (economy-wide) − CPI inflation."""
    w = _ser(db, "wages_by_sector", "annual", "TOTAL")
    if w.empty:
        return pd.DataFrame(columns=["period", "value"])
    w = w.sort_values("period").copy()
    w["nom_g"] = w["value"].pct_change() * 100
    infl = _annual_cpi_inflation(db)
    w["value"] = w.apply(lambda r: r["nom_g"] - infl.get(r["period"], float("nan")), axis=1).round(1)
    return w.dropna(subset=["value"])[["period", "value"]]


def _inflation_contributions(db, rng=None):
    """Contribution (percentage points) of each COICOP group to headline YoY CPI.

    contribution_i = weight_i(share) × group_YoY_i. Weights are annual; a month
    uses its own year's basket (nearest earlier year if missing). Returns
    (long df [period, group, contrib], headline df [period, headline]); months are
    filtered to the (start, end) year range ``rng`` (all months if None).
    """
    w = cache.macro_series(db, "cpi_weights", "annual")
    y = cache.macro_series(db, "cpi_yoy", "month")
    if w.empty or y.empty:
        return pd.DataFrame(), pd.DataFrame()
    w = w.copy()
    w["g"] = w["breakdown"].map(lambda x: _COICOP_SHORT.get(x, x))
    wt = {(p, g): v for p, g, v in zip(w["period"], w["g"], w["value"])}
    wyears = sorted(w["period"].unique())

    def weight_for(period, g):
        yr = period[:4]
        if (yr, g) in wt:
            return wt[(yr, g)]
        earlier = [p for p in wyears if p <= yr]
        return wt.get((earlier[-1], g)) if earlier else None

    grp = y[y["breakdown"] != "TOTAL"].copy()
    grp["g"] = grp["breakdown"].map(lambda x: _COICOP_SHORT.get(x, x))
    grp["w"] = [weight_for(p, g) for p, g in zip(grp["period"], grp["g"])]
    grp = grp.dropna(subset=["w"])
    grp["contrib"] = grp["w"] * grp["value"]
    keep = sorted(grp["period"].unique())
    if rng:
        lo, hi = rng
        keep = [p for p in keep if lo <= int(p[:4]) <= hi]
    grp = grp[grp["period"].isin(keep)]
    head = (y[(y["breakdown"] == "TOTAL") & (y["period"].isin(keep))]
            [["period", "value"]].rename(columns={"value": "headline"}))
    return grp[["period", "g", "contrib"]], head


def _expenditure_decomposition(db):
    """Contribution of each expenditure aggregate to annual real GDP growth.

    contribution_i = real_growth_i × prior-year nominal share_i (imports enter
    negative, since GDP = C + I + X − M). Households fold into Final Consumption;
    only the four top-level aggregates are shown. Returns (long df, total df).
    """
    g = cache.macro_series(db, "gdp_growth_by_expenditure", "annual")
    lv = cache.macro_series(db, "gdp_by_expenditure", "annual")
    if g.empty or lv.empty:
        return pd.DataFrame(), pd.DataFrame()
    gdp = lv[lv["breakdown"] == "TOTAL"].set_index("period")["value"]
    comps = [("Final Consumption Expenditures", "Consumption", 1),
             ("Gross Capital Formation", "Investment", 1),
             ("Exports of Goods and Services", "Exports", 1),
             ("Imports of Goods and Services", "Imports (−)", -1)]
    rows = []
    for period in sorted(g["period"].unique()):
        prev = str(int(period) - 1)
        if prev not in gdp.index or not gdp[prev]:
            continue
        for raw, label, sign in comps:
            gr = g[(g["period"] == period) & (g["breakdown"] == raw)]["value"]
            lvp = lv[(lv["period"] == prev) & (lv["breakdown"] == raw)]["value"]
            if gr.empty or lvp.empty:
                continue
            share = lvp.iloc[0] / gdp[prev]
            rows.append({"period": period, "component": label,
                         "contrib": round(sign * gr.iloc[0] * share, 2)})
    df = pd.DataFrame(rows)
    tot = (g[g["breakdown"] == "TOTAL"][["period", "value"]]
           .rename(columns={"value": "total"}))
    if not df.empty:
        tot = tot[tot["period"].isin(df["period"].unique())]
    return df, tot


# ---------------------------------------------------------------------------
# Plotly layout + chart builders (all theme-aware via ``pal``)
# ---------------------------------------------------------------------------

def _layout(fig, pal, height=_H, legend=True, hover="x unified"):
    fig.update_layout(
        height=height, margin=dict(l=52, r=30, t=38, b=44),
        paper_bgcolor=pal["surface"], plot_bgcolor=pal["surface"],
        font=dict(family=_FONT, size=13, color=pal["ink"]),
        hoverlabel=dict(font=dict(family=_FONT, size=12)),
        hovermode=hover, bargap=0.3, showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right",
                    x=1, font=dict(size=11, color=pal["muted"])) if legend else dict(),
    )
    fig.update_xaxes(gridcolor=pal["grid"], zeroline=False, linecolor=pal["grid"],
                     tickfont=dict(color=pal["muted"]), title_font=dict(color=pal["muted"]))
    fig.update_yaxes(gridcolor=pal["grid"], zeroline=False, linecolor=pal["grid"],
                     tickfont=dict(color=pal["muted"]), title_font=dict(color=pal["muted"]))
    # Zero baseline: PRIMARY axes only, in a much darker ink than the hairline grid.
    # Set through fig.layout rather than update_[xy]axes on purpose — the dual-axis charts
    # switch the secondary axis's zeroline off (its zero sits at a different height than the
    # left axis's, so a second line would read as one misplaced baseline), and a blanket
    # update_yaxes here runs last and would undo that.
    for _ax in (fig.layout.xaxis, fig.layout.yaxis):
        _ax.update(zeroline=True, zerolinecolor=pal["zero"], zerolinewidth=1.5)
    fig.update_traces(marker=dict(cornerradius=4), selector=dict(type="bar"))
    fig.update_traces(line=dict(width=2.6), marker=dict(size=8), selector=dict(type="scatter"))
    return fig


def _bar_fig(df, name, color, unit, pal, height=_H):
    import plotly.graph_objects as go
    fig = go.Figure(go.Bar(x=df["period"], y=df["value"], name=name, marker_color=color,
                           hovertemplate="%{x}<br>%{y:,.1f} " + unit + "<extra></extra>"))
    return _layout(fig, pal, height, legend=False)


def _line_fig(traces, unit, pal, height=_H):
    """traces = [(name, df, color)]."""
    import plotly.graph_objects as go
    fig = go.Figure()
    for name, df, color in traces:
        fig.add_trace(go.Scatter(
            x=df["period"], y=df["value"], name=name, mode="lines",
            line=dict(color=color, width=2.6),
            hovertemplate="%{x}<br>" + name + ": %{y:,.1f} " + unit + "<extra></extra>"))
    return _layout(fig, pal, height, legend=len(traces) > 1)


def _hbar_fig(df, color, unit, pal, height=_H, name_fix=False, pct=False):
    """Horizontal ranking bars: full category name (truncated on the axis, full on
    hover), the axis auto-sizes to fit it, and a direct value label at each bar end."""
    import plotly.graph_objects as go
    d = df.sort_values("value")
    full = [_GEO_NAME_FIX.get(x, x) if name_fix else str(x) for x in d["breakdown"]]
    short = [s if len(s) <= 28 else s[:27] + "…" for s in full]
    txt = [f"{v:,.1f}" if pct else f"{v:,.0f}" for v in d["value"]]
    hv = ("%{customdata}<br>" + ("%{x:,.1f}" if pct else "%{x:,.0f}") + " " + unit + "<extra></extra>")
    fig = go.Figure(go.Bar(
        x=d["value"], y=short, orientation="h", marker_color=color,
        text=txt, textposition="outside", textfont=dict(color=pal["muted"], size=11),
        cliponaxis=False, customdata=full, hovertemplate=hv))
    fig = _layout(fig, pal, height, legend=False, hover="closest")
    vmax = float(d["value"].max()) if len(d) else 1.0
    vmin = min(0.0, float(d["value"].min())) if len(d) else 0.0
    fig.update_xaxes(range=[vmin, vmax * 1.22], showgrid=True)
    fig.update_yaxes(showgrid=False, automargin=True)  # expand left margin to fit labels
    fig.update_layout(margin=dict(r=56))               # room for the outside value labels
    return fig


def _stack_fig(df, x, color_col, y, pal, unit, order=None, height=_H, barmode="stack"):
    """Stacked bar over `x`, one series per `color_col` value, with segment gaps."""
    import plotly.express as px
    fig = px.bar(df, x=x, y=y, color=color_col, barmode=barmode,
                 color_discrete_sequence=pal["cat"],
                 category_orders={color_col: order} if order else None)
    fig.update_traces(
        marker_line=dict(width=1, color=pal["surface"]),  # 1px surface gap between fills
        hovertemplate="%{x}<br>%{fullData.name}: %{y:,.1f} " + unit + "<extra></extra>")
    return _layout(fig, pal, height, legend=True)


# ---------------------------------------------------------------------------
# KPI row
# ---------------------------------------------------------------------------

def _kpis(db):
    # latest value + the value one year earlier (row-1 for annual, 12 rows back for
    # monthly), so each card can show a year-on-year delta.
    def lp(dataset, ptype, breakdown="TOTAL", complete=False, lag=1):
        df = _ser(db, dataset, ptype, breakdown)
        if df.empty:
            return None, None, None
        if complete and ptype == "annual":
            yr = _dt.date.today().year
            full = df[df["period"].str.fullmatch(r"\d{4}") & (df["period"].astype(int) < yr)]
            if not full.empty:
                df = full
        cur = df.iloc[-1]
        prev = df.iloc[-1 - lag] if len(df) > lag else None
        return cur["period"], cur["value"], (None if prev is None else prev["value"])

    pct = lambda v, pv: f"{(v/pv - 1)*100:+.1f}%" if pv else None   # level → YoY %
    pp = lambda v, pv: f"{v - pv:+.1f} pp"                          # rate  → YoY Δ (pp)

    def show(col, label, p, v, pv, valfmt, delta=None, dcolor="normal", help=None):
        d = delta(v, pv) if (delta and v is not None and pv not in (None, 0)) else None
        tip = (f"{help} · {p}" if help else str(p)) if p else help
        col.metric(label, valfmt(v) if v is not None else "—", delta=d, delta_color=dcolor, help=tip)

    r1 = st.columns(4)
    show(r1[0], "Nominal GDP", *lp("gdp_nominal", "annual", complete=True),
         lambda v: f"₾{v/1000:,.1f}bn", pct, help="GDP at current prices")
    show(r1[1], "Real GDP growth", *lp("gdp_real_growth", "annual", complete=True),
         lambda v: f"{v:+.1f}%", pp, dcolor="off")
    show(r1[2], "GDP per capita", *lp("gdp_per_capita_usd", "annual", complete=True),
         lambda v: f"${v:,.0f}", pct)
    show(r1[3], "Unemployment", *lp("unemployment_rate", "annual", complete=True),
         lambda v: f"{v:.1f}%", pp, dcolor="inverse")
    r2 = st.columns(4)
    show(r2[0], "Inflation (CPI)", *lp("cpi_yoy", "month", lag=12),
         lambda v: f"{v:.1f}%", pp, dcolor="off")
    show(r2[1], "Policy rate", *lp("policy_rate", "month", lag=12),
         lambda v: f"{v:.2f}%", pp, dcolor="off")
    show(r2[2], "FDI (net, yr)", *lp("fdi_total", "annual", complete=True),
         lambda v: f"${v/1e9:.2f}bn", pct)
    ca = _ca_pct_gdp(db)
    if not ca.empty:
        cp, cv = ca["period"].iloc[-1], ca["value"].iloc[-1]
        cpv = ca["value"].iloc[-2] if len(ca) > 1 else None
        show(r2[3], "Current account", cp, cv, cpv, lambda v: f"{v:+.1f}%", pp,
             help="Balance as % of GDP")
    else:
        r2[3].metric("Current account", "—")


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

def _overview(db, hz, pal):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### Nominal GDP & real growth")
        gdp = _clip(_ser(db, "gdp_nominal", "annual"), hz, "annual")
        rg = _clip(_ser(db, "gdp_real_growth", "annual"), hz, "annual")
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Bar(x=gdp["period"], y=gdp["value"] / 1000, name="GDP (₾bn)",
                             marker_color=pal["blue"],
                             hovertemplate="%{x}<br>₾%{y:,.1f}bn<extra></extra>"), secondary_y=False)
        fig.add_trace(go.Scatter(x=rg["period"], y=rg["value"], name="Real growth (%)",
                                 mode="lines+markers", line=dict(color=pal["green"], width=3),
                                 hovertemplate="%{x}<br>%{y:.1f}%<extra></extra>"), secondary_y=True)
        fig.update_yaxes(title_text="₾bn", secondary_y=False)  # left axis owns the gridlines
        fig.update_yaxes(title_text="%", secondary_y=True, showgrid=False, zeroline=False)
        st.plotly_chart(_layout(fig, pal), use_container_width=True, theme=None, key="mac_ov_gdp")
    with c2:
        st.markdown("##### Inflation & policy rate")
        traces = [("Headline CPI", _ser(db, "cpi_yoy", "month", "TOTAL"), pal["orange"]),
                  ("Core", _ser(db, "cpi_core_yoy", "month"), pal["blue"]),
                  ("Policy rate", _ser(db, "policy_rate", "month"), pal["red"])]
        traces = [(n, _clip(d, hz, "month"), c) for n, d, c in traces if not d.empty]
        fig = _line_fig(traces, "%", pal)
        fig.add_hline(y=3.0, line_dash="dot", line_color=pal["faint"],
                      annotation_text="NBG target 3%", annotation_position="bottom left",
                      annotation_font=dict(color=pal["muted"], size=11))
        st.plotly_chart(fig, use_container_width=True, theme=None, key="mac_ov_infl")
    st.caption("Dotted line = NBG's 3% inflation target. GDP bars are current-price ₾bn; "
               "real growth and prices/rate are on the right-hand % axis.")


def _gdp(db, hz, pal):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### Nominal GDP & GDP per capita")
        gdp = _clip(_ser(db, "gdp_nominal", "annual"), hz, "annual")
        pc = _clip(_ser(db, "gdp_per_capita_usd", "annual"), hz, "annual")
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Bar(x=gdp["period"], y=gdp["value"] / 1000, name="GDP (₾bn)",
                             marker_color=pal["blue"],
                             hovertemplate="%{x}<br>₾%{y:,.1f}bn<extra></extra>"), secondary_y=False)
        fig.add_trace(go.Scatter(x=pc["period"], y=pc["value"], name="Per capita ($)",
                                 mode="lines+markers", line=dict(color=pal["teal"], width=3),
                                 hovertemplate="%{x}<br>$%{y:,.0f}<extra></extra>"), secondary_y=True)
        fig.update_yaxes(title_text="₾bn", secondary_y=False)  # left axis owns the gridlines
        fig.update_yaxes(title_text="US$", secondary_y=True, showgrid=False, zeroline=False)
        st.plotly_chart(_layout(fig, pal), use_container_width=True, theme=None, key="mac_gdp_level")
    with c2:
        st.markdown("##### Real GDP growth (annual)")
        st.plotly_chart(_bar_fig(_clip(_ser(db, "gdp_real_growth", "annual"), hz, "annual"),
                                 "Real growth", pal["green"], "%", pal),
                        use_container_width=True, theme=None, key="mac_gdp_rg")

    pyears = _annual_years(db, "gdp_by_production")
    yr = _head_row("Monthly GDP growth (rapid estimate)", "GDP by production — share of GDP",
                   pyears, _complete_year(db, "gdp_by_production"), "mac_gdp_prod_yr")
    c3, c4 = st.columns(2)
    with c3:
        mon = _clip(_ser(db, "gdp_monthly_growth", "month"), hz, "month")
        if not mon.empty:
            st.plotly_chart(_line_fig([("Monthly YoY", mon, pal["orange"])], "%", pal),
                            use_container_width=True, theme=None, key="mac_gdp_mon")
            st.caption("Best-effort — from Geostat's monthly rapid-estimate press release.")
        else:
            st.caption("Monthly rapid estimate not available.")
    with c4:
        prod = cache.macro_series(db, "gdp_by_production", "annual")
        gval = _ser(db, "gdp_nominal", "annual")
        gval = gval[gval["period"] == yr]["value"]
        if not prod.empty and not gval.empty:
            d = prod[(prod["period"] == yr) & (prod["breakdown"] != "TOTAL")].copy()
            d["value"] = d["value"] / gval.iloc[0] * 100
            st.plotly_chart(_hbar_fig(d.nlargest(10, "value"), pal["violet"], "% of GDP", pal, pct=True),
                            use_container_width=True, theme=None, key="mac_gdp_prod")
            st.caption("Gross value added by activity ÷ nominal GDP. Shares sum to <100% — "
                       "the remainder is net taxes on products.")

    st.markdown("##### Contributions to real GDP growth — by expenditure")
    df, tot = _expenditure_decomposition(db)
    if not df.empty:
        keep = _clip_years(df["period"].unique(), hz)
        df = df[df["period"].isin(keep)]
        tot = tot[tot["period"].isin(keep)]
        fig = go.Figure()
        for label, color in [("Consumption", pal["blue"]), ("Investment", pal["orange"]),
                             ("Exports", pal["green"]), ("Imports (−)", pal["red"])]:
            dd = df[df["component"] == label]
            fig.add_trace(go.Bar(x=dd["period"], y=dd["contrib"], name=label, marker_color=color,
                                 marker_line=dict(width=1, color=pal["surface"]),
                                 hovertemplate="%{x}<br>" + label + ": %{y:+.1f}pp<extra></extra>"))
        fig.add_trace(go.Scatter(x=tot["period"], y=tot["total"], name="Real GDP growth",
                                 mode="lines+markers", line=dict(color=pal["ink"], width=2.5),
                                 hovertemplate="%{x}<br>Total: %{y:.1f}%<extra></extra>"))
        fig.update_layout(barmode="relative")
        fig.update_yaxes(title_text="pp / %")
        st.plotly_chart(_layout(fig, pal), use_container_width=True, theme=None, key="mac_gdp_exp")
        st.caption("Each bar = component real growth × its prior-year share of GDP "
                   "(GDP = Consumption + Investment + Exports − Imports; households sit inside "
                   "Consumption). Bars sum to the real-growth line.")


def _labour(db, hz, pal):
    import plotly.graph_objects as go

    wyears = _annual_years(db, "wages_by_sector")
    yr = _head_row("Unemployment & real wage growth", "Average monthly wage by sector",
                   wyears, _complete_year(db, "wages_by_sector"), "mac_lab_wage_yr")
    c1, c2 = st.columns(2)
    with c1:
        unemp = _clip(_ser(db, "unemployment_rate", "annual"), hz, "annual")
        rwg = _clip(_real_wage_growth(db), hz, "annual")
        # Both series are in %, so a single shared axis (no dual scale).
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=unemp["period"], y=unemp["value"], name="Unemployment",
                                 mode="lines+markers", line=dict(color=pal["red"], width=2.8),
                                 hovertemplate="%{x}<br>%{y:.1f}%<extra></extra>"))
        if not rwg.empty:
            fig.add_trace(go.Scatter(x=rwg["period"], y=rwg["value"], name="Real wage growth",
                                     mode="lines+markers", line=dict(color=pal["teal"], width=2.8),
                                     hovertemplate="%{x}<br>%{y:+.1f}%<extra></extra>"))
        # No manual zero line — _layout draws the axis zero baseline in the darker ink.
        fig.update_yaxes(title_text="%")
        st.plotly_chart(_layout(fig, pal), use_container_width=True, theme=None, key="mac_lab_unemp")
        st.caption("Both in %. Real wage growth = economy-wide nominal wage growth − average CPI inflation.")
    with c2:
        w = cache.macro_series(db, "wages_by_sector", "annual")
        avg = w[(w["period"] == str(yr)) & (w["breakdown"] == "TOTAL")]["value"]
        d = w[(w["period"] == str(yr)) & (w["breakdown"] != "TOTAL")].nlargest(10, "value")
        fig = _hbar_fig(d, pal["green"], "₾", pal)
        if not avg.empty:
            fig.add_vline(x=float(avg.iloc[0]), line_dash="dash", line_color=pal["ink"],
                          annotation_text=f"Economy avg ₾{avg.iloc[0]:,.0f}",
                          annotation_position="top", annotation_font_color=pal["muted"])
        st.plotly_chart(fig, use_container_width=True, theme=None, key="mac_lab_wage")
        prov = w[(w["period"] == str(yr)) & (w["breakdown"] == "TOTAL")]["source"]
        if not prov.empty and prov.astype(str).str.contains("provisional").any():
            st.caption(f"{yr} annual is provisional — last official annual chained by quarterly growth.")


def _external(db, hz, pal):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    # --- Trade -------------------------------------------------------------
    st.markdown("##### External trade & balance")
    exp = _clip(_ser(db, "trade_flows_total", "annual", "Export"), hz, "annual")
    imp = _clip(_ser(db, "trade_flows_total", "annual", "Import"), hz, "annual")
    bal = _clip(_ser(db, "trade_flows_total", "annual", "Balance"), hz, "annual")
    fig = go.Figure()
    fig.add_trace(go.Bar(x=exp["period"], y=exp["value"] / 1e6, name="Exports", marker_color=pal["blue"]))
    fig.add_trace(go.Bar(x=imp["period"], y=imp["value"] / 1e6, name="Imports", marker_color=pal["red"]))
    fig.add_trace(go.Scatter(x=bal["period"], y=bal["value"] / 1e6, name="Balance",
                             mode="lines+markers", line=dict(color=pal["ink"], width=3)))
    fig.update_layout(barmode="group")
    fig.update_yaxes(title_text="US$ bn")
    st.plotly_chart(_layout(fig, pal), use_container_width=True, theme=None, key="mac_ext_trade")

    c1, c2 = st.columns(2)
    with c1:
        pyears = _annual_years(db, "exports_by_partner")
        tp = _year_picker("Exports by partner", pyears,
                          _complete_year(db, "exports_by_partner"), "mac_ext_partner_yr")
        d = _top(db, "exports_by_partner", tp, "annual", 12)
        d = d.assign(value=d["value"] / 1000)
        st.plotly_chart(_hbar_fig(d, pal["blue"], "US$ mln", pal), use_container_width=True, theme=None, key="mac_ext_partner")
    with c2:
        hyears = _annual_years(db, "exports_by_product_hs4")
        hp = _year_picker("Top export products (HS4)", hyears,
                          _complete_year(db, "exports_by_product_hs4"), "mac_ext_hs4_yr")
        d = _top(db, "exports_by_product_hs4", hp, "annual", 12)
        d = d.assign(value=d["value"] / 1000)
        st.plotly_chart(_hbar_fig(d, pal["orange"], "US$ mln", pal), use_container_width=True, theme=None, key="mac_ext_hs4")

    # --- Current account ---------------------------------------------------
    st.markdown("##### Current account — components & balance (% of GDP)")
    ca = cache.macro_series(db, "current_account", "quarter")
    capct = _ca_pct_gdp(db)
    if not ca.empty:
        ca = ca[ca["breakdown"] != "TOTAL"].copy()
        ca["year"] = ca["period"].str.slice(0, 4).astype(int)
        cnt = ca.groupby(["year", "breakdown"]).size().reset_index(name="n")
        full_years = cnt[cnt["n"] == 4]["year"].unique()
        agg = (ca[ca["year"].isin(full_years)].groupby(["year", "breakdown"])["value"]
               .sum().reset_index())
        keep = {int(y) for y in _clip_years([str(y) for y in agg["year"].unique()], hz)}
        agg = agg[agg["year"].isin(keep)]
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        comp_colors = {"Goods": pal["red"], "Services": pal["blue"],
                       "Primary income": pal["violet"], "Secondary income": pal["green"]}
        for comp, col in comp_colors.items():
            dd = agg[agg["breakdown"] == comp]
            fig.add_trace(go.Bar(x=dd["year"], y=dd["value"], name=comp, marker_color=col,
                                 marker_line=dict(width=1, color=pal["surface"])), secondary_y=False)
        cap = capct[capct["period"].astype(int).isin(keep)]
        fig.add_trace(go.Scatter(x=cap["period"].astype(int), y=cap["value"],
                                 name="Balance (% of GDP)", mode="lines+markers",
                                 line=dict(color=pal["ink"], width=2.6),
                                 hovertemplate="%{x}<br>%{y:+.1f}% of GDP<extra></extra>"),
                      secondary_y=True)
        fig.update_layout(barmode="relative")
        fig.update_yaxes(title_text="US$ mln", secondary_y=False)  # left axis owns the gridlines
        fig.update_yaxes(title_text="% of GDP", secondary_y=True, showgrid=False, zeroline=False)
        st.plotly_chart(_layout(fig, pal), use_container_width=True, theme=None, key="mac_ext_ca")
        st.caption("Net Goods / Services / Primary & Secondary income (bars, US$ mln) sum to the "
                   "current-account balance; the dark line shows that balance as % of GDP (right axis).")

    # --- Foreign direct investment ----------------------------------------
    # Titled per column (like the exports pair above) rather than under one shared
    # section header, which left this pair's two charts on different lines.
    fyears = _annual_years(db, "fdi_by_country")
    fy = _head_row("Foreign direct investment", "FDI by source country",
                   fyears, _complete_year(db, "fdi_by_country"), "mac_fdi_country_yr")
    c3, c4 = st.columns(2)
    with c3:
        fdi = _clip(_ser(db, "fdi_total", "annual"), hz, "annual")
        st.plotly_chart(_bar_fig(fdi.assign(value=fdi["value"] / 1e9), "FDI", pal["teal"], "US$ bn", pal),
                        use_container_width=True, theme=None, key="mac_fdi_total")
        st.caption("Net FDI inflows, US$ bn per year.")
    with c4:
        d = _top(db, "fdi_by_country", fy, "annual", 12)
        d = d.assign(value=d["value"] / 1e6)
        st.plotly_chart(_hbar_fig(d, pal["blue"], "US$ mln", pal, name_fix=True),
                        use_container_width=True, theme=None, key="mac_fdi_country")
        st.caption("Top 12 source countries, US$ mln.")
    fsyears = _annual_years(db, "fdi_by_sector")
    fsy = _year_picker("FDI by sector", fsyears,
                       _complete_year(db, "fdi_by_sector"), "mac_fdi_sector_yr")
    d = _top(db, "fdi_by_sector", fsy, "annual", 12)
    d = d.assign(value=d["value"] / 1e6)
    st.plotly_chart(_hbar_fig(d, pal["violet"], "US$ mln", pal),
                    use_container_width=True, theme=None, key="mac_fdi_sector")

    # --- Tourism & remittances --------------------------------------------
    _tourism(db, hz, pal)


def _tourism(db, hz, pal):
    import plotly.express as px

    st.markdown("##### Where visitors come from")
    arr = cache.macro_series(db, "tourism_arrivals_by_country", "annual")
    if not arr.empty:
        years = sorted(arr[arr["breakdown"] != "TOTAL"]["period"].unique())
        default = years[-2] if len(years) >= 2 else years[-1]
        yr = st.select_slider("Year", options=years, value=default, key="mac_tour_year")
        d = arr[(arr["period"] == yr) & (arr["breakdown"] != "TOTAL") & (arr["breakdown"] != "Georgia")].copy()
        d["country"] = d["breakdown"].map(lambda x: _GEO_NAME_FIX.get(x, x))
        import numpy as np
        d["logv"] = np.log10(d["value"].clip(lower=1))
        map_col, tbl_col = st.columns([2, 1])
        with map_col:
            fig = px.choropleth(d, locations="country", locationmode="country names",
                                color="logv", color_continuous_scale="Blues",
                                hover_name="breakdown", custom_data=["value"],
                                projection="natural earth")
            fig.update_traces(hovertemplate="%{hovertext}<br>%{customdata[0]:,.0f} visitors<extra></extra>")
            ticks = [3, 4, 5, 6]
            fig.update_layout(
                height=_H, margin=dict(l=8, r=8, t=8, b=8),
                paper_bgcolor=pal["surface"], geo=dict(bgcolor=pal["surface"]),
                font=dict(color=pal["muted"]),
                coloraxis_colorbar=dict(title="visitors", tickvals=ticks,
                                        ticktext=["1k", "10k", "100k", "1M"]))
            st.plotly_chart(fig, use_container_width=True, theme=None, key="mac_tour_map")
        with tbl_col:
            tbl = (d[["breakdown", "value"]].rename(columns={"breakdown": "Country", "value": "Visits"})
                   .sort_values("Visits", ascending=False).reset_index(drop=True))
            tbl.index = tbl.index + 1  # 1-based rank
            st.dataframe(tbl, height=_H, use_container_width=True,
                         column_config={"Visits": st.column_config.NumberColumn(
                             "Visits", format="localized")})

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### Arrivals by region (annual)")
        reg, order = _arrivals_by_region(db)
        if not reg.empty:
            keep = {int(y) for y in _clip_years([str(y) for y in reg["year"].unique()], hz)}
            reg = reg[reg["year"].isin(keep)].copy()
            reg["value"] = reg["value"] / 1000  # persons → thousands
            py, pm = _partial_year(db)
            reg["yr"] = reg["year"].apply(lambda y: _yr_label(y, py, pm))
            xorder = [_yr_label(y, py, pm) for y in sorted(reg["year"].unique())]
            fig = _stack_fig(reg, "yr", "region", "value", pal, "thsd visitors", order=order)
            fig.update_xaxes(categoryorder="array", categoryarray=xorder)
            fig.update_yaxes(title_text="thsd visitors")
            st.plotly_chart(fig, use_container_width=True, theme=None, key="mac_tour_grp")
            note = f" The latest bar ({pm}m{str(py)[2:]}) is year-to-date." if py else ""
            st.caption("By country of citizenship, grouped into regions. CIS excl. Russia = Armenia, "
                       "Azerbaijan, Belarus, Kazakhstan, Kyrgyzstan, Moldova, Tajikistan, Turkmenistan, "
                       "Uzbekistan, Ukraine — Russia is shown separately." + note)
    with c2:
        st.markdown("##### Inbound tourism revenue (by spend category)")
        tr = cache.macro_series(db, "tourism_revenue", "annual")
        if not tr.empty:
            d = tr[tr["breakdown"] != "TOTAL"].copy()
            d["breakdown"] = d["breakdown"].map(lambda x: _SPEND_SHORT.get(x, x))
            d["year"] = d["period"].astype(int)
            keep = {int(y) for y in _clip_years([str(y) for y in d["year"].unique()], hz)}
            d = d[d["year"].isin(keep)]
            fig = _stack_fig(d, "year", "breakdown", "value", pal, "mln GEL")
            fig.update_yaxes(title_text="₾ mln")
            st.plotly_chart(fig, use_container_width=True, theme=None, key="mac_tour_rev")
            st.caption("Geostat visitor-survey spend, ₾mln. Not published by country — only visitor "
                       "*arrivals* (left) are broken out by country. 2020–2021 are absent: the inbound-"
                       "visitor expenditure survey was suspended during the pandemic border closures.")

    ryears = _full_remit_years(db)
    rp = _year_picker("Remittances by country (full year)", ryears,
                      ryears[-1] if ryears else None, "mac_rem_yr")
    d = _remittances_year(db, rp).nlargest(12, "value")
    d = d.assign(value=d["value"] / 1000)
    st.plotly_chart(_hbar_fig(d, pal["green"], "US$ mln", pal, name_fix=True),
                    use_container_width=True, theme=None, key="mac_rem")


def _full_remit_years(db):
    rem = cache.macro_series(db, "remittances_by_country", "month")
    if rem.empty:
        return []
    rem = rem[rem["breakdown"] != "TOTAL"].copy()
    rem["yr"] = rem["period"].str.slice(0, 4)
    months = rem.groupby("yr")["period"].nunique()
    full = sorted(months[months >= 12].index.tolist())
    return full or sorted(rem["yr"].unique())


def _remittances_year(db, yr):
    rem = cache.macro_series(db, "remittances_by_country", "month")
    rem = rem[(rem["breakdown"] != "TOTAL") & (rem["period"].str.slice(0, 4) == str(yr))]
    return rem.groupby("breakdown")["value"].sum().reset_index()


def _prices(db, hz, pal):
    st.markdown("##### Inflation & monetary policy")
    traces = [("Headline CPI", _ser(db, "cpi_yoy", "month", "TOTAL"), pal["orange"]),
              ("Core", _ser(db, "cpi_core_yoy", "month"), pal["blue"]),
              ("Policy rate", _ser(db, "policy_rate", "month"), pal["red"])]
    traces = [(n, _clip(d, hz, "month"), c) for n, d, c in traces if not d.empty]
    fig = _line_fig(traces, "%", pal)
    fig.add_hline(y=3.0, line_dash="dot", line_color=pal["faint"],
                  annotation_text="NBG target 3%", annotation_position="bottom left",
                  annotation_font=dict(color=pal["muted"], size=11))
    st.plotly_chart(fig, use_container_width=True, theme=None, key="mac_pr_infl")
    st.caption("Headline & core CPI (Geostat) and the NBG refinancing rate; dotted line = NBG's 3% "
               "inflation target.")

    st.markdown("##### Inflation — contribution by group (percentage points)")
    contrib, head = _inflation_contributions(db, rng=hz)
    if not contrib.empty:
        contrib, order = _fold_other(contrib, "g", "contrib", keep=7)  # ≤8 hues
        fig = _stack_fig(contrib, "period", "g", "contrib", pal, "pp", order=order)
        fig.add_scatter(x=head["period"], y=head["headline"], name="Headline CPI",
                        mode="lines", line=dict(color=pal["ink"], width=2.6),
                        hovertemplate="%{x}<br>Headline: %{y:.1f}%<extra></extra>")
        fig.update_yaxes(title_text="pp")
        st.plotly_chart(fig, use_container_width=True, theme=None, key="mac_pr_contrib")
        st.caption("Each group's share of the basket × its YoY inflation. Stacked bars sum to "
                   "the headline line — tall segments are what's actually driving inflation.")

    c1, c2 = st.columns([1, 1])
    with c1:
        wyears = _annual_years(db, "cpi_weights")
        wy = _year_picker("CPI basket weights", wyears,
                          wyears[-1] if wyears else None, "mac_pr_wt_yr")
        import plotly.express as px
        d = _top(db, "cpi_weights", wy, "annual", 12).copy()
        d["pct"] = d["value"] * 100
        fig = px.pie(d, names="breakdown", values="pct", hole=0.5,
                     color_discrete_sequence=pal["cat"])
        fig.update_traces(textposition="inside", textinfo="percent",
                          marker=dict(line=dict(color=pal["surface"], width=1.5)),
                          hovertemplate="%{label}<br>%{value:.1f}%<extra></extra>")
        fig.update_layout(height=_H, margin=dict(l=10, r=10, t=16, b=10),
                          paper_bgcolor=pal["surface"],
                          font=dict(family=_FONT, color=pal["ink"]), showlegend=True,
                          legend=dict(font=dict(size=10, color=pal["muted"])))
        st.plotly_chart(fig, use_container_width=True, theme=None, key="mac_pr_wt")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def render(ctx: ViewContext) -> None:
    db = ctx.db_path
    st.markdown("## Georgia — Macroeconomy")
    if not cache.has_macro_data(db):
        st.info("Macro datasets aren't present in this database yet. Run the macro "
                "importers (see `docs/macro-data-runbook.md`) to populate them.")
        return
    pal = _pal()
    # Render each chart on a solid surface (white in light mode) instead of the
    # transparent-on-grey default — cleaner, higher-contrast reading. Streamlit's
    # own plotly theme would overwrite the background, so charts pass theme=None
    # and we give the containers a rounded-card border here.
    _shadow = "rgba(0,0,0,0.06)" if pal["mode"] == "light" else "rgba(0,0,0,0.35)"
    st.markdown(
        f"""<style>
        div[data-testid="stPlotlyChart"] {{
            border: 1px solid {pal['grid']};
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 1px 4px {_shadow};
        }}
        </style>""",
        unsafe_allow_html=True,
    )
    cat = cache.macro_catalog(db)
    spans = cat["max_period"].dropna()
    st.caption(f"{len(cat)} datasets across GDP · Labour · External · Monetary — "
               f"API-sourced from Geostat & the National Bank of Georgia, cached in-app "
               f"(latest data up to {spans.max() if not spans.empty else '—'}).")

    _kpis(db)
    st.caption("Deltas are year-on-year — % for levels (GDP, per-capita, FDI), percentage points "
               "for rates; CPI & policy rate compare with the same month a year earlier.")
    st.divider()
    lo0, hi0 = _year_bounds(db)
    start0 = max(lo0, hi0 - (_HZ_DEFAULT_SPAN - 1))
    hc, _sp = st.columns([3, 4])
    with hc:
        hz = st.slider(
            "Year range", min_value=lo0, max_value=hi0, value=(start0, hi0),
            step=1, key="mac_hz",
            help="Start and end year applied to every time-series chart. Snapshot "
                 "charts (rankings, shares, weights) have their own year picker.")

    tabs = st.tabs(["Overview", "GDP", "Labour", "External sector", "Prices & money"])
    with tabs[0]:
        _overview(db, hz, pal)
    with tabs[1]:
        _gdp(db, hz, pal)
    with tabs[2]:
        _labour(db, hz, pal)
    with tabs[3]:
        _external(db, hz, pal)
    with tabs[4]:
        _prices(db, hz, pal)

    with st.expander("Dataset catalog & sources"):
        st.dataframe(cat, use_container_width=True, hide_index=True)
