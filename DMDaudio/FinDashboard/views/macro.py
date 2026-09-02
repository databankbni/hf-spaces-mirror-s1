"""Macro view — Georgia macro-economics dashboard.

Reads the cached ``macro_series`` / ``macro_dataset`` tables (API-sourced from
Geostat + NBG; see docs/macro-data-runbook.md) and renders a tabbed dashboard:
Overview · GDP · Labour · External sector · Prices & money. All charts are Plotly
with the app's transparent, theme-aware layout; data comes through ``lib.cache``
(mtime-invalidated). Degrades gracefully if the macro tables aren't in the DB.

Interactivity: a page-level **year-range** slider (pick start & end year) clips
every time-series chart; each **snapshot** chart (top-N rankings, shares, weights)
has a compact **year picker** defaulting to the latest complete year.

Two conventions run through the page:

* **Complete years only** on annual charts. Several Geostat/NBG annual series carry
  a row for the *current* year that is really year-to-date (trade, FDI by sector,
  tourism arrivals); plotted straight it reads as a collapsed final bar. ``_clip``
  caps every ``annual`` series at the last finished calendar year, and the snapshot
  year pickers offer the same set.
* **Shares and ratios, not levels**, wherever a level invites a false comparison:
  trade / FDI / current-account run as **% of GDP**, and every top-N ranking is a
  **share of its own total with an explicit "Other"** so nothing is silently
  dropped off the bottom of the chart.

Colour: the GCAP brand palette (``lib.theme.CHART_CATEGORICAL``), extended from six
to eight slots so a stack never leaves the brand set. Text, gridlines and the
"total" overlay lines follow the active light/dark theme (``lib.theme``) so nothing
goes invisible in dark mode.
"""
from __future__ import annotations

import datetime as _dt
import re

import pandas as pd
import streamlit as st

from lib import cache
from lib import theme as _theme
from views.shared import ViewContext

# GCAP brand categorical palette — the six hues of ``lib.theme.CHART_CATEGORICAL``
# plus two extra slots (sky, moss) so an eight-way stack stays inside the brand set.
# Graphite/ink is deliberately NOT in the run: it is reserved for the "total"
# overlay line drawn on top of stacks, which has to read as not-a-category.
# Slots: blue, gold, green, clay, plum, sky, moss, red.
_CAT_LIGHT = ["#3E6B8C", "#C8922E", "#1E7D5A", "#A6533F", "#6B4E7A", "#7FA8C9", "#8FA86B", "#B23A48"]
_CAT_DARK = ["#6FA8D8", "#E8B85C", "#2FA98A", "#D2876B", "#A892C0", "#9FC2DE", "#8FB07F", "#E5707E"]

