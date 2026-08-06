# ============================================================
# CRB DST — modules/publications.py
# Publications Tab: All papers from NASA CRB project (Vivoni Lab, ASU)
# NASA Award 80NSSC22K0925
# ============================================================

from dash import html, dcc, Input, Output, callback
import dash_bootstrap_components as dbc

# ── Publication data ─────────────────────────────────────────
# Status: published | in_review | in_prep
PUBLICATIONS = [
    {
        "id": "ghimire2026",
        "year": 2026,
        "status": "published",
        "title": "Revisiting the Application of the Variable Infiltration Capacity (VIC) Model in the Colorado River Basin using SMAP and GRACE",
        "authors": "Wang, Z., Ghimire, S., Whitney, K.M., Mascaro, G., Xiao, M., Yue, H., Vivoni, E.R.",
        "journal": "Scientific Reports",
        "journal_short": "Sci. Rep.",
        "doi": "10.1038/s41598-026-47430-9",
        "volume": "16",
        "pages": "15890",
        "tags": ["VIC", "SMAP", "GRACE", "Calibration", "CRB"],
        "highlight": True,
        "tiles": [
            {"value": "NSE = 0.96", "label": "Streamflow (Upper Basin)", "icon": " ", "color": "tile-maroon"},
            {"value": "R² = 0.81",  "label": "SMAP root-zone soil moisture", "icon": " ", "color": "tile-navy"},
            {"value": "R² = 0.71",  "label": "SMAP surface soil moisture",  "icon": " ", "color": "tile-green"},
            {"value": "7 Basins",   "label": "Sub-basins Calibrated",  "icon": "", "color": "tile-gold"},
        ],
        "abstract": (
            "This study presents a multi-variable calibration of the VIC 5.0 hydrological model ""across seven CRB sub-basins by constraining streamflow against ground records and ""evaluating against NASA SMAP soil moisture and GRACE terrestrial water storage. The ""calibrated model achieves NSE=0.96 for Upper-Basin streamflow, with independent SMAP ""evaluation giving R²=0.71 (surface) and R²=0.81 (root-zone) soil moisture, plus GRACE ""terrestrial-water-storage evaluation — establishing a rigorously validated CRB hydrologic ""model that forms the scientific foundation of this tool."),
    },
    {
        "id": "whitney2023jwrpm",
        "year": 2023,
        "status": "published",
        "title": "A Stakeholder Engaged Approach to Anticipating Forest Disturbance Impacts in the Colorado River Basin under Climate Change",
        "authors": "Whitney, K.M., Vivoni, E.R., Wang, Z., White, D.D., Quay, R., Mahmoud, M.I., Templeton, N.P.",
        "journal": "Journal of Water Resources Planning and Management",
        "journal_short": "J. Water Resour. Plan. Manag.",
        "doi": "10.1061/JWRMD5.WRENG-5905",
        "volume": "149(7)",
        "pages": "04023020",
        "tags": ["Stakeholder", "Forest", "Climate Change", "CRB"],
        "highlight": False,
        "tiles": [
            {"value": "4 Scenarios",  "label": "Forest Disturbance Scenarios", "icon": " ", "color": "tile-maroon"},
            {"value": "2026",         "label": "Target: CRB Renegotiation",    "icon": " ", "color": "tile-navy"},
            {"value": "15 Agencies",  "label": "Stakeholders Engaged",         "icon": " ", "color": "tile-green"},
            {"value": "LOCA2+VIC",    "label": "Modeling Framework",           "icon": "", "color": "tile-gold"},
        ],
        "abstract": (
            "A collaborative modeling approach integrating VIC with stakeholder-co-developed scenarios of ""forest thinning, wildfire, and mortality across CRB. Results show forest disturbance can alter ""sub-basin streamflow by ±15%, with significant implications for water management planning ""ahead of the 2026 Colorado River Compact renegotiation."),
    },
    {
        "id": "whitney2023ems",
        "year": 2023,
        "status": "published",
        "title": "Enhancing the Accessibility and Interactions of Regional Hydrologic Projections for Water Managers",
        "authors": "Whitney, K.M., Vivoni, E.R., White, D.D.",
        "journal": "Environmental Modelling and Software",
        "journal_short": "Environ. Model. Softw.",
        "doi": "10.1016/j.envsoft.2023.105763",
        "volume": "167",
        "pages": "105763",
        "tags": ["Visualization", "Decision Support", "Stakeholder", "CRB"],
        "highlight": False,
        "tiles": [
            {"value": "ShinyApp",  "label": "Visualization Tool", "icon": "", "color": "tile-maroon"},
            {"value": "8 Basins",  "label": "CRB Sub-basins",     "icon": "", "color": "tile-navy"},
            {"value": "CoMods",    "label": "Stakeholder Process", "icon": " ", "color": "tile-green"},
            {"value": "2100",      "label": "Projection Horizon",  "icon": " ", "color": "tile-gold"},
        ],
        "abstract": (
            "Developed and evaluated an interactive ShinyApps-based visualization environment for ""regional hydrologic projections in the CRB. The tool was co-developed with CAWCD, ""Bureau of Reclamation, and state agency stakeholders through collaborative modeling sessions. ""Informed the development of the current Python-Dash CRB Decision Support Tool."),
    },
    {
        "id": "whitney2023jhydrol",
        "year": 2023,
        "status": "published",
        "title": "Spatial Attribution of Declining Colorado River Streamflow under Future Warming",
        "authors": "Whitney, K.M., Vivoni, E.R., Bohn, T.J., Wang, Z., Xiao, M., Mascaro, G., Mahmoud, M.I., Cullom, C., White, D.D.",
        "journal": "Journal of Hydrology",
        "journal_short": "J. Hydrology",
        "doi": "10.1016/j.jhydrol.2023.129125",
        "volume": "617(C)",
        "pages": "129125",
        "tags": ["Climate Change", "Streamflow", "Attribution", "VIC"],
        "highlight": False,
        "tiles": [
            {"value": "−30%",      "label": "Streamflow Decline (SSP585)", "icon": " ", "color": "tile-maroon"},
            {"value": "Upper CRB", "label": "Dominant Runoff Source",      "icon": "", "color": "tile-navy"},
            {"value": "CMIP6",     "label": "Climate Projections Used",    "icon": "", "color": "tile-green"},
            {"value": "2099",      "label": "End-of-century Horizon",      "icon": " ", "color": "tile-gold"},
        ],
        "abstract": (
            "Spatial attribution of projected CRB streamflow changes shows Upper Basin (Green River, ""Upper Colorado) as the dominant source of decline under warming. ""Under SSP5-8.5, total CRB runoff decreases by ~30% by 2099, driven primarily by ""increased ET and reduced snowpack in the headwaters, with sub-basin contributions ""quantified for water management planning."),
    },
    {
        "id": "xiao2022hess",
        "year": 2022,
        "status": "published",
        "title": "On the Value of Satellite Remote Sensing to Reduce Uncertainties in Regional Simulations of the Colorado River",
        "authors": "Xiao, M., Mascaro, G., Wang, Z., Whitney, K.M., Vivoni, E.R.",
        "journal": "Hydrology and Earth System Sciences",
        "journal_short": "Hydrol. Earth Syst. Sci.",
        "doi": "10.5194/hess-26-5627-2022",
        "volume": "26(21)",
        "pages": "5627–5646",
        "tags": ["Remote Sensing", "MODIS", "Calibration", "VIC"],
        "highlight": False,
        "tiles": [
            {"value": "MODIS LST", "label": "Calibration Constraint",       "icon": "", "color": "tile-maroon"},
            {"value": "NSE ",     "label": "Improved Model Skill",         "icon": " ", "color": "tile-navy"},
            {"value": "ECOSTRESS", "label": "ET Validation Platform",       "icon": " ", "color": "tile-green"},
            {"value": "6 km",      "label": "VIC Grid Resolution",          "icon": "", "color": "tile-gold"},
        ],
        "abstract": (
            "Demonstrates how multi-variable satellite observations (MODIS Land Surface Temperature, ""Snow Cover Fraction) systematically reduce parameter uncertainty in VIC regional simulations ""of the CRB. Multi-objective calibration using remote sensing constraints significantly improves ""streamflow prediction, establishing the remote-sensing-calibrated VIC used in this dashboard."),
    },
    {
        "id": "wang2022jawra",
        "year": 2022,
        "status": "published",
        "title": "Individualized and Combined Effects of Future Urban Growth and Climate Change on Irrigation Water Use in Central Arizona",
        "authors": "Wang, Z., Vivoni, E.R.",
        "journal": "Journal of the American Water Resources Association",
        "journal_short": "J. Am. Water Resour. Assoc.",
        "doi": "10.1111/1752-1688.13005",
        "volume": "58(3)",
        "pages": "370–387",
        "tags": ["Urban Growth", "Irrigation", "Climate Change", "Arizona"],
        "highlight": False,
        "tiles": [
            {"value": "+40%",      "label": "Irrigation Demand Increase",  "icon": " ", "color": "tile-maroon"},
            {"value": "2050",      "label": "Projection Horizon",           "icon": " ", "color": "tile-navy"},
            {"value": "CAP Zone",  "label": "Study Area: CAP Service",     "icon": " ", "color": "tile-green"},
            {"value": "PlanetScope","label": "Land Cover Detection",       "icon": "", "color": "tile-gold"},
        ],
        "abstract": (
            "Combined VIC-based assessment of urban growth and climate warming effects on irrigation ""water demand in Central Arizona. Results quantify that combined effects can increase ""annual irrigation demand by up to 40% by 2050, critical for Central Arizona Project ""long-term planning and water allocation under drought stress."),
    },
    {
        "id": "wang2021jawra",
        "year": 2021,
        "status": "published",
        "title": "A Multiyear Assessment of Irrigation Cooling Capacity in Agricultural and Urban Settings of Arizona",
        "authors": "Wang, Z., Vivoni, E.R., Bohn, T.J., Wang, Z-H.",
        "journal": "Journal of the American Water Resources Association",
        "journal_short": "J. Am. Water Resour. Assoc.",
        "doi": "10.1111/1752-1688.12920",
        "volume": "57(5)",
        "pages": "771–788",
        "tags": ["Irrigation", "Urban Heat", "Arizona", "MODIS"],
        "highlight": False,
        "tiles": [
            {"value": "−2.5°C",   "label": "Urban Cooling Effect",        "icon": "", "color": "tile-maroon"},
            {"value": "MODIS LST","label": "Thermal Observation Source",  "icon": "", "color": "tile-navy"},
            {"value": "8 yr",     "label": "Multi-year Analysis Period",  "icon": " ", "color": "tile-green"},
            {"value": "Maricopa", "label": "Study Region",                "icon": " ", "color": "tile-gold"},
        ],
        "abstract": (
            "Multi-year MODIS Land Surface Temperature analysis across Arizona agricultural and urban ""landscapes reveals irrigation-induced cooling of up to 2.5°C relative to non-irrigated areas. ""Findings inform the soil moisture replenishment scheme in VIC and provide context for ""ET estimation critical to CRB water balance modeling."),
    },
    # ── Additional peer-reviewed studies ─────────────────────
    {
        "id": "wang2024wrr",
        "year": 2024,
        "status": "published",
        "title": "On the Sensitivity of Future Hydrology in the Colorado River to the Selection of the Precipitation Partitioning Method",
        "authors": "Wang, Z., Vivoni, E.R., Whitney, K.M., Xiao, M., Mascaro, G.",
        "journal": "Water Resources Research",
        "journal_short": "Water Resour. Res.",
        "doi": "10.1029/2023WR035801",
        "volume": "60(6)",
        "pages": "e2023WR035801",
        "tags": ["Snow-Rain Partitioning", "VIC", "Future Hydrology", "CRB"],
        "highlight": False,
        "tiles": [
            {"value": "PPM",       "label": "New Partitioning Method",    "icon": "", "color": "tile-maroon"},
            {"value": "Wet Bulb T","label": "Temperature Metric Used",   "icon": "", "color": "tile-navy"},
            {"value": "15 Models", "label": "CMIP5+CMIP6 Ensembles",     "icon": " ", "color": "tile-green"},
            {"value": "2099",      "label": "Projection Horizon",         "icon": " ", "color": "tile-gold"},
        ],
        "abstract": (
            "Investigates how choice of snow-rain partitioning method (wet bulb vs. air temperature) ""affects projected CRB hydrology under climate change. A new Precipitation Partition Method ""(PPM) using wet bulb temperature is evaluated across CMIP5 and CMIP6 scenarios, showing ""significant implications for snowpack and streamflow projections, especially under high-emission scenarios."),
    },
    {
        "id": "yue2025jhm",
        "year": 2025,
        "status": "published",
        "title": "Hydrometeorological Forecast Skill of the North American Multimodel Ensemble in the Upper Colorado River Basin",
        "authors": "Yue, H., Mascaro, G., Wang, Z., Vivoni, E.R.",
        "journal": "Journal of Hydrometeorology",
        "journal_short": "J. Hydrometeorol.",
        "doi": "10.1175/JHM-D-24-0087.1",
        "volume": "26(7)",
        "pages": "933–949",
        "tags": ["NMME", "Seasonal Forecast", "CRB", "ISM"],
        "highlight": False,
        "tiles": [
            {"value": "NMME",       "label": "6-Model Ensemble",          "icon": "", "color": "tile-maroon"},
            {"value": "6 Months",   "label": "Forecast Lead Time",        "icon": " ", "color": "tile-navy"},
            {"value": "vs ISM",     "label": "Comparison Method",         "icon": " ", "color": "tile-green"},
            {"value": "2015–2023",  "label": "Evaluation Period",         "icon": " ", "color": "tile-gold"},
        ],
        "abstract": (
            "Evaluates the hydrometeorological forecast skill of the North American Multi-Model Ensemble ""(NMME) at multiple lead times across CRB sub-basins, comparing against the Index Sequential ""Method (ISM) currently used by USBR and CAP for the 24-month study. Results inform which ""forecast products best support short-range operational water management decisions."),
    },
    {
        "id": "ghimire2026wrr",
        "year": 2026,
        "status": "published",
        "title": "Fall Soil Moisture Modulates Snow–Streamflow Dynamics in the Colorado River Basin",
        "authors": "Ghimire, S., Vivoni, E.R., Wang, Z.",
        "journal": "Water Resources Research",
        "journal_short": "Water Resour. Res.",
        "doi": "10.1029/2025WR042871",
        "volume": "62(7), e2025WR042871",
        "pages": "—",
        "tags": ["Soil Moisture", "Streamflow Prediction", "VIC", "CRB", "Seasonal Forecast"],
        "highlight": True,
        "tiles": [
            {"value": "69–77%",   "label": "Upper-Basin flow variability from fall SM", "icon": "", "color": "tile-maroon"},
            {"value": "1 Oct SM", "label": "Enhances water-year prediction",            "icon": "", "color": "tile-navy"},
            {"value": "48–87%",   "label": "Lower-Basin flow from spring precip",        "icon": "", "color": "tile-green"},
            {"value": "Open access","label": "WRR 2026",                                 "icon": " ", "color": "tile-gold"},
        ],
        "abstract": (
            "Controlled VIC experiments isolate the roles of 1 October soil moisture and April–June ""precipitation and temperature on snow-to-streamflow conversion, holding average snowpack. Fall ""soil moisture explains 69–77% of Upper-Basin streamflow variability; spring precipitation ""dominates in the Lower Basin (48–87%). For average-snowpack years, multilinear regressions on ""fall soil moisture and spring weather predict water-year streamflow, and 1 October total-column ""soil moisture enhances Upper-Basin seasonal predictions — the published basis for this tool's ""Soil Moisture–Streamflow Coupling module."),
    },
]


