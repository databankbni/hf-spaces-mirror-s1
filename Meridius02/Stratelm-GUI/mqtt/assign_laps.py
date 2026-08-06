"""
assign_laps.py — add a lap_number column to telemetry that doesn't have one.

Made for the situation where the logger records no lap attribute but the pit
wall knows each lap's duration (stopwatch / race control). Two modes:

1. Duration mode (what you'll use tomorrow):
       python assign_laps.py cleaned.csv --durations "512,498,505,510"
   Durations are seconds per lap, in order. Race start defaults to the first
   row where the car moves (velocity > 0.5); override with
   --start "2026-07-13 08:05:00" (same format as the timestamp column).
   Rows before the start or after the last lap get lap_number = NaN.

2. GPS mode (cross-check, needs no durations):
       python assign_laps.py cleaned.csv --gps
   Estimates lap boundaries from the moments the car returns close to its
   starting coordinates, and prints the implied lap durations. Use it to
   sanity-check the stopwatch numbers before trusting them.

3. Distance mode (best when the logger records cumulative distance):
       python assign_laps.py cleaned.csv --lap-dist 1200
   --lap-dist is the track length of ONE lap in the same unit as the
   distance column (the real MCU sends meters). Lap boundaries fall exactly
   every lap-length of recorded distance — no stopwatch needed, immune to
   clock drift. Prints the implied lap durations so you can cross-check
   the pit-wall stopwatch.

Output: <name>_laps.csv with `lap_number` and `elapsed_s` added.
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd

from clean_telemetry import _find_ts_column, _norm


def find_col(df, names):
    for c in df.columns:
        if _norm(c) in names:
            return c
    return None


def race_start_index(df, vel_col):
    if vel_col is None:
        return 0
    moving = pd.to_numeric(df[vel_col], errors="coerce") > 0.5
    return int(moving.idxmax()) if moving.any() else 0


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    a = (np.sin((lat2 - lat1) / 2) ** 2
         + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2)
    return r * 2 * np.arcsin(np.sqrt(a))


def gps_lap_estimate(df, elapsed, radius_m=15.0, min_lap_s=60.0, start_lat=None, start_lon=None):
    """Times at which the car comes back near its starting point (or specified start line coords)."""
    lat_c = find_col(df, {"latitude", "lat", "gpslat"})
    lon_c = find_col(df, {"longitude", "lon", "lng", "long", "gpslon"})
    if lat_c is None or lon_c is None:
        return []
    lat = pd.to_numeric(df[lat_c], errors="coerce")
    lon = pd.to_numeric(df[lon_c], errors="coerce")
    start = elapsed.ge(0).idxmax() if elapsed.ge(0).any() else 0

    target_lat = start_lat if start_lat is not None else lat[start]
    target_lon = start_lon if start_lon is not None else lon[start]

    d = haversine_m(target_lat, target_lon, lat, lon)

    crossings = []
    inside = False
    last_t = 0.0
    for t, dist in zip(elapsed, d):
        if np.isnan(dist) or t <= 0:
            continue
        if dist < radius_m and not inside and t - last_t >= min_lap_s:
            crossings.append(t)
            last_t = t
            inside = True
        elif dist >= radius_m:
            inside = False
    return crossings


def assign_laps_to_df(df, durations=None, lap_dist=None, use_gps=False, start_lat=None, start_lon=None, start_time=None, ts_col="ts"):
    """In-memory lap assignment helper for API and web consumption."""
    df = df.copy()
    ts_name, ts_ms = _find_ts_column(df, ts_col)
    if ts_name is None:
        raise ValueError("No timestamp column found")

    vel_col = find_col(df, {"velocity", "speed", "vel", "kecepatan"})
    if start_time:
        start_ms = pd.Timestamp(start_time).to_datetime64().astype("datetime64[ns]").astype("int64") / 1e6
    else:
        idx = race_start_index(df, vel_col)
        start_ms = float(ts_ms.iloc[idx])

    elapsed = (ts_ms - start_ms) / 1000.0
    df["elapsed_s"] = elapsed.round(2)

    if use_gps or (durations is None and lap_dist is None):
        crossings = gps_lap_estimate(df, elapsed, start_lat=start_lat, start_lon=start_lon)
        if crossings:
            durations = list(np.diff([0.0] + crossings))

    if lap_dist:
        dist_col = find_col(df, {"distance", "jarak", "odometer", "odo", "cumdist", "cumdistkm", "distancem", "totaldistance"})
        if dist_col is not None:
            d = pd.to_numeric(df[dist_col], errors="coerce")
            start_idx = elapsed.ge(0).idxmax() if elapsed.ge(0).any() else 0
            rel = (d - d.loc[start_idx]).clip(lower=0)
            lap = np.floor(rel / lap_dist) + 1.0
            lap[elapsed < 0] = np.nan
            df["lap_number"] = lap
            return df

    if durations:
        boundaries = np.cumsum(durations)
        lap = np.searchsorted(boundaries, elapsed, side="right") + 1.0
        lap[(elapsed < 0) | (elapsed > boundaries[-1]) | (lap > len(durations))] = np.nan
        df["lap_number"] = lap
        return df

    # Fallback default: if GPS produced no crossings, assign lap 1 to all valid moving rows
    df["lap_number"] = np.where(elapsed >= 0, 1.0, np.nan)
    return df


def main():
    ap = argparse.ArgumentParser(description="Assign lap numbers to telemetry")
    ap.add_argument("csv", help="cleaned telemetry CSV")
    ap.add_argument("--durations", help='comma-separated lap durations in '
                                        'seconds, e.g. "512,498,505"')
    ap.add_argument("--start", help="race start timestamp (default: first "
                                    "row where the car moves)")
    ap.add_argument("--gps", action="store_true",
                    help="estimate lap durations from GPS start-line returns")
    ap.add_argument("--lap-dist", type=float,
                    help="track length of one lap (same unit as the distance "
                         "column, e.g. meters) — assign laps from cumulative "
                         "distance instead of durations")
    ap.add_argument("--ts-col", default="ts")
    ap.add_argument("-o", "--out")
    args = ap.parse_args()

    if not os.path.isfile(args.csv):
        sys.exit(f"file not found: {args.csv}")
    df = pd.read_csv(args.csv)

    ts_name, ts_ms = _find_ts_column(df, args.ts_col)
    if ts_name is None:
        sys.exit("no timestamp column found (looked for ts/timestamp/"
                 "recorded_at/datetime/...)")
    print(f"timestamp column: {ts_name}")

    vel_col = find_col(df, {"velocity", "speed", "vel", "kecepatan"})
    if args.start:
        start_ms = pd.Timestamp(args.start).to_datetime64().astype("datetime64[ns]").astype("int64") / 1e6
    else:
        idx = race_start_index(df, vel_col)
        start_ms = float(ts_ms.iloc[idx])
        print(f"race start auto-detected at row {idx} "
              f"(first movement{' of ' + vel_col if vel_col else ''})")
    elapsed = (ts_ms - start_ms) / 1000.0
    df["elapsed_s"] = elapsed.round(2)

    if args.gps:
        crossings = gps_lap_estimate(df, elapsed)
        if not crossings:
            print("no start-line returns found — is the route a closed loop?")
        else:
            print(f"\nGPS start-line crossings at t = "
                  f"{[round(c) for c in crossings]} s")
            durs = np.diff([0.0] + crossings)
            print(f"implied lap durations: {[round(d) for d in durs]} s")
            print('use them as: --durations "' +
                  ",".join(str(round(d)) for d in durs) + '"')
        if not args.durations:
            return

    if args.lap_dist:
        dist_col = find_col(df, {"distance", "jarak", "odometer", "odo",
                                 "cumdist", "cumdistkm", "distancem",
                                 "totaldistance"})
        if dist_col is None:
            sys.exit("--lap-dist needs a cumulative distance column")
        d = pd.to_numeric(df[dist_col], errors="coerce")
        start_idx = elapsed.ge(0).idxmax()
        rel = (d - d.loc[start_idx]).clip(lower=0)
        lap = np.floor(rel / args.lap_dist) + 1.0
        lap[elapsed < 0] = np.nan
        df["lap_number"] = lap

        print(f"\ndistance column: {dist_col}, lap length {args.lap_dist:g}")
        implied = []
        for i in sorted(df["lap_number"].dropna().unique()):
            g = elapsed[df["lap_number"] == i]
            n = int((df["lap_number"] == i).sum())
            dur = float(g.max() - g.min())
            implied.append(dur)
            print(f"  lap {int(i)}: {dur:.0f} s, {n} rows")
        if implied:
            print('implied durations (cross-check the stopwatch): "' +
                  ",".join(str(round(x)) for x in implied) + '"')
        last = df["lap_number"].dropna()
        if len(last):
            last_id = last.max()
            last_dist = float(rel[df["lap_number"] == last_id].max())
            done = last_dist - (last_id - 1) * args.lap_dist
            if done < 0.95 * args.lap_dist:
                print(f"  catatan: lap {int(last_id)} belum penuh "
                      f"({done:.0f}/{args.lap_dist:g} jarak) — lap berjalan "
                      f"saat logging berhenti")
        unassigned = int(df["lap_number"].isna().sum())
        print(f"  outside the race window (lap_number = NaN): {unassigned} rows")

        out = args.out or os.path.splitext(args.csv)[0] + "_laps.csv"
        df.to_csv(out, index=False)
        print(f"\nwrote {out}")
        return

    if not args.durations:
        sys.exit("provide --durations, --lap-dist, or --gps")

    durations = [float(x) for x in args.durations.replace(" ", "").split(",")]
    boundaries = np.cumsum(durations)          # lap i ends at boundaries[i-1]
    lap = np.searchsorted(boundaries, elapsed, side="right") + 1.0
    # elapsed yang tepat sama dengan batas terakhir ikut searchsorted ke
    # "lap n+1" — buang bersama baris di luar jendela race
    lap[(elapsed < 0) | (elapsed > boundaries[-1]) | (lap > len(durations))] = np.nan
    df["lap_number"] = lap

    print(f"\n{len(durations)} laps over {boundaries[-1]:.0f} s:")
    for i in range(1, len(durations) + 1):
        n = int((df['lap_number'] == i).sum())
        print(f"  lap {i}: {durations[i-1]:.0f} s, {n} rows")
    unassigned = int(df["lap_number"].isna().sum())
    print(f"  outside the race window (lap_number = NaN): {unassigned} rows")

    out = args.out or os.path.splitext(args.csv)[0] + "_laps.csv"
    df.to_csv(out, index=False)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
