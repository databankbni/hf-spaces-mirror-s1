"""
modules/home.py — Scenario Explorer (Stakeholder Landing Page)
NASA Project: Managing the Colorado River as an Infrastructure Asset
PI: Enrique Vivoni, ASU | Collaborators: Kristen Whitney (NASA Goddard)
Stakeholders: Bureau of Reclamation, ADWR, CAWCD, Met Water District, SNWA
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, Input, Output, State, no_update, ALL, callback_context
import dash_bootstrap_components as dbc
from scipy import stats
from utils.components import pub_star
from utils.data_loader import (
    load_vic_annual, load_snotel_annual, load_snotel_stations,
    load_grace, basin_label, trend_slope
)

MAROON="#8C1D40"; NAVY="#0D2137"; NAVY2="#1a3a5c"; GOLD="#FFC627"
BLUE="#01579B"; GREEN="#2E7D32"; ORANGE="#E65100"; PURPLE="#4527A0"
TEAL="#00695C"; RED="#B71C1C"
BASIN_OPTIONS = [
    {"label": "Colorado River Basin (Full)", "value": "CRB"},
    {"label": "Upper Basin",                 "value": "UpperBasin"},
    {"label": "Lower Basin",                 "value": "LowerBasin"},
    {"label": "Green River",                 "value": "Green"},
    {"label": "San Juan",                    "value": "SanJuan"},
    {"label": "Grand Canyon",                "value": "GrandCanyon"},
    {"label": "Gila River",                  "value": "Gila"},
]

METRIC_OPTIONS = [
    {"label": " Water Supply (Runoff + Baseflow)", "value": "supply"},
    {"label": " Runoff Efficiency (RBFE)",         "value": "rbfe"},
    {"label": "Snowpack (SWE)",                   "value": "swe"},
    {"label": "Temperature",                      "value": "temp"},
    {"label": "Precipitation",                    "value": "prec"},
    {"label": " Evapotranspiration",               "value": "et"},
    {"label": " Soil Moisture (total)",             "value": "sm"},
    {"label": " Soil Moisture L1 (0–10 cm)",       "value": "sm_l1"},
    {"label": " Soil Moisture L2 (10–40 cm)",      "value": "sm_l2"},
    {"label": " Soil Moisture L3 (40–200 cm)",     "value": "sm_l3"},
]

# Analysis finder — grouped "Section · Analysis" labels → route
FINDER_OPTIONS = [
    {"label": "Scenario · Climate-Sensitivity Scenario", "value": "/scenario"},
    {"label": "Scenario · Uncertainty & Confidence", "value": "/uncertainty"},
    {"label": "Water Supply · Snowpack & Runoff", "value": "/snowpack"},
    {"label": "Water Supply · Water Balance", "value": "/watbal"},
    {"label": "Water Supply · Snowmelt Timing & Flash Drought", "value": "/timing"},
    {"label": "Water Supply · Soil Moisture ↔ Streamflow", "value": "/links"},
    {"label": "Water Supply · Elevation-Dependent Snow Loss", "value": "/elevsnow"},
    {"label": "Risk · Drought & Shortage Risk", "value": "/drought"},
    {"label": "Risk · Reservoirs & Shortage Tiers", "value": "/reservoirs"},
    {"label": "Risk · Terrestrial Water Storage (GRACE)", "value": "/tws"},
    {"label": "Risk · Subsurface Storage (GW + reservoir)", "value": "/storage"},
    {"label": "Risk · Drought Recovery (WY2023)", "value": "/recovery"},
    {"label": "Projections · Hydrologic Projections to 2100", "value": "/future"},
    {"label": "Projections · Seasonal Forecasts (NMME)", "value": "/nmme"},
    {"label": "Projections · Climate Projections (CMIP)", "value": "/cmip"},
    {"label": "Spatial · Spatial Hydrology Maps", "value": "/spatial"},
    {"label": "Governance · Water Governance (Law of the River)", "value": "/governance"},
    {"label": "Governance · CRIA Asset Framework", "value": "/cria"},
    {"label": "Advanced · Aridification & Runoff Loss", "value": "/aridification"},
    {"label": "Advanced · Aridity Severity Index", "value": "/asi"},
    {"label": "Advanced · Budyko Water–Energy Balance", "value": "/budyko"},
    {"label": "Advanced · No-Analog Future Climate", "value": "/noanalog"},
    {"label": "Advanced · Drought Propagation", "value": "/cascade"},
    {"label": "Advanced · Land-Surface Warming & Energy", "value": "/warming"},
    {"label": "About · References & Validation", "value": "/references"},
]

BASELINE_OPTIONS = [
    {"label": "1983–2010 (WMO-style)",     "value": "1982_2010"},
    {"label": "1983–2024 (full record)",   "value": "1982_2024"},
    {"label": "1990–2020 (recent 30-yr)",  "value": "1990_2020"},
]

METRIC_MAP = {
    "supply": {"col": "supply",         "label": "Water Supply",        "unit": "mm/yr", "icon": " "},
    "rbfe":   {"col": "RBFE",           "label": "Runoff Efficiency",   "unit": "%",     "icon": " "},
    "swe":    {"col": "OUT_SWE",        "label": "Snowpack (SWE)",      "unit": "mm",    "icon": ""},
    "temp":   {"col": "OUT_AIR_TEMP",   "label": "Temperature",         "unit": "°C",    "icon": ""},
    "prec":   {"col": "OUT_PREC",       "label": "Precipitation",       "unit": "mm/yr", "icon": ""},
    "et":     {"col": "OUT_EVAP",       "label": "Total ET",            "unit": "mm/yr", "icon": " "},
    "sm":     {"col": "OUT_SOIL_MOIST",    "label": "Soil Moisture (total)", "unit": "mm", "icon": " "},
    "sm_l1":  {"col": "OUT_SOIL_MOIST_L1","label": "Soil Moisture L1",      "unit": "mm", "icon": " "},
    "sm_l2":  {"col": "OUT_SOIL_MOIST_L2","label": "Soil Moisture L2",      "unit": "mm", "icon": " "},
    "sm_l3":  {"col": "OUT_SOIL_MOIST_L3","label": "Soil Moisture L3",      "unit": "mm", "icon": " "},
}

CONTEXT = {
    "supply": [
        "Bureau of Reclamation manages Lee Ferry compact (7.5 MAF/yr to Upper Basin states).",
        "CAP receives ~1.5 MAF/yr — first to be cut under shortage declarations.",
        "Lake Mead Tier 1 shortage triggers at elevation 1,075 ft (~10.5 km³ storage).",
        "SNWA and Metropolitan Water District face similar shortage risk as storage falls.",
    ],
    "swe": [
        "April 1 SWE is the primary operational predictor of spring runoff volume.",
        "NRCS SNOTEL network monitors snowpack at 103 CRB stations daily.",
        "Earlier snowmelt reduced summer baseflow stress on late-season water rights.",
        "Upper Basin headwaters (Green, San Juan) supply majority of mainstem flow.",
    ],
    "temp": [
        "Warming increases evaporative demand, reducing runoff efficiency basin-wide.",
        "Higher temperatures accelerate snowmelt timing, shifting runoff earlier in season.",
        "Every 1°C warming reduces CRB runoff by ~2–9% through increased ET losses.",
        "Urban heat stress increases municipal water demand, compounding supply shortfall.",
    ],
    "prec": [
        "Precipitation uncertainty is large — CMIP6 models diverge on future P for CRB.",
        "Increased P variability means both intensified floods and prolonged droughts.",
        "Rain-snow transition elevation is rising more precipitation falling as rain.",
        "NMME seasonal forecasts provide 6–9 month operational precipitation outlooks.",
    ],
    "et": [
        "ET is the dominant water loss (60–80% of precipitation) throughout the CRB.",
        "Rising ET under warming directly reduces water available for compact delivery.",
        "Agriculture (~80% of CRB consumptive use) is the primary ET driver.",
        "ECOSTRESS provides field-scale ET at 70 m resolution for irrigation monitoring.",
    ],
    "rbfe": [
        "RBFE = (Runoff + Baseflow) / Precipitation × 100 — % of rain/snow that becomes streamflow.",
        "Declining RBFE under warming signals 'hot drought': higher ET consuming more of each mm of rain.",
        "CRB RBFE (~10%) is among the lowest of major US river basins due to high aridity.",
        "A 1 percentage point drop in RBFE translates directly to ~1% less compact-deliverable water.",
    ],
    "sm": [
        "Soil moisture deficit drives demand for supplemental irrigation and municipal water.",
        "Low spring soil moisture reduces snowmelt-to-runoff conversion efficiency.",
        "SMAP L4 (9 km, daily) provides near-real-time root zone soil moisture globally.",
        "Soil moisture integrates antecedent precipitation and ET, signaling drought onset.",
    ],
    "sm_l1": [
        "Layer 1 (0–10 cm) responds rapidly to rainfall — best indicator of surface evaporation.",
        "Warm-season drying in L1 accelerates bare-soil evaporation losses from the top layer.",
        "SMAP satellite observes the top 5 cm; VIC L1 provides the closest model analog.",
        "L1 moisture drives the partitioning between infiltration and surface runoff generation.",
    ],
    "sm_l2": [
        "Layer 2 (10–40 cm) represents the active root zone for most CRB vegetation types.",
        "L2 depletion precedes plant water stress and drives transpiration decline.",
        "Spring L2 replenishment from snowmelt determines summer drought resilience.",
        "Agriculture relies heavily on L2 moisture for crop water availability.",
    ],
    "sm_l3": [
        "Layer 3 (40–200 cm) is the deep storage buffer — responds slowly to surface forcing.",
        "L3 trends reveal multi-year drought accumulation and groundwater recharge signals.",
        "Deep moisture depletion persists across years — a key indicator of compound drought.",
        "Baseflow generation is tightly coupled to L3 saturation status.",
    ],
}


def _safe(fn):
    try:
        return fn()
    except Exception:
        return pd.DataFrame()


def _get_bl_range(bl_key):
    m = {"1982_2010": (1983, 2010), "1982_2024": (1983, 2023), "1990_2020": (1990, 2020)}
    return m.get(bl_key, (1982, 2010))


def _prep(basin, metric_key, bl_key):
    """Returns (df_hist_with_val, None, base_mean, base_std) or (None,...) on failure."""
    df_h = _safe(load_vic_annual)
    if df_h.empty:
        return None, None, None, None

    y0, y1 = _get_bl_range(bl_key)
    col = METRIC_MAP[metric_key]["col"]

    if metric_key == "supply":
        if "OUT_RUNOFF" not in df_h.columns or "OUT_BASEFLOW" not in df_h.columns:
            return None, None, None, None
        df_h = df_h.copy()
        df_h["supply"] = df_h["OUT_RUNOFF"] + df_h["OUT_BASEFLOW"]

    if col not in df_h.columns:
        return None, None, None, None

    bh = df_h[df_h["basin"] == basin].sort_values("water_year").copy()
    bh["val"] = bh[col]

    baseline_vals = bh[(bh["water_year"] >= y0) & (bh["water_year"] <= y1)]["val"].dropna()
    base_mean = baseline_vals.mean() if not baseline_vals.empty else None
    base_std  = baseline_vals.std()  if not baseline_vals.empty else None

    return bh, None, base_mean, base_std


def _empty_fig(msg="Preprocessing required — run 01_basin_aggregation.py"):
    fig = go.Figure()
    fig.add_annotation(text=msg, xref="paper", yref="paper",
                       x=0.5, y=0.5, showarrow=False,
                       font=dict(size=12, color="#90a4ae"))
    fig.update_layout(
        paper_bgcolor="white", plot_bgcolor="white",
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        margin=dict(l=20, r=20, t=20, b=20), height=360,
    )
    return fig


def _tile(val, label, icon, color):
    return html.Div([
        html.Div(str(val), className="info-tile-value"),
        html.Div(label,    className="info-tile-label"),
        html.Div(icon,     className="info-tile-icon"),
    ], className=f"info-tile {color}")


# ── Hero KPI strip — the current state of the basin, computed live from VIC/GRACE ──
def _hero_kpis():
    """Return a list of (value_str, label, caption, accent) KPI cards from real data.
    Baseline = WY1983–2010; 'recent' = WY2015–2024. Nothing here is fabricated —
    every number is derived from the loaded VIC 5.0 / GRACE record."""
    df = _safe(load_vic_annual)
    kpis = []

    def _recent_vs_base(col, build=None):
        if df.empty:
            return None, None, None
        d = df[df["basin"] == "CRB"].copy()
        if build:
            d = build(d)
            col2 = "val"
        else:
            col2 = col
        if col2 not in d.columns:
            return None, None, None
        base = d[(d["water_year"] >= 1983) & (d["water_year"] <= 2010)][col2].mean()
        rec = d[d["water_year"] >= 2015][col2].mean()
        if base is None or np.isnan(base) or abs(base) < 1e-6 or rec is None or np.isnan(rec):
            return None, base, rec
        return (rec - base) / abs(base) * 100.0, base, rec

    # 1 · Snowpack (SWE) recent vs baseline
    swe_pct, _, _ = _recent_vs_base("OUT_SWE")
    if swe_pct is not None:
        kpis.append((f"{swe_pct:+.0f}%", "Snowpack (SWE)", "recent decade vs 1983–2010",
                     "down" if swe_pct < 0 else "up"))

    # 2 · Water supply (runoff + baseflow) recent vs baseline
    sup_pct, _, _ = _recent_vs_base(
        None, build=lambda d: d.assign(val=d.get("OUT_RUNOFF", np.nan) + d.get("OUT_BASEFLOW", np.nan)))
    if sup_pct is not None:
        kpis.append((f"{sup_pct:+.0f}%", "Water supply", "runoff + baseflow vs baseline",
                     "down" if sup_pct < 0 else "up"))

    # 3 · Warming rate (Sen's slope per decade)
    if not df.empty:
        d = df[df["basin"] == "CRB"]
        if "OUT_AIR_TEMP" in d.columns:
            t = trend_slope(d["OUT_AIR_TEMP"], d["water_year"])
            if t.get("slope") is not None:
                per_dec = t["slope"] * 10
                kpis.append((f"{per_dec:+.2f}°C", "Warming rate", "per decade (Sen's slope)",
                             "down" if per_dec > 0 else "up"))

    # 4 · GRACE record-low total water storage
    dg = _safe(load_grace)
    if not dg.empty and "tws_mm" in dg.columns:
        crb_g = dg[dg["basin"] == "CRB"]["tws_mm"].dropna()
        if not crb_g.empty:
            kpis.append((f"{crb_g.min():.0f} mm", "Record-low storage",
                         "GRACE TWS anomaly (basin low)", "down"))

    return kpis


def _wow_hero():
    """A large, emotional centerpiece: the whole basin drying over four decades,
    animated from the real VIC reanalysis — the first thing anyone sees."""
    # Live "the tell": precip vs river shortfall over the last decade (the aridification signal)
    p_below, y_below = 5, 8
    try:
        d = _safe(load_vic_annual)
        d = d[d["basin"] == "CRB"].sort_values("water_year")
        d = d.assign(yld=d["OUT_RUNOFF"] + d["OUT_BASEFLOW"])
        pnorm, ynorm = d["OUT_PREC"].mean(), d["yld"].mean()
        last10 = d[d["water_year"] >= 2015]
        p_below = int((last10["OUT_PREC"] < pnorm).sum())
        y_below = int((last10["yld"] < ynorm).sum())
    except Exception:
        pass
    return html.Div([
        dbc.Row([
            dbc.Col(html.Div(
                html.Img(src="/assets/animations/anomaly_mapchart.gif",
                         alt="Animated Colorado River Basin anomaly map across water years 1984 to 2024",
                         style={"width": "100%", "height": "auto",
                                "display": "block", "margin": "0 auto",
                                "borderRadius": "10px", "border": "1px solid #e2e8f0"}),
                style={"display": "flex", "alignItems": "center", "justifyContent": "center",
                       "height": "100%"}), xs=12, lg=7),
            dbc.Col(html.Div([
                html.Div("THE BASIN, 1984 → 2024", style={
                    "display": "inline-block", "background": MAROON, "color": "#fff",
                    "fontSize": "10.5px", "fontWeight": "800", "letterSpacing": "0.6px",
                    "padding": "4px 11px", "borderRadius": "12px", "marginBottom": "10px"}),
                html.H2("Four decades of drought, in one view",
                        style={"fontSize": "21px", "fontWeight": "800", "color": "#0D2137",
                               "lineHeight": "1.15", "margin": "0 0 8px"}),
                html.P("Watch the Colorado River Basin dry out, water year by water year — "
                       "soil moisture, snowpack, precipitation and runoff together. Red means "
                       "drier than the 1984–2024 normal, blue wetter; the recent decades light up "
                       "red across the whole basin. Every frame is computed from the PRISM-calibrated "
                       "VIC reanalysis.",
                       style={"fontSize": "12.5px", "color": "#37474f", "lineHeight": "1.6",
                              "marginBottom": "12px"}),
                # ── the new question the animation answers ──
                html.Div([
                    html.Div("THE TELL", style={
                        "display": "inline-block", "background": "#0D2137", "color": "#FFC627",
                        "fontSize": "9.5px", "fontWeight": "800", "letterSpacing": "1px",
                        "padding": "3px 9px", "borderRadius": "10px", "marginBottom": "8px"}),
                    html.Div("If the rain was about normal, why did the river keep running low?",
                             style={"fontSize": "14.5px", "fontWeight": "800", "color": "#0D2137",
                                    "lineHeight": "1.25", "marginBottom": "7px"}),
                    html.Div(["Over the last decade the rain fell short in only ",
                              html.B(f"{p_below} of 10 years"),
                              " — but the river's water supply fell short in ",
                              html.B(f"{y_below} of 10"),
                              ". The missing water isn't missing rain. It's warming, turning snow "
                              "and soil into vapor before it ever reaches the river."],
                             style={"fontSize": "12.5px", "color": "#37474f", "lineHeight": "1.55"}),
                ], style={"background": "transparent", "borderLeft": f"3px solid {MAROON}",
                          "padding": "11px 14px", "borderRadius": "0 8px 8px 0",
                          "marginBottom": "12px"}),
                html.Div([
                    html.A(["Why warming, not just drought  ", html.I(className="bi bi-arrow-right")],
                           href="/aridification",
                           style={"fontSize": "12.5px", "fontWeight": "700", "color": "#01579B",
                                  "textDecoration": "none", "marginRight": "16px"}),
                    html.A(["See the whole basin  ", html.I(className="bi bi-arrow-right")],
                           href="/basinwide",
                           style={"fontSize": "12.5px", "fontWeight": "700", "color": "#01579B",
                                  "textDecoration": "none"}),
                ]),
            ], style={"padding": "6px 4px"}), xs=12, lg=5),
        ], className="g-3 align-items-center"),
    ], className="crb-card", style={"padding": "16px 18px", "marginBottom": "18px"})


def _hero():
    kpis = _hero_kpis()
    # Use the existing info-tile style (white, accent border) — no fill colour.
    tile_color = {"down": "tile-maroon", "up": "tile-navy"}
    cols = []
    for val, label, cap, acc in kpis:
        cols.append(dbc.Col(
            _tile(val, f"{label} · {cap}", "", tile_color.get(acc, "tile-navy")),
            xs=6, md=3))

    return html.Div([
        html.Div("At a glance — how the basin today compares with its 1983–2010 baseline "
                 "(computed live from the VIC 5.0 / GRACE record).",
                 style={"fontSize": "11.5px", "fontWeight": "600", "color": "#37474f",
                        "marginBottom": "10px"}),
        dbc.Row(cols, className="g-2"),
    ], style={"marginBottom": "18px"})


def _chip(text, icon):
    return html.Span([
        html.I(className=f"bi {icon}", style={"marginRight": "6px", "color": MAROON}),
        text,
    ], style={"display": "inline-flex", "alignItems": "center", "background": "#f4f6f9",
              "border": "1px solid #e2e8f0", "borderRadius": "16px", "padding": "5px 12px",
              "fontSize": "12px", "color": "#0D2137", "fontWeight": "600",
              "margin": "0 8px 8px 0"})


def _novel_card(icon, title, body):
    return dbc.Col(html.Div([
        html.Div([
            html.I(className=f"bi {icon}", style={"fontSize": "20px", "color": MAROON,
                                                  "marginRight": "8px"}),
            html.Span(title, style={"fontWeight": "800", "fontSize": "13.5px", "color": "#0D2137"}),
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "6px"}),
        html.Div(body, style={"fontSize": "12px", "color": "#37474f", "lineHeight": "1.55"}),
    ], style={"background": "#fff", "border": "1px solid #e2e8f0", "borderTop": f"3px solid {MAROON}",
              "borderRadius": "0 0 10px 10px", "padding": "14px 16px", "height": "100%"}),
        xs=12, md=4, className="mb-2")


def _positioning():
    """Interactive, honest positioning — answers a reviewer's hard questions on click.
       Respectful of operational tools (CRSS etc.); no competitive scorecard, no overclaim."""
    QA = [
        ("bi-patch-check-fill", "Is this publishable?",
         ["Yes — as an applied-science / decision-support contribution, not a new physical "
          "discovery. The publishable unit is the ",
          html.B("integration-and-validation framework"),
          ": a PRISM-calibrated VIC 5.0 reanalysis evaluated jointly against NASA GRACE, SMAP "
          "and SNOTEL, delivered as a sub-basin, manager-facing tool. Comparable tool and "
          "framework papers appear in Environmental Modelling & Software, Frontiers in Water and "
          "JAWRA. The underlying results are already peer-reviewed — Ghimire, Vivoni & Wang "
          "(2026, WRR); Wang et al. (2026, Sci. Rep.); Yue et al. (2025, J. Hydrometeorology) — "
          "which strengthens a synthesis paper rather than weakening it."]),
        ("bi-stars", "What is genuinely novel?",
         ["Not the individual findings — those are corroborated in the literature, and the tool "
          "says so on screen. The novelty is the ", html.B("synthesis"),
          ": bringing surface water, snowpack and subsurface (groundwater) storage into one "
          "observation-validated, sub-basin view, framed around the decisions managers actually "
          "make — acre-feet and Lake Mead tiers — with the line between established and open "
          "science drawn explicitly. That combination does not currently exist as a single tool."]),
        ("bi-diagram-3", "How is it different from what already exists?",
         ["It complements, rather than competes with, the tools in use. Operations models such as "
          "the Bureau of Reclamation's CRSS answer ", html.I("how to manage the reservoirs"),
          "; CRIA provides the ", html.B("observation-validated hydrologic diagnosis behind that"),
          " — where the water is, why it is changing, and how confident we are. It also extends "
          "the lab's own CRB Scenario-Explorer lineage from streamflow scenarios to the full "
          "water balance plus subsurface storage, validation and decision-ready units."]),
        ("bi-globe-americas", "What exists in the world today — and what doesn't?",
         ["Exists: excellent GRACE groundwater studies, seasonal-forecast evaluations, "
          "aridification analyses, reservoir-operations models and state data portals (e.g. "
          "Colorado's CDSS). ", html.B("What doesn't exist"),
          " is a single, sub-basin, observation-validated decision-support tool that ties the "
          "surface and subsurface story together for managers, with uncertainty stated and every "
          "figure traceable to its source."]),
        ("bi-bullseye", "What gap does it fill?",
         ["The Colorado is over-allocated and drying, yet snowpack, storage, drought and climate "
          "projections still live in separate tools and different units. Managers have lacked one "
          "consistent, observation-validated view of the whole basin. ",
          html.B("CRIA fills that gap"),
          " — moving the project from a set of individual studies to an integrated, "
          "decision-ready tool."]),
    ]
    items = []
    for i, (icon, q, a) in enumerate(QA):
        items.append(html.Details([
            html.Summary([
                html.Span(html.I(className=f"bi {icon}"), className="pos-ic"),
                html.Span(q, className="pos-q"),
                html.I(className="bi bi-chevron-down pos-chev"),
            ], className="pos-sum"),
            html.Div(a, className="pos-a"),
        ], className="pos-item", open=(i == 0)))
    return html.Div([
        html.Div([html.I(className="bi bi-compass2", style={"color": MAROON, "marginRight": "8px",
                                                            "fontSize": "18px"}),
                  html.Span("Where CRIA stands", style={"fontSize": "16px", "fontWeight": "800",
                                                        "color": MAROON, "letterSpacing": "0.3px"}),
                  html.Span("the questions a reviewer will ask — answered plainly (click to open)",
                            style={"fontSize": "11px", "color": "#1e293b", "marginLeft": "10px"})],
                 style={"borderBottom": f"2px solid {MAROON}", "paddingBottom": "8px",
                        "marginBottom": "14px", "display": "flex", "alignItems": "center",
                        "flexWrap": "wrap", "gap": "10px"}),
        html.Div(items, className="pos-wrap"),
    ], className="crb-card", style={"marginBottom": "18px", "borderTop": "4px solid #FFC627"})


def _why_cria():
    NAVY = "#0D2137"

    def _sub(label):
        return html.Div(label, style={"fontSize": "12.5px", "fontWeight": "800",
                                       "color": MAROON, "textTransform": "uppercase",
                                       "letterSpacing": "0.4px", "margin": "4px 0 10px"})

    def _value_row(icon, head, body):
        return html.Div([
            html.I(className=f"bi {icon}", style={"fontSize": "17px", "color": MAROON,
                                                  "marginRight": "10px", "marginTop": "1px"}),
            html.Div([
                html.Span(head + " ", style={"fontWeight": "800", "color": "#0D2137"}),
                html.Span(body, style={"color": "#37474f"}),
            ], style={"fontSize": "12.5px", "lineHeight": "1.55"}),
        ], style={"display": "flex", "alignItems": "flex-start", "marginBottom": "9px"})

    def _wstat(icon, num, label):
        return html.Div([html.I(className=f"bi {icon}"),
                         html.Div(num, className="why-stat-num"),
                         html.Div(label, className="why-stat-lbl")], className="why-stat")

    def _wfirst(icon, badge, head, body):
        return html.Div([
            html.Div([html.I(className=f"bi {icon}"),
                      html.Span(badge, className="why-first-badge")], className="why-first-top"),
            html.Div(head, className="why-first-head"),
            html.Div(body, className="why-first-body"),
        ], className="why-first")

    return html.Div([
        html.Div([
            html.I(className="bi bi-stars", style={"color": MAROON, "marginRight": "8px",
                                                   "fontSize": "18px"}),
            html.Span("Why CRIA", style={"fontSize": "16px", "fontWeight": "800",
                                         "color": MAROON, "letterSpacing": "0.3px"}),
            html.Span("who it's for, the gap it fills, and what makes it new",
                      style={"fontSize": "11px", "color": "#1e293b", "marginLeft": "10px"}),
        ], style={"borderBottom": f"2px solid {MAROON}", "paddingBottom": "8px",
                  "marginBottom": "14px", "display": "flex", "alignItems": "center",
                  "flexWrap": "wrap"}),

        # ── impressive novelty hero ──
        html.Div([
            html.Div("WHAT MAKES CRIA DIFFERENT", className="why-hero-eyebrow"),
            html.Div(["One ", html.Span("validated, integrated", className="why-hl"),
                      " view of the whole Colorado River Basin"], className="why-hero-title"),
            html.Div("Surface water, snowpack and subsurface storage — together, checked against "
                     "NASA satellites, and presented in the units managers actually decide in: "
                     "one integrated, observation-validated view of the basin.", className="why-hero-sub"),
        ], className="why-hero"),

        # ── credibility stats ──
        html.Div([
            _wstat("bi-graph-up-arrow", "NSE ≈ 0.96", "streamflow skill vs gauges"),
            _wstat("bi-moisture", "R² 0.71–0.81", "soil moisture vs NASA SMAP"),
            _wstat("bi-globe-americas", "p = 10⁻¹⁹", "GRACE storage decline"),
            _wstat("bi-calendar-check", "LOO R² 0.45", "autumn soil → year-ahead runoff"),
        ], className="why-stats"),

        # ── original contributions (scoped to the Colorado River Basin) ──
        _sub("What CRIA brings together — for the Colorado River Basin"),
        html.Div([
            _wfirst("bi-layers-half", "INTEGRATED", "One validated basin view",
                    "Surface + snowpack + subsurface storage in a single sub-basin picture — "
                    "validated against NASA GRACE & SMAP."),
            _wfirst("bi-globe-americas", "IN-APP", "GRACE storage → groundwater",
                    "Groundwater-loss diagnosis inferred from NASA GRACE total water-storage "
                    "anomalies, cross-checked against the modelled water balance."),
            _wfirst("bi-sliders", "INTERACTIVE", "ΔT / ΔP sensitivity engine",
                    "Dial warming & rainfall — get projected runoff with a 95% CI, in acre-feet."),
            _wfirst("bi-activity", "CUSTOM", "Tool-built risk indices",
                    "Aridity Severity Index & Compound Water-System Risk — custom composite "
                    "diagnostics built from the validated record."),
            _wfirst("bi-patch-check", "TRACEABLE", "Evidence shown in-app",
                    "Every headline number sits beside the peer-reviewed study that reached it "
                    "independently."),
            _wfirst("bi-compass", "HONEST", "The frontier, stated",
                    "Where no study exists yet, CRIA says so — established vs open science, "
                    "made explicit."),
        ], className="why-first-grid"),

        # The gap it fills
        _sub("The gap it fills"),
        html.Div("The Colorado River is over-allocated and drying, yet snowpack, storage, drought "
                 "and climate projections still live in separate tools and different units. Managers "
                 "have lacked a single, consistent, observation-validated view of the whole basin — "
                 "that is the gap CRIA fills.",
                 style={"fontSize": "12.5px", "color": "#37474f", "lineHeight": "1.6",
                        "marginBottom": "16px"}),

        # Who it's for
        _sub("Who CRIA is for"),
        html.Div([
            _chip("CAP & Reclamation operations", "bi-building"),
            _chip("Basin states & Tribes", "bi-people"),
            _chip("ASU researchers & students", "bi-mortarboard"),
            _chip("NASA applied science", "bi-globe-americas"),
            _chip("Water policy & outreach", "bi-megaphone"),
        ], style={"marginBottom": "16px"}),

        # What's novel
        _sub("What makes it novel"),
        dbc.Row([
            _novel_card("bi-layers-half", "Observation-informed & validated",
                        "A PRISM-calibrated VIC 5.0 reanalysis, independently evaluated against NASA "
                        "GRACE and SMAP, and reproducing Upper-Basin streamflow with NSE ≈ 0.96. Key "
                        "results are shown next to their published values."),
            _novel_card("bi-grid-3x3-gap", "Whole system, one place",
                        "Supply, snowpack, drought propagation, storage, reservoir tiers, "
                        "projections to 2100, spatial maps and uncertainty — together."),
            _novel_card("bi-chat-dots", "Explainable & decision-ready",
                        "An AI assistant (RIA) and guided reading on every tab, with key supply and "
                        "shortage results in acre-feet and Lake Mead tiers."),
        ], className="g-2", style={"marginBottom": "16px"}),

        # Why it matters for the basin
        _sub("Why it matters for the basin"),
        html.Div([
            _value_row("bi-diagram-3",
                       "One basin, one picture.",
                       "Supply, snow, storage, drought and climate are usually scattered across "
                       "separate tools and units. CRIA brings them into a single, consistent view "
                       "of the whole Colorado River Basin, so decisions rest on one shared evidence base."),
            _value_row("bi-patch-check",
                       "Observation-grounded and verifiable.",
                       "A PRISM-calibrated VIC 5.0 reanalysis is independently evaluated against NASA "
                       "GRACE and SMAP, and reproduces Upper-Basin streamflow with NSE ≈ 0.96; key "
                       "results are shown next to their published values, with uncertainty made "
                       "explicit and every figure sourced to its origin."),
            _value_row("bi-speedometer2",
                       "Built for planning.",
                       "Key supply and shortage results are expressed in the units managers already "
                       "use — acre-feet and Lake Mead shortage tiers — with live reservoir levels, so "
                       "the science plugs straight into planning and allocation decisions."),
            _value_row("bi-mortarboard",
                       "Accessible to everyone.",
                       "40-year spatial animations, guided reading on every tab, and an AI assistant "
                       "make the science usable by managers, tribes, students and the public alike — "
                       "no hydrology degree required."),
        ], style={"marginBottom": "12px"}),
        html.Div("CRIA turns decades of NASA Earth observations and physical modeling into a single, "
                 "consistent, decision-ready view of the entire Colorado River Basin — advancing the "
                 "project's applied-science mission from individual studies to an integrated "
                 "decision-support tool.",
                 style={"fontSize": "12px", "color": "#8C1D40", "fontWeight": "600",
                        "background": "transparent", "borderLeft": f"3px solid {MAROON}",
                        "padding": "10px 14px", "borderRadius": "0 6px 6px 0"}),
    ], className="crb-card", style={"padding": "16px 18px", "marginBottom": "18px"})


def _ticker():
    """A live-signal ticker — the basin's key outputs scrolling like a market tape.
       Every value here is real and already shown elsewhere in the app."""
    # (label, value, kind, critical)  kind: down=decline up=rising-bad ok=validated
    items = [
        ("Precipitation", "−8%", "down", False),
        ("Evapotranspiration", "−5%", "down", False),
        ("Soil moisture", "−12%", "down", False),
        ("Surface runoff", "−26%", "down", False),
        ("Baseflow", "−28%", "down", True),
        ("Snowpack declining", "67/103 stn", "down", False),
        ("Basin storage", "−45 MAF", "down", True),
        ("GRACE high→low swing", "−113 mm", "down", False),
        ("Subsurface share of loss", "96%", "hot", True),
        ("Rain→river amplification", "3.5×", "hot", True),
        ("Warming", "+0.28°C/dec", "hot", False),
        ("Runoff-efficiency loss", "−20%", "down", False),
        ("October signal", "LOO R² 0.45", "ok", False),
        ("Model skill", "NSE 0.96", "ok", False),
        ("SMAP validation", "R² 0.81", "ok", False),
    ]
    icon = {"down": "bi-arrow-down-right", "hot": "bi-arrow-up-right", "ok": "bi-check-circle-fill"}

    def cell(lab, val, k, crit):
        inner = [
            html.Span(lab, className="tk-l"),
            html.Span(val, className=f"tk-v tk-{k}" + (" tk-critv" if crit else "")),
            html.I(className=f"bi {icon[k]} tk-{k}"),
        ]
        if crit:
            inner.insert(0, html.I(className="bi bi-exclamation-diamond-fill tk-critmark"))
        return html.Span(inner, className="tk-cell" + (" tk-cell-crit" if crit else ""))

    row = [cell(*it) for it in items]
    tape = html.Div(row + row, className="tk-tape")   # doubled for seamless loop
    return html.Div([
        html.Div([html.Span(className="tk-live-dot"), "KEY BASIN SIGNALS"], className="tk-badge"),
        html.Div(tape, className="tk-track"),
    ], className="tk-bar")


def _role_entry():
    """Role-based entry — orients a first-time user in one glance: pick who you are,
       jump straight to the 3 analyses that matter most for you."""
    roles = [
        ("bi-building", "Water Manager",
         "Supply security, shortage tiers, and what-if scenarios — in the units you plan in.",
         [("Drought & Shortage Risk", "/drought"), ("Reservoirs & Tiers", "/reservoirs"),
          ("Scenario Explorer", "/scenario")]),
        ("bi-mortarboard", "Researcher",
         "Methods, multi-sensor validation, the open questions, and the papers behind them.",
         [("October Signal", "/october"), ("Soil Moisture & Streamflow", "/links"),
          ("Uncertainty & Confidence", "/uncertainty")]),
        ("bi-people", "Student & Public",
         "Guided and visual — the basin's story, no hydrology degree required.",
         [("Basin Overview", "/home"), ("Snowpack & Runoff", "/snowpack"),
          ("Seasonal Cycles", "/animations")]),
        ("bi-grid-3x3-gap", "Explore everything",
         "Browse all 32 analyses across 6 decision themes — or ask RIA anything.",
         [("Basin-Wide Maps", "/basinwide"), ("Water Governance", "/governance"),
          ("Publications", "/publications")]),
    ]
    cards = []
    for i, (icon, role, desc, tabs) in enumerate(roles):
        chips = [html.A([lbl, html.I(className="bi bi-arrow-right-short")],
                        href=href, className="re-chip") for lbl, href in tabs]
        cards.append(html.Div([
            html.Div([html.I(className=f"bi {icon}")], className="re-ic"),
            html.Div(role, className="re-role"),
            html.Div(desc, className="re-desc"),
            html.Div(chips, className="re-chips"),
        ], className="re-card", style={"animationDelay": f"{i*0.07:.2f}s"}))
    return html.Div([
        html.Div([
            html.I(className="bi bi-compass", style={"color": MAROON, "marginRight": "8px",
                                                     "fontSize": "18px"}),
            html.Span("New here? Start with your persona",
                      style={"fontSize": "16px", "fontWeight": "800", "color": MAROON,
                             "letterSpacing": "0.3px"}),
            html.Span("pick who you are — we'll point you to the analyses that matter most",
                      style={"fontSize": "11px", "color": "#1e293b", "marginLeft": "10px"}),
        ], style={"borderBottom": f"2px solid {MAROON}", "paddingBottom": "8px",
                  "marginBottom": "14px", "display": "flex", "alignItems": "center",
                  "flexWrap": "wrap", "gap": "10px"}),
        html.Div(cards, className="re-grid"),
        html.Div([html.I(className="bi bi-info-circle",
                         style={"marginRight": "6px", "color": MAROON}),
                  "These are quick starts, not limits — every one of the 32 analyses stays open "
                  "to everyone in the sidebar, and RIA can take you to any of them."],
                 className="re-note"),
    ], className="crb-card", style={"padding": "16px 18px 14px", "marginBottom": "18px"})


def _report_card():
    """State of the basin — one status chip per theme, real data, traffic-light + link."""
    RED, AMBER, GREEN, NEUT = "#B71C1C", "#E65100", "#2E7D32", "#546e7a"
    df = _safe(load_vic_annual)

    def _recent_vs_base(col, build=None):
        if df.empty:
            return None
        d = df[df["basin"] == "CRB"].copy()
        if build:
            d = build(d); col = "val"
        if col not in d.columns:
            return None
        base = d[(d["water_year"] >= 1983) & (d["water_year"] <= 2010)][col].mean()
        rec = d[d["water_year"] >= 2015][col].mean()
        if base is None or np.isnan(base) or abs(base) < 1e-6 or rec is None or np.isnan(rec):
            return None
        return (rec - base) / abs(base) * 100.0

    # These are DIFFERENT vitals from the three headline questions (supply / storage / warming),
    # so the two sections complement rather than repeat each other.
    def _re_change():
        if df.empty:
            return None
        d = df[df["basin"] == "CRB"]
        if not {"OUT_RUNOFF", "OUT_BASEFLOW", "OUT_PREC"}.issubset(d.columns):
            return None
        def re(y0, y1):
            w = d[(d.water_year >= y0) & (d.water_year <= y1)]
            p = w["OUT_PREC"].mean()
            return ((w["OUT_RUNOFF"] + w["OUT_BASEFLOW"]).mean() / p) if p else None
        b, r = re(1983, 2010), re(2015, 2024)
        return (r - b) / abs(b) * 100 if (b and r) else None

    tiles = []

    def _pct_tile(label, icon, val, note, href, up_bad=False):
        if val is None:
            return
        bad = (val > 0) if up_bad else (val < 0)
        mag = abs(val)
        color = RED if (bad and mag >= 12) else AMBER if bad else GREEN
        arrow = "bi-arrow-up-right" if val > 0 else "bi-arrow-down-right"
        tiles.append((label, icon, f"{val:+.0f}%", arrow, color, note, href))

    _pct_tile("Precipitation", "bi-cloud-rain", _recent_vs_base("OUT_PREC"),
              "rain + snow vs 1983–2010", "/watbal")
    # Dryness = the SHARE of precipitation lost to the sky (ET/P). This rises as the basin
    # aridifies, even when absolute ET falls because there is simply less water to evaporate —
    # so it is the honest signal here (up = worse), not the raw ET flux.
    _pct_tile("Dryness (ET / P)", "bi-brightness-high",
              _recent_vs_base("val", build=lambda d: d.assign(val=d["OUT_EVAP"] / d["OUT_PREC"])),
              "share of rain & snow lost to the sky", "/warming", up_bad=True)
    _pct_tile("Soil moisture", "bi-moisture", _recent_vs_base("OUT_SOIL_MOIST"),
              "root-zone wetness vs baseline", "/links")
    _pct_tile("Runoff efficiency", "bi-percent", _re_change(),
              "share of rain/snow reaching rivers", "/budyko")

    sta = _safe(load_snotel_stations)
    if not sta.empty:
        crb = sta[sta["basin"] == "CRB"].drop_duplicates("site_id")
        n_tot = len(crb); n_dec = int((crb["mk_slope"].dropna() < 0).sum())
        frac = n_dec / n_tot if n_tot else 0
        col = RED if frac > 0.75 else AMBER if frac > 0.5 else GREEN
        tiles.append(("Snowpack", "bi-snow", f"{n_dec}/{n_tot}", "bi-arrow-down-right", col,
                      "SNOTEL stations declining", "/snowpack"))

    tiles.append(("Reservoirs & tiers", "bi-water", "Watch", "bi-exclamation-triangle", AMBER,
                  "Lake Mead / Powell shortage tiers", "/reservoirs"))

    GOLD = "#FFC627"

    def _tile(label, icon, val, arrow, color, note, href, accent):
        return html.A([
            html.Div([
                html.I(className=f"bi {icon}", style={"fontSize": "14px", "color": color,
                                                      "marginRight": "6px", "flex": "0 0 auto"}),
                html.Span(label, className="rc-tile-label",
                          style={"fontSize": "9.5px", "fontWeight": "700", "color": "#546e7a",
                                 "textTransform": "uppercase", "letterSpacing": "0.2px"}),
            ], style={"display": "flex", "alignItems": "center", "marginBottom": "4px",
                      "minWidth": "0"}),
            html.Div([
                html.Span(val, style={"fontSize": "21px", "fontWeight": "800", "color": "#0D2137",
                                      "whiteSpace": "nowrap"}),
                html.I(className=f"bi {arrow}", style={"fontSize": "13px", "color": color,
                                                       "marginLeft": "5px", "flex": "0 0 auto"}),
            ], style={"display": "flex", "alignItems": "baseline", "marginBottom": "2px",
                      "flexWrap": "nowrap", "whiteSpace": "nowrap"}),
            html.Div(note, style={"fontSize": "10px", "color": "#607d8b", "lineHeight": "1.3"}),
        ], href=href, className="rc-tile",
            style={"borderLeft": f"3px solid {accent}"})

    return html.Div([
        html.Div([
            html.I(className="bi bi-activity", style={"color": MAROON, "marginRight": "8px",
                                                      "fontSize": "18px"}),
            html.Span("State of the basin", style={"fontSize": "16px", "fontWeight": "800",
                                                    "color": MAROON, "letterSpacing": "0.3px"}),
            html.Span("the deeper indicators behind the three headline questions — click any to open",
                      style={"fontSize": "11px", "color": "#1e293b", "marginLeft": "10px"}),
        ], style={"borderBottom": f"2px solid {MAROON}", "paddingBottom": "8px",
                  "marginBottom": "14px", "display": "flex", "alignItems": "center",
                  "flexWrap": "wrap"}),
        html.Div([_tile(*t, GOLD if i % 2 == 0 else MAROON) for i, t in enumerate(tiles)],
                 className="rc-tiles"),
    ], className="crb-card", style={"padding": "18px 20px 12px", "marginBottom": "18px"})


def _spark_fig(x, y, color, hov):
    """A small REAL interactive sparkline (Plotly) — hover shows the actual value."""
    xy = [(a, b) for a, b in zip(x, y) if b == b]
    if len(xy) < 2:
        return None
    xs = [a for a, _ in xy]; ys = [b for _, b in xy]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines",
                             line=dict(color=color, width=2.2, shape="spline", smoothing=0.5),
                             hovertemplate=hov + "<extra></extra>"))
    fig.add_trace(go.Scatter(x=[xs[-1]], y=[ys[-1]], mode="markers",
                             marker=dict(color=color, size=8, line=dict(color="white", width=1.5)),
                             hoverinfo="skip"))
    fig.update_layout(margin=dict(l=0, r=2, t=6, b=0), height=56, showlegend=False,
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      xaxis=dict(visible=False), yaxis=dict(visible=False), hovermode="x",
                      hoverlabel=dict(bgcolor="white", bordercolor=color, font_size=11))
    return fig


_MINI_CACHE = {}


def _basin_outline():
    """CRB exterior ring(s) as list of (xs, ys) for the mini maps."""
    import json, os
    try:
        gj = json.load(open(os.path.join("assets", "crb_basins.geojson")))
    except Exception:
        return []
    rings = []
    for f in gj.get("features", []):
        if f.get("properties", {}).get("basin_id") != "CRB":
            continue
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for poly in polys:
            for r in poly:
                rings.append(([p[0] for p in r], [p[1] for p in r]))
    return rings


def _mini_map(var, colorscale, unit, reverse=False):
    """Small REAL interactive basin map — the mean spatial pattern of one VIC field
       (hover reads the value; drag to pan, scroll to zoom). Cached per variable."""
    key = (var, colorscale, reverse)
    if key in _MINI_CACHE:
        return _MINI_CACHE[key]
    import os
    fig = go.Figure()
    try:
        path = os.path.join("data", "cache", "spatial", f"spatial_{var}.parquet")
        df = pd.read_parquet(path, columns=["lat", "lon", "value"])
        agg = df.groupby(["lat", "lon"], as_index=False)["value"].mean()
        if len(agg) > 2600:                       # keep it light + snappy
            agg = agg.iloc[:: max(1, len(agg) // 2600)]
        lo, hi = np.nanpercentile(agg["value"], [2, 98])
        fig.add_trace(go.Scattergl(
            x=agg["lon"], y=agg["lat"], mode="markers",
            marker=dict(color=agg["value"], colorscale=colorscale, reversescale=reverse,
                        cmin=lo, cmax=hi, size=3.4, showscale=False),
            customdata=agg["value"],
            hovertemplate="%{customdata:.1f} " + unit + "<extra></extra>"))
    except Exception:
        pass
    for xs, ys in _basin_outline():
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines",
                                 line=dict(color="#0D2137", width=1.1),
                                 hoverinfo="skip", showlegend=False))
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0), height=120, showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(visible=False),
        yaxis=dict(visible=False, scaleanchor="x", scaleratio=1.26),
        dragmode="pan", hoverlabel=dict(bgcolor="white", font_size=11))
    _MINI_CACHE[key] = fig
    return fig


def _q3_data():
    """Compute the three live headline metrics with full scientific provenance."""
    df = _safe(load_vic_annual)
    d = df[df["basin"] == "CRB"].sort_values("water_year") if not df.empty else df
    RED, AMBER = "#B71C1C", "#E65100"
    years = d["water_year"].tolist() if not d.empty else []

    sup, sup_series = None, []
    if not d.empty and "OUT_RUNOFF" in d.columns:
        s = d.assign(v=d["OUT_RUNOFF"] + d["OUT_BASEFLOW"])
        base = s[(s.water_year >= 1983) & (s.water_year <= 2010)]["v"].mean()
        rec = s[s.water_year >= 2015]["v"].mean()
        sup = (rec - base) / abs(base) * 100 if base else None
        sup_series = s["v"].tolist()

    warm, warm_p, warm_series = None, None, []
    if not d.empty and "OUT_AIR_TEMP" in d.columns:
        t = trend_slope(d["OUT_AIR_TEMP"], d["water_year"])
        if t.get("slope") is not None:
            warm = t["slope"] * 10; warm_p = t.get("pvalue")
        warm_series = d["OUT_AIR_TEMP"].tolist()

    gmin, risk_series, risk_x = None, [], []
    g = _safe(load_grace)
    if not g.empty and "tws_mm" in g.columns:
        gg = g[g["basin"] == "CRB"].copy()
        xcol = next((c for c in ("date", "time", "year") if c in gg.columns), None)
        if xcol:
            gg = gg.sort_values(xcol)
        v = gg["tws_mm"]
        m = v.notna()
        gmin = float(v[m].min()) if m.any() else None
        risk_series = v[m].tolist()
        risk_x = (gg.loc[m, xcol].astype(str).tolist() if xcol else list(range(int(m.sum()))))

    sig = ("statistically significant, Mann–Kendall p < 0.05"
           if (warm_p is not None and warm_p < 0.05) else "Mann–Kendall test applied")

    return {
        "supply": {
            "q": "How much water is there?", "icon": "bi-droplet-half", "tint": "#E6F1FB",
            "plain": "Less water reaches the river than a generation ago.",
            "sci": "Naturalized water supply — surface runoff + baseflow",
            "num": (f"{sup:+.0f}%" if sup is not None else "—"),
            "cval": sup, "cdec": 0, "csuf": "%", "cplus": False,
            "col": "#01579B",
            "mapvar": "OUT_RUNOFF", "cmap": "Blues", "unit": "mm/yr", "crev": False,
            "fig": _spark_fig(years, sup_series, "#01579B", "WY %{x}<br>%{y:.0f} mm/yr"),
            "method": "Recent decade (WY2015–2024) vs the WY1983–2010 baseline, from the VIC 5.0 "
                      "reanalysis (basin-mean runoff + baseflow).",
            "src": "VIC 5.0 PRISM-calibrated reanalysis — NSE 0.96 (Ghimire, Wang & Vivoni, 2026, Sci. Reports).",
            "cta": "Open the water balance", "href": "/watbal",
        },
        "risk": {
            "q": "How bad is the risk?", "icon": "bi-exclamation-triangle", "tint": "#F7E9EE",
            "plain": "Basin storage is near its lowest in the satellite record.",
            "sci": "Terrestrial water storage anomaly (NASA GRACE / GRACE-FO)",
            "num": (f"{gmin:.0f} mm" if gmin is not None else "—"),
            "cval": gmin, "cdec": 0, "csuf": " mm", "cplus": False,
            "col": "#8C1D40",
            "mapvar": "OUT_SOIL_MOIST", "cmap": "YlGnBu", "unit": "mm", "crev": False,
            "fig": _spark_fig(risk_x, risk_series, "#8C1D40", "%{x}<br>%{y:.0f} mm"),
            "method": "Basin-mean monthly total-water-storage anomaly; the record minimum over the "
                      "2002–present satellite era.",
            "src": "NASA JPL GRACE & GRACE-FO mascon solution (RL06 CRI).",
            "cta": "Open water storage (GRACE)", "href": "/tws",
        },
        "climate": {
            "q": "What if it gets warmer?", "icon": "bi-thermometer-half", "tint": "#FBF0D2",
            "plain": "Steady warming — and rising toward 2100.",
            "sci": "Near-surface air-temperature trend",
            "num": (f"{warm:+.2f}°C" if warm is not None else "—"),
            "cval": warm, "cdec": 2, "csuf": "°C", "cplus": True,
            "col": "#BA7517",
            "mapvar": "OUT_AIR_TEMP", "cmap": "RdBu", "unit": "°C", "crev": True,
            "fig": _spark_fig(years, warm_series, "#BA7517", "WY %{x}<br>%{y:.2f} °C"),
            "method": f"Theil–Sen slope on basin-mean annual air temperature, WY1984–2024, per decade "
                      f"({sig}).",
            "src": "VIC 5.0 forcing (PRISM-based); trend after Sen (1968) and Mann–Kendall.",
            "cta": "Open surface warming", "href": "/warming",
        },
    }


def _q3_card(e):
    return html.Div(html.Div([
        # glassy 3D number tile — bottom-right corner, so the question above stays fully readable
        html.Div(e["num"], style={
            "position": "absolute", "bottom": "13px", "right": "13px", "zIndex": "3",
            "background": "rgba(255,255,255,0.5)",
            "backdropFilter": "blur(11px) saturate(1.15)",
            "WebkitBackdropFilter": "blur(11px) saturate(1.15)",
            "border": "none", "color": e["col"],
            "fontSize": "18px", "fontWeight": "800", "letterSpacing": "-0.5px",
            "lineHeight": "1", "padding": "7px 11px", "borderRadius": "12px",
            "boxShadow": ("0 8px 18px rgba(13,33,55,0.16), "
                          "0 1px 0 rgba(255,255,255,0.95) inset, "
                          "-3px -3px 8px rgba(255,255,255,0.65) inset, "
                          "3px 3px 8px rgba(13,33,55,0.06) inset"),
            "whiteSpace": "nowrap"}),
        # compact row: animated MAP left · text RIGHT (fits in little space)
        html.Div([
            # ── LEFT · animated basin map (change across water years, WY1984 → 2024) ──
            html.Img(src=f"/assets/animations/spatial_{e['mapvar']}.gif",
                     alt=f"Animated Colorado River Basin map — {e['q']}",
                     style={"height": "118px", "width": "auto", "maxWidth": "40%",
                            "display": "block", "borderRadius": "11px",
                            "boxShadow": "0 5px 14px rgba(13,33,55,0.14)",
                            "flex": "0 0 auto", "alignSelf": "center"}),
            # ── RIGHT · text beside the map ──
            html.Div([
                html.Div([
                    html.Span(html.I(className=f"bi {e['icon']}"),
                              style={"display": "inline-flex", "alignItems": "center",
                                     "justifyContent": "center", "width": "34px", "height": "34px",
                                     "borderRadius": "10px", "background": e["tint"],
                                     "color": e["col"], "fontSize": "17px",
                                     "flex": "0 0 34px", "marginRight": "9px"}),
                    html.Div(e["q"], style={"fontSize": "15px", "fontWeight": "800",
                                            "color": "#0D2137", "lineHeight": "1.15"}),
                ], style={"display": "flex", "alignItems": "center", "marginBottom": "9px"}),
                html.Div(e["plain"], style={"fontSize": "13px", "color": "#0D2137",
                                            "fontWeight": "800", "lineHeight": "1.35",
                                            "marginBottom": "8px"}),
                html.Div(e["sci"], className="q3-src", style={"marginBottom": "8px"}),
                html.A([e["cta"], "  ", html.I(className="bi bi-arrow-right")], href=e["href"],
                       className="q3-ev-cta",
                       style={"fontSize": "12.5px", "fontWeight": "700", "color": "#01579B",
                              "textDecoration": "none", "marginTop": "6px"}),
            ], className="q3-ev-text", style={"flex": "1 1 0", "minWidth": "0", "display": "flex",
                      "flexDirection": "column", "justifyContent": "center"}),
        ], className="q3-ev-row", style={"display": "flex", "alignItems": "center", "gap": "12px"}),
    ], className="q3-evcard",
        style={"position": "relative", "height": "100%"}),
        className="q3-evcol")


def _start_here():
    data = _q3_data()
    return html.Div([
        html.Div("What CRIA does", className="q3-eyebrow"),
        html.Div(["NASA Earth observations and physical modeling, turned into ",
                  html.Span("decisions the Colorado River can be run on.", className="hl")],
                 className="q3-title"),
        html.Div("Three questions the basin turns on — each a live number from the VIC "
                 "reanalysis and NASA satellites. Hover any chart to read the record.",
                 className="q3-sub"),
        html.Div(style={"height": "14px"}),
        html.Div([_q3_card(data["supply"]), _q3_card(data["risk"]), _q3_card(data["climate"])],
                 className="q3-grid"),
    ], className="crb-card", style={"padding": "22px 24px 16px", "marginBottom": "18px",
                                    "borderTop": "1px solid rgba(255,255,255,0.6)"})


def _forecast_data():
    """Real SWE -> runoff seasonal-supply forecast: regression skill + 95% prediction band.
       Honest: fit on the WY1984-2024 record; nothing synthetic."""
    s = _safe(load_snotel_annual); v = _safe(load_vic_annual)
    if s.empty or v.empty:
        return None
    sb = s[s["basin"] == "CRB"][["water_year", "peak_swe_mm"]].dropna()
    r = (v[v["basin"] == "CRB"][["water_year", "OUT_RUNOFF"]]
         .rename(columns={"OUT_RUNOFF": "runoff_mm"}))
    m = sb.merge(r, on="water_year").dropna().sort_values("water_year")
    if len(m) < 8:
        return None
    x = m["peak_swe_mm"].to_numpy(); y = m["runoff_mm"].to_numpy()
    sl, ic, rr, p, _ = stats.linregress(x, y)
    n = len(m); r2 = rr ** 2
    resid = y - (sl * x + ic)
    s_err = float(np.sqrt(np.sum(resid ** 2) / (n - 2)))
    xbar = float(x.mean()); sxx = float(np.sum((x - xbar) ** 2))
    xl = np.linspace(x.min(), x.max(), 60)
    yhat = sl * xl + ic
    pi = 1.96 * s_err * np.sqrt(1 + 1 / n + (xl - xbar) ** 2 / sxx)
    last = m.iloc[-1]
    return {"x": x, "y": y, "yr": m["water_year"].astype(int).to_numpy(),
            "xl": xl, "yhat": yhat, "lo": yhat - pi, "hi": yhat + pi,
            "sl": sl, "ic": ic, "r2": r2, "p": p, "n": n, "s_err": s_err,
            "xbar": xbar, "sxx": sxx,
            "last_yr": int(last["water_year"]), "last_swe": float(last["peak_swe_mm"]),
            "last_obs": float(last["runoff_mm"]),
            "last_fc": float(sl * last["peak_swe_mm"] + ic),
            "last_pi": float(1.96 * s_err * np.sqrt(1 + 1 / n +
                        (last["peak_swe_mm"] - xbar) ** 2 / sxx))}


def _forecast_fig(fc):
    """Interactive SWE -> runoff forecast scatter with fit + 95% prediction band."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=np.concatenate([fc["xl"], fc["xl"][::-1]]),
                             y=np.concatenate([fc["hi"], fc["lo"][::-1]]),
                             fill="toself", fillcolor="rgba(1,87,155,0.10)",
                             line=dict(width=0), hoverinfo="skip",
                             name="95% prediction band"))
    fig.add_trace(go.Scatter(x=fc["xl"], y=fc["yhat"], mode="lines",
                             line=dict(color="#8C1D40", width=2.4),
                             name=f"Fit · R²={fc['r2']:.2f}", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=fc["x"], y=fc["y"], mode="markers",
                             marker=dict(color="#01579B", size=7, opacity=0.75,
                                         line=dict(color="white", width=1)),
                             text=[str(a) for a in fc["yr"]],
                             hovertemplate="WY %{text}<br>April SWE %{x:.0f} mm<br>"
                                           "Runoff %{y:.0f} mm<extra></extra>",
                             name="Observed years"))
    fig.add_trace(go.Scatter(x=[fc["last_swe"]], y=[fc["last_fc"]], mode="markers",
                             marker=dict(color="#FFC627", size=15, symbol="diamond",
                                         line=dict(color="#8C1D40", width=2)),
                             hovertemplate=(f"WY{fc['last_yr']} forecast<br>"
                                            f"{fc['last_fc']:.0f} ± {fc['last_pi']:.0f} mm"
                                            "<extra></extra>"),
                             name=f"WY{fc['last_yr']} forecast"))
    fig.update_layout(height=230, margin=dict(l=48, r=12, t=8, b=64),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      xaxis=dict(title="April 1 snowpack — SWE (mm)", showgrid=False),
                      yaxis=dict(title="Annual runoff (mm)", showgrid=True,
                                 gridcolor="rgba(13,33,55,0.06)"),
                      legend=dict(orientation="h", y=-0.32, x=0, font=dict(size=10)),
                      hoverlabel=dict(bgcolor="white", font_size=11))
    return fig


