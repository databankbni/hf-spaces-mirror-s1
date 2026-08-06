"""
modules/governance.py — Water Governance (the "Law of the River")

Covers Objective 3 (sociopolitical) of the NASA project. The ASU team conducted a
Colorado River Basin water-governance analysis 1922–2022 (NASA Annual Review, Feb 2024).
Allocation and agreement facts here are public "Law of the River" records (U.S. Bureau of
Reclamation). Every block states its source; where a value is not available it is marked
"No data available".
"""
import plotly.graph_objects as go
from dash import html, dcc
import dash_bootstrap_components as dbc
from utils.charts import lollipop_h

NAVY="#0D2137"; MAROON="#8C1D40"; BLUE="#01579B"; GREEN="#2E7D32"; ORANGE="#E65100"; GOLD="#FFC627"; GREY="#94a3b8"

# ── Key agreements (public Law of the River record; USBR) ───────
TIMELINE = [
    (1922, "Colorado River Compact", "Divides the basin into Upper & Lower, 7.5 MAF/yr each"),
    (1928, "Boulder Canyon Project Act", "Authorizes Hoover Dam & Lake Mead; Lower Basin apportionment"),
    (1944, "U.S.–Mexico Water Treaty", "Guarantees Mexico 1.5 MAF/yr"),
    (1948, "Upper Colorado River Basin Compact", "Splits Upper Basin by percentage among states"),
    (1963, "Arizona v. California", "Supreme Court fixes Lower Basin state shares"),
    (1968, "Colorado River Basin Project Act", "Authorizes the Central Arizona Project (CAP)"),
    (2007, "Interim Guidelines", "First coordinated Mead/Powell shortage-sharing rules"),
    (2019, "Drought Contingency Plan (DCP)", "Additional voluntary cutbacks to protect reservoirs"),
    (2021, "First-ever Tier 1 Shortage", "USBR declares shortage for 2022 — unprecedented"),
    (2026, "Post-2026 Renegotiation", "New operating guidelines under negotiation"),
]

# ── Allocations (MAF/yr) — public; USBR Law of the River ────────
BASIN_ALLOC = [("Upper Basin", 7.5), ("Lower Basin", 7.5), ("Mexico (1944 Treaty)", 1.5)]
LOWER_STATES = [("California", 4.4), ("Arizona", 2.8), ("Nevada", 0.3)]   # Boulder Canyon Act / AZ v CA 1963
UPPER_STATES = [("Colorado", 51.75), ("Utah", 23.0), ("Wyoming", 14.0), ("New Mexico", 11.25)]  # 1948 Compact (% of Upper share); Arizona ~50 KAF fixed


def _tile(v, l, c):
    return html.Div([html.Div(v, className="info-tile-value"),
        html.Div(l, className="info-tile-label")], className=f"info-tile {c}")


def _timeline_fig():
    yrs = [t[0] for t in TIMELINE]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=yrs, y=[0]*len(yrs), mode="markers",
        marker=dict(size=16, color=[MAROON if y == 2021 else NAVY for y in yrs],
                    line=dict(color="white", width=2)),
        customdata=[(t[1], t[2]) for t in TIMELINE],
        hovertemplate="<b>%{x} — %{customdata[0]}</b><br>%{customdata[1]}<extra></extra>"))
    for i, (yr, name, _) in enumerate(TIMELINE):
        fig.add_annotation(x=yr, y=0.16 if i % 2 == 0 else -0.16,
            text=f"<b>{yr}</b><br>{name}", showarrow=True, arrowhead=0, arrowwidth=1,
            arrowcolor="#cbd5e1", ax=0, ay=-26 if i % 2 == 0 else 26,
            font=dict(size=9, color=NAVY), align="center",
            bgcolor="rgba(255,255,255,0.92)", bordercolor="#e2e8f0", borderwidth=1, borderpad=3)
    fig.add_shape(type="line", x0=1918, x1=2030, y0=0, y1=0, line=dict(color="#cbd5e1", width=2))
    fig.update_layout(height=300, margin=dict(l=10, r=10, t=20, b=10),
        paper_bgcolor="white", plot_bgcolor="white",
        xaxis=dict(range=[1916, 2032], showgrid=False, tickfont=dict(size=10)),
        yaxis=dict(visible=False, range=[-0.5, 0.5]), showlegend=False)
    return fig


def _alloc_fig():
    return lollipop_h([a[0] for a in BASIN_ALLOC], [a[1] for a in BASIN_ALLOC],
                      [BLUE, MAROON, GREEN], x_title="Apportionment (MAF/yr)",
                      unit=" MAF", height=210)


def _lower_fig():
    # smallest → largest for a clean lollipop ladder
    rows = sorted(LOWER_STATES, key=lambda s: s[1])
    return lollipop_h([s[0] for s in rows], [s[1] for s in rows],
                      [ORANGE, MAROON, BLUE], x_title="Apportionment (MAF/yr)",
                      unit=" MAF", height=230)


def _upper_fig():
    fig = go.Figure(go.Pie(
        labels=[s[0] for s in UPPER_STATES], values=[s[1] for s in UPPER_STATES], hole=0.5,
        marker=dict(colors=[BLUE, GREEN, ORANGE, "#6A1B9A"], line=dict(color="white", width=2)),
        textinfo="label+percent", sort=False,
        hovertemplate="%{label}: %{value}% of Upper Basin share<extra></extra>"))
    fig.update_layout(height=230, margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="white", showlegend=False)
    return fig


def _src(text):
    return html.Div(text, style={"fontSize": "10px", "color": "#1e293b", "fontStyle": "italic",
                                  "padding": "2px 16px 10px"})


