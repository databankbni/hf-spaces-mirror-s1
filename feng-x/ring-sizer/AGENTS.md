# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Standard Task Workflow

For tasks of implementing **new features**:
1. Read PRD.md, Plan.md, Progress.md before coding
2. Summarize current project state before implementation
3. Carry out the implementatation; after that, build and test if possible
4. Update Progress.md after changes
5. Commit with a clear, concise message

For tasks of **bug fixing**:
1. Summarize the bug, reason and solution before implementation
2. Carry out the implementation to fix the bug; build and test afterwards;
3. Update Progress.md after changes
4. Commit with a clear, concise message

For tasks of **reboot** from a new codex session:
1. Read doc/v0/PRD.md, doc/v0/Plan.md, doc/v0/Progress.md for baseline implementation
2. Read doc/v1/PRD.md, doc/v1/Plan.md, doc/v1/Progress.md for edge refinement (v1)
3. Read doc/v4/PRD.md, doc/v4/Plan.md, doc/v4/Progress.md for SAM 2.1 integration (card + hand)
4. Read doc/v5/PRD.md, doc/v5/Plan.md, doc/v5/Progress.md for the in-browser capture coach (distance + level gates)
5. Read doc/v6/PRD.md, doc/v6/Plan.md, doc/v6/Progress.md for the mobile-native demo surface (`/m`)
6. Read doc/v10/PRD.md, doc/v10/Plan.md, doc/v10/Progress.md for multi-shot session median recommendations
7. Assume this is a continuation of an existing project.
8. Summarize your understanding of the current state and propose the next concrete step without writing code yet.

## Project Overview

Ring Sizer is a **local, terminal-executable computer vision program** that measures the outer width (diameter) of a finger at the ring-wearing zone using a single RGB image. It uses a standard credit card (ISO/IEC 7810 ID-1: 85.60mm × 53.98mm) as a physical size reference for scale calibration.

**Key characteristics:**
- Single image input (JPG/PNG)
- SAM 2.1 for card + hand segmentation; MediaPipe for hand landmarks
- Finger width measured from the SAM mask boundary (`mask` edge method) by default
- Outputs JSON measurement data and optional debug visualization
- No cloud processing, runs entirely locally
- Python 3.8+ with OpenCV, NumPy, MediaPipe, PyTorch, transformers

## Development Commands

### Installation
```bash
# Create virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Running the Program
```bash
# Basic measurement (defaults: index finger, mask edge method, classic card)
python measure_finger.py --input input/test_image.jpg --output output/result.json

# Measure a different finger
python measure_finger.py --input input/test_image.jpg --output output/result.json \
  --finger-index ring

# Save intermediate debug images alongside the result PNG
python measure_finger.py --input input/test_image.jpg --output output/result.json \
  --debug

# Use SAM card detection (first run downloads ~150 MB of weights)
python measure_finger.py --input input/test_image.jpg --output output/result.json \
  --card-method sam

# Subpixel Sobel gradient refinement anchored on the SAM mask boundary
python measure_finger.py --input input/test_image.jpg --output output/result.json \
  --card-method sam --edge-method sobel
