"""
modules/team.py — The people behind CRIA

Roles and affiliations are from the NASA project record (Award 80NSSC22K0925,
"Managing the Colorado River as an Infrastructure Asset") and each person's public
institutional page. Every card links to a verified public profile — ASU Search, the
NASA Sciences directory, LinkedIn or an institutional page. No personal contact
details are listed here; where no public profile was verified, no link is shown.
"""
from dash import html
import dash_bootstrap_components as dbc
from utils.components import howto

# ASU palette only — maroon, gold, white (LinkedIn chips keep the LinkedIn blue by brand)
MAROON = "#8C1D40"; GOLD = "#BA7517"; NAVY = "#0D2137"

# (name, role, affiliation, contribution, [(label, url), ...])  — links verified public pages
LEADERSHIP = [
    ("Enrique R. Vivoni", "Principal Investigator",
     "Fulton Professor of Hydrosystems Engineering, ASU · Director, Center for Hydrologic Innovations",
     "Leads the project, the hydrologic modelling and basin-wide stakeholder engagement. "
     "PhD in hydrology, MIT (2003); licensed professional engineer; Fellow of the American "
     "Meteorological Society.",
     [("LinkedIn", "https://www.linkedin.com/in/enrique-vivoni/"),
      ("ASU profile", "https://search.asu.edu/profile/1346273"),
      ("Research group", "http://vivoni.asu.edu/")]),
    ("Giuseppe Mascaro", "Co-Investigator",
     "Associate Professor, ASU School of Sustainable Engineering and the Built Environment",
     "Forecasting, statistical analysis and climate downscaling. Leads the Hydroclimate & "
     "Infrastructure Research Lab; PhD in hydrology, University of Cagliari (2008).",
     [("LinkedIn", "https://www.linkedin.com/in/giuseppe-mascaro-4b319429/"),
      ("ASU profile", "https://search.asu.edu/profile/1743729"),
      ("Hydroclimate Lab", "https://labs.engineering.asu.edu/hydroclimate/people/")]),
    ("Dave D. White", "Co-Investigator",
     "Professor, ASU · Associate Vice President and Director, Global Institute of Sustainability "
     "and Innovation",
     "Water governance, sustainability and stakeholder engagement. Previously led the NSF "
     "Decision Center for a Desert City; leads the Arizona Water Innovation Initiative.",
     [("LinkedIn", "https://www.linkedin.com/in/dave-white-4b001b20b/"),
      ("ASU profile", "https://search.asu.edu/profile/386604"),
      ("Google Scholar", "https://scholar.google.com/citations?user=uxg_m-cAAAAJ")]),
    ("Vineetha Kartha", "CAP Co-Lead",
     "Colorado River Programs Manager, Central Arizona Project (CAP)",
     "Grounds the tool in real operational needs and steers co-development with basin "
     "stakeholders. Nearly two decades in water management; previously managed the Colorado "
     "River section at the Arizona Department of Water Resources.",
     [("CAP profile", "https://knowyourwaternews.com/welcome-vineetha-kartha-cap-colorado-river-programs-manager/"),
      ("Glen Canyon AMP bio", "http://gcdamp.com/index.php/Vineetha_Kartha-_BIO_PAGE"),
      ("Central Arizona Project", "https://www.cap-az.com/")]),
]