def layout():
    return html.Div([
        html.Div([
            html.H2("Water Governance — the “Law of the River”"),
            html.P("The institutional framework that allocates the Colorado River. "
                   "Objective 3 of the project: a basin governance analysis (1922–2022)."),
        ], className="tab-header"),
        html.Div([
            html.Div([
                _tile("1922", "Colorado River Compact", "tile-maroon"),
                _tile("7 + Mexico", "States + treaty partner", "tile-navy"),
                _tile("16.5 MAF", "Total apportioned / yr", "tile-blue"),
                _tile("30", "Federally recognized tribes", "tile-green"),
            ], style={"display": "grid", "gridTemplateColumns": "repeat(auto-fit,minmax(150px,1fr))",
                      "gap": "10px", "marginBottom": "16px"}),

            # Timeline
            html.Div([
                html.Div([html.Span("Key agreements — “Law of the River”", style={"fontWeight": "700", "fontSize": "13px"}),
                    html.Span("hover any milestone", style={"color": "#1e293b", "fontSize": "11px"})],
                    className="crb-card-header"),
                dcc.Graph(figure=_timeline_fig(), config={"displayModeBar": False}, style={"height": "300px"}),
                _src("Source: U.S. Bureau of Reclamation — Law of the River (public record). "
                     "Project governance analysis 1922–2022: NASA Annual Review, Feb 2024 (Vivoni, White et al., ASU)."),
            ], className="crb-card", style={"marginBottom": "16px"}),

            # Allocations
            dbc.Row([
                dbc.Col(html.Div([
                    html.Div("Basin & treaty apportionment", className="crb-card-header",
                             style={"fontWeight": "700", "fontSize": "13px"}),
                    dcc.Graph(figure=_alloc_fig(), config={"displayModeBar": False}, style={"height": "210px"}),
                    _src("Source: 1922 Colorado River Compact + 1944 U.S.–Mexico Treaty (USBR)."),
                ], className="crb-card"), md=12),
            ], className="g-3 mb-3"),

            dbc.Row([
                dbc.Col(html.Div([
                    html.Div("Lower Basin — state shares", className="crb-card-header",
                             style={"fontWeight": "700", "fontSize": "13px"}),
                    dcc.Graph(figure=_lower_fig(), config={"displayModeBar": False}, style={"height": "230px"}),
                    _src("Source: Boulder Canyon Project Act (1928); Arizona v. California (1963). MAF/yr."),
                ], className="crb-card"), md=6),
                dbc.Col(html.Div([
                    html.Div("Upper Basin — state shares", className="crb-card-header",
                             style={"fontWeight": "700", "fontSize": "13px"}),
                    dcc.Graph(figure=_upper_fig(), config={"displayModeBar": False}, style={"height": "230px"}),
                    _src("Source: Upper Colorado River Basin Compact (1948) — % of the Upper Basin share "
                         "(Arizona holds a fixed ~50 KAF)."),
                ], className="crb-card"), md=6),
            ], className="g-3 mb-3"),

            # Tribal rights — partial data
            html.Div([
                html.Div("Tribal water rights", className="crb-card-header",
                         style={"fontWeight": "700", "fontSize": "13px"}),
                html.Div([
                    html.P("Thirty federally recognized tribes hold rights to a substantial share of "
                           "Colorado River water. These are largely senior “Winters” reserved rights — "
                           "with priority dating to each reservation's establishment — so they sit ahead "
                           "of many state allocations in the priority system. The Ten Tribes Partnership "
                           "represents the tribes with the largest quantified entitlements, while several "
                           "major claims (including parts of the Navajo Nation's) remain unquantified or "
                           "in active settlement.",
                           style={"fontSize": "12px", "color": "#37474f", "marginBottom": "8px",
                                  "lineHeight": "1.55"}),
                    html.Div([
                        "A complete, quantified tribe-by-tribe allocation is a legal dataset that is not "
                        "bundled with this project. For authoritative figures see:",
                    ], style={"fontSize": "11px", "color": "#546e7a", "marginBottom": "8px"}),
                    html.A("Ten Tribes Partnership — Reclamation →",
                           href="https://www.usbr.gov/ColoradoRiverBasin/", target="_blank",
                           style={"background": GREEN, "color": "white", "textDecoration": "none",
                                  "borderRadius": "6px", "padding": "6px 14px", "fontSize": "12px",
                                  "fontWeight": "700", "display": "inline-block"}),
                ], style={"padding": "10px 16px"}),
                _src("Sources: Winters v. United States (1908); USBR / Ten Tribes Partnership (public). "
                     "Per-tribe quantified allocations are legal-settlement data, not bundled in this project."),
            ], className="crb-card", style={"marginBottom": "16px"}),

            # Why it matters
            html.Div([
                html.Div("Why governance matters here", style={"fontWeight": "700", "fontSize": "12px",
                                                               "color": MAROON, "marginBottom": "4px"}),
                html.P("The 1922 Compact allocated 16.5 MAF/yr based on an unusually wet early-1900s "
                       "record. The hydrologic tabs in this tool show the basin now yields well below "
                       "that — the structural gap that drives the post-2026 renegotiation. Governance "
                       "(sociopolitical assets) and hydrology (biophysical assets) together form the "
                       "project's CRIA framework.",
                       style={"fontSize": "11.5px", "color": "#37474f", "lineHeight": "1.6", "marginBottom": 0}),
            ], className="crb-card"),
        ], className="tab-body"),
    ])


def register_callbacks(app):
    pass
