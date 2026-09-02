"""Seat-vs-PIP-knuckle width validation over a folder of hand photos.

For each image: run the real pipeline up through canonical rotation, then
measure two bands on the chosen finger --
  * SEAT    : current anatomical band  [PIP - seg , PIP]            (median)
  * KNUCKLE : PIP-centered band         PIP +/- K_SEG*seg            (median + p90)
-- map each to a ring size, and write
  * an annotated overlay PNG so the seat vs knuckle lines can be eyeballed
  * a row in results.csv

No ground truth is required: this is a visual + tabular comparison to confirm
the knuckle band detects the wider PIP joint on knuckle-dominant fingers.

Usage:
  python script/validate_knuckle.py [input_dir] [--finger index] [--limit N]
"""
import sys
import csv
import argparse
from pathlib import Path

import numpy as np
import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.finger_segmentation import segment_hand, isolate_finger
from src.geometry import (
    estimate_finger_axis, localize_ring_zone_from_landmarks,
    calculate_angle_from_vertical, rotate_image_precise, rotate_axis_data,
    transform_points_rotation,
)
from src.edge_refinement import refine_edges_sobel
from src.card_detection import compute_scale_factor
from src.ring_size import recommend_ring_size
from measure_finger import _sam_card_detect

# --- locked method parameters (per agreed recommendation) ---
K_SEG = 0.4                # knuckle band half-height in units of |DIP-PIP|
SLOPE, INTERCEPT = 0.809353, 0.251506   # src/calibration.json (mask/classic)


def _cal_mm(raw_px, px_per_cm):
    raw_cm = raw_px / px_per_cm
    return (SLOPE * raw_cm + INTERCEPT) * 10.0


def _size(cal_mm):
    rs = recommend_ring_size(cal_mm / 10.0)
    return rs["best_match"] if rs else None


def _band_widths_px(image, axis_data, zone, px_per_cm, landmarks, mask):
    """Return (median_px, p90_px, n) of per-row mask widths over a band."""
    m = refine_edges_sobel(
        image=image, axis_data=axis_data, zone_data=zone,
        scale_px_per_cm=px_per_cm, finger_landmarks=landmarks,
        finger_mask=mask, mask_mode="mask_only",
    )
    ed = m["edge_data"]
    vr = ed["valid_rows"]
    w = (ed["right_edges"][vr] - ed["left_edges"][vr])
    if w.size == 0:
        return None, None, 0
    # same MAD trim the production median uses, so seat matches the real number
    med = np.median(w)
    mad = np.median(np.abs(w - med))
    keep = np.abs(w - med) <= 3 * mad if mad > 0 else np.ones_like(w, bool)
    w = w[keep]
    return float(np.median(w)), float(np.percentile(w, 90)), int(w.size)