RESEARCHERS = [
    ("Pradeepika (Praddy) Kaushik", "Postdoctoral Scholar — tool lead & developer",
     "Geospatial & Data-Visualization Scientist, ASU",
     "Designed and built this decision-support tool: the data pipeline, the analyses, the "
     "interface, and the validation surfacing that runs through every tab.",
     [("LinkedIn", "https://www.linkedin.com/in/dr-pradeepika-kaushik/"),
      ("Portfolio", "https://praddyspax.netlify.app/"),
      ("GitHub", "https://github.com/Praddy-GByte")]),
    ("Zhaocheng Wang", "Research Scientist",
     "Center for Hydrologic Innovations, ASU",
     "Lead hydrologic modeller — VIC calibration, precipitation partitioning and the "
     "satellite-informed model improvements that underpin every analysis in this tool.",
     [("LinkedIn", "https://www.linkedin.com/in/zhaocheng-wang/"),
      ("ASU profile", "https://search.asu.edu/profile/2509398"),
      ("Google Scholar", "https://scholar.google.com/citations?user=elboAGYAAAAJ")]),
    ("Haowen Yue", "Postdoctoral Scholar",
     "School of Sustainable Engineering and the Built Environment, ASU",
     "Seasonal streamflow forecasting with the North American Multi-Model Ensemble (NMME). "
     "PhD, Civil & Environmental Engineering, UCLA.",
     [("Lab profile", "https://mascaro.engineering.asu.edu/project/haowen-yue/")]),
    ("Kristen M. Whitney", "Former project researcher",
     "Assistant Research Scientist, ESSIC / University of Maryland at NASA Goddard Space Flight Center",
     "Streamflow attribution, stakeholder engagement and the accessibility of hydrologic "
     "projections — including the CRB Scenario-Explorer this tool builds on.",
     [("LinkedIn", "https://www.linkedin.com/in/kristen-m-whitney/"),
      ("NASA Goddard profile", "https://science.gsfc.nasa.gov/sci/bio/kristen.m.whitney")]),
    ("Mu Xiao", "Research Hydrologist",
     "Center for Western Weather and Water Extremes (CW3E), UC San Diego · formerly ASU",
     "Satellite remote sensing and model calibration — work on using remote sensing to reduce "
     "uncertainty in Colorado River simulations. PhD, Geography, UCLA.",
     [("CW3E profile", "https://cw3e.ucsd.edu/cw3e-welcomes-dr-mu-xiao/"),
      ("ORCID", "https://orcid.org/0000-0002-7437-0739")]),
]

STUDENTS = [
    ("Swastik Ghimire", "MS student, ASU",
     "First author of the peer-reviewed study on how fall soil moisture shapes the basin's "
     "snow-to-streamflow dynamics (Water Resources Research, 2026) — the science behind this "
     "tool's October Signal — and contributes the drought-propagation analysis.",
     [("ASU profile", "https://search.asu.edu/profile/4601049"),
      ("Google Scholar", "https://scholar.google.com/citations?user=6OOqN2cAAAAJ")]),
    ("Xinyu Chen", "PhD student, ASU",
     "Studies CMIP5 and CMIP6 climate projections and the basin's future hydroclimate — the "
     "climate-change signal behind the tool's long-range outlooks.",
     []),
    ("Nour Kandalaft", "MS student, ASU",
     "Contributes to the data assembly, quality control and analysis that underpin the tool's "
     "basin-wide records.",
     [("LinkedIn", "https://www.linkedin.com/in/nour-kandalaft-288627207/")]),
]

PROGRAM = [
    ("Vivian Hobbins", "Senior Program Manager",
     "ASU School of Sustainable Engineering and the Built Environment",
     "Program management for the research group, supporting the Arizona Water Innovation "
     "Initiative. PhD in Ecohydrology; MS Natural Resources; BS Civil Engineering, with more "
     "than a decade in water sustainability.",
     [("LinkedIn", "https://www.linkedin.com/in/vivian-hobbins/"),
      ("ASU profile", "https://search.asu.edu/profile/2360958")]),
]

PARTNERS = [
    ("Arizona State University", "Project lead — Center for Hydrologic Innovations",
     "https://chi.asu.edu"),
    ("Central Arizona Project (CAP)", "Water-management partner & co-developer",
     "https://www.cap-az.com/"),
    ("NASA Applied Sciences", "Funder — Water Resources Program, Award 80NSSC22K0925",
     "https://appliedsciences.nasa.gov/what-we-do/water-resources"),
    ("U.S. Bureau of Reclamation", "Operations & policy (Law of the River, shortage tiers)",
     "https://www.usbr.gov/lc/region/g4000/riverops/"),
    ("NASA Goddard Space Flight Center", "Collaborating institution",
     "https://science.gsfc.nasa.gov/"),
    ("Hydrology @ ASU", "Water research at Arizona State University",
     "https://hydrology.asu.edu/"),
]


