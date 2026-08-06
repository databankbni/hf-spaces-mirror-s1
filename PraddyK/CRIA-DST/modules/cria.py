"""
modules/cria.py — Infrastructure Asset Framework (Objective 3: managing the Colorado River as an infrastructure asset)

The project's end-vision: treat the Colorado River as an infrastructure asset by fusing
BIOPHYSICAL assets (water, snow, storage — covered by this tool's hydrology tabs) with
SOCIOPOLITICAL assets (governance, legal, institutional — covered by the Governance tab).
The project's CRIA prototype is a separate ShinyApp (Annual Progress Report, Feb 2025, Fig 4).
The BIOPHYSICAL asset condition is scored live here (Normal/Caution/Critical per sub-basin) from
the real VIC reanalysis using the validated ASI signals; the SOCIOPOLITICAL asset scores and the
stakeholder-agreed weights come from the project's separate co-development process and are not
estimated here.
"""
from dash import html
import dash_bootstrap_components as dbc

NAVY="#0D2137"; MAROON="#8C1D40"; BLUE="#01579B"; GREEN="#2E7D32"; ORANGE="#E65100"; GREY="#94a3b8"

BIOPHYSICAL = [
    ("Surface water / runoff", "/snowpack", True),
    ("Snowpack (SWE)", "/snowpack", True),
    ("Soil moisture", "/links", True),
    ("Terrestrial water storage", "/tws", True),
    ("Groundwater", "/storage", True),
    ("Drought state", "/drought", True),
]
SOCIOPOLITICAL = [
    ("Water allocations / compacts", "/governance", True),
    ("Interstate & tribal governance", "/governance", True),
    ("Reservoir operations (CRSS)", "/reservoirs", True),
    ("Stakeholder / institutional capacity", None, False),
    ("Legal & policy vulnerability scoring", None, False),
]


def _src(text):
    return html.Div(text, style={"fontSize": "10px", "color": "#1e293b", "fontStyle": "italic",
                                  "padding": "2px 4px 0"})


def _asset_row(name, route, covered):
    icon = "bi-check-circle-fill" if covered else "bi-dash-circle"
    color = GREEN if covered else GREY
    label = html.A(name, href=route, style={"color": NAVY, "fontWeight": "600",
                                            "textDecoration": "none"}) if route else \
            html.Span(name, style={"color": "#1e293b", "fontWeight": "600"})
    tag = ("in this tool" if (covered and route) else
           "via report" if covered else "no data available")
    tagcol = GREEN if covered else ORANGE
    return html.Div([
        html.I(className=f"bi {icon}", style={"color": color, "marginRight": "8px", "fontSize": "13px"}),
        label,
        html.Span(tag, style={"marginLeft": "auto", "fontSize": "9.5px", "fontWeight": "600",
                              "color": tagcol, "background": f"{tagcol}1a",
                              "padding": "1px 7px", "borderRadius": "8px"}),
    ], style={"display": "flex", "alignItems": "center", "padding": "6px 0",
              "borderBottom": "1px solid #f0f0f0"})


def _phase(num, title, items, status):
    """status: 'done' | 'active' | 'planned'."""
    cfg = {"done":   (GREEN,  "bi-check-circle-fill", "Live now"),
           "active": (BLUE,   "bi-arrow-repeat",      "In progress"),
           "planned":(GREY,   "bi-circle",            "Planned — next milestone")}
    col, icon, tag = cfg[status]
    return html.Div([
        html.Div([
            html.Span(str(num), style={"display": "inline-flex", "alignItems": "center",
                "justifyContent": "center", "width": "26px", "height": "26px", "borderRadius": "50%",
                "background": col, "color": "#fff", "fontWeight": "800", "fontSize": "13px",
                "marginRight": "10px", "flex": "0 0 auto"}),
            html.Span(title, style={"fontWeight": "700", "fontSize": "13px", "color": NAVY}),
            html.Span([html.I(className=f"bi {icon}", style={"marginRight": "5px"}), tag],
                      style={"marginLeft": "auto", "fontSize": "10px", "fontWeight": "700",
                             "color": col, "background": f"{col}1a", "padding": "2px 9px",
                             "borderRadius": "9px", "whiteSpace": "nowrap"}),
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "5px"}),
        html.Div(items, style={"fontSize": "11px", "color": "#37474f", "lineHeight": "1.5",
                               "paddingLeft": "36px"}),
    ], style={"borderLeft": f"3px solid {col}", "padding": "10px 14px", "marginBottom": "10px",
              "background": f"{col}0d", "borderRadius": "0 6px 6px 0"})


