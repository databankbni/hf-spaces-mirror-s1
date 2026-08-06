"""modules/methods.py — Methods & Data Citations"""
from dash import html
import dash_bootstrap_components as dbc

NAVY="#0D2137"; MAROON="#8C1D40"; BLUE="#01579B"; GREEN="#2E7D32"; PURPLE="#4527A0"; ORANGE="#E65100"


def _stat(value, unit, label, color):
    return html.Div([
        html.Div([html.Span(value, style={"fontSize": "26px", "fontWeight": "800", "color": color,
                                           "lineHeight": "1"}),
                  html.Span(unit, style={"fontSize": "12px", "fontWeight": "700", "color": color,
                                         "marginLeft": "3px"})]),
        html.Div(label, style={"fontSize": "10.5px", "color": "#37474f", "fontWeight": "600",
                               "marginTop": "4px", "lineHeight": "1.3"}),
    ], style={"background": "#fff", "borderTop": f"3px solid {color}", "borderRadius": "6px",
              "padding": "12px 14px", "height": "100%",
              "boxShadow": "0 2px 8px rgba(0,0,0,0.06)"})


def _skill(label, value, sub, color, value_label=None):
    """Horizontal skill bar (0–1 scale) for the model-validation card."""
    pct = max(0, min(100, int(round(value * 100))))
    return html.Div([
        html.Div([
            html.Span(label, style={"fontSize": "12px", "fontWeight": "700", "color": NAVY}),
            html.Span(value_label or f"{value:.2f}",
                      style={"fontSize": "12.5px", "fontWeight": "800", "color": color,
                             "float": "right"}),
        ]),
        html.Div(html.Div(style={"width": f"{pct}%", "background": color, "height": "100%",
                                 "borderRadius": "5px"}),
                 style={"background": "#e8edf2", "height": "9px", "borderRadius": "5px",
                        "marginTop": "4px", "overflow": "hidden"}),
        html.Div(sub, style={"fontSize": "10px", "color": "#78909c", "marginTop": "3px"}),
    ], style={"marginBottom": "11px"})


def _pipe_step(num, title, sub, color, last=False):
    return html.Div([
        html.Div([
            html.Span(str(num), style={"display": "inline-flex", "alignItems": "center",
                "justifyContent": "center", "width": "22px", "height": "22px", "borderRadius": "50%",
                "background": color, "color": "#fff", "fontWeight": "800", "fontSize": "11px",
                "marginRight": "8px", "flex": "0 0 auto"}),
            html.Span(title, style={"fontWeight": "700", "fontSize": "12px", "color": NAVY}),
        ], style={"display": "flex", "alignItems": "center"}),
        html.Div(sub, style={"fontSize": "10.5px", "color": "#546e7a", "paddingLeft": "30px",
                             "marginTop": "2px", "lineHeight": "1.35"}),
    ], style={"flex": "1 1 0", "minWidth": "150px",
              "borderRight": "none" if last else "1px dashed #cfd8dc", "paddingRight": "12px"})


