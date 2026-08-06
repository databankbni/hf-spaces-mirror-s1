# Track width digitization (satellite imagery)

Produces `data/track_edges_imagery.csv` (per-5m drivable-corridor edges/width for the
SEM APME Lusail urban track) and `data/track_reference_tum.csv` (TUM
`x_m,y_m,w_tr_right_m,w_tr_left_m` reference-track format for the driving-line
optimizer). Replaces the old constant "12 m" width assumption.

## Method (2026-07-17)

1. **`prep_centerline.py`** — smooth the Shell GPS trace
   (`data/sem_apme_2025-track_coordinates.csv`) with a spline (avg residual ~1.5 m),
   resample to 5 m stations, compute unit normals. 734 stations, 3665 m.
2. **`download_tiles.py`** — Esri World Imagery tiles, zoom 19 (~0.27 m/px at 25.5°N;
   z20 has no real data there), ±35 m corridor → 242 tiles.
   URL: `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}`
3. **`detect_edges2.py`** — at each station, sample RGB every 0.1 m along the ±30 m
   perpendicular; classify asphalt vs not (adaptive brightness/saturation thresholds +
   hue rules for red runoff / blue paint / green decor); anchor on the longest asphalt
   run within ±8 m (the Shell line is off-corridor in places); edge = first sustained
   (≥1.2 m) non-asphalt run outward. White edge lines <1.2 m are ignored (crossable).
4. **Visual QA** (`render_strips.py`, `render_zoom.py`) — all 37 straightened 100 m
   strip maps and plan-view zooms were inspected by eye; systematic misdetections were
   recorded as manual override anchor tables in **`build_final.py`** (~20 spans: pit
   separation band, kart-track junction red tongue, road fork at 1050 m, blue-strip
   section 1160–1440 m, two kart corners where the detector anchored on the adjacent
   service strip, etc.).
5. **`build_final.py`** — overrides + rolling-median outlier cleanup, then the TRUE
   centerline is rebuilt as the midpoint of the two edges (the Shell GPS line hugs an
   edge / cuts corners; median |shift| ≈ 3.9 m, max 10.4 m). Final widths:
   min 5.2 / median 13.3 / max 26.9 m. `render_final.py` renders the verification
   overlay (`final_overview.png`).

## Column meanings (`track_edges_imagery.csv`)

- `station_shell_m` — arc length along the smoothed Shell reference line
- `station_new_m` — arc length along the rebuilt (midpoint) centerline (3685 m loop)
- `lat/lon` — rebuilt centerline point
- `w_left_m` / `w_right_m` — drivable corridor to the left/right of the rebuilt
  centerline (left = left of travel direction)
- `centerline_shift_m` — how far the rebuilt centerline sits left (+) of the Shell line

## Definition of "drivable width" & caveats

- Edge = start of curb / painted runoff (red) / blue-painted strip / sand / wall.
  Painted runoff and curbs are NOT counted as drivable (conservative, track-limits
  style). White boundary lines are treated as crossable (width measured to the curb
  or surface change beyond, when the asphalt continues).
- Sections where the route crosses wide paddock/parking asphalt use the lane the
  route follows, bounded by paint/median markings — not the full apron.
- Imagery georegistration is good (checked vs. grid boxes at start/finish and OSM),
  but treat absolute positions as ±1–2 m. Widths (relative measurements) are better,
  roughly ±0.5–1 m away from shadows.
- Vehicle half-width + safety margin must be subtracted by the consumer
  (driving-line optimizer), NOT baked into this dataset.