BASIN_NAMES = {
    "CRB": "Colorado River Basin", "UpperBasin": "Upper Basin", "LowerBasin": "Lower Basin",
    "Green": "Green River", "SanJuan": "San Juan", "UpperColo": "Upper Colorado",
    "GlenCanyon": "Glen Canyon", "Gila": "Gila River", "GrandCanyon": "Grand Canyon",
    "LittleColo": "Little Colorado", "LowerColo": "Lower Colorado",
}


def _status(score):
    """Biophysical condition class, tied to the basin's own baseline (ASI scale,
    50 = baseline mean, 15 points = 1 SD). >=65 (>=1 SD worse) = Critical."""
    if score >= 65: return ("Critical", MAROON)
    if score >= 55: return ("Caution", ORANGE)
    return ("Normal", GREEN)


def _scorecard_rows():
    """Live biophysical asset score per basin from the real VIC reanalysis.
    Reuses the validated ASI signals (runoff efficiency, dryness, soil moisture,
    warming), each standardized against the basin's own WY1984–2024 baseline.
    Returns None if the data cache is unavailable (tab then hides the scorecard)."""
    try:
        import numpy as np
        from utils.data_loader import load_vic_annual
        df = load_vic_annual()
        if df is None or df.empty:
            return None
        d = df.copy()
        d["RE"] = (d["OUT_RUNOFF"] + d["OUT_BASEFLOW"]) / d["OUT_PREC"]
        d["DRY"] = d["OUT_EVAP"] / d["OUT_PREC"]

        def z(s):
            sd = s.std(ddof=0)
            return (s - s.mean()) / sd if sd > 0 else s * 0.0

        rows = []
        for b, g in d.groupby("basin"):
            g = g.sort_values("water_year").copy()
            g["sRE"] = -z(g["RE"]); g["sDRY"] = z(g["DRY"])
            g["sSM"] = -z(g["OUT_SOIL_MOIST"]); g["sT"] = z(g["OUT_AIR_TEMP"])
            g["ASI"] = np.clip(50 + (g["sRE"] + g["sDRY"] + g["sSM"] + g["sT"]) / 4 * 15, 0, 100)
            recent = g[g["water_year"] >= g["water_year"].max() - 2]   # most recent 3 WYs
            score = float(recent["ASI"].mean())
            yrs = g["water_year"].values.astype(float)
            slope = float(np.polyfit(yrs, g["ASI"].values, 1)[0] * 10) if len(g) > 2 else 0.0
            drv = {"low runoff": recent["sRE"].mean(), "high dryness": recent["sDRY"].mean(),
                   "low soil moisture": recent["sSM"].mean(), "warming": recent["sT"].mean()}
            top = max(drv, key=drv.get)
            rows.append({"basin": b, "name": BASIN_NAMES.get(b, b),
                         "score": score, "slope": slope, "driver": top})
        rows.sort(key=lambda r: r["score"], reverse=True)
        return rows
    except Exception:
        return None


def _score_row(r):
    label, col = _status(r["score"])
    if r["slope"] > 0.5:   trend = ("▲ worsening", MAROON)
    elif r["slope"] < -0.5: trend = ("▼ improving", GREEN)
    else:                  trend = ("— stable", GREY)
    return html.Div([
        html.Span(r["name"], style={"fontWeight": "700", "fontSize": "12px", "color": NAVY,
                                    "flex": "1 1 150px", "minWidth": "120px"}),
        html.Span(f"{r['score']:.1f}", style={"fontWeight": "800", "fontSize": "15px",
                  "color": col, "width": "46px", "textAlign": "right"}),
        html.Span(label, style={"fontSize": "10px", "fontWeight": "700", "color": col,
                  "background": f"{col}1a", "padding": "2px 9px", "borderRadius": "9px",
                  "width": "62px", "textAlign": "center"}),
        html.Span(trend[0], style={"fontSize": "10.5px", "fontWeight": "600", "color": trend[1],
                  "width": "92px", "textAlign": "center"}),
        html.Span(f"driver: {r['driver']}", style={"fontSize": "10.5px", "color": "#546e7a",
                  "flex": "1 1 130px", "textAlign": "right"}),
    ], style={"display": "flex", "alignItems": "center", "gap": "10px", "flexWrap": "wrap",
              "padding": "7px 4px", "borderBottom": "1px solid #f0f0f0",
              "borderLeft": f"4px solid {col}", "paddingLeft": "10px", "marginBottom": "2px",
              "background": f"{col}08", "borderRadius": "0 4px 4px 0"})


