# ============================================================
# CRB DST — app.py
# Colorado River Basin Decision Support Tool
# Python Dash + HuggingFace Spaces deployment
# ============================================================

import os
# Force the Dash dev-tools / debug toolbar OFF everywhere — users must never see the
# "Callbacks / Errors / Server / Dash update available" overlay, even if an env var is set.
for _k in ("DASH_DEBUG", "DASH_DEV_TOOLS_UI", "DASH_DEV_TOOLS_PROPS_CHECK",
           "DASH_HOT_RELOAD", "DASH_DEV_TOOLS_HOT_RELOAD",
           "DASH_DEV_TOOLS_SERVE_DEV_BUNDLES"):
    os.environ[_k] = "false"

import dash
from dash import html, dcc, Input, Output, State
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import plotly.io as pio
# ── App init ─────────────────────────────────────────────────
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP,
        "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css"],
    suppress_callback_exceptions=True,
    title="CRIA — Colorado River Integrated Assessment",
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)
server = app.server  # for gunicorn

# ── Custom Plotly theme (same feel as CRB-WRDST) ────────────
import plotly.graph_objects as go

crb_template = go.layout.Template()
crb_template.layout = go.Layout(
    font=dict(family="Inter, sans-serif", size=12, color="#1e293b"),
    paper_bgcolor="white",
    plot_bgcolor="white",
    # richer, professional colorway
    colorway=["#8C1D40","#01579B","#2E7D32","#E65100","#4527A0","#00838F","#C62828","#00695C"],
    # automargin=True → Plotly auto-expands the plot margins to fit tick labels
    # and axis titles at ANY container size, so text never clips or spills out.
    xaxis=dict(showgrid=True, gridcolor="#eef2f6", gridwidth=1, linecolor="#e0e0e0",
               tickfont=dict(size=11), zeroline=False, automargin=True),
    yaxis=dict(showgrid=True, gridcolor="#eef2f6", gridwidth=1, linecolor="#e0e0e0",
               tickfont=dict(size=11), zeroline=False, automargin=True),
    margin=dict(l=50, r=20, t=40, b=40),
    legend=dict(bgcolor="rgba(255,255,255,0.9)", bordercolor="#e0e0e0", borderwidth=1,
                font=dict(size=11)),
    # polished rounded bars + clean hover + smooth transitions on update
    barcornerradius=6,
    bargap=0.28,
    hovermode="closest",
    hoverlabel=dict(bgcolor="white", bordercolor="#cfd8dc",
                    font=dict(size=12, color="#0D2137", family="Inter, sans-serif")),
    transition=dict(duration=450, easing="cubic-in-out"),
)
# default bar styling — no harsh outlines
crb_template.data.bar = [go.Bar(marker=dict(line=dict(width=0)))]
pio.templates["crb"] = crb_template
pio.templates.default = "crb"# ── Basin + Variable dictionaries ───────────────────────────
BASINS = {
    "CRB":        "Colorado River Basin",
    "UpperBasin": "Upper Basin",
    "LowerBasin": "Lower Basin",
    "Green":      "Green River",
    "SanJuan":    "San Juan",
    "GrandCanyon":"Grand Canyon",
    "Gila":       "Gila River",
}

VIC_VARS = {
    "OUT_PREC":      {"label": "Precipitation",        "unit": "mm/yr",   "color": "#0D2137"},
    "OUT_RUNOFF":    {"label": "Surface Runoff",        "unit": "mm/yr",   "color": "#8C1D40"},
    "OUT_BASEFLOW":  {"label": "Baseflow",              "unit": "mm/yr",   "color": "#4527A0"},
    "OUT_EVAP":      {"label": "Total ET",              "unit": "mm/yr",   "color": "#2E7D32"},
    "OUT_EVAP_CANOP":{"label": "Canopy Evaporation",   "unit": "mm/yr",   "color": "#388E3C"},
    "OUT_TRANSP_VEG":{"label": "Transpiration",         "unit": "mm/yr",   "color": "#1B5E20"},
    "OUT_EVAP_BARE": {"label": "Bare Soil Evaporation", "unit": "mm/yr",   "color": "#A5D6A7"},
    "OUT_SWE":       {"label": "Snow Water Equiv (SWE)","unit": "mm",      "color": "#01579B"},
    "OUT_SNOW_MELT": {"label": "Snowmelt",              "unit": "mm/yr",   "color": "#0288D1"},
    "OUT_SOIL_MOIST":{"label": "Soil Moisture",         "unit": "mm",      "color": "#E65100"},
    "OUT_AIR_TEMP":  {"label": "Air Temperature",       "unit": "°C",      "color": "#C62828"},
    "OUT_LATENT":    {"label": "Latent Heat Flux",      "unit": "W/m²",    "color": "#00695C"},
}

# ── Navigation structure ─────────────────────────────────────
# Per-view metadata: route key → (sub-tab label, sidebar/section icon)
VIEW_LABELS = {
    "home":          ("Basin Overview",                       "bi-water"),
    "snowpack":      ("Snowpack & Runoff",                    "bi-snow"),
    "watbal":        ("Basin Water Balance",                  "bi-droplet"),
    "timing":        ("Snowmelt Timing",                      "bi-calendar3"),
    "links":         ("Soil Moisture & Streamflow",           "bi-link-45deg"),
    "october":       ("October Signal",                       "bi-calendar-check"),
    "elevsnow":      ("Elevation-Dependent Snow Loss",        "bi-graph-down-arrow"),
    "warming":       ("Surface Warming & Energy",             "bi-thermometer-high"),
    "references":    ("References & Validation",              "bi-journal-check"),
    "tws":           ("Water Storage — GRACE",                "bi-globe-americas"),
    "storage":       ("Subsurface Storage",                   "bi-bank"),
    "drought":       ("Drought & Shortage Risk",              "bi-exclamation-triangle"),
    "cascade":       ("Drought Propagation",                  "bi-diagram-3"),
    "recovery":      ("Drought Recovery",                     "bi-arrow-repeat"),
    "aridification": ("Aridification",                        "bi-thermometer-sun"),
    "asi":           ("Aridity Severity Index",               "bi-bar-chart-steps"),
    "budyko":        ("Budyko Water–Energy Balance",          "bi-vector-pen"),
    "scenario":      ("Scenario Explorer",                    "bi-sliders"),
    "future":        ("Projections to 2100",                  "bi-graph-up-arrow"),
    "noanalog":      ("No-Analog Climate",                    "bi-eye"),
    "nmme":          ("Seasonal Forecasts (NMME)",            "bi-cloud-drizzle"),
    "cmip":          ("Climate Projections (CMIP5/6)",        "bi-thermometer-half"),
    "cria":          ("Infrastructure Asset Framework",       "bi-diagram-3-fill"),
    "workflow":      ("How This Tool Is Built",               "bi-diagram-2"),
    "governance":    ("Water Governance",                     "bi-bank2"),
    "reservoirs":    ("Reservoirs & Shortage Tiers",          "bi-moisture"),
    "uncertainty":   ("Uncertainty & Confidence",             "bi-plusminus"),
    "spatial":       ("Maps Over Time",                       "bi-map"),
    "spatcompare":   ("Compare by Year",                      "bi-layout-split"),
    "basinwide":     ("Basin-Wide Overview",                  "bi-grid-3x3-gap"),
    "animations":    ("Seasonal Cycles",                      "bi-play-circle"),
    "methods":       ("Methods & Data",                       "bi-book"),
    "publications":  ("Publications",                         "bi-journals"),
    "team":          ("Research Team",                        "bi-people-fill"),
}