# Sequential ramp for the choropleth, anchored on the brand slate-blue.
_SEQ_LIGHT = [[0.0, "#EDF2F6"], [0.5, "#7FA8C9"], [1.0, "#1F3F58"]]
_SEQ_DARK = [[0.0, "#1E2831"], [0.5, "#4E7FA6"], [1.0, "#BBD6EA"]]

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
    the GCAP brand categorical hues and named semantic handles into them.
    """
    mode = _theme.active_theme()
    t = _theme.tokens(mode)
    dark = mode == "dark"
    cat = _CAT_DARK if dark else _CAT_LIGHT
    return {
        "mode": mode, "ink": t["ink"], "muted": t["ink_muted"], "faint": t["ink_faint"],
        "grid": t["grid"], "zero": t["zero"], "surface": t["surface"], "cat": cat,
        "seq": _SEQ_DARK if dark else _SEQ_LIGHT,
        "blue": cat[0], "gold": cat[1], "green": cat[2], "clay": cat[3],
        "plum": cat[4], "sky": cat[5], "moss": cat[6], "red": cat[7],
    }


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _last_full_year() -> int:
    """The most recent finished calendar year.

    Annual charts stop here. Several sources publish a row for the *running* year
    that is really year-to-date — Geostat's trade tables (5 months of 2026 filed as
    "2026"), FDI by sector, tourism arrivals — and drawing it next to full years
    reads as a crash rather than a partial count.
    """
    return _dt.date.today().year - 1


def _ser(db, dataset, ptype, breakdown="TOTAL") -> pd.DataFrame:
    df = cache.macro_series(db, dataset, ptype)
    if df.empty:
        return df
    return df[df["breakdown"] == breakdown].sort_values("period")


def _hi_for(rng, ptype):
    """Upper year bound for ``ptype`` — annual series never run past a full year."""
    hi = rng[1] if rng else _dt.date.today().year
    return min(hi, _last_full_year()) if ptype == "annual" else hi


def _clip(df, rng, ptype=None):
    """Keep only rows whose year falls within the (start, end) ``rng`` tuple.

    Works for any period_type — the year is the first four chars of ``period``
    ('YYYY', 'YYYY-Qn', 'YYYY-MM'). ``ptype='annual'`` additionally drops the
    running year (see ``_last_full_year``); monthly/quarterly series keep it, which
    is the whole point of having them.
    """
    if df is None or df.empty:
        return df
    lo = rng[0] if rng else 0
    hi = _hi_for(rng, ptype)
    yrs = df["period"].astype(str).str.slice(0, 4).astype(int)
    return df[(yrs >= lo) & (yrs <= hi)]


def _clip_years(years, rng, ptype="annual"):
    """From a list of 'YYYY' strings, keep those inside the (start, end) ``rng``."""
    ys = sorted(set(years))
    lo = rng[0] if rng else 0
    hi = _hi_for(rng, ptype)
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


def _rank_with_other(db, dataset, period, n=10, exclude=("TOTAL",), other="Other"):
    """Top ``n`` breakdowns for one period + an explicit **Other** row, and the total.

    Every ranking on this page used to be a bare top-12 with the rest of the
    distribution simply absent, so a chart of 178 export partners looked like the
    whole picture. Here the tail is folded into one bar and the denominator comes
    from the dataset's own published ``TOTAL`` when it has one (FDI, tourism) —
    which also absorbs any coverage gap between the total and the parts.

    Returns ``(df[breakdown, value], total)``; ``total`` is None if it can't be
    established (then shares are meaningless and the caller should fall back).
    """
    df = cache.macro_series(db, dataset, "annual")
    if df.empty:
        return pd.DataFrame(columns=["breakdown", "value"]), None
    per = df[df["period"] == str(period)]
    published = per[per["breakdown"] == "TOTAL"]["value"]
    parts = per[~per["breakdown"].isin(exclude)].sort_values("value", ascending=False)
    if parts.empty:
        return pd.DataFrame(columns=["breakdown", "value"]), None
    total = float(published.iloc[0]) if not published.empty else float(parts["value"].sum())
    head = parts.head(n)[["breakdown", "value"]].copy()
    rest = total - float(head["value"].sum())
    if len(parts) > n or abs(rest) > 0.005 * abs(total or 1):
        head = pd.concat([head, pd.DataFrame([{"breakdown": other, "value": rest}])],
                         ignore_index=True)
    return head, total


def _n_breakdowns(db, dataset, period, exclude=("TOTAL",)) -> int:
    """How many categories the dataset actually carries for ``period`` — so a
    "top 10 of N" caption can be honest about what the Other bar is hiding."""
    df = cache.macro_series(db, dataset, "annual")
    if df.empty:
        return 0
    per = df[(df["period"] == str(period)) & (~df["breakdown"].isin(exclude))]
    return int(per["breakdown"].nunique())


def _product_dataset(db) -> str:
    """HS 4-digit export products if that dataset was imported, else SITC sections.

    The HS4 table (~1,140 headings) is the useful one, but it is the largest thing
    the trade importer pulls and an older DB may only have the 10 SITC sections.
    """
    hs4 = cache.macro_series(db, "exports_by_product_hs4", "annual")
    return "exports_by_product" if hs4.empty else "exports_by_product_hs4"


def _gdp_usd_map(db) -> dict:
    """{'YYYY': nominal GDP in mln USD} — the denominator for every % of GDP chart."""
    g = _ser(db, "gdp_usd", "annual")
    return {} if g.empty else dict(zip(g["period"].astype(str), g["value"]))


def _as_pct_of_gdp(df, gdp, scale):
    """Rescale ``df.value`` to % of nominal GDP, keeping the amount in ``amount``.

    ``scale`` converts the series' own unit into **mln USD** (thsd USD → 1/1000,
    plain USD → 1/1e6), which is the unit ``gdp_usd`` is published in.
    """
    d = df.copy()
    d["amount"] = d["value"] * scale
    yrs = d["period"].astype(str).str.slice(0, 4)
    d["gdp"] = [gdp.get(y) for y in yrs]
    d = d.dropna(subset=["gdp"])
    d["value"] = d["amount"] / d["gdp"] * 100.0
    return d


def _annual_years(db, dataset, complete_only=True):
    """Sorted 4-digit years ``dataset`` has annual data for (full years by default)."""
    df = cache.macro_series(db, dataset, "annual")
    if df.empty:
        return []
    ys = sorted(p for p in df["period"].unique() if re.fullmatch(r"\d{4}", str(p)))
    return [y for y in ys if int(y) <= _last_full_year()] if complete_only else ys


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


def _arrivals_by_region(db):
    """Visitor arrivals grouped into regions → (long df [period, region, value],
    region order by total). Uses the per-country annual arrivals + ISO-2 codes."""
    arr = cache.macro_series(db, "tourism_arrivals_by_country", "annual")
    if arr.empty:
        return pd.DataFrame(), []
    d = arr[(arr["breakdown"] != "TOTAL") & (arr["breakdown"] != "Georgia")].copy()
    d["region"] = [_region_of(i, n) for i, n in zip(d["sub_breakdown"], d["breakdown"])]
    g = d.groupby(["period", "region"])["value"].sum().reset_index()
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


def _current_account(db) -> pd.DataFrame:
    """Annual current account by component, as % of GDP **and** in US$ mln.

    NBG publishes the balance of payments quarterly in US$ (BPM6: Goods + Services
    + Primary income + Secondary income = the current-account balance, deficit
    negative). A year is only formed once **all four** of its quarters are filed —
    otherwise the running year lands as a shallow deficit that looks like a
    dramatic improvement. The denominator is Geostat's nominal GDP in USD
    (``gdp_usd``, mln USD), matching the numerator's currency and its year.

    Returns long rows ``[period, breakdown, amount (US$ mln), value (% of GDP)]``
    with ``breakdown='TOTAL'`` carrying the balance, so the components and the
    balance can be drawn against ONE axis with one shared zero — the earlier
    chart put components (US$ mln) and balance (% of GDP) on a dual axis whose
    two zero lines sat at different heights.
    """
    ca = cache.macro_series(db, "current_account", "quarter")
    gdp = _gdp_usd_map(db)
    if ca.empty or not gdp:
        return pd.DataFrame(columns=["period", "breakdown", "amount", "value"])
    d = ca.copy()
    d["period"] = d["period"].str.slice(0, 4)
    quarters = d[d["breakdown"] == "TOTAL"].groupby("period")["value"].size()
    full = set(quarters[quarters == 4].index)
    d = d[d["period"].isin(full) & d["period"].isin(gdp)]
    if d.empty:
        return pd.DataFrame(columns=["period", "breakdown", "amount", "value"])
    g = d.groupby(["period", "breakdown"], as_index=False)["value"].sum()
    g = g.rename(columns={"value": "amount"})
    g["value"] = [round(100.0 * a / gdp[p], 2) for p, a in zip(g["period"], g["amount"])]
    return g.sort_values(["period", "breakdown"])


def _annual_cpi_inflation(db) -> dict:
    """{year: mean of the 12 monthly YoY headline-CPI readings}."""
    y = cache.macro_series(db, "cpi_yoy", "month")
    if y.empty:
        return {}
    y = y[y["breakdown"] == "TOTAL"].copy()
    y["yr"] = y["period"].str.slice(0, 4)
    return y.groupby("yr")["value"].mean().to_dict()


def _real_wage_growth(db) -> pd.DataFrame:
    """Annual real wage growth = nominal wage growth (economy-wide) − CPI inflation.

    Reads the spliced headline (``wages_total``, 1998-) in preference to the
    Rev.2 sector table, which only starts in 2014 and so used to cut this line
    off at 2015 — the growth calculation eats the first year. CPI was never the
    constraint: ``cpi_yoy`` runs monthly from 2004, which is what now bounds the
    series at 2004 (22 years instead of 11). Falls back to the sector table's TOTAL on a database without the
    spliced dataset.
    """
    w = _ser(db, "wages_total", "annual", "TOTAL")
    if w.empty:
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


_NET_TAXES = "Net taxes on products (residual)"


def _gdp_structure(db, year):
    """Every production-side component of GDP for ``year``, as % of GDP.

    Geostat's activity rows are gross VALUE ADDED, which comes to ~87% of GDP —
    the balance is net taxes on products. The chart used to show the ten largest
    activities as "% of GDP", so ten of the twenty activities were missing *and*
    the visible shares stopped at ~63% with no way to see what the gap was. Here
    all twenty are kept and the tax wedge is added back as an explicit residual,
    so the bars are a complete decomposition summing to 100% of GDP.

    Returns ``(df[breakdown, value], gdp_mln_gel)`` sorted largest first, or
    ``(empty, None)``.
    """
    prod = cache.macro_series(db, "gdp_by_production", "annual")
    gdp = _ser(db, "gdp_nominal", "annual")
    gdp = gdp[gdp["period"] == str(year)]["value"]
    if prod.empty or gdp.empty or not gdp.iloc[0]:
        return pd.DataFrame(columns=["breakdown", "value"]), None
    total = float(gdp.iloc[0])
    d = prod[(prod["period"] == str(year)) & (prod["breakdown"] != "TOTAL")][
        ["breakdown", "value"]].copy()
    if d.empty:
        return pd.DataFrame(columns=["breakdown", "value"]), None
    d = pd.concat([d, pd.DataFrame([{"breakdown": _NET_TAXES,
                                     "value": total - float(d["value"].sum())}])],
                  ignore_index=True)
    d["amount"] = d["value"]
    d["value"] = d["amount"] / total * 100.0
    return d.sort_values("value", ascending=False), total


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


def _year_axis(fig):
    """Force an x-axis of years to render as discrete year labels.

    Plotly.js type-sniffs an axis, and an array of year *strings* ("2021", "2022")
    all parse as numbers — so it drew a linear axis and happily labelled the
    half-way ticks "2021.5". A category axis has no in-between position to label.
    """
    fig.update_xaxes(type="category", categoryorder="category ascending")
    return fig


def _bar_fig(df, name, color, unit, pal, height=_H):
    import plotly.graph_objects as go
    fig = go.Figure(go.Bar(x=df["period"].astype(str), y=df["value"], name=name,
                           marker_color=color,
                           hovertemplate="%{x}<br>%{y:,.1f} " + unit + "<extra></extra>"))
    return _year_axis(_layout(fig, pal, height, legend=False))


def _line_fig(traces, unit, pal, height=_H):
    """traces = [(name, df, color)] — or [(name, df, color, dash)]."""
    import plotly.graph_objects as go
    fig = go.Figure()
    for name, df, color, *rest in traces:
        dash = rest[0] if rest else None
        fig.add_trace(go.Scatter(
            x=df["period"], y=df["value"], name=name, mode="lines",
            line=dict(color=color, width=2.6, dash=dash),
            hovertemplate="%{x}<br>" + name + ": %{y:,.1f} " + unit + "<extra></extra>"))
    return _layout(fig, pal, height, legend=len(traces) > 1)


def _hbar_fig(df, color, unit, pal, height=_H, name_fix=False, pct=False, amounts=None):
    """Horizontal ranking bars: full category name (truncated on the axis, full on
    hover), the axis auto-sizes to fit it, and a direct value label at each bar end.

    ``amounts`` — an optional list of pre-formatted absolute figures aligned to
    ``df``'s rows — is carried into the hover, so a share chart can still answer
    "yes, but how much is that?" without giving up the axis to a level.
    """
    import plotly.graph_objects as go
    # Ascending, so the biggest sits at the top — except "Other", which is pinned to
    # the bottom whatever its size. It is a residual, not a competitor: leaving it in
    # the ranking put "Other" above real partners and read as a country.
    d = df.assign(_o=(df["breakdown"] == "Other")).sort_values(
        ["_o", "value"], ascending=[False, True]).drop(columns="_o")
    full = [_GEO_NAME_FIX.get(x, x) if name_fix else str(x) for x in d["breakdown"]]
    short = [s if len(s) <= 28 else s[:27] + "…" for s in full]
    num = "%{x:,.1f}" if pct else "%{x:,.0f}"
    txt = [f"{v:,.1f}" + ("%" if pct else "") if pct else f"{v:,.0f}" for v in d["value"]]
    if amounts is None:
        cdata = [[s] for s in full]
        hv = f"%{{customdata[0]}}<br>{num} {unit}<extra></extra>"
    else:
        amt = list(pd.Series(list(amounts), index=df.index).reindex(d.index))
        cdata = [[s, a] for s, a in zip(full, amt)]
        hv = f"%{{customdata[0]}}<br>{num} {unit} · %{{customdata[1]}}<extra></extra>"
    fig = go.Figure(go.Bar(
        x=d["value"], y=short, orientation="h", marker_color=color,
        text=txt, textposition="outside", textfont=dict(color=pal["muted"], size=11),
        cliponaxis=False, customdata=cdata, hovertemplate=hv))
    fig = _layout(fig, pal, height, legend=False, hover="closest")
    vmax = float(d["value"].max()) if len(d) else 1.0
    vmin = min(0.0, float(d["value"].min())) if len(d) else 0.0
    fig.update_xaxes(range=[vmin * 1.22, vmax * 1.22], showgrid=True)
    fig.update_yaxes(showgrid=False, automargin=True)  # expand left margin to fit labels
    fig.update_layout(margin=dict(r=64))               # room for the outside value labels
    return fig


def _share_hbar(df, total, color, pal, *, amount_fmt, height=_H, name_fix=False):
    """``_hbar_fig`` over shares: x = % of ``total``, amount preserved in the hover."""
    d = df.copy()
    amounts = [amount_fmt(v) for v in d["value"]]
    d["value"] = d["value"] / total * 100.0 if total else d["value"]
    return _hbar_fig(d, color, "% of total", pal, height=height, name_fix=name_fix,
                     pct=True, amounts=amounts)


def _stack_fig(df, x, color_col, y, pal, unit, order=None, height=_H, barmode="stack",
               pct=False, year_axis=True):
    """Stacked bar over `x`, one series per `color_col` value, with segment gaps.

    ``pct=True`` normalises each x to 100% (a share-of-mix chart) and puts the
    underlying amount in the hover.
    """
    import plotly.express as px
    d = df.copy()
    d[x] = d[x].astype(str)
    hover_amt = ""
    if pct:
        d["_amt"] = d[y]
        tot = d.groupby(x)[y].transform("sum")
        d[y] = d[y] / tot * 100.0
        hover_amt = " (%{customdata[0]:,.0f} " + unit + ")"
    fig = px.bar(d, x=x, y=y, color=color_col, barmode=barmode,
                 color_discrete_sequence=pal["cat"],
                 custom_data=["_amt"] if pct else None,
                 category_orders={color_col: order} if order else None)
    fig.update_traces(
        marker_line=dict(width=1, color=pal["surface"]),  # 1px surface gap between fills
        hovertemplate="%{x}<br>%{fullData.name}: %{y:,.1f} "
                      + ("%" if pct else unit) + hover_amt + "<extra></extra>")
    fig = _layout(fig, pal, height, legend=True)
    return _year_axis(fig) if year_axis else fig


def _add_total_labels(fig, totals, pal, fmt):
    """Print the stack total above each bar of a stacked chart.

    A stacked chart shows the mix but hides the level it is a mix *of*; these
    labels put the year's total back on the chart without a second axis.
    ``totals`` is an ordered {x: value} mapping.
    """
    import plotly.graph_objects as go
    vals = list(totals.values())
    fig.add_trace(go.Scatter(
        x=[str(k) for k in totals], y=vals, mode="text",
        text=[fmt(v) for v in vals], textposition="top center",
        textfont=dict(color=pal["muted"], size=11), showlegend=False,
        hoverinfo="skip", cliponaxis=False))
    if vals:  # headroom for the labels — Plotly's autorange only sees the bar tops
        fig.update_yaxes(range=[0, max(vals) * 1.12])
    return fig


# ---------------------------------------------------------------------------
# KPI row
# ---------------------------------------------------------------------------

def _kpis(db):
    """Headline levels, each stamped with the period it belongs to.

    No year-on-year deltas: the cards mixed frequencies (an annual level against a
    monthly rate) and each source's latest period lands at a different point in the
    year, so the printed change was not a like-for-like YoY and the macro desk read
    several of them as wrong. The period now rides in the card label instead, and
    the change over time is what every chart below this row is for.
    """
    def latest(dataset, ptype, breakdown="TOTAL", complete=False):
        df = _ser(db, dataset, ptype, breakdown)
        if df.empty:
            return None, None
        if complete and ptype == "annual":
            full = df[df["period"].str.fullmatch(r"\d{4}")
                      & (df["period"].astype(int) <= _last_full_year())]
            if not full.empty:
                df = full
        cur = df.iloc[-1]
        return cur["period"], cur["value"]

    def show(col, label, p, v, valfmt, help=None):
        col.metric(f"{label} · {p}" if p else label,
                   valfmt(v) if v is not None else "—", help=help)

    r1 = st.columns(4)
    show(r1[0], "Nominal GDP", *latest("gdp_nominal", "annual", complete=True),
         lambda v: f"₾{v/1000:,.1f}bn", help="GDP at current market prices (Geostat)")
    show(r1[1], "Real GDP growth", *latest("gdp_real_growth", "annual", complete=True),
         lambda v: f"{v:+.1f}%", help="Constant-price GDP, % on the year before")
    show(r1[2], "GDP per capita", *latest("gdp_per_capita_usd", "annual", complete=True),
         lambda v: f"${v:,.0f}", help="Nominal GDP per head, US$")
    show(r1[3], "Unemployment", *latest("unemployment_rate", "annual", complete=True),
         lambda v: f"{v:.1f}%", help="ILO definition, % of the labour force (LFS)")
    r2 = st.columns(4)
    show(r2[0], "Inflation (CPI)", *latest("cpi_yoy", "month"),
         lambda v: f"{v:.1f}%", help="Headline CPI, % on the same month a year earlier")
    show(r2[1], "Policy rate", *latest("policy_rate", "month"),
         lambda v: f"{v:.2f}%", help="NBG refinancing rate")
    show(r2[2], "FDI (net)", *latest("fdi_total", "annual", complete=True),
         lambda v: f"${v/1e9:.2f}bn", help="Net FDI inflows — sum of the year's four quarters")
    ca = _current_account(db)
    ca = ca[ca["breakdown"] == "TOTAL"]
    if not ca.empty:
        show(r2[3], "Current account", ca["period"].iloc[-1], ca["value"].iloc[-1],
             lambda v: f"{v:+.1f}%", help="Balance as % of GDP (NBG BPM6 ÷ Geostat GDP in USD)")
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
        st.plotly_chart(_year_axis(_layout(fig, pal)), use_container_width=True, theme=None,
                        key="mac_ov_gdp")
    with c2:
        st.markdown("##### Inflation & policy rate")
        fig = _prices_fig(db, hz, pal)
        st.plotly_chart(fig, use_container_width=True, theme=None, key="mac_ov_infl")
    st.caption("Dotted line = NBG's 3% inflation target. GDP bars are current-price ₾bn; "
               "real growth is on the right-hand % axis. Annual charts stop at the last "
               f"complete year ({_last_full_year()}); monthly series run to the latest reading.")


def _prices_fig(db, hz, pal):
    """Headline CPI, core CPI and the policy rate on one % axis.

    The policy rate gets the plum hue and a dashed stroke: it was previously a red
    that sat one step from the CPI orange, and at chart scale the two lines were
    hard to tell apart — it is also a different kind of series (a set rate, not a
    measured outcome), so the dash earns its keep.
    """
    traces = [("Headline CPI", _ser(db, "cpi_yoy", "month", "TOTAL"), pal["gold"], None),
              ("Core CPI", _ser(db, "cpi_core_yoy", "month"), pal["blue"], None),
              ("Policy rate", _ser(db, "policy_rate", "month"), pal["plum"], "dash")]
    traces = [(n, _clip(d, hz, "month"), c, s) for n, d, c, s in traces if not d.empty]
    fig = _line_fig(traces, "%", pal)
    fig.add_hline(y=3.0, line_dash="dot", line_color=pal["faint"],
                  annotation_text="NBG target 3%", annotation_position="bottom left",
                  annotation_font=dict(color=pal["muted"], size=11))
    return fig


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
                                 mode="lines+markers", line=dict(color=pal["green"], width=3),
                                 hovertemplate="%{x}<br>$%{y:,.0f}<extra></extra>"), secondary_y=True)
        fig.update_yaxes(title_text="₾bn", secondary_y=False)  # left axis owns the gridlines
        fig.update_yaxes(title_text="US$", secondary_y=True, showgrid=False, zeroline=False)
        st.plotly_chart(_year_axis(_layout(fig, pal)), use_container_width=True, theme=None,
                        key="mac_gdp_level")
    with c2:
        st.markdown("##### Real GDP growth (annual)")
        st.plotly_chart(_bar_fig(_clip(_ser(db, "gdp_real_growth", "annual"), hz, "annual"),
                                 "Real growth", pal["green"], "%", pal),
                        use_container_width=True, theme=None, key="mac_gdp_rg")

    st.markdown("##### Monthly GDP growth (rapid estimate)")
    mon = _clip(_ser(db, "gdp_monthly_growth", "month"), hz, "month")
    if not mon.empty:
        st.plotly_chart(_line_fig([("Monthly YoY", mon, pal["clay"])], "%", pal),
                        use_container_width=True, theme=None, key="mac_gdp_mon")
        st.caption("Best-effort — from Geostat's monthly rapid-estimate press release.")
    else:
        st.caption("Monthly rapid estimate not available.")

    pyears = _annual_years(db, "gdp_by_production")
    yr = _year_picker("What GDP is made of — every component, % of GDP", pyears,
                      _complete_year(db, "gdp_by_production"), "mac_gdp_prod_yr")
    struct, gtot = _gdp_structure(db, yr)
    if not struct.empty:
        st.plotly_chart(
            _hbar_fig(struct, pal["blue"], "% of GDP", pal, pct=True,
                      height=max(_H, 24 * len(struct) + 80),
                      amounts=[f"₾{a/1000:,.2f}bn" for a in struct["amount"]]),
            use_container_width=True, theme=None, key="mac_gdp_prod")
        st.caption(
            f"All {len(struct) - 1} NACE activities Geostat publishes, as a share of the ₾"
            f"{gtot/1000:,.1f}bn nominal GDP for {yr}. The activity rows are gross value "
            "added, which comes to ~87% of GDP; the balance is indirect taxes less "
            "subsidies on products, shown here as the residual bar so the decomposition "
            "closes at 100%.")

    st.markdown("##### Contributions to real GDP growth — by expenditure")
    df, tot = _expenditure_decomposition(db)
    if not df.empty:
        keep = _clip_years(df["period"].unique(), hz)
        df = df[df["period"].isin(keep)]
        tot = tot[tot["period"].isin(keep)]
        fig = go.Figure()
        for label, color in [("Consumption", pal["blue"]), ("Investment", pal["gold"]),
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
        st.plotly_chart(_year_axis(_layout(fig, pal)), use_container_width=True, theme=None,
                        key="mac_gdp_exp")
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
                                     mode="lines+markers", line=dict(color=pal["green"], width=2.8),
                                     hovertemplate="%{x}<br>%{y:+.1f}%<extra></extra>"))
        # No manual zero line — _layout draws the axis zero baseline in the darker ink.
        fig.update_yaxes(title_text="%")
        st.plotly_chart(_year_axis(_layout(fig, pal)), use_container_width=True, theme=None,
                        key="mac_lab_unemp")
        st.caption("Both in %. Real wage growth = economy-wide nominal wage growth − average "
                   "CPI inflation, and starts in 2004 because that is where the CPI series "
                   "does; the wage level itself is spliced back to 1998 from Geostat's "
                   "pre-NACE-Rev.2 table. The sector breakdown below cannot be spliced — the "
                   "two classifications differ — so it starts in 2014.")
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

    gdp = _gdp_usd_map(db)
    usd_mln = lambda v: f"US${v:,.0f} mln"

    # --- Trade -------------------------------------------------------------
    # As % of GDP, not US$ bn: Georgia's nominal GDP roughly doubled over the
    # window, so a rising import bar mostly restated the growth of the economy.
    # Against GDP the same bars answer the question actually being asked — how
    # open is the economy, and is the gap widening relative to what it earns?
    st.markdown("##### External trade & balance (% of GDP)")
    flows = [("Export", "Exports", pal["blue"]), ("Import", "Imports", pal["red"])]
    fig = go.Figure()
    for key, label, color in flows:
        d = _as_pct_of_gdp(_clip(_ser(db, "trade_flows_total", "annual", key), hz, "annual"),
                           gdp, 1 / 1000)
        fig.add_trace(go.Bar(
            x=d["period"], y=d["value"], name=label, marker_color=color,
            customdata=[[a] for a in d["amount"]],
            hovertemplate="%{x}<br>" + label + ": %{y:,.1f}% of GDP "
                          "(US$%{customdata[0]:,.0f} mln)<extra></extra>"))
    bal = _as_pct_of_gdp(_clip(_ser(db, "trade_flows_total", "annual", "Balance"), hz, "annual"),
                         gdp, 1 / 1000)
    fig.add_trace(go.Scatter(
        x=bal["period"], y=bal["value"], name="Trade balance", mode="lines+markers",
        line=dict(color=pal["ink"], width=3), customdata=[[a] for a in bal["amount"]],
        hovertemplate="%{x}<br>Balance: %{y:,.1f}% of GDP "
                      "(US$%{customdata[0]:,.0f} mln)<extra></extra>"))
    fig.update_layout(barmode="group")
    fig.update_yaxes(title_text="% of GDP")
    st.plotly_chart(_year_axis(_layout(fig, pal)), use_container_width=True, theme=None,
                    key="mac_ext_trade")
    st.caption("Goods trade only (Geostat customs data) against nominal GDP in USD — services, "
               "which run a large surplus, are in the current account below. Hover for the "
               "US$ amounts.")

    c1, c2 = st.columns(2)
    with c1:
        pyears = _annual_years(db, "exports_by_partner")
        tp = _year_picker("Exports by partner — share of exports", pyears,
                          _complete_year(db, "exports_by_partner"), "mac_ext_partner_yr")
        d, tot = _rank_with_other(db, "exports_by_partner", tp, n=10)
        if not d.empty:
            st.plotly_chart(_share_hbar(d, tot, pal["blue"], pal, name_fix=True,
                                        amount_fmt=lambda v: usd_mln(v / 1000)),
                            use_container_width=True, theme=None, key="mac_ext_partner")
            st.caption(f"Top 10 of {_n_breakdowns(db, 'exports_by_partner', tp)} destinations; "
                       "the rest are pooled into Other so the bars account for all "
                       f"US${tot/1000:,.0f} mln of {tp} exports.")
    with c2:
        prod_ds = _product_dataset(db)
        hyears = _annual_years(db, prod_ds)
        hp = _year_picker("Export products — share of exports", hyears,
                          _complete_year(db, prod_ds), "mac_ext_hs4_yr")
        d, tot = _rank_with_other(db, prod_ds, hp, n=10)
        if not d.empty:
            st.plotly_chart(_share_hbar(d, tot, pal["gold"], pal,
                                        amount_fmt=lambda v: usd_mln(v / 1000)),
                            use_container_width=True, theme=None, key="mac_ext_hs4")
            grain = "HS 4-digit headings" if prod_ds.endswith("hs4") else "SITC sections"
            st.caption(f"Top 10 of {_n_breakdowns(db, prod_ds, hp)} {grain}; everything else is "
                       "pooled into Other.")

    # --- Current account ---------------------------------------------------
    st.markdown("##### Current account — components & balance (% of GDP)")
    ca = _current_account(db)
    if not ca.empty:
        keep = set(_clip_years(ca["period"].unique(), hz))
        ca = ca[ca["period"].isin(keep)]
        fig = go.Figure()
        # One axis, one zero. Components and balance are both % of GDP now, so the
        # bars literally stack to the line; the old dual axis gave them separate
        # zeros at different heights and the line could sit inside a deficit stack.
        for comp, col in [("Goods", pal["red"]), ("Services", pal["blue"]),
                          ("Primary income", pal["plum"]), ("Secondary income", pal["green"])]:
            dd = ca[ca["breakdown"] == comp]
            fig.add_trace(go.Bar(
                x=dd["period"], y=dd["value"], name=comp, marker_color=col,
                marker_line=dict(width=1, color=pal["surface"]),
                customdata=[[a] for a in dd["amount"]],
                hovertemplate="%{x}<br>" + comp + ": %{y:+.1f}% of GDP "
                              "(US$%{customdata[0]:,.0f} mln)<extra></extra>"))
        tot = ca[ca["breakdown"] == "TOTAL"]
        fig.add_trace(go.Scatter(
            x=tot["period"], y=tot["value"], name="Current-account balance",
            mode="lines+markers", line=dict(color=pal["ink"], width=2.6),
            customdata=[[a] for a in tot["amount"]],
            hovertemplate="%{x}<br>Balance: %{y:+.1f}% of GDP "
                          "(US$%{customdata[0]:,.0f} mln)<extra></extra>"))
        fig.update_layout(barmode="relative")
        fig.update_yaxes(title_text="% of GDP")
        st.plotly_chart(_year_axis(_layout(fig, pal)), use_container_width=True, theme=None,
                        key="mac_ext_ca")
        st.caption("NBG balance of payments (BPM5, standard presentation — not the analytical "
                   "sheet, which reclassifies part of current transfers and runs a wider "
                   "deficit), ÷ Geostat nominal GDP in USD. Net Goods / Services / Primary & "
                   "Secondary income stack to the balance line; a year appears only once all "
                   "four of its quarters are filed.")

    # --- Foreign direct investment ----------------------------------------
    # Titled per column (like the exports pair above) rather than under one shared
    # section header, which left this pair's two charts on different lines.
    fyears = _annual_years(db, "fdi_by_country")
    fy = _head_row("Foreign direct investment (% of GDP)", "FDI by source country — share",
                   fyears, _complete_year(db, "fdi_by_country"), "mac_fdi_country_yr")
    c3, c4 = st.columns(2)
    with c3:
        fdi = _as_pct_of_gdp(_clip(_ser(db, "fdi_total", "annual"), hz, "annual"), gdp, 1 / 1e6)
        f = go.Figure(go.Bar(
            x=fdi["period"].astype(str), y=fdi["value"], marker_color=pal["green"],
            customdata=[[a] for a in fdi["amount"]],
            hovertemplate="%{x}<br>%{y:,.1f}% of GDP "
                          "(US$%{customdata[0]:,.0f} mln)<extra></extra>"))
        f.update_yaxes(title_text="% of GDP")
        st.plotly_chart(_year_axis(_layout(f, pal, legend=False)), use_container_width=True,
                        theme=None, key="mac_fdi_total")
        st.caption("Net FDI inflows against nominal GDP. The annual figure is the sum of the "
                   "year's four quarters — Geostat's own annual 'Total' column repeated Q1 for "
                   "2025 and understated that year roughly nine-fold.")
    with c4:
        d, tot = _rank_with_other(db, "fdi_by_country", fy, n=10)
        if not d.empty:
            st.plotly_chart(_share_hbar(d, tot, pal["blue"], pal, name_fix=True,
                                        amount_fmt=lambda v: usd_mln(v / 1e6)),
                            use_container_width=True, theme=None, key="mac_fdi_country")
            st.caption(f"Share of the US${tot/1e6:,.0f} mln net inflow in {fy}. FDI is a NET "
                       "figure, so a source country — or the pooled Other — can be negative "
                       "when disinvestment beats new money.")
    fsyears = _annual_years(db, "fdi_by_sector")
    fsy = _year_picker("FDI by sector — share of the year's inflow", fsyears,
                       _complete_year(db, "fdi_by_sector"), "mac_fdi_sector_yr")
    d, tot = _rank_with_other(db, "fdi_by_sector", fsy, n=10)
    if not d.empty:
        st.plotly_chart(_share_hbar(d, tot, pal["plum"], pal,
                                    amount_fmt=lambda v: usd_mln(v / 1e6)),
                        use_container_width=True, theme=None, key="mac_fdi_sector")

    # --- Tourism & remittances --------------------------------------------
    _tourism(db, hz, pal)


def _tourism(db, hz, pal):
    import plotly.express as px
    import plotly.graph_objects as go

    gdp = _gdp_usd_map(db)
    st.markdown("##### Where visitors come from")
    arr = cache.macro_series(db, "tourism_arrivals_by_country", "annual")
    if not arr.empty:
        years = _annual_years(db, "tourism_arrivals_by_country")
        yr = st.select_slider("Year", options=years, value=years[-1], key="mac_tour_year")
        d = arr[(arr["period"] == yr) & (arr["breakdown"] != "TOTAL") & (arr["breakdown"] != "Georgia")].copy()
        d["country"] = d["breakdown"].map(lambda x: _GEO_NAME_FIX.get(x, x))
        import numpy as np
        d["logv"] = np.log10(d["value"].clip(lower=1))
        # Geostat's TOTAL includes visitors of GEORGIAN citizenship (non-residents
        # coming home), which the map, the table and the region chart all exclude —
        # so quote the foreign-citizenship figure and name the difference rather
        # than printing a headline that none of the charts below it add up to.
        published = arr[(arr["period"] == yr) & (arr["breakdown"] == "TOTAL")]["value"]
        foreign = float(d["value"].sum())
        allciz = float(published.iloc[0]) if not published.empty else foreign
        extra = (f" — {allciz/1e6:,.2f}m counting the {(allciz-foreign)/1e3:,.0f}k arrivals of "
                 "Georgian citizenship, which the map and charts exclude"
                 if allciz > foreign else "")
        st.caption(f"{foreign/1e6:,.2f} million international visitors in {yr}, across "
                   f"{len(d):,} countries of citizenship{extra}.")
        map_col, tbl_col = st.columns([2, 1])
        with map_col:
            fig = px.choropleth(d, locations="country", locationmode="country names",
                                color="logv", color_continuous_scale=pal["seq"],
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
            tbl["Share"] = (tbl["Visits"] / foreign * 100).round(1) if foreign else None
            tbl.index = tbl.index + 1  # 1-based rank
            st.dataframe(tbl, height=_H, use_container_width=True,
                         column_config={
                             "Visits": st.column_config.NumberColumn("Visits", format="localized"),
                             "Share": st.column_config.NumberColumn("Share", format="%.1f%%")})

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### Arrivals by region (annual)")
        reg, order = _arrivals_by_region(db)
        if not reg.empty:
            keep = set(_clip_years(reg["period"].unique(), hz))
            reg = reg[reg["period"].isin(keep)].copy()
            reg["value"] = reg["value"] / 1000  # persons → thousands
            fig = _stack_fig(reg, "period", "region", "value", pal, "thsd visitors", order=order)
            # The stack shows the mix; without this the year's headline number — the
            # thing everyone actually quotes — was nowhere on the chart.
            totals = reg.groupby("period")["value"].sum().sort_index()
            _add_total_labels(fig, totals.to_dict(), pal, lambda v: f"{v/1000:,.2f}m")
            fig.update_yaxes(title_text="thsd visitors")
            st.plotly_chart(fig, use_container_width=True, theme=None, key="mac_tour_grp")
            st.caption("By country of citizenship, grouped into regions; the figure above each bar "
                       "is that year's total in millions. CIS excl. Russia = Armenia, Azerbaijan, "
                       "Belarus, Kazakhstan, Kyrgyzstan, Moldova, Tajikistan, Turkmenistan, "
                       "Uzbekistan, Ukraine — Russia is shown separately.")
    with c2:
        # The headline "tourism revenue" everyone quotes is the BoP travel CREDIT,
        # not Geostat's visitor-expenditure survey (which is below, for the mix).
        # The two are ~15-20% apart — US$4.69bn of travel credit in 2025 against a
        # ₾15.0bn ≈ US$5.5bn survey — and quoting the survey as "tourism revenue"
        # is what put this page at odds with the macro desk's deck.
        st.markdown("##### Tourism receipts (% of GDP)")
        rec = _as_pct_of_gdp(_clip(_ser(db, "tourism_receipts_bop", "annual"), hz, "annual"),
                             gdp, 1.0)
        if not rec.empty:
            f = go.Figure(go.Bar(
                x=rec["period"].astype(str), y=rec["value"], marker_color=pal["gold"],
                customdata=[[a] for a in rec["amount"]],
                hovertemplate="%{x}<br>%{y:,.1f}% of GDP "
                              "(US$%{customdata[0]:,.0f} mln)<extra></extra>"))
            f.update_yaxes(title_text="% of GDP")
            st.plotly_chart(_year_axis(_layout(f, pal, legend=False)), use_container_width=True,
                            theme=None, key="mac_tour_receipts")
            st.caption("Credit side of the balance-of-payments 'Travel' line (NBG) against "
                       "nominal GDP — the standard tourism-revenue measure. Hover for the US$ "
                       "amount.")
        else:
            st.caption("BoP travel receipts not present in this database — run "
                       "`scripts/import_nbg.py`.")

    c3, c4 = st.columns(2)
    with c3:
        st.markdown("##### Visitor spend mix (Geostat survey)")
        tr = cache.macro_series(db, "tourism_revenue", "annual")
        if not tr.empty:
            d = tr[tr["breakdown"] != "TOTAL"].copy()
            d["breakdown"] = d["breakdown"].map(lambda x: _SPEND_SHORT.get(x, x))
            keep = set(_clip_years(d["period"].unique(), hz))
            d = d[d["period"].isin(keep)]
            d, order = _fold_other(d[["period", "breakdown", "value"]], "breakdown", "value", keep=5)
            fig = _stack_fig(d, "period", "breakdown", "value", pal, "₾ mln", order=order, pct=True)
            fig.update_yaxes(title_text="% of spend", range=[0, 100])
            st.plotly_chart(fig, use_container_width=True, theme=None, key="mac_tour_rev")
            st.caption(
                "What visitors spend on, from Geostat's inbound-visitor survey (ages 15+). "
                "Shown as a mix, not a level: the survey grosses a monthly average up over "
                "twelve months and lands ~15-20% above the BoP travel receipts above, so the "
                "composition is the part worth reading. Not published by country. 2020–2021 "
                "are absent — the survey was suspended during the border closures.")
    with c4:
        ryears = _full_remit_years(db)
        rp = _year_picker("Remittances by country — share of the year's inflow", ryears,
                          ryears[-1] if ryears else None, "mac_rem_yr")
        d, tot = _remittances_year(db, rp, n=10)
        if not d.empty:
            st.plotly_chart(_share_hbar(d, tot, pal["green"], pal, name_fix=True,
                                        amount_fmt=lambda v: f"US${v/1000:,.0f} mln"),
                            use_container_width=True, theme=None, key="mac_rem")
            st.caption(f"NBG money-transfer inflows, {rp}: top 10 sources plus Other, together "
                       f"US${tot/1000:,.0f} mln.")


def _full_remit_years(db):
    rem = cache.macro_series(db, "remittances_by_country", "month")
    if rem.empty:
        return []
    rem = rem[rem["breakdown"] != "TOTAL"].copy()
    rem["yr"] = rem["period"].str.slice(0, 4)
    months = rem.groupby("yr")["period"].nunique()
    full = sorted(months[months >= 12].index.tolist())
    return full or sorted(rem["yr"].unique())


def _remittances_year(db, yr, n=10, other="Other"):
    """Top ``n`` remittance sources for ``yr`` + an Other row, and the year's total."""
    rem = cache.macro_series(db, "remittances_by_country", "month")
    rem = rem[rem["period"].str.slice(0, 4) == str(yr)]
    if rem.empty:
        return pd.DataFrame(columns=["breakdown", "value"]), None
    by = rem[rem["breakdown"] != "TOTAL"].groupby("breakdown")["value"].sum()
    published = rem[rem["breakdown"] == "TOTAL"]["value"].sum()
    total = float(published) if published else float(by.sum())
    d = by.sort_values(ascending=False).head(n).reset_index()
    rest = total - float(d["value"].sum())
    if len(by) > n or abs(rest) > 0.005 * abs(total or 1):
        d = pd.concat([d, pd.DataFrame([{"breakdown": other, "value": rest}])],
                      ignore_index=True)
    return d, total


