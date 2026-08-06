# Antasena Falcon Telemetry Pipeline

MQTT telemetry logging, cleaning, and lap analysis for the Antasena SEM car.

## Scripts

| Script | Purpose |
|---|---|
| `log.py` | Subscribe to `falcon/telemetry` on the MQTT broker, append rows to CSV |
| `simulate_field.py` | Physics-based car simulator with injected worst-case faults (`--offline N` writes CSV without a broker) |
| `clean_telemetry.py` | Deterministic cleaner: bounds, cumulative, zero-glitch, MAD detection + interpolation. Handles renamed attributes, text columns, datetime timestamps. `--trim-idle` drops parked rows. QC report → `reports/` |
| `assign_laps.py` | Add `lap_number` from per-lap durations (`--durations`, `--start`) or estimate boundaries from GPS (`--gps`) |

## Notebooks

- `02_Train_Cleaning_Analysis.ipynb` — per-attribute audit of the cleaner on the real test-drive data (NOISE vs NATURAL verdicts, what was fixed and why)
- `03_Script_vs_Real_Cleaning.ipynb` — three-way comparison: raw vs script-cleaned vs manually cleaned reference (script matches the reference 95–100%)
- `data/race_day/exampleAttempt/` — **race-day attempt template** (see below)

### Attempt analysis template (`data/race_day/exampleAttempt/`)

Filled in with `example_attempt_cleaned_laps.csv` (a copy of `data/train_cleaned.csv`,
already lapped) since real race-day telemetry isn't in yet. This folder's structure is
the pattern to copy into each real `attempt_XX/` once its data arrives:

- `00_All_Laps_Summary.ipynb` — cross-lap comparison: summary table, speed/gas-glide/
  efficiency/time bar charts, duty-vs-efficiency scatter, voltage-sag health, total
  attempt numbers (distance-weighted, not a naive per-lap average), auto feedback notes.
  Exports `lap_summary.csv` (one row per lap, the six research-division metrics: speed,
  gas/glide %, real-time consumption, efficiency, time) and `attempt_totals.csv`.
- `lap_XX_analysis.ipynb` (one per lap) — that lap's own time-series deep dive: speed
  curve, gas/glide timeline, real-time consumption curve (unit explained by a priority
  cascade — powerW → V×I → dEnergy/dt → velocity/kmPerkWh proxy → current-only → skip),
  efficiency and time vs. the attempt average, voltage curve.

Both notebook kinds are self-contained templates (`CSV_PATH` + `LAP_NUMBER` at the top) —
regenerate/rerun per attempt by pointing at a new `attempt_XX_cleaned_laps.csv`.

## Layout

```
data/               raw + cleaned CSVs
data/race_day/      attempt_01 … attempt_06 (test-drive day, 6 laps each)
reports/            QC report JSONs (one per cleaning run)
tests/              test_cleaner.py — 15 checks against injected corruption
```

## Race day

See **RACE_DAY_GUIDE.md** for the step-by-step commands per attempt.

Typical flow:

```powershell
python clean_telemetry.py data/race_day/attempt_01/attempt_01.csv --trim-idle
python assign_laps.py data/race_day/attempt_01/attempt_01_cleaned.csv --durations "112,105,108,103,106,104" --start "2026-07-13 08:05:00"
```

Run the tests with: `$env:PYTHONPATH='.'; python tests/test_cleaner.py`
