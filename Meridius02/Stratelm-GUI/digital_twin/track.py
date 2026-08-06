"""
Unified per-point track profile: joins the raw GPS/elevation backbone
(data/sem_apme_2025-track_coordinates.csv) with the already-computed per-turn
curvature table (data/turns.csv, extracted from data/track_analysis_final.csv)
into one DataFrame indexed by distance, with heading and stop-location flags
added -- this is the gap identified in the plan: track_analysis_final.csv is a
hand-transcribed summary (per-turn rows + two headline grade extremes), not a
per-point table usable by a forward simulator.

Grade here is a simplified centered-difference-over-window estimate, not the
notebook's bootstrap/spline methodology -- it exists to give the vehicle
dynamics model a continuous per-point grade signal, not to re-derive the two
headline max-grade figures (those two remain the authoritative reference
values from the Track_Analysis notebook; this profile is for simulation use).
"""

import math

import numpy as np
import pandas as pd

from . import config

COORDINATES_CSV = "data/sem_apme_2025-track_coordinates.csv"
TURNS_CSV = "data/turns.csv"
EDGES_CSV = "data/track_edges_imagery.csv"
OUTPUT_CSV = "data/track_profile_1m.csv"
RACING_LINE_CSV = "data/racing_line.csv"
RACING_LINE_OUTPUT_CSV = "data/track_profile_racing_line.csv"

GRADE_WINDOW_M = 20.0  # centered finite-difference half-window for grade smoothing
ALTITUDE_SMOOTH_WINDOW_M = 50.0  # half-window for the light altitude pre-smoothing (see _smooth_altitude):
                                  # de-noises the 0.1 m GPS staircase without flattening real slopes.
                                  # 0.0 disables it (raw behaviour). Tuned on the Losail trace 2026-07-21.


def load_raw_coordinates(path: str = COORDINATES_CSV) -> pd.DataFrame:
    df = pd.read_csv(path, sep="\t")
    df = df.rename(columns={"altitude (m)": "altitude_m", "distance (km)": "distance_km"})
    df["distance_m"] = df["distance_km"] * 1000.0
    return df


def load_turns(path: str = TURNS_CSV) -> pd.DataFrame:
    return pd.read_csv(path)


def compute_heading_deg(df: pd.DataFrame) -> np.ndarray:
    """Forward compass bearing (deg, clockwise from North) from each point to the next."""
    lat = np.radians(df["latitude"].to_numpy())
    lon = np.radians(df["longitude"].to_numpy())
    lat1, lat2 = lat[:-1], lat[1:]
    lon1, lon2 = lon[:-1], lon[1:]
    dlon = lon2 - lon1
    y = np.sin(dlon) * np.cos(lat2)
    x = np.cos(lat1) * np.sin(lat2) - np.sin(lat1) * np.cos(lat2) * np.cos(dlon)
    bearing = (np.degrees(np.arctan2(y, x)) + 360.0) % 360.0
    # last point has no "next" point -- repeat the final computed heading
    return np.append(bearing, bearing[-1])


def _smooth_altitude(z: np.ndarray, half_window_m: float) -> np.ndarray:
    """Centered moving average over +-half_window_m (profile points are ~1 m apart) to
    strip the altitude column's 0.1 m quantization staircase BEFORE differentiating for
    grade. Deliberately LIGHT (not a flatten): it removes sub-window jitter and dampens
    the sharpest GPS-drift ramps, while preserving real elevation trends. Edge-padded so
    the loop's start/finish (same physical point) stay consistent."""
    if half_window_m <= 0:
        return z
    k = max(1, int(round(half_window_m)))
    kernel = np.ones(2 * k + 1) / (2 * k + 1)
    return np.convolve(np.pad(z, k, mode="edge"), kernel, mode="valid")


def compute_grade_pct(df: pd.DataFrame, window_m: float = GRADE_WINDOW_M,
                      altitude_smooth_window_m: float = ALTITUDE_SMOOTH_WINDOW_M) -> np.ndarray:
    """Centered finite-difference grade estimate (%). The altitude is first lightly
    smoothed (see _smooth_altitude) to remove the 0.1 m rounding staircase, then the
    grade is taken over +-window_m. Two stages: smoothing kills quantization jitter,
    the window keeps the finite-difference itself stable."""
    s = df["distance_m"].to_numpy()
    z = _smooth_altitude(df["altitude_m"].to_numpy(), altitude_smooth_window_m)
    n = len(s)
    grade = np.zeros(n)
    lo_idx = np.searchsorted(s, s - window_m)
    hi_idx = np.searchsorted(s, s + window_m)
    hi_idx = np.clip(hi_idx, 0, n - 1)
    for i in range(n):
        lo, hi = lo_idx[i], hi_idx[i]
        if hi <= lo:
            grade[i] = 0.0
            continue
        ds = s[hi] - s[lo]
        dz = z[hi] - z[lo]
        grade[i] = (dz / ds) * 100.0 if ds > 0 else 0.0
    return grade


