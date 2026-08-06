"""
Point-mass longitudinal equation of motion: m*a = F_traction - F_drag - F_roll - F_grade.

Drag area (CdA) comes from the VD team's CFD runs (config.AERO_CDA_CFD),
interpolated over speed per body geometry -- it is a shape property; weather
only enters through air density and relative airspeed (weather.py), both
consumed here by drag_force_n().
"""

import math

import numpy as np

from . import config
from . import weather as weather_mod


def grade_rad(grade_pct: float) -> float:
    return math.atan(grade_pct / 100.0)


def drag_area_m2(v_kmh: float, geometry: str = None) -> float:
    """Speed-dependent CdA from the CFD table (constant beyond the measured endpoints)."""
    pts = config.AERO_CDA_CFD[geometry or config.AERO_BODY_GEOMETRY]
    speeds = [p[0] for p in pts]
    cdas = [p[1] for p in pts]
    return float(np.interp(abs(v_kmh), speeds, cdas))


def drag_force_n(v_kmh: float, scenario: weather_mod.WeatherScenario, track_heading_deg: float,
                  geometry: str = None) -> float:
    """Signed drag force (N), opposing relative airflow direction."""
    rho = weather_mod.air_density(scenario)
    v_rel_kmh = weather_mod.relative_airspeed_kmh(v_kmh, scenario, track_heading_deg)
    v_rel_ms = v_rel_kmh / 3.6
    # CdA looked up at the RELATIVE airspeed -- that's the flow speed the body sees
    cda = drag_area_m2(v_rel_kmh, geometry)
    return 0.5 * rho * cda * v_rel_ms * abs(v_rel_ms)


def rolling_resistance_n(grade_pct: float, mass_kg: float = None,
                          crr: float = None, g: float = config.GRAVITY_M_S2) -> float:
    mass_kg = config.MASS_TOTAL_KG if mass_kg is None else mass_kg
    crr = config.CRR if crr is None else crr
    return crr * mass_kg * g * math.cos(grade_rad(grade_pct))


def grade_force_n(grade_pct: float, mass_kg: float = None,
                   g: float = config.GRAVITY_M_S2) -> float:
    """Positive = uphill (opposes motion), negative = downhill (aids motion)."""
    mass_kg = config.MASS_TOTAL_KG if mass_kg is None else mass_kg
    return mass_kg * g * math.sin(grade_rad(grade_pct))


def cornering_drag_n(v_kmh: float, r_min_m: float, mass_kg: float = None) -> float:
    """Induced drag from tire slip angle when turning. 0 on straights (r_min_m = inf)."""
    mass_kg = config.MASS_TOTAL_KG if mass_kg is None else mass_kg
    if np.isinf(r_min_m) or r_min_m <= 0.0:
        return 0.0
    v_ms = v_kmh / 3.6
    lateral_accel = (v_ms ** 2) / r_min_m
    return mass_kg * lateral_accel * config.CORNERING_SCRUB_COEFF


def resistance_force_n(v_kmh: float, grade_pct: float, scenario: weather_mod.WeatherScenario,
                        track_heading_deg: float, mass_kg: float = None,
                        r_min_m: float = np.inf) -> float:
    """Total resisting force (N): drag + rolling + grade + cornering, signed positive when opposing motion."""
    mass_kg = config.MASS_TOTAL_KG if mass_kg is None else mass_kg
    return (
        drag_force_n(v_kmh, scenario, track_heading_deg)
        + rolling_resistance_n(grade_pct, mass_kg)
        + grade_force_n(grade_pct, mass_kg)
        + cornering_drag_n(v_kmh, r_min_m, mass_kg)
    )