# ── Helper: status badge ──────────────────────────────────────
def status_badge(status):
    if status == "published":
        return html.Span("Published",
                         style={"background": "#2E7D32", "color": "white",
                                "padding": "2px 8px", "borderRadius": "12px",
                                "fontSize": "11px", "fontWeight": "600"})
    elif status == "in_review":
        return html.Span("⟳ In Review",
                         style={"background": "#E65100", "color": "white",
                                "padding": "2px 8px", "borderRadius": "12px",
                                "fontSize": "11px", "fontWeight": "600"})
    else:
        return html.Span("In Preparation",
                         style={"background": "#4527A0", "color": "white",
                                "padding": "2px 8px", "borderRadius": "12px",
                                "fontSize": "11px", "fontWeight": "600"})


# ── Helper: render one publication card ──────────────────────
def pub_card(p):
    is_highlight = p.get("highlight", False)
    card_class = "pub-card pub-card-highlight" if is_highlight else "pub-card"# Info tiles
    tiles = [
        html.Div([
            html.Div(t["icon"], className="pub-tile-icon"),
            html.Div(t["value"], className="pub-tile-value"),
            html.Div(t["label"], className="pub-tile-label"),
        ], className=f"pub-tile {t['color']}")
        for t in p["tiles"]
    ]

    # Tags
    tag_els = [html.Span(t, className="pub-tag") for t in p["tags"]]

    # DOI link
    if p["doi"] != "—":
        doi_el = html.A(
            f"DOI: {p['doi']}",
            href=f"https://doi.org/{p['doi']}",
            target="_blank",
            style={"fontSize": "11px", "color": "#8C1D40", "textDecoration": "none",
                   "fontFamily": "monospace"}
        )
    else:
        doi_el = html.Span(f"Journal: {p['journal_short']} — {p['volume']}",
                           style={"fontSize": "11px", "color": "#1e293b",
                                  "fontFamily": "monospace"})

    return html.Div([
        # Top row: year + status
        html.Div([
            html.Span(str(p["year"]),
                      style={"fontSize": "13px", "fontWeight": "700",
                             "color": "#8C1D40", "marginRight": "10px"}),
            status_badge(p["status"]),
            html.Span("KEY PAPER",
                      style={"marginLeft": "8px", "fontSize": "11px",
                             "color": "#FFC627", "fontWeight": "700"})
            if is_highlight else html.Span(),
        ], style={"marginBottom": "6px", "display": "flex", "alignItems": "center",
                  "flexWrap": "wrap", "gap": "4px"}),

        # Title
        html.H5(p["title"],
                style={"fontSize": "14px", "fontWeight": "700", "color": "#1e293b",
                       "lineHeight": "1.35", "marginBottom": "4px"}),

        # Authors
        html.P(p["authors"],
               style={"fontSize": "12px", "color": "#1e293b", "marginBottom": "4px",
                      "fontStyle": "italic"}),

        # Journal + DOI
        html.Div([
            html.Span(f"{p['journal_short']}  |  ",
                      style={"fontSize": "12px", "fontWeight": "600", "color": "#0D2137"}),
            doi_el,
        ], style={"marginBottom": "10px"}),

        # Info tiles
        html.Div(tiles, className="pub-tiles-row"),

        # Abstract
        html.Details([
            html.Summary("Abstract / Relevance",
                         style={"cursor": "pointer", "fontSize": "12px",
                                "color": "#8C1D40", "fontWeight": "600",
                                "marginTop": "10px", "marginBottom": "4px"}),
            html.P(p["abstract"],
                   style={"fontSize": "12px", "color": "#1e293b",
                          "lineHeight": "1.55", "marginTop": "6px",
                          "paddingLeft": "8px", "borderLeft": "3px solid #e2e8f0"}),
        ]),

        # Tags
        html.Div(tag_els, style={"marginTop": "8px", "display": "flex",
                                 "flexWrap": "wrap", "gap": "4px"}),
    ], className=card_class)


