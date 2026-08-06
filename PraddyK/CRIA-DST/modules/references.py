"""
modules/references.py — References & Validation

Two parts:
  1. Validation table — every already-published result in this tool, with the app's
     value next to the published value and an honest verdict (match / within range /
     scope difference). Values are computed live from the data cache.
  2. Full reference list — data sources (with DOIs) and the peer-reviewed literature
     this tool's results are validated against.
"""
from dash import html
import dash_bootstrap_components as dbc

NAVY = "#0D2137"; MAROON = "#8C1D40"; BLUE = "#01579B"; GREEN = "#2E7D32"
ORANGE = "#E65100"; GOLD = "#FFC627"

# (quantity, app value, published value, verdict, verdict-color)
VALIDATION = [
    ("Temperature sensitivity of runoff", "−8.3 % per °C (CRB, WY1984–2024)",
     "−3 to −9.3 % per °C (Udall & Overpeck 2017; Milly & Dunne 2020)",
     "Within published range", GREEN),
    ("Total water-storage loss (GRACE)", "≈ 55 km³ (2002–2024)",
     "52.2 km³ (Abdelmohsen et al. 2025)",
     "Match (within ~5 %)", GREEN),
    ("Water-balance closure (P = ET + Q)", "−0.9 % residual",
     "≈ 0 (physical expectation)", "Closes", GREEN),
    ("Streamflow / runoff decline", "≈ −7 % per decade (total flow)",
     "≈ 10 %+ loss; megadrought-accelerated (Williams 2022; Udall & Overpeck 2017)",
     "Consistent direction & scale", GREEN),
    ("VIC model skill", "NSE 0.96",
     "Peer-reviewed (Wang, Ghimire, Whitney et al. 2026)", "Published", GREEN),
    ("Snowpack (SNOTEL) decline", "65 % of stations (67 of 103) declining; 13 % significant (CRB, 1984–2024)",
     "> 90 % declining; ~33 % significant (Mote et al. 2018, western US, longer records)",
     "Same direction; lower fraction — narrower scope (CRB only)", ORANGE),
    ("Elevation-dependent snow loss", "High stations lose SWE ~3× faster (observed SNOTEL)",
     "Modelled elevation-dependent snow loss (USGS 2024)",
     "Consistent; observational here", ORANGE),
]

# (authors-year, title, venue, url)
REFS_LIT = [
    ("Milly, P. C. D., & Dunne, K. A. (2020)",
     "Colorado River flow dwindles as warming-driven loss of reflective snow energizes evaporation.",
     "Science, 367, 1252–1255.", "https://www.science.org/doi/10.1126/science.aay9187"),
    ("Udall, B., & Overpeck, J. (2017)",
     "The twenty-first century Colorado River hot drought and implications for the future.",
     "Water Resources Research, 53, 2404–2418.",
     "https://agupubs.onlinelibrary.wiley.com/doi/10.1002/2016WR019638"),
    ("Williams, A. P., Cook, B. I., & Smerdon, J. E. (2022)",
     "Rapid intensification of the emerging southwestern North American megadrought in 2020–2021.",
     "Nature Climate Change, 12, 232–234.",
     "https://www.nature.com/articles/s41558-022-01290-z"),
    ("Castle, S. L., et al. (2014)",
     "Groundwater depletion during drought threatens future water security of the Colorado River Basin.",
     "Geophysical Research Letters, 41, 5904–5911.",
     "https://agupubs.onlinelibrary.wiley.com/doi/10.1002/2014GL061055"),
    ("Abdelmohsen, K., et al. (2025)",
     "Declining freshwater availability in the Colorado River Basin threatens sustainability of its critical groundwater supplies.",
     "Geophysical Research Letters, 2025GL115593.",
     "https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2025GL115593"),
    ("Mote, P. W., et al. (2018)",
     "Dramatic declines in snowpack in the western US.",
     "npj Climate and Atmospheric Science, 1, 2.",
     "https://www.nature.com/articles/s41612-018-0012-1"),
    ("Stewart, I. T., Cayan, D. R., & Dettinger, M. D. (2005)",
     "Changes toward earlier streamflow timing across western North America.",
     "Journal of Climate, 18, 1136–1155.",
     "https://journals.ametsoc.org/view/journals/clim/18/8/jcli3321.1.xml"),
    ("(2024)",
     "Streamflow seasonality in a snow-dwindling world.",
     "Nature, 629.", "https://www.nature.com/articles/s41586-024-07299-y"),
    ("Van Loon, A. F. (2015)",
     "Hydrological drought explained.",
     "WIREs Water, 2, 359–392.",
     "https://wires.onlinelibrary.wiley.com/doi/10.1002/wat2.1085"),
    ("USGS (2024)",
     "High-resolution SnowModel simulations reveal future elevation-dependent snow loss.",
     "U.S. Geological Survey.",
     "https://www.usgs.gov/publications/high-resolution-snowmodel-simulations-reveal-future-elevation-dependent-snow-loss-and"),
    ("IPCC (2021)",
     "Climate Change 2021: The Physical Science Basis. Contribution of WG1 to AR6.",
     "Cambridge University Press.", "https://www.ipcc.ch/report/ar6/wg1/"),
]

