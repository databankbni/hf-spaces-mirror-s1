"""
clean_telemetry.py — deterministic on-track telemetry cleaner for Antasena SEM test drives.

Usage:
    python clean_telemetry.py falcon_telemetry.csv
    python clean_telemetry.py falcon_telemetry.csv -o cleaned.csv

Pipeline (order matters):
  1. Coerce every column to numeric (pd.to_numeric errors='coerce')
  2. Drop exact duplicate rows (MQTT QoS 1 = at-least-once => duplicates happen)
  3. Sort by ts, drop duplicate timestamps (keep first)
  4. Detect packet-loss gaps (reported, never silently filled)
  5. Physical range validation -> out-of-bounds values become NaN
  6. Cumulative columns (EnergyWh, Distance, timeS) must be non-decreasing
  7. Velocity zero-drop glitch detection (0 between moving samples = impossible)
  8. Rolling-median MAD outlier detection per signal column
     (window auto-sized: detect glitch run length L, window = 2L+1)
  9. Linear interpolation of flagged points (interior only, bounded run length)
 10. QC report: every change counted, unrecoverable columns flagged (GIGO)

Design rule (from .agents/AGENTS.md): detection-then-interpolation only.
Sustained real behaviour (voltage sag, pulses) moves the rolling median with it,
so it is never flagged. We never blanket-smooth a signal.
"""

import argparse
import json
import os
import re
import sys

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Column rules. Covers both the live falcon schema and the old TestDrive schema.
# Columns not listed are treated as generic signals (MAD only, no bounds).
# kind: 'signal' | 'cumulative' | 'meta' (never touched)
# ---------------------------------------------------------------------------
RULES = {
    # live falcon schema
    "vinBattery":      {"kind": "signal", "bounds": (0.0, 100.0)},
    "currentBattery":  {"kind": "signal", "bounds": (-10.0, 200.0)},
    "velocity":    {"kind": "signal", "bounds": (0.0, 120.0), "zero_glitch": True},
    "distance":    {"kind": "cumulative"},
    "powerW":      {"kind": "signal", "bounds": (-100.0, 10000.0)},
    "energyWh":    {"kind": "cumulative"},
    "kmPerkWh":    {"kind": "signal", "bounds": (0.0, 500.0)},
    "mslAltitude": {"kind": "signal", "bounds": (-50.0, 150.0)},
    "wgsAltitude": {"kind": "signal", "bounds": (-50.0, 150.0)},
    "gForceX":     {"kind": "signal", "bounds": (-8.0, 8.0)},
    "gForceY":     {"kind": "signal", "bounds": (-8.0, 8.0)},
    "gForceZ":     {"kind": "signal", "bounds": (-8.0, 8.0)},
    "latitude":    {"kind": "signal", "bounds": (-12.0, 8.0)},
    "longitude":   {"kind": "signal", "bounds": (94.0, 142.0)},
    "timeS":       {"kind": "cumulative"},
    "countdown":   {"kind": "meta"},
    "ts":          {"kind": "meta"},
    # old TestDrive schema aliases
    "vinBattery":  {"kind": "signal", "bounds": (0.0, 100.0)},
    "vinM":        {"kind": "signal", "bounds": (0.0, 100.0)},
    "arusM":       {"kind": "signal", "bounds": (-10.0, 200.0)},
    "Power":       {"kind": "signal", "bounds": (-100.0, 10000.0)},
    "EnergyWh":    {"kind": "cumulative"},
    "Distance":    {"kind": "cumulative"},
    "Velocity":    {"kind": "signal", "bounds": (0.0, 120.0), "zero_glitch": True},
}