ASU_GOLD = "#FFC627"          # bright ASU gold for researcher badges
_GLOSS = ("inset 0 1.5px 0 rgba(255,255,255,0.45), "
          "inset -2px -3px 7px rgba(0,0,0,0.10), "
          "0 6px 14px rgba(13,33,55,0.20), 0 1px 3px rgba(13,33,55,0.12)")


def _badge_style(kind):
    """3D glossy initials badge.
       lead      → solid ASU maroon, white text
       research  → solid ASU gold, maroon text
       student   → ASU maroon→gold gradient, white text"""
    if kind == "lead":
        return {"background": f"linear-gradient(145deg, #A32B52 0%, {MAROON} 55%, #6d1531 100%)",
                "borderColor": MAROON, "color": "#ffffff", "boxShadow": _GLOSS}
    if kind == "research":
        return {"background": f"linear-gradient(145deg, #FFD86B 0%, {ASU_GOLD} 55%, #E0A800 100%)",
                "borderColor": "#E0A800", "color": MAROON, "boxShadow": _GLOSS}
    return {"background": f"linear-gradient(145deg, {ASU_GOLD} 0%, #C25A78 38%, {MAROON} 72%, #6d1531 100%)",
            "borderColor": MAROON, "color": "#ffffff", "boxShadow": _GLOSS}


def _initials(name):
    parts = [p for p in name.replace("(", "").replace(")", "").split() if p[:1].isalpha()]
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()


def _person(name, role, affil, focus, links, accent=MAROON, kind="lead"):
    """A person card. Every chip is its own link, so each opens the right destination."""
    # the name links to the primary profile; each chip links to its own URL
    name_el = (html.A(name, href=links[0][1], target="_blank", rel="noopener",
                      className="tm-name tm-name-link",
                      title=f"Open {name}'s {links[0][0]}")
               if links else html.Div(name, className="tm-name"))
    inner = [
        html.Div([
            html.Div(_initials(name), className="tm-avatar", style=_badge_style(kind)),
            html.Div([
                name_el,
                html.Div(role, className="tm-role", style={"color": accent}),
                html.Div(affil, className="tm-affil"),
            ], style={"minWidth": "0"}),
        ], className="tm-head"),
        html.Div(className="tm-rule"),
        html.Div(focus, className="tm-focus"),
    ]
    if links:
        chips = []
        for lab, url in links:
            is_li = "linkedin.com" in url.lower()
            icon = ("bi bi-linkedin" if is_li else
                    "bi bi-github" if "github.com" in url.lower() else
                    "bi bi-box-arrow-up-right")
            chips.append(html.A([
                html.I(className=icon, style={"fontSize": "10.5px", "marginRight": "5px"}),
                lab,
            ], href=url, target="_blank", rel="noopener",
                className="tm-chip tm-chip-li" if is_li else "tm-chip",
                title=f"Open {lab}"))
        inner.append(html.Div(chips, className="tm-links"))
    return dbc.Col(html.Div(inner, className="tm-card", style={"borderColor": accent}),
                   xs=12, md=6, className="mb-3")