def _scorecard_anim_uri(rows):
    """Build the animated scorecard as a self-contained data: URI — the animation template
       with THIS render's live data injected, so it always reflects the current VIC
       computation (no static snapshot). Returns None if the template is unavailable, in
       which case the card falls back to the static rows."""
    import json
    import os
    import urllib.parse
    try:
        tpl = open(os.path.join("assets", "cria_scorecard_template.html"), encoding="utf-8").read()
    except Exception:
        return None
    data = []
    for r in rows:
        s = float(r["score"])
        status = "Critical" if s >= 65 else ("Caution" if s >= 55 else "Normal")
        data.append({"name": r["name"], "score": round(s, 2),
                     "slope": round(float(r["slope"]), 2),
                     "driver": r["driver"], "status": status})
    return "data:text/html;charset=utf-8," + urllib.parse.quote(tpl.replace("__DATA__", json.dumps(data)))


def _scorecard_card():
    rows = _scorecard_rows()
    if not rows:
        return None
    n_crit = sum(1 for r in rows if r["score"] >= 65)
    n_caut = sum(1 for r in rows if 55 <= r["score"] < 65)
    anim = _scorecard_anim_uri(rows)
    return html.Div([
        html.Div([
            html.I(className="bi bi-clipboard2-pulse", style={"marginRight": "8px", "color": MAROON}),
            html.Span("Biophysical asset scorecard — basin condition (live from VIC + observations)",
                      style={"fontWeight": "700", "fontSize": "13px"}),
        ], className="crb-card-header"),
        html.Div([
            html.P(["Each sub-basin is scored 0–100 from the same validated, observation-based signals as the "
                    "Aridity Severity Index — runoff efficiency, dryness (ET/P), soil moisture and "
                    "warming — standardized against the basin's own WY1984–2024 baseline "
                    "(50 = baseline; +15 = one standard deviation worse). Condition is the most-recent "
                    "3-year mean. This realizes the project's biophysical asset-tracking "
                    "(Normal / Caution / Critical) from observed and modelled hydrology."],
                   style={"fontSize": "11.5px", "color": "#37474f", "lineHeight": "1.6",
                          "marginBottom": "6px"}),
            # Live animated scorecard — each sub-basin eases from baseline (50) to its current
            # condition score; roll-up counts, drivers and trend are shown in the reveal itself.
            # Generated live from this render's data (data: URI), so it always stays current.
            html.Div(
                html.Iframe(src=anim,
                            title="Biophysical asset scorecard — live animated reveal",
                            style={"position": "absolute", "top": 0, "left": 0,
                                   "width": "100%", "height": "100%", "border": "0"}),
                style={"position": "relative", "width": "100%", "height": 0,
                       "paddingBottom": "56.25%", "overflow": "hidden",
                       "borderRadius": "12px", "border": "1px solid #eef0f3",
                       "margin": "6px 0 12px"})
            if anim else html.Div([_score_row(r) for r in rows]),
            html.Div([
                html.I(className="bi bi-info-circle", style={"marginRight": "6px", "color": MAROON}),
                html.B("Scope: "),
                "Biophysical condition only, from observed/modelled hydrology. The full CRIA framework "
                "additionally integrates sociopolitical asset scores and stakeholder-agreed weights — "
                "those come from the project's separate co-development process and are not estimated here.",
            ], style={"fontSize": "10.5px", "color": "#8a5a00", "background": "#fff8e1",
                      "borderLeft": f"3px solid {ORANGE}", "padding": "8px 12px",
                      "borderRadius": "0 6px 6px 0", "marginTop": "10px", "lineHeight": "1.5"}),
        ], style={"padding": "12px 16px"}),
        _src("Score method: validated ASI signals (this tool: VIC reanalysis with SNOTEL, GRACE and SMAP). "
             "Framework: NASA Annual Progress Report, Feb 2025, Fig. 4."),
    ], className="crb-card", style={"marginBottom": "16px", "borderTop": f"3px solid {MAROON}"})