```

## Architecture Overview

### Processing Pipeline

1. **Image quality** — blur / brightness / contrast (informational, no hard fail)
2. **Hand segmentation** — MediaPipe landmarks + SAM 2.1 mask (palm-center prompt); image rotated to canonical orientation
3. **Card detection** — classical (default CLI) or SAM prompt-based (web demo); scale calibration to `px_per_cm`
4. **Finger isolation** — per-finger mask from the SAM hand mask + landmark ROI
5. **Finger axis** — landmark-based (`MCP→PIP`, the proximal phalanx); image rotated a second time so the ring zone is vertical
6. **Ring zone** — anatomical mode centered on PIP (from landmarks), or 15–25% percentage mode as fallback
7. **Edge measurement** — `mask` (SAM boundary, default) or `sobel` (subpixel gradient anchored on the SAM boundary)
8. **Confidence** — 4-component weighted score (see below)
9. **Visualization** — result PNG with mask overlays, edges, ring-zone band, measurement text

### Module Structure

| Module | Primary Responsibilities |
|---|---|
| `card_detection.py` | Classical card detection (Canny / adaptive / Otsu / color waterfall), scale calibration |
| `sam_backend.py` | Shared `Sam2Model`/`Sam2Processor` singleton (card + hand) |
| `sam_card_detection.py` | Prompt-based SAM card detection + seed helpers |
| `sam_hand_segmentation.py` | Prompt-based SAM hand mask seeded at palm center |
| `finger_segmentation.py` | MediaPipe landmarks + finger isolation against the SAM hand mask |
| `geometry.py` | Landmark-based axis estimation, ring-zone localization, precise rotation helpers |
| `edge_refinement.py` | `mask_only` boundary measurement + `sobel_only` subpixel gradient path |
| `confidence.py` | Card / finger / measurement / edge-quality scoring + overall confidence |
| `image_quality.py` | Blur (Laplacian variance), exposure, finger-spacing / lighting checks |
| `visualization.py` | Result PNG overlays (card rect, hand silhouette, edges, measurement) |
| `debug_observer.py` | Stage-by-stage debug image writer (single canonical writer) |
| `logging_config.py` | `configure_logging()` + `log_phase()` timing context manager |
| `cli_display.py` | Terminal-only decorative output for the CLI entry point |

### Key Design Decisions

**Ring-wearing zone** — anatomical mode: centered on PIP, width = `ANATOMICAL_ZONE_WIDTH_FACTOR × |MCP–PIP|`. Falls back to 15–25% percentage mode only when landmarks are unavailable.

**Axis estimation** — landmark-only (`estimate_finger_axis_from_landmarks`). Defaults to `linear_fit` which uses the MCP→PIP vector (proximal phalanx). Raises `ValueError` on invalid landmarks (NaN, collapsed, too short, non-monotonic); callers map this to `fail_reason="axis_estimation_failed"`.

**Edge measurement** — `mask` (default) reads per-row finger width directly from the SAM boundary. `sobel` runs bidirectional Sobel + sub-pixel parabola fitting, anchored ±N px on the SAM boundary.

**Confidence scoring** — single 4-component model: card 25%, finger 25%, edge quality 20%, measurement 30%. Levels: HIGH (>0.85), MEDIUM (≥0.6), LOW (<0.6). Defined in `src/confidence_constants.py` as `WEIGHT_*`.

---

## CLI Flags

| Flag | Values | Default | Notes |
|---|---|---|---|
| `--finger-index` | auto, index, middle, ring, pinky | `index` | Which finger to measure; also drives orientation |
| `--mode` | single, multi | `single` | `multi` measures index + middle + ring in one pass |
| `--edge-method` | mask, sobel | `mask` | `mask` reads the SAM boundary; `sobel` adds subpixel gradient refinement anchored on it |
| `--sobel-threshold` | float | 15.0 | Minimum gradient magnitude (sobel mode only) |
| `--sobel-kernel-size` | 3, 5, 7 | 3 | Sobel kernel (sobel mode only) |
| `--no-subpixel` | flag | off | Disable parabola refinement (sobel mode only) |
| `--card-method` | classic, sam | `classic` | CLI default is classical to avoid surprise 150 MB SAM weight download; web demo forces `sam` |
| `--ring-model` | see `src/ring_size.py` | — | Ring-size lookup table |
| `--debug` | flag | off | Write stage debug images next to the result PNG |
| `--skip-card-detection` | flag | off | Test-only: use a dummy scale factor |
| `--no-calibration` | flag | off | Report raw (uncalibrated) diameter |

The v0 contour path and the v1 `auto` / `compare` diagnostic modes were removed during the v4 cleanup; only `mask` and `sobel` remain as edge methods, and the hand mask is always SAM (with an automatic internal fallback to the MediaPipe convex hull if SAM raises).

---

## v4 Architecture (SAM 2.1 Segmentation)

v4 replaces the two fragile detection stages in v0/v1 with Meta's Segment Anything 2.1 (Hiera Small, Apache 2.0, ~150 MB). Both SAM calls are prompt-based so CPU inference stays under ~2 s total per image.

### What's new in v4

- **SAM card detection** — `src/sam_card_detection.py::detect_credit_card_sam_prompt()`. Seeds sampled outside the hand mask; each seed fires a positive prompt + negative prompts at every other seed; candidate masks are filtered by rectangularity (≥0.90), aspect ratio (1.586 ± 15%), and area bounds. ~14× faster than the AMG grid path that originally shipped (AMG has since been removed).
- **SAM hand mask** — `src/sam_hand_segmentation.py::segment_hand_sam()`. Single positive prompt at the palm center (mean of MediaPipe landmarks 0, 5, 9, 13, 17). If SAM raises, the pipeline automatically falls back to a MediaPipe landmark convex hull (kept available under `hand_data["mask_synthetic"]` for debug).
- **`mask` edge method** (default) — measures width directly from the SAM boundary with no Sobel search. `sobel` is a second mode that anchors bidirectional Sobel + subpixel refinement on the SAM boundary (±N px).
- **Shared SAM backend** (`src/sam_backend.py`) — single `Sam2Model` + `Sam2Processor` singleton shared by card + hand. Tries the local HF cache first (`local_files_only=True`) to avoid HEAD-request retry storms.
- **Pipeline ordering** — hand mask runs first; the background complement seeds card detection. Cheap because SAM hand segmentation is ~0.5 s.

### v4 module additions

| Module | Purpose |
|--------|---------|
| `src/sam_backend.py` | Shared Sam2Model/Sam2Processor singleton |
| `src/sam_card_detection.py` | Prompt-based SAM card detection + seed helper |
| `src/sam_hand_segmentation.py` | Prompt-based SAM hand segmentation |

### v4 debug additions

- SAM card mask and SAM hand mask are blended onto the final debug PNG by `src/visualization.py` so the user can see what was actually measured.
- `script/validate_sam_card.py` and `script/compare_hand_sam.py` are offline validation/comparison harnesses for the two SAM stages.

### v4 defaults

| Component | CLI default | Web demo |
|---|---|---|
| `--card-method` | `classic` (avoids surprise 150 MB download) | `sam` (hard-coded) |
| `--edge-method` | `mask` | `mask` (hard-coded) |

Hand mask is always SAM; there is no user-facing flag for it. If SAM raises at runtime, `segment_hand()` silently falls back to the MediaPipe convex hull.

### Ring / pinky handling

For outer fingers the ROI is shrunk and rotation is centered on the proximal phalanx rather than the finger midpoint. `mask_only` measurements (i.e., the `mask` edge method) drop invalid rows and hard-fail if too few valid rows remain, rather than silently returning a low-confidence number.

### Environment flags

- `RING_DISABLE_SUPABASE=1` — opt out of Supabase persistence for local dev runs (the web demo otherwise persists each measurement off the request thread).
- `RING_DEV_TLS_CERT` / `RING_DEV_TLS_KEY` — paths to a local mkcert pair. When both are set, `web_demo/app.py` runs Flask under HTTPS on `0.0.0.0:8000` so a phone on the same LAN can hit the dev server (`getUserMedia` requires a secure context). Unset on HF Space deploys (TLS terminates upstream).

---

## Web demo surfaces

`web_demo/app.py` serves two front-end shells off the same Flask app:

| Route | Template | Notes |
|---|---|---|
| `/` (desktop UA) | `templates/index.html` | Original single-page form + result demo. |
| `/` (mobile UA) | 302 → `/m` | Coarse UA regex (`iphone|ipod|android.+mobile|...`); `?desktop=1` overrides. |
| `/m` | `templates/mobile.html` | v6 paginated six-step flow (intro → form → guide → capture → confirm → result). |
| `/dev`, `/debug` | `templates/index.html` | Desktop with `dev_mode=True` (AI-explanation toggle visible). |
| `/admin` | `templates/admin.html` | Token-gated KOL dashboard. |
| `/feedback` | `templates/feedback.html` | v8 public post-shipment fit-feedback form (all UAs, no redirect). |

`/api/measure` is the single contract both surfaces speak. Any algorithm change in `measure_finger.py` improves both surfaces with zero front-end work. See `doc/v5/` for the in-browser capture coach (distance + level gates) and `doc/v6/` for the mobile flow.

### Post-result feedback (rating + comment)

After a successful run both surfaces show a "How did it go?" panel (5-star rating + optional comment). `POST /api/feedback` attaches them to the existing `measurements` row via `run_id` — there is no separate `feedback` table. Two columns on `measurements`:

| Column | Type | Notes |
|---|---|---|
| `feedback_rating` | `int` (1–5, NULL allowed) | API validates the range; no DB constraint. |
| `feedback_message` | `text` (NULL allowed) | Server caps length at `FEEDBACK_MAX_MESSAGE_LEN = 4000`. |

The endpoint only patches columns the user actually provided (partial submissions don't NULL the other column), retries 6 × 500 ms to absorb the race with the async measurement insert, and returns a real `404` if the row truly isn't there after the retries.

The admin dashboard surfaces this as an **Avg rating** stat card, a **User Ratings** 1★–5★ distribution chart, and per-row **Rating** + **Comment** columns in the records table. `_compute_stats` filters feedback aggregation by `not fail_reason` so any pre-existing ratings on failed runs don't skew `avg_rating`.

The columns were added to the live DB via the Supabase Management API (the repo has no migrations dir); equivalent SQL:

```sql
alter table public.measurements
  add column if not exists feedback_rating int,
  add column if not exists feedback_message text;