# 7 top-level groups. Each group's first view is its landing route.
# Decision-first order for stakeholders. Every multi-view group uses a dropdown menu
# (the user picks an analysis from the menu — nothing is shown until chosen).
# ── Six clear, decision-framed sections (the questions a manager/scientist asks) ──
GROUPS = [
    {"key": "home",    "label": "Overview",            "icon": "bi-house-door",
     "question": "Start here",
     "views": ["home"],
     "desc": "Start here — the three questions this tool answers, then open any analysis."},
    {"key": "water",   "label": "Water Supply & Snow", "icon": "bi-droplet", "nav": "tabs",
     "question": "How much water is there?",
     "views": ["snowpack", "elevsnow", "timing", "watbal", "budyko", "links", "october"],
     "desc": "Where the water comes from — snowpack-to-runoff, the water balance, snowmelt "
             "timing, soil-moisture controls, and the Budyko water–energy partition."},
    {"key": "risk",    "label": "Drought & Risk",      "icon": "bi-exclamation-triangle", "nav": "tabs",
     "question": "How severe is the stress?",
     "views": ["drought", "reservoirs", "cascade", "recovery", "tws", "storage",
               "warming", "aridification", "asi"],
     "desc": "Supply security and stress — drought & shortage risk, reservoir tiers, terrestrial "
             "& groundwater storage, recovery, drought propagation, and long-term aridification."},
    {"key": "future",  "label": "Scenarios & Future",  "icon": "bi-sliders", "nav": "tabs",
     "question": "What happens under change?",
     "views": ["scenario", "uncertainty", "nmme", "future", "cmip", "noanalog"],
     "desc": "The decision centerpiece — dial a warming / precipitation change and see the projected "
             "streamflow response (with confidence), plus projections, climate scenarios and forecasts."},
    {"key": "spatial", "label": "Basin Maps",          "icon": "bi-map", "nav": "tabs",
     "question": "Where across the basin?",
     "views": ["basinwide", "spatial", "spatcompare", "animations"],
     "desc": "Interactive side-by-side maps of every VIC variable, SNOTEL stations, watersheds "
             "and rivers across the basin — plus animated seasonal and 40-year drought cycles."},
    {"key": "about",   "label": "Governance & About",  "icon": "bi-bank2", "nav": "tabs",
     "question": "How it works & where it comes from",
     "views": ["governance", "cria", "methods", "publications", "references"],
     "desc": "How it works and where it comes from — water governance (Law of the River), the "
             "infrastructure-asset framework, methods & data sources, publications, and validation."},
]
VIEW_TO_GROUP = {v: g for g in GROUPS for v in g["views"]}


# ── Sidebar (7 groups only) ──────────────────────────────────
def make_sidebar():
    items = []
    for g in GROUPS:
        first_route = "/" + g["views"][0]
        routes = ",".join("/" + v for v in g["views"])
        items.append(
            html.A(
                [html.I(className=f"bi {g['icon']}",
                        style={"fontSize": "16px", "marginRight": "10px", "width": "18px",
                               "display": "inline-block"}),
                 g["label"]],
                id=f"nav-{g['key']}",
                href=first_route,
                className="nav-link",
                **{"data-routes": routes},
            )
        )

    return html.Div([
        # Title (logo removed — it already appears in the right-hand header strip)
        html.Div([
            html.Div([
                html.Img(src="/assets/img/cria-wordmark.svg?v=3",
                         className="sidebar-logo-img", alt="CRIA"),
                html.Div("Decision Support Tool", className="sidebar-logo-sub"),
            ], style={"width": "100%"})
        ], className="sidebar-logo"),

        # Nav
        html.Nav(items, style={"padding": "12px 0"}, **{"aria-label": "Main navigation"}),

        # Display size — 3 scales
        html.Div([
            html.Div("Display size", className="zoom-title"),
            html.Div([
                html.Button("A", id="zoom-1", className="zoom-btn", n_clicks=0,
                            title="Standard", **{"aria-label": "Standard text size"}),
                html.Button("A", id="zoom-2", className="zoom-btn zoom-2", n_clicks=0,
                            title="Large — easier reading",
                            **{"aria-label": "Large text size"}),
                html.Button("A", id="zoom-3", className="zoom-btn zoom-3", n_clicks=0,
                            title="Presentation — for screens and demos",
                            **{"aria-label": "Extra-large text size for presentations"}),
            ], className="zoom-row"),
        ], className="zoom-box"),

        # Quick links — a stable sidebar container (same items as the mobile "+" menu)
        html.Div([
            html.Div("Quick links", className="zoom-title"),
            html.Button([html.I(className="bi bi-chat-dots"), html.Span("Ask RIA")],
                        id="ria-fab-sb", n_clicks=0, className="ql-link ql-maroon"),
            html.A([html.I(className="bi bi-map"), html.Span("Blueprint")],
                   href="/assets/CRIA_Blueprint.html", target="_blank", className="ql-link ql-navy"),
            html.A([html.I(className="bi bi-people-fill"), html.Span("Meet the team")],
                   href="/team", className="ql-link ql-maroon"),
            html.A([html.I(className="bi bi-stars"), html.Span("Why CRIA")],
                   href="/why", className="ql-link ql-navy"),
            html.A([html.I(className="bi bi-diagram-3"), html.Span("How it's built")],
                   href="/workflow", className="ql-link ql-maroon"),
            html.A([html.I(className="bi bi-chat-quote-fill"), html.Span("Add your voice")],
                   href="/reviews", className="ql-link ql-navy"),
        ], className="ql-box"),

        # Live visitor count — shown to the admin only (?admin=KEY); still counts all visits
        html.Div([
            html.Span(id="visit-count"),
            dcc.Store(id="fb-visit-guard", storage_type="session"),
            dcc.Store(id="tz-store", storage_type="session"),
        ], className="visits-box"),

    ], className="sidebar", id="sidebar")


# ── Page layout wrapper ──────────────────────────────────────
def page_layout(title, subtitle, icon, color_class, tiles, content):
    return html.Div([
        # Header
        html.Div([
            html.H2(f"{icon}  {title}"),
            html.P(subtitle),
        ], className="tab-header"),

        # Body
        html.Div([
            # Info tiles row
            dbc.Row([
                dbc.Col(t, xs=6, md=3) for t in tiles
            ], className="mb-3 g-2") if tiles else html.Div(),

            # Main content
            content,
        ], className="tab-body"),
    ])


def info_tile(value, label, icon, color):
    return html.Div([
        html.Div(str(value), className="info-tile-value"),
        html.Div(label, className="info-tile-label"),
        html.Div(icon, className="info-tile-icon"),
    ], className=f"info-tile {color}")