def layout():
    return html.Div([
        html.Div([
            html.H2("Infrastructure Asset Framework"),
            html.P("The project's organizing vision: manage the river as an infrastructure asset by "
                   "fusing biophysical and sociopolitical assets. This tab maps the development "
                   "roadmap — what this tool delivers today and what comes next."),
        ], className="tab-header"),
        html.Div([
            # Concept
            html.Div([
                html.Div("The framework", className="crb-card-header",
                         style={"fontWeight": "700", "fontSize": "13px"}),
                html.Div([
                    html.P(["CRIA treats the Colorado River system as a portfolio of ",
                            html.B("biophysical assets"), " (the water itself — runoff, snow, storage) and ",
                            html.B("sociopolitical assets"), " (the rules and institutions that govern it — "
                            "compacts, allocations, reservoir operations). Resilience depends on both. "
                            "This tool is a prototype of the biophysical half plus the governance entry-point "
                            "to the sociopolitical half."],
                           style={"fontSize": "12px", "color": "#37474f", "lineHeight": "1.6", "marginBottom": "6px"}),
                    _src("Source: NASA Annual Progress Report, Feb 2025, Fig. 4 (CRIA prototype, Vivoni et al., ASU). "
                         "Official CRIA prototype: chiproject.shinyapps.io/colorado-river-tool"),
                ], style={"padding": "10px 16px"}),
            ], className="crb-card", style={"marginBottom": "16px"}),

            # Live biophysical asset scorecard (real data — realizes the project's asset tracking)
            _scorecard_card(),

            # Two asset columns
            dbc.Row([
                dbc.Col(html.Div([
                    html.Div([html.I(className="bi bi-droplet-half", style={"marginRight": "8px", "color": BLUE}),
                              html.Span("Biophysical assets", style={"fontWeight": "700", "fontSize": "13px"})],
                             className="crb-card-header"),
                    html.Div([_asset_row(*a) for a in BIOPHYSICAL], style={"padding": "8px 16px"}),
                    _src("Covered live by this tool's hydrology tabs (VIC reanalysis with SNOTEL, GRACE and SMAP)."),
                ], className="crb-card"), md=6),
                dbc.Col(html.Div([
                    html.Div([html.I(className="bi bi-people-fill", style={"marginRight": "8px", "color": MAROON}),
                              html.Span("Sociopolitical assets", style={"fontWeight": "700", "fontSize": "13px"})],
                             className="crb-card-header"),
                    html.Div([_asset_row(*a) for a in SOCIOPOLITICAL], style={"padding": "8px 16px"}),
                    _src("Governance & reservoir entry-points added; full institutional scoring pending."),
                ], className="crb-card"), md=6),
            ], className="g-3 mb-3"),

            # Development roadmap (reframes the asset-scoring gap as a deliberate milestone)
            html.Div([
                html.Div("Development roadmap", className="crb-card-header",
                         style={"fontWeight": "700", "fontSize": "13px"}),
                html.Div([
                    html.P("The full CRIA framework scores each sub-basin on combined biophysical + "
                           "sociopolitical vulnerability to rank management priorities. This tool builds "
                           "toward that in three phases:",
                           style={"fontSize": "12px", "color": "#37474f", "marginBottom": "12px"}),
                    _phase(1, "Biophysical asset monitoring", [
                        "VIC runoff, snowpack (SWE), soil moisture and storage; GRACE terrestrial water "
                        "storage; SNOTEL SWE; drought state — all computed live from observed and reanalysis data in this tool."],
                        "done"),
                    _phase(2, "Sociopolitical entry-points", [
                        "Water allocations & compacts, interstate/tribal governance, and reservoir "
                        "operations (CRSS tier ladder) are surfaced as governance entry-points. "
                        "Quantitative institutional coupling is the active work."],
                        "active"),
                    _phase(3, "Combined asset-vulnerability scoring", [
                        "The biophysical asset scorecard above now scores every sub-basin "
                        "Normal / Caution / Critical live from the VIC reanalysis and observations. "
                        "Integrating the project's sociopolitical asset scores and stakeholder-agreed "
                        "weights into a single biophysical + sociopolitical vulnerability index — drawn "
                        "from the separate CRIA stakeholder process — is the remaining milestone."],
                        "active"),
                ], style={"padding": "12px 16px"}),
                _src("Source: NASA Annual Progress Report, Feb 2025, Fig. 4 (CRIA framework). "
                     "Phase-3 asset-score dataset not yet provided."),
            ], className="crb-card", style={"marginBottom": "16px"}),

            # Scope statement
            html.Div([
                html.Div("Where this tool sits in the project", style={"fontWeight": "700", "fontSize": "12px",
                                                                       "color": MAROON, "marginBottom": "4px"}),
                html.P("This application is a prototype of the project's hydrologic/biophysical "
                       "decision-support component (Objectives 1–2) plus the governance entry-point to "
                       "Objective 3. It complements — and is a step toward — the complete CRIA framework, "
                       "which additionally integrates quantified sociopolitical asset scoring and full CRSS "
                       "operational coupling.",
                       style={"fontSize": "11.5px", "color": "#37474f", "lineHeight": "1.6", "marginBottom": 0}),
            ], className="crb-card"),
        ], className="tab-body"),
    ])


def register_callbacks(app):
    pass