```

### KOL identity field: email (the cross-table join key)

Both web surfaces collect a single required identity field, now labelled
**Email** (`type="email"`, `autocomplete="email"`, `inputmode="email"`,
posted as `kol_email`). The server normalizes it **trim + lowercase**.
Email — not name — is the key used to join `measurements` ↔ the v8
`feedback` table ↔ the ops shipping-records CSV (names mis-merge and the
shipping source is email-native). See `doc/v8/PRD.md`.

Two columns on `measurements`:

| Column | Notes |
|---|---|
| `kol_email` | `text`, normalized address; the join key for new rows. |
| `kol_name` | `text`, **legacy only** — pre-email historical rows; NULL on new rows. |

```sql
alter table public.measurements add column if not exists kol_email text;
```

Stored object paths slug the **email local-part only** (`_email_local_part`
in `web_demo/app.py`), never the full address, to keep PII out of bucket
paths. Admin grouping/display and CSV export prefer `kol_email` and fall
back to `kol_name` for legacy rows.

### v10 multi-shot session median

Repeat captures in the same browser session are linked by a client-generated
UUID. The browser carries the previous server-returned session state; Python
adds the current successful calibrated per-finger diameters and computes each
median. The precise median is retained, while a half-up 0.1 mm value is used
for `recommend_ring_size()`; exact midpoint ties prefer the smaller size. Raw
shot fields remain unchanged. The visible result cards prefer the separate
`session_recommendation` object. A single footer below the cards reads
`Based on N measurements of your right/left hand. (For best reliability, take
at least 3 measurements using the same hand.)` The line is left-aligned on
both web surfaces and matches the following feedback hint's `0.95rem` size.
The admin Records table preserves its raw-shot columns and adds a separate
`Session Recommendation` summary column with an on-demand JSON view; legacy
rows display `—` in that column.

Aggregation is partitioned by `handedness + finger + ring_model`; failed
fingers are excluded and exact duplicate images are identified by SHA-256.
Supabase is only an asynchronous audit trail and is never queried on the live
recommendation path. Sessions expire after 30 minutes or when email/model/mode
context changes. See `doc/v10/`.

Additive columns on `measurements`:

| Column | Notes |
|---|---|
| `session_id` | Browser-session UUID; nullable for legacy/non-session clients. |
| `session_attempt_index` | Monotonic request count within the carried state. |
| `image_sha256` | Exact duplicate detection and audit. |
| `session_recommendation` | JSONB snapshot of precise medians, 0.1 mm decision diameters, sizes, counts, and spreads. |

Existing `diameter_cm`, `per_finger`, and `overall_*` fields continue to mean
the current raw shot, not the session median.

### v8 post-shipment feedback (`/feedback` + `feedback` table)

A **separate** flow from the post-result rating above — different
lifecycle (5–7 days after the ring ships, not right after measurement)
and a different table. Don't confuse the two:

| | Post-result rating | v8 fit feedback |
|---|---|---|
| Route (POST) | `/api/feedback` | `/api/fit-feedback` |
| Storage | columns on `measurements` (patched by `run_id`) | new `feedback` table (standalone row) |
| Question | "did the website work?" | "which finger did the shipped ring fit?" |

The `feedback` table is **intentionally decoupled** — no `run_id`, no
foreign key. The only link to `measurements` is the normalized
`kol_email`, joined at analysis time in a pandas notebook (see
`doc/v8/analysis.md`). `GET /feedback` renders `templates/feedback.html`
(single-page form, reuses `mobile.css`; **not** the `/m` step framework).
`POST /api/fit-feedback` normalizes the email, uploads the optional photo
under `feedback/` (local-part slug only, same PII stance), and inserts
via `save_feedback`. The photo upload + insert are **synchronous** (no
heavy compute, unlike `/api/measure`), so the row lands complete. RLS is
enabled on the table (the app's service key bypasses it; this blocks
anon-key reads of the email PII). The admin dashboard has a **Feedback**
tab (`/api/admin/feedback` → `list_feedback`) that lists the rows
read-only; deeper analysis is still pandas-only (`doc/v8/analysis.md`).
Table columns:

```sql
create table public.feedback (
  id uuid primary key default gen_random_uuid(),
  submitted_at timestamptz not null default now(),
  kol_email text not null,          -- normalized join key
  kol_name text,                    -- also captured: legacy KOLs measured
                                    -- pre-email-switch have kol_name (not
                                    -- kol_email) on their measurements row,
                                    -- so name lets their feedback join back
  received_size text, received_model text, best_fit_finger text,
  fit_quality text, hand text, photo_url text, notes text
);
```

---

## Important Technical Details

### What This Measures
The system measures the **external horizontal width** (outer diameter) of the finger at the ring-wearing zone. This is:
- ✅ The width of soft tissue + bone at the ring-wearing position
- ❌ NOT the inner diameter of a ring
- Used as a geometric proxy for downstream ring size mapping (out of scope for v0)

### Coordinate Systems
- Images use standard OpenCV format: (row, col) = (y, x)
- Most geometry functions work in (x, y) format
- Contours are Nx2 arrays in (x, y) format
- Careful conversion needed between formats (see `geometry.py:35`)

### MediaPipe Integration
- Uses pretrained hand landmark detection model (no custom training)
- Provides 21 hand landmarks per hand
- Each finger has 4 landmarks: MCP (base), PIP, DIP, TIP
- Finger indices: 0=thumb, 1=index, 2=middle, 3=ring, 4=pinky
- **Orientation detection**: Uses wrist → specified finger tip to determine hand rotation
- **Automatic rotation**: Image rotated to canonical orientation (wrist at bottom, fingers up) based on selected finger

### Input Requirements
For optimal results:
- Resolution: 1080p or higher recommended
- View angle: Near top-down view
- **Finger**: One finger extended (index, middle, or ring). Specify with `--finger-index`
- Credit card: Must show at least 3 corners, aspect ratio ~1.586
- Finger and card must be on the same plane
- Good lighting, minimal blur

### Failure Modes (values of `fail_reason`)
- `hand_not_detected` — MediaPipe did not locate a hand
- `card_not_detected` — classical or SAM card detector returned nothing
- `card_not_parallel` — card detected but `scale_confidence ≤ 0.95` (too much perspective)
- `card_too_small` — card detected but `longer_side_px / shorter_image_px < 0.33` (camera held too far from the table; see `doc/report/framing_ratio_survey.md`)
- `finger_isolation_failed`, `finger_mask_too_small`, `contour_extraction_failed` — finger segmentation stages
- `axis_estimation_failed` — landmarks missing or failed quality checks (NaN, collapsed, non-monotonic, below min length)
- `zone_localization_failed` — ring zone could not be derived
- `sobel_edge_refinement_failed` — `sobel` mode requested but edge detection raised
- `insufficient_edge_samples_<N>` — `mask` mode: too few valid rows to form a robust median

## Output Format

### JSON Output Structure
```json
{
  "finger_outer_diameter_cm": 1.78,
  "confidence": 0.86,
  "scale_px_per_cm": 42.3,
  "quality_flags": {
    "card_detected": true,
    "finger_detected": true,
    "view_angle_ok": true
  },
  "fail_reason": null
}
```

### Debug Visualization
The result PNG is written alongside every JSON output. With `--debug`, the same sibling directory also gets per-phase subdirs with numbered stage images (`NN_name.png`) produced by a single writer, `DebugObserver`:

- `finger_segmentation_debug/` — MediaPipe landmarks, hand skeleton; `sam_hand/` subdir for SAM mask + overlay
- `card_detection_debug/` (classical) or `sam_card_prompt_debug/` (SAM) — strategy waterfall / prompt points / candidates / final selection
- `edge_refinement_debug/` — ROI, Sobel stages, subpixel refinement, per-row widths (sobel mode)

### Observability

`src/logging_config.py` provides `configure_logging()` (called once by each entry point) and a `log_phase(name, totals)` context manager. All phase timings log as `[phase] name: X ms` through the standard `logger`; `src/` modules use module-level `logging.getLogger(__name__)` exclusively — no `print()`. Terminal-only decorative output (final result summary, "TESTING MODE" banner) lives in `src/cli_display.py` and is imported only by `measure_finger.py` main.

## Code Patterns and Conventions

- Functions raise on malformed inputs; `measure_finger()` maps exceptions to structured `fail_reason` values in the output dict.
- Realistic width range: 1.0–3.0 cm (typical 1.4–2.4 cm). Out-of-range widths log a warning but do not fail.
- Credit card aspect ratio tolerance: ±15% of 1.586. `scale_confidence > 0.95` is required (hard fail `card_not_parallel` otherwise).
- Coordinate convention: OpenCV is `(row, col) = (y, x)`; most `src/geometry.py` helpers use `(x, y)`. Contours are `Nx2` in `(x, y)` format.