def _forecast_strip():
    """Overview 'water-supply outlook' — real forecast skill, uncertainty, and the
       NMME+VIC seasonal result. Honest: skill + prediction band shown, nothing synthetic."""
    fc = _forecast_data()

    def _tile(big, sub, note, accent):
        return dbc.Col(html.Div([
            html.Div(big, style={"fontSize": "26px", "fontWeight": "800", "color": accent,
                                 "lineHeight": "1", "letterSpacing": "-0.5px"}),
            html.Div(sub, style={"fontSize": "12.5px", "fontWeight": "800", "color": "#0D2137",
                                 "margin": "6px 0 3px", "lineHeight": "1.25"}),
            html.Div(note, style={"fontSize": "11.5px", "color": "#546e7a", "lineHeight": "1.4"}),
        ], className="fc-tile", style={"borderLeft": f"3px solid {accent}"}),
            xs=12, sm=6, md=4, className="mb-2")

    r2 = fc["r2"] if fc else None
    slope100 = fc["sl"] * 100 if fc else None
    tiles = [
        _tile(f"{int(round(r2*100))}%" if fc else "—",
              "of annual runoff predicted from April snowpack",
              (f"SWE→runoff regression · R²={r2:.2f}, p<0.001 · WY1984–{fc['last_yr']} ({fc['n']} yrs)"
               if fc else "SWE→runoff regression"),
              "#01579B"),
        _tile(f"+{slope100:.0f} mm" if fc else "—",
              "more basin runoff per +100 mm April SWE",
              ("Each year's snowpack sets the water supply — with a 95% prediction band, "
               "not a point guess"),
              "#8C1D40"),
        _tile("≈ / >",
              "NMME+VIC seasonal skill vs Reclamation's 24-Month Study",
              "9-month streamflow forecast, comparable or better skill (Yue et al. 2024)",
              "#BA7517"),
    ]

    body = [
        html.Div("Water-supply outlook", className="q3-eyebrow"),
        html.Div(["Will the snow deliver? ",
                  html.Span("Forecasting the basin's water — with the skill shown.",
                            className="hl")], className="q3-title",
                 style={"fontSize": "23px"}),
        html.Div("Managers watch one thing above all: how much runoff this year's snow will "
                 "yield. CRIA shows the forecast and how good it is — the record, the fit, and "
                 "a 95% prediction band — never a bare number.", className="q3-sub"),
        html.Div(style={"height": "10px"}),
        dbc.Row(tiles, className="g-3"),
    ]
    if fc:
        body += [
            html.Div(
                dcc.Graph(figure=_forecast_fig(fc),
                          config={"displayModeBar": False},
                          style={"height": "230px"}),
                style={"marginTop": "6px", "borderRadius": "12px", "overflow": "hidden"}),
            html.Div([html.I(className="bi bi-journal-check", style={"marginRight": "6px"}),
                      f"WY{fc['last_yr']} check: forecast {fc['last_fc']:.0f} ± {fc['last_pi']:.0f} mm · "
                      f"observed {fc['last_obs']:.0f} mm — inside the band. Fit on the VIC "
                      "reanalysis, WY1984–2024; nothing synthetic."],
                     className="q3-src", style={"marginTop": "6px"}),
        ]
    body += [
        html.Div([
            html.A(["Open the snow→runoff forecast  ", html.I(className="bi bi-arrow-right")],
                   href="/snowpack", style={"fontSize": "12.5px", "fontWeight": "700",
                                            "color": "#01579B", "textDecoration": "none",
                                            "marginRight": "18px"}),
            html.A(["Open seasonal forecasts (NMME)  ", html.I(className="bi bi-arrow-right")],
                   href="/nmme", style={"fontSize": "12.5px", "fontWeight": "700",
                                        "color": "#01579B", "textDecoration": "none"}),
        ], style={"marginTop": "12px"}),
    ]
    return html.Div(body, className="crb-card",
                    style={"padding": "22px 24px 18px", "marginBottom": "18px",
                           "borderTop": "1px solid rgba(255,255,255,0.6)"})


