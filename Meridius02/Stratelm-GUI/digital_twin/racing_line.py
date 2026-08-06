"""Energy-optimal DRIVING line (not a lap-time racing line) for the SEM APME
Lusail urban track.

Objective choice (locked decision + why): at SEM speeds (25-50 km/h) the
dominant losses -- rolling resistance and aero -- are both proportional to
DISTANCE TRAVELLED, not time. So the energy-optimal line is (to first order)
the SHORTEST path inside the drivable corridor, NOT the classic minimum-
curvature racing line (which lengthens the path to keep speed up -- the wrong
trade here). This is the same formulation as `opt_shortest_path` in the TUM
global race trajectory optimizer (Downloads/Raceline-Optimization clone),
re-implemented here because (a) that repo needs quadprog, we only have scipy,
and (b) we add a curvature regularizer so the line doesn't kink at apexes
(a kink costs cornering scrub via config.CORNERING_SCRUB_COEFF and lowers
v_safe locally).

Formulation: lateral offset alpha_i along the left unit normal of the
imagery-digitized centerline (data/track_edges_imagery.csv, closed loop,
~5 m stations). Path point p_i = c_i + alpha_i * n_i.

  minimize   sum_i |p_{i+1} - p_i|^2  +  LAMBDA_CURV * sum_i |p_{i-1} - 2 p_i + p_{i+1}|^2
  subject to -(w_right_i - margin) <= alpha_i <= (w_left_i - margin)

Both terms are linear in alpha -> bounded sparse linear least squares
(scipy.optimize.lsq_linear). Indices wrap around (closed loop).

The sum-of-squared-segment-lengths objective is the standard quadratic
surrogate for path length used by TUM's shortest-path option (exact for
uniform spacing up to a constant factor).

Run:  python -m digital_twin.racing_line
"""

import math

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.optimize import lsq_linear

from . import config
from . import track

EDGES_CSV = "data/track_edges_imagery.csv"
OUTPUT_CSV = "data/racing_line.csv"

# Edge clearance: half vehicle width + safety margin to the measured edge.
SAFETY_MARGIN_M = 0.40   # PLACEHOLDER driver-skill margin; widths themselves are conservative
CLEARANCE_M = config.VEHICLE_WIDTH_M / 2.0 + SAFETY_MARGIN_M

# Curvature regularizer weight. 0 = pure shortest path (kinks at apexes).
# Chosen so the second-difference term is a gentle penalty: it trades <1 m of
# extra length for keeping min radius comfortably above the vehicle's 6 m
# turning-radius floor (Art. 47) -- see __main__ sweep printout.
#
# Benchmark (2026-07-25, WIDTH_QA_MAX_M=13m corridor, Lusail SEM route):
#   lambda=  0 (pure shortest): length=3622.0 m, R_min= 11.0 m (Turn 10, s=2566 m)
#   lambda=300 (our default)  : length=3625.5 m, R_min= 33.9 m (Turn 10, s=2569 m)
#   Centerline (no QP)        : length=3682.5 m, R_min=  3.0 m (GPS noise artefact)
# Cost of smoothing: +3.5 m/lap (x4 laps = +14 m total) for R_min 11→33.9 m.
# V_safe @ R_min: lambda=0 → 34.6 km/h; lambda=300 → 60.5 km/h (well above 25-30 km/h cruise).
LAMBDA_CURV = 300.0

MIN_CORRIDOR_HALF_M = 0.30  # never let bounds cross even if corridor < vehicle width


def _local_xy(lat, lon, lat0, lon0):
    mlat = 111132.954 - 559.822 * math.cos(2 * math.radians(lat0))
    mlon = 111412.84 * math.cos(math.radians(lat0))
    return (np.asarray(lon) - lon0) * mlon, (np.asarray(lat) - lat0) * mlat, mlat, mlon