# ── Import page modules (populated in later phases) ─────────
from utils.insights import insights_panel
from utils import metrics
from utils import tzcc
from modules.home     import layout as home_layout
from modules.home     import reviews_layout
from modules.snowpack import layout as snowpack_layout
from modules.watbal   import layout as watbal_layout
from modules.tws      import layout as tws_layout
from modules.drought  import layout as drought_layout
from modules.future   import layout as future_layout
from modules.spatial  import layout as spatial_layout
from modules.spatial_compare import layout as spatcompare_layout
from modules.aridification import layout as aridification_layout
from modules.asi          import layout as asi_layout
from modules.storage      import layout as storage_layout
from modules.budyko       import layout as budyko_layout
from modules.cascade      import layout as cascade_layout
from modules.recovery     import layout as recovery_layout
from modules.noanalog     import layout as noanalog_layout
from modules.timing       import layout as timing_layout
from modules.links        import layout as links_layout
from modules.nmme         import layout as nmme_layout
from modules.cmip         import layout as cmip_layout
from modules.scenario     import layout as scenario_layout
from modules.governance   import layout as governance_layout
from modules.reservoirs   import layout as reservoirs_layout
from modules.cria         import layout as cria_layout
from modules.uncertainty  import layout as uncertainty_layout
from modules.methods      import layout as methods_layout
from modules.october     import layout as october_layout
from modules.publications import layout as publications_layout
from modules.team         import layout as team_layout
from modules.elevsnow     import layout as elevsnow_layout
from modules.warming      import layout as warming_layout
from modules.references   import layout as references_layout
from modules.animations   import layout as animations_layout
from modules.basinwide    import layout as basinwide_layout
from modules.workflow     import layout as workflow_layout
from modules.why          import layout as why_layout

# ── Register callbacks ───────────────────────────────────────
from modules.home         import register_callbacks as home_cb
from modules.snowpack     import register_callbacks as snowpack_cb
from modules.watbal       import register_callbacks as watbal_cb
from modules.tws          import register_callbacks as tws_cb
from modules.drought      import register_callbacks as drought_cb
from modules.future       import register_callbacks as future_cb
from modules.spatial      import register_callbacks as spatial_cb
from modules.spatial_compare import register_callbacks as spatcompare_cb
from modules.aridification import register_callbacks as aridification_cb
from modules.asi          import register_callbacks as asi_cb
from modules.storage      import register_callbacks as storage_cb
from modules.budyko       import register_callbacks as budyko_cb
from modules.cascade      import register_callbacks as cascade_cb
from modules.recovery     import register_callbacks as recovery_cb
from modules.noanalog     import register_callbacks as noanalog_cb
from modules.timing       import register_callbacks as timing_cb
from modules.links        import register_callbacks as links_cb
from modules.october      import register_callbacks as october_cb
from modules.nmme         import register_callbacks as nmme_cb
from modules.cmip         import register_callbacks as cmip_cb
from modules.scenario     import register_callbacks as scenario_cb
from modules.governance   import register_callbacks as governance_cb
from modules.reservoirs   import register_callbacks as reservoirs_cb
from modules.cria         import register_callbacks as cria_cb
from modules.uncertainty  import register_callbacks as uncertainty_cb
from modules.publications import register_callbacks as publications_cb
from modules.elevsnow     import register_callbacks as elevsnow_cb
from modules.warming      import register_callbacks as warming_cb
from modules.references   import register_callbacks as references_cb
from modules.animations   import register_callbacks as animations_cb
from modules.basinwide    import register_callbacks as basinwide_cb
from modules.workflow     import register_callbacks as workflow_cb

for cb in [home_cb, snowpack_cb, watbal_cb, tws_cb, drought_cb, future_cb, spatial_cb, spatcompare_cb,
           aridification_cb, asi_cb, storage_cb, budyko_cb, cascade_cb, recovery_cb,
           noanalog_cb, timing_cb, links_cb, october_cb, nmme_cb, cmip_cb, scenario_cb,
           governance_cb, reservoirs_cb, cria_cb, uncertainty_cb,
           publications_cb, elevsnow_cb, warming_cb, references_cb,
           animations_cb, basinwide_cb, workflow_cb]:
    cb(app)

# ── Main layout ──────────────────────────────────────────────
app.layout = html.Div([
    dcc.Location(id="url", refresh=False),

    # Accessibility: keyboard users can skip the sidebar/header straight to the content.
    html.A("Skip to main content", href="#page-content", className="skip-link"),

    # Mobile hamburger button
    html.Button("", id="sidebar-toggle", className="sidebar-toggle",
                n_clicks=0),

    make_sidebar(),

    # ── Main content wrapper ─────────────────────────────────
    html.Div([
        # Global header band — LOGOS ONLY (same on every page)
        html.Div([
            html.Img(src="/assets/img/nasa-logo.webp", className="header-logo", title="NASA Applied Sciences"),
            html.Img(src="/assets/img/asu.jpeg",       className="header-logo", title="Arizona State University"),
            html.Img(src="/assets/img/cap.jpeg",       className="header-logo", title="Central Arizona Project"),
        ], className="app-header"),

        # Global title container — fixed title + subtitle (same on every page)
        html.Div([
            html.H1("CRIA — Colorado River Integrated Assessment", className="app-title"),
            html.P("Decision-support tool for the Colorado River Basin",
                   className="app-subtitle"),
            html.P("Historical hydroclimatic analysis, WY1984–2024 · VIC 5.0 PRISM-calibrated "
                   "(U. Washington, NASA-funded) · SNOTEL · GRACE · SMAP · "
                   "For the Bureau of Reclamation, ADWR, CAWCD & Basin Stakeholders",
                   className="app-subtitle",
                   style={"fontSize": "12px", "opacity": "0.85", "marginTop": "2px"}),
            html.P([html.B("Research team: "),
                    "E. Vivoni (PI), G. Mascaro (Co-I), D. White (Co-I), V. Kartha (CAP Co-PI), "
                    "K. Whitney, Z. Wang, S. Ghimire, H. Yue, X. Chen, N. Kandalaft, M. Xiao"],
                   className="app-subtitle",
                   style={"fontSize": "13px", "opacity": "0.9", "lineHeight": "1.55"}),
            html.P([html.B("Program Manager: "), "V. Hobbins · ",
                    html.B("Tool developed by: "), "Pradeepika (Praddy) Kaushik"],
                   className="app-subtitle",
                   style={"fontSize": "13px", "opacity": "0.95", "marginTop": "2px",
                          "fontWeight": "600"}),
        ], className="app-titlebar"),

        html.Div(id="page-content", tabIndex=-1, **{"role": "main"}),
        html.Div(id="zoom-sink", style={"display": "none"}),
        html.Div(id="scroll-sink", style={"display": "none"}),
    ], className="main-content"),

    # ── Floating action pills (collapse into one dot on small screens) ──
    html.Button(html.I(className="bi bi-plus-lg"), id="fab-toggle",
                className="fab-toggle", n_clicks=0,
                title="Quick links — Blueprint, Ask RIA, team, and more",
                **{"aria-label": "Quick links menu"}),
    html.Div([
        html.A([html.I(className="bi bi-map"), html.Span("Blueprint")],
               href="/assets/CRIA_Blueprint.html", target="_blank",
               className="bp-fab",
               title="Open the full CRIA blueprint, feature map & reference",
               **{"aria-label": "Blueprint document"}),
        html.A([html.I(className="bi bi-people-fill"), html.Span("Meet the team")],
               href="/team", className="team-fab",
               title="The researchers and partner agencies behind CRIA",
               **{"aria-label": "Research team"}),
        html.Button([html.I(className="bi bi-stars"), html.Span("Why CRIA")],
                    id="why-fab", className="why-fab", n_clicks=0,
                    title="Why CRIA — who it's for, the gap it fills, and what makes it new",
                    **{"aria-label": "Why CRIA"}),
        html.Button([html.I(className="bi bi-diagram-2"), html.Span("How it's built")],
                    id="wf-fab", className="wf-fab", n_clicks=0,
                    title="How this tool is built",
                    **{"aria-label": "How this tool is built"}),
        html.Button([html.I(className="bi bi-chat-dots-fill"),
                     html.Span("Ask RIA", className="ria-fab-label")],
                    id="ria-fab", className="ria-fab", n_clicks=0,
                    title="Ask RIA — ask me anything about CRIA",
                    **{"aria-label": "Ask RIA — ask me anything"}),
        html.A([html.I(className="bi bi-chat-quote-fill"), html.Span("Add your voice")],
               href="/reviews", className="reviews-fab",
               title="What people are saying — read and leave a review",
               **{"aria-label": "Reviews"}),
    ], id="fab-stack", className="fab-stack"),
    html.Div(
        html.Div([
            html.Div([
                html.A(html.I(className="bi bi-box-arrow-up-right"),
                       href="/assets/ria_assistant.html?v=22", target="_blank",
                       className="ria-ctl", title="Open in a new page",
                       **{"aria-label": "Open RIA in a new page"}),
                html.Button(html.I(className="bi bi-arrows-angle-expand"), id="ria-expand",
                            className="ria-ctl", n_clicks=0, title="Expand / shrink",
                            **{"aria-label": "Expand or shrink the RIA window"}),
                html.Button(html.I(className="bi bi-dash-lg"), id="ria-min",
                            className="ria-ctl", n_clicks=0, title="Minimise",
                            **{"aria-label": "Minimise RIA"}),
                html.Button(html.I(className="bi bi-x-lg"), id="ria-modal-close",
                            className="ria-ctl", n_clicks=0, title="Close",
                            **{"aria-label": "Close RIA"}),
            ], className="ria-ctls"),
            html.Iframe(src="/assets/ria_assistant.html?v=22", className="ria-frame",
                        title="RIA assistant chat"),
        ], className="ria-card"),
        id="ria-modal", className="ria-modal",
        **{"role": "dialog", "aria-modal": "true", "aria-label": "RIA assistant"},
    ),
    html.Div([
        html.Span("CRIA — Colorado River Integrated Assessment",
                  className="crb-footer-left"),
        html.Span(["Full data sources & citations: ",
                   html.A("References & Validation", href="/references",
                          style={"color":"#01579B","fontWeight":"600","textDecoration":"underline"})],
                  className="crb-footer-center"),
        html.Span("© 2026 ASU | NASA Applied Sciences",
                  className="crb-footer-right"),
    ], className="crb-footer"),

])