# ---------------------------------------------------------------------------
# Attribute-name aliases: tomorrow's logger may call the same physical signal
# something else. Names are matched after normalisation (lowercase, strip
# non-alphanumerics), so "Speed_kmh", "speed kmh" and "speedKMH" all match.
# Each alias maps to a canonical RULES key.
# ---------------------------------------------------------------------------
ALIAS_GROUPS = {
    # mobil sekarang full EV baterai — TIDAK ada fuel cell. Nama kanonik
    # vinBattery/currentBattery; vinfc/currentm dipertahankan sebagai alias
    # supaya file lama tetap terbaca (dan ikut di-rename ke nama baru).
    "vinBattery":     ["vinbattery", "vinfc", "vinm", "vin", "voltage", "volt",
                       "vbat", "batteryvoltage", "battvoltage", "battvolt",
                       "tegangan", "teganganbaterai"],
    "currentBattery": ["currentbattery", "batterycurrent", "battcurrent",
                       "currentm", "arusm", "current", "arus", "ampere",
                       "amp", "motorcurrent"],
    "velocity":    ["velocity", "speed", "vel", "kecepatan", "speedkmh",
                    "velocitykmh", "speedms"],
    "distance":    ["distance", "jarak", "odometer", "odo", "distancekm",
                    "distancem", "cumdistkm", "cumdist", "totaldistance"],
    "powerW":      ["powerw", "power", "daya", "watt", "powerwatt"],
    "energyWh":    ["energywh", "energiwh", "energy", "energi",
                    "energywatthour", "totalenergy", "energykwh"],
    "kmPerkWh":    ["kmperkwh", "efficiency", "efisiensi", "kmkwh",
                    "kmperkwhr"],
    "mslAltitude": ["mslaltitude", "altitude", "alt", "elevation",
                    "altitudem", "ketinggian"],
    "wgsAltitude": ["wgsaltitude", "gpsaltitude"],
    "gForceX":     ["gforcex", "accelx", "ax", "gx", "accx"],
    "gForceY":     ["gforcey", "accely", "ay", "gy", "accy"],
    "gForceZ":     ["gforcez", "accelz", "az", "gz", "accz"],
    "latitude":    ["latitude", "lat", "gpslat"],
    "longitude":   ["longitude", "lon", "lng", "long", "gpslon", "gpslng"],
    "timeS":       ["times", "elapsed", "elapseds", "elapsedtime", "timesec",
                    "waktus", "runtime"],
    "ts":          ["ts", "timestamp", "timestampms", "tsms", "epochms",
                    "unixms", "unixtime"],
}

# Names that are bookkeeping, not sensor signals: never coerced, never
# filtered, never interpolated. Interpolating a lap number or an ID would
# invent nonsense.
META_NAMES = {
    "id", "idx", "index", "no", "rownum", "mode", "status", "state", "flag",
    "lap", "laps", "lapnumber", "lapno", "session", "driver", "istrain",
    "recordedat", "createdat", "datetime", "date", "waktu", "tanggal",
    "note", "notes", "event", "countdown",
    # boolean safety flag from the real MCU + logTime receive-time columns:
    # never coerce or interpolate any of these
    "h2leak", "receivedatwib", "receiveddatewib", "receivedtimewib",
}

# Candidate timestamp columns for auto-detection (normalised names, in
# priority order). Datetime strings are parsed; numeric ones used as-is.
TS_CANDIDATES = ["ts", "timestamp", "timestampms", "recordedat", "datetime",
                 "createdat", "epochms", "unixms", "time", "waktu",
                 # logTime.py wall-clock (preferred over MCU uptime), then the
                 # MCU uptime column Time(s) as a last resort
                 "receivedatwib", "times"]


def _norm(name):
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


_ALIAS_LOOKUP = {}
for _canon, _names in ALIAS_GROUPS.items():
    for _n in _names:
        _ALIAS_LOOKUP.setdefault(_n, _canon)


def resolve_rule(col):
    """Map a column name to its cleaning rule via alias (which also covers an
    exact canonical match, e.g. "velocity" is its own alias), then legacy
    RULES-only keys, then meta names, then generic signal. Returns (rule,
    canonical_or_None).

    Alias lookup runs BEFORE the raw "col in RULES" check: several legacy
    schema keys (old TestDrive-era "Velocity", "Distance", "Power", ...) are
    both a RULES entry (for their bounds) AND an ALIAS_GROUPS member of the
    modern lowercase name. Checking RULES first would return canon=col=
    "Velocity" unchanged (exact key match short-circuits) instead of
    unifying to "velocity", silently defeating the alias system for exactly
    the schema variant it exists to normalise -- e.g. a real Antasena log
    with "Velocity" would never get renamed to the canonical "velocity" a
    downstream consumer (Stratelm-GUI's chart normalizer) looks for."""
    n = _norm(col)
    if n in _ALIAS_LOOKUP:
        canon = _ALIAS_LOOKUP[n]
        return RULES[canon], canon
    if col in RULES:
        return RULES[col], col
    if n in META_NAMES:
        return {"kind": "meta"}, None
    return {"kind": "signal"}, None