def load_reference(path: str = EDGES_CSV):
    """Centerline + normals + lateral bounds from the imagery edge dataset."""
    d = pd.read_csv(path)
    # Same field-verified QA clamp track.join_track_widths() applies to the
    # simulator's per-point profile (see track.apply_width_qa_clamp) -- without
    # it the QP would think it has up to 26.9 m of room at the km 1.47 apron
    # merge and place the line somewhere the corridor doesn't actually allow.
    d = track.apply_width_qa_clamp(d)
    lat0, lon0 = float(d.lat.mean()), float(d.lon.mean())
    x, y, mlat, mlon = _local_xy(d.lat, d.lon, lat0, lon0)

    # closed-loop tangents via centered differences with wraparound
    xp = np.concatenate([[x[-1]], x, [x[0]]])
    yp = np.concatenate([[y[-1]], y, [y[0]]])
    tx = xp[2:] - xp[:-2]
    ty = yp[2:] - yp[:-2]
    norm = np.hypot(tx, ty)
    tx, ty = tx / norm, ty / norm
    nx, ny = -ty, tx  # left of travel

    lo = -(d.w_right_m.to_numpy() - CLEARANCE_M)
    hi = d.w_left_m.to_numpy() - CLEARANCE_M
    # degenerate stations (corridor narrower than clearance): pin to centerline
    bad = lo > hi - 2 * MIN_CORRIDOR_HALF_M
    center = (lo + hi) / 2.0
    lo[bad] = center[bad] - MIN_CORRIDOR_HALF_M
    hi[bad] = center[bad] + MIN_CORRIDOR_HALF_M

    return {
        "df": d, "x": x, "y": y, "nx": nx, "ny": ny, "lo": lo, "hi": hi,
        "lat0": lat0, "lon0": lon0, "mlat": mlat, "mlon": mlon,
    }


def _spacing(ref):
    """Reference segment lengths ds_i = |c_{i+1} - c_i| with wraparound.
    The seam segment (last -> first station) is ~2-3x a normal 5 m step; all
    operators must be spacing-aware or the seam gets over-weighted (a plain
    sum-of-squares objective slams both seam ends laterally -> fake 3 m kink)."""
    x, y = ref["x"], ref["y"]
    dx = np.roll(x, -1) - x
    dy = np.roll(y, -1) - y
    return np.hypot(dx, dy)


def _d1_weighted(n, ds):
    """Rows r_i = (p_{i+1} - p_i)/sqrt(ds_i): sum of squares = sum |dp|^2/ds
    (chord-length energy -- the proper quadratic surrogate for path LENGTH
    under non-uniform spacing)."""
    w = 1.0 / np.sqrt(ds)
    rows, cols, vals = [], [], []
    for i in range(n):
        rows += [i, i]
        cols += [i, (i + 1) % n]
        vals += [-w[i], w[i]]
    return sparse.csr_matrix((vals, (rows, cols)), shape=(n, n))


def _d2_weighted(n, ds):
    """Second divided difference (curvature vector estimate) with wraparound,
    row-weighted by sqrt of the local arc window so the sum approximates the
    integral of |kappa|^2 ds."""
    rows, cols, vals = [], [], []
    for i in range(n):
        ds_prev = ds[(i - 1) % n]
        ds_next = ds[i]
        h = 0.5 * (ds_prev + ds_next)
        c_prev = 2.0 / (ds_prev * (ds_prev + ds_next))
        c_mid = -2.0 / (ds_prev * ds_next)
        c_next = 2.0 / (ds_next * (ds_prev + ds_next))
        w = math.sqrt(h)
        rows += [i, i, i]
        cols += [(i - 1) % n, i, (i + 1) % n]
        vals += [w * c_prev, w * c_mid, w * c_next]
    return sparse.csr_matrix((vals, (rows, cols)), shape=(n, n))


def solve_driving_line(ref, lambda_curv: float = LAMBDA_CURV):
    """Bounded sparse least squares for the lateral offsets alpha."""
    x, y, nx, ny = ref["x"], ref["y"], ref["nx"], ref["ny"]
    n = len(x)
    ds = _spacing(ref)
    D1 = _d1_weighted(n, ds)
    D2 = _d2_weighted(n, ds)
    Nx = sparse.diags(nx)
    Ny = sparse.diags(ny)

    blocks = [D1 @ Nx, D1 @ Ny]
    rhs = [-(D1 @ x), -(D1 @ y)]
    if lambda_curv > 0:
        w = math.sqrt(lambda_curv)
        blocks += [w * (D2 @ Nx), w * (D2 @ Ny)]
        rhs += [-w * (D2 @ x), -w * (D2 @ y)]

    A = sparse.vstack(blocks, format="csr")
    b = np.concatenate(rhs)
    res = lsq_linear(A, b, bounds=(ref["lo"], ref["hi"]),
                     method="trf", tol=1e-10, max_iter=300, verbose=0)
    return res.x