# Mobile sidebar toggle: hamburger opens/closes; navigating closes it
app.clientside_callback(
    """function(n, path){
        var sb = document.getElementById('sidebar');
        var open = sb && sb.classList.contains('open');
        var ctx = dash_clientside.callback_context;
        if (ctx.triggered && ctx.triggered.length){
            var src = ctx.triggered[0].prop_id;
            if (src.indexOf('sidebar-toggle') !== -1) { open = !open; }
            else { open = false; }   // navigation closes the drawer
        }
        return open ? 'sidebar open' : 'sidebar';
    }""",
    Output("sidebar", "className"),
    Input("sidebar-toggle", "n_clicks"),
    Input("url", "pathname"),
    prevent_initial_call=False,
)

# Read the visitor's IANA timezone once (client-side; no IP or location request) so the
# server can derive an approximate country from it. Set only once per session.
app.clientside_callback(
    """function(p){
        try{
            if (window.__criaTz) return window.dash_clientside.no_update;
            var tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'unknown';
            window.__criaTz = tz;
            return tz;
        }catch(e){ return 'unknown'; }
    }""",
    Output("tz-store", "data"),
    Input("url", "pathname"),
    prevent_initial_call=False,
)

# Scroll to top whenever the route changes (so a newly opened analysis starts at the top)
app.clientside_callback(
    """function(p){ try{ window.scrollTo({top:0, left:0, behavior:'auto'});
        var mc=document.querySelector('.main-content'); if(mc) mc.scrollTop=0; }catch(e){}
        return ''; }""",
    Output("scroll-sink", "children"),
    Input("url", "pathname"),
    prevent_initial_call=True,
)

# Display size: three scales applied to the whole app (remembered in the session)
app.clientside_callback(
    """function(a, b, c){
        var ctx = dash_clientside.callback_context;
        var lvl = 1;
        if (ctx.triggered && ctx.triggered.length){
            var s = ctx.triggered[0].prop_id;
            if (s.indexOf('zoom-2') !== -1) lvl = 2;
            else if (s.indexOf('zoom-3') !== -1) lvl = 3;
        }
        var b0 = document.body;
        b0.classList.remove('zoom-lv2','zoom-lv3');
        if (lvl === 2) b0.classList.add('zoom-lv2');
        if (lvl === 3) b0.classList.add('zoom-lv3');
        ['zoom-1','zoom-2','zoom-3'].forEach(function(id, i){
            var el = document.getElementById(id);
            if (el) el.classList.toggle('active', (i + 1) === lvl);
        });
        return '';
    }""",
    Output("zoom-sink", "children"),
    Input("zoom-1", "n_clicks"),
    Input("zoom-2", "n_clicks"),
    Input("zoom-3", "n_clicks"),
    prevent_initial_call=True,
)

# RIA assistant floating launcher: the bubble TOGGLES the panel (click to open,
# click again to close); the × button and route changes always close it.
app.clientside_callback(
    """function(openN, closeN, path, cur){
        var ctx = dash_clientside.callback_context;
        if (!ctx.triggered || !ctx.triggered.length) return 'ria-modal';
        var src = ctx.triggered[0].prop_id;
        var open = cur && cur.indexOf('open') !== -1;
        var big  = cur && cur.indexOf('big') !== -1;
        var mini = cur && cur.indexOf('mini') !== -1;
        if (src.indexOf('ria-fab') !== -1){
            return open ? 'ria-modal' : 'ria-modal open';
        }
        if (src.indexOf('ria-expand') !== -1){
            return 'ria-modal open' + (big ? '' : ' big');
        }
        if (src.indexOf('ria-min') !== -1){
            return 'ria-modal open' + (big ? ' big' : '') + (mini ? '' : ' mini');
        }
        return 'ria-modal';
    }""",
    Output("ria-modal", "className"),
    Input("ria-fab", "n_clicks"),
    Input("ria-fab-sb", "n_clicks"),
    Input("ria-modal-close", "n_clicks"),
    Input("url", "pathname"),
    Input("ria-expand", "n_clicks"),
    Input("ria-min", "n_clicks"),
    State("ria-modal", "className"),
    prevent_initial_call=True,
)

# "Why CRIA" and "How it's built" pills TOGGLE their page: click opens the page,
# click again (while already on it) returns to the Overview.
app.clientside_callback(
    """function(whyN, wfN, path){
        var ctx = dash_clientside.callback_context;
        if (!ctx.triggered || !ctx.triggered.length) return dash_clientside.no_update;
        var src = ctx.triggered[0].prop_id;
        if (src.indexOf('why-fab') !== -1) return (path === '/why') ? '/home' : '/why';
        if (src.indexOf('wf-fab')  !== -1) return (path === '/workflow') ? '/home' : '/workflow';
        return dash_clientside.no_update;
    }""",
    Output("url", "pathname", allow_duplicate=True),
    Input("why-fab", "n_clicks"),
    Input("wf-fab", "n_clicks"),
    State("url", "pathname"),
    prevent_initial_call=True,
)