# ── Top-level info tiles ──────────────────────────────────────
def make_header_tiles():
    n_pub = sum(1 for p in PUBLICATIONS if p["status"] == "published")
    n_high = sum(1 for p in PUBLICATIONS if p.get("highlight"))
    journals = len({p["journal"] for p in PUBLICATIONS if p["status"] == "published"})
    years = f"{min(p['year'] for p in PUBLICATIONS)}–{max(p['year'] for p in PUBLICATIONS)}"
    tiles = [
        {"v": str(n_pub),   "l": "Peer-reviewed Papers",  "i": " ", "c": "tile-maroon"},
        {"v": str(n_high),  "l": "Foundational to the tool", "i": " ",  "c": "tile-navy"},
        {"v": str(journals),"l": "Peer-reviewed Journals", "i": " ", "c": "tile-green"},
        {"v": years,        "l": "Publication Span",       "i": " ", "c": "tile-gold"},
    ]
    return dbc.Row([
        dbc.Col(
            html.Div([
                html.Div(t["i"], className="info-tile-icon"),
                html.Div(t["v"], className="info-tile-value"),
                html.Div(t["l"], className="info-tile-label"),
            ], className=f"info-tile {t['c']}"),
            xs=6, md=3
        )
        for t in tiles
    ], className="g-2 mb-3")