def _draw(img, landmarks, seat_c, seat_w, knk_c, knk_w, texts):
    """Draw both width lines + landmarks on a copy, crop tight, return it."""
    vis = img.copy()
    t = max(2, img.shape[1] // 500)
    pts = [seat_c, knk_c] + [tuple(p) for p in landmarks]

    def hline(c, half, color):
        cx, cy = float(c[0]), float(c[1])
        a = (int(cx - half), int(cy)); b = (int(cx + half), int(cy))
        cv2.line(vis, a, b, color, t)
        cv2.circle(vis, a, t + 1, color, -1)
        cv2.circle(vis, b, t + 1, color, -1)
        pts.extend([a, b])

    hline(seat_c, seat_w / 2, (0, 200, 0))      # green = seat
    hline(knk_c, knk_w / 2, (0, 80, 255))       # orange = knuckle
    for name, p in zip(["MCP", "PIP", "DIP", "TIP"], landmarks):
        cv2.circle(vis, (int(p[0]), int(p[1])), t + 2, (255, 255, 0), -1)

    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    pad = int(img.shape[1] * 0.12)
    x0 = max(0, int(min(xs)) - pad); x1 = min(img.shape[1], int(max(xs)) + pad)
    y0 = max(0, int(min(ys)) - pad); y1 = min(img.shape[0], int(max(ys)) + pad)
    crop = vis[y0:y1, x0:x1].copy()

    fs = crop.shape[1] / 700.0
    for i, txt in enumerate(texts):
        y = int(30 * fs) + int(i * 34 * fs)
        cv2.putText(crop, txt, (int(10 * fs), y), cv2.FONT_HERSHEY_SIMPLEX,
                    fs, (0, 0, 0), max(3, int(4 * fs)), cv2.LINE_AA)
        cv2.putText(crop, txt, (int(10 * fs), y), cv2.FONT_HERSHEY_SIMPLEX,
                    fs, (255, 255, 255), max(1, int(2 * fs)), cv2.LINE_AA)
    return crop


def process(path, finger, out_dir):
    image = cv2.imread(str(path))
    if image is None:
        return {"name": path.stem, "fail_reason": "imread_failed"}

    hand = segment_hand(image, finger=finger)
    if hand is None:
        return {"name": path.stem, "fail_reason": "hand_not_detected"}
    img_can = hand.get("canonical_image", image)
    raw_mask = hand.get("mask")

    card = _sam_card_detect(img_can, hand, False, None)
    if card is None:
        return {"name": path.stem, "fail_reason": "card_not_detected"}
    px_per_cm, _ = compute_scale_factor(card["corners"])

    h, w = img_can.shape[:2]
    fd = isolate_finger(hand, finger=finger, image_shape=(h, w))
    if fd is None or fd.get("landmarks") is None:
        return {"name": path.stem, "fail_reason": "finger_isolation_failed"}

    axis = estimate_finger_axis(fd["landmarks"])
    angle = calculate_angle_from_vertical(axis["direction"])
    R = None
    if abs(angle) >= 0.0:
        img_can, R = rotate_image_precise(img_can, angle, (w / 2.0, h / 2.0))
        axis = rotate_axis_data(axis, R)
        lm = transform_points_rotation(fd["landmarks"], R)
        raw_mask = cv2.warpAffine(raw_mask, R, (w, h), flags=cv2.INTER_NEAREST)
    else:
        lm = fd["landmarks"]

    mcp, pip, dip, tip = lm
    seg = float(np.linalg.norm(dip - pip))
    direction = (pip - mcp) / np.linalg.norm(pip - mcp)

    seat = localize_ring_zone_from_landmarks(lm, axis, zone_type="anatomical")
    half = K_SEG * seg
    knuckle = {
        "start_point": (pip - direction * half).astype(np.float32),
        "end_point": (pip + direction * half).astype(np.float32),
        "center_point": pip.astype(np.float32),
        "length": float(2 * half),
        "localization_method": "pip_knuckle",
    }

    seat_med, _, seat_n = _band_widths_px(img_can, axis, seat, px_per_cm, lm, raw_mask)
    knk_med, knk_p90, knk_n = _band_widths_px(img_can, axis, knuckle, px_per_cm, lm, raw_mask)
    if seat_med is None or knk_med is None:
        return {"name": path.stem, "fail_reason": "no_valid_rows"}

    seat_cal = _cal_mm(seat_med, px_per_cm)
    knk_cal = _cal_mm(knk_med, px_per_cm)
    knk_p90_cal = _cal_mm(knk_p90, px_per_cm)
    row = {
        "name": path.stem,
        "finger": finger,
        "scale_px_per_cm": round(px_per_cm, 1),
        "seat_cal_mm": round(seat_cal, 2),
        "seat_size": _size(seat_cal),
        "knuckle_med_cal_mm": round(knk_cal, 2),
        "knuckle_size": _size(knk_cal),
        "knuckle_p90_cal_mm": round(knk_p90_cal, 2),
        "knuckle_p90_size": _size(knk_p90_cal),
        "gap_mm": round(knk_cal - seat_cal, 2),
        "size_up": int((_size(knk_cal) or 0) > (_size(seat_cal) or 0)),
        "fail_reason": "",
    }

    texts = [
        f"seat   {seat_cal:.1f}mm  size {row['seat_size']}",
        f"knuckle {knk_cal:.1f}mm  size {row['knuckle_size']}  (gap {row['gap_mm']:+.1f}mm)",
    ]
    crop = _draw(img_can, lm, seat["center_point"], seat_med,
                 pip, knk_med, texts)
    cv2.imwrite(str(out_dir / f"{path.stem}__cmp.png"), crop)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_dir", nargs="?", default="input/kol_high_quality")
    ap.add_argument("--finger", default="index")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    in_dir = Path(args.input_dir)
    out_dir = Path("output/knuckle_validation")
    out_dir.mkdir(parents=True, exist_ok=True)

    exts = {".jpg", ".jpeg", ".png"}
    images = sorted(p for p in in_dir.iterdir() if p.suffix.lower() in exts)
    if args.limit:
        images = images[:args.limit]

    fields = ["name", "finger", "scale_px_per_cm", "seat_cal_mm", "seat_size",
              "knuckle_med_cal_mm", "knuckle_size", "knuckle_p90_cal_mm",
              "knuckle_p90_size", "gap_mm", "size_up", "fail_reason"]
    rows = []
    for i, p in enumerate(images, 1):
        try:
            r = process(p, args.finger, out_dir)
        except Exception as e:
            r = {"name": p.stem, "fail_reason": f"error:{type(e).__name__}:{e}"}
        rows.append({k: r.get(k, "") for k in fields})
        print(f"[{i}/{len(images)}] {p.stem}: "
              + (r["fail_reason"] if r.get("fail_reason")
                 else f"seat={r['seat_size']} knuckle={r['knuckle_size']} gap={r['gap_mm']:+.1f}mm"),
              flush=True)

    csv_path = out_dir / "results.csv"
    with open(csv_path, "w", newline="") as f:
        wcsv = csv.DictWriter(f, fieldnames=fields)
        wcsv.writeheader()
        wcsv.writerows(rows)

    ok = [r for r in rows if not r["fail_reason"]]
    up = [r for r in ok if r["size_up"]]
    print("\n==== summary ====")
    print(f"processed {len(rows)}, ok {len(ok)}, failed {len(rows) - len(ok)}")
    if ok:
        gaps = [float(r["gap_mm"]) for r in ok]
        print(f"knuckle wider in {sum(g > 0 for g in gaps)}/{len(ok)} images; "
              f"mean gap {np.mean(gaps):+.2f}mm, max {max(gaps):+.2f}mm")
        print(f"knuckle bumps the recommended size up in {len(up)}/{len(ok)} images")
    print(f"overlays + results.csv -> {out_dir}")


if __name__ == "__main__":
    main()
