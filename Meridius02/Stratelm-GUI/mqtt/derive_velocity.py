"""
derive_velocity.py — reconstruct velocity from the cumulative Distance column.

The wheel distance counter (1.57 m per revolution) kept working even when the
velocity sensor read 0 for long stretches (attempt 01). Speed is therefore
recoverable as the slope of Distance over a short time window:

    v(t) = [D(t + W/2) - D(t - W/2)] / W * 3.6      (km/h)

W defaults to 6 s: at 25 km/h that window spans ~27 wheel ticks of 1.57 m,
so the estimate resolves ~0.9 km/h. A smaller window reacts faster but gets
noisier, because Distance only moves in 1.57 m steps.

Honesty rules (GIGO, same as clean_telemetry.py):
  - the original sensor column is preserved untouched as `velocity_raw`
  - `Velocity` is replaced by the derived value ONLY where the sensor reads 0
    while Distance is demonstrably advancing (the dead-sensor case)
  - real stops stay 0 (Distance flat -> derived ~0 -> nothing to invent)
  - `velocity_source` marks every row: sensor | derived | stopped

Usage:
    python derive_velocity.py <cleaned_or_laps.csv> [-o out.csv] [--window 6]
    (default output: <name>_velfix.csv next to the input)
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd

MOVING_MIN_KMH = 1.0   # derived speed above this while sensor=0 => dead sensor


def find_col(df, *names):
    low = {c.lower(): c for c in df.columns}
    for n in names:
        if n.lower() in low:
            return low[n.lower()]
    return None


def derive(df, window):
    tcol = find_col(df, "elapsed_s", "timeS", "Time(s)")
    dcol = find_col(df, "Distance", "distance")
    vcol = find_col(df, "Velocity", "velocity")
    if tcol is None or dcol is None or vcol is None:
        sys.exit(f"need time/distance/velocity columns, found: {list(df.columns)}")

    t = pd.to_numeric(df[tcol], errors="coerce").to_numpy(dtype=float)
    d = pd.to_numeric(df[dcol], errors="coerce").to_numpy(dtype=float)

    # one (time, distance) sample per unique second: max distance seen, then
    # cummax so packet reordering can never make the odometer run backwards
    ok = ~(np.isnan(t) | np.isnan(d))
    tu, inv = np.unique(t[ok], return_inverse=True)
    du = np.zeros_like(tu)
    np.maximum.at(du, inv, d[ok])
    du = np.maximum.accumulate(du)

    # centered slope of the odometer, window clipped at the session edges
    lo = np.clip(t - window / 2.0, tu[0], tu[-1])
    hi = np.clip(t + window / 2.0, tu[0], tu[-1])
    span = hi - lo
    span[span <= 0] = np.nan
    v_est = (np.interp(hi, tu, du) - np.interp(lo, tu, du)) / span * 3.6

    raw = pd.to_numeric(df[vcol], errors="coerce").to_numpy(dtype=float)
    dead = (raw == 0) & (v_est >= MOVING_MIN_KMH)

    out = df.copy()
    out["velocity_raw"] = df[vcol]
    out["velocity_derived_kmh"] = np.round(v_est, 2)
    fixed = raw.copy()
    fixed[dead] = np.round(v_est[dead], 2)
    out[vcol] = fixed
    src = np.where(dead, "derived", np.where(raw > 0, "sensor", "stopped"))
    out["velocity_source"] = src
    return out, int(dead.sum()), int((raw == 0).sum())


def main():
    ap = argparse.ArgumentParser(description="recover 0-velocity rows from Distance")
    ap.add_argument("csv")
    ap.add_argument("-o", "--out", help="output CSV (default: <name>_velfix.csv)")
    ap.add_argument("--window", type=float, default=6.0,
                    help="slope window in seconds (default 6)")
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    out, n_fixed, n_zero = derive(df, args.window)

    dest = args.out or os.path.splitext(args.csv)[0] + "_velfix.csv"
    out.to_csv(dest, index=False)
    kept = n_zero - n_fixed
    print(f"rows              : {len(out)}")
    print(f"zero-velocity rows: {n_zero}")
    print(f"  recovered       : {n_fixed} (sensor dead while Distance advanced)")
    print(f"  left at 0       : {kept} (car genuinely stopped/idle)")
    print(f"wrote {dest}")


if __name__ == "__main__":
    main()