# ── Filter bar ───────────────────────────────────────────────
def make_filter_bar():
    all_tags = sorted({tag for p in PUBLICATIONS for tag in p["tags"]})
    return html.Div([
        html.Div([
            html.Label("Filter by topic:", style={"fontSize": "12px", "fontWeight": "600",
                                                   "color": "#1e293b", "marginRight": "8px",
                                                   "whiteSpace": "nowrap"}),
            dcc.Dropdown(
                id="pub-filter-tag",
                options=[{"label": t, "value": t} for t in all_tags],
                placeholder="All topics",
                multi=True,
                clearable=True,
                style={"fontSize": "12px", "flex": "1 1 240px", "minWidth": "0"},
            ),
        ], style={"display": "flex", "alignItems": "center", "flexWrap": "wrap", "gap": "8px"}),

        html.Div([
            html.Label("Status:", style={"fontSize": "12px", "fontWeight": "600",
                                          "color": "#1e293b", "marginRight": "8px"}),
            dcc.RadioItems(
                id="pub-filter-status",
                options=[
                    {"label": "All", "value": "all"},
                    {"label": "Published", "value": "published"},
                ],
                value="all",
                inline=True,
                labelStyle={"fontSize": "12px", "marginRight": "12px"},
            ),
        ], style={"display": "flex", "alignItems": "center", "flexWrap": "wrap", "gap": "4px"}),
    ], className="pub-filter-bar")


