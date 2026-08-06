"""Step 3 v2: improved edge detection.

Changes vs v1:
- Color exclusions independent of brightness: blue-painted strip (B-dominant),
  dull red/brown separation bands (R-dominant), green decor (G-dominant).
- Robust asphalt core: instead of assuming the centerline sits on asphalt,
  find the longest asphalt-like run within +-8 m and anchor the search there.
  Edges are then walked outward from that run's interior. This fixes stations
  where the Shell GPS sits on paint/blue strip/red runoff.
- Output offsets are still relative to the station centerline (+left).
"""
import numpy as np
import pandas as pd
from PIL import Image

import mosaic

OFF_MAX = 30.0
STEP = 0.1
SUSTAIN_M = 1.2
V_BRIGHT = 45.0
S_SAT = 0.30
CORE_SEARCH_M = 8.0

offs = np.arange(-OFF_MAX, OFF_MAX + 1e-9, STEP)
n_off = len(offs)
i0 = n_off // 2
sustain = int(SUSTAIN_M / STEP)

BLUE_OK_RANGES = [(1150.0, 1445.0)]  # blue-painted lane IS drivable here (user-verified, 11.47 m GT)

st = pd.read_csv("stations.csv")
MLAT = 111132.954 - 559.822 * np.cos(2 * np.radians(st.lat.mean()))
MLON = 111412.84 * np.cos(np.radians(st.lat.mean()))

ribbon = np.zeros((len(st), n_off, 3), dtype=np.uint8)
rows = []

core_mask = np.abs(offs) <= CORE_SEARCH_M

for k, r in st.iterrows():
    la = r.lat + (offs * r.ny) / MLAT
    lo = r.lon + (offs * r.nx) / MLON
    px, py = mosaic.latlon_to_gpx(la, lo)
    rgb = mosaic.sample_rgb(px, py)
    ribbon[k] = rgb.astype(np.uint8)

    R, G, B = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    V = rgb.mean(axis=1)
    mx = rgb.max(axis=1); mn = rgb.min(axis=1)
    S = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)

    blue_ok = any(a <= r.station_m <= b for a, b in BLUE_OK_RANGES)
    blue_rule = ((B > R + 18) & (B > G + 8)) if not blue_ok else np.zeros_like(B, dtype=bool)
    colored = (
        blue_rule |                                # blue paint (drivable in BLUE_OK_RANGES)
        ((R > G + 14) & (R > B + 22)) |            # red / dull red-brown bands
        ((G > R + 10) & (G > B + 10))              # green decor
    )

    # provisional asphalt reference: median of non-colored samples in the core window
    core_ok = core_mask & ~colored
    v_core = V[core_ok]; s_core = S[core_ok]
    v_ref = np.median(v_core) if len(v_core) > 10 else np.median(V[core_mask])
    s_ref = np.median(s_core) if len(s_core) > 10 else np.median(S[core_mask])
    s_thr = max(S_SAT, s_ref + 0.15)

    nonasphalt = colored | (V > v_ref + V_BRIGHT) | (S > s_thr)

    # longest asphalt run within the core search window -> anchor
    best_len, best_start, cur_len, cur_start = 0, None, 0, None
    lo_i = np.searchsorted(offs, -CORE_SEARCH_M)
    hi_i = np.searchsorted(offs, CORE_SEARCH_M)
    for i in range(lo_i, hi_i):
        if not nonasphalt[i]:
            if cur_len == 0:
                cur_start = i
            cur_len += 1
            if cur_len > best_len:
                best_len, best_start = cur_len, cur_start
        else:
            cur_len = 0
    if best_start is None:
        anchor = i0
    else:
        anchor = best_start + best_len // 2

    # refine reference from a window around the anchored run, then re-threshold
    a_lo = max(0, anchor - int(3.0 / STEP)); a_hi = min(n_off, anchor + int(3.0 / STEP))
    seg = ~colored[a_lo:a_hi]
    if seg.sum() > 5:
        v_ref = np.median(V[a_lo:a_hi][seg])
        s_thr = max(S_SAT, np.median(S[a_lo:a_hi][seg]) + 0.15)
    nonasphalt = colored | (V > v_ref + V_BRIGHT) | (S > s_thr)

    def walk(direction, start):
        run = 0; run_start = None
        rng = range(start, n_off) if direction > 0 else range(start, -1, -1)
        for i in rng:
            if nonasphalt[i]:
                if run == 0:
                    run_start = i
                run += 1
                if run >= sustain:
                    return offs[run_start]
            else:
                run = 0
        return OFF_MAX * direction

    e_left = walk(+1, anchor)
    e_right = walk(-1, anchor)
    rows.append({
        "station_m": r.station_m,
        "off_left_m": e_left, "off_right_m": e_right,
        "width_m": e_left - e_right,
        "anchor_off_m": offs[anchor],
        "flag_left_open": abs(e_left) >= OFF_MAX - STEP,
        "flag_right_open": abs(e_right) >= OFF_MAX - STEP,
    })
    if k % 100 == 0:
        print(f"s={int(r.station_m):4d}  L={e_left:+6.1f} R={e_right:+6.1f} w={e_left-e_right:5.1f}  anchor={offs[anchor]:+.1f}")

ed = pd.DataFrame(rows)
ed.to_csv("edges_raw.csv", index=False)
print("\nwidth stats:", ed.width_m.describe().round(1).to_dict())
print("open flags:", ed.flag_left_open.sum(), "left,", ed.flag_right_open.sum(), "right")

ann = ribbon.copy()
for k in range(len(ed)):
    for off, col in ((ed.off_left_m[k], (255, 0, 255)), (ed.off_right_m[k], (0, 255, 255)),
                     (ed.anchor_off_m[k], (255, 255, 0))):
        j = int(round((off + OFF_MAX) / STEP))
        ann[k, max(0, j - 2):j + 3] = col
Image.fromarray(ann).save("ribbon_annot.png")
print("ribbon_annot.png saved")