# ── URL routing ──────────────────────────────────────────────
# Every view keeps its own route (so deep-links + in-app links work),
# but views are rendered inside their parent group with a sub-tab bar.
VIEW_LAYOUTS = {
    "home": home_layout, "snowpack": snowpack_layout, "watbal": watbal_layout,
    "timing": timing_layout, "links": links_layout, "october": october_layout,
    "tws": tws_layout,
    "storage": storage_layout, "drought": drought_layout, "cascade": cascade_layout,
    "recovery": recovery_layout, "aridification": aridification_layout, "asi": asi_layout,
    "budyko": budyko_layout, "future": future_layout, "noanalog": noanalog_layout,
    "nmme": nmme_layout, "cmip": cmip_layout, "scenario": scenario_layout,
    "cria": cria_layout, "governance": governance_layout, "reservoirs": reservoirs_layout,
    "uncertainty": uncertainty_layout, "spatial": spatial_layout,
    "spatcompare": spatcompare_layout,
    "methods": methods_layout, "publications": publications_layout, "team": team_layout,
    "elevsnow": elevsnow_layout, "warming": warming_layout,
    "references": references_layout,
    "animations": animations_layout,
    "basinwide": basinwide_layout,
    "workflow": workflow_layout,
    "why": why_layout,
    "reviews": reviews_layout,
}
PAGE_MAP = {f"/{k}": v for k, v in VIEW_LAYOUTS.items()}
PAGE_MAP["/"] = home_layout


def _subtab_bar(group, active_view):
    """Section intro + a view switcher. Style per group:
       nav='tabs'  → horizontal sub-tabs (like Kristen's tool)
       default     → dropdown (decision-support style)."""
    q = group.get("question")
    intro = html.Div([
        html.Div([
            html.I(className=f"bi {group['icon']}",
                   style={"color": "#8C1D40", "marginRight": "8px", "fontSize": "15px"}),
            html.Span(q or group["label"], style={"fontWeight": "800", "color": "#8C1D40",
                                                  "fontSize": "14px", "marginRight": "10px"}),
            html.Span(group["label"], style={"fontWeight": "700", "color": "#0D2137",
                                             "fontSize": "11.5px"}) if q else None,
        ], style={"display": "flex", "alignItems": "center", "flexWrap": "wrap"}),
        html.Span(group.get("desc", ""), className="subtab-desc",
                  style={"color": "#64748b", "fontSize": "11.5px"}),
    ], className="subtab-intro")

    if group.get("nav") == "tabs":
        tabs = []
        for v in group["views"]:
            label, icon = VIEW_LABELS.get(v, (v, ""))
            cls = "subtab-tab active" if v == active_view else "subtab-tab"
            tabs.append(html.A(
                [html.I(className=f"bi {icon}", style={"marginRight": "7px", "fontSize": "13px"}), label],
                href=f"/{v}", className=cls))
        switcher = html.Div(tabs, className="subtab-tabs")
    else:
        options = [{"label": VIEW_LABELS.get(v, (v, ""))[0], "value": v} for v in group["views"]]
        switcher = html.Div([
            html.Span("Select analysis", className="subnav-label"),
            dcc.Dropdown(id="subnav-dropdown", options=options, value=active_view,
                         clearable=False, searchable=False, className="subnav-dropdown"),
        ], className="subnav-row")

    return html.Div([intro, switcher], className="subtab-bar")


# Dropdown view selector → navigate (decision-support style)
@app.callback(
    Output("url", "pathname"),
    Input("subnav-dropdown", "value"),
    State("url", "pathname"),
    prevent_initial_call=True,
)
def _nav_from_dropdown(view, current):
    if not view:
        raise PreventUpdate
    target = f"/{view}"
    if target == current:          # avoids loop when dropdown is rebuilt on navigation
        raise PreventUpdate
    return target


@app.callback(Output("page-content", "children"), Input("url", "pathname"))
def render_page(pathname):
    if not pathname or pathname == "/":
        pathname = "/home"
    view = pathname.strip("/")
    group = VIEW_TO_GROUP.get(view)
    if group is None:
        # A valid analysis that isn't in the main sidebar nav (reachable from the Overview
        # launcher) renders standalone; a truly unknown route falls back to home.
        if view in VIEW_LAYOUTS:
            return html.Div([VIEW_LAYOUTS[view](), insights_panel(view)])
        view, group = "home", VIEW_TO_GROUP["home"]
    layout_fn = VIEW_LAYOUTS.get(view, home_layout)
    # Single-view groups need no sub-tab bar
    if len(group["views"]) <= 1:
        return html.Div([layout_fn(), insights_panel(view)])
    return html.Div([_subtab_bar(group, view), layout_fn(), insights_panel(view)])


# Highlight active group in sidebar (by matching pathname to the group's routes)
app.clientside_callback(
    """function(pathname) {
        setTimeout(function() {
            var path = (pathname === '/' || !pathname) ? '/home' : pathname;
            document.querySelectorAll('.nav-link').forEach(function(el) {
                var routes = (el.getAttribute('data-routes') || '').split(',');
                el.classList.toggle('active', routes.indexOf(path) !== -1);
            });
        }, 50);
        return window.dash_clientside.no_update;
    }
    """,
    Output("url", "search"),
    Input("url", "pathname"),
    prevent_initial_call=False,
)


