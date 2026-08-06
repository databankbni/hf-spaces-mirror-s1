"""
build_research_csv.py — merge each attempt's per-lap files into ONE CSV for the
research division's intern.

For every data/race_day/attempt_XX/laps_split/ it:
  1. concatenates lap_01..lap_NN.csv (schema is identical across laps)
  2. patches dead-velocity rows via derive_velocity (odometer slope), keeping
     the original as velocity_raw and marking velocity_source
  3. mirrors the fixed speed into kecepatan_kmh (research's mandatory column)
  4. adds attempt metadata: attempt, motor_setting (15/25/30), battery_limit_A

Outputs go to data/research/ — attempt folders are never written to:
    attemptN_research.csv        one per attempt
    all_attempts_research.csv    everything concatenated
"""

import glob
import os

import numpy as np
import pandas as pd

from derive_velocity import derive

BASE = "data/race_day"
OUT_DIR = "data/research"
# settingan motor dari divisi riset; battery current limit 5 A untuk semua
MOTOR_SETTING = {1: 15, 2: 25, 3: 30}
# lap yang dikeluarkan dari paket riset: attempt 1 lap 5-6 = mobil mogok di
# tengah lap 5 lalu didorong kembali ke pit (bukan berkendara normal)
EXCLUDE_LAPS = {1: {5, 6}}


def build_attempt(n):
    lap_files = sorted(glob.glob(f"{BASE}/attempt_{n:02d}/laps_split/lap_*.csv"))
    if not lap_files:
        return None
    df = pd.concat([pd.read_csv(p) for p in lap_files], ignore_index=True)
    if n in EXCLUDE_LAPS:
        df = df[~df["lap_number"].isin(EXCLUDE_LAPS[n])].reset_index(drop=True)

    # recover dead-velocity rows from the odometer (adds velocity_raw,
    # velocity_derived_kmh, velocity_source; fixes Velocity in place)
    df, n_fixed, n_zero = derive(df, window=6.0)
    vcol = "Velocity" if "Velocity" in df.columns else "velocity"
    if "kecepatan_kmh" in df.columns:
        df["kecepatan_kmh"] = pd.to_numeric(df[vcol], errors="coerce")

    df.insert(0, "attempt", n)
    df.insert(1, "motor_setting", MOTOR_SETTING.get(n, np.nan))
    df.insert(2, "battery_limit_A", 5)
    return df, n_fixed, n_zero, len(lap_files)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    merged = []
    for n in range(1, 7):
        res = build_attempt(n)
        if res is None:
            continue
        df, n_fixed, n_zero, n_laps = res
        dest = f"{OUT_DIR}/attempt{n}_research.csv"
        df.to_csv(dest, index=False)
        merged.append(df)
        print(f"attempt {n}: {n_laps} laps, {len(df)} rows, "
              f"velocity zeros {n_zero} -> {n_fixed} recovered  => {dest}")
    if merged:
        alld = pd.concat(merged, ignore_index=True)
        alld.to_csv(f"{OUT_DIR}/all_attempts_research.csv", index=False)
        print(f"combined: {len(alld)} rows => {OUT_DIR}/all_attempts_research.csv")


if __name__ == "__main__":
    main()