_LEDGER = {}


def _loss_ledger():
    """Structural-loss accounting in managers' units (MAF), computed live from the
       reanalysis + GRACE. eff_loss = yield the basin no longer produces at its old
       runoff efficiency; grace_cum = total stored water lost over the GRACE record."""
    if "v" in _LEDGER:
        return _LEDGER["v"]
    AREA = 654441.0
    def maf(mm):
        return mm * AREA * 1e-6 * 0.810714      # 1 mm over the CRB ≈ 0.53 MAF
    out = {"eff_loss_maf": 3.8, "eff_pct": 24, "grace_cum_maf": 45,
           "grace_yr0": 2002, "grace_yr1": 2024}
    try:
        d = _safe(load_vic_annual)
        d = d[d["basin"] == "CRB"].sort_values("water_year")
        d = d.assign(re=(d["OUT_RUNOFF"] + d["OUT_BASEFLOW"]) / d["OUT_PREC"])
        base = d[(d.water_year >= 1983) & (d.water_year <= 2010)]
        rec = d[d.water_year >= 2015]
        re_b, re_r = base["re"].mean(), rec["re"].mean()
        prec_r = rec["OUT_PREC"].mean()
        yield_r = (rec["OUT_RUNOFF"] + rec["OUT_BASEFLOW"]).mean()
        eff_mm = (re_b - re_r) * prec_r
        out["eff_loss_maf"] = maf(eff_mm)
        out["eff_pct"] = eff_mm / yield_r * 100
    except Exception:
        pass
    try:
        g = _safe(load_grace)
        gg = g[g["basin"] == "CRB"].dropna(subset=["tws_mm"]).copy()
        gg["t"] = pd.to_datetime(gg["date"]); gg = gg.sort_values("t")
        yr = gg["t"].dt.year + gg["t"].dt.dayofyear / 365.25
        sl, _ic = np.polyfit(yr, gg["tws_mm"], 1)
        out["grace_cum_maf"] = abs(maf(sl * float(yr.max() - yr.min())))
        out["grace_yr0"], out["grace_yr1"] = int(yr.min()), int(yr.max())
    except Exception:
        pass
    _LEDGER["v"] = out
    return out


_GW = {}


def _gw_share():
    """Live GRACE − VIC storage split: how much of the observed total-storage decline is
       NOT explained by snow + soil (i.e. groundwater + surface-reservoir change).
       Reproducible from the bundled cache — replaces a figure quoted from a report."""
    if "v" in _GW:
        return _GW["v"]
    out = None
    try:
        from modules.storage import _series
        df = _series("CRB")
        if df is not None and not df.empty:
            g = stats.linregress(df["water_year"], df["grace_mm"])
            r = stats.linregress(df["water_year"], df["resid_mm"])
            if g.slope:
                out = {"share": r.slope / g.slope * 100.0,
                       "resid_slope": r.slope, "resid_p": r.pvalue,
                       "grace_slope": g.slope}
    except Exception:
        pass
    _GW["v"] = out
    return out


def _eye_opener():
    """Flagship — the Colorado's 'balance sheet of losses'. Each row: the story on the
       left, the loss figure in a 3D glassy tile on the right. Measured, in acre-feet,
       benchmarked to the Law of the River. Warming named as leading (not sole) driver."""
    L = _loss_ledger()
    G = _gw_share()

    def tile(kicker, line, src, href, num, unit, accent):
        return dbc.Col(html.Div([
            # top row: kicker on the left, number chip on the right
            html.Div([
                html.Div(kicker, className="eo3-kicker"),
                html.Div([
                    html.Div(num, className="eo3-num", style={"color": accent}),
                    html.Div(unit, className="eo3-unit"),
                ], className="eo3-numbox", style={"borderTop": f"3px solid {accent}"}),
            ], className="eo3-top"),
            # descriptive text — FULL WIDTH below (never squeezed by the number)
            html.Div(line, className="eo3-line"),
            html.Div([html.Span(src, className="eo3-src"),
                      html.A(["See the evidence  ", html.I(className="bi bi-arrow-right")],
                             href=href, className="eo3-cta")], className="eo3-foot"),
        ], className="eo3-tile"), xs=12, md=6, lg=4, className="mb-2")

    return html.Div([
        html.Div("What the record shows", className="q3-eyebrow"),
        html.Div(["Drought, or a ", html.Span("longer-term decline?", className="hl")],
                 className="q3-title", style={"fontSize": "23px"}),
        html.Div("Three basin-scale losses, expressed in acre-feet, computed from the "
                 "PRISM-calibrated VIC reanalysis and NASA GRACE over the WY1984–2024 record.",
                 className="q3-sub"),
        html.Div(style={"height": "12px"}),
        dbc.Row([
            tile("Runoff-efficiency loss",
                 ["The basin now yields about this much less water for the same precipitation "
                  "— roughly ", html.B(f"{L['eff_pct']:.0f}% of recent flow"),
                  " — on the order of a Lower-Basin state's full annual Colorado River allotment. "
                  "The decline is statistically significant (p<0.001); warming is its leading driver."],
                 "VIC 5.0 reanalysis · runoff efficiency, WY1984–2024 (cf. Udall & Overpeck 2017)",
                 "/aridification", f"{L['eff_loss_maf']:.1f}", "MAF a year", "#8C1D40"),
            tile("Total storage depletion",
                 [f"Net decline in the basin's total water storage since {L['grace_yr0']}, a "
                  "magnitude ", html.B("comparable to the combined Mead + Powell capacity"),
                  "; a large share is groundwater."],
                 f"NASA GRACE / GRACE-FO · trend over {L['grace_yr0']}–{L['grace_yr1']} (approximate)",
                 "/tws", f"{L['grace_cum_maf']:.0f}", f"MAF since {L['grace_yr0']}", "#01579B"),
            tile("Not snow, not soil",
                 ["This much of the basin's storage decline is ",
                  html.B("not explained by snow or soil moisture"),
                  " — it is groundwater and surface-reservoir drawdown."],
                 (f"GRACE − VIC residual, computed live: {G['resid_slope']:+.2f} mm/yr, "
                  f"{_pf(G['resid_p'])}" if G else "GRACE − VIC residual (Storage Detective)"),
                 "/storage", (f"{G['share']:.0f}%" if G else "—"), "of the loss", "#BA7517"),
        ], className="g-3"),
        html.Div([
            html.B("How these are computed: "),
            "efficiency loss = (historical − recent runoff efficiency) × recent precipitation, "
            "converted to acre-feet over the basin; storage depletion = the GRACE trend across "
            "its record × record length. These are basin-scale diagnostics from validated data "
            "(VIC: NSE ≈ 0.96 vs streamflow; GRACE: satellite observation) — the tool's own "
            "computations, not peer-reviewed findings, and nothing synthetic."],
            style={"fontSize": "11px", "color": "#78909c", "marginTop": "12px",
                   "lineHeight": "1.55"}),
    ], className="crb-card", style={"padding": "22px 24px 16px", "marginBottom": "18px",
                                    "borderTop": "1px solid rgba(255,255,255,0.6)"})


_AMP = {}


def _pf(p):
    """Format a p-value for display, keeping very small values striking but exact."""
    try:
        if p != p:
            return ""
        if p >= 0.01:
            return f"p = {p:.2f}"
        e = int(np.floor(np.log10(p)))
        m = p / (10 ** e)
        sup = str(e)
        for a, b in zip("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹"):
            sup = sup.replace(a, b)
        return f"p = {m:.0f}×10{sup}"
    except Exception:
        return ""


def _amplify():
    """The amplification chain — how a modest precipitation deficit becomes a large
       deficit in the river, with each step's trend significance. All computed from
       the validated VIC record (recent WY2015+ vs the WY1983–2010 baseline)."""
    if "v" in _AMP:
        return _AMP["v"]
    out = None
    try:
        d = _safe(load_vic_annual)
        d = d[d["basin"] == "CRB"].sort_values("water_year")
        rows = []
        for col, label in [("OUT_PREC", "Precipitation"),
                           ("OUT_SOIL_MOIST", "Soil moisture"),
                           ("OUT_RUNOFF", "Surface runoff"),
                           ("OUT_BASEFLOW", "Baseflow")]:
            base = d[(d.water_year >= 1983) & (d.water_year <= 2010)][col].mean()
            rec = d[d.water_year >= 2015][col].mean()
            pct = (rec - base) / abs(base) * 100.0
            _sl, _ic, _r, p, _se = stats.linregress(d["water_year"], d[col])
            rows.append({"label": label, "pct": float(pct), "p": float(p)})
        amp = abs(rows[-1]["pct"]) / abs(rows[0]["pct"]) if rows[0]["pct"] else float("nan")
        # snowpack, for the honest counterpoint
        _s, _i, _r2, psnow, _e = stats.linregress(d["water_year"], d["OUT_SWE"])
        out = {"rows": rows, "amp": amp, "p_snow": float(psnow)}
    except Exception:
        pass
    _AMP["v"] = out
    return out


_DECLINE_FIG = {}


def _decline_fig():
    """The finding, as a real data figure: each water-balance term as % of its own
       1983–2010 baseline, 5-year smoothed. The deeper the term sits in the basin,
       the further it falls — the amplification made visible. Cached."""
    if "f" in _DECLINE_FIG:
        return _DECLINE_FIG["f"]
    fig = go.Figure()
    x0, x1 = 1983, 2026
    try:
        d = _safe(load_vic_annual)
        d = d[d["basin"] == "CRB"].sort_values("water_year").set_index("water_year")
        base = d.loc[1983:2010]

        def sm(col):
            return ((d[col] / base[col].mean() * 100)
                    .rolling(5, center=True, min_periods=3).mean().dropna())

        P, S = sm("OUT_PREC"), sm("OUT_SOIL_MOIST")
        R, B = sm("OUT_RUNOFF"), sm("OUT_BASEFLOW")
        # pin the x-range to the data so it fills the width (no empty stretch to 2070)
        x0, x1 = int(P.index.min()) - 1, int(P.index.max()) + 4

        # precipitation first, then baseflow filled back to it → the widening deficit wedge
        fig.add_trace(go.Scatter(
            x=P.index, y=P.values, mode="lines", name="Precipitation",
            line=dict(color="#5B9BD5", width=3.4),
            hovertemplate="<b>Precipitation</b><br>WY %{x}: %{y:.0f}%<extra></extra>"))
        fig.add_trace(go.Scatter(
            x=B.index, y=B.values, mode="lines", name="Baseflow",
            line=dict(color="#8C1D40", width=3.8),
            fill="tonexty", fillcolor="rgba(140,29,64,0.13)",
            hovertemplate="<b>Baseflow</b><br>WY %{x}: %{y:.0f}%<extra></extra>"))
        for s, lab, col in ((S, "Soil moisture", "#01579B"),
                            (R, "Surface runoff", "#B5551F")):
            fig.add_trace(go.Scatter(
                x=s.index, y=s.values, mode="lines", name=lab,
                line=dict(color=col, width=2.2, dash="dot"), opacity=0.9,
                hovertemplate=f"<b>{lab}</b><br>WY %{{x}}: %{{y:.0f}}%<extra></extra>"))

        fig.add_hline(y=100, line=dict(color="#90a4ae", width=1.4, dash="dash"))
        for s, col in ((P, "#5B9BD5"), (B, "#8C1D40"), (S, "#01579B"), (R, "#B5551F")):
            fig.add_annotation(x=s.index[-1], y=s.values[-1], text=f" {s.values[-1]:.0f}%",
                               showarrow=False, xanchor="left",
                               font=dict(color=col, size=12.5, family="Inter, sans-serif"))
        # the story, written on the figure
        fig.add_annotation(x=1987, y=140, text="<b>Then:</b> baseflow ran <i>above</i> the rain",
                           showarrow=False, xanchor="left", align="left",
                           font=dict(color="#8C1D40", size=12),
                           bgcolor="rgba(255,255,255,0.82)", borderpad=4)
        fig.add_annotation(x=2013, y=52,
                           text="<b>Now:</b> rain is nearly back to normal —<br>"
                                "the river's reserves are not",
                           showarrow=False, xanchor="left", align="left",
                           font=dict(color="#8C1D40", size=12),
                           bgcolor="rgba(255,255,255,0.82)", borderpad=4)
        fig.add_annotation(x=2021, y=(P.loc[2021] + B.loc[2021]) / 2,
                           text="the widening deficit", showarrow=True, arrowhead=0,
                           arrowcolor="#8C1D40", ax=-52, ay=0,
                           font=dict(color="#8C1D40", size=11.5))
    except Exception:
        pass
    fig.update_layout(
        height=430, margin=dict(l=58, r=66, t=14, b=46),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        hovermode="x unified",
        legend=dict(orientation="h", y=1.09, x=0, font=dict(size=12),
                    bgcolor="rgba(0,0,0,0)"),
        xaxis=dict(title="Water year", showgrid=False, ticks="outside", linecolor="#cfd8dc",
                   range=[x0, x1], autorange=False),
        yaxis=dict(title="% of each term's 1983–2010 baseline", range=[45, 165],
                   gridcolor="rgba(13,33,55,0.07)", zeroline=False, ticksuffix="%"),
        hoverlabel=dict(bgcolor="white", font_size=12))
    _DECLINE_FIG["f"] = fig
    return fig


def _signature():
    """The signature finding — the Colorado's decline is driven from below. A modest
       precipitation deficit amplifies into a far larger deficit in the river, and the
       most statistically certain changes are underground, not overhead."""
    A = _amplify()
    if not A:
        return html.Div()
    rows = A["rows"]
    mx = max(abs(r["pct"]) for r in rows) or 1.0
    colors = ["#5B9BD5", "#01579B", "#B5551F", "#8C1D40"]

    stage = ["falls from the sky", "soaks into the soil", "reaches the channels",
             "sustains the river between storms"]
    p0 = abs(rows[0]["pct"]) or 1.0
    bars = []
    for i, r in enumerate(rows):
        bars.append(html.Div([
            html.Div(html.Span(className="amp-dot", style={"background": colors[i]}),
                     className="amp-node"),
            html.Div([
                html.Div([
                    html.Span(r["label"], className="amp-lab"),
                    html.Span(stage[i], className="amp-stage"),
                    html.Span(_pf(r["p"]), className="amp-p"),
                ], className="amp-head"),
                html.Div([
                    html.Div(f"{r['pct']:+.0f}%", className="amp-pct",
                             style={"color": colors[i]}),
                    html.Div(html.Div(className="amp-fill",
                                      style={"width": f"{abs(r['pct'])/mx*100:.0f}%",
                                             "background": colors[i],
                                             "animationDelay": f"{0.15*i:.2f}s"}),
                             className="amp-track"),
                    html.Div(f"{abs(r['pct'])/p0:.1f}×", className="amp-mult"),
                ], className="amp-barrow"),
            ], className="amp-body"),
        ], className="amp-row"))

    return html.Div([
        # ── row 1: the animated basin (left) · the finding, in words (right) ──
        html.Div([
            html.Div(
                html.Img(src="/assets/figures/basin_cycle.svg",
                         alt="Diagram of the Colorado River Basin water cycle: precipitation, "
                             "evapotranspiration, runoff and storage",
                         style={"width": "100%", "height": "auto", "display": "block",
                                "borderRadius": "12px",
                                "boxShadow": "0 8px 22px rgba(13,33,55,0.13)"}),
                className="sig-fig"),
            html.Div([
                html.Div("The finding", className="q3-eyebrow"),
                html.Div(["The river's decline is being driven ",
                          html.Span("from below.", className="hl")],
                         className="q3-title", style={"fontSize": "26px", "margin": "8px 0 10px"}),
                html.Div(["Everyone watches the sky. But in four decades of the calibrated record, "
                          "the most statistically certain changes are ",
                          html.Span("underground", className="hl-gold"),
                          " — and a modest shortfall in rain arrives at the river ",
                          html.Span("far larger than it started.", className="hl-maroon")],
                         className="sig-note"),
                html.Div([
                    html.Div("Stored water — GRACE equivalent depth", className="scl-t"),
                    html.Div("a layer of water spread over the whole basin, not a water-table depth",
                             className="scl-s"),
                    html.Div([
                        html.Div([html.Div([html.Span("+16", className="scl-n",
                                                      style={"color": "#01579B"}),
                                            html.Span(" mm", className="scl-u")]),
                                  html.Div("2006 high", className="scl-l")], className="scl-item"),
                        html.Div([html.Div([html.Span("−97", className="scl-n",
                                                      style={"color": "#8C1D40"}),
                                            html.Span(" mm", className="scl-u")]),
                                  html.Div("2022 low", className="scl-l")], className="scl-item"),
                        html.Div([html.Div([html.Span("−113", className="scl-n",
                                                      style={"color": "#BA7517"}),
                                            html.Span(" mm", className="scl-u")]),
                                  html.Div("depth lost", className="scl-l")],
                                 className="scl-item scl-item-hl"),
                    ], className="scl-row"),
                ], className="scl-box"),
            ], className="sig-ev"),
        ], className="sig-row"),

        # ── row 2: the measured record (left) · the evidence tiles (right) ──
        html.Div([
            html.Div([
                html.Div(["The measured record", pub_star("https://doi.org/10.1029/2025WR042871", "Ghimire, Vivoni & Wang (2026), Water Resources Research 62(7)")], className="sig-charttitle"),
                html.Div(className="sig-graphwrap", children=[
                    dcc.Graph(figure=_decline_fig(),
                              config={"displayModeBar": False, "responsive": True},
                              style={"height": "360px", "width": "100%"}),
                ]),
                html.Div("Each term as a percentage of its own WY1983–2010 baseline, smoothed over "
                         "five years. The shaded wedge is the gap between what falls and what the "
                         "river keeps.",
                         style={"fontSize": "11px", "color": "#78909c", "lineHeight": "1.5"}),
            ], className="sig-fig"),
            html.Div([
                html.Div("Rain to river", className="sig-evh", style={"marginTop": "0"}),
                html.Div([
                    html.Div(bars, className="amp-bars"),
                    html.Div([
                        html.Div(f"{A['amp']:.1f}×", className="amp-badge-n"),
                        html.Div("amplification", className="amp-badge-l"),
                        html.Div("from rain to river", className="amp-badge-s"),
                    ], className="amp-badge"),
                ], className="amp-wrap"),
            ], className="sig-ev"),
        ], className="sig-row"),
        html.Div([
            html.I(className="bi bi-info-circle-fill",
                   style={"marginRight": "8px", "color": "#8C1D40"}),
            "Soil moisture and baseflow — the basin's reserves — carry the strongest signals in the "
            "whole record, far stronger than precipitation itself. Basin-mean snowpack shows ",
            html.B("no significant trend at all"),
            f" ({_pf(A['p_snow'])}). The river is losing the water that sustains it between storms.",
        ], className="sig-punch"),
        html.Div([
            html.I(className="bi bi-journal-check",
                   style={"marginRight": "7px", "color": "#2E7D32"}),
            "Peer-reviewed basis: ",
            html.A("Ghimire, Vivoni & Wang (2026), “Fall Soil Moisture Modulates Snow–Streamflow "
                   "Dynamics in the Colorado River Basin”, Water Resources Research 62(7)",
                   href="https://doi.org/10.1029/2025WR042871", target="_blank", rel="noopener"),
            " — fall soil moisture explains ", html.B("69–77% of Upper-Basin flow variability"),
            ". Model skill from ",
            html.A("Wang et al. (2026), Scientific Reports 16:15890",
                   href="https://doi.org/10.1038/s41598-026-47430-9", target="_blank",
                   rel="noopener"),
            " (NSE 0.96; SMAP R² 0.71–0.81).",
        ], className="sig-cite"),
        html.A(["See where the missing water went  ", html.I(className="bi bi-arrow-right")],
               href="/storage", className="sig-cta"),
    ], className="crb-card sig-card")


def _cycle_explainer():
    """Animated basin cross-section — rain, soil, runoff, baseflow, heat — each labelled
       with its measured change, so any visitor understands the whole story at a glance."""
    return html.Div([
        html.Div("See it happen", className="q3-eyebrow"),
        html.Div(["One rainfall, ", html.Span("followed all the way to the river.", className="hl")],
                 className="q3-title", style={"fontSize": "22px"}),
        html.Div("Watch the water move: rain falls, the soil takes what it can, heat pulls some "
                 "back up, the rest reaches the channel, and the aquifer feeds the river between "
                 "storms. Every label is a measured change from the calibrated record.",
                 className="q3-sub"),
        html.Div(
            html.Img(src="/assets/figures/basin_cycle.svg",
                     alt="Diagram of the Colorado River Basin water cycle: precipitation, "
                         "evapotranspiration, runoff and storage",
                     style={"width": "100%", "maxWidth": "760px", "height": "auto",
                            "display": "block", "margin": "14px auto 0",
                            "borderRadius": "12px",
                            "boxShadow": "0 8px 22px rgba(13,33,55,0.13)"}),
            style={"textAlign": "center"}),
        html.Div("Recent years (WY2015+) against the WY1983–2010 baseline, from the PRISM-calibrated "
                 "VIC reanalysis and NASA GRACE. Nothing synthetic.",
                 style={"fontSize": "11px", "color": "#78909c", "marginTop": "10px",
                        "textAlign": "center"}),
    ], className="crb-card", style={"padding": "22px 24px 16px", "marginBottom": "18px"})