# ── Optional RIA "AI mode" — server-side LLM call ────────────
# Enabled only when an API key is provided as a Space secret (env var LLM_API_KEY).
# No key in the repository; if unset, this returns null and RIA uses its curated answers.
@app.server.route("/ai_ask", methods=["POST", "GET"])
def ai_ask():
    import os, json, urllib.request
    from flask import request, jsonify
    key = os.environ.get("LLM_API_KEY")
    if not key:
        return jsonify({"answer": None})
    if request.method == "GET":
        q = (request.args.get("q") or "")[:600]
    else:
        q = ((request.get_json(silent=True) or {}).get("q") or "")[:600]
    if not q.strip():
        return jsonify({"answer": None})
    url = os.environ.get("LLM_API_URL", "https://api.groq.com/openai/v1/chat/completions")
    model = os.environ.get("LLM_MODEL", "openai/gpt-oss-20b")
    knowledge = (
        "FACTS ABOUT CRIA (use these; do not invent others):\n"
        "- CRIA = Colorado River Integrated Assessment: an interactive decision-support tool for the "
        "Colorado River Basin. It is the applied face of the NASA Applied Sciences project 'Managing the "
        "Colorado River as an Infrastructure Asset', Award 80NSSC22K0925, PI Enrique R. Vivoni, Arizona "
        "State University, with the Central Arizona Project.\n"
        "- Built by Pradeepika Kaushik (Praddy), a geospatial and data-visualization scientist at ASU.\n"
        "- Data sources: VIC 5.0 PRISM-calibrated hydrologic reanalysis (Nash-Sutcliffe 0.96 for Upper "
        "Basin streamflow, water years 1984-2024); NASA GRACE/GRACE-FO terrestrial water storage; NASA "
        "SMAP L4 soil moisture (~9 km); SNOTEL 103 snow-telemetry stations; USBR policy (Lake Mead "
        "shortage-tier thresholds, reservoir capacities, CAP delivery cuts from the 2007 Interim "
        "Guidelines and 2019 Drought Contingency Plan).\n"
        "- Pipeline: preprocessing scripts aggregate, quality-check and grid raw NetCDF (~58 GB) into a "
        "compact Parquet cache (~300 MB; 11 basin tables + 19 spatial-grid tables). A data loader reads "
        "the cache once into memory. The app computes statistics, renders maps and animations with "
        "matplotlib and interactive charts with Plotly, and serves 6 sections and 29 analysis views via "
        "Plotly Dash (Flask + Bootstrap). Python end to end (pandas, numpy, scipy, statsmodels, "
        "pymannkendall). Containerized with Docker, served by gunicorn on Hugging Face Spaces; data in "
        "Git LFS.\n"
        "- Sections: Overview; Water Supply and Snow; Drought and Risk; Scenarios and Future; Basin "
        "Maps; Governance and About.\n"
        "- Scenario engine: dial a temperature change and a precipitation change to see projected runoff "
        "via hydrologic elasticity (OLS of log-streamflow on log-precipitation and temperature), giving "
        "percent change per degree C and per percent precipitation with a 95% confidence interval, "
        "converted to acre-feet and read against Lake Mead tiers. Roughly -8% streamflow per degree C of "
        "warming.\n"
        "- Uncertainty is shown: 95% CIs on scenarios and major trends, Mann-Kendall significance, and a "
        "dedicated Uncertainty tab with bootstrap CIs and cross-sensor validation.\n"
        "- Validation: VIC vs NASA SMAP (soil-moisture R-squared 0.71 surface, 0.81 root zone) and vs "
        "GRACE (storage R-squared 0.66-0.86), published in Scientific Reports; headline results "
        "cross-checked against 12+ peer-reviewed studies; an automated 26-test suite checks data "
        "integrity, water-balance closure, and statsmodels recomputation.\n"
        "- An acre-foot is about 326,000 gallons (one acre, one foot deep), roughly a year for 2-3 "
        "households. MAF = million acre-feet; KAF = thousand acre-feet.\n"
        "- Motivation: the 1922 Compact allocated the river using an unusually wet early-1900s record, so "
        "the basin is now over-allocated; managers need supply, risk and climate-sensitivity together in "
        "acre-feet and Lake Mead tiers.\n"
        "- Stakeholders: co-developed with the Central Arizona Project, U.S. Bureau of Reclamation, the "
        "Basin States, Tribes and Colorado River Basin agencies, with Hydrology Working Group "
        "engagement.\n"
        "- Public recognitions: 2023 Governor's Award for Arizona's Future (Arizona Forward "
        "Environmental Excellence Awards); 2023 Paul F. Boulos Excellence in Computational Hydraulics and "
        "Hydrology Award; 2023 Arizona Hydrological Society academic award; Babbitt Center dissertation "
        "fellowships; a NASA Postdoctoral Fellowship at Goddard.\n"
        "- Limitations: it is a historical reanalysis, not a forecast; the scenario engine is a "
        "statistical elasticity, not a full climate model; some datasets are coarse; it states 'no data "
        "available' where evidence is missing.\n"
        "- PROJECT DETAILS: Full title 'Managing the Colorado River as an Infrastructure Asset: Fusing "
        "Remote Sensing and Numerical Modeling in the Operations of the Central Arizona Project.' NASA "
        "Applied Sciences - Water Resources Program, Award 80NSSC22K0925. A 36-month project led by "
        "Arizona State University (ASU) in coordination with the Central Arizona Project (CAP), started "
        "in summer 2022.\n"
        "- Principal Investigator: Enrique R. Vivoni, Fulton Professor of Hydrosystems Engineering in "
        "ASU's School of Sustainable Engineering and the Built Environment and Director of ASU's Center "
        "for Hydrologic Innovations (chi.asu.edu) — the lab this tool sits within. PhD in hydrology from "
        "MIT (2003), licensed professional engineer, Fellow of the American Meteorological Society; his "
        "work spans watershed modeling, eco-hydrology of semiarid regions and stakeholder-driven "
        "decision support, with long collaborations supporting CAP, the Salt River Project and Arizona "
        "agencies. He leads the overall project, the hydrologic modeling and stakeholder outreach.\n"
        "- Co-Investigators: Giuseppe Mascaro (Associate Professor, ASU SSEBE; leads the Hydroclimate & "
        "Infrastructure Research Lab; PhD in hydrology, University of Cagliari 2008; stochastic hydrology, "
        "watershed modeling, hydroclimatology, climate change; contributes forecasting, statistics and "
        "climate downscaling) and Dave D. White (Professor, ASU School of Community Resources and "
        "Development; Director of ASU's Global Institute of Sustainability and Innovation; former lead of "
        "the NSF Decision Center for a Desert City and lead of the Arizona Water Innovation "
        "Initiative; water governance and sustainability). CAP co-lead: Vineetha Kartha, CAP's Colorado "
        "River Programs Manager (nearly two decades in water management; MS Urban and Environmental "
        "Planning, ASU, and MS Geology, University of Bombay; former manager of the Colorado River "
        "section at the Arizona Department of Water Resources); earlier CAP collaborators Charlie Cullom "
        "and N. P. Templeton.\n"
        "- Postdoctoral scholars: Dr. Zhaocheng Wang (ASU), the lead hydrologic modeler (VIC calibration, "
        "precipitation-partition and snow-rainfall work); Dr. Pradeepika 'Praddy' Kaushik (ASU), the "
        "geospatial and data-visualization scientist who built this CRIA interactive decision-support "
        "tool; and Dr. Haowen Yue (ASU), seasonal streamflow forecasting with NMME. Kristen M. Whitney "
        "was a project researcher and NASA Postdoctoral Fellow and is now an Associate Research Scientist "
        "at NASA Goddard Space Flight Center (streamflow attribution and stakeholder engagement).\n"
        "- Graduate students: Swastik Ghimire (MS; drought propagation), Xinyu Chen (PhD; CMIP5/CMIP6 "
        "hydroclimate) and Nour Kandalaft (MS), with Mu Xiao contributing satellite remote sensing and "
        "model-calibration work.\n"
        "- Program management: Vivian Hobbins, a Senior Program Manager in ASU's School of "
        "Sustainable Engineering and the Built Environment (PhD in Ecohydrology), supports program "
        "management for the research group.\n"
        "- Partner organizations: Arizona State University (lead), the Central Arizona Project (CAP), the "
        "Colorado River Climate and Hydrology Working Group, the U.S. Bureau of Reclamation (including "
        "San Juan River Basin Operations), and NASA Goddard Space Flight Center.\n"
        "- The four objectives: (1) collect Earth-observation and in-situ datasets plus NMME seasonal "
        "climate forecasts using in-house scripts; (2) run short- and long-range VIC simulations with "
        "those forecasts and climate projections; (3) analyze the sociopolitical and governance context "
        "(a Colorado River governance analysis spanning 1922-2022) and build the infrastructure-asset "
        "framework; (4) engage stakeholders through co-development. Objective 1 is complete; 2 to 4 are "
        "substantially advanced.\n"
        "- Selected method results: VIC surface soil moisture matched NASA SMAP with R-squared about 0.69 "
        "over 2015-2024; an NMME+VIC system issued 9-month Upper-Basin streamflow forecasts (52 ensemble "
        "members across five climate models) with skill comparable to or better than the U.S. Bureau of "
        "Reclamation 24-Month Study, especially in January; CMIP5 and CMIP6 projections were downscaled "
        "with the LOCA method and run through VIC at hourly, 6-km resolution over 1976-2099 to compare "
        "future (2066-2095) to historical (1976-2005) precipitation, runoff and soil moisture.\n"
        "- Evolution: an earlier prototype of the CRIA framework was a web app built in R and ShinyApps; "
        "the current tool is this Python/Dash interactive decision-support version built by Praddy "
        "Kaushik.\n"
        "- Project publications (peer-reviewed): Wang et al. 2021 (irrigation cooling capacity, JAWRA); "
        "Wang and Vivoni 2022 (urban growth and irrigation water use, JAWRA); Xiao et al. 2022 (value of "
        "satellite remote sensing to reduce uncertainty, Hydrology and Earth System Sciences); Whitney "
        "et al. 2023 (spatial attribution of declining Colorado River streamflow, Journal of Hydrology); "
        "Whitney et al. 2023 (stakeholder-engaged forest-disturbance impacts, J. Water Resources Planning "
        "and Management); Whitney et al. 2023 (accessibility of hydrologic projections for water "
        "managers, Environmental Modelling and Software); Wang et al. 2024 (sensitivity to the "
        "precipitation-partition method, Water Resources Research). In review or in preparation: Yue et "
        "al. (NMME forecast skill, J. Hydrometeorology); Wang et al. (revisiting VIC with Earth-"
        "observation datasets, Scientific Reports); Ghimire et al. (early-21st-century drought "
        "propagation, Water Resources Research); Chen et al. (CMIP5/CMIP6 hydroclimate, J. Hydrologic "
        "Engineering).\n"
        "- Key published results underpinning this tool: (1) Wang, Z., Ghimire, S., Whitney, K.M., "
        "Mascaro, G., Xiao, M., Yue, H. and Vivoni, E.R. (2026), 'Revisiting the Application of the "
        "Variable Infiltration Capacity (VIC) Model in the Colorado River Basin using SMAP and GRACE', "
        "Scientific Reports 16:15890, doi:10.1038/s41598-026-47430-9 - the validation paper (NSE 0.96 "
        "for Upper-Basin streamflow; SMAP R-squared 0.71 surface and 0.81 root zone). (2) Mascaro, G., "
        "Wang, Z., Vivoni, E.R. and Yue, H. (2025), 'Hydrometeorological Forecast Skill of the North "
        "American Multi-Model Ensemble (NMME) in the Upper Colorado River Basin', Journal of "
        "Hydrometeorology - the seasonal-forecast skill result. (3) Ghimire, S., Vivoni, E.R. and "
        "Wang, Z. (2026), 'Fall Soil Moisture Modulates Snow-Streamflow Dynamics in the Colorado River "
        "Basin', Water Resources Research 62(7), e2025WR042871, doi:10.1029/2025WR042871 - fall soil "
        "moisture explains 69-77% of Upper-Basin flow variability, which is the peer-reviewed basis for "
        "this tool's 'the decline is driven from below' finding. All three are published; describe them "
        "as published.\n"
        "- Approximate authorship on these project publications: Vivoni on all of them (project PI); "
        "Zhaocheng Wang about ten; Kristen Whitney about six; Giuseppe Mascaro about four; Dave White "
        "three; Mu Xiao three; Haowen Yue two; Swastik Ghimire two; Xinyu Chen two; Nour Kandalaft one. "
        "Praddy Kaushik's core contribution is the CRIA decision-support tool itself rather than these "
        "modeling papers.\n"
        "- Awards and recognitions: PI Vivoni elected AMS Fellow (2024); Kristen Whitney and Zhaocheng "
        "Wang received Babbitt Center for Land and Water Policy dissertation fellowships; Kristen Whitney "
        "received a NASA Postdoctoral Fellowship at Goddard; Zhaocheng Wang received a 2023 AZ Water "
        "Scholarship and the 2023 Paul F. Boulos Excellence in Computational Hydraulics and Hydrology "
        "Award; Swastik Ghimire received a 2023 Arizona Hydrological Society academic award; the project "
        "was selected for the 2023 Governor's Award for Arizona's Future (Arizona Forward Environmental "
        "Excellence Awards).\n"
        "- POSITIONING AND VALUE (use these when a user asks what the tool does, what makes it "
        "special or novel, who it is for, how it differs from other tools, or why it is helpful):\n"
        "- Primary user, and who benefits most: the Technical Water Manager at an operating agency "
        "(the Central Arizona Project / CAWCD, the U.S. Bureau of Reclamation, or the Arizona "
        "Department of Water Resources) - quantitatively fluent and accountable for supply and "
        "shortage decisions, but who does not run hydrologic models. They benefit most because the "
        "tool gives a basin-wide, observation-validated picture already in their own units "
        "(acre-feet, Lake Mead shortage tiers, live reservoir status) and answers CAP's stated "
        "soil-moisture science priority. Basin States and Tribes, students and researchers, and "
        "NASA partners are served by the same interface.\n"
        "- What makes it novel: it is not new science - it faithfully implements the lab's own "
        "validated results. The novelty is the class of tool: an observation-validated, whole-basin, "
        "decision-ready tool that (a) independently evaluates the VIC reanalysis against NASA "
        "GRACE, SMAP and SNOTEL and shows results beside published values; (b) integrates supply, "
        "snowpack, a drought-propagation cascade, storage, reservoir tiers, projections and spatial "
        "change in one consistent platform; (c) reports in operational units; and (d) reports its own limits by "
        "design - it states what does NOT hold up (for example, the elevation-snow gradient once "
        "latitude and record length are controlled) and shows 'no data available' rather than "
        "inventing numbers.\n"
        "- How it differs from the Whitney et al. (2023) CRB Scenario-Explorer: same lab lineage, so "
        "it is best described as a successor. Whitney's Scenario-Explorer (built in Shiny/R) made VIC "
        "streamflow projections under climate and forest-disturbance scenarios accessible, with "
        "strong stakeholder engagement and user-experience testing. This tool adds an independent "
        "observational-validation layer (GRACE/SMAP/SNOTEL), broadens from a single scenario theme to "
        "the full observed diagnostic chain, and carries through to operations (Mead tiers, CAP "
        "delivery cuts, live levels) rather than stopping at projections. Note: Whitney's "
        "formal stakeholder and UX-testing methodology is a benchmark this tool has not yet matched.\n"
        "- New capabilities versus previous tools: a GRACE-minus-VIC subsurface-storage reconstruction "
        "extended through 2024 (extends Castle et al. 2014); drought propagation shown as a lag "
        "cross-correlation cascade; runoff-efficiency and warming attribution via an elasticity fit "
        "benchmarked to Milly and Dunne 2020; Budyko migration toward the water-limited regime; "
        "previously-unused land-surface warming and energy signals; the 2023 'Great Recovery' as a "
        "multi-sensor natural experiment; explicit bootstrap uncertainty and significance; live "
        "reservoir shortage tiers; and an interactive, uncertainty-aware scenario engine in acre-feet.\n"
        "- Why it is helpful, by audience: for NASA, it turns GRACE and SMAP observations into "
        "decisions and validates against those same sensors - applied Earth science, end to end; for "
        "ASU and the Center for Hydrologic Innovations, it is rigorous and self-reporting, stating what does "
        "not hold up and citing every source, and brings the lab's work into one tool; for CAP "
        "and Reclamation, it speaks acre-feet, Lake Mead tiers, CAP delivery cuts and live levels, and "
        "answers CAP's soil-moisture science priority with no models to run. In one line: it brings "
        "into a single tool what usually sits in separate tools - NASA Earth observations, their "
        "independent validation, whole-basin integration, and the decision units managers actually "
        "use - documenting its uncertainty and limits."
    )
    system = (
        "You are RIA, the warm, knowledgeable built-in assistant for CRIA (Colorado River "
        "Integrated Assessment), a decision-support tool. A user may ask you ANYTHING - about the tool, the "
        "project and its team, hydrology and water management, NASA Earth observations, general or "
        "everyday questions, or just casual conversation. Always respond helpfully, warmly and clearly, "
        "usually in under 100 words. For anything about CRIA or the project, ground your answer in the "
        "FACTS below. For general-knowledge or casual questions, answer naturally and helpfully as a "
        "friendly assistant would; if you are uncertain of a fact, say so rather than inventing "
        "specifics. Never reveal confidential project details such as grant dollar amounts, budgets, "
        "salaries, personal contact information, credentials, or unpublished raw results; if asked for "
        "those, politely say that information is confidential and you cannot share it. Stay kind and "
        "professional at all times.\n\n" + knowledge
    )
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": q}],
        "max_tokens": 700, "temperature": 0.3, "reasoning_effort": "low",
    }).encode()
    try:
        import ssl
        try:
            import certifi
            _ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            _ctx = ssl.create_default_context()
        req = urllib.request.Request(url, data=body, headers={
            "Authorization": "Bearer " + key, "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; CRIA-RIA/1.0)"})
        with urllib.request.urlopen(req, timeout=20, context=_ctx) as r:
            d = json.loads(r.read())
        return jsonify({"answer": d["choices"][0]["message"]["content"].strip()})
    except Exception as e:
        try:
            import urllib.error
            if isinstance(e, urllib.error.HTTPError):
                app.server.logger.warning("ai_ask HTTP %s: %s", e.code, e.read().decode()[:300])
            else:
                app.server.logger.warning("ai_ask error: %r", e)
        except Exception:
            pass
        return jsonify({"answer": None})


