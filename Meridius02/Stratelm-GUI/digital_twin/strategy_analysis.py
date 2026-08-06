"""
Shared post-processing for the driving-strategy notebooks (fuzzy_analyze.ipynb,
mpc_analyze.ipynb). Takes a raw telemetry frame from simulate()/mpc.run_closed_loop()
and enriches it with the columns the driver-facing charts need:

  * drive_phase       -- gas / glide / brake, derived from motor_state
  * x_m, y_m          -- local flat-earth track projection (metres) for the map heatmaps
  * lap_distance_km   -- distance around ONE lap (for per-lap overlays)
  * stop_label        -- which mandatory stop-and-go a flagged row belongs to
  * gas_glide_num     -- numeric encoding (0 glide / 1 gas / 2 brake) for heatmap colouring

Physics is never touched here -- this is presentation prep only, kept out of the
notebooks so their cells stay about the *charts*, not bookkeeping.
"""

import numpy as np
import pandas as pd

from . import config

# Authoritative event coordinates (deg lat/lon), from the SEM Lusail track survey.
START_FINISH_LATLON = (25.48842018, 51.45017025)
STOP_AND_GO_LATLON = {
    "stop-and-go 1": (25.488390, 51.450116),   # ~6 m from start/finish (Art. 227 stop 1)
    "stop-and-go 2": (25.491948, 51.450453),   # far side of the lap (Art. 227 stop 2)
}

# gas = motor powering, glide = coasting motor-off, brake = decelerating under braking
PHASE_FROM_MOTOR_STATE = {"accel": "gas", "cruise": "glide", "brake": "brake"}
PHASE_COLORS = {"gas": "#1a9e4b", "glide": "#eda100", "brake": "#e34948"}
PHASE_NUM = {"glide": 0, "gas": 1, "brake": 2}
MOTOR_COLORS = {config.ACCEL_MOTOR_NAME: "#eb6834", config.CRUISE_MOTOR_NAME: "#2a78d6"}
MOTOR_ROLE = {config.ACCEL_MOTOR_NAME: "acceleration motor",
              config.CRUISE_MOTOR_NAME: "cruise motor"}


def latlon_to_xy(lat, lon, lat0, lon0):
    """Local equirectangular projection (metres east/north of the reference point)."""
    x = (np.asarray(lon) - lon0) * np.cos(np.radians(lat0)) * 111320.0
    y = (np.asarray(lat) - lat0) * 111132.0
    return x, y


def enrich(tel: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of `tel` with the driver-facing analysis columns added."""
    df = tel.copy()
    df["drive_phase"] = df["motor_state"].map(PHASE_FROM_MOTOR_STATE).fillna("glide")
    df["gas_glide_num"] = df["drive_phase"].map(PHASE_NUM)

    lat0, lon0 = df["latitude"].mean(), df["longitude"].mean()
    df["x_m"], df["y_m"] = latlon_to_xy(df["latitude"], df["longitude"], lat0, lon0)

    lap_len_km = df["distance_km"].iloc[-1] / df["lap"].nunique()
    df["lap_distance_km"] = df["distance_km"] - (df["lap"] - 1) * lap_len_km

    # label each flagged stop row by which mandatory stop-and-go it is (nearest of the two)
    df["stop_label"] = None
    if "stop_event" in df:
        for label, (slat, slon) in STOP_AND_GO_LATLON.items():
            sx, sy = latlon_to_xy(slat, slon, lat0, lon0)
            flagged = df.index[df["stop_event"]]
            for idx in flagged:
                d = np.hypot(df.at[idx, "x_m"] - sx, df.at[idx, "y_m"] - sy)
                if d < 40.0:
                    df.at[idx, "stop_label"] = label
    return df


def event_xy(df: pd.DataFrame):
    """Project the fixed start/finish + two stop-and-go coordinates into df's xy frame."""
    lat0, lon0 = df["latitude"].mean(), df["longitude"].mean()
    out = {"start_finish": latlon_to_xy(*START_FINISH_LATLON, lat0, lon0)}
    for label, (slat, slon) in STOP_AND_GO_LATLON.items():
        out[label] = latlon_to_xy(slat, slon, lat0, lon0)
    return out


def summary(tel: pd.DataFrame, label: str = "") -> dict:
    """Headline strategy numbers for the report tables/cards."""
    from . import telemetry as telemetry_mod
    dist_km = tel["s_m"].iloc[-1] / 1000.0
    # SEM Art. 56c(iii): any supercap recharge time is added to the recorded run time.
    recharge_s = float(tel["supercap_recharge_s"].iloc[0]) if "supercap_recharge_s" in tel.columns else 0.0
    time_s = tel["t_s"].iloc[-1] + recharge_s
    h2_m3 = tel["h2_cumulative_m3"].iloc[-1]
    acc_j = tel["accessory_energy_cumulative_j"].iloc[-1]
    score = telemetry_mod.h2_score_km_per_m3(dist_km, h2_m3, accessory_energy_j=acc_j)
    ph = tel["motor_state"].map(PHASE_FROM_MOTOR_STATE)
    return {
        "strategy": label,
        "distance_km": round(dist_km, 3),
        "time_min": round(time_s / 60.0, 2),
        "avg_speed_kmh": round(dist_km / (time_s / 3600.0), 2),
        "h2_litres": round(h2_m3 * 1000.0, 2),
        "score_km_per_m3": round(score, 1),
        "gas_pct": round((ph == "gas").mean() * 100, 1),
        "glide_pct": round((ph == "glide").mean() * 100, 1),
        "brake_pct": round((ph == "brake").mean() * 100, 1),
        "accel_motor_pct": round((tel["active_motor"] == config.ACCEL_MOTOR_NAME).mean() * 100, 1),
        "cruise_motor_pct": round((tel["active_motor"] == config.CRUISE_MOTOR_NAME).mean() * 100, 1),
        "time_ok": bool(time_s <= config.MAX_ATTEMPT_TIME_MIN * 60.0),
        "rule_violations": int(tel["rule_violation"].sum()),
    }