MAD_K = 5.0                 # threshold: |x - rolling median| > K * scaled MAD (~5 sigma).
                            # 3.0 flags ~1-2% of ordinary Gaussian noise; real telemetry
                            # glitches (999 codes, g-force spikes) sit hundreds of sigma out.
BASE_WINDOW = 7             # first-pass detection window
MAX_WINDOW = 41             # cap on auto-sized window
MAX_INTERP_RUN = 25         # never invent more than this many consecutive rows
GAP_FACTOR = 5.0            # gap = interval > GAP_FACTOR * median interval
ZERO_GLITCH_MAX_RUN = 15    # velocity zero-runs longer than this = real stop
ZERO_GLITCH_MIN_NEIGHBOR = 3.0  # km/h on both sides to call a zero a glitch


def _runs_of(mask):
    """Yield (start, length) of consecutive True runs in a boolean array."""
    idx = np.flatnonzero(mask)
    if len(idx) == 0:
        return
    breaks = np.flatnonzero(np.diff(idx) > 1)
    starts = np.r_[idx[0], idx[breaks + 1]]
    ends = np.r_[idx[breaks], idx[-1]]
    for s, e in zip(starts, ends):
        yield int(s), int(e - s + 1)


def mad_flags(series, window):
    """Boolean mask of points deviating > MAD_K scaled-MADs from rolling median.

    The detection median is local (window), but the MAD scale is estimated over
    a wider window: a 7-sample MAD estimate is itself so noisy that it randomly
    collapses and flags ordinary sensor noise."""
    med = series.rolling(window, center=True, min_periods=1).median()
    abs_dev = (series - med).abs()
    # Elementwise max of local and wide MAD: the wide window stabilises the
    # estimate on flat stretches, the local one keeps the scale honest where a
    # quiet regime borders a noisy one (pulse edges). Max = conservative =
    # when in doubt, do not touch the data.
    mad_local = abs_dev.rolling(window, center=True, min_periods=1).median()
    wide = max(31, window)
    mad_wide = abs_dev.rolling(wide, center=True, min_periods=1).median()
    # Directional windows: a point just after a regime change (pulse start,
    # sag onset) is judged against the FUTURE noise level too, not only the
    # quiet past. A point consistent with either side is not a glitch.
    mad_past = abs_dev.rolling(wide, min_periods=1).median()
    mad_future = abs_dev[::-1].rolling(wide, min_periods=1).median()[::-1]
    mad = pd.concat([mad_local, mad_wide, mad_past, mad_future], axis=1).max(axis=1)
    scale = 1.4826 * mad
    # Floor the scale so flat stretches (MAD = 0) don't flag natural jitter.
    nonzero = abs_dev[abs_dev > 0]
    floor = 0.5 * 1.4826 * float(nonzero.median()) if len(nonzero) else 1e-12
    scale = scale.clip(lower=max(floor, 1e-12))
    return (abs_dev > MAD_K * scale) & series.notna()


def _unflag_real_steps(series, flags):
    """A glitch REVERTS (signal returns to prior level); real physics PERSISTS
    (signal jumps and stays — pulse start, voltage sag edge). Unflag the latter
    so we never smooth genuine step changes."""
    v = series.to_numpy(dtype=float)
    f = flags.to_numpy().copy()
    for start, length in _runs_of(f):
        b = start - 1
        while b >= 0 and np.isnan(v[b]):
            b -= 1
        a = start + length
        while a < len(v) and np.isnan(v[a]):
            a += 1
        if b < 0 or a >= len(v):
            continue  # no context at series edge: keep the flag (conservative)
        jump = abs(v[a] - v[b])                      # did the baseline move?
        baseline = 0.5 * (v[a] + v[b])
        run_dev = np.nanmedian(np.abs(v[start:start + length] - baseline))
        if run_dev < 2.0 * jump:                     # deviation ~ the step itself
            f[start:start + length] = False
    return pd.Series(f, index=series.index)