def path_metrics(x, y):
    """Closed-loop length, per-point curvature radius (3-point circumradius)."""
    dx = np.diff(np.concatenate([x, [x[0]]]))
    dy = np.diff(np.concatenate([y, [y[0]]]))
    seg = np.hypot(dx, dy)
    length = float(seg.sum())

    xp = np.concatenate([[x[-1]], x, [x[0]]])
    yp = np.concatenate([[y[-1]], y, [y[0]]])
    ax, ay = xp[:-2], yp[:-2]
    bx, by = xp[1:-1], yp[1:-1]
    cx, cy = xp[2:], yp[2:]
    a = np.hypot(bx - ax, by - ay)
    b_ = np.hypot(cx - bx, cy - by)
    c = np.hypot(cx - ax, cy - ay)
    cross = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    with np.errstate(divide="ignore", invalid="ignore"):
        radius = np.where(np.abs(cross) > 1e-9, (a * b_ * c) / (2.0 * np.abs(cross)), np.inf)
    return length, radius, seg


def build_racing_line(save: bool = True, lambda_curv: float = LAMBDA_CURV) -> pd.DataFrame:
    ref = load_reference()
    alpha = solve_driving_line(ref, lambda_curv)

    x = ref["x"] + alpha * ref["nx"]
    y = ref["y"] + alpha * ref["ny"]
    length, radius, seg = path_metrics(x, y)
    center_len, center_radius, _ = path_metrics(ref["x"], ref["y"])

    lat = ref["lat0"] + y / ref["mlat"]
    lon = ref["lon0"] + x / ref["mlon"]
    s = np.concatenate([[0.0], np.cumsum(seg[:-1])])
    v_safe = np.sqrt(config.CORNERING_FRICTION_MU * config.GRAVITY_M_S2 *
                     np.minimum(radius, 1e6)) * 3.6

    out = pd.DataFrame({
        "s_m": s,
        "x_m": x, "y_m": y, "lat": lat, "lon": lon,
        "alpha_m": alpha,
        "radius_m": radius,
        "v_safe_kmh": v_safe,
        "station_shell_m": ref["df"].station_shell_m,
    })
    out.attrs["length_m"] = length
    out.attrs["centerline_length_m"] = center_len
    if save:
        out.to_csv(OUTPUT_CSV, index=False)
    return out


# ---------------------------------------------------------------------------
# Live driving-line advisory: signed lateral deviation of the car's ACTUAL
# GPS fix from this racing line, for Stratelm-GUI's driver_advisory_bridge.
# Separate from the DP/gas-glide speed advisory (driver_advisory.py) -- this
# one is about STEERING, not throttle/brake, and needs a real lat/lon fix
# (the flat constant-cruise sim has no lateral freedom at all -- it drives
# the fixed Shell GPS backbone exactly, see track.build_track_profile() --
# so this number is only meaningful with a live/simulated GPS topic feeding
# real latitude/longitude).
# ---------------------------------------------------------------------------
LOOKAHEAD_M_DEFAULT = 10.0

_lookup_cache: dict = {}


def _lookup_for(racing_line_csv: str = None):
    """(s_ext, lat_ext, lon_ext, lap_len_m) with one extra point appended that
    wraps back to the start -- lets interpolation across the loop seam (e.g.
    querying s=3624 -> lookahead lands at s=2, past the last real row) work
    with a plain np.interp-style search instead of special-casing the wrap."""
    path = racing_line_csv or OUTPUT_CSV
    cached = _lookup_cache.get(path)
    if cached is not None:
        return cached

    df = pd.read_csv(path)
    s = df["s_m"].to_numpy()
    lat = df["lat"].to_numpy()
    lon = df["lon"].to_numpy()

    lat_mid = (lat[-1] + lat[0]) / 2.0
    mlat = 111132.954 - 559.822 * math.cos(2 * math.radians(lat_mid))
    mlon = 111412.84 * math.cos(math.radians(lat_mid))
    close_len = math.hypot((lon[0] - lon[-1]) * mlon, (lat[0] - lat[-1]) * mlat)
    lap_len_m = float(s[-1]) + close_len

    s_ext = np.concatenate([s, [lap_len_m]])
    lat_ext = np.concatenate([lat, [lat[0]]])
    lon_ext = np.concatenate([lon, [lon[0]]])

    result = (s_ext, lat_ext, lon_ext, lap_len_m)
    _lookup_cache[path] = result
    return result