def layout():
    return html.Div([
        html.Div([
            # ── animated hero (carries the page header too) ──
            html.Div([
                html.Div([
                    html.Div("Research team", className="tmh-eyebrow"),
                    html.Div(["The people behind ", html.Span("CRIA", className="tmh-hl")],
                             className="tmh-title"),
                    html.Div("Who builds CRIA and stands behind its numbers — the NASA Applied "
                             "Sciences project “Managing the Colorado River as an Infrastructure "
                             "Asset” (Award 80NSSC22K0925), led by Arizona State University with "
                             "the Central Arizona Project.", className="tmh-sub"),
                    html.Div(className="tmh-rule"),
                    html.Div([
                        html.Div([html.Div(str(len(LEADERSHIP) + len(PROGRAM) + len(RESEARCHERS)
                                               + len(STUDENTS)), className="tmh-n"),
                                  html.Div("researchers & students", className="tmh-l")],
                                 className="tmh-stat"),
                        html.Div([html.Div(str(len(PARTNERS)), className="tmh-n"),
                                  html.Div("partner organisations", className="tmh-l")],
                                 className="tmh-stat"),
                        html.Div([html.Div("36", className="tmh-n"),
                                  html.Div("month NASA project", className="tmh-l")],
                                 className="tmh-stat"),
                    ], className="tmh-stats"),
                ], className="tmh-text"),
                # animated figures — a quiet nod to the people at work
                html.Div([html.Span(className=f"tmh-fig f{i}") for i in range(1, 6)],
                         className="tmh-figs"),
            ], className="tmh"),
            howto("Click any card to open that person's public profile — LinkedIn, ASU Search, "
                  "NASA Goddard or their institution. Roles come from the project record and "
                  "public pages; no personal contact details are listed."),

            html.Div("Project leadership", className="tm-sec"),
            dbc.Row([_person(*p, accent=MAROON, kind="lead") for p in LEADERSHIP],
                    className="g-3 tm-stagger"),

            html.Div("Program Manager", className="tm-sec"),
            dbc.Row([_person(*p, accent=GOLD, kind="research") for p in PROGRAM],
                    className="g-3 tm-stagger justify-content-center"),

            html.Div("Researchers", className="tm-sec"),
            dbc.Row([_person(*p, accent=GOLD, kind="research") for p in RESEARCHERS],
                    className="g-3 tm-stagger"),

            html.Div("Graduate students", className="tm-sec"),
            dbc.Row([
                dbc.Col(html.Div([
                    (html.A(_initials(n), href=lk[0][1], target="_blank", rel="noopener",
                            className="tm-avatar tm-stu-av", style=_badge_style("student"),
                            title=f"Open {n}'s {lk[0][0]}") if lk else
                     html.Div(_initials(n), className="tm-avatar tm-stu-av",
                              style=_badge_style("student"))),
                    html.Div(n, className="tm-stu-name"),
                    html.Div(a, className="tm-stu-affil"),
                    html.Div(className="tm-stu-rule"),
                    html.Div(f, className="tm-stu-focus"),
                    html.Div([
                        html.A([html.I(className=("bi bi-linkedin" if "linkedin" in u.lower()
                                                  else "bi bi-box-arrow-up-right"),
                                       style={"fontSize": "10.5px", "marginRight": "5px"}), lab],
                               href=u, target="_blank", rel="noopener",
                               className="tm-chip tm-chip-li" if "linkedin" in u.lower() else "tm-chip",
                               title=f"Open {lab}")
                        for lab, u in lk], className="tm-links",
                        style={"justifyContent": "center", "marginTop": "8px"}) if lk else None,
                ], className="tm-card tm-stu"), xs=12, sm=6, md=4, className="mb-3")
                for n, a, f, lk in STUDENTS
            ], className="g-3 tm-stagger justify-content-center"),

            html.Div("Partner organisations", className="tm-sec"),
            dbc.Row([
                dbc.Col(html.A([
                    html.Div([html.Span(nm, className="tm-pn"),
                              html.I(className="bi bi-box-arrow-up-right",
                                     style={"marginLeft": "auto", "fontSize": "10px",
                                            "color": MAROON})],
                             style={"display": "flex", "alignItems": "center", "gap": "8px"}),
                    html.Div(role, className="tm-pr"),
                ], href=url, target="_blank", rel="noopener", className="tm-partner"),
                    xs=12, md=4, className="mb-3")
                for nm, role, url in PARTNERS
            ], className="g-3 tm-stagger"),

            html.Div("Tool developed by Pradeepika Kaushik (Praddy), Geospatial & "
                     "Data-Visualization Scientist, Arizona State University.",
                     style={"fontSize": "11.5px", "color": "#546e7a", "marginTop": "18px",
                            "borderTop": "1px solid #e2e8f0", "paddingTop": "12px"}),
        ], className="tab-body"),
    ])