def detect_signal_outliers(series):
    """Two-pass MAD detection with auto window sizing (window = 2*run + 1),
    then a revert-check so real step changes are never flagged."""
    flags = mad_flags(series, BASE_WINDOW)
    max_run = max((ln for _, ln in _runs_of(flags.to_numpy())), default=0)
    window = min(2 * max_run + 1, MAX_WINDOW)
    if window > BASE_WINDOW:
        flags = mad_flags(series, window)
    flags = _unflag_real_steps(series, flags)
    return flags, window if window > BASE_WINDOW else BASE_WINDOW


def detect_zero_glitches(series):
    """Velocity dropping to 0 between moving samples is physically impossible."""
    flags = np.zeros(len(series), dtype=bool)
    v = series.to_numpy()
    zero = (v == 0) & ~np.isnan(v)
    for start, length in _runs_of(zero):
        if length > ZERO_GLITCH_MAX_RUN:
            continue  # long stop: probably real (start line, pit)
        before = v[start - 1] if start > 0 else np.nan
        after = v[start + length] if start + length < len(v) else np.nan
        if (not np.isnan(before) and before > ZERO_GLITCH_MIN_NEIGHBOR
                and not np.isnan(after) and after > ZERO_GLITCH_MIN_NEIGHBOR):
            flags[start:start + length] = True
    return pd.Series(flags, index=series.index)


def _find_ts_column(df, ts_col):
    """Return (column_name, numeric_ms_series) for the best timestamp column,
    or (None, None). Datetime strings are parsed to epoch milliseconds.
    Numeric columns in seconds (epoch-s or MCU uptime like Time(s)) are
    converted to ms so downstream elapsed/gap math stays unit-consistent."""
    norm_map = {}
    for c in df.columns:
        norm_map.setdefault(_norm(c), c)
    # exact --ts-col name first, then TS_CANDIDATES priority order (a wall
    # clock like received_at_wib beats MCU uptime even if it comes later
    # in the file)
    candidates = [ts_col] + [norm_map[n] for n in TS_CANDIDATES
                             if n in norm_map and norm_map[n] != ts_col]
    for col in candidates:
        if col not in df.columns:
            continue
        s = df[col]
        if pd.api.types.is_numeric_dtype(s):
            vals = s.astype("float64")
            finite = vals.dropna()
            # epoch-ms is ~1.7e12; anything below 1e11 is seconds
            # (epoch-s ~1.7e9, or relative uptime like Time(s))
            if len(finite) and float(finite.abs().median()) < 1e11:
                vals = vals * 1000.0
            return col, vals
        parsed = pd.to_datetime(s, errors="coerce", format="mixed")
        if parsed.notna().mean() >= 0.9:
            # normalise to ns first: pandas may parse at s/ms/us resolution
            ns = parsed.astype("datetime64[ns]").astype("int64")
            return col, ns.where(parsed.notna()) / 1e6
    return None, None