# ── Layout ───────────────────────────────────────────────────
def layout():
    return html.Div([
        # Header
        html.Div([
            html.H2("Publications"),
            html.P(
                "Peer-reviewed research from the NASA Colorado River Basin ""Infrastructure Asset Project (Award 80NSSC22K0925) · ""Vivoni Hydrologic Systems Lab · Arizona State University"),
        ], className="tab-header"),

        # Body
        html.Div([
            make_header_tiles(),
            make_filter_bar(),
            html.Div(id="pub-cards-container", style={"marginTop": "12px"}),
        ], className="tab-body"),
    ])


# ── Callbacks ────────────────────────────────────────────────
def register_callbacks(app):
    @app.callback(
        Output("pub-cards-container", "children"),
        Input("pub-filter-tag", "value"),
        Input("pub-filter-status", "value"),
    )
    def update_pub_cards(selected_tags, selected_status):
        filtered = PUBLICATIONS

        if selected_status == "published":
            filtered = [p for p in filtered if p["status"] == "published"]
        elif selected_status == "prep":
            filtered = [p for p in filtered if p["status"] in ("in_review", "in_prep")]

        if selected_tags:
            filtered = [p for p in filtered
                        if any(t in p["tags"] for t in selected_tags)]

        if not filtered:
            return html.Div("No publications match the selected filters.",
                            style={"color": "#1e293b", "padding": "24px",
                                   "textAlign": "center", "fontSize": "14px"})

        # Sort: highlight first, then by year desc
        filtered = sorted(filtered, key=lambda p: (not p.get("highlight", False), -p["year"]))

        return html.Div([pub_card(p) for p in filtered])