def lateral_deviation_m(car_lat: float, car_lon: float, s_now_m: float,
                         lookahead_m: float = LOOKAHEAD_M_DEFAULT,
                         racing_line_csv: str = None) -> float:
    """Signed lateral deviation (meters) of the car's actual GPS position from
    this racing line, evaluated `lookahead_m` AHEAD of the car's own arc-length
    position rather than at the car's position itself -- a live number telling
    the driver where they'll need to be, not where they already are, so it's
    still valid by the time the driver reacts and steers (same lookahead idea
    as driver_advisory_bridge.LOOKAHEAD_S for the speed advisory).

    Sign convention:
    0.00 = exactly on the line; positive (+) = steer LEFT; negative (-) =
    steer RIGHT. s_now_m is the car's raw cumulative distance (wraps on its
    own against this line's lap length, independent of any other module's
    attempt-length wrapping)."""
    s_ext, lat_ext, lon_ext, lap_len_m = _lookup_for(racing_line_csv)

    s_look = (s_now_m % lap_len_m + lookahead_m) % lap_len_m
    i = int(np.clip(np.searchsorted(s_ext, s_look) - 1, 0, len(s_ext) - 2))
    s0, s1 = s_ext[i], s_ext[i + 1]
    t = 0.0 if s1 == s0 else (s_look - s0) / (s1 - s0)
    look_lat = lat_ext[i] + t * (lat_ext[i + 1] - lat_ext[i])
    look_lon = lon_ext[i] + t * (lon_ext[i + 1] - lon_ext[i])

    mlat = 111132.954 - 559.822 * math.cos(2 * math.radians(look_lat))
    mlon = 111412.84 * math.cos(math.radians(look_lat))

    tx = (lon_ext[i + 1] - lon_ext[i]) * mlon
    ty = (lat_ext[i + 1] - lat_ext[i]) * mlat
    tnorm = math.hypot(tx, ty)
    if tnorm < 1e-9:
        return 0.0
    tx, ty = tx / tnorm, ty / tnorm
    nx, ny = -ty, tx  # left of travel -- same convention as build_racing_line's alpha offset

    dx = (car_lon - look_lon) * mlon
    dy = (car_lat - look_lat) * mlat
    return dx * nx + dy * ny


if __name__ == "__main__":
    ref = load_reference()
    center_len, center_radius, _ = path_metrics(ref["x"], ref["y"])
    print(f"clearance to measured edge: {CLEARANCE_M:.2f} m "
          f"(half width {config.VEHICLE_WIDTH_M/2:.2f} + margin {SAFETY_MARGIN_M:.2f})")
    print(f"centerline loop length: {center_len:.1f} m | min radius {np.nanmin(center_radius):.1f} m")
    print()
    print(f"{'lambda':>8} {'length_m':>9} {'saved_m':>8} {'minR_m':>7} {'minVsafe':>9}")
    for lam in (0.0, 30.0, 100.0, 300.0, 1000.0, 3000.0):
        alpha = solve_driving_line(ref, lam)
        x = ref["x"] + alpha * ref["nx"]
        y = ref["y"] + alpha * ref["ny"]
        L, R, _ = path_metrics(x, y)
        vmin = math.sqrt(config.CORNERING_FRICTION_MU * config.GRAVITY_M_S2 * np.nanmin(R)) * 3.6
        print(f"{lam:>8.0f} {L:>9.1f} {center_len - L:>8.1f} {np.nanmin(R):>7.1f} {vmin:>8.1f}")
    print()
    line = build_racing_line(save=True)
    print(f"wrote {OUTPUT_CSV}: {len(line)} points, length {line.attrs['length_m']:.1f} m "
          f"(saves {line.attrs['centerline_length_m'] - line.attrs['length_m']:.1f} m/lap vs centerline, "
          f"x4 laps = {4*(line.attrs['centerline_length_m'] - line.attrs['length_m']):.0f} m)")
    print(f"min radius on line: {np.nanmin(line.radius_m):.1f} m (vehicle floor 6 m, Art. 47)")
    print(f"min v_safe on line: {line.v_safe_kmh.min():.1f} km/h")