# Diagnostic: confirm the key is loaded and the model works. Never exposes the key value.
@app.server.route("/ai_health")
def ai_health():
    import os, json, urllib.request, urllib.error
    from flask import jsonify
    key = os.environ.get("LLM_API_KEY")
    url = os.environ.get("LLM_API_URL", "https://api.groq.com/openai/v1/chat/completions")
    model = os.environ.get("LLM_MODEL", "openai/gpt-oss-20b")
    info = {"key_present": bool(key),
            "key_hint": ((key[:3] + "...len" + str(len(key))) if key else None),
            "model": model, "url": url}
    if not key:
        info["status"] = "NO_KEY"
        return jsonify(info)
    try:
        import ssl
        try:
            import certifi
            _ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            _ctx = ssl.create_default_context()
        body = json.dumps({"model": model,
                           "messages": [{"role": "user", "content": "In one short sentence, what is CRIA?"}],
                           "max_tokens": 400, "reasoning_effort": "low"}).encode()
        req = urllib.request.Request(url, data=body, headers={
            "Authorization": "Bearer " + key, "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; CRIA-RIA/1.0)"})
        with urllib.request.urlopen(req, timeout=20, context=_ctx) as r:
            d = json.loads(r.read())
        msg = d["choices"][0]["message"]
        info["status"] = "OK"
        info["content"] = (msg.get("content") or "")[:200]
        info["msg_keys"] = list(msg.keys())
        info["reasoning_present"] = bool(msg.get("reasoning"))
        info["finish_reason"] = d["choices"][0].get("finish_reason")
    except urllib.error.HTTPError as e:
        try:
            info["error"] = e.read().decode()[:300]
        except Exception:
            info["error"] = str(e)
        info["status"] = "HTTP_" + str(e.code)
    except Exception as e:
        info["status"] = "ERROR"
        info["error"] = repr(e)[:300]
    return jsonify(info)


