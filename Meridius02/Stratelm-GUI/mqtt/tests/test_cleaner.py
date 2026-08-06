"""
test_cleaner.py — proves clean_telemetry.py actually works.

Strategy:
  1. Generate a physically plausible ground-truth telemetry trace
     (pulse-and-glide velocity, correlated current/power, REAL voltage sag,
     cumulative energy/distance, GPS drift) at 5 Hz.
  2. Inject corruption at KNOWN locations:
       - duplicate rows (MQTT QoS 1 redelivery)
       - an out-of-order block (reconnect burst)
       - a packet-loss gap
       - velocity zero-drop glitches (runs of 1-4 rows)
       - kmPerkWh 999 error-code runs (up to 6 rows)
       - single-sample extreme spikes (gForceZ = 5, velocity = 999.9)
       - scattered NaN / text garbage
       - a dead-sensor stretch of junk altitude
  3. Run the cleaner and score it:
       RECOVERY  : are corrupted points restored close to ground truth?
       PRESERVE  : are clean points — especially the voltage sag — untouched?
       STRUCTURE : duplicates gone, order restored, gap reported?

Run:  python test_cleaner.py
"""

import numpy as np
import pandas as pd

from clean_telemetry import clean

rng = np.random.default_rng(42)

N = 3000          # 3000 rows @ 5 Hz = 10 minutes
DT_MS = 200


def make_ground_truth():
    t = np.arange(N) * (DT_MS / 1000.0)

    # pulse-and-glide velocity: accelerate to ~30, coast to ~18, repeat
    velocity = np.zeros(N)
    v = 0.0
    for i in range(1, N):
        phase = (t[i] % 60)
        if phase < 15:          # pulse
            v += 0.45 * (DT_MS / 1000.0) * (30 - v) / 30 * 10
        else:                   # glide
            v -= 0.06 * (DT_MS / 1000.0) * 10
        v = max(v, 0.0)
        velocity[i] = v
    velocity += rng.normal(0, 0.05, N)
    velocity = np.clip(velocity, 0, None)

    # current follows the pulse phase; near zero when gliding
    pulsing = (t % 60) < 15
    current = np.where(pulsing, 3.5 + rng.normal(0, 0.15, N),
                       0.08 + rng.normal(0, 0.01, N))
    current = np.clip(current, 0, None)

    # REAL voltage sag: voltage drops with current draw (internal resistance)
    vin = 38.0 - 0.55 * current + rng.normal(0, 0.005, N)

    power = vin * current
    energy = np.cumsum(power * DT_MS / 3600000.0) + 0.05      # Wh
    dist = np.cumsum(velocity * DT_MS / 3600000.0)            # km
    with np.errstate(divide="ignore"):
        eff = np.where(energy > 0, dist / (energy / 1000.0), 0.0)
    eff = np.clip(eff, 0, 400)

    lat = -7.2767 + np.cumsum(rng.normal(0, 2e-7, N))
    lon = 112.7999 + np.cumsum(rng.normal(0, 2e-7, N))

    df = pd.DataFrame({
        "vinBattery": np.round(vin, 3),
        "currentBattery": np.round(current, 3),
        "velocity": np.round(velocity, 2),
        "distance": np.round(dist, 5),
        "powerW": np.round(power, 2),
        "energyWh": np.round(energy, 5),
        "kmPerkWh": np.round(eff, 2),
        "mslAltitude": np.round(9.0 + rng.normal(0, 0.05, N), 2),
        "gForceZ": np.round(0.837 + rng.normal(0, 0.002, N), 3),
        "latitude": np.round(lat, 6),
        "longitude": np.round(lon, 6),
        "ts": 1783129448035 + np.arange(N) * DT_MS,
    })
    return df, pulsing