def _prices(db, hz, pal):
    st.markdown("##### Inflation & monetary policy")
    st.plotly_chart(_prices_fig(db, hz, pal), use_container_width=True, theme=None,
                    key="mac_pr_infl")
    st.caption("Headline & core CPI (Geostat) and the NBG refinancing rate — the rate is dashed "
               "and in plum so it doesn't read as a third inflation series; dotted line = NBG's "
               "3% inflation target.")

    st.markdown("##### Inflation — contribution by group (percentage points)")
    contrib, head = _inflation_contributions(db, rng=hz)
    if not contrib.empty:
        contrib, order = _fold_other(contrib, "g", "contrib", keep=7)  # ≤8 hues
        fig = _stack_fig(contrib, "period", "g", "contrib", pal, "pp", order=order,
                         year_axis=False)
        fig.add_scatter(x=head["period"], y=head["headline"], name="Headline CPI",
                        mode="lines", line=dict(color=pal["ink"], width=2.6),
                        hovertemplate="%{x}<br>Headline: %{y:.1f}%<extra></extra>")
        fig.update_yaxes(title_text="pp")
        st.plotly_chart(fig, use_container_width=True, theme=None, key="mac_pr_contrib")
        st.caption("Each group's share of the basket × its YoY inflation. Stacked bars sum to "
                   "the headline line — tall segments are what's actually driving inflation.")

    c1, c2 = st.columns([1, 1])
    with c1:
        # The basket year runs ahead of the last complete data year — Geostat
        # publishes the current year's weights in January — so this picker keeps it.
        wyears = _annual_years(db, "cpi_weights", complete_only=False)
        wy = _year_picker("CPI basket weights", wyears,
                          wyears[-1] if wyears else None, "mac_pr_wt_yr")
        import plotly.express as px
        d, _tot = _rank_with_other(db, "cpi_weights", wy, n=7)
        d = d.copy()
        d["breakdown"] = d["breakdown"].map(lambda x: _COICOP_SHORT.get(x, x))
        d["pct"] = d["value"] * 100
        fig = px.pie(d, names="breakdown", values="pct", hole=0.5,
                     color_discrete_sequence=pal["cat"])
        fig.update_traces(textposition="inside", textinfo="percent", sort=False,
                          marker=dict(line=dict(color=pal["surface"], width=1.5)),
                          hovertemplate="%{label}<br>%{value:.1f}% of the basket<extra></extra>")
        fig.update_layout(height=_H, margin=dict(l=10, r=10, t=16, b=10),
                          paper_bgcolor=pal["surface"],
                          font=dict(family=_FONT, color=pal["ink"]), showlegend=True,
                          legend=dict(font=dict(size=10, color=pal["muted"])))
        st.plotly_chart(fig, use_container_width=True, theme=None, key="mac_pr_wt")
        st.caption("Seven largest COICOP groups plus Other — the full basket, so the ring is "
                   "100% of consumer spend.")


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
    st.caption(f"{len(cat)} datasets across GDP · Labour · External · Monetary — "
               f"API-sourced from Geostat & the National Bank of Georgia, cached in-app "
               f"(latest reading {cache.macro_latest_period(db) or '—'}).")

    _kpis(db)
    st.caption("Each card is a level stamped with the period it comes from — the sources land on "
               "different calendars (annual GDP, monthly CPI), so a single year-on-year figure "
               "across the row would not be like-for-like. Trends are in the charts below.")
    st.divider()
    lo0, hi0 = _year_bounds(db)
    start0 = max(lo0, _last_full_year() - (_HZ_DEFAULT_SPAN - 1))
    hc, _sp = st.columns([3, 4])
    with hc:
        hz = st.slider(
            "Year range", min_value=lo0, max_value=hi0, value=(start0, hi0),
            step=1, key="mac_hz",
            help=f"Start and end year applied to every time-series chart. Annual charts stop at "
                 f"{_last_full_year()} (the last complete year) whatever the end year; monthly "
                 f"and quarterly series run on. Snapshot charts (rankings, shares, weights) have "
                 f"their own year picker.")

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