def _is_admin(search):
    """True only when the URL carries ?admin=<the private key>. Users never see analytics."""
    try:
        import os
        import urllib.parse as _up
        key = _up.parse_qs((search or "").lstrip("?")).get("admin", [""])[0]
        admin_key = os.environ.get("CRIA_ADMIN_KEY")
        return bool(key) and bool(admin_key) and key == admin_key
    except Exception:
        return False


# ── Live visitor counter + approximate country from the browser timezone ─────
# The visitor's IANA timezone (e.g. "America/Phoenix") is read client-side and mapped
# to a country offline — no IP lookup and no third-party request, and unaffected by the
# hosting proxy, so the tally reflects the real visitor rather than the datacenter.
@app.callback(
    Output("visit-count", "children"),
    Output("fb-visit-guard", "data"),
    Input("tz-store", "data"),
    Input("url", "pathname"),
    State("url", "search"),
    State("fb-visit-guard", "data"),
    prevent_initial_call=False,
)
def _count_visit(tz, _path, search, guard):
    try:
        if not guard:
            # Count once per browser session — but only after the timezone has been
            # resolved by the client-side callback; if it hasn't arrived yet, wait.
            if not tz:
                raise PreventUpdate
            ua = ""
            try:
                from flask import request
                ua = (request.headers.get("User-Agent", "") or "").lower()
            except Exception:
                pass
            # Skip obvious bots / crawlers / uptime probes so the count AND the country
            # breakdown reflect real human visitors, not automated traffic.
            _BOTS = ("bot", "crawl", "spider", "slurp", "headless", "python-requests",
                     "curl/", "wget", "monitor", "uptime", "probe", "preview", "scan",
                     "facebookexternalhit", "go-http", "okhttp", "axios", "libwww",
                     "phantom", "lighthouse", "httpx", "http-client", "dataprovider")
            is_bot = (not ua) or any(b in ua for b in _BOTS)
            if is_bot:
                total = metrics.summary()["visits"]        # don't count automated traffic
            else:
                total = metrics.bump_visit()
                if tz and tz != "unknown":
                    cc = tzcc.country_from_tz(tz)
                    if cc:
                        metrics.bump_country(cc)
                    metrics.bump_tz(tz)     # keep the raw timezone tally too
            guard = True
        else:
            total = metrics.summary()["visits"]
        codes = metrics.get_country_counts()
    except PreventUpdate:
        raise
    except Exception:
        total, codes = 0, []
    # visits are always counted, but only the admin (?admin=KEY) ever sees the figure
    if not _is_admin(search):
        return "", True
    children = [html.I(className="bi bi-people-fill", style={"marginRight": "6px"}),
                f"{total:,} visits"]
    if codes:
        breakdown = " · ".join(f"{c} {n:,}" for c, n in codes)
        children.append(html.Span(" · " + breakdown,
                        style={"color": "#78909c", "fontWeight": "700", "marginLeft": "5px"}))
        # DB-IP IP-to-Country Lite is CC BY 4.0 — attribution is required where used.
        children.append(html.Span(" · geo: DB-IP",
                        style={"color": "#b0bec5", "fontWeight": "600", "marginLeft": "5px",
                               "fontSize": "10px"}))
    return children, True


# One-time migration: clear the old IP-based country tally (which counted the hosting
# proxy's location) so the new timezone-based tally starts clean. Runs once ever.
metrics.reset_geo_once()


if __name__ == "__main__":
    app.run(debug=False, dev_tools_ui=False, port=8050)
