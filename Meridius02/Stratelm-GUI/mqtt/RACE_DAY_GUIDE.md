# Race Day Guide — 2026-07-13

6 attempts, 6 laps each. One raw CSV per attempt, no exceptions —
`log.py` appends per topic, so a leftover file mixes sessions and the
cumulative columns (distance/energy/timeS) get flagged corrupt.

## What to write down at the track (per attempt)

| What | Why | Example |
|---|---|---|
| Race start time | anchors lap assignment exactly | `2026-07-13 08:05:00` |
| Duration of each of the 6 laps, in order, seconds | lap boundaries | `112, 105, 108, 103, 106, 104` |

If the start time is missed, `--gps` can estimate it, but the stopwatch + start
time combo is exact.

## Per attempt (repeat 6×, shown for attempt 1)

**1. Log the attempt.** In one terminal:

```powershell
python log.py
```

Ctrl+C after the attempt ends, then immediately move the file into its slot:

```powershell
Move-Item falcon_telemetry.csv data/race_day/attempt_01/attempt_01.csv
```

(The attempt number in the filename matters — it keeps the six QC reports in
`reports/` from overwriting each other. If the topic/filename differs
tomorrow, move whatever CSV `log.py` created.)

**2. Clean it:**

```powershell
python clean_telemetry.py data/race_day/attempt_01/attempt_01.csv --trim-idle
```

- Output: `data/race_day/attempt_01/attempt_01_cleaned.csv` + `reports/attempt_01_cleaned_report.json`
- Glance at the PER-COLUMN section. `treated_as` shows how renamed
  attributes were matched. A column with no rule you expected to have one
  (or anything UNRELIABLE) → paste the CSV header line to Claude.

**3. Assign the 6 laps** (durations from the stopwatch, in order):

```powershell
python assign_laps.py data/race_day/attempt_01/attempt_01_cleaned.csv --durations "112,105,108,103,106,104" --start "2026-07-13 08:05:00"
```

- Output: `data/race_day/attempt_01/attempt_01_cleaned_laps.csv` with `lap_number`
  and `elapsed_s` added. Rows outside the race window get `lap_number = NaN`
  (warm-up / cool-down) — drop them for analysis with
  `df.dropna(subset=['lap_number'])`.
- Sanity check: the printed rows-per-lap should be roughly proportional to
  each lap's duration.

**4. Cross-check (optional but cheap):**

```powershell
python assign_laps.py data/race_day/attempt_01/attempt_01_cleaned.csv --gps
```

Prints lap durations implied by GPS start-line returns. If they disagree with
the stopwatch by more than a few seconds, trust neither — investigate.

## If things go wrong

| Symptom | Cause / fix |
|---|---|
| Column 100% NaN / UNRELIABLE in report | text or broken format — send the header + a few rows to Claude |
| No `median sample interval` in report | timestamp column not detected or low-resolution — check `ts_column_used` in the JSON report |
| distance/energyWh flagged with many `cumulative_violations` | two sessions in one CSV — the logger file wasn't moved between attempts; split at the reset |
| `--trim-idle` trimmed nothing | velocity column not recognized — send the header |
| Laps look shifted by a few seconds | start time slightly off — re-run `assign_laps.py` with the corrected `--start` (cheap, idempotent) |

## After all 6 attempts

Each `data/race_day/attempt_XX/` should hold `attempt_XX.csv`,
`attempt_XX_cleaned.csv`, `attempt_XX_cleaned_laps.csv`; QC reports accumulate
in `reports/`. Then commit.