def corrupt(truth):
    """Return (corrupted_df, dict of injected corruption locations by ts)."""
    df = truth.copy()
    inj = {}

    # velocity zero-drop glitches: runs of 1-4 rows while moving
    inj["velocity_glitch_ts"] = []
    # placed in clearly-moving sections (mid-pulse / mid-glide, v >> 3 km/h);
    # a zero at ~3 km/h is physically ambiguous and not the cleaner's job
    for start in [420, 950, 1550, 2150, 2650]:
        run = rng.integers(1, 5)
        df.loc[start:start + run - 1, "velocity"] = 0.0
        inj["velocity_glitch_ts"] += list(truth["ts"].iloc[start:start + run])

    # kmPerkWh error-code runs of 999 (widest = 6 rows)
    inj["eff_glitch_ts"] = []
    for start, run in [(700, 2), (1300, 6), (2400, 4)]:
        df.loc[start:start + run - 1, "kmPerkWh"] = 999.0
        inj["eff_glitch_ts"] += list(truth["ts"].iloc[start:start + run])

    # single-sample sensor spikes (like simulate_field.py's glitch mode)
    inj["spike_ts"] = []
    for i in [550, 1750, 2850]:
        df.loc[i, "gForceZ"] = 5.0
        df.loc[i, "velocity"] = 999.9
        inj["spike_ts"].append(int(truth["ts"].iloc[i]))

    # scattered NaN + text garbage (object dtype, like a CSV read with junk in it)
    df["currentBattery"] = df["currentBattery"].astype(object)
    inj["nan_ts"] = []
    for i in [333, 1111, 1999]:
        df.loc[i, "powerW"] = np.nan
        df.loc[i, "currentBattery"] = "error"
        inj["nan_ts"].append(int(truth["ts"].iloc[i]))

    # dead-sensor stretch: altitude spews garbage for 200 rows
    df.loc[1000:1199, "mslAltitude"] = rng.uniform(-900, 900, 200).round(1)

    # cumulative violation: energy dips backwards for 3 rows
    df.loc[1600:1602, "energyWh"] = df.loc[1590, "energyWh"] - 0.01
    inj["cum_violation_ts"] = list(truth["ts"].iloc[1600:1603])

    # packet loss: drop 12 consecutive rows
    inj["gap_after_ts"] = int(truth["ts"].iloc[1899])
    df = df.drop(index=range(1900, 1912))

    # out-of-order block: reconnect burst delivers 30 rows late
    block = df.iloc[500:530]
    df = pd.concat([df.iloc[:500], df.iloc[530:600], block, df.iloc[600:]])

    # QoS-1 duplicates: re-deliver 25 random rows
    dup_idx = rng.choice(len(df), 25, replace=False)
    df = pd.concat([df, df.iloc[dup_idx]])
    inj["n_duplicates"] = 25

    return df.reset_index(drop=True), inj


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def main():
    truth, pulsing = make_ground_truth()
    dirty, inj = corrupt(truth)

    print(f"ground truth: {len(truth)} rows | corrupted input: {len(dirty)} rows")
    cleaned, report = clean(dirty.copy())

    # align cleaned to truth by ts (the gap rows are legitimately missing)
    merged = truth.merge(cleaned, on="ts", suffixes=("_true", "_clean"))
    results = []

    # --- STRUCTURE ---------------------------------------------------------
    print("\nSTRUCTURE")
    results.append(check("duplicates removed",
                         report["duplicate_rows_dropped"] == inj["n_duplicates"],
                         f"dropped {report['duplicate_rows_dropped']}, injected {inj['n_duplicates']}"))
    results.append(check("order restored",
                         cleaned["ts"].is_monotonic_increasing and report["reordered"]))
    gap_found = any(g["after_ts"] == inj["gap_after_ts"] for g in report["gaps"])
    results.append(check("packet-loss gap reported", gap_found,
                         f"{len(report['gaps'])} gap(s) reported"))

    # --- RECOVERY ----------------------------------------------------------
    print("\nRECOVERY (corrupted points restored to ~truth)")

    m = merged[merged["ts"].isin(inj["velocity_glitch_ts"])]
    err = (m["velocity_clean"] - m["velocity_true"]).abs()
    results.append(check("velocity zero-glitches interpolated",
                         (err < 2.0).mean() >= 0.9,
                         f"max err {err.max():.2f} km/h over {len(m)} points"))

    m = merged[merged["ts"].isin(inj["eff_glitch_ts"])]
    rel = ((m["kmPerkWh_clean"] - m["kmPerkWh_true"]).abs()
           / m["kmPerkWh_true"].clip(lower=1))
    results.append(check("kmPerkWh 999-runs recovered (incl. 6-wide run)",
                         (rel < 0.10).all(),
                         f"worst rel err {rel.max():.1%}"))

    m = merged[merged["ts"].isin(inj["spike_ts"])]
    results.append(check("gForceZ spikes removed",
                         ((m["gForceZ_clean"] - m["gForceZ_true"]).abs() < 0.05).all()))
    results.append(check("velocity 999.9 spikes removed",
                         ((m["velocity_clean"] - m["velocity_true"]).abs() < 2.0).all()))

    m = merged[merged["ts"].isin(inj["nan_ts"])]
    results.append(check("text garbage coerced & interpolated",
                         m["currentBattery_clean"].notna().all()
                         and ((m["currentBattery_clean"] - m["currentBattery_true"]).abs() < 0.5).all()))

    m = merged[merged["ts"].isin(inj["cum_violation_ts"])]
    results.append(check("cumulative energy dip repaired",
                         (m["energyWh_clean"] >= m["energyWh_true"] * 0.99).all()))

    alt_verdict = report["columns"]["mslAltitude"].get("verdict", "OK")
    results.append(check("dead altitude sensor flagged, not 'fixed'",
                         "OK" not in alt_verdict or
                         report["columns"]["mslAltitude"].get("out_of_bounds", 0) > 150,
                         alt_verdict))

    # --- PRESERVATION (the AGENTS.md rule) ----------------------------------
    print("\nPRESERVATION (clean physics must be untouched)")

    corrupted_ts = set(inj["velocity_glitch_ts"]) | set(inj["eff_glitch_ts"]) \
        | set(inj["spike_ts"]) | set(inj["nan_ts"]) | set(inj["cum_violation_ts"])
    clean_rows = merged[~merged["ts"].isin(corrupted_ts)]

    sag_rows = clean_rows[np.isin(clean_rows["ts"],
                                  truth["ts"].to_numpy()[pulsing])]
    sag_delta = (sag_rows["vinBattery_clean"] - sag_rows["vinBattery_true"]).abs()
    results.append(check("voltage sag NOT smoothed",
                         (sag_delta < 1e-9).mean() > 0.995,
                         f"{(sag_delta < 1e-9).mean():.2%} of sag samples bit-identical"))

    for col in ["velocity", "currentBattery", "powerW", "kmPerkWh"]:
        d = (clean_rows[f"{col}_clean"] - clean_rows[f"{col}_true"]).abs()
        altered = (d > 1e-9).mean()
        results.append(check(f"{col}: clean points untouched", altered < 0.005,
                             f"{altered:.3%} altered"))

    # --- SUMMARY -------------------------------------------------------------
    print(f"\n{'='*50}")
    n_pass = sum(results)
    print(f"RESULT: {n_pass}/{len(results)} checks passed")
    if n_pass == len(results):
        print("Cleaner is verified against known injected corruption.")
    else:
        print("SOME CHECKS FAILED — do not trust the cleaner yet.")
    return n_pass == len(results)


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)