def layout():
    from modules.home import _cold_open  # the observation-validated proof band (moved from Overview)
    return html.Div([
        html.Div([
            html.H2("Methods & Data Sources"),
            html.P("What's under the hood — the data, the model, and the processing behind every "
                   "chart in this tool."),
        ],className="tab-header"),
        # ── Observation-validated proof band (relocated from the Overview) — every claim links
        #    to its source, and the Basin Briefing PDF lives here too ──
        html.Div(_cold_open(), className="tab-body", style={"paddingBottom": "0"}),
        html.Div([
            # ── Data-scale hero banner (makes the depth visible at a glance) ──
            html.Div([
                html.Div([
                    html.I(className="bi bi-database-fill-gear",
                           style={"color": MAROON, "marginRight": "8px", "fontSize": "16px"}),
                    html.Span("The data behind this tool", style={"fontWeight": "800",
                              "color": MAROON, "fontSize": "14px"}),
                ], style={"borderBottom": f"2px solid {MAROON}", "paddingBottom": "8px",
                          "marginBottom": "14px", "display": "flex", "alignItems": "center"}),
                dbc.Row([
                    dbc.Col(_stat("58", " GB", "Raw VIC simulation processed", MAROON), xs=6, md=2, className="mb-2"),
                    dbc.Col(_stat("41", " yrs", "Water years (WY1984–2024), daily", NAVY), xs=6, md=2, className="mb-2"),
                    dbc.Col(_stat("224×176", "", "Grid cells at 1/16° (~6 km)", BLUE), xs=6, md=2, className="mb-2"),
                    dbc.Col(_stat("4", "", "Independent data sources fused", GREEN), xs=6, md=2, className="mb-2"),
                    dbc.Col(_stat("11", "", "Basins (CRB + Upper/Lower + 8 sub)", PURPLE), xs=6, md=2, className="mb-2"),
                    dbc.Col(_stat("103", "", "SNOTEL snow stations", ORANGE), xs=6, md=2, className="mb-2"),
                ], className="g-2"),
                html.Div([
                    html.Span("Sources fused: ", style={"fontWeight": "700", "fontSize": "11px", "color": NAVY}),
                    html.Span("VIC 5.0 (PRISM-calibrated hydrology) · GRACE/GRACE-FO (terrestrial water "
                              "storage, 229 months) · NRCS SNOTEL (snowpack) · NASA SMAP L4 (soil moisture).",
                              style={"fontSize": "11px", "color": "#37474f"}),
                ], style={"marginTop": "10px", "background": "#f1f5f9", "padding": "8px 12px",
                          "borderRadius": "6px"}),
            ], className="crb-card", style={"marginBottom": "16px", "padding": "14px 16px"}),

            # ── Processing pipeline (raw → cache → analyses) ──
            html.Div([
                html.Div("From raw simulation to interactive analysis", className="crb-card-header",
                         style={"fontWeight": "700", "fontSize": "13px"}),
                html.Div([
                    _pipe_step(1, "Raw NetCDF", "58 GB VIC output + GRACE / SNOTEL / SMAP, daily resolution", MAROON),
                    _pipe_step(2, "Basin masking", "Each grid cell assigned to 11 basins via GeoJSON boundaries", NAVY),
                    _pipe_step(3, "Water-year aggregation", "Oct–Sep; fluxes summed, states averaged, SWE annual-max", BLUE),
                    _pipe_step(4, "Validated cache", "Parquet store; reproduces raw to 0.00% on a water-year check", GREEN),
                    _pipe_step(5, "32 interactive analyses", "Loaded live in this tool with downloadable CSVs", PURPLE, last=True),
                ], style={"display": "flex", "flexWrap": "wrap", "gap": "10px", "padding": "14px 16px"}),
            ], className="crb-card", style={"marginBottom": "16px"}),

            # Primary citation
            html.Div([
                html.Div("Primary Data Source — please cite",className="crb-card-header",
                         style={"fontWeight":"700","fontSize":"13px"}),
                html.Div([
                    html.P(["The VIC hydrology, calibration and multi-sensor (SMAP/GRACE/SNOTEL) ""validation underlying this tool are from:"],style={"fontSize":"12px","marginBottom":"6px"}),
                    html.P([html.B("Wang, Z., Ghimire, S., Whitney, K. M., Mascaro, G., Xiao, M., ""Yue, H., & Vivoni, E. R. (2026). "),
                            "Revisiting the application of the variable infiltration capacity (VIC) model in the ""Colorado River Basin using SMAP and GRACE. ",
                            html.I("Scientific Reports, 16, "),"15890."],
                           style={"fontSize":"12px","marginBottom":"6px"}),
                    html.A("https://www.nature.com/articles/s41598-026-47430-9",
                           href="https://www.nature.com/articles/s41598-026-47430-9",target="_blank",
                           style={"fontSize":"11.5px","color":"#01579B"}),
                    html.P("Arizona State University · NASA Applied Sciences. All graphs and data in this tool ""derive from this work and its validated VIC cache.",
                           style={"fontSize":"11px","color":"#1e293b","marginTop":"6px","marginBottom":"0"}),
                ],style={"padding":"12px 16px"}),
            ],className="crb-card",style={"borderLeft":"4px solid #8C1D40","marginBottom":"14px"}),
            # ── Model Validation showcase (published skill scores) ──
            html.Div([
                html.Div("Model Validation — independent skill of the calibrated VIC model",
                         className="crb-card-header", style={"fontWeight": "700", "fontSize": "13px"}),
                html.Div([
                    html.P(["The hydrologic model behind this tool was calibrated on snowpack "
                            "(SNOTEL) and naturalized streamflow, then evaluated against ",
                            html.B("independent NASA observations it never saw during calibration"),
                            " — SMAP soil moisture and GRACE water storage. Published skill "
                            "(Ghimire/Wang et al. 2026, Scientific Reports 16:15890):"],
                           style={"fontSize": "12px", "marginBottom": "12px"}),
                    _skill("Streamflow — Upper Basin", 0.96,
                           "Nash–Sutcliffe Efficiency vs naturalized USBR flow (calibration target)", MAROON),
                    _skill("Soil moisture — surface", 0.71,
                           "R² vs NASA SMAP L4 — independent of calibration", BLUE),
                    _skill("Soil moisture — root-zone", 0.81,
                           "R² vs NASA SMAP L4 — independent of calibration", GREEN),
                    _skill("Terrestrial water storage", 0.86,
                           "R² vs GRACE / GRACE-FO — independent of calibration", PURPLE,
                           value_label="0.66–0.86"),
                    html.Div([
                        html.Span("How to read: ", style={"fontWeight": "700"}),
                        "1.0 = perfect agreement. An NSE of 0.96 plus R² of 0.71–0.86 against data "
                        "the model was never tuned on indicate a rigorously validated model — not "
                        "merely a streamflow fit. A live, month-by-month VIC-vs-SMAP comparison is "
                        "available in the Water Supply & Snow → Water Storage view."],
                        style={"fontSize": "10.5px", "color": "#546e7a", "marginTop": "6px",
                               "background": "#f1f5f9", "padding": "8px 12px", "borderRadius": "6px"}),
                ], style={"padding": "12px 16px"}),
            ], className="crb-card",
               style={"borderLeft": "4px solid #2E7D32", "marginBottom": "14px"}),
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Div("VIC 5.0 Model",className="crb-card-header",
                                 style={"fontWeight":"700","fontSize":"13px"}),
                        html.Div([
                            html.P("Variable Infiltration Capacity (VIC) model v5.0 ""run at 1/16° (~6 km) spatial resolution over the ""Colorado River Basin (224 × 176 grid; ~16,900 cells within the basin).",
                                   style={"fontSize":"12px"}),
                            html.Ul([
                                html.Li("Forcing: PRISM-calibrated precipitation + temperature",style={"fontSize":"11.5px"}),
                                html.Li("Period: WY1984–WY2024 (41 complete water years, Oct–Sep)",style={"fontSize":"11.5px"}),
                                html.Li("Output: 20 variables at daily timestep (incl. OUT_RAD_TEMP)",style={"fontSize":"11.5px"}),
                                html.Li("Basins: 11 (CRB + Upper/Lower + 8 sub-basins that tile the CRB exactly)",style={"fontSize":"11.5px"}),
                                html.Li("Aggregation: fluxes summed · temperatures/states averaged · SWE annual-max",style={"fontSize":"11.5px"}),
                                html.Li("Verified: raw cache reproduces to 0.00% (water-year test)",style={"fontSize":"11.5px"}),
                                html.Li("Future anchor: VICOut2.nc contains WY2100 only (single snapshot)",style={"fontSize":"11.5px"}),
                            ]),
                        ],style={"padding":"12px 16px"}),
                    ],className="crb-card"),
                    html.Div([
                        html.Div("GRACE JPL Mascon RL06",className="crb-card-header",
                                 style={"fontWeight":"700","fontSize":"13px","marginTop":"12px"}),
                        html.Div([
                            html.P("GRACE and GRACE-FO Level-3 gridded terrestrial water ""storage anomaly. CRI-filtered mascon solution.",
                                   style={"fontSize":"12px"}),
                            html.Ul([
                                html.Li("Resolution: 0.5° global grid",style={"fontSize":"11.5px"}),
                                html.Li("Period: April 2002 – January 2024 (229 months)",style={"fontSize":"11.5px"}),
                                html.Li("Units: cm liquid water equivalent anomaly (× scale_factor applied)",style={"fontSize":"11.5px"}),
                                html.Li("2017–18 mission gap left broken (not interpolated)",style={"fontSize":"11.5px"}),
                                html.Li("DOI: 10.5067/TEMSC-3JC62",style={"fontSize":"11.5px"}),
                            ]),
                        ],style={"padding":"12px 16px"}),
                    ],className="crb-card"),
                ],md=6),
                dbc.Col([
                    html.Div([
                        html.Div(" NRCS SNOTEL Network",className="crb-card-header",
                                 style={"fontWeight":"700","fontSize":"13px"}),
                        html.Div([
                            html.P("Natural Resources Conservation Service SNOwpack TELemetry ""network monitoring mountain snowpack in the Western US.",
                                   style={"fontSize":"12px"}),
                            html.Ul([
                                html.Li("Stations: 103 within CRB boundary",style={"fontSize":"11.5px"}),
                                html.Li("Variables: SWE, snow depth, precipitation, temperature",style={"fontSize":"11.5px"}),
                                html.Li("Period: 1978–2024 (varies by station)",style={"fontSize":"11.5px"}),
                                html.Li("Trend method: Mann-Kendall + Sen's slope",style={"fontSize":"11.5px"}),
                            ]),
                        ],style={"padding":"12px 16px"}),
                    ],className="crb-card"),
                    html.Div([
                        html.Div(" SMAP Level-4 Soil Moisture",className="crb-card-header",
                                 style={"fontWeight":"700","fontSize":"13px","marginTop":"12px"}),
                        html.Div([
                            html.P("NASA SMAP Level-4 (L4_SM) global surface and root-zone soil "
                                   "moisture — SMAP observations assimilated into the NASA Catchment "
                                   "land-surface model.",
                                   style={"fontSize":"12px"}),
                            html.Ul([
                                html.Li("Resolution: 9 km EASE-Grid 2.0",style={"fontSize":"11.5px"}),
                                html.Li("Period: November 2022 – September 2024",style={"fontSize":"11.5px"}),
                                html.Li("Units: m³/m³ volumetric soil moisture",style={"fontSize":"11.5px"}),
                                html.Li("DOI: 10.5067/9LNYIYOBNBR5",style={"fontSize":"11.5px"}),
                            ]),
                        ],style={"padding":"12px 16px"}),
                    ],className="crb-card"),
                ],md=6),
            ],className="g-3"),

            # Analysis methods
            html.Div([
                html.Div("Analysis Methods (interactive modules)",className="crb-card-header",
                         style={"fontWeight":"700","fontSize":"13px"}),
                html.Div([
                    html.Ul([
                        html.Li([html.B("Aridification & Runoff: "),"warming sensitivity via elasticity ""ln(Q)=a+b·ln(P)+c·T; c = % water yield per +1 °C. CRB −8.3%/°C ""(benchmark: Milly & Dunne 2020, −9.3%/°C)."],style={"fontSize":"11.5px"}),
                        html.Li([html.B("Aridification Severity Index: "),"composite 0–100 from 4 z-scored ""signals (runoff efficiency, dryness ET/P, soil moisture, temperature)."],style={"fontSize":"11.5px"}),
                        html.Li([html.B("Storage Detective: "),"groundwater ≈ GRACE total − VIC (soil+snow), ""baselined 2004–09; extends Castle et al. 2014 to 2024."],style={"fontSize":"11.5px"}),
                        html.Li([html.B("Budyko Migration: "),"aridity PET/P (Hamon PET) vs ET/P; Fu (1981) curve, w=2.6."],style={"fontSize":"11.5px"}),
                        html.Li([html.B("Drought Cascade: "),"deseasonalized standardized anomalies; lag cross-correlation ""Precip Soil Runoff Storage."],style={"fontSize":"11.5px"}),
                        html.Li([html.B("2023 Recovery: "),"multi-sensor indexed to 2021–22 drought; SMAP covers the window."],style={"fontSize":"11.5px"}),
                        html.Li([html.B("2100 No-Analog: "),"WY2100 vs full 1984–2024 envelope (σ + min/max); end-point snapshot only."],style={"fontSize":"11.5px"}),
                        html.Li([html.B("Melt Timing & Flash Drought: "),"daily-resolution melt center-of-timing, ""peak-SWE day, and steepest 30-day soil-moisture decline."],style={"fontSize":"11.5px"}),
                    ]),
                    html.P("Trends: Mann-Kendall + Sen's slope. Significance flagged (p<0.05 / |t|>2). ""Every chart offers a CSV of its underlying data.",
                           style={"fontSize":"11px","color":"#1e293b","marginTop":"4px"}),
                ],style={"padding":"12px 16px"}),
            ],className="crb-card mt-3"),

            # Validation
            html.Div([
                html.Div("Validation & Data Provenance",className="crb-card-header",
                         style={"fontWeight":"700","fontSize":"13px"}),
                html.Div([
                    html.Ul([
                        html.Li("Reproducible: one script rebuilds the whole cache from raw; an automated check re-validates against the raw NetCDF.",style={"fontSize":"11.5px"}),
                        html.Li("Cross-validated: VIC SWE vs SNOTEL r≈0.83–0.93; VIC+GRACE storage consistent.",style={"fontSize":"11.5px"}),
                        html.Li("Provenance: SHA-256 MANIFEST of every raw + output file.",style={"fontSize":"11.5px"}),
                        html.Li("Known limits: GRACE ≈300 km (small basins flagged); SMAP ~2 yr; future = 2100 only; SNOTEL upper-basin only.",style={"fontSize":"11.5px"}),
                    ]),
                ],style={"padding":"12px 16px"}),
            ],className="crb-card mt-3"),

            # Funding
            html.Div([
                html.Div(" Acknowledgements",className="crb-card-header",
                         style={"fontWeight":"700","fontSize":"13px"}),
                html.Div([
                    html.P("This work was supported by the NASA Applied Sciences Program ""(Award No. 80NSSC22K0925: Managing the Colorado River as an Infrastructure Asset). ""Developed at Arizona State University in collaboration with the ""Central Arizona Project.",
                           style={"fontSize":"12px","color":"#1e293b"}),
                    html.P([html.B("Tool developed by: "),
                            "Praddy Kaushik — Geospatial & Data-Visualization Scientist (Postdoctoral "
                            "Researcher), Arizona State University."],
                           style={"fontSize":"12px","color":"#1e293b","marginTop":"6px","marginBottom":"0"}),
                ],style={"padding":"12px 16px"}),
            ],className="crb-card mt-3"),

            # ── Limitations & scope (stated plainly — scientific maturity) ──
            html.Div([
                html.Div("Limitations & scope", className="crb-card-header",
                         style={"fontWeight": "700", "fontSize": "13px"}),
                html.Div([
                    html.P("Stated plainly, so the tool is used for what it is — and not for what it isn't:",
                           style={"fontSize": "12px", "color": "#37474f", "marginBottom": "8px"}),
                    html.Ul([
                        html.Li(["This is a ", html.B("historical reanalysis"), " (WY1984–2024), not a "
                                 "live operational feed. Current reservoir elevations and real-time "
                                 "conditions are not streamed in; shortage-tier thresholds shown are "
                                 "public USBR policy values."]),
                        html.Li(["The Aridity Severity Index and the basin asset scorecard are ",
                                 html.B("exploratory composite indicators"), " built from validated "
                                 "signals — useful for ranking and tracking condition, but not "
                                 "peer-reviewed standalone metrics."]),
                        html.Li([html.B("Sociopolitical"), " asset scores and stakeholder-agreed weights "
                                 "are the project's separate co-development process; they are not "
                                 "estimated in this tool."]),
                        html.Li(["The far-future (2100) state is a ", html.B("single VIC snapshot"),
                                 ", not a continuous trajectory; it is labelled as such wherever shown."]),
                        html.Li(["Model-skill figures (NSE, R²) are reported from the cited validation "
                                 "study; this tool surfaces the validated reanalysis rather than "
                                 "re-deriving the full calibration."]),
                    ], style={"fontSize": "11.5px", "color": "#37474f", "lineHeight": "1.6",
                              "paddingLeft": "18px", "marginBottom": "0"}),
                ], style={"padding": "12px 16px"}),
            ], className="crb-card mt-3", style={"borderTop": "3px solid #E65100"}),
        ],className="tab-body"),
    ])

def register_callbacks(app): pass