def clean(df, ts_col="ts", trim_idle=False, lat_bounds=None, lon_bounds=None):
    """Clean a telemetry DataFrame. Returns (cleaned_df, report_dict).

    lat_bounds/lon_bounds override RULES' latitude/longitude sanity box,
    which is calibrated to Indonesia (Antasena's home test track, roughly
    lat -12..8 / lon 94..142) -- correct for THAT venue's telemetry, but it
    would silently wipe every point of a GPS trace recorded anywhere else
    (e.g. Lusail, Qatar is ~25N/51E, entirely outside that box) since the
    bounds check can't tell "impossible fix" apart from "different country".
    Pass the venue's own (lo, hi) bounds when cleaning telemetry for a track
    other than the original one; leave both None to keep the default
    Indonesia box."""
    report = {"input_rows": len(df), "columns": {}, "gaps": [], "warnings": []}
    bounds_override = {}
    if lat_bounds is not None:
        bounds_override["latitude"] = lat_bounds
    if lon_bounds is not None:
        bounds_override["longitude"] = lon_bounds

    resolved = {col: resolve_rule(col) for col in df.columns}
    for col, (rule, canon) in resolved.items():
        if canon and canon != col:
            report["columns"].setdefault(col, {})["treated_as"] = canon

    # 1. numeric coercion (meta columns are preserved untouched; text columns
    #    that don't parse as numbers are demoted to meta instead of destroyed)
    for col in df.columns:
        rule, _ = resolved[col]
        if rule["kind"] == "meta":
            continue
        s = df[col]
        if not pd.api.types.is_numeric_dtype(s):
            as_num = pd.to_numeric(s, errors="coerce")
            # European decimal commas ("8,26"): fix if it parses better
            fixed = pd.to_numeric(s.astype(str).str.replace(",", ".", regex=False),
                                  errors="coerce")
            if fixed.notna().sum() > as_num.notna().sum():
                as_num = fixed
                report["columns"].setdefault(col, {})["decimal_commas_fixed"] = \
                    int(fixed.notna().sum() - pd.to_numeric(s, errors="coerce").notna().sum())
            nonnull = s.notna()
            parse_rate = as_num.notna().sum() / max(int(nonnull.sum()), 1)
            if parse_rate < 0.5:
                # text column (mode, notes, ...): keep it, never clean it
                resolved[col] = ({"kind": "meta"}, None)
                report["columns"].setdefault(col, {})["non_numeric"] = "preserved as text"
                continue
            before_na = int(s.isna().sum())
            df[col] = as_num
            coerced = int(as_num.isna().sum()) - before_na
            if coerced:
                report["columns"].setdefault(col, {})["coerced_to_nan"] = coerced

    # 2. exact duplicate rows ----------------------------------------------
    n = len(df)
    df = df.drop_duplicates(keep="first")
    report["duplicate_rows_dropped"] = n - len(df)

    # 3. sort + duplicate timestamps -----------------------------------------
    ts_name, ts_ms = _find_ts_column(df, ts_col)
    if ts_name is not None:
        report["ts_column_used"] = ts_name
        ts_ms = ts_ms.loc[df.index]
        was_sorted = ts_ms.is_monotonic_increasing
        order = ts_ms.sort_values(kind="stable").index
        df = df.loc[order]
        ts_ms = ts_ms.loc[order]
        report["reordered"] = not was_sorted

        # Dedupe on timestamp only when timestamps are high-resolution.
        # A 1 Hz clock on a 10 Hz logger repeats each second legitimately —
        # deduping there would delete real data.
        dup_frac = float(ts_ms.duplicated().mean())
        if dup_frac < 0.05:
            n = len(df)
            keep = ~ts_ms.duplicated(keep="first")
            df, ts_ms = df[keep], ts_ms[keep]
            report["duplicate_ts_dropped"] = n - len(df)
        else:
            report["duplicate_ts_dropped"] = 0
            report["warnings"].append(
                f"'{ts_name}' is low-resolution ({dup_frac:.0%} repeated values): "
                f"timestamp dedupe skipped (rows kept)")
        df = df.reset_index(drop=True)
        ts_ms = ts_ms.reset_index(drop=True)

        # 4. gap detection ----------------------------------------------------
        dt = ts_ms.diff()
        med_dt = float(dt.median())
        if med_dt > 0:
            report["median_interval_ms"] = med_dt
            gaps = dt[dt > GAP_FACTOR * med_dt]
            for i, g in gaps.items():
                report["gaps"].append({
                    "after_ts": int(ts_ms.iloc[i - 1]),
                    "gap_ms": int(g),
                    "approx_lost_rows": int(round(g / med_dt)) - 1,
                })
    else:
        df = df.reset_index(drop=True)
        report["warnings"].append(f"no timestamp column found: skipped sort/dedupe/gap checks")

    # 3b. optional idle trim: drop leading/trailing rows where the car is not
    # moving (pre-race logging, cool-down). Mid-run stops are never touched.
    if trim_idle:
        vel_col = next((c for c, (r, canon) in resolved.items()
                        if canon in ("velocity", "Velocity") or c in ("velocity", "Velocity")), None)
        if vel_col is not None:
            moving = pd.to_numeric(df[vel_col], errors="coerce") > 0.5
            if moving.any():
                first = int(moving.idxmax())
                last = int(moving[::-1].idxmax())
                report["idle_rows_trimmed"] = {"leading": first,
                                               "trailing": len(df) - 1 - last}
                df = df.iloc[first:last + 1].reset_index(drop=True)
            else:
                report["warnings"].append("--trim-idle: car never moves, nothing trimmed")
        else:
            report["warnings"].append("--trim-idle: no velocity column found")

    # 5-8. per-column detection ---------------------------------------------
    to_nan = pd.DataFrame(False, index=df.index, columns=df.columns)

    for col in df.columns:
        rule, canon = resolved[col]
        stats = report["columns"].setdefault(col, {})
        if rule["kind"] == "meta":
            continue

        s = df[col]

        # 5. bounds (lat/lon overridable per-call -- see clean()'s docstring)
        bounds = bounds_override.get(canon, rule.get("bounds"))
        if bounds is not None:
            lo, hi = bounds
            oob = ((s < lo) | (s > hi)) & s.notna()
            if oob.any():
                stats["out_of_bounds"] = int(oob.sum())
                to_nan[col] |= oob
                s = s.mask(oob)

        # 6. cumulative monotonicity: a value below the running max is corrupt
        if rule["kind"] == "cumulative":
            running_max = s.cummax()
            drops = (s < running_max) & s.notna()
            if drops.any():
                stats["cumulative_violations"] = int(drops.sum())
                to_nan[col] |= drops
                s = s.mask(drops)
            continue  # no MAD on cumulative ramps

        # 7. velocity zero-drop glitches
        if rule.get("zero_glitch"):
            zg = detect_zero_glitches(s)
            if zg.any():
                stats["zero_glitches"] = int(zg.sum())
                to_nan[col] |= zg
                s = s.mask(zg)

        # 8. MAD spike detection
        flags, window = detect_signal_outliers(s)
        if flags.any():
            stats["mad_outliers"] = int(flags.sum())
            stats["mad_window"] = window
            to_nan[col] |= flags

    # 9. interpolation --------------------------------------------------------
    for col in df.columns:
        rule, _ = resolved[col]
        if rule["kind"] == "meta":
            continue
        stats = report["columns"].setdefault(col, {})
        df[col] = df[col].mask(to_nan[col])
        na = df[col].isna()
        if not na.any():
            continue
        long_runs = sum(1 for _, ln in _runs_of(na.to_numpy()) if ln > MAX_INTERP_RUN)
        filled = df[col].interpolate(method="linear", limit=MAX_INTERP_RUN,
                                     limit_area="inside")
        stats["interpolated"] = int((na & filled.notna()).sum())
        remaining = int(filled.isna().sum())
        if remaining:
            stats["unrecoverable_nan"] = remaining
        if long_runs:
            report["warnings"].append(
                f"{col}: {long_runs} NaN run(s) longer than {MAX_INTERP_RUN} rows "
                f"left unfilled (GIGO: do not invent data)")
        df[col] = filled

    # 10. column health verdicts ---------------------------------------------
    for col, stats in report["columns"].items():
        touched = sum(v for k, v in stats.items()
                      if k in ("out_of_bounds", "cumulative_violations",
                               "zero_glitches", "mad_outliers", "coerced_to_nan"))
        frac = touched / max(len(df), 1)
        stats["fraction_touched"] = round(frac, 4)
        if frac > 0.30:
            stats["verdict"] = "UNRELIABLE (>30% corrupt — treat as dead sensor)"
            report["warnings"].append(f"{col}: sensor looks unreliable "
                                      f"({frac:.0%} of samples corrupt)")
        elif frac > 0.05:
            stats["verdict"] = "SUSPECT (5-30% corrupt — inspect before trusting)"
        else:
            stats["verdict"] = "OK"

    # 9. rename aliased columns to their canonical names so downstream tools
    # (assign_laps, split_laps, notebooks) see one consistent vocabulary no
    # matter what the logger called things ("Batt Voltage" -> vinBattery, ...).
    # Skipped when the canonical name already exists as another column.
    renames = {}
    taken = set(df.columns)
    for col, (rule, canon) in resolved.items():
        if canon and canon != col and col in df.columns and canon not in taken:
            renames[col] = canon
            taken.add(canon)
    if renames:
        df = df.rename(columns=renames)
        report["columns_renamed"] = renames
        if report.get("ts_column_used") in renames:
            report["ts_column_used"] = renames[report["ts_column_used"]]

    report["output_rows"] = len(df)
    return df, report


