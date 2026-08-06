"""
utils/manager.py — shared helpers for manager-oriented framing
(acre-feet / MAF conversion + a concise professional summary banner).
"""
from dash import html

# Basin areas (km²) for depth(mm) → volume(MAF) conversion
AREA_KM2 = {"CRB": 654441, "UpperBasin": 293377, "LowerBasin": 361064, "Green": 110702,
            "SanJuan": 60870, "UpperColo": 64735, "GlenCanyon": 57070, "Gila": 161990,
            "GrandCanyon": 85133, "LittleColo": 69561, "LowerColo": 44379}


def to_maf(depth_mm, basin):
    """Basin-mean depth (mm) → basin-integrated volume (million acre-feet).
    1 AF = 1233.48 m³; volume(m³) = depth_mm/1000 × area_km² × 1e6."""
    area = AREA_KM2.get(basin)
    if not area or depth_mm is None or depth_mm != depth_mm:
        return float("nan")
    return depth_mm * area / 1.23348e6


def manager_line(children, color="#0D2137", label="Summary"):
    """A concise, professional summary banner."""
    return html.Div(
        [html.Span(f"{label}   ", style={"fontWeight": "800", "color": color}),
         html.Span(children, style={"fontWeight": "600", "color": "#1e293b"})],
        style={"background": "#eef5fb", "borderLeft": f"4px solid {color}",
               "borderRadius": "0 6px 6px 0", "padding": "9px 14px",
               "fontSize": "12px", "lineHeight": "1.5", "marginBottom": "10px"})