def assign_turn_zones(df: pd.DataFrame, turns: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["zone_type"] = "straight"
    df["zone_id"] = -1
    df["r_min_m"] = math.inf
    df["v_safe_kmh"] = math.inf
    for _, turn in turns.iterrows():
        mask = df["distance_km"].between(turn["dist_start_km"], turn["dist_end_km"])
        df.loc[mask, "zone_type"] = "turn"
        df.loc[mask, "zone_id"] = int(turn["turn_no"])
        df.loc[mask, "r_min_m"] = turn["r_min_m"]
        df.loc[mask, "v_safe_kmh"] = turn["v_safe_kmh"]
    return df


# QA correction for the Lusail corridor specifically (field-verified, see
# notebooks/Track_Analysis.ipynb Bagian 7): the raw per-point satellite
# digitization occasionally over-/under-detects the drivable edge -- e.g. it
# sees the F1 apron pavement around station 1470 m as drivable out to 26.9 m,
# when the team's own ground-truth walk says this corridor is a uniform
# 11-13 m the whole way round. Applied proportionally (scales w_left_m/
# w_right_m together) so centerline_shift_m -- and therefore which side of the
# Shell GPS line the corridor sits on -- is preserved, not just truncated.
# A future track digitized from scratch would need its own bounds here.
WIDTH_QA_MIN_M = 11.0
WIDTH_QA_MAX_M = 13.0


def apply_width_qa_clamp(df: pd.DataFrame, w_min: float = WIDTH_QA_MIN_M,
                          w_max: float = WIDTH_QA_MAX_M) -> pd.DataFrame:
    df = df.copy()
    hi = df["width_m"] > w_max
    sc_hi = w_max / df.loc[hi, "width_m"]
    df.loc[hi, "w_left_m"] *= sc_hi
    df.loc[hi, "w_right_m"] *= sc_hi
    df.loc[hi, "width_m"] = w_max

    lo = df["width_m"] < w_min
    sc_lo = w_min / df.loc[lo, "width_m"]
    df.loc[lo, "w_left_m"] *= sc_lo
    df.loc[lo, "w_right_m"] *= sc_lo
    df.loc[lo, "width_m"] = w_min
    return df


def join_track_widths(df: pd.DataFrame, path: str = EDGES_CSV) -> pd.DataFrame:
    """Attach per-point drivable width from the satellite-imagery digitization
    (2026-07, Esri World Imagery z19 ~0.27 m/px; asphalt-edge detection at 5 m
    stations, visually QA'd section-by-section with manual overrides -- see
    scripts/track_width_digitization/), then apply the QA clamp above.
    Joined by nearest lat/lon because the edge dataset's rebuilt centerline
    (edge midpoint) has its own arc length; width_m / w_left_m / w_right_m are
    measured across the drivable corridor, and centerline_shift_m says how far
    the true corridor midline sits LEFT of the Shell GPS line at that point
    (median ~4 m -- the Shell trace hugs one edge in places and cuts two
    corners)."""
    edges = pd.read_csv(path)
    lat0 = df["latitude"].mean()
    mlat = 111132.954 - 559.822 * math.cos(2 * math.radians(lat0))
    mlon = 111412.84 * math.cos(math.radians(lat0))
    ex = (edges["lon"].to_numpy() - df["longitude"].mean()) * mlon
    ey = (edges["lat"].to_numpy() - lat0) * mlat
    px = (df["longitude"].to_numpy() - df["longitude"].mean()) * mlon
    py = (df["latitude"].to_numpy() - lat0) * mlat
    from scipy.spatial import cKDTree
    idx = cKDTree(np.c_[ex, ey]).query(np.c_[px, py])[1]
    df = df.copy()
    for col in ("width_m", "w_left_m", "w_right_m", "centerline_shift_m"):
        df[col] = edges[col].to_numpy()[idx]
    return apply_width_qa_clamp(df)


def assign_stop_flags(df: pd.DataFrame, stop_locations_km) -> pd.DataFrame:
    df = df.copy()
    df["stop_event"] = False
    for stop_km in stop_locations_km:
        idx = (df["distance_km"] - stop_km).abs().idxmin()
        df.loc[idx, "stop_event"] = True
    return df


def build_track_profile(save: bool = True, coordinates_csv: str = None, turns_csv: str = None,
                         edges_csv: str = None, stop_locations_km=None) -> pd.DataFrame:
    """Builds the per-point profile for one track. Defaults to the module-level
    CSV constants (the original Lusail 2027 track) so every existing caller
    (simulate.py, optimize_*.py) keeps working unchanged; the Stratelm-GUI
    backend passes a selected track's own CSV paths instead, for multi-track
    support (see Stratelm-GUI/backend/registry.py)."""
    df = load_raw_coordinates(coordinates_csv or COORDINATES_CSV)
    turns = load_turns(turns_csv or TURNS_CSV)

    df["heading_deg"] = compute_heading_deg(df)
    df["grade_pct"] = compute_grade_pct(df)
    df = assign_turn_zones(df, turns)
    df = join_track_widths(df, edges_csv or EDGES_CSV)
    df = assign_stop_flags(df, stop_locations_km if stop_locations_km is not None else config.STOP_LOCATIONS_KM)

    df = df[[
        "Id", "latitude", "longitude", "altitude_m", "distance_km", "distance_m",
        "heading_deg", "grade_pct", "zone_type", "zone_id", "r_min_m", "v_safe_kmh", "stop_event",
        "width_m", "w_left_m", "w_right_m", "centerline_shift_m",
    ]]

    if save:
        df.to_csv(OUTPUT_CSV, index=False)
    return df


def build_racing_line_profile(save: bool = True, racing_line_csv: str = None,
                               coordinates_csv: str = None, stop_locations_km=None) -> pd.DataFrame:
    """Per-point profile built on the QP shortest-path racing line (racing_line.py's
    output) instead of the raw Shell GPS backbone -- same column schema consumed by
    simulate.py/optimize_*.py (distance_km/distance_m/heading_deg/grade_pct/r_min_m/
    v_safe_kmh/stop_event), so it's a drop-in replacement for build_track_profile()
    at those call sites.

    Two different distance axes are involved and must not be confused: the racing
    line's own arc length `s_m` (shorter than the backbone -- this IS the point, it's
    what saves distance) drives distance_km/distance_m here, while `station_shell_m`
    (the racing line's position expressed in the ORIGINAL backbone's arc length,
    carried over from track_edges_imagery.csv) is only used to look up altitude,
    since the QP solve only optimizes lateral offset and has no elevation of its own.
    Heading is recomputed from the racing line's own lat/lon (not copied from the
    backbone) because the car's true heading through a corner differs slightly once
    it's cutting the apex instead of following the backbone line. r_min_m/v_safe_kmh
    come straight from racing_line.csv's continuous per-point curvature (radius_m),
    replacing the old per-turn-zone constant from turns.csv with the actual radius
    at each point of the real driving line.
    """
    line = pd.read_csv(racing_line_csv or RACING_LINE_CSV)
    raw = load_raw_coordinates(coordinates_csv or COORDINATES_CSV)

    df = pd.DataFrame({
        "latitude": line["lat"],
        "longitude": line["lon"],
        "distance_m": line["s_m"],
        "distance_km": line["s_m"] / 1000.0,
        "r_min_m": line["radius_m"],
        "v_safe_kmh": line["v_safe_kmh"],
    })
    df["altitude_m"] = np.interp(line["station_shell_m"], raw["distance_m"], raw["altitude_m"])
    df["heading_deg"] = compute_heading_deg(df)
    df["grade_pct"] = compute_grade_pct(df)
    df = assign_stop_flags(df, stop_locations_km if stop_locations_km is not None else config.STOP_LOCATIONS_KM)

    if save:
        df.to_csv(RACING_LINE_OUTPUT_CSV, index=False)
    return df


if __name__ == "__main__":
    profile = build_track_profile()
    finite_cols = ["altitude_m", "distance_km", "heading_deg", "grade_pct"]
    print(f"Built {OUTPUT_CSV}: {len(profile)} points, "
          f"{(profile['zone_type'] == 'turn').sum()} in turn zones, "
          f"{profile['stop_event'].sum()} stop-location flags set")
    print(profile[finite_cols].describe().T[["count", "min", "max"]])
    turn_only = profile[profile["zone_type"] == "turn"]
    print(f"r_min_m min (tightest turn): {turn_only['r_min_m'].min()}")
    print(f"v_safe_kmh min (tightest turn): {turn_only['v_safe_kmh'].min()}")