def format_report(report):
    lines = ["", "=" * 62, "QC REPORT", "=" * 62]
    lines.append(f"rows in: {report['input_rows']}   rows out: {report['output_rows']}")
    lines.append(f"exact duplicate rows dropped : {report.get('duplicate_rows_dropped', 0)}")
    lines.append(f"duplicate timestamps dropped : {report.get('duplicate_ts_dropped', 0)}")
    if "ts_column_used" in report:
        lines.append(f"timestamp column              : {report['ts_column_used']}")
    if "idle_rows_trimmed" in report:
        t = report["idle_rows_trimmed"]
        lines.append(f"idle rows trimmed            : {t['leading']} leading, {t['trailing']} trailing")
    if report.get("reordered"):
        lines.append("NOTE: rows arrived out of order and were re-sorted by ts")
    if "median_interval_ms" in report:
        lines.append(f"median sample interval       : {report['median_interval_ms']:.0f} ms")
    if report["gaps"]:
        lines.append(f"\nPACKET-LOSS GAPS ({len(report['gaps'])}):")
        for g in report["gaps"][:20]:
            lines.append(f"  after ts {g['after_ts']}: {g['gap_ms']} ms "
                         f"(~{g['approx_lost_rows']} rows lost)")
        if len(report["gaps"]) > 20:
            lines.append(f"  ... and {len(report['gaps']) - 20} more")
    else:
        lines.append("packet-loss gaps             : none")

    lines.append("\nPER-COLUMN:")
    for col, st in report["columns"].items():
        fixes = {k: v for k, v in st.items() if k not in ("verdict", "fraction_touched")}
        verdict = st.get("verdict", "OK")
        if fixes or verdict != "OK":
            lines.append(f"  {col:<14} {verdict:<12} {fixes if fixes else ''}")
    clean_cols = [c for c, st in report["columns"].items()
                  if st.get("verdict") == "OK" and st.get("fraction_touched", 0) == 0]
    if clean_cols:
        lines.append(f"  (untouched & OK: {', '.join(clean_cols)})")

    if report["warnings"]:
        lines.append("\nWARNINGS:")
        for w in report["warnings"]:
            lines.append(f"  ! {w}")
    lines.append("=" * 62)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Clean SEM telemetry CSV")
    ap.add_argument("csv", help="raw telemetry CSV (from log.py)")
    ap.add_argument("-o", "--out", help="output CSV (default: <name>_cleaned.csv)")
    ap.add_argument("--ts-col", default="ts", help="timestamp column name")
    ap.add_argument("--trim-idle", action="store_true",
                    help="drop leading/trailing rows where the car is not moving")
    args = ap.parse_args()

    if not os.path.isfile(args.csv):
        sys.exit(f"file not found: {args.csv}")

    df = pd.read_csv(args.csv)
    cleaned, report = clean(df, ts_col=args.ts_col, trim_idle=args.trim_idle)

    out = args.out or os.path.splitext(args.csv)[0] + "_cleaned.csv"
    cleaned.to_csv(out, index=False)
    # QC reports live in reports/, separate from the data files
    os.makedirs("reports", exist_ok=True)
    report_path = os.path.join(
        "reports", os.path.splitext(os.path.basename(out))[0] + "_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    print(format_report(report))
    print(f"\ncleaned CSV : {out}")
    print(f"full report : {report_path}")


if __name__ == "__main__":
    main()