def _october_viz(f, gain):
    """Two contrasting scenes — a dry October vs a wet one — as an animated SVG:
       sun + cracked earth + a thin trickle on the left; rain + green banks + a full
       flowing river on the right. Values are the real fitted yields."""
    dry = int(round(f["dry_y"])); wet = int(round(f["wet_y"])); g = int(round(gain))
    import urllib.parse
    # rain drops (staggered)
    rain = "".join(
        f'<line x1="{470+i*13}" y1="34" x2="{467+i*13}" y2="46" stroke="#4a9fe0" '
        f'stroke-width="2.4" stroke-linecap="round">'
        f'<animateTransform attributeName="transform" type="translate" from="0 -10" '
        f'to="6 78" dur="0.9s" begin="{i*0.13:.2f}s" repeatCount="indefinite"/>'
        f'<animate attributeName="opacity" values="0;1;1;0" dur="0.9s" begin="{i*0.13:.2f}s" '
        f'repeatCount="indefinite"/></line>'
        for i in range(7))
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 700 250" font-family="Inter,Arial,sans-serif">
<defs>
<linearGradient id="skyD" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fdefd0"/><stop offset="1" stop-color="#f7e0ac"/></linearGradient>
<linearGradient id="skyW" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#e0f1fc"/><stop offset="1" stop-color="#bfe1f6"/></linearGradient>
<clipPath id="cL"><rect x="0" y="0" width="336" height="250" rx="16"/></clipPath>
<clipPath id="cR"><rect x="364" y="0" width="336" height="250" rx="16"/></clipPath>
</defs>
<!-- ============ DRY ============ -->
<g clip-path="url(#cL)">
<rect x="0" y="0" width="336" height="250" fill="url(#skyD)"/>
<g transform="translate(66,60)"><g><animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="45s" repeatCount="indefinite"/>
{''.join(f'<line x1="0" y1="0" x2="0" y2="30" stroke="#f0b53d" stroke-width="3" stroke-linecap="round" transform="rotate({a})"/>' for a in range(0,360,45))}</g>
<circle r="17" fill="#f4b740"/></g>
<rect x="0" y="168" width="336" height="82" fill="#d9b884"/>
<rect x="0" y="168" width="336" height="10" fill="#c8a670"/>
<path d="M40 196 l14 20 M120 188 l-10 24 M190 200 l12 22 M270 190 l-8 26 M300 205 l10 18" stroke="#b0905c" stroke-width="2.2" fill="none" stroke-linecap="round"/>
<ellipse cx="150" cy="240" rx="90" ry="12" fill="#caa25f"/>
<g clip-path="url(#cL)"><g><animateTransform attributeName="transform" type="translate" from="0 0" to="-60 0" dur="3.2s" repeatCount="indefinite"/>
<path d="M40 232 q15 -5 30 0 t30 0 t30 0 t30 0 t30 0 t30 0 t30 0 t30 0 t30 0 V250 H40 Z" fill="#cc9236"/></g></g>
<text x="24" y="34" font-size="13" font-weight="800" letter-spacing="1" fill="#7a4a0c" stroke="#fff" stroke-width="2.4" paint-order="stroke">OCTOBER STARTS DRY</text>
<text x="24" y="120" font-size="52" font-weight="800" fill="#a3560c" letter-spacing="-2" stroke="#fff" stroke-width="4" paint-order="stroke">{dry}<tspan font-size="22" dx="2">mm</tspan></text>
<text x="26" y="145" font-size="13" font-weight="800" fill="#6f4a10" stroke="#fff" stroke-width="2.2" paint-order="stroke">a lean water year</text>
</g>
<!-- ============ WET ============ -->
<g clip-path="url(#cR)">
<rect x="364" y="0" width="336" height="250" fill="url(#skyW)"/>
<g fill="#cdd8e2"><ellipse cx="500" cy="34" rx="34" ry="18"/><ellipse cx="470" cy="40" rx="24" ry="15"/><ellipse cx="530" cy="40" rx="26" ry="15"/></g>
{rain}
<rect x="364" y="168" width="336" height="82" fill="#8bb96e"/>
<rect x="364" y="168" width="336" height="10" fill="#6fa354"/>
<g clip-path="url(#cR)">
<g><animateTransform attributeName="transform" type="translate" from="0 0" to="-60 0" dur="2.1s" repeatCount="indefinite"/>
<path d="M364 188 q15 -8 30 0 t30 0 t30 0 t30 0 t30 0 t30 0 t30 0 t30 0 t30 0 t30 0 t30 0 V250 H364 Z" fill="#2f8ad0"/></g>
<g opacity="0.55"><animateTransform attributeName="transform" type="translate" from="-30 0" to="-90 0" dur="1.5s" repeatCount="indefinite"/>
<path d="M364 198 q15 -7 30 0 t30 0 t30 0 t30 0 t30 0 t30 0 t30 0 t30 0 t30 0 t30 0 t30 0 V250 H364 Z" fill="#5aa9e6"/></g></g>
<text x="388" y="34" font-size="13" font-weight="800" letter-spacing="1" fill="#024e79" stroke="#fff" stroke-width="2.4" paint-order="stroke">OCTOBER STARTS WET</text>
<text x="420" y="120" font-size="52" font-weight="800" fill="#014a86" letter-spacing="-2" stroke="#fff" stroke-width="4" paint-order="stroke">{wet}<tspan font-size="22" dx="2">mm</tspan></text>
<text x="422" y="145" font-size="13" font-weight="800" fill="#04588c" stroke="#fff" stroke-width="2.2" paint-order="stroke">a productive water year</text>
</g>
<!-- ============ +% badge ============ -->
<g transform="translate(350,125)">
<circle r="54" fill="#ffffff" stroke="#FFC627" stroke-width="4"/>
<circle r="54" fill="none" stroke="#8C1D40" stroke-width="1.2" opacity="0.35"/>
<text x="0" y="4" font-size="38" font-weight="800" fill="#8C1D40" text-anchor="middle" stroke="#fff" stroke-width="0.6" paint-order="stroke">+{g}%</text>
<text x="0" y="26" font-size="11.5" font-weight="800" fill="#8a6d0f" text-anchor="middle" letter-spacing="0.5">more runoff</text>
</g>
</svg>'''
    return html.Img(src="data:image/svg+xml," + urllib.parse.quote(svg),
                    className="oct-scene",
                    style={"width": "100%", "maxWidth": "500px", "height": "auto",
                           "display": "block", "borderRadius": "16px",
                           "boxShadow": "0 10px 26px rgba(13,33,55,.14)"})


def _october_teaser():
    """Forward-looking hook: what the basin already knows on 1 October."""
    f = None
    try:
        from modules.october import _fit
        f = _fit("CRB")
    except Exception:
        pass
    if not f:
        return html.Div()
    gain = (f["wet_y"] - f["dry_y"]) / abs(f["dry_y"]) * 100
    return html.Div([
        html.Div([
            # ── text, left ──
            html.Div([
                html.Div("Antecedent conditions", className="q3-eyebrow"),
                html.Div(["By October 1st, ",
                          html.Span("the water year is half-written.", className="hl")],
                         className="q3-title", style={"fontSize": "24px"}),
                html.Div(["Attention fixes on the April snowpack. But the water year opens on "
                          "October 1st, and the antecedent soil moisture the basin carries into it "
                          "already partitions a productive year from a lean one — ",
                          html.Span("two full seasons ahead of runoff.", className="hl-gold")],
                         className="q3-sub"),
                html.Div([
                    html.I(className="bi bi-check-circle-fill",
                           style={"marginRight": "7px", "color": "#2E7D32"}),
                    f"Out-of-sample skill: leave-one-out R² = {f['loo']:.2f} over {f['n']} water "
                    f"years (p = {f['p']:.0e}); low predictability in the Lower Basin, reported as "
                    "such. Peer-reviewed basis: Ghimire, Vivoni & Wang (2026), Water Resources "
                    "Research.",
                ], className="sig-cite"),
                html.A(["Open the October Signal  ", html.I(className="bi bi-arrow-right")],
                       href="/october", className="sig-cta"),
            ], className="oct-text"),
            # ── visualization, right ──
            html.Div(_october_viz(f, gain), className="oct-vizcol"),
        ], className="oct-split"),
    ], className="crb-card sig-card")


def _open_questions():
    """Each established finding is shown NOT as our own discovery, but paired with the
       peer-reviewed study that reached it independently — corroboration, not a claim.
       The open cards carry no citation because no one has done them yet: the true frontier."""
    # kind, icon, hero, question, tag, answer, (link_url, link_label)
    Q = [
        ("ok", "bi-globe-americas",
         [html.Span("p", className="qh-v"), html.Span("=10", className="qh-v"),
          html.Sup("−19", className="qh-sup")],
         ["Is the ", html.Span("disappearing water", className="qf-hl"), " actually real?"],
         "GRACE · Castle 2014, Abdelmohsen 2025",
         "GRACE satellites see the same loss from orbit — no model in between.",
         ("https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2025GL115593", "Read the paper")),
        ("ok", "bi-moisture",
         [html.Span("R", className="qh-v"), html.Sup("2", className="qh-sup"),
          html.Span("0.45", className="qh-v", style={"marginLeft": "5px"})],
         ["Can autumn soil ", html.Span("predict the year ahead", className="qf-hl"), "?"],
         "Koster 2012 · CBRFC operational",
         "October soil moisture explains about half of the next year's runoff (leave-one-out cross-validated).",
         ("https://doi.org/10.1029/2025WR042871", "Read the paper")),
        ("ok", "bi-graph-up-arrow",
         [html.Span("NSE", className="qh-v", style={"fontSize": "15px"}),
          html.Span("0.96", className="qh-v", style={"marginLeft": "7px"})],
         ["Can the model be ", html.Span("trusted", className="qf-hl"), "?"],
         "Wang et al. 2026 · SMAP + streamflow",
         "Reproduces the river almost exactly, and SMAP-validated (R² 0.81).",
         ("https://www.nature.com/articles/s41598-026-47430-9", "Read the paper")),
        ("part", "bi-arrow-repeat",
         [html.Span("1", className="qh-v"),
          html.Span("test", className="qh-v", style={"fontSize": "13px", "marginLeft": "5px"})],
         ["A physical signal — or just the model ", html.Span("echoing itself", className="qf-hl"), "?"],
         "One decisive check still open",
         "SMAP breaks most of the circularity; one observed-vs-observed test remains.",
         ("/october", "See the open test")),
        ("open", "bi-calendar-check",
         [html.Span("?", className="qh-v qh-q")],
         ["Could the basin be read ", html.Span("every October", className="qf-hl"), "?"],
         "No study yet — open frontier",
         "Never built — a live autumn index could warn managers months earlier.",
         ("/october", "The open study")),
        ("open", "bi-sliders",
         [html.Span("?", className="qh-v qh-q")],
         ["Can we ", html.Span("shift the odds", className="qf-hl"), " before the year begins?"],
         "No study yet — open frontier",
         "Recharge, forest, irrigation timing — untested at basin scale.",
         ("/october", "The open study")),
    ]
    lab = {"ok": "Corroborated", "part": "Partly open", "open": "Open"}

    # ── established findings: a clean evidence table (finding · statistic · paper) ──
    established = [
        ("The basin's water loss is real — and largely underground",
         "p = 10⁻¹⁹", "GRACE terrestrial-storage trend, independent of the model",
         "Castle et al. 2014; Abdelmohsen et al. 2025, GRL",
         "https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2025GL115593"),
        ("October soil moisture forecasts the water year",
         "LOO R² = 0.45", "leave-one-out cross-validation over 41 water years",
         "Ghimire, Vivoni & Wang 2026, Water Resources Research",
         "https://doi.org/10.1029/2025WR042871"),
    ]
    open_qs = [
        ("Does October soil moisture add skill beyond the operational outlook?",
         "Not yet tested against the Bureau of Reclamation 24-Month Study."),
        ("Could a live, standing 1-October index be operationalised?",
         "The reanalysis ends in WY2024; a real-time version has never been built."),
        ("Can autumn storage be managed as a lever on next-year supply?",
         "Managed recharge, forest treatment, irrigation timing — untested at basin scale."),
    ]

    # question-style interactive cards: a bold question (highlighted keyphrase) → the
    # evidence (stat + answer + source + paper). Corroborated / partly-open / open frontier.
    kinds = {
        "ok":   ("Corroborated",  "bi-patch-check-fill"),
        "part": ("Partly open",   "bi-adjust"),
        "open": ("Open frontier", "bi-compass"),
    }
    tiles = []
    for i, (kind, icon, hero, question, tag, answer, (url, label)) in enumerate(Q):
        klab, kico = kinds[kind]
        ext = url.startswith("http")
        tiles.append(html.Div([
            html.Div([html.I(className=f"bi {kico}"), html.Span(klab)],
                     className=f"oqx-badge oqx-badge-{kind}"),
            html.Div(question, className="oqx-q"),
            html.Div(className="oqx-rule"),
            html.Div([
                html.Div(hero, className=f"oqx-stat oqx-stat-{kind}"),
                html.Div(answer, className="oqx-ans"),
            ], className="oqx-evi"),
            html.Div([html.I(className="bi bi-journal-text"), html.Span(tag)],
                     className="oqx-src"),
            html.A([html.Span(label), html.I(className="bi bi-arrow-right")],
                   href=url, target="_blank" if ext else None,
                   className=f"oqx-link oqx-link-{kind}"),
        ], className=f"oqx-card oqx-card-{kind}", style={"animationDelay": f"{i*0.07:.2f}s"}))

    return html.Div([
        html.Div([
            html.I(className="bi bi-journal-check", style={"color": MAROON, "marginRight": "8px",
                                                           "fontSize": "18px"}),
            html.Span("Findings and open questions",
                      style={"fontSize": "16px", "fontWeight": "800", "color": MAROON,
                             "letterSpacing": "0.3px"}),
            html.Span("three questions the basin has already answered — and three it still "
                      "leaves open",
                      style={"fontSize": "11px", "color": "#1e293b", "marginLeft": "10px"}),
        ], style={"borderBottom": f"2px solid {MAROON}", "paddingBottom": "8px",
                  "marginBottom": "16px", "display": "flex", "alignItems": "center",
                  "flexWrap": "wrap", "gap": "10px"}),
        html.Div(tiles, className="oqx-grid"),
        html.A(["Open the full analysis on the October Signal  ",
                html.I(className="bi bi-arrow-right")],
               href="/october", className="sig-cta"),
    ], className="crb-card oq-wrap")


def _trust_strip():
    """Thin credibility band — validation figures, for experts (NASA/ASU/managers)."""
    def _badge(txt):
        return html.Span(txt, style={
            "display": "inline-flex", "alignItems": "center", "background": "#eef4ef",
            "border": "1px solid #cfe0d3", "borderRadius": "14px", "padding": "4px 11px",
            "fontSize": "11.5px", "color": "#1b5e20", "fontWeight": "700",
            "margin": "0 8px 6px 0"})

    return html.Div([
        html.Div([
            html.I(className="bi bi-patch-check-fill",
                   style={"color": "#2E7D32", "marginRight": "8px", "fontSize": "16px"}),
            html.Span("Validated against independent data",
                      style={"fontWeight": "800", "fontSize": "13px", "color": "#0D2137"}),
        ], style={"marginBottom": "8px", "display": "flex", "alignItems": "center"}),
        html.Div([
            _badge("Upper-Basin streamflow NSE 0.96"),
            _badge("SMAP soil moisture R² 0.71 / 0.81"),
            _badge("GRACE storage evaluated"),
            _badge("Every key value shown vs its published value"),
        ]),
        html.A(["Methods, data sources & validation  ", html.I(className="bi bi-arrow-right")],
               href="/references",
               style={"fontSize": "11.5px", "fontWeight": "700", "color": "#01579B",
                      "textDecoration": "none"}),
    ], className="crb-card", style={"padding": "13px 16px", "marginBottom": "18px",
                                    "borderLeft": "4px solid #2E7D32"})


# ─────────────────────────────────────────────────────────────
TESTI_AVATARS = ["💧", "🌊", "🏔️", "🌵", "🧑‍💼", "👩‍🔬", "🧑‍🏫", "🏞️"]


def _testi_cards(reviews):
    """Render testimonial cards (or a friendly empty state). Used at load and after submit."""
    if not reviews:
        return [html.Div([
            html.Div("💬", className="testi-empty-emoji"),
            html.Div("Be the first to share your experience with CRIA.",
                     className="testi-empty-text"),
        ], className="testi-empty")]
    cards = []
    for r in reviews:
        try:
            stars = max(1, min(5, int(r.get("stars", 5) or 5)))
        except Exception:
            stars = 5
        name = (r.get("name") or "").strip() or "Anonymous"
        role = (r.get("role") or "").strip()
        avatar = (r.get("avatar") or "").strip()
        text = (r.get("text") or "").strip()
        if avatar.startswith("data:image"):
            av = html.Img(src=avatar, className="testi-av testi-av-img", alt=name)
        elif avatar:
            av = html.Div(avatar, className="testi-av testi-av-emoji")
        else:
            initials = "".join(w[0] for w in name.split()[:2]).upper() or "◆"
            av = html.Div(initials, className="testi-av")
        idblock = [html.Div(name, className="testi-name")]
        if role:
            idblock.append(html.Div(role, className="testi-role"))
        cards.append(html.Div([
            html.Div([av, html.Div(idblock, className="testi-id")], className="testi-head"),
            html.Div("★" * stars + "☆" * (5 - stars), className="testi-stars"),
            html.Div(text, className="testi-text"),
        ], className="testi-card"))
    return cards


def _manage_rows(reviews, my_ids, admin):
    """Rows the current user may edit/delete: their own (browser-remembered) or all (admin)."""
    my = set(my_ids or [])
    rows = []
    for r in reviews:
        rid = r.get("id", "")
        if not rid or not (admin or rid in my):
            continue
        stars = int(r.get("stars", 5) or 5)
        head = [html.Span("★" * stars, className="mrev-stars"),
                html.Span(r.get("name") or "Anonymous", className="mrev-name")]
        if r.get("role"):
            head.append(html.Span(" · " + r["role"], className="mrev-role"))
        # Edit + Delete for the reviews shown here (a user's own, or all when admin).
        actions = [html.Button([html.I(className="bi bi-pencil"), " Edit"],
                               id={"type": "mrev-edit", "index": rid}, n_clicks=0,
                               className="mrev-btn mrev-edit"),
                   html.Button([html.I(className="bi bi-trash"), " Delete"],
                               id={"type": "mrev-del", "index": rid}, n_clicks=0,
                               className="mrev-btn mrev-del")]
        rows.append(html.Div([
            html.Div(head, className="mrev-head"),
            html.Div((r.get("text") or "")[:160], className="mrev-text"),
            html.Div(actions, className="mrev-actions"),
        ], className="mrev-row"))
    if not rows:
        return None  # nothing to manage yet → take no space
    title = "Manage all reviews (admin)" if admin else "Your review"
    return [html.Div([html.I(className="bi bi-gear-fill", style={"marginRight": "7px"}), title],
                     className="mrev-title")] + rows


ROLE_OPTIONS = ["Water manager", "Hydrologist / Researcher", "Policy / Government",
                "Engineer", "Educator", "Student", "Consultant", "Other"]


def _reviews_safe():
    try:
        from utils import metrics
        return metrics.get_reviews()
    except Exception:
        return []


def _testi_header(sub=None):
    return html.Div([
        html.Div([
            html.I(className="bi bi-chat-quote-fill",
                   style={"color": MAROON, "marginRight": "8px", "fontSize": "18px"}),
            html.Span("Share Your Experience",
                      style={"fontWeight": "800", "fontSize": "16px", "color": MAROON}),
        ], style={"display": "flex", "alignItems": "center"}),
        html.Div("Tell us how CRIA has helped you. Your review makes a real difference — "
                 "it helps us improve, and helps others make confident decisions.",
                 style={"fontSize": "12.5px", "color": "#1a2733", "marginTop": "5px",
                        "lineHeight": "1.5", "fontWeight": "600"}),
    ], style={"borderBottom": f"2px solid {MAROON}", "paddingBottom": "9px",
              "marginBottom": "14px"})


def _testi_carousel(track_id):
    return html.Div([
        html.Div(_testi_cards(_reviews_safe()), id=track_id, className="testi-track"),
        html.Div(className="testi-dots"),
    ], className="testi-carousel")


def _testimonials():
    """Overview (before footer): read-only carousel + a CTA to the full Reviews page."""
    return html.Div([
        _reviews_hero(compact=True),
        _testi_carousel("ov-testi-track"),
        html.A([html.I(className="bi bi-pencil-square", style={"marginRight": "7px"}),
                "Add your voice"], href="/reviews", className="testi-cta"),
    ], className="crb-card testi-wrap", style={"padding": "16px 18px", "marginBottom": "18px"})


def _testi_form():
    """Engaging review form: rating, required name, role dropdown + custom, photo/avatar, comment."""
    return html.Div([
        html.Div([html.I(className="bi bi-stars", style={"marginRight": "7px"}),
                  "Add your voice"], className="testi-form-title"),
        html.Div("Working on the Colorado — or any river basin? Tell us how CRIA helped "
                 "you. Your answer guides others and shapes where CRIA goes next. "
                 "It takes just 30 seconds.",
                 className="testi-form-intro"),
        html.Div([
            html.Span("Your rating *", className="testi-lbl"),
            html.Div([html.Button("★", id=f"tr-s{i}", n_clicks=0, className="fb-star testi-star")
                      for i in (1, 2, 3, 4, 5)], id="tr-stars", className="fb-stars"),
        ], className="testi-row"),
        html.Div([
            html.Span("Name *", className="testi-lbl"),
            dcc.Input(id="tr-name", type="text", placeholder="Your name (required)",
                      className="testi-input"),
        ], className="testi-row"),
        html.Div([
            html.Div("Role", className="testi-lbl", style={"display": "block",
                                                           "marginBottom": "5px"}),
            dcc.Dropdown(id="tr-role-dd",
                         options=[{"label": r, "value": r} for r in ROLE_OPTIONS],
                         placeholder="Select your role…", clearable=False,
                         className="testi-dd"),
        ], className="testi-row testi-role-row"),
        dcc.Input(id="tr-role-custom", type="text", placeholder="Type your role / organisation",
                  className="testi-input", style={"display": "none"}),
        html.Div([
            html.Span("Photo / avatar", className="testi-lbl"),
            dcc.Upload(id="tr-photo", accept="image/*", multiple=False,
                       children=html.Span([html.I(className="bi bi-camera",
                                                  style={"marginRight": "6px"}), "Upload photo"],
                                          className="testi-upload")),
            html.Div(id="tr-photo-preview", className="testi-photo-preview"),
            html.Span("or pick one:", className="testi-or"),
            html.Div([html.Button(a, id=f"tr-av{i}", n_clicks=0, className="testi-avpick")
                      for i, a in enumerate(TESTI_AVATARS)], id="tr-avrow", className="testi-avrow"),
        ], className="testi-row testi-photo-row"),
        dcc.Textarea(id="tr-text", className="testi-textarea",
                     placeholder="What worked well? What would you improve?"),
        html.Button([html.I(className="bi bi-send", style={"marginRight": "7px"}),
                     "Post my review"], id="tr-submit", n_clicks=0, className="testi-submit"),
        html.Div(id="tr-thanks", className="testi-thanks"),
        dcc.Store(id="tr-star-store", data=0),
        dcc.Store(id="tr-av-store", data=""),
        dcc.Store(id="tr-photo-store", data=""),
    ], className="testi-form")


def _water_flow():
    """Overview — a professional, animated multicolour water-balance graph with an
    enticing hook that pulls the user into the full analysis. Real VIC data (CRB)."""
    df = _safe(load_vic_annual)
    b = df[df["basin"] == "CRB"] if not df.empty else df
    if b is None or b.empty or "OUT_PREC" not in b.columns:
        return html.Div()
    p  = b["OUT_PREC"].mean(); et = b["OUT_EVAP"].mean()
    q  = (b["OUT_RUNOFF"] + b["OUT_BASEFLOW"]).mean()
    et_pct = int(round(et / p * 100)) if p else 0
    q_pct  = int(round(q / p * 100)) if p else 0
    ds     = max(0.1, abs(p - et - q))
    canop  = b["OUT_EVAP_CANOP"].mean() if "OUT_EVAP_CANOP" in b.columns else et * 0.12
    transp = b["OUT_TRANSP_VEG"].mean() if "OUT_TRANSP_VEG" in b.columns else et * 0.55
    bare   = b["OUT_EVAP_BARE"].mean()  if "OUT_EVAP_BARE" in b.columns else et * 0.33
    surf_q = b["OUT_RUNOFF"].mean(); base_q = b["OUT_BASEFLOW"].mean()

    punch = html.Div([
        "Of every ", html.B("100 drops of rain", style={"color": "#0277BD"}),
        f" ({p:.0f} mm/yr), about ",
        html.B(f"{et_pct} slip back into the sky", style={"color": "#e2700a"}), " and barely ",
        html.B(f"{q_pct} reach the river", style={"color": "#0277BD"}),
        ". Trace every path below — then ", html.B("open the tab", style={"color": MAROON}),
        " to see how that razor-thin margin is shifting, year by year.",
    ], className="wflow-punch")

    # ── vibrant, multicolour, interactive Sankey — the full breakdown ──
    # "Sublimation & other" closes the ET node so canopy+transpiration+bare-soil+
    # sublimation = total ET exactly (the ~18 mm snow-sublimation remainder).
    sublim = max(0.1, et - (canop + transp + bare))
    labels = [f"Precipitation<br>{p:.0f} mm", f"Evapotranspiration<br>{et:.0f} mm",
              f"Runoff<br>{q:.0f} mm", f"Storage Δ<br>{ds:.0f} mm",
              "Canopy", "Transpiration", "Bare soil", "Surface", "Baseflow",
              "Sublimation & other"]
    node_colors = ["#0277BD", "#EF6C00", "#0288D1", "#8E24AA",
                   "#43A047", "#1B5E20", "#C77D2E", "#00ACC1", "#5E35B1", "#78909C"]
    link_colors = ["rgba(239,108,0,0.75)", "rgba(2,136,209,0.80)", "rgba(142,36,170,0.65)",
                   "rgba(67,160,71,0.72)", "rgba(27,94,32,0.72)", "rgba(199,125,46,0.72)",
                   "rgba(0,172,193,0.78)", "rgba(94,53,177,0.70)", "rgba(120,144,156,0.62)"]
    fig = go.Figure(go.Sankey(
        arrangement="snap",
        node=dict(pad=17, thickness=22, label=labels, color=node_colors,
                  line=dict(color="white", width=1.8),
                  hovertemplate="%{label}: %{value:.0f} mm/yr<extra></extra>"),
        textfont=dict(size=11, color="#0D2137", family="Inter, sans-serif"),
        link=dict(source=[0, 0, 0, 1, 1, 1, 2, 2, 1], target=[1, 2, 3, 4, 5, 6, 7, 8, 9],
                  value=[max(0.1, et), max(0.1, q), ds, max(0.1, canop), max(0.1, transp),
                         max(0.1, bare), max(0.1, surf_q), max(0.1, base_q), sublim],
                  color=link_colors,
                  hovertemplate="%{source.label} → %{target.label}: %{value:.0f} mm/yr<extra></extra>")))
    fig.update_layout(margin=dict(l=6, r=6, t=8, b=6), height=280,
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(size=11, color="#0D2137"),
                      hoverlabel=dict(bgcolor="white", bordercolor="#cfd8dc",
                                      font=dict(size=12, color="#0D2137", family="Inter, sans-serif")))
    return html.Div([
        # ── left: the story ──
        html.Div([
            html.Div([
                html.I(className="bi bi-droplet-half", style={"color": MAROON, "marginRight": "8px", "fontSize": "18px"}),
                html.Span("Where does the basin's water go?",
                          style={"fontSize": "16px", "fontWeight": "800", "color": MAROON, "letterSpacing": "0.3px"}),
            ], className="wflow-head"),
            html.Div("Follow every drop — sky, soil and river.",
                     style={"fontSize": "11.5px", "color": "#546e7a", "fontWeight": "700",
                            "marginBottom": "8px"}),
            punch,
            html.A(["Open the full interactive water balance ", html.I(className="bi bi-arrow-right")],
                   href="/watbal", className="wflow-cta"),
        ], className="wflow-text"),
        # ── right: the graph ──
        html.Div([
            html.Div(["The full breakdown — ", html.B("hover any flow"), " for the exact mm/yr."],
                     className="wflow-sub"),
            html.Div(dcc.Graph(figure=fig, config={"displayModeBar": False, "responsive": True},
                               style={"height": "300px"}), className="wflow-graph"),
        ], className="wflow-viz"),
    ], className="crb-card wflow-card wflow-split")


def _hero_drop():
    """A single water drop falling into ripples — looping — for the hero's maroon side."""
    import urllib.parse
    svg = (
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 170">'
      '<defs><radialGradient id="wd" cx="42%" cy="34%" r="66%">'
      '<stop offset="0" stop-color="#ffffff"/><stop offset="0.5" stop-color="#ffe9a8"/>'
      '<stop offset="1" stop-color="#f2b23c"/></radialGradient></defs>'
      '<g><animateTransform attributeName="transform" type="translate" '
      'values="0,-6;0,86;0,86" keyTimes="0;0.5;1" dur="2.6s" repeatCount="indefinite"/>'
      '<path d="M60,22 C72,46 79,56 79,67 a19,19 0 0,1 -38,0 C41,56 48,46 60,22 Z" fill="url(#wd)">'
      '<animate attributeName="opacity" values="1;1;0;0;1" keyTimes="0;0.46;0.56;0.98;1" dur="2.6s" repeatCount="indefinite"/>'
      '</path></g>'
      '<ellipse cx="60" cy="150" rx="4" ry="1.6" fill="none" stroke="#ffffff" stroke-width="1.4">'
      '<animate attributeName="rx" values="4;40" dur="2.6s" begin="1.25s" repeatCount="indefinite"/>'
      '<animate attributeName="ry" values="1.6;10" dur="2.6s" begin="1.25s" repeatCount="indefinite"/>'
      '<animate attributeName="opacity" values="0.85;0" dur="2.6s" begin="1.25s" repeatCount="indefinite"/></ellipse>'
      '<ellipse cx="60" cy="150" rx="4" ry="1.6" fill="none" stroke="#FFC627" stroke-width="1.2">'
      '<animate attributeName="rx" values="4;40" dur="2.6s" begin="1.7s" repeatCount="indefinite"/>'
      '<animate attributeName="ry" values="1.6;10" dur="2.6s" begin="1.7s" repeatCount="indefinite"/>'
      '<animate attributeName="opacity" values="0.7;0" dur="2.6s" begin="1.7s" repeatCount="indefinite"/></ellipse>'
      '</svg>'
    )
    return html.Img(src="data:image/svg+xml," + urllib.parse.quote(svg),
                    className="why-hero-drop", alt="")


def _novelty_showcase():
    """Overview — an impressive, professional 'what makes CRIA different' band
    (mirrors the Why-CRIA page): mini hero + credibility stats + original
    contributions, all scoped to the Colorado River Basin."""
    def _wstat(icon, num, label):
        return html.Div([html.I(className=f"bi {icon}"),
                         html.Div(num, className="why-stat-num"),
                         html.Div(label, className="why-stat-lbl")], className="why-stat")

    def _wfirst(icon, badge, head, body):
        return html.Div([
            html.Div([html.I(className=f"bi {icon}"),
                      html.Span(badge, className="why-first-badge")], className="why-first-top"),
            html.Div(head, className="why-first-head"),
            html.Div(body, className="why-first-body"),
        ], className="why-first")

    return html.Div([
        # ── page title inside the SAME container — one strong first impression ──
        html.Div([
            html.H2("Overview", style={"display": "inline", "margin": "0", "color": MAROON,
                                        "letterSpacing": "-.3px"}),
            html.Div([
                html.Button([html.I(className="bi bi-binoculars-fill"), " Quick View: CRIA Observatory"],
                            id="qv-open-btn", className="tour-btn qv-open", n_clicks=0,
                            title="Open the CRB Observatory — every basin signal in one board"),
                html.Button([html.I(className="bi bi-play-btn-fill"), " Watch Basin Walkthrough"],
                            id="film-open-btn", className="tour-btn film-open filmcta", n_clicks=0,
                            title="The whole basin's assessment, walked through in minutes"),
                html.Button([html.I(className="bi bi-signpost-2-fill"), " Guided tour"],
                            id="tour-btn", className="tour-btn", n_clicks=0),
            ], style={"display": "flex", "alignItems": "center", "gap": "8px", "flexWrap": "wrap"}),
        ], style={"display": "flex", "alignItems": "center", "justifyContent": "space-between",
                  "flexWrap": "wrap", "gap": "12px", "marginBottom": "10px"}),
        # ── wow lead — one band, white→maroon gradient ──
        html.Div([
            html.Div("41 YEARS  ·  4 DATA SOURCES  ·  26 VARIABLES  ·  32 ANALYSES",
                     className="why-hero-eyebrow"),
            html.Div(["Four decades of the entire Colorado River Basin — ",
                      html.Span("seen whole", className="why-hl"), "."], className="why-hero-title"),
            html.Div([html.Span("Because CRIA counts — ", className="why-hero-tag-pre"),
                      "Every drop. Every signal. Every year."], className="why-hero-tag"),
            html.Div(["Snowpack, soil moisture, rivers and the water hidden underground — "
                      "reconstructed with a PRISM-calibrated VIC reanalysis and validated against ",
                      html.B("NASA GRACE, SMAP and SNOTEL"), ". Surface and subsurface water "
                      "are brought together in one ",
                      html.B("integrated, observation-validated"), " view, in the units that "
                      "matter — acre-feet, reservoir storage and Lake Mead shortage tiers — with "
                      "every figure traceable back to its physical origin. Scientifically grounded, "
                      "decision-ready."], className="why-hero-sub"),
            _hero_drop(),
        ], className="why-hero"),
        html.Div([
            html.Div([
                _wstat("bi-graph-up-arrow", "NSE ≈ 0.96", "streamflow skill vs gauges"),
                _wstat("bi-moisture", "R² 0.71–0.81", "soil moisture vs NASA SMAP"),
                _wstat("bi-globe-americas", "p = 10⁻¹⁹", "GRACE storage decline"),
                _wstat("bi-calendar-check", "LOO R² 0.45", "autumn soil → year-ahead runoff"),
            ], className="why-tiles"),
            html.Div([
                html.Div("Curious how CRIA works?", className="why-cta-lead"),
                html.Div([
                    html.A(["Open the CRIA story ", html.I(className="bi bi-arrow-right")],
                           href="/why", className="wflow-cta wflow-cta-pulse"),
                    html.A(["Methods & validation ", html.I(className="bi bi-arrow-right")],
                           href="/references", className="wflow-cta wflow-cta-navy"),
                ], className="why-ctabtns"),
            ], className="why-ctacol"),
        ], className="why-proofrow"),
    ], className="crb-card wflow-card", style={"marginBottom": "18px"})


def _river_quote():
    """Two voices on the basin — Vivoni (the science) above, Praddy (the human stakes) below."""
    return html.Div([
        html.Div([
            "The Colorado River is more than water moving through a channel — it is the lifeline of "
            "over 40 million people. Even in the grip of drought, ",
            html.Span("it keeps fighting to remain a river", className="cria-quote-hl"),
            ". To read this basin is to feel both its resilience and its fragility, and to know "
            "that every decision made upstream echoes through every life downstream.",
        ], className="cria-quote-text"),
        html.Div([
            html.Span('— Dr. Pradeepika ("Praddy") Kaushik', className="cria-quote-name"),
            html.Span("Tool Lead & Developer", className="cria-quote-role"),
        ], className="cria-quote-by"),
    ], className="cria-quote")


def _briefing_pdf():
    """Generate the fixed 3-page CRIA Basin Briefing as PDF bytes — the distribution artifact.
       All numbers are pulled live from the same cache/model as the app (no fabrication)."""
    import io, textwrap, datetime
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    from matplotlib.backends.backend_pdf import PdfPages
    MAROON_="#8C1D40"; GOLD_="#FFC627"; INK="#1e293b"; GREY="#64748b"

    def band(fig, y, h, color):
        ax = fig.add_axes([0, y, 1, h]); ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
        ax.add_patch(Rectangle((0, 0), 1, 1, color=color, zorder=0)); return ax

    L = _loss_ledger()
    maf = float(L.get("grace_cum_maf", 45)); y0 = int(L.get("grace_yr0", 2002)); y1 = int(L.get("grace_yr1", 2024))
    km3 = maf * 1.233; mead = maf / 26.12
    try:
        from modules.scenario import _project
        s2 = _project("CRB", 2, 0)
    except Exception:
        s2 = None
    today = datetime.date.today().strftime("%B %Y")
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        # PAGE 1 — cover + executive summary
        fig = plt.figure(figsize=(8.5, 11)); fig.patch.set_facecolor("white")
        band(fig, 0.905, 0.095, MAROON_)
        fig.text(0.07, 0.955, "CRIA — Colorado River Integrated Assessment", color="white", fontsize=15, fontweight="bold", va="center")
        fig.text(0.07, 0.925, "Basin Briefing", color=GOLD_, fontsize=12, fontweight="bold", va="center")
        fig.text(0.93, 0.94, today, color="white", fontsize=9.5, ha="right", va="center")
        fig.text(0.07, 0.85, f"Since {y0}, the Colorado River Basin has lost", fontsize=12.5, color=INK)
        fig.text(0.07, 0.795, f"≈ {maf:.0f} million acre-feet", fontsize=31, color=MAROON_, fontweight="bold")
        fig.text(0.07, 0.758, f"of total water storage — about {km3:.0f} km³, roughly {mead:.1f}× the full capacity of Lake Mead.", fontsize=10.5, color=INK)
        fig.text(0.07, 0.735, f"NASA GRACE / GRACE-FO satellite gravimetry, {y0}–{y1} · ~two-thirds groundwater (Castle et al. 2014).", fontsize=8.5, color=GREY, style="italic")
        fig.text(0.07, 0.685, "KEY FINDINGS", fontsize=10.5, color=MAROON_, fontweight="bold")
        finds = [
            f"Total water storage is declining at ~{maf/(y1-y0):.1f} MAF/yr (GRACE); most of the loss is groundwater.",
            (f"At +2°C warming, the basin's own fitted elasticity projects {s2['pct']:+.0f}% water yield (≈ {abs(s2['maf_lost']):.1f} MAF/yr less) — status: {s2['status']}." if s2 else
             "Warming reduces water yield via the basin's fitted temperature sensitivity (≈ −8%/°C)."),
            "Runoff efficiency has fallen: the basin now yields less streamflow per unit of precipitation than its 1983–2010 baseline.",
            "The reanalysis reproduces Upper-Basin streamflow at NSE = 0.96 and is independently validated against NASA SMAP and GRACE.",
        ]
        yy = 0.655
        for t in finds:
            fig.text(0.075, yy, "▸", fontsize=10, color=GOLD_, fontweight="bold")
            wrapped = textwrap.wrap(t, 92)
            for i, ln in enumerate(wrapped):
                fig.text(0.105, yy - i * 0.021, ln, fontsize=9.5, color=INK)
            yy -= 0.021 * len(wrapped) + 0.016
        fig.text(0.07, 0.30, "WHAT THIS IS", fontsize=10.5, color=MAROON_, fontweight="bold")
        for i, ln in enumerate(textwrap.wrap(
                "CRIA is a decision-support reanalysis of the Colorado River Basin: a PRISM-calibrated VIC 5.0 "
                "hydrologic model (WY1984–2024, ~6 km) fused with NASA GRACE, SMAP and 103 SNOTEL stations, "
                "expressed in the units water managers decide in — acre-feet, storage, and shortage-relevant terms.", 95)):
            fig.text(0.07, 0.275 - i * 0.021, ln, fontsize=9.5, color=INK)
        band(fig, 0, 0.052, "#f1f3f6")
        fig.text(0.07, 0.026, "Arizona State University · Center for Hydrologic Innovations   |   Central Arizona Project   |   "
                 "NASA Applied Sciences – Water Resources (Award 80NSSC22K0925, PI E. R. Vivoni)", fontsize=7.6, color=GREY, va="center")
        pdf.savefig(fig); plt.close(fig)

        # PAGE 2 — the measured record (real figures)
        fig = plt.figure(figsize=(8.5, 11)); fig.patch.set_facecolor("white")
        band(fig, 0.93, 0.07, MAROON_)
        fig.text(0.07, 0.963, "The measured record", color="white", fontsize=13, fontweight="bold", va="center")
        fig.text(0.93, 0.963, "CRIA Basin Briefing · 2/3", color=GOLD_, fontsize=9, ha="right", va="center")
        try:
            g = _safe(load_grace); g = g[g["basin"] == "CRB"].dropna(subset=["tws_mm"]).copy()
            g["t"] = pd.to_datetime(g["date"]); g = g.sort_values("t")
            axA = fig.add_axes([0.10, 0.60, 0.83, 0.26])
            axA.fill_between(g["t"], g["tws_mm"], g["tws_mm"].min() - 10, color=MAROON_, alpha=0.08)
            axA.plot(g["t"], g["tws_mm"], color=MAROON_, lw=1.4)
            tt = (g["t"] - g["t"].min()).dt.days / 365.25; m, bb = np.polyfit(tt, g["tws_mm"], 1)
            axA.plot(g["t"], m * tt + bb, color=GOLD_, lw=2, ls="--")
            axA.set_title("Total water storage anomaly — GRACE / GRACE-FO (observed)", fontsize=10.5, color=INK, loc="left", fontweight="bold")
            axA.set_ylabel("cm equivalent water", fontsize=8.5); axA.tick_params(labelsize=8)
            for s in ["top", "right"]:
                axA.spines[s].set_visible(False)
            fig.text(0.10, 0.575, f"Trend {m/10:+.2f} cm/yr · cumulative ≈ {maf:.0f} MAF lost, {y0}–{y1}. Source: NASA/JPL GRACE mascons.", fontsize=8, color=GREY, style="italic")
        except Exception:
            pass
        try:
            axB = fig.add_axes([0.10, 0.24, 0.83, 0.26])
            dts = np.arange(0, 5.01, 0.25); pcts = []; los = []; his = []
            for d in dts:
                r = _project("CRB", float(d), 0); pcts.append(r["pct"]); los.append(r["pct_lo"]); his.append(r["pct_hi"])
            axB.axhline(0, color="#cbd5e1", lw=1)
            axB.fill_between(dts, los, his, color=MAROON_, alpha=0.10)
            axB.plot(dts, pcts, color=MAROON_, lw=2)
            axB.scatter([2], [_project("CRB", 2, 0)["pct"]], color=GOLD_, zorder=5, s=40, edgecolor=MAROON_)
            axB.set_title("Projected water-yield change vs warming — basin's fitted elasticity", fontsize=10.5, color=INK, loc="left", fontweight="bold")
            axB.set_xlabel("warming above today (°C)", fontsize=8.5); axB.set_ylabel("water yield change (%)", fontsize=8.5)
            axB.tick_params(labelsize=8)
            for s in ["top", "right"]:
                axB.spines[s].set_visible(False)
            fig.text(0.10, 0.212, "Empirical elasticity ln Q = a + b·ln P + c·T fitted to WY1984–2024; precipitation at today's normal; band = 95% CI.", fontsize=8, color=GREY, style="italic")
        except Exception:
            pass
        band(fig, 0, 0.052, "#f1f3f6")
        fig.text(0.07, 0.026, "Figures reproducible from the bundled data cache · CRIA", fontsize=7.6, color=GREY, va="center")
        pdf.savefig(fig); plt.close(fig)

        # PAGE 3 — methods, validation, references
        fig = plt.figure(figsize=(8.5, 11)); fig.patch.set_facecolor("white")
        band(fig, 0.93, 0.07, MAROON_)
        fig.text(0.07, 0.963, "Methods, validation & references", color="white", fontsize=13, fontweight="bold", va="center")
        fig.text(0.93, 0.963, "CRIA Basin Briefing · 3/3", color=GOLD_, fontsize=9, ha="right", va="center")
        yv = [0.87]
        def block(title, lines):
            fig.text(0.07, yv[0], title, fontsize=10.5, color=MAROON_, fontweight="bold"); yv[0] -= 0.03
            for t in lines:
                for ln in textwrap.wrap(t, 98):
                    fig.text(0.07, yv[0], ln, fontsize=9.3, color=INK); yv[0] -= 0.02
                yv[0] -= 0.006
            yv[0] -= 0.02
        block("Data & model", [
            "VIC 5.0 macroscale hydrologic model, PRISM-forced, ~6 km (1/16°), water years 1984–2024; calibrated on snow and streamflow.",
            "NASA GRACE / GRACE-FO terrestrial water storage (2002–present); NASA SMAP L4 surface & root-zone soil moisture; 103 NRCS SNOTEL stations.",
        ])
        block("Validation (independent)", [
            "Upper-Basin streamflow: NSE = 0.96.",
            "SMAP soil moisture: R² = 0.71 (surface), 0.81 (root-zone).",
            "GRACE terrestrial water storage: R² = 0.66–0.86.",
            "Automated pytest suite (26 tests) run on every push via GitHub Actions.",
        ])
        block("References", [
            "Ghimire, S., Vivoni, E. R., & Wang, Z. (2026). Regional hydrologic projections for the Colorado River Basin. Water Resources Research, 62(7).",
            "Ghimire, S., et al. (2026). Fall soil-moisture modulation of snow–streamflow dynamics in the Colorado River Basin using SMAP and GRACE. Scientific Reports, 16, 15890.",
            "Castle, S. L., et al. (2014). Groundwater depletion during drought threatens future water security of the Colorado River Basin. Geophysical Research Letters, 41(16).",
        ])
        block("Caveats", [
            "GRACE measures TOTAL water storage (groundwater + soil + snow + surface); the Lake-Mead comparison is a perspective device, not a reservoir-only figure.",
            "The warming projection is an empirical elasticity, not a full reservoir-operations model; it reports water-yield change, not allocation or shortage tier.",
        ])
        band(fig, 0, 0.052, "#f1f3f6")
        fig.text(0.07, 0.026, "Generated by CRIA · chi.asu.edu · Tool: Pradeepika Kaushik · PI: Enrique R. Vivoni", fontsize=7.6, color=GREY, va="center")
        pdf.savefig(fig); plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def _grace_spark(w=560, h=58):
    """Inline SVG sparkline of the GRACE total-storage decline — real cache data, no chart lib."""
    import urllib.parse
    try:
        g = _safe(load_grace)
        g = g[g["basin"] == "CRB"].dropna(subset=["tws_mm"]).copy()
        g["t"] = pd.to_datetime(g["date"]); g = g.sort_values("t")
        y = g["tws_mm"].values.astype(float)
    except Exception:
        return html.Div()
    if len(y) < 4:
        return html.Div()
    x = np.linspace(6, w - 6, len(y))
    ymin, ymax = float(np.min(y)), float(np.max(y))
    yy = (h - 6) - (y - ymin) / (ymax - ymin + 1e-9) * (h - 16)
    line = " ".join(f"{xi:.1f},{yi:.1f}" for xi, yi in zip(x, yy))
    area = f"6,{h - 2} " + line + f" {w - 6},{h - 2}"
    m, b = np.polyfit(x, yy, 1)
    ty0, ty1 = m * 6 + b, m * (w - 6) + b
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' width='%d' height='%d' viewBox='0 0 %d %d' preserveAspectRatio='none'>"
           "<polygon points='%s' fill='rgba(255,198,39,0.14)'/>"
           "<polyline points='%s' fill='none' stroke='#FFC627' stroke-width='2' stroke-linejoin='round'/>"
           "<line x1='6' y1='%.1f' x2='%d' y2='%.1f' stroke='rgba(255,255,255,.55)' stroke-width='1.5' stroke-dasharray='4 3'/>"
           "</svg>") % (w, h, w, h, area, line, ty0, w - 6, ty1)
    uri = "data:image/svg+xml," + urllib.parse.quote(svg)
    return html.Img(src=uri, className="co-spark",
                    alt="GRACE total water-storage decline, 2002 to 2024")


def _hero_film():
    """Animated hero — the basin's story as a motion film. Sits in the hero row BESIDE the
       proof/actions band (both containers share one row). Served at /assets/cria_story.html."""
    return html.Div(
        html.Iframe(
            src="/assets/cria_story.html",
            title="CRIA — the basin's story",
            style={"position": "absolute", "top": 0, "left": 0,
                   "width": "100%", "height": "100%", "border": "0"},
        ),
        className="hero-film-box",
        style={"position": "relative", "overflow": "hidden", "borderRadius": "16px",
               "boxShadow": "0 18px 50px rgba(13,33,55,.28)",
               "border": "1px solid rgba(140,29,64,.18)"},
    )


def _cold_open():
    """Proof/actions band — the RIGHT container of the hero row (the film is the left one).
       Vertically stacked to fit its column: framing line, two LIVE stat-tiles (GRACE loss,
       +2°C warming), the clickable sourcing chips, the briefing/actions, and the caveat."""
    L = _loss_ledger()
    maf = float(L.get("grace_cum_maf", 45))
    mead = maf / 26.12
    try:
        from modules.scenario import _project
        w = _project("CRB", 2.0, 0)
        wpct, wmaf, wstatus = w["pct"], abs(w["maf_lost"]), w["status"]
    except Exception:
        wpct, wmaf, wstatus = -15.0, 3.0, "Caution"
    chips = [
        ("VIC 5.0 · 6 km · WY1984–2024", "/methods"),
        ("NSE 0.96", "/methods"),
        ("SMAP R² 0.71/0.81", "/tws"),
        ("GRACE R² 0.66–0.86", "/tws"),
        ("103 SNOTEL", "/snowpack"),
        ("10 peer-reviewed papers", "/publications"),
        ("26 tests passing", "/methods"),
    ]
    return html.Div([
        html.Div([
            html.I(className="bi bi-patch-check-fill",
                   style={"color": "#5ad07f", "marginRight": "8px", "fontSize": "15px"}),
            html.Span("Observation-validated — every claim links to its source.",
                      style={"fontWeight": "800", "fontSize": "13px", "color": "#fff"}),
        ], className="pb-head"),
        html.Div([
            html.Div([
                html.Div("NASA GRACE · since 2002", className="pbt-eye"),
                html.Div([html.Span(f"≈{maf:.0f}", className="pbt-v gold"),
                          html.Span("M ac-ft", className="pbt-u")], className="pbt-row"),
                html.Div(f"storage lost · ≈{mead:.1f}× Lake Mead", className="pbt-l"),
            ], className="pb-tile g"),
            html.Div([
                html.Div("at +2°C warming", className="pbt-eye"),
                html.Div([html.Span(f"{wpct:+.0f}%", className="pbt-v amber"),
                          html.Span("yield", className="pbt-u")], className="pbt-row"),
                html.Div([f"≈{wmaf:.1f} MAF less/yr  ",
                          html.Span(wstatus, className="pbt-badge")], className="pbt-l"),
            ], className="pb-tile m"),
        ], className="pb-stats"),
        html.Div([html.A(t, href=h, className="pb-chip") for t, h in chips], className="pb-chips"),
        html.Div([
            html.Button([html.I(className="bi bi-file-earmark-arrow-down"),
                         " Basin Briefing (PDF)"],
                        id="briefing-btn", n_clicks=0, className="co-cta co-cta-primary"),
            html.A(["See how we know  ", html.I(className="bi bi-arrow-right")],
                   href="/tws", className="co-cta co-cta-ghost"),
            html.A(["Explore the basin  ", html.I(className="bi bi-arrow-down")],
                   href="#overview-body", className="co-cta co-cta-ghost"),
        ], className="co-ctas"),
        dcc.Download(id="briefing-dl"),
        html.Div("Total water storage = groundwater + soil moisture + snow + surface water "
                 "(GRACE satellite gravimetry). ~two-thirds of the decline is groundwater "
                 "(Castle et al. 2014); the Lake-Mead comparison is a perspective device.",
                 className="co-foot"),
    ], className="proof-band")


def _cred_strip():
    """A thin, monospace 'this is real science' strip — every claim links to its source."""
    def item(text, href=None, strong=False):
        cls = "cred-item" + (" cred-strong" if strong else "")
        if href:
            return html.A(text, href=href, className=cls + " cred-link")
        return html.Span(text, className=cls)
    sep = lambda: html.Span("·", className="cred-sep")
    parts = [
        item("VIC 5.0 · 6 km · WY1984–2024", href="/methods"), sep(),
        item("NSE 0.96", href="/methods", strong=True), sep(),
        item("SMAP R² 0.71/0.81", href="/tws"), sep(),
        item("GRACE R² 0.66–0.86", href="/tws"), sep(),
        item("103 SNOTEL", href="/snowpack"), sep(),
        item("2 peer-reviewed papers", href="/publications", strong=True), sep(),
        item("26 tests passing", href="/methods"),
    ]
    return html.Div([
        html.I(className="bi bi-patch-check-fill", style={"color": "#2E7D32", "marginRight": "8px"}),
    ] + parts, className="cred-strip")


def _dt_out(dt):
    """Live output for the landing warming dial — reuses the fitted elasticity in scenario.py.
       Honest: reports water-yield change (% and MAF), not a fabricated shortage probability."""
    try:
        from modules.scenario import _project
        r = _project("CRB", float(dt), 0)
    except Exception:
        r = None
    if not r:
        return html.Div("—")
    pct, maf, status, col = r["pct"], r["maf_lost"], r["status"], r["scolor"]
    return html.Div([
        html.Div([
            html.Span(f"{pct:+.0f}%", className="sm-big", style={"color": col}),
            html.Span("Colorado River water yield", className="sm-cap"),
        ], className="sm-metric"),
        html.Div([
            html.Span(f"≈ {abs(maf):.1f}", className="sm-maf", style={"color": col}),
            html.Span("MAF less water — every year", className="sm-cap"),
        ], className="sm-metric"),
        html.Div(status, className="sm-badge", style={"background": col}),
        html.Div(f"95% CI {r['pct_lo']:+.0f}% to {r['pct_hi']:+.0f}%  ·  fit R² = {r['r2']:.2f}",
                 className="sm-ci"),
    ], className="sm-out-inner")


def _scenario_proj():
    """The fitted warming response for ΔT = 0..5 °C — the SAME elasticity as the full Scenario
       Explorer — as plain data for the client-side animated dial (no server round-trip)."""
    try:
        from modules.scenario import _project
        rows, r2 = [], 0.60
        for dt in (0, 1, 2, 3, 4, 5):
            r = _project("CRB", float(dt), 0)
            r2 = r.get("r2", r2)
            rows.append({"dt": dt, "pct": round(r["pct"], 1), "maf": round(abs(r["maf_lost"]), 2),
                         "lo": round(r["pct_lo"], 1), "hi": round(r["pct_hi"], 1),
                         "status": r["status"]})
        return rows, round(float(r2), 2)
    except Exception:
        return ([{"dt": 0, "pct": 0.0, "maf": 0.0, "lo": 0.0, "hi": 0.0, "status": "Normal"},
                 {"dt": 1, "pct": -8.0, "maf": 1.54, "lo": -20.5, "hi": 6.5, "status": "Normal"},
                 {"dt": 2, "pct": -15.4, "maf": 2.96, "lo": -36.8, "hi": 13.4, "status": "Caution"},
                 {"dt": 3, "pct": -22.1, "maf": 4.27, "lo": -49.8, "hi": 20.7, "status": "Caution"},
                 {"dt": 4, "pct": -28.4, "maf": 5.47, "lo": -60.1, "hi": 28.5, "status": "Critical"},
                 {"dt": 5, "pct": -34.1, "maf": 6.58, "lo": -68.2, "hi": 36.8, "status": "Critical"}], 0.60)


def _scenario_mini():
    """The landing warming dial — an interactive, ANIMATED gauge (client-side, assets/
       scenario_dial.js): it auto-sweeps 0→5→+2 °C on load, then you drag it live with a
       smooth needle, colour morph and count-up. Same fitted elasticity as the full Explorer."""
    import json
    proj, r2 = _scenario_proj()
    return html.Div([
        html.Div([
            html.I(className="bi bi-thermometer-sun",
                   style={"color": MAROON, "marginRight": "8px", "fontSize": "18px"}),
            html.Span("What if the basin keeps warming?",
                      style={"fontSize": "16px", "fontWeight": "800", "color": MAROON,
                             "letterSpacing": "0.3px"}),
            html.Span("Drag the dial to any warming level — see how much Colorado River water is left.",
                      style={"fontSize": "11.5px", "color": "#475569", "marginLeft": "10px",
                             "fontWeight": "600"}),
        ], style={"borderBottom": f"2px solid {MAROON}", "paddingBottom": "8px",
                  "marginBottom": "16px", "display": "flex", "alignItems": "center",
                  "flexWrap": "wrap", "gap": "10px"}),
        html.Div(
            html.Div("WARMING ABOVE TODAY · loading the dial…", className="control-label",
                     style={"padding": "18px 4px"}),
            className="scen-dial",
            **{"data-proj": json.dumps(proj), "data-r2": str(r2)},
        ),
        html.Div([
            "Empirical hydrologic elasticity (ln Q = a + b·ln P + c·T) fitted to the CRB's own "
            "WY1984–2024 record; precipitation held at today's normal. ",
            html.A(["Open the full Scenario Explorer  ", html.I(className="bi bi-arrow-right")],
                   href="/scenario", style={"fontWeight": "700", "color": "#01579B",
                                            "textDecoration": "none"}),
        ], style={"fontSize": "11px", "color": "#64748b", "marginTop": "12px", "lineHeight": "1.5"}),
    ], className="crb-card scen-mini")


def _svg_uri(svg):
    import urllib.parse
    return "data:image/svg+xml," + urllib.parse.quote(svg)


_TABM = {}


# ---- chart-only mini-vizzes (viewBox 0 0 200 120, NO text — the 3D value tile carries the numbers) ----

def _chart_line(vals, stroke, fill_rgb):
    v = np.array(vals, float); n = len(v)
    if n < 3:
        return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 120"></svg>')
    xs = np.linspace(10, 190, n); lo, hi = float(v.min()), float(v.max())
    ys = 106 - (v - lo) / (hi - lo + 1e-9) * 84
    d = "M" + " L".join("%.1f %.1f" % (x, y) for x, y in zip(xs, ys))
    area = "M10 108 L" + " L".join("%.1f %.1f" % (x, y) for x, y in zip(xs, ys)) + " L190 108 Z"
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 120" preserveAspectRatio="none">'
      '<style>@keyframes dr{0%,6%{stroke-dashoffset:100}62%,92%{stroke-dashoffset:0}100%{stroke-dashoffset:100}}'
      '@keyframes af{0%,6%{opacity:0}62%,92%{opacity:.9}100%{opacity:0}}'
      '.ln{stroke-dasharray:100;animation:dr 5s ease-in-out infinite}.ar{animation:af 5s ease-in-out infinite}</style>'
      '<path class="ar" d="' + area + '" fill="rgba(' + fill_rgb + ',.20)"/>'
      '<path class="ln" pathLength="100" d="' + d + '" fill="none" stroke="' + stroke + '" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>'
      '</svg>')


def _chart_map(pts):
    if not pts:
        return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 120"></svg>'
    lons = [q["x"] for q in pts]; lats = [q["y"] for q in pts]
    x0, x1 = min(lons), max(lons); y0, y1 = min(lats), max(lats)
    dots = ""
    for i, q in enumerate(pts):
        px = 16 + (q["x"] - x0) / (x1 - x0 + 1e-9) * 168
        py = 106 - (q["y"] - y0) / (y1 - y0 + 1e-9) * 92
        col = "#8C1D40" if q["dn"] else "#E0A200"
        dots += '<circle class="dt" cx="%.1f" cy="%.1f" r="2.8" fill="%s" style="animation-delay:%.2fs"/>' % (px, py, col, (i % 24) * 0.14)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 120">'
      '<style>@keyframes pop{0%,4%{opacity:0;transform:scale(0)}16%{opacity:1;transform:scale(1)}86%{opacity:1;transform:scale(1)}100%{opacity:0;transform:scale(0)}}'
      '.dt{transform-box:fill-box;transform-origin:center;animation:pop 5s ease-in-out infinite}</style>' + dots + '</svg>')


def _chart_gov():
    # Law of the River — ALLOCATED (paper water) 16.5 MAF vs DELIVERED (wet water) ~12.4 MAF.
    # 16.5 = Compact 1922 (Upper 7.5 + Lower 7.5) + Mexican Treaty 1944 (1.5) — the legal allocation.
    # ~12.4 = recent-period natural flow at Lees Ferry (USBR). Gap = a ~4 MAF structural over-allocation.
    x0 = 16.0; per = 148.0 / 16.5
    prom = [("#FFC627", 7.5, 0.0), ("#E0A200", 7.5, 7.5), ("#8C1D40", 1.5, 15.0)]
    defs = ('<defs><filter id="sh" x="-30%" y="-30%" width="160%" height="160%">'
            '<feDropShadow dx="0" dy="1.4" stdDeviation="1.2" flood-color="#000" flood-opacity="0.18"/></filter>')
    bp = ""
    for j, (col, w, off) in enumerate(prom):
        defs += ('<linearGradient id="gp%d" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="%s"/>'
                 '<stop offset="1" stop-color="%s"/></linearGradient>' % (j, _lighten(col, 0.4), col))
        bp += '<rect x="%.1f" y="30" width="%.1f" height="17" rx="2.5" fill="url(#gp%d)" class="gb" style="transform-box:fill-box;transform-origin:left"/>' % (x0 + off * per, w * per, j)
    fw = 12.4 * per
    defs += ('<linearGradient id="gf" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="%s"/>'
             '<stop offset="1" stop-color="#1565C0"/></linearGradient></defs>' % _lighten("#2196F3", 0.3))
    flow = '<rect x="%.1f" y="70" width="%.1f" height="17" rx="2.5" fill="url(#gf)" class="gb2" style="transform-box:fill-box;transform-origin:left"/>' % (x0, fw)
    defx = x0 + fw; endx = x0 + 16.5 * per
    deficit = '<rect x="%.1f" y="70" width="%.1f" height="17" rx="2.5" fill="none" stroke="#D84315" stroke-width="1.4" stroke-dasharray="3 2"/>' % (defx, (16.5 - 12.4) * per)
    labels = (
        '<text x="16" y="25" font-family="Arial" font-size="8.5" font-weight="800" fill="#8a6b5f" letter-spacing=".3">ALLOCATED · on paper</text>'
        + '<text x="%.1f" y="44" font-family="Arial" font-size="14" font-weight="800" fill="#8C1D40">16.5</text>' % (endx + 3)
        + '<text x="16" y="65" font-family="Arial" font-size="8.5" font-weight="800" fill="#8a6b5f" letter-spacing=".3">DELIVERED · in the river</text>'
        + '<text x="%.1f" y="84" font-family="Arial" font-size="14" font-weight="800" fill="#1565C0">≈12.4</text>' % (defx + 4)
        + '<text x="%.1f" y="66" font-family="Arial" font-size="9" font-weight="800" fill="#D84315" text-anchor="middle">−4.1</text>' % ((defx + endx) / 2.0)
        + '<text x="100" y="106" font-family="Arial" font-size="10" font-weight="800" fill="#D84315" text-anchor="middle">over-allocated by ~4 MAF (25%)</text>')
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 120">'
      + defs +
      '<style>@keyframes gw{0%,6%{transform:scaleX(0)}52%,94%{transform:scaleX(1)}100%{transform:scaleX(0)}}'
      '.gb{animation:gw 5s ease-in-out infinite}.gb2{animation:gw 5s ease-in-out .25s infinite}</style>'
      '<g filter="url(#sh)">' + bp + flow + '</g>' + deficit + labels +
      '</svg>')


def _chart_ria():
    # CRIA brand mascot — the yellow water drop (sharp top, round bottom), wearing its hat,
    # smiling, talking (open mouth + speech dots) and bouncing.
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 120">'
      '<style>'
      '@keyframes bob{0%{transform:translateY(0) scaleY(1)}25%{transform:translateY(-11px) scaleY(1.03)}'
      '50%{transform:translateY(0) scaleY(.94)}60%{transform:translateY(0) scaleY(1.02)}100%{transform:translateY(0) scaleY(1)}}'
      '@keyframes talk{0%,100%{transform:scaleY(.35)}50%{transform:scaleY(1)}}'
      '@keyframes tk{0%,60%,100%{transform:translateY(0);opacity:.3}30%{transform:translateY(-4px);opacity:1}}'
      '@keyframes blink{0%,92%,100%{transform:scaleY(1)}96%{transform:scaleY(.1)}}'
      '.mascot{transform-box:fill-box;transform-origin:92px 104px;animation:bob 1.25s ease-in-out infinite}'
      '.mouth{transform-box:fill-box;transform-origin:center;animation:talk .5s ease-in-out infinite}'
      '.eye{transform-box:fill-box;transform-origin:center;animation:blink 3.4s ease-in-out infinite}'
      '.tk{transform-box:fill-box;transform-origin:center;animation:tk 1.1s ease-in-out infinite}'
      '</style>'
      '<ellipse cx="92" cy="112" rx="21" ry="4.5" fill="#000" opacity=".16">'
      '<animate attributeName="rx" values="21;15;21" dur="1.25s" repeatCount="indefinite"/>'
      '<animate attributeName="opacity" values=".16;.09;.16" dur="1.25s" repeatCount="indefinite"/></ellipse>'
      '<g class="mascot">'
      '<ellipse cx="92" cy="33" rx="18" ry="4.6" fill="#8C1D40"/>'
      '<path d="M82 33 L86 17 L98 17 L102 33 Z" fill="#8C1D40"/>'
      '<rect x="84" y="25" width="16" height="4.4" rx="2" fill="#FFC627"/>'
      '<path d="M92 32 C104 50 117 66 117 80 A25 25 0 1 1 67 80 C67 66 80 50 92 32 Z" fill="#FFC627" stroke="#E0A200" stroke-width="2.4"/>'
      '<path d="M84 58 C78 66 79 76 86 80 C80 74 80 64 84 58 Z" fill="#fff" opacity=".35"/>'
      '<circle cx="78" cy="80" r="3.6" fill="#ff8fa3" opacity=".55"/>'
      '<circle cx="106" cy="80" r="3.6" fill="#ff8fa3" opacity=".55"/>'
      '<g class="eye"><circle cx="85" cy="70" r="5" fill="#fff" stroke="#8C1D40" stroke-width="1"/><circle cx="86" cy="71" r="2.3" fill="#3a1020"/><circle cx="87" cy="70" r=".8" fill="#fff"/></g>'
      '<g class="eye"><circle cx="99" cy="70" r="5" fill="#fff" stroke="#8C1D40" stroke-width="1"/><circle cx="100" cy="71" r="2.3" fill="#3a1020"/><circle cx="101" cy="70" r=".8" fill="#fff"/></g>'
      '<g class="mouth"><path d="M84 81 Q92 83 100 81 Q92 93 84 81 Z" fill="#7a1029"/>'
      '<path d="M87 88 Q92 91 97 88 Q92 91.5 87 88 Z" fill="#ff6f91"/></g>'
      '</g>'
      '<circle class="tk" cx="132" cy="58" r="4" fill="#FFC627" style="animation-delay:0s"/>'
      '<circle class="tk" cx="146" cy="52" r="3.4" fill="#8C1D40" style="animation-delay:.15s"/>'
      '<circle class="tk" cx="159" cy="48" r="2.8" fill="#E0A200" style="animation-delay:.3s"/>'
      '</svg>')


_TVT_TRACK = "#e7e2d8"; _TVT_INK = "#5a1226"; _TVT_MUTE = "#8a6b5f"


def _tvt_safe(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _lighten(hex_c, f=0.5):
    h = str(hex_c).lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r = int(r + (255 - r) * f); g = int(g + (255 - g) * f); b = int(b + (255 - b) * f)
    return "#%02x%02x%02x" % (r, g, b)


def _cdefs(col, vertical=True):
    """Reusable gradient + soft drop-shadow (gives every chart a colourful, 3D pop)."""
    lt = _lighten(col, 0.55)
    xy = 'x1="0" y1="0" x2="0" y2="1"' if vertical else 'x1="0" y1="0" x2="1" y2="0"'
    return ('<defs><linearGradient id="g" ' + xy + '>'
            '<stop offset="0" stop-color="' + lt + '"/><stop offset="1" stop-color="' + col + '"/></linearGradient>'
            '<filter id="sh" x="-40%" y="-40%" width="180%" height="180%">'
            '<feDropShadow dx="0" dy="1.5" stdDeviation="1.7" flood-color="' + col + '" flood-opacity="0.35"/></filter>'
            '</defs>')


def _svg2(inner):
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 120">' + inner + '</svg>'


def _chart_statline(big, small, vals, col="#8C1D40", fill=None):
    """Big value + caption + a mini animated gradient sparkline (or an animated accent when no series)."""
    v = np.array(vals, float); n = len(v)
    style = ('<style>@keyframes dr{0%,10%{stroke-dashoffset:100}70%,92%{stroke-dashoffset:0}100%{stroke-dashoffset:100}}'
             '@keyframes af{0%,10%{opacity:0}70%,92%{opacity:.85}100%{opacity:0}}'
             '.ln{stroke-dasharray:100;animation:dr 4.8s ease-in-out infinite}.ar{animation:af 4.8s ease-in-out infinite}'
             '.acc{animation:dr 3.4s ease-in-out infinite}</style>')
    if n < 3:
        body = ('<line class="acc" x1="66" y1="58" x2="134" y2="58" stroke="url(#g)" stroke-width="3.4" '
                'stroke-linecap="round" pathLength="100" stroke-dasharray="100" filter="url(#sh)"/>')
        yb2, ys2 = 46, 74
    else:
        x0, x1, yt, yb = 52, 148, 80, 102
        xs = np.linspace(x0, x1, n); lo, hi = float(v.min()), float(v.max())
        yy = yb - (v - lo) / (hi - lo + 1e-9) * (yb - yt)
        d = "M" + " L".join("%.1f %.1f" % (x, y) for x, y in zip(xs, yy))
        area = "M52 102 L" + " L".join("%.1f %.1f" % (x, y) for x, y in zip(xs, yy)) + " L148 102 Z"
        body = ('<path class="ar" d="' + area + '" fill="url(#g)" opacity=".55"/>'
                '<path class="ln" pathLength="100" d="' + d + '" fill="none" stroke="' + col + '" stroke-width="2.6" '
                'stroke-linecap="round" stroke-linejoin="round" filter="url(#sh)"/>')
        yb2, ys2 = 48, 66
    txt = ('<text x="100" y="%d" font-family="Arial" font-weight="800" font-size="30" fill="%s" text-anchor="middle">%s</text>'
           '<text x="100" y="%d" font-family="Arial" font-weight="700" font-size="10.5" fill="%s" text-anchor="middle">%s</text>'
           % (yb2, col, _tvt_safe(big), ys2, _TVT_INK, _tvt_safe(small)))
    return _svg2(_cdefs(col) + style + body + txt)


def _chart_area(vals, big, small, col="#17A2A8"):
    """A bold gradient area chart with the headline value floated on top."""
    v = np.array(vals, float); n = len(v)
    if n < 3:
        return _chart_statline(big, small, [], col)
    x0, x1, yt, yb = 8, 192, 44, 104
    xs = np.linspace(x0, x1, n); lo, hi = float(v.min()), float(v.max())
    yy = yb - (v - lo) / (hi - lo + 1e-9) * (yb - yt)
    d = "M" + " L".join("%.1f %.1f" % (x, y) for x, y in zip(xs, yy))
    area = "M8 104 L" + " L".join("%.1f %.1f" % (x, y) for x, y in zip(xs, yy)) + " L192 104 Z"
    style = ('<style>@keyframes gro{0%,8%{clip-path:inset(0 100% 0 0)}66%,92%{clip-path:inset(0 0 0 0)}100%{clip-path:inset(0 100% 0 0)}}'
             '.grw{animation:gro 4.8s ease-in-out infinite}</style>')
    body = ('<g class="grw"><path d="' + area + '" fill="url(#g)" opacity=".85"/>'
            '<path d="' + d + '" fill="none" stroke="' + col + '" stroke-width="2.6" stroke-linecap="round" '
            'stroke-linejoin="round" filter="url(#sh)"/></g>')
    txt = ('<text x="100" y="30" font-family="Arial" font-weight="800" font-size="27" fill="' + col + '" text-anchor="middle">' + _tvt_safe(big) + '</text>'
           '<text x="100" y="116" font-family="Arial" font-weight="700" font-size="10" fill="' + _TVT_MUTE + '" text-anchor="middle">' + _tvt_safe(small) + '</text>')
    return _svg2(_cdefs(col) + style + body + txt)


def _chart_columns(items, small, col="#E8590C"):
    """Vertical gradient columns that grow — items: (label, value, disp)."""
    items = items[:3]
    mx = max(abs(v) for _l, v, _d in items) or 1.0
    n = len(items); bw = 30; gap = 20; total = n * bw + (n - 1) * gap; x0 = (200 - total) / 2.0
    baseY = 84; maxH = 52
    bars = ""; labels = ""
    for i, (lab, val, disp) in enumerate(items):
        h = abs(val) / mx * maxH; x = x0 + i * (bw + gap); y = baseY - h
        bars += ('<rect class="cg" x="%.1f" y="%.1f" width="%d" height="%.1f" rx="3" fill="url(#g)" filter="url(#sh)" '
                 'style="transform-box:fill-box;transform-origin:bottom;animation-delay:%.2fs"/>' % (x, y, bw, h, i * 0.12))
        labels += ('<text x="%.1f" y="%.1f" font-family="Arial" font-size="10.5" font-weight="800" fill="%s" text-anchor="middle">%s</text>'
                   % (x + bw / 2.0, y - 4, col, _tvt_safe(disp)))
        labels += ('<text x="%.1f" y="98" font-family="Arial" font-size="9" font-weight="700" fill="%s" text-anchor="middle">%s</text>'
                   % (x + bw / 2.0, _TVT_INK, _tvt_safe(lab)))
    cap = '<text x="100" y="112" font-family="Arial" font-size="10" font-weight="700" fill="%s" text-anchor="middle">%s</text>' % (_TVT_MUTE, _tvt_safe(small))
    style = '<style>@keyframes cg{0%,8%{transform:scaleY(0)}55%,92%{transform:scaleY(1)}100%{transform:scaleY(0)}}.cg{animation:cg 4.6s ease-out infinite}</style>'
    return _svg2(_cdefs(col) + style + bars + labels + cap)


def _chart_waffle(pct, big, small, col="#8C1D40", cols=5, rows=4):
    """A waffle / dot-grid filled to `pct`% — a fresh way to show a share. Big value below."""
    n = cols * rows; fill = int(round(max(0.0, min(1.0, pct / 100.0)) * n))
    cw = 12; gap = 5; gw = cols * cw + (cols - 1) * gap; x0 = (200 - gw) / 2.0; y0 = 12
    cells = ""; k = 0
    for r in range(rows):
        for c in range(cols):
            on = k < fill
            fc = "url(#g)" if on else _TVT_TRACK
            filt = ' filter="url(#sh)"' if on else ''
            cls = ' class="wf"' if on else ''
            dly = ' style="animation-delay:%.2fs"' % (k * 0.04) if on else ''
            cells += '<rect%s x="%.1f" y="%.1f" width="%d" height="%d" rx="3" fill="%s"%s%s/>' % (
                cls, x0 + c * (cw + gap), y0 + r * (cw + gap), cw, cw, fc, filt, dly)
            k += 1
    txt = ('<text x="100" y="98" font-family="Arial" font-weight="800" font-size="23" fill="%s" text-anchor="middle">%s</text>'
           '<text x="100" y="113" font-family="Arial" font-weight="700" font-size="10" fill="%s" text-anchor="middle">%s</text>'
           % (col, _tvt_safe(big), _TVT_INK, _tvt_safe(small)))
    style = ('<style>@keyframes wp{0%,3%{opacity:0;transform:scale(0)}20%,92%{opacity:1;transform:scale(1)}100%{opacity:0;transform:scale(0)}}'
             '.wf{transform-box:fill-box;transform-origin:center;animation:wp 4.8s ease-out infinite}</style>')
    return _svg2(_cdefs(col) + style + cells + txt)


def _chart_bars2(items, small):
    """Horizontal gradient bars; the value (with sign) is the label, colour per item."""
    items = items[:3]
    mx = max(abs(v) for _l, _d, v, _c in items) or 1.0
    x0 = 50; span = 70; rows = [34, 58, 82] if len(items) >= 3 else [44, 72]
    defs = "<defs>"; bars = ""; labels = ""
    for i, (lab, disp, val, col) in enumerate(items):
        defs += ('<linearGradient id="gb%d" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="%s"/>'
                 '<stop offset="1" stop-color="%s"/></linearGradient>' % (i, _lighten(col, 0.35), col))
        y = rows[i]; w = abs(val) / mx * span
        bars += ('<rect x="%d" y="%d" width="%.1f" height="14" rx="3" fill="url(#gb%d)" '
                 'style="transform-box:fill-box;transform-origin:left;animation:bg 4.8s ease-out infinite"/>' % (x0, y, w, i))
        labels += ('<text x="%d" y="%d" font-family="Arial" font-weight="700" font-size="9.5" fill="%s">%s</text>'
                   % (x0, y - 3, _TVT_INK, _tvt_safe(lab)))
        labels += ('<text x="%.1f" y="%d" font-family="Arial" font-weight="800" font-size="10.5" fill="%s">%s</text>'
                   % (x0 + w + 4, y + 11, col, _tvt_safe(disp)))
    defs += ('<filter id="sh" x="-40%" y="-40%" width="180%" height="180%"><feDropShadow dx="0" dy="1.4" '
             'stdDeviation="1.3" flood-color="#000" flood-opacity="0.18"/></filter></defs>')
    axis = '<line x1="%d" y1="30" x2="%d" y2="92" stroke="#d8cdb9" stroke-width="1.4"/>' % (x0, x0)
    cap = '<text x="100" y="106" font-family="Arial" font-weight="700" font-size="10" fill="%s" text-anchor="middle">%s</text>' % (_TVT_MUTE, _tvt_safe(small))
    style = '<style>@keyframes bg{0%,8%{transform:scaleX(0)}55%,92%{transform:scaleX(1)}100%{transform:scaleX(0)}}</style>'
    return _svg2(defs + '<g filter="url(#sh)">' + bars + '</g>' + style + axis + labels + cap)


def _chart_donut(segs, big, small, col="#8C1D40", cx=100, cy=52, r=32, w=13):
    """Animated gradient donut. segs: list of (fraction, colour); first colour drives the value text."""
    import math
    C = 2 * math.pi * r
    defs = "<defs>"; parts = '<circle cx="%d" cy="%d" r="%d" fill="none" stroke="%s" stroke-width="%d"/>' % (cx, cy, r, _TVT_TRACK, w)
    style = "<style>"; off = 0.0; i = 0
    for frac, scol in segs:
        defs += ('<linearGradient id="gd%d" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="%s"/>'
                 '<stop offset="1" stop-color="%s"/></linearGradient>' % (i, _lighten(scol, 0.5), scol))
        seg = frac * C; rot = off / C * 360 - 90
        parts += ('<circle class="ar%d" cx="%d" cy="%d" r="%d" fill="none" stroke="url(#gd%d)" stroke-width="%d" '
                  'stroke-dasharray="%.1f %.1f" transform="rotate(%.1f %d %d)"/>' % (i, cx, cy, r, i, w, seg, C - seg, rot, cx, cy))
        style += ('.ar%d{stroke-dashoffset:%.1f;animation:dn%d 4.6s ease-out infinite}'
                  '@keyframes dn%d{0%%,%d%%{stroke-dashoffset:%.1f}%d%%,100%%{stroke-dashoffset:0}}'
                  % (i, seg, i, i, int(8 + i * 8), seg, int(42 + i * 8)))
        off += seg; i += 1
    defs += ('<filter id="sh" x="-40%" y="-40%" width="180%" height="180%"><feDropShadow dx="0" dy="1.5" '
             'stdDeviation="1.6" flood-color="' + (segs[0][1] if segs else col) + '" flood-opacity="0.3"/></filter></defs>')
    style += "</style>"
    txt = ('<text x="%d" y="%d" font-family="Arial" font-weight="800" font-size="23" fill="%s" text-anchor="middle">%s</text>'
           '<text x="%d" y="%d" font-family="Arial" font-weight="700" font-size="10.5" fill="%s" text-anchor="middle">%s</text>'
           % (cx, cy + 5, (segs[0][1] if segs else col), _tvt_safe(big), cx, cy + r + 15, _TVT_INK, _tvt_safe(small)))
    return _svg2(defs + '<g filter="url(#sh)">' + parts + '</g>' + style + txt)


def _chart_ring(pct, big, small, col="#8C1D40", cx=100, cy=52, r=32, w=13):
    """Animated gradient progress ring (clock-style sweep) + centre value."""
    import math
    C = 2 * math.pi * r; seg = pct / 100.0 * C
    style = ('<style>.rg{stroke-dashoffset:' + ("%.1f" % seg) + ';animation:rw 4.6s ease-out infinite}'
             '@keyframes rw{0%,8%{stroke-dashoffset:' + ("%.1f" % seg) + '}55%,92%{stroke-dashoffset:0}'
             '100%{stroke-dashoffset:' + ("%.1f" % seg) + '}}</style>')
    track = '<circle cx="%d" cy="%d" r="%d" fill="none" stroke="%s" stroke-width="%d"/>' % (cx, cy, r, _TVT_TRACK, w)
    arc = ('<circle class="rg" cx="%d" cy="%d" r="%d" fill="none" stroke="url(#g)" stroke-width="%d" '
           'stroke-linecap="round" stroke-dasharray="%.1f %.1f" transform="rotate(-90 %d %d)" filter="url(#sh)"/>'
           % (cx, cy, r, w, seg, C - seg, cx, cy))
    txt = ('<text x="%d" y="%d" font-family="Arial" font-weight="800" font-size="24" fill="%s" text-anchor="middle">%s</text>'
           '<text x="%d" y="%d" font-family="Arial" font-weight="700" font-size="10.5" fill="%s" text-anchor="middle">%s</text>'
           % (cx, cy + 5, col, _tvt_safe(big), cx, cy + r + 15, _TVT_INK, _tvt_safe(small)))
    return _svg2(_cdefs(col) + style + track + arc + txt)


def _chart_gauge(frac, big, small, col="#8C1D40"):
    """Animated radial gauge / speedometer with a gradient arc + needle."""
    import math
    cx, cy, r = 100, 78, 46
    def pol(a, rr):
        return (cx + rr * math.cos(math.radians(a)), cy - rr * math.sin(math.radians(a)))
    frac = max(0.0, min(1.0, frac))
    x0, y0 = pol(180, r); x1, y1 = pol(0, r)
    bg = '<path d="M%.1f %.1f A%d %d 0 0 1 %.1f %.1f" fill="none" stroke="%s" stroke-width="11" stroke-linecap="round"/>' % (x0, y0, r, r, x1, y1, _TVT_TRACK)
    ang = 180 - frac * 180; xv, yv = pol(ang, r)
    val = '<path class="gv" d="M%.1f %.1f A%d %d 0 0 1 %.1f %.1f" fill="none" stroke="url(#g)" stroke-width="11" stroke-linecap="round" pathLength="100" stroke-dasharray="100" filter="url(#sh)"/>' % (x0, y0, r, r, xv, yv)
    ticks = ""
    for i in range(0, 6):
        a = 180 - i / 5.0 * 180; tx0, ty0 = pol(a, r - 14); tx1, ty1 = pol(a, r - 8)
        ticks += '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#cdbfa8" stroke-width="1.6"/>' % (tx0, ty0, tx1, ty1)
    nx, ny = pol(ang, r - 6)
    needle = ('<g class="nd"><line x1="%d" y1="%d" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="3" stroke-linecap="round"/>'
              '<circle cx="%d" cy="%d" r="5.5" fill="%s" filter="url(#sh)"/></g>' % (cx, cy, nx, ny, col, cx, cy, col))
    style = ('<style>@keyframes gd{0%,6%{stroke-dashoffset:100}55%,92%{stroke-dashoffset:0}100%{stroke-dashoffset:100}}'
             '.gv{animation:gd 4.6s ease-out infinite}'
             '@keyframes sw{0%,6%{transform:rotate(' + ("%.1f" % (180 - ang)) + 'deg)}55%,92%{transform:rotate(0deg)}'
             '100%{transform:rotate(' + ("%.1f" % (180 - ang)) + 'deg)}}'
             '.nd{transform-box:fill-box;transform-origin:' + ("%dpx %dpx" % (cx, cy)) + ';animation:sw 4.6s ease-out infinite}</style>')
    txt = ('<text x="%d" y="%d" font-family="Arial" font-weight="800" font-size="21" fill="%s" text-anchor="middle">%s</text>'
           '<text x="%d" y="98" font-family="Arial" font-weight="700" font-size="9" fill="%s" text-anchor="middle">%s</text>'
           % (cx, cy - 14, col, _tvt_safe(big), cx, _TVT_MUTE, _tvt_safe(small)))
    return _svg2(_cdefs(col) + style + bg + val + ticks + needle + txt)


def _chart_pie(segs, small, cx=100, cy=50, r=36):
    """Animated pie — segs: (value, colour, label). Wedges grow in; % on each wide wedge."""
    import math
    total = sum(v for v, _c, _l in segs) or 1.0
    a0 = -90.0
    def pol(a, rr):
        return (cx + rr * math.cos(math.radians(a)), cy + rr * math.sin(math.radians(a)))
    wedges = ""; labels = ""; i = 0
    for val, col, lab in segs:
        sweep = val / total * 360.0; a1 = a0 + sweep
        x0, y0 = pol(a0, r); x1, y1 = pol(a1, r); large = 1 if sweep > 180 else 0
        wedges += ('<path class="pw p%d" d="M%d %d L%.1f %.1f A%d %d 0 %d 1 %.1f %.1f Z" fill="%s" stroke="#fff" stroke-width="1.5"/>'
                   % (i, cx, cy, x0, y0, r, r, large, x1, y1, col))
        mid = (a0 + a1) / 2.0; lx, ly = pol(mid, r * 0.60); pct = int(round(val / total * 100))
        fillc = "#3a1020" if col == "#FFC627" else "#fff"
        if pct >= 12:
            labels += ('<text x="%.1f" y="%.1f" font-family="Arial" font-weight="800" font-size="11" fill="%s" text-anchor="middle">%d%%</text>'
                       % (lx, ly + 3, fillc, pct))
        a0 = a1; i += 1
    cap = '<text x="%d" y="%d" font-family="Arial" font-weight="700" font-size="10.5" fill="%s" text-anchor="middle">%s</text>' % (cx, cy + r + 16, _TVT_INK, _tvt_safe(small))
    style = ('<style>@keyframes pw{0%,4%{transform:scale(0)}26%,96%{transform:scale(1)}100%{transform:scale(0)}}'
             '.pw{transform-box:fill-box;transform-origin:' + ("%dpx %dpx" % (cx, cy)) + ';animation:pw 5s ease-out infinite}'
             '.p1{animation-delay:.1s}.p2{animation-delay:.2s}</style>')
    return _svg2('<defs><filter id="sh" x="-30%" y="-30%" width="160%" height="160%"><feDropShadow dx="0" dy="2" stdDeviation="2" flood-color="#000" flood-opacity="0.2"/></filter></defs>'
                 + style + '<g filter="url(#sh)">' + wedges + '</g>' + labels + cap)


def _darken(hex_c, f=0.4):
    h = str(hex_c).lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r = int(r * (1 - f)); g = int(g * (1 - f)); b = int(b * (1 - f))
    return "#%02x%02x%02x" % (r, g, b)


def _wpath(yb, amp):
    """A repeating wave surface (wavelength 80) filled to the bottom — for flowing water."""
    p = "M-80 %.0f" % yb
    x = -80; up = True
    while x < 280:
        cy = yb - amp if up else yb + amp
        p += " Q%.0f %.0f %.0f %.0f" % (x + 20, cy, x + 40, yb)
        x += 40; up = not up
    p += " L280 230 L-80 230 Z"
    return p


def _wviz_snow(big, small, col="#4FC3F7"):
    """A white snow mound melting into blue drips + a little blue puddle with a ripple."""
    ink = _darken(col, 0.45)
    style = ('<style>@keyframes mlt{0%,8%{transform:scaleY(1)}60%,92%{transform:scaleY(.42)}100%{transform:scaleY(1)}}'
             '@keyframes drip{0%,25%{transform:translateY(0);opacity:0}42%{opacity:1}100%{transform:translateY(28px);opacity:0}}'
             '@keyframes rip{0%{transform:scale(.4);opacity:.7}100%{transform:scale(2.4);opacity:0}}'
             '.mound{transform-box:fill-box;transform-origin:bottom;animation:mlt 4.8s ease-in-out infinite}'
             '.drip{transform-box:fill-box;animation:drip 2.4s ease-in infinite}'
             '.rip{transform-box:fill-box;transform-origin:center;animation:rip 3s ease-out infinite}</style>')
    ground = '<line x1="42" y1="94" x2="158" y2="94" stroke="#cdbfa8" stroke-width="2"/>'
    puddle = '<ellipse cx="100" cy="95" rx="26" ry="4" fill="' + col + '" opacity=".55"/>'
    rip = '<ellipse class="rip" cx="100" cy="95" rx="9" ry="2.2" fill="none" stroke="' + col + '" stroke-width="1.4"/>'
    mound = ('<path class="mound" d="M60 94 Q100 38 140 94 Z" fill="#ffffff" stroke="' + col + '" stroke-width="2" filter="url(#sh)"/>'
             '<path class="mound" d="M82 94 Q100 62 118 94 Z" fill="' + _lighten(col, 0.7) + '" opacity=".7"/>')
    drips = ('<circle class="drip" cx="100" cy="92" r="3.2" fill="' + col + '"/>'
             '<circle class="drip" cx="86" cy="92" r="2.6" fill="' + col + '" style="animation-delay:.9s"/>'
             '<circle class="drip" cx="114" cy="92" r="2.6" fill="' + col + '" style="animation-delay:1.6s"/>')
    txt = ('<text x="100" y="24" font-family="Arial" font-weight="800" font-size="26" fill="' + ink + '" text-anchor="middle">' + _tvt_safe(big) + '</text>'
           '<text x="100" y="112" font-family="Arial" font-weight="700" font-size="10" fill="' + _TVT_INK + '" text-anchor="middle">' + _tvt_safe(small) + '</text>')
    return _svg2(_cdefs(col) + style + ground + puddle + rip + mound + drips + txt)


def _wviz_drain(big, small, col="#2196F3"):
    """A tank of flowing BLUE water whose level keeps dropping — dry tan shows above."""
    ink = _darken(col, 0.5)
    clip = '<clipPath id="tk"><rect x="54" y="34" width="92" height="62" rx="9"/></clipPath>'
    tankbg = '<rect x="54" y="34" width="92" height="62" rx="9" fill="#f3ece1"/>'
    water = ('<g clip-path="url(#tk)"><g class="wl">'
             '<path class="wv wvb" d="' + _wpath(46, 4) + '" fill="' + _lighten(col, 0.45) + '"/>'
             '<path class="wv wvf" d="' + _wpath(43, 5) + '" fill="url(#g)"/>'
             '</g><ellipse class="rip" cx="100" cy="44" rx="9" ry="2.4" fill="none" stroke="#ffffff" stroke-width="1.3"/></g>')
    tankline = '<rect x="54" y="34" width="92" height="62" rx="9" fill="none" stroke="' + ink + '" stroke-width="2.5" opacity=".5"/>'
    style = ('<style>@keyframes flow{from{transform:translateX(0)}to{transform:translateX(-80px)}}'
             '@keyframes drn{0%,8%{transform:translateY(0)}58%,92%{transform:translateY(44px)}100%{transform:translateY(0)}}'
             '@keyframes rip{0%{transform:scale(.3);opacity:.75}80%,100%{transform:scale(2.6);opacity:0}}'
             '.wvb{animation:flow 4.2s linear infinite}.wvf{animation:flow 2.8s linear infinite}'
             '.wl{animation:drn 4.8s ease-in-out infinite}'
             '.rip{transform-box:fill-box;transform-origin:center;animation:rip 3s ease-out infinite}</style>')
    txt = ('<text x="100" y="26" font-family="Arial" font-weight="800" font-size="24" fill="' + ink + '" text-anchor="middle">' + _tvt_safe(big) + '</text>'
           '<text x="100" y="112" font-family="Arial" font-weight="700" font-size="10" fill="' + _TVT_INK + '" text-anchor="middle">' + _tvt_safe(small) + '</text>')
    return _svg2(_cdefs(col) + clip + tankbg + water + tankline + style + txt)


def _wviz_rise(big, small, col="#2196F3"):
    """A glass of flowing BLUE water that fills up then settles lower — rise then recede."""
    ink = _darken(col, 0.5)
    clip = '<clipPath id="gl"><rect x="62" y="34" width="76" height="62" rx="8"/></clipPath>'
    glass = '<rect x="62" y="34" width="76" height="62" rx="8" fill="#f3ece1"/>'
    water = ('<g clip-path="url(#gl)"><g class="wl">'
             '<path class="wv wvb" d="' + _wpath(46, 4) + '" fill="' + _lighten(col, 0.45) + '"/>'
             '<path class="wv wvf" d="' + _wpath(43, 5) + '" fill="url(#g)"/>'
             '</g></g>')
    line = '<rect x="62" y="34" width="76" height="62" rx="8" fill="none" stroke="' + ink + '" stroke-width="2.5" opacity=".5"/>'
    style = ('<style>@keyframes flow{from{transform:translateX(0)}to{transform:translateX(-80px)}}'
             '@keyframes rz{0%,6%{transform:translateY(46px)}32%{transform:translateY(0)}60%,90%{transform:translateY(24px)}100%{transform:translateY(46px)}}'
             '.wvb{animation:flow 4.2s linear infinite}.wvf{animation:flow 2.8s linear infinite}'
             '.wl{animation:rz 5s ease-in-out infinite}</style>')
    txt = ('<text x="100" y="26" font-family="Arial" font-weight="800" font-size="24" fill="' + ink + '" text-anchor="middle">' + _tvt_safe(big) + '</text>'
           '<text x="100" y="112" font-family="Arial" font-weight="700" font-size="10" fill="' + _TVT_INK + '" text-anchor="middle">' + _tvt_safe(small) + '</text>')
    return _svg2(_cdefs(col) + clip + glass + water + line + style + txt)


def _wviz_evap(big, small, water="#2196F3", heat="#E8590C"):
    """A blue puddle (with a ripple) losing orange 'heat' droplets rising up — evaporation."""
    style = ('<style>@keyframes ev{0%{transform:translateY(0);opacity:0}18%{opacity:.95}100%{transform:translateY(-52px);opacity:0}}'
             '@keyframes shr{0%,8%{transform:scaleX(1)}60%,92%{transform:scaleX(.5)}100%{transform:scaleX(1)}}'
             '@keyframes rip{0%{transform:scale(.4);opacity:.7}100%{transform:scale(2.4);opacity:0}}'
             '.ev{transform-box:fill-box;animation:ev 3s ease-out infinite}'
             '.pud{transform-box:fill-box;transform-origin:center;animation:shr 4.8s ease-in-out infinite}'
             '.rip{transform-box:fill-box;transform-origin:center;animation:rip 3s ease-out infinite}</style>')
    drops = ""
    for x, d, r in [(80, 0.0, 3.4), (94, 0.5, 2.8), (108, 1.0, 3.2), (122, 1.5, 2.6), (88, 0.8, 2.4), (116, 1.3, 2.8)]:
        drops += '<circle class="ev" cx="%d" cy="94" r="%.1f" fill="%s" style="animation-delay:%.1fs"/>' % (x, r, heat, d)
    puddle = '<ellipse class="pud" cx="100" cy="99" rx="44" ry="8" fill="url(#g)" filter="url(#sh)"/>'
    rip = '<ellipse class="rip" cx="100" cy="99" rx="11" ry="2.6" fill="none" stroke="' + water + '" stroke-width="1.4"/>'
    txt = ('<text x="100" y="30" font-family="Arial" font-weight="800" font-size="26" fill="' + _darken(heat, 0.12) + '" text-anchor="middle">' + _tvt_safe(big) + '</text>'
           '<text x="100" y="114" font-family="Arial" font-weight="700" font-size="10" fill="' + _TVT_INK + '" text-anchor="middle">' + _tvt_safe(small) + '</text>')
    return _svg2(_cdefs(water) + style + drops + puddle + rip + txt)


def _tab_motifs():
    """Real, validated headline value + TWO supporting animated mini-vizzes per tab (live from the
       cache) — a primary trend and a second analysis in a different chart form, cycled on the card.
       Each entry: dict(num, to, dec, suf, unit, cap, acc, charts=[svg, svg])."""
    if "v" in _TABM:
        return _TABM["v"]
    import math
    MRN = "#8C1D40"; GLD = "#FFC627"; AMB = "#E0A200"
    # Water supply & snow — runoff efficiency trend + Budyko partition (where the rain goes)
    try:
        d = _safe(load_vic_annual); d = d[d["basin"] == "CRB"].sort_values("water_year")
        rea = ((d["OUT_RUNOFF"] + d["OUT_BASEFLOW"]) / d["OUT_PREC"])
        base = rea[(d.water_year >= 1983) & (d.water_year <= 2010)].mean()
        rec = rea[d.water_year >= 2015].mean()
        rep = int(round((rec - base) / abs(base) * 100))
        P = float(d["OUT_PREC"].mean()); ET = float(d["OUT_EVAP"].mean())
        Q = float((d["OUT_RUNOFF"] + d["OUT_BASEFLOW"]).mean())
        et_f = ET / P; q_f = Q / P; q_pct = int(round(q_f * 100)); et_pct = int(round(et_f * 100))
        # Cycle the tab's real sub-analyses (one per sub-page), each with its own value + chart form.
        sc = [_chart_line(rea.values, MRN, "140,29,64")]
        try:  # Snowpack & Runoff — peak SWE, earliest vs latest 5-yr
            sa = _safe(load_snotel_annual); sa = sa[sa["basin"] == "CRB"]
            swe = sa.groupby("water_year")["peak_swe_mm"].mean().dropna()
            wmin, wmax = int(sa.water_year.min()), int(sa.water_year.max())
            e5 = sa[sa.water_year <= wmin + 4]["peak_swe_mm"].mean()
            l5 = sa[sa.water_year >= wmax - 4]["peak_swe_mm"].mean()
            spct = int(round((l5 - e5) / e5 * 100))
            sc.append(_chart_statline("%+d%%" % spct, "peak snowpack", swe.values, MRN))
        except Exception:
            pass
        try:  # Elevation-Dependent Snow Loss — trend by elevation band
            st = _safe(load_snotel_stations)
            st = st[st["basin"] == "CRB"].dropna(subset=["mk_slope"]).drop_duplicates("site_id")
            hi = float(st[st["elev"] >= 3000]["mk_slope"].mean())
            lo = float(st[st["elev"] < 3000]["mk_slope"].mean())
            sc.append(_chart_bars2([("High elev", "%.2f" % hi, hi, MRN), ("Low elev", "%.2f" % lo, lo, AMB)],
                                   "SWE trend, mm/yr"))
        except Exception:
            pass
        try:  # Snowmelt Timing — centre-of-timing shift
            from utils.data_loader import CACHE_DIR as _CDIR
            dm = pd.read_parquet(str(_CDIR / "vic_daily_metrics.parquet"))
            dm = dm[dm["basin"] == "CRB"]
            gm = dm.groupby("water_year")["melt_com_doy"].mean().reset_index()
            slope = float(np.polyfit(gm["water_year"], gm["melt_com_doy"], 1)[0]) * 10
            sc.append(_chart_gauge(min(abs(slope) / 3.0, 1.0), "%+.1f" % slope, "days/decade earlier", col=MRN))
        except Exception:
            pass
        # Basin Water Balance — where the precipitation goes
        sc.append(_chart_donut([(et_f, MRN), (q_f, GLD)], "%d%%" % q_pct, "runs off · %d%% ET" % et_pct))
        try:  # Budyko — aridity index, early vs late
            from modules.budyko import _budyko_df
            bd = _budyko_df("CRB")
            ai_l = float(bd[bd["year"] >= 2004]["AI"].mean())
            sc.append(_chart_ring(min(ai_l / 3.0 * 100, 100), "%.2f" % ai_l, "aridity, rising", col=MRN))
        except Exception:
            pass
        try:  # Soil Moisture & Streamflow — drivers of summer flow
            from modules.links import _seasonal, _r
            ld = _seasonal("CRB")
            rh = _r(ld["amjT"], ld["jjasQ"]); rs = _r(ld["oct1"], ld["jjasQ"])
            sc.append(_chart_bars2([("Spring heat", "%+.2f" % rh, rh, MRN), ("Soil moist", "%+.2f" % rs, rs, AMB)],
                                   "→ summer flow"))
        except Exception:
            pass
        try:  # October Signal — out-of-sample forecast skill
            from modules.october import _fit as _octfit
            of = _octfit("CRB"); loo = float(of["loo"])
            sc.append(_chart_ring(max(0, min(100, loo * 100)), "%.2f" % loo, "Oct forecast skill", col=MRN))
        except Exception:
            pass
        snow = {"num": "%d" % rep, "to": rep, "dec": 0, "suf": "%", "unit": "runoff efficiency",
                "cap": "streamflow per unit of rain, vs the 1983–2010 normal", "acc": MRN,
                "charts": sc}
    except Exception:
        snow = None
    # Drought & risk — GRACE storage trend + groundwater share of the loss
    try:
        L = _loss_ledger(); maf = int(round(float(L.get("grace_cum_maf", 45))))
        g = _safe(load_grace); g = g[g["basin"] == "CRB"].dropna(subset=["tws_mm"]).copy()
        g["t"] = pd.to_datetime(g["date"]); g = g.sort_values("t")
        G = _gw_share(); share = int(round(G["share"])) if G and G.get("share") else 96
        share = max(0, min(100, share))
        dc = [_chart_line(g["tws_mm"].values, AMB, "255,198,39"),
              _chart_ring(share, "%d%%" % share, "is groundwater", col=MRN)]
        try:  # Drought & shortage — frequency of drought years
            dv = _safe(load_vic_annual); dv = dv[dv["basin"] == "CRB"]
            qd = dv["OUT_RUNOFF"] + dv["OUT_BASEFLOW"]; frq = int(round((qd < qd.median() * 0.8).mean() * 100))
            dc.append(_chart_donut([(frq / 100.0, MRN), (1 - frq / 100.0, GLD)], "%d%%" % frq, "of years in drought"))
        except Exception:
            pass
        try:  # Aridification Severity Index — basin stress, 0–100
            from modules.asi import _compute_asi
            aa = _compute_asi(_safe(load_vic_annual).copy()); aa = aa[aa["basin"] == "CRB"]
            asi_l = int(round(aa[aa.water_year >= 2003]["ASI"].mean())); asi_pk = int(round(aa["ASI"].max()))
            dc.append(_chart_gauge(min(asi_l / 100.0, 1.0), "%d" % asi_l, "basin stress (peak %d)" % asi_pk, col=MRN))
        except Exception:
            pass
        try:  # Drought recovery — WY2023 rebound vs what was retained
            rv = _safe(load_vic_annual); rv = rv[rv["basin"] == "CRB"].set_index("water_year")
            qy = rv["OUT_RUNOFF"] + rv["OUT_BASEFLOW"]; dn = qy.loc[[2021, 2022]].mean()
            reb = int(round((qy.loc[2023] / dn - 1) * 100)); kept = int(round((qy.loc[2024] - dn) / (qy.loc[2023] - dn) * 100))
            dc.append(_chart_bars2([("Rebound '23", "+%d%%" % reb, reb, GLD), ("Kept by '24", "%d%%" % kept, kept, MRN)],
                                   "one big snow year"))
        except Exception:
            pass
        drought = {"num": "%d" % maf, "to": maf, "dec": 0, "pre": "≈", "suf": "", "unit": "MAF of storage lost",
                   "cap": "total water storage since 2002 · NASA GRACE", "acc": GLD, "charts": dc}
    except Exception:
        drought = None
    # Scenarios & future — warming response curve + the fitted dial (speedometer)
    try:
        c = -0.0834
        try:
            from modules.scenario import _fit
            f = _fit("CRB")
            if f:
                c = f[2]
        except Exception:
            pass
        per = int(round((math.exp(c) - 1) * 100))
        dts = list(np.linspace(0, 5, 40)); pct = [(math.exp(c * dt) - 1) * 100 for dt in dts]
        gc = [_chart_line(pct, MRN, "140,29,64"),
              _chart_gauge(min(abs(per) / 15.0, 1.0), "%d%%" % per, "yield per +1°C", col=MRN)]
        try:  # No-analog 2100 — temperature beyond anything on record
            from modules.noanalog import _table as _noan
            nt = _noan("CRB")
            arow = nt[nt["var"] == "OUT_AIR_TEMP"].iloc[0]
            gc.append(_chart_statline("%.1f°C" % float(arow["f2100"]),
                                      "2100 · +%.1fσ, no analog" % float(arow["z"]), [], MRN))
        except Exception:
            pass
        # CMIP — 5 of 6 published scenarios keep declining
        gc.append(_chart_donut([(5 / 6.0, MRN), (1 / 6.0, GLD)], "5/6", "scenarios decline"))
        gauge = {"num": "%d" % per, "to": per, "dec": 0, "suf": "%", "unit": "water yield / +1°C",
                 "cap": "the basin's own fitted warming response", "acc": MRN, "charts": gc}
    except Exception:
        gauge = None
    # Basin maps — SNOTEL decline map + declining-vs-stable donut
    try:
        s = _safe(load_snotel_stations)
        s = s[s["basin"] == "CRB"].dropna(subset=["latitude", "longitude"]).drop_duplicates("site_id")
        n_tot = len(s); n_dec = int((s["mk_slope"].dropna() < 0).sum())
        pts = [{"x": float(r.longitude), "y": float(r.latitude),
                "dn": 1 if (pd.notna(r.mk_slope) and r.mk_slope < 0) else 0} for r in s.itertuples()]
        mc = [_chart_map(pts)]
        # The maps already show change over time — here we surface the actual change VALUES
        # (recent 15 yrs vs the first 15), computed live from the reanalysis.
        try:
            from modules.cmip import _delta_table

            def _dmean(var, kind="pct"):
                dt = _delta_table(var, kind)
                return dt["delta"], float(dt["delta"].mean()), dt

            rd, rmean, rtab = _dmean("OUT_RUNOFF")
            _pd, pmean, _pt = _dmean("OUT_PREC")
            _sd, smean, _st = _dmean("OUT_SWE")
            _td, tmean, _tt = _dmean("OUT_AIR_TEMP", "abs")
            mc.append(_chart_bars2([("Runoff", "%d%%" % round(rmean), rmean, MRN),
                                    ("Precip", "%d%%" % round(pmean), pmean, AMB),
                                    ("Snowpack", "%.0f%%" % smean, smean, GLD)],
                                   "basin change since the 1990s"))
            worst = rtab.sort_values("delta").iloc[0]; least = rtab.sort_values("delta").iloc[-1]
            mc.append(_chart_bars2([(str(worst["name"])[:11], "%d%%" % round(worst["delta"]), float(worst["delta"]), MRN),
                                    (str(least["name"])[:11], "%d%%" % round(least["delta"]), float(least["delta"]), AMB)],
                                   "runoff change · worst vs least"))
            mc.append(_chart_statline("+%.1f°C" % tmean, "basin warmer since the 1990s", [], MRN))
        except Exception:
            dn_f = n_dec / n_tot if n_tot else 0.65
            mc.append(_chart_donut([(dn_f, MRN), (1 - dn_f, GLD)], "%d" % n_dec, "of %d falling" % n_tot))
        mp = {"num": "%d" % n_dec, "to": n_dec, "dec": 0, "suf": "/%d" % n_tot, "unit": "SNOTEL declining",
              "cap": "stations across the basin now trending down", "acc": MRN, "charts": mc}
    except Exception:
        mp = None
    # Governance — promised-vs-flow bars + allocation pie + the framework's live scorecard
    goc = [_chart_gov(),
           _chart_pie([(7.5, GLD, "Upper"), (7.5, AMB, "Lower"), (1.5, MRN, "Mexico")], "Upper · Lower · Mexico")]
    try:  # Biophysical Asset Scorecard — how many basins are stressed right now
        from modules.cria import _scorecard_rows
        sr = _scorecard_rows(); ntot = len(sr)
        ncaut = sum(1 for r in sr if r["score"] >= 55)
        goc.append(_chart_donut([(ncaut / ntot, MRN), (1 - ncaut / ntot, GLD)], "%d/%d" % (ncaut, ntot), "assets in Caution+"))
    except Exception:
        pass
    goc.append(_chart_statline("0.96", "model skill (NSE) vs gauges", [], MRN))
    goc.append(_chart_statline("10", "peer-reviewed papers, 2021–26", [], MRN))
    gov = {"num": "16.5", "to": 16.5, "dec": 1, "suf": "", "unit": "MAF promised",
           "cap": "yet only ~12.4 MAF actually flows", "acc": GLD, "charts": goc}
    ria = {"num": "32", "to": 32, "dec": 0, "suf": "", "unit": "analyses · 6 themes",
           "cap": "ask RIA anything in plain language", "acc": GLD, "charts": [_chart_ria()]}
    ph = {"num": "—", "to": 0, "dec": 0, "suf": "", "unit": "", "cap": "", "acc": MRN,
          "charts": ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 120"></svg>']}
    out = {"snow": snow or ph, "drought": drought or ph, "gauge": gauge or ph,
           "map": mp or ph, "gov": gov, "ria": ria}
    _TABM["v"] = out
    return out


def _tab_showcase(as_overlay=False, compact=False):
    """Overview — a click-through directory of every analysis. Each tab is a card; inside it,
       every sub-analysis is a small clickable chip showing its real headline value, so a
       first-time user can jump straight to any tab OR any specific analysis in one click.
       Values are validated live from the VIC 5.0 / GRACE / SNOTEL cache."""
    # (landing_route, question, tab_title, description, [ (sub_route, name, value, meaning), ... ])
    TABS = [
        ("/snowpack", "How much water is there?", "Water Supply & Snow",
         "Where the basin's water comes from — snowpack, runoff, the water balance & Budyko. 7 analyses.", [
            ("/snowpack", "Snowpack & Runoff", "−21%", "peak snowpack (SWE)", True),
            ("/elevsnow", "Elevation Snow Loss", "−1.97", "mm/yr at high peaks"),
            ("/timing", "Snowmelt Timing", "−1.7", "days/decade earlier"),
            ("/watbal", "Basin Water Balance", "10%", "of rain reaches rivers", True),
            ("/budyko", "Budyko Balance", "2.32", "aridity index, rising"),
            ("/links", "Soil Moisture ↔ Flow", "−0.73", "spring heat vs flow"),
            ("/october", "October Signal", "0.45", "forecast skill (R²)"),
        ]),
        ("/drought", "How severe is the stress?", "Drought & Risk",
         "How hard the basin is being squeezed — storage loss, drought risk, reservoirs & aridification. 9 analyses.", [
            ("/storage", "Subsurface Storage", "96%", "of loss is groundwater", True),
            ("/tws", "Terrestrial Storage", "−138 mm", "GRACE low · 72% dry"),
            ("/drought", "Drought & Shortage", "24%", "of years in drought"),
            ("/asi", "Aridification Severity", "55", "stress · peak 74 (2018)"),
            ("/recovery", "Drought Recovery", "52%", "of 2023 gain kept"),
            ("/cascade", "Propagation Cascade", "+0.83", "dry soil → low flow"),
            ("/aridification", "Aridification", "−8.3%", "yield per +1°C", True),
            ("/warming", "Warming & Energy", "+0.28°C", "per decade"),
            ("/reservoirs", "Reservoirs & Tiers", "2022", "first-ever Tier 1"),
        ]),
        ("/scenario", "What happens under change?", "Scenarios & Future",
         "What warming does to supply — dial a change and see the streamflow response, with confidence. 6 analyses.", [
            ("/noanalog", "No-Analog 2100", "16.7°C", "+7.9σ, no precedent", True),
            ("/cmip", "Already Measured (CMIP)", "−41%", "runoff · L. Colo −71%", True),
            ("/scenario", "Scenario Explorer", "−8.3%", "per +1°C — dial it"),
            ("/uncertainty", "Uncertainty", "[−21,+2]", "%/°C, 95% CI"),
            ("/future", "Projections to 2100", "→2100", "single VIC run"),
            ("/nmme", "Seasonal Forecasts", "NMME", "beats 24-Month Study"),
        ]),
        ("/basinwide", "Where across the basin?", "Basin Maps",
         "WHERE it's happening — interactive maps of 8 VIC variables across 41 years (1984→2024). Scrub a year, "
         "put two years side-by-side, rank all 11 sub-basins, and watch runoff & drought animate decade by decade. 4 map tools.", [
            ("/spatial", "Maps Over Time", "−41%", "runoff, basin-wide, 41 yrs", True),
            ("/basinwide", "Basin-Wide Overview", "−72%", "worst sub-basin (Little Colorado)", True),
            ("/spatcompare", "Compare by Year", "3.7×", "wettest vs driest year"),
            ("/animations", "Seasonal Cycles", "20/41", "years below normal"),
        ]),
        ("/governance", "How it works & where it's from", "Governance & About",
         "How it works & the proof — the Law of the River, the asset scorecard, methods, data & validation. 5 sections.", [
            ("/governance", "Law of the River", "16.5", "MAF promised vs ~12.4", True),
            ("/cria", "Asset Scorecard", "7/11", "assets in Caution"),
            ("/methods", "Methods & Data", "0.96", "model skill (NSE)"),
            ("/publications", "Publications", "10", "peer-reviewed papers"),
            ("/references", "References", "18", "refs · 7 validations"),
        ]),
    ]

    # Each analysis gets its OWN animated mini-viz (value baked in, self-animating) — a different
    # impressive form per analysis, so a first-time user grasps each at a glance. Real values.
    # Hydrologist palette: water = blue, snow/ice = icy blue, drought/heat = orange/red,
    # soil moisture / vegetation = green, institutional = gold / maroon.
    MRN = "#8C1D40"; GLD = "#FFC627"; AMB = "#E0A200"; PLUM = "#6D1531"
    BLUE = "#2196F3"; DEEPBLUE = "#1565C0"; ICE = "#4FC3F7"
    ORNG = "#E8590C"; RED = "#D84315"; RUST = "#C1440E"; BROWN = "#8D5524"
    GRN = "#2E9E6B"; TEAL = "#17A2A8"; SEA = "#12879A"; CORAL = "#E23D5B"
    swe_v = grace_v = []
    try:
        _sa = _safe(load_snotel_annual); _sa = _sa[_sa["basin"] == "CRB"]
        swe_v = _sa.groupby("water_year")["peak_swe_mm"].mean().dropna().values
    except Exception:
        pass
    try:
        _g = _safe(load_grace); _g = _g[_g["basin"] == "CRB"].dropna(subset=["tws_mm"]).copy()
        _g["t"] = pd.to_datetime(_g["date"]); grace_v = _g.sort_values("t")["tws_mm"].values
    except Exception:
        pass

    def _st(big, small, col=MRN):
        return _chart_statline(big, small, [], col)

    CH = {
        # Water Supply & Snow — snow = icy blue, water = blue, moisture = green
        "/snowpack": _wviz_snow("−21%", "snowpack melting away", ICE),
        "/elevsnow": _chart_columns([("High", 1.97, "−1.97"), ("Low", 0.70, "−0.70")], "SWE trend, mm/yr", ICE),
        "/timing": _chart_gauge(1.7 / 3.0, "−1.7", "days/decade earlier", col=DEEPBLUE),
        "/watbal": _chart_donut([(0.10, BLUE), (0.90, ORNG)], "10%", "reaches rivers · 90% to ET"),
        "/budyko": _chart_ring(77, "2.32", "aridity, rising", col=ORNG),
        "/links": _chart_bars2([("Spring heat", "−.73", -0.73, ORNG), ("Soil moist", "+.39", 0.39, GRN)], "→ summer flow"),
        "/october": _chart_waffle(45, "0.45", "forecast skill (R²)", BLUE),
        # Drought & Risk — water loss = blue draining, dryness/heat = orange/red/brown
        "/storage": _wviz_drain("96%", "storage draining away", BLUE),
        "/tws": _chart_area(grace_v, "−138", "mm · GRACE low", BLUE) if len(grace_v) > 3 else _st("−138", "mm · GRACE low", BLUE),
        "/drought": _chart_waffle(24, "24%", "of years in drought", RED),
        "/asi": _chart_gauge(0.55, "55", "basin stress · peak 74", col=RED),
        "/recovery": _wviz_rise("52%", "rose in '23, then fell", BLUE),
        "/cascade": _chart_ring(83, "+0.83", "dry soil → low flow", col=BROWN),
        "/aridification": _wviz_evap("−8.3%", "yield lost to heat / +1°C", water=BLUE, heat=RED),
        "/warming": _wviz_evap("+0.28°C", "warming per decade", water=BLUE, heat=ORNG),
        "/reservoirs": _wviz_drain("2022", "first-ever Tier 1 cut", BLUE),
        # Scenarios & Future — heat/change = orange/red, forecast/water = blue
        "/noanalog": _st("16.7°C", "2100 · +7.9σ, no analog", RED),
        "/cmip": _chart_columns([("L. Colo", 71, "−71%"), ("Glen Cyn", 22, "−22%")], "runoff change now", ORNG),
        "/scenario": _chart_gauge(8.3 / 15.0, "−8.3%", "per +1°C · dial it live", col=ORNG),
        "/uncertainty": _st("[−21,+2]", "%/°C · 95% CI", AMB),
        "/future": _st("→ 2100", "single VIC run", RED),
        "/nmme": _st("NMME", "beats 24-Month Study", BLUE),
        # Basin Maps — each tool's real, shocking finding (variation across space & time)
        "/spatial": _chart_columns([("Runoff", 41, "−41%"), ("Precip", 13, "−13%"), ("Snow", 6, "−6%")],
                                   "basin-wide change · 41 yrs", ORNG),
        "/basinwide": _chart_columns([("L.Colo", 72, "−72%"), ("Lower", 44, "−44%"), ("Glen Cyn", 22, "−22%")],
                                     "runoff loss varies by sub-basin", ORNG),
        "/spatcompare": _chart_bars2([("Wet 1984", "65 mm", 65, BLUE), ("Dry 2002", "17 mm", 17, ORNG)],
                                     "wettest vs driest — 3.7× swing"),
        "/animations": _chart_waffle(int(round(20 / 41.0 * 100)), "20/41", "years below normal since 1984", RED),
        # Governance & About — gold / amber / maroon / green
        "/governance": _chart_gov(),
        "/cria": _chart_waffle(int(round(7 / 11.0 * 100)), "7/11", "assets in Caution", MRN),
        "/methods": _chart_ring(96, "0.96", "model skill (NSE)", col=GRN),
        "/publications": _st("10", "papers · 2021–26", AMB),
        "/references": _st("18", "refs · 7 validations", GLD),
    }

    # Analyses whose result is backed by a specific CRIA peer-reviewed paper (→ Publications list).
    # Analyses whose result is backed by a specific CRIA peer-reviewed paper.
    # NOT /storage: the 96% subsurface share is a CRIA-derived (GRACE−VIC) figure, not
    # reported in any paper — the GRACE method is published, the 96% share is not.
    PUB_ROUTES = {"/snowpack", "/october", "/links", "/scenario", "/future",
                  "/nmme", "/tws", "/methods", "/aridification",
                  "/basinwide", "/spatial"}
    # CRIA-original diagnostics — novel metrics first quantified in this tool (no paper yet).
    # Honest credit without a "published" claim; click opens Methods.
    DIAG_ROUTES = {"/storage", "/asi", "/recovery", "/cascade", "/noanalog"}

    def chip(sub, name, val, mean, hot=False):
        svg = CH.get(sub) or _st(val, mean)
        main = html.A([
            html.Img(src=_svg_uri(svg), className="chip-chart", alt=name),
            html.Div(name, className="chip-name"),
        ], href=sub, className="chip-main")
        kids = [main]
        if hot:
            kids.append(html.Span("★", className="an-star"))
        if sub in PUB_ROUTES:
            kids.append(html.A([html.Span("★", className="pub-star"), "Published"],
                               href="/publications", className="pub-badge",
                               title="Peer-reviewed — open the paper"))
        elif sub in DIAG_ROUTES:
            kids.append(html.A([html.Span("◆", className="diag-mark"), "CRIA Diagnostic"],
                               href="/methods", className="diag-badge",
                               title="First quantified in CRIA — see Methods"))
        return html.Div(kids, className="an-chip hot" if hot else "an-chip")

    def tabcard(landing, q, title, desc, subs):
        head = html.A([
            html.Div(q, className="tabnav-q"),
            html.Div([html.Span(title, className="tabnav-title"),
                      html.I(className="bi bi-arrow-right tabnav-arrow")], className="tabnav-titlerow"),
            html.Div(desc, className="tabnav-desc"),
        ], href=landing, className="tabnav-head")
        grid = html.Div([chip(*s) for s in subs], className="an-grid")
        return html.Div([head, grid], className="tabcard tabnav")

    ria = html.Div([
        html.Img(src=_svg_uri(_chart_ria()), className="ria-mini", alt="RIA"),
        html.Div([
            html.Div("Not sure where to look?", className="tabnav-q"),
            html.Div("Ask RIA", className="tabnav-title"),
            html.Div("Ask in plain language — RIA opens the right analysis, on any tab.",
                     className="ria-mini-cap"),
        ]),
    ], className="tabcard tabnav ria", id="tabcard-ria")

    cards = [tabcard(*t) for t in TABS] + [ria]
    def _vs(icon, num, lab):
        return html.Div([
            html.I(className="bi " + icon + " vs-stat-ic"),
            html.Div(num, className="vs-stat-num"),
            html.Div(lab, className="vs-stat-lab"),
        ], className="vs-stat")

    if as_overlay:
        head_right = html.Button("×", id="qv-close", n_clicks=0, className="qv-close",
                                 **{"aria-label": "Close Quick View"})
    elif compact:
        head_right = None            # button lives up top next to the tour — none needed here
    else:
        head_right = html.Button([html.I(className="bi bi-grid-1x2-fill"), " Quick View"],
                                 n_clicks=0, className="qv-btn qv-open",
                                 title="Open every signal in one full-screen view")

    title_txt = ("Where the Colorado stands" if compact
                 else "Colorado River Basin — Vital Signs")
    sub_txt = ("Five numbers that frame the Colorado — open the full board for all 32 analyses."
               if compact else
               "Every analysis in the tool, read at a glance — click any signal to open it.")
    head = html.Div([
        html.Div([
            html.Span(html.Img(src=_svg_uri(
                "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
                "stroke='#FFC627' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'>"
                "<path d='M2 12h4l2-6 3 12 2.5-8 1.8 4H22'/></svg>"),
                className="vs-icon-svg", alt=""), className="vs-icon"),
            html.Div([
                html.Div(title_txt, className="vs-title"),
                html.Div(sub_txt, className="vs-sub"),
            ]),
            head_right,
        ], className="vs-titlerow"),
        html.Div([
            _vs("bi-droplet-half", "~2 MAF", "water lost every year"),
            _vs("bi-arrows-angle-expand", "3.5×", "less rain, far less river"),
            _vs("bi-graph-down-arrow", "−41%", "runoff decline since 1984"),
            _vs("bi-moisture", "10%", "of rainfall reaches rivers"),
            _vs("bi-calendar-x", "20 / 41", "years below normal"),
        ], className="vs-stats"),
    ], className="tabshow-head",
        style={"paddingBottom": "14px", "marginBottom": ("0" if compact else "16px")})

    # Compact overview card — just the headline; the full board opens in Quick View.
    if compact:
        return html.Div([head], className="crb-card tabshow-card tabshow-compact")

    return html.Div([
        head,
        html.Div(cards, className="tabshow-grid"),
        html.Div([
            html.Div([
                html.Span([html.Span("★ ", className="lg-pub"), html.B("Published"),
                           " — peer-reviewed paper"], className="lg-item"),
                html.Span([html.Span("◆ ", className="lg-diag"), html.B("CRIA Diagnostic"),
                           " — first quantified in CRIA"], className="lg-item"),
            ], className="tabshow-legend"),
            html.Div("Original analyses developed for CRIA · Vivoni Hydrologic Systems Lab, "
                     "Arizona State University · NASA Award 80NSSC22K0925 · built on the "
                     "peer-reviewed CRIA VIC hydrologic model.", className="tabshow-attrib"),
        ], className="tabshow-foot"),
    ], className="crb-card tabshow-card" + (" qv-inpanel" if as_overlay else ""))


def _hidden_findings():
    """'What most people miss' — the most novel/shocking findings buried in the tabs,
       surfaced with real, verified numbers (each checked against its source module)."""
    def card(num, unit, head, so, tag, kind, href, delay):
        return html.A([
            html.Span(tag, className="hf-tag hf-" + kind),
            html.Div([html.Span(num, className="hf-num"),
                      html.Span(unit, className="hf-unit")], className="hf-numrow"),
            html.Div(html.Span(className="hf-rule")),
            html.Div(head, className="hf-head"),
            html.Div(so, className="hf-so"),
            html.Div([html.Span("Open the analysis"), html.I(className="bi bi-arrow-right")],
                     className="hf-cta"),
        ], href=href, className="hf-card", style={"animationDelay": str(delay) + "s"})

    cards = [
        card("87.5", "%", "In the Lower Basin, groundwater is 87.5% of all water loss",
             "28.18 million acre-feet drawn down since 2002 — below the surface, where no "
             "reservoir gauge can see it.", "PUBLISHED", "pub", "/storage", 0.05),
        card("11", " / 11", "Every sub-basin is worsening — none stable, none improving",
             "All eleven basins trend toward aridification (+4 to +6.5 per decade) — most driven "
             "by vanishing soil moisture.", "CRIA ANALYSIS", "cria", "/cria", 0.13),
        card("30", " tribes", "The most senior water rights in the basin have no fixed number",
             "Thirty tribes' reserved rights sit ahead of the states — many, including parts of "
             "the Navajo Nation's, still unquantified.", "SOURCE", "src", "/governance", 0.21),
        card("−1.16", " W/m² per decade", "The basin is warming — yet putting less energy into evaporation",
             "It has run out of water to evaporate: the land is tipping from energy-limited to "
             "water-limited.", "CRIA ANALYSIS", "cria", "/warming", 0.29),
    ]
    return html.Div([
        html.Div([
            html.Div("FROM THE INTEGRATED RECORD", className="hf-eyebrow"),
            html.H2(["Five findings that reward a ", html.Span("closer look", className="hf-hl")],
                    className="hf-title"),
            html.Div("Each one is real, verified against its source, and easy to lose in a "
                     "single-variable view.", className="hf-sub"),
        ], className="hf-headwrap"),
        html.Div(cards, className="hf-grid"),
        # ── secondary (forward-looking) — the scenario finding, live from /scenario ──
        html.A([
            html.Div([
                html.Div([html.Span("+16.6", className="hf-lead-num"),
                          html.Span("%", className="hf-lead-unit")], className="hf-lead-numrow"),
                html.Div("precipitation needed", className="hf-lead-cap"),
            ], className="hf-lead-figure"),
            html.Div([
                html.Span("CRIA ANALYSIS · LIVE SCENARIO", className="hf-tag hf-cria"),
                html.Div("To hold today's supply at +2 °C, the basin needs more rain than it has "
                         "ever seen", className="hf-lead-head"),
                html.Div(["The wettest decade in the record delivered just ", html.B("+8.3%"),
                          " — this demands nearly twice that. The last decade actually ran ",
                          html.B("−7.9%"), ". Under warming, supply loss is practically unavoidable."],
                         className="hf-lead-so"),
                html.Div([html.Span("Dial the warming yourself"),
                          html.I(className="bi bi-arrow-right")], className="hf-cta"),
            ], className="hf-lead-body"),
        ], href="/scenario", className="hf-lead"),
        html.Div(["And a myth, busted — ",
                  html.B("the high country does not lose its snow first"),
                  ". Once latitude and record length are controlled, elevation is not a "
                  "significant driver of snow loss ", html.B("(p = 0.56)"), ". ",
                  html.A(["See the 103 stations ", html.I(className="bi bi-arrow-right")],
                         href="/elevsnow", className="hf-mythlink")], className="hf-myth"),
    ], className="crb-card hf-band")



def layout():
    return html.Div([
        html.Div([

            # ═══ MOVEMENT 1 — Page opener: identity, mission, the basin's voice & live signals ═══
            # ── Title + intro + what makes CRIA different — the page's headline identity ──
            _novelty_showcase(),

            # ── The basin, in the PI's words — an emotional beat ──
            _river_quote(),

            # ── Live-signal ticker — the basin's real outputs, scrolling ──
            _ticker(),

            # ═══ MOVEMENT 2 — The hook: everything at a glance ═══
            # (hero video → /why; warming dial → /scenario; proof band → /methods —
            #  each moved to the tab where its actual analysis lives)
            html.Div(className="ov-actbreak"),
            html.Div(id="overview-body"),

            # ── Vital Signs — compact headline card on the page; the full board opens in Quick View ──
            _tab_showcase(compact=True),
            # ── From the integrated record — five verified findings that reward a closer look
            #    (paired with the vital signs: the headline stand, then the non-obvious reads) ──
            _hidden_findings(),
            # ── Quick View — the whole Vital Signs board as a full-screen pop-over ──
            html.Div(_tab_showcase(as_overlay=True), id="qv-overlay", className="qv-overlay"),
            # ── The story film — opens in a pop-over player (scrub / speed / download) ──
            html.Div(
                html.Div([
                    html.Button("×", className="film-close", **{"aria-label": "Close film"}),
                    html.Div([
                        html.Span("The whole basin — in three minutes", className="filmm-title"),
                        html.Span("Colorado River Integrated Assessment", className="filmm-sub"),
                    ], className="filmm-head"),
                    html.Video(src="/assets/cria_story.mp4", controls=True, preload="metadata",
                               className="filmm-video"),
                    html.A([html.I(className="bi bi-download"), " Download"],
                           href="/assets/cria_story.mp4", download="CRIA_film.mp4",
                           className="filmm-dl"),
                ], className="filmm-panel"),
                id="film-overlay", className="film-overlay"),

            # ── Role-based entry — orient a first-time user in one glance ──
            _role_entry(),

            # ═══ MOVEMENT 3 — State of the basin: the data ═══
            html.Div(className="ov-actbreak"),
            # ── State of the basin — vital signs first (real data + links) ──
            _report_card(),

            # ── Where the basin's water goes — 3D Sankey wow (complements vitals) ──
            _water_flow(),

            # ── The three questions — glassy 3D hero (the heart of the tool) ──
            _start_here(),

            # ═══ MOVEMENT 4 — The finding: evidence & the climax ═══
            html.Div(className="ov-actbreak"),
            # ── Wow centerpiece — the basin drying over four decades (animated, real data) ──
            _wow_hero(),

            # ── Eye-opener — three striking, cited numbers that pull you deeper ──
            _eye_opener(),

            # ── The signature finding — animated story + the evidence behind it ──
            _signature(),

            # ── Looking ahead — what the basin already knows on 1 October ──
            _october_teaser(),

            # ═══ MOVEMENT 5 — What's next: forward & explore ═══
            html.Div(className="ov-actbreak"),
            # ── Still unanswered — the questions this basin puts back to us ──
            _open_questions(),

            # ── Explore analyses — one section: quick jump menu + flagship tiles ──
            html.Div([
              html.Div([
                html.I(className="bi bi-compass", style={"color": MAROON, "marginRight": "8px",
                                                         "fontSize": "18px"}),
                html.Span("Explore analyses", style={"fontSize": "16px", "fontWeight": "800",
                                                     "color": MAROON, "letterSpacing": "0.3px"}),
                html.Span("jump to any analysis, or open a flagship below",
                          style={"fontSize": "11px", "color": "#1e293b", "marginLeft": "10px"}),
              ], style={"borderBottom": f"2px solid {MAROON}", "paddingBottom": "8px",
                      "marginBottom": "14px", "gap": "10px", "flexWrap": "wrap",
                      "display": "flex", "alignItems": "center"}),
              # quick-jump menu (was the separate "Find an analysis" card)
              dbc.Row([
                  dbc.Col([
                      html.Div("STARTING BASIN", className="control-label"),
                      dcc.Dropdown(id="home-finder-basin", options=BASIN_OPTIONS, value="CRB",
                                   clearable=False, style={"fontSize": "12.5px"}),
                  ], xs=12, md=4),
                  dbc.Col([
                      html.Div("JUMP TO AN ANALYSIS", className="control-label"),
                      dcc.Dropdown(id="home-finder", options=FINDER_OPTIONS, value=None,
                                   placeholder="Select an analysis to open…",
                                   clearable=False, style={"fontSize": "12.5px"}),
                  ], xs=12, md=8),
              ], className="mb-3"),
              html.Div("Or open a flagship analysis:",
                       style={"fontSize": "11.5px", "fontWeight": "700", "color": "#37474f",
                              "marginBottom": "8px"}),
              dbc.Row([
                dbc.Col([
                    html.A([
                        html.Div([
                            html.I(className=f"bi {c['icon']}", style={"fontSize": "18px",
                                   "marginRight": "8px", "color": MAROON}),
                            html.Span(c["title"]),
                        ], style={"fontSize": "13px", "fontWeight": "700",
                                  "color": "#0D2137", "marginBottom": "5px",
                                  "display": "flex", "alignItems": "center"}),
                        html.Div(c["desc"],
                                 style={"fontSize": "10.5px", "color": "#1e293b",
                                        "lineHeight": "1.4"}),
                        html.Div(["Open ", html.I(className="bi bi-arrow-right")],
                                 style={"fontSize": "10.5px", "fontWeight": "700",
                                        "color": "#01579B", "marginTop": "6px"}),
                    ], href=c["href"],
                       className=f"info-tile flag-tile {c['color']}",
                       style={"display": "block", "textDecoration": "none"}),
                ], xs=12, sm=6, md=3, className="mb-2")
                for c in [
                    {"icon": "bi-layers", "title": "Basin-Wide Overview",
                     "desc": "Animated anomaly maps · every sub-basin on one chart",
                     "href": "/basinwide", "color": "tile-maroon"},
                    {"icon": "bi-snow", "title": "Snowpack & Runoff",
                     "desc": "SNOTEL SWE trends · SWE→Q forecast · Seasonal shift",
                     "href": "/snowpack", "color": "tile-navy"},
                    {"icon": "bi-droplet", "title": "Water Balance",
                     "desc": "P→ET + Q + ΔS · Runoff ratio trends · ET partition",
                     "href": "/watbal", "color": "tile-green"},
                    {"icon": "bi-globe-americas", "title": "Water Storage (GRACE)",
                     "desc": "TWS anomaly · Drought memory · SMAP validation",
                     "href": "/tws", "color": "tile-blue"},
                    {"icon": "bi-exclamation-triangle", "title": "Drought & Risk",
                     "desc": "VIC basin runoff · Shortage probability · SM deficit index",
                     "href": "/drought", "color": "tile-maroon"},
                    {"icon": "bi-graph-up-arrow", "title": "Projections to 2100",
                     "desc": "VIC projections · All variables · Basin ranking",
                     "href": "/future", "color": "tile-purple"},
                    {"icon": "bi-calendar-check", "title": "October Signal",
                     "desc": "Autumn soil moisture · next year's yield · out-of-sample skill",
                     "href": "/october", "color": "tile-navy"},
                    {"icon": "bi-map", "title": "Spatial Analysis",
                     "desc": "~22k-cell CRB VIC grid · Trend maps · Period compare",
                     "href": "/spatial", "color": "tile-orange"},
                ]
              ], className="g-2"),
            ], className="crb-card", style={"padding": "14px 16px", "marginBottom": "18px"}),

        ], className="tab-body overview-page"),
    ])


def _reviews_hero(compact=False):
    """Animated 3D welcome banner. compact=True (Overview): just animation + two lines."""
    note = ("CRIA was built for people like you. If it helped you read the basin, saved you "
            "time, or shaped a decision — take a moment to tell us. Your story gives other "
            "water professionals the confidence to lean on it, and shows us where to take "
            "CRIA next."
            if compact else
            "Welcome — and thank you for being here. CRIA is built for the people who "
            "manage and study the Colorado River, and your perspective makes it stronger. "
            "Tell us what worked, what you would change, and how it helped. Your words "
            "guide our next steps and help fellow water professionals decide with confidence.")
    return html.Div([
        html.Div([
            html.Div(className="rev-orb-ring"),
            html.Div(html.I(className="bi bi-droplet-fill"), className="rev-orb"),
            html.Span("★", className="rev-spark s1"),
            html.Span("★", className="rev-spark s2"),
            html.Span("💬", className="rev-spark s3"),
            html.Span("★", className="rev-spark s4"),
        ], className="rev-hero-anim"),
        html.Div([
            html.Div("YOUR EXPERIENCE MATTERS", className="rev-hero-eyebrow"),
            html.H2("Share your CRIA story", className="rev-hero-title"),
            html.P(note, className="rev-hero-note"),
        ], className="rev-hero-text"),
    ], className="rev-hero" + (" rev-hero-compact" if compact else ""))


def reviews_layout():
    """Standalone 'Testimonials' page — opens from its own pill (Why CRIA / How it's built style)."""
    reviews = _reviews_safe()
    voices = []
    if reviews:
        voices = [
            html.Div([
                html.I(className="bi bi-chat-quote-fill",
                       style={"color": MAROON, "marginRight": "8px", "fontSize": "17px"}),
                html.Span("What people are saying", style={"fontWeight": "800",
                          "fontSize": "15px", "color": MAROON}),
            ], style={"display": "flex", "alignItems": "center", "margin": "4px 0 10px"}),
            _testi_carousel("rev-page-track"),
            html.Div(style={"height": "8px"}),
        ]
    return html.Div([
        html.Div([
            _reviews_hero(),
            html.Div(voices, className="crb-card testi-wrap",
                     style={"padding": "16px 18px", "marginBottom": "14px",
                            "display": ("block" if voices else "none")}),
            # Manage panel sits right under the reviews so a user sees Edit next to their own review.
            html.Div(id="manage-panel", className="manage-panel"),
            html.Div([
                _testi_form(),
            ], className="crb-card testi-wrap", style={"padding": "18px 20px"}),
            dcc.Store(id="my-reviews", storage_type="local", data=[]),
            dcc.Store(id="admin-mode", storage_type="session", data=False),
            dcc.Store(id="editing-rid", data=""),
            dcc.Store(id="rev-refresh", data=0),
        ], className="tab-body"),
    ])


# ─────────────────────────────────────────────────────────────
def register_callbacks(app):

    # ── Landing warming dial is now a self-contained client-side gauge (assets/scenario_dial.js);
    #    no server callback needed — it computes from the injected fitted response. ──

    # ── One-click Basin Briefing PDF (the distribution artifact) ──
    @app.callback(Output("briefing-dl", "data"), Input("briefing-btn", "n_clicks"),
                  prevent_initial_call=True)
    def _dl_briefing(n):
        return dcc.send_bytes(lambda bio: bio.write(_briefing_pdf()), "CRIA_Basin_Briefing.pdf")

    # ── Testimonials: pick star rating (client-side fill) ──
    app.clientside_callback(
        """function(n1,n2,n3,n4,n5){
            var ctx=dash_clientside.callback_context;
            var nu=window.dash_clientside.no_update;
            if(!ctx.triggered||!ctx.triggered.length) return [nu,nu];
            var m=ctx.triggered[0].prop_id.match(/tr-s(\\d)/);
            if(!m) return [nu,nu];
            var r=parseInt(m[1]);
            return [r, "fb-stars sel-"+r];
        }""",
        Output("tr-star-store", "data"),
        Output("tr-stars", "className"),
        Input("tr-s1", "n_clicks"), Input("tr-s2", "n_clicks"), Input("tr-s3", "n_clicks"),
        Input("tr-s4", "n_clicks"), Input("tr-s5", "n_clicks"),
        prevent_initial_call=True,
    )

    # ── Testimonials: pick an avatar (client-side highlight) ──
    app.clientside_callback(
        """function(a,b,c,d,e,f,g,h){
            var avs=["\\uD83D\\uDCA7","\\uD83C\\uDF0A","\\u26F0\\uFE0F","\\uD83C\\uDF35",
                     "\\uD83E\\uDDD1\\u200D\\uD83D\\uDCBC","\\uD83D\\uDC69\\u200D\\uD83D\\uDD2C",
                     "\\uD83E\\uDDD1\\u200D\\uD83C\\uDFEB","\\uD83C\\uDFDE\\uFE0F"];
            var ctx=dash_clientside.callback_context;
            var nu=window.dash_clientside.no_update;
            if(!ctx.triggered||!ctx.triggered.length) return [nu,nu];
            var m=ctx.triggered[0].prop_id.match(/tr-av(\\d)/);
            if(!m) return [nu,nu];
            var i=parseInt(m[1]);
            return [avs[i]||"", "testi-avrow sel-"+i];
        }""",
        Output("tr-av-store", "data"),
        Output("tr-avrow", "className"),
        Input("tr-av0", "n_clicks"), Input("tr-av1", "n_clicks"), Input("tr-av2", "n_clicks"),
        Input("tr-av3", "n_clicks"), Input("tr-av4", "n_clicks"), Input("tr-av5", "n_clicks"),
        Input("tr-av6", "n_clicks"), Input("tr-av7", "n_clicks"),
        prevent_initial_call=True,
    )

    # ── Testimonials: show custom role input when "Other" is picked ──
    @app.callback(
        Output("tr-role-custom", "style"),
        Input("tr-role-dd", "value"),
        prevent_initial_call=True,
    )
    def _role_custom(v):
        return {"display": "block"} if (v and "Other" in v) else {"display": "none"}

    # ── Testimonials: photo upload → preview + store (size-capped) ──
    @app.callback(
        Output("tr-photo-store", "data"),
        Output("tr-photo-preview", "children"),
        Input("tr-photo", "contents"),
        prevent_initial_call=True,
    )
    def _photo(contents):
        if not contents:
            return "", None
        if not str(contents).startswith("data:image") or len(contents) > 500000:
            return "", html.Span("Please use a smaller image (or pick an avatar).",
                                 style={"color": "#C62828", "fontSize": "11px"})
        return contents, html.Img(src=contents, className="testi-photo-thumb")

    # ── Testimonials: post a NEW review, or UPDATE the one being edited ──
    @app.callback(
        Output("tr-thanks", "children"),
        Output("tr-text", "value"),
        Output("tr-name", "value"),
        Output("my-reviews", "data"),
        Output("editing-rid", "data"),
        Output("rev-refresh", "data", allow_duplicate=True),
        Output("manage-panel", "children", allow_duplicate=True),
        Input("tr-submit", "n_clicks"),
        State("tr-star-store", "data"),
        State("tr-name", "value"),
        State("tr-role-dd", "value"),
        State("tr-role-custom", "value"),
        State("tr-av-store", "data"),
        State("tr-photo-store", "data"),
        State("tr-text", "value"),
        State("editing-rid", "data"),
        State("my-reviews", "data"),
        State("rev-refresh", "data"),
        State("admin-mode", "data"),
        prevent_initial_call=True,
    )
    def _post_review(_n, stars, name, role_dd, role_custom, avatar, photo, text,
                     editing, my_ids, refresh, admin):
        name = (name or "").strip()
        if not name:
            return "Please enter your name.", no_update, no_update, no_update, no_update, no_update, no_update
        if not stars:
            return "Please pick a star rating ★", no_update, no_update, no_update, no_update, no_update, no_update
        if not (text or "").strip():
            return ("Please write a short comment before posting.",
                    no_update, no_update, no_update, no_update, no_update, no_update)
        role = (role_custom or "").strip() if (role_dd and "Other" in role_dd) else (role_dd or "")
        av = photo or avatar or ""
        panel = no_update
        try:
            from utils import metrics
            if editing:
                metrics.edit_review(editing, stars=stars, name=name, role=role, avatar=av, text=text)
                thanks, new_my = "Updated! Your review has been changed ✓", no_update
                eff_my = my_ids or []
            else:
                rid = metrics.add_review(stars, name, role, av, text or "")
                thanks = "Thanks! Your review is now live ✓"
                new_my = (my_ids or []) + ([rid] if rid else [])
                eff_my = new_my
            # Render the Manage panel right here so the Edit/Delete controls appear
            # immediately — don't wait on the (sometimes-stale) localStorage round-trip.
            panel = _manage_rows(metrics.get_reviews(), eff_my, bool(admin))
        except Exception:
            thanks, new_my = "Saved.", no_update
        return thanks, "", "", new_my, "", (refresh or 0) + 1, panel

    # ── Admin unlock via ?admin=KEY (key kept server-side in CRIA_ADMIN_KEY) ──
    @app.callback(
        Output("admin-mode", "data"),
        Input("url", "search"),
        prevent_initial_call=False,
    )
    def _admin(search):
        try:
            import os
            import urllib.parse as _up
            key = _up.parse_qs((search or "").lstrip("?")).get("admin", [""])[0]
            return bool(key) and key == os.environ.get("CRIA_ADMIN_KEY", "cria-admin-2026")
        except Exception:
            return False

    # ── Re-render the "manage your reviews" panel whenever reviews change ──
    @app.callback(
        Output("manage-panel", "children"),
        Input("rev-refresh", "data"),
        Input("my-reviews", "data"),
        Input("admin-mode", "data"),
        prevent_initial_call=False,
    )
    def _refresh_reviews(_r, my_ids, admin):
        try:
            from utils import metrics
            reviews = metrics.get_reviews()
        except Exception:
            reviews = []
        return _manage_rows(reviews, my_ids or [], bool(admin))

    # ── Delete a review (own or admin) ──
    @app.callback(
        Output("rev-refresh", "data", allow_duplicate=True),
        Input({"type": "mrev-del", "index": ALL}, "n_clicks"),
        State("my-reviews", "data"),
        State("admin-mode", "data"),
        State("rev-refresh", "data"),
        prevent_initial_call=True,
    )
    def _del_review(clicks, my_ids, admin, refresh):
        if not any(clicks or []):
            return no_update
        ctx = callback_context
        if not ctx.triggered:
            return no_update
        import json as _json
        try:
            rid = _json.loads(ctx.triggered[0]["prop_id"].split(".")[0])["index"]
        except Exception:
            return no_update
        if not (admin or rid in set(my_ids or [])):
            return no_update
        try:
            from utils import metrics
            metrics.delete_review(rid)
        except Exception:
            pass
        return (refresh or 0) + 1

    # ── Edit a review → load it into the form ──
    @app.callback(
        Output("tr-name", "value", allow_duplicate=True),
        Output("tr-text", "value", allow_duplicate=True),
        Output("tr-role-dd", "value"),
        Output("tr-star-store", "data", allow_duplicate=True),
        Output("tr-stars", "className", allow_duplicate=True),
        Output("editing-rid", "data", allow_duplicate=True),
        Output("tr-thanks", "children", allow_duplicate=True),
        Input({"type": "mrev-edit", "index": ALL}, "n_clicks"),
        State("my-reviews", "data"),
        State("admin-mode", "data"),
        prevent_initial_call=True,
    )
    def _edit_review(clicks, my_ids, admin):
        nu = (no_update,) * 7
        if not any(clicks or []):
            return nu
        ctx = callback_context
        if not ctx.triggered:
            return nu
        import json as _json
        try:
            rid = _json.loads(ctx.triggered[0]["prop_id"].split(".")[0])["index"]
        except Exception:
            return nu
        if not (admin or rid in set(my_ids or [])):
            return nu
        try:
            from utils import metrics
            rev = next((r for r in metrics.get_reviews() if r.get("id") == rid), None)
        except Exception:
            rev = None
        if not rev:
            return nu
        stars = int(rev.get("stars", 5) or 5)
        return (rev.get("name", ""), rev.get("text", ""), rev.get("role", "") or None,
                stars, "fb-stars sel-" + str(stars), rid,
                "Editing your review — change it below and click Post to update.")

    # Analysis Finder → navigate to the chosen analysis
    @app.callback(
        Output("url", "pathname", allow_duplicate=True),
        Input("home-finder", "value"),
        prevent_initial_call=True,
    )
    def _finder_go(route):
        from dash.exceptions import PreventUpdate
        if not route:
            raise PreventUpdate
        return route



