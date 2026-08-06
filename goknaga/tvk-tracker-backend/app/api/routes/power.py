"""TN Power overview — verified peak-demand history + how the record was met
+ the honest structural context.

Static, sourced public figures (CEA / TANGEDCO / press). Kept in code like
baselines so it's version-controlled and auditable. Framed honestly: the
DMK-era record (met all-time peak, rating B+ -> A) is real; the structural
fragility (heavy procurement dependence, generation gap over ~5 years) is
shown too so the view can't be ambushed.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/power", tags=["power"])

# Peak demand (MW), verified from press/CEA. note flags context.
PEAK_DEMAND_HISTORY = [
    {"year": "FY2016", "peak_mw": 14533, "note": ""},
    {"year": "FY2019", "peak_mw": 17651, "note": ""},
    {"year": "2021",   "peak_mw": 16845, "note": "COVID dip (Apr 10, 2021 record)"},
    {"year": "2022",   "peak_mw": 17563, "note": ""},
    {"year": "2023-24", "peak_mw": 19045, "note": "met with minimal disruption"},
    {"year": "2024",   "peak_mw": 20830, "note": "May 2 — highest-ever then"},
    {"year": "2026",   "peak_mw": 21307, "note": "Apr 29 — ALL-TIME HIGH (DMK era)"},
]

# How the all-time-high day (Apr 29, 2026, 471.45 MU) was supplied.
PROCUREMENT_MIX = [
    {"source": "Private producers", "pct": 36, "mu": 173.1, "color": "amber"},
    {"source": "Central stations",  "pct": 25, "mu": 118.9, "color": "blue"},
    {"source": "TNPDCL own gen.",   "pct": 17, "mu": 81.6,  "color": "emerald"},
    {"source": "Renewables",        "pct": 13, "mu": 61.8,  "color": "green"},
    {"source": "Other / exchange",  "pct": 9,  "mu": 36.0,  "color": "gray"},
]

RATING = {
    "label": "TANGEDCO national service rating",
    "from": "B+", "to": "A",
    "detail": "Consumer Service Rating of DISCOMs (CSRD), Union Power Ministry, "
              "2022-23 — improved from B+ to A grade (10th of 62 discoms).",
}

# Honest structural context so the panel can't be flipped on us.
CONTEXT = [
    {"kind": "win", "text": "TN met its all-time peak demand of 21,307 MW (Apr 29, 2026) — "
                            "and met demand every year as it grew ~47% in a decade."},
    {"kind": "win", "text": "Met through disciplined diversified procurement (private + central "
                            "+ renewables), not panic load-shedding."},
    {"kind": "risk", "text": "TN buys ~75% of its power externally — own generation is only ~17% "
                             "of peak-day supply. A structural dependence, not a one-govt issue."},
    {"kind": "risk", "text": "Unions flag no major new generation capacity added in ~5 years and "
                             "~80% field-staff vacancies — a build-up across the last term."},
    {"kind": "neutral", "text": "2026 summer cuts: TNEB says demand is being met; outages are "
                                "LOCAL (cable faults, overload, substation interruptions), not a "
                                "grid shortfall."},
]


@router.get("/overview")
async def power_overview():
    return {
        "peak_demand_history": PEAK_DEMAND_HISTORY,
        "all_time_high_mw": 21307,
        "all_time_high_date": "2026-04-29",
        "procurement_mix": PROCUREMENT_MIX,
        "rating": RATING,
        "context": CONTEXT,
        "sources": [
            "CEA / TANGEDCO peak-demand data",
            "DT Next, News Today (Apr 2026 record)",
            "The Federal (2026 summer power analysis)",
        ],
    }