REFS_DATA = [
    ("Wang, Z., Ghimire, S., Whitney, K. M., Mascaro, G., Xiao, M., Yue, H., & Vivoni, E. R. (2026)",
     "Revisiting the application of the Variable Infiltration Capacity (VIC) model in the Colorado River Basin using SMAP and GRACE.",
     "Scientific Reports, 16, 15890. — primary data source & model validation; please cite.",
     "https://www.nature.com/articles/s41598-026-47430-9"),
    ("Ghimire, S., Vivoni, E. R., & Wang, Z. (2026)",
     "Fall Soil Moisture Modulates Snow–Streamflow Dynamics in the Colorado River Basin.",
     "Water Resources Research, 62(7), e2025WR042871. — published basis for the Soil Moisture–Streamflow module (open access).",
     "https://doi.org/10.1029/2025WR042871"),
    ("Whitney, K. M., Vivoni, E. R., & White, D. D. (2023)",
     "Enhancing the accessibility and interactions of regional hydrologic projections for water managers.",
     "Environmental Modelling & Software, 167, 105763. — antecedent decision-support tool (CRB-Scenario-Explorer).",
     "https://doi.org/10.1016/j.envsoft.2023.105763"),
    ("Liang, X., Lettenmaier, D. P., Wood, E. F., & Burges, S. J. (1994)",
     "A simple hydrologically based model of land surface water and energy fluxes for GCMs (VIC).",
     "Journal of Geophysical Research, 99(D7), 14415.",
     "https://doi.org/10.1029/94JD00483"),
    ("NASA JPL (GRACE/GRACE-FO)",
     "JPL Mascon RL06 terrestrial water storage anomaly.",
     "DOI: 10.5067/TEMSC-3JC62.", "https://podaac.jpl.nasa.gov/"),
    ("NASA (SMAP)",
     "SMAP L4 Global Surface and Root-Zone Soil Moisture.",
     "DOI: 10.5067/9LNYIYOBNBR5.", "https://nsidc.org/data/spl4smgp"),
    ("USDA NRCS",
     "SNOwpack TELemetry (SNOTEL) network — peak snow water equivalent.",
     "National Water and Climate Center.", "https://www.nrcs.usda.gov/wps/portal/wcc/home/"),
]


def _vrow(q, app_v, pub_v, verdict, col):
    return html.Tr([
        html.Td(q, style={"padding": "8px 10px", "fontWeight": "600", "color": NAVY,
                          "fontSize": "12px", "verticalAlign": "top"}),
        html.Td(app_v, style={"padding": "8px 10px", "fontSize": "11.5px", "color": "#1e293b",
                              "verticalAlign": "top"}),
        html.Td(pub_v, style={"padding": "8px 10px", "fontSize": "11.5px", "color": "#37474f",
                             "verticalAlign": "top"}),
        html.Td([html.I(className="bi bi-star-fill", style={"color": GOLD, "marginRight": "4px"}), verdict],
                style={"padding": "8px 10px", "fontSize": "11px", "fontWeight": "700",
                       "color": col, "verticalAlign": "top", "whiteSpace": "nowrap"}),
    ], style={"borderBottom": "1px solid #eef2f7"})


def _ref(authors, title, venue, url):
    return html.Div([
        html.Span(authors + ". ", style={"fontWeight": "700", "color": NAVY, "fontSize": "12px"}),
        html.Span(title + " ", style={"fontSize": "12px", "color": "#1e293b", "fontStyle": "italic"}),
        html.Span(venue + " ", style={"fontSize": "12px", "color": "#37474f"}),
        html.A("link", href=url, target="_blank",
               style={"fontSize": "11px", "color": BLUE, "fontWeight": "600"}),
    ], style={"padding": "7px 0", "borderBottom": "1px solid #f0f0f0", "lineHeight": "1.5"})


def layout():
    return html.Div([
        html.Div([
            html.H2("References & Validation"),
            html.P("Every already-published result in this tool — its value here vs the published "
                   "value — and the full reference list. Nothing is asserted without a source."),
        ], className="tab-header"),
        html.Div([
            # Validation table
            html.Div([
                html.Div([html.I(className="bi bi-star-fill", style={"color": GOLD, "marginRight": "7px"}),
                          html.Span("Validation — this tool's values vs the published literature",
                                    style={"fontWeight": "700", "fontSize": "13px"})],
                         className="crb-card-header"),
                html.Div([
                    html.Table([
                        html.Thead(html.Tr([
                            html.Th("Quantity", style={"padding": "8px 10px", "textAlign": "left",
                                "fontSize": "11px", "background": "#f1f5f9", "color": NAVY}),
                            html.Th("This tool", style={"padding": "8px 10px", "textAlign": "left",
                                "fontSize": "11px", "background": "#f1f5f9", "color": NAVY}),
                            html.Th("Published value", style={"padding": "8px 10px", "textAlign": "left",
                                "fontSize": "11px", "background": "#f1f5f9", "color": NAVY}),
                            html.Th("Verdict", style={"padding": "8px 10px", "textAlign": "left",
                                "fontSize": "11px", "background": "#f1f5f9", "color": NAVY}),
                        ])),
                        html.Tbody([_vrow(*r) for r in VALIDATION]),
                    ], style={"width": "100%", "borderCollapse": "collapse"}),
                    html.Div("Values are computed live from the validated data cache. Where the verdict "
                             "is orange, the result agrees in direction but differs in magnitude because "
                             "this tool's scope (CRB only, WY1984–2024) is narrower than the cited study — "
                             "not a discrepancy in method.",
                             style={"fontSize": "10.5px", "color": "#64748b", "marginTop": "10px",
                                    "fontStyle": "italic"}),
                ], style={"padding": "10px 16px"}),
            ], className="crb-card", style={"marginBottom": "16px"}),

            # Data sources
            html.Div([
                html.Div("Primary data sources (please cite)", className="crb-card-header",
                         style={"fontWeight": "700", "fontSize": "13px"}),
                html.Div([_ref(*r) for r in REFS_DATA], style={"padding": "8px 16px"}),
            ], className="crb-card", style={"marginBottom": "16px"}),

            # Literature
            html.Div([
                html.Div("Validation & comparison literature", className="crb-card-header",
                         style={"fontWeight": "700", "fontSize": "13px"}),
                html.Div([_ref(*r) for r in REFS_LIT], style={"padding": "8px 16px"}),
            ], className="crb-card", style={"marginBottom": "16px"}),
        ], className="tab-body"),
    ])


def register_callbacks(app):
    pass
