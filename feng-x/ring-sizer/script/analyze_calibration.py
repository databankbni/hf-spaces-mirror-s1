#!/usr/bin/env python3
"""Analysis & regression script for calibration dataset.

Performs:
1. px/cm stability analysis
2. A vs B repeatability
3. Ground truth sanity check (π×diameter vs circumference)
4. Scatter plot & bias analysis
5. Linear regression with leave-one-person-out cross-validation
"""

import json
import math
import os
from pathlib import Path

import numpy as np

# Optional: matplotlib for plots (skip gracefully if missing)
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_PLT = True
except ImportError:
    HAS_PLT = False
    print("Warning: matplotlib not available, skipping plots")


def load_results(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def analyze_scale_stability(results: list[dict]):
    """Phase 3a: px/cm stability across all images."""
    section("1. Card Detection / px/cm Stability")

    scales = {}
    for r in results:
        img = r["image"]
        if img not in scales and r["cv_scale_px_per_cm"]:
            scales[img] = r["cv_scale_px_per_cm"]

    vals = list(scales.values())
    mean_s = np.mean(vals)
    std_s = np.std(vals)
    cv_pct = (std_s / mean_s) * 100

    print(f"  Images analyzed: {len(scales)}")
    print(f"  Mean px/cm:  {mean_s:.2f}")
    print(f"  Std px/cm:   {std_s:.2f}")
    print(f"  CV%:         {cv_pct:.2f}%")
    print(f"  Range:       {min(vals):.2f} — {max(vals):.2f}")
    print(f"  Max spread:  {max(vals)-min(vals):.2f} px/cm ({(max(vals)-min(vals))/mean_s*100:.2f}%)")

    # Per-image table
    print(f"\n  {'Image':<16} {'px/cm':>8} {'Δ from mean':>12}")
    print(f"  {'-'*38}")
    for img, s in sorted(scales.items()):
        print(f"  {img:<16} {s:>8.2f} {s-mean_s:>+12.2f}")

    return mean_s, std_s


def analyze_repeatability(results: list[dict]):
    """Phase 3b: A vs B repeatability."""
    section("2. A vs B Repeatability")

    # Group by (person, finger)
    pairs = {}
    for r in results:
        key = (r["person"], r["finger_en"])
        if key not in pairs:
            pairs[key] = {}
        pairs[key][r["shot"]] = r["cv_diameter_cm"]

    diffs = []
    print(f"  {'Person':<10} {'Finger':<8} {'Shot A':>8} {'Shot B':>8} {'Δ(B-A)':>8} {'%diff':>7}")
    print(f"  {'-'*53}")
    for (person, finger), shots in sorted(pairs.items()):
        a = shots.get("A")
        b = shots.get("B")
        if a and b:
            d = b - a
            pct = abs(d) / ((a + b) / 2) * 100
            diffs.append(abs(d))
            print(f"  {person:<10} {finger:<8} {a:>8.3f} {b:>8.3f} {d:>+8.3f} {pct:>6.1f}%")

    if diffs:
        print(f"\n  Mean |A-B| difference: {np.mean(diffs):.4f} cm")
        print(f"  Max  |A-B| difference: {max(diffs):.4f} cm")
        print(f"  Std  |A-B| difference: {np.std(diffs):.4f} cm")
        print(f"  95th percentile:       {np.percentile(diffs, 95):.4f} cm")

    return diffs


def check_ground_truth_sanity(results: list[dict]):
    """Phase 3c: Check π×diameter ≈ circumference."""
    section("3. Ground Truth Sanity (π×diameter vs circumference)")

    seen = set()
    diffs = []
    print(f"  {'Person':<10} {'Finger':<6} {'Diam':>6} {'Circ':>6} {'π×D':>6} {'Δ':>7} {'%err':>6}")
    print(f"  {'-'*55}")

    for r in results:
        key = (r["person"], r["finger_cn"])
        if key in seen:
            continue
        seen.add(key)

        d = r["gt_diameter_cm"]
        c = r["gt_circumference_cm"]
        if d and c:
            pi_d = math.pi * d
            diff = c - pi_d
            pct = diff / c * 100
            diffs.append(diff)
            print(f"  {r['person']:<10} {r['finger_cn']:<6} {d:>6.2f} {c:>6.1f} {pi_d:>6.2f} {diff:>+7.2f} {pct:>+5.1f}%")

    if diffs:
        print(f"\n  Mean (circ - π×diam): {np.mean(diffs):+.3f} cm")
        print(f"  This is expected: circumference > π×diameter because")
        print(f"  fingers are not perfect circles (slightly oval/flattened).")


def bias_analysis(results: list[dict]):
    """Phase 4a: Scatter plot and bias analysis."""
    section("4. Accuracy & Bias Analysis")

    valid = [r for r in results if r["cv_diameter_cm"] and r["gt_diameter_cm"]]
    cv = np.array([r["cv_diameter_cm"] for r in valid])
    gt = np.array([r["gt_diameter_cm"] for r in valid])
    errors = cv - gt
    pct_errors = errors / gt * 100

    print(f"  N = {len(valid)} measurements")
    print(f"  Mean error (CV-GT):    {np.mean(errors):+.4f} cm")
    print(f"  Median error:          {np.median(errors):+.4f} cm")
    print(f"  Std of error:          {np.std(errors):.4f} cm")
    print(f"  Mean % error:          {np.mean(pct_errors):+.1f}%")
    print(f"  MAE (absolute):        {np.mean(np.abs(errors)):.4f} cm")
    print(f"  Max error:             {np.max(np.abs(errors)):.4f} cm")
    print(f"  RMSE:                  {np.sqrt(np.mean(errors**2)):.4f} cm")

    # Correlation
    corr = np.corrcoef(cv, gt)[0, 1]
    print(f"  Pearson r:             {corr:.4f}")
    print(f"  R²:                    {corr**2:.4f}")

    return cv, gt, errors


def linear_regression(cv: np.ndarray, gt: np.ndarray, results: list[dict]):
    """Phase 4b: OLS regression + leave-one-person-out CV."""
    section("5. Linear Regression Calibration")

    # Fit: gt = a * cv + b
    A = np.vstack([cv, np.ones(len(cv))]).T
    (a, b), residuals, _, _ = np.linalg.lstsq(A, gt, rcond=None)

    calibrated = a * cv + b
    cal_errors = calibrated - gt

    print(f"  Model: actual = {a:.4f} × measured + {b:.4f}")
    print(f"  (i.e., slope={a:.4f}, intercept={b:.4f})")
    print(f"\n  After calibration:")
    print(f"  Mean error:  {np.mean(cal_errors):+.4f} cm")
    print(f"  MAE:         {np.mean(np.abs(cal_errors)):.4f} cm")
    print(f"  Max error:   {np.max(np.abs(cal_errors)):.4f} cm")
    print(f"  RMSE:        {np.sqrt(np.mean(cal_errors**2)):.4f} cm")

    # Sanity check: a slope ≈ 1 AND intercept ≈ 0 usually means the input data
    # was already calibrated upstream (e.g. batch_measure.py read the calibrated
    # finger_outer_diameter_cm field instead of raw_diameter_cm). The regression
    # then picks up residual noise only and is meaningless as a calibration fit.
    # See doc/v2/Progress.md (2026-04-20 entry) for the incident this guards.
    if abs(a - 1.0) < 0.03 and abs(b) < 0.02:
        print()
        print("  " + "!" * 56)
        print("  ! WARNING: slope ≈ 1 AND intercept ≈ 0 — looks like identity. !")
        print("  ! This usually means the input batch_results.json was already !")
        print("  ! calibrated upstream. Re-run batch_measure.py with           !")
        print("  ! --no-calibration (or verify 'calibration_applied_upstream'  !")
        print("  ! is false in the JSON) before trusting these coefficients.  !")
        print("  " + "!" * 56)

    # Leave-one-person-out cross-validation
    section("6. Leave-One-Person-Out Cross-Validation")

    persons = sorted(set(r["person"] for r in results if r["cv_diameter_cm"] and r["gt_diameter_cm"]))
    all_cv_errors = []
    all_cv_cal_errors = []

    print(f"  {'Person':<10} {'N':>3} {'a':>7} {'b':>7} {'MAE_raw':>8} {'MAE_cal':>8} {'Max_cal':>8}")
    print(f"  {'-'*57}")

    for holdout in persons:
        # Train on all except holdout
        train = [r for r in results
                 if r["cv_diameter_cm"] and r["gt_diameter_cm"] and r["person"] != holdout]
        test = [r for r in results
                if r["cv_diameter_cm"] and r["gt_diameter_cm"] and r["person"] == holdout]

        train_cv = np.array([r["cv_diameter_cm"] for r in train])
        train_gt = np.array([r["gt_diameter_cm"] for r in train])
        test_cv = np.array([r["cv_diameter_cm"] for r in test])
        test_gt = np.array([r["gt_diameter_cm"] for r in test])

        A_train = np.vstack([train_cv, np.ones(len(train_cv))]).T
        (a_fold, b_fold), _, _, _ = np.linalg.lstsq(A_train, train_gt, rcond=None)

        test_cal = a_fold * test_cv + b_fold
        raw_errors = np.abs(test_cv - test_gt)
        cal_errors_fold = np.abs(test_cal - test_gt)

        all_cv_errors.extend(raw_errors.tolist())
        all_cv_cal_errors.extend(cal_errors_fold.tolist())

        print(f"  {holdout:<10} {len(test):>3} {a_fold:>7.4f} {b_fold:>+7.4f} "
              f"{np.mean(raw_errors):>8.4f} {np.mean(cal_errors_fold):>8.4f} "
              f"{np.max(cal_errors_fold):>8.4f}")

    all_cv_errors = np.array(all_cv_errors)
    all_cv_cal_errors = np.array(all_cv_cal_errors)

    print(f"\n  Cross-validated results (all holdout predictions):")
    print(f"  Raw  MAE: {np.mean(all_cv_errors):.4f} cm")
    print(f"  Cal  MAE: {np.mean(all_cv_cal_errors):.4f} cm")
    print(f"  Raw  RMSE: {np.sqrt(np.mean(all_cv_errors**2)):.4f} cm")
    print(f"  Cal  RMSE: {np.sqrt(np.mean(all_cv_cal_errors**2)):.4f} cm")
    print(f"  Improvement: {(1 - np.mean(all_cv_cal_errors)/np.mean(all_cv_errors))*100:.1f}% reduction in MAE")

    return a, b


def generate_plots(cv: np.ndarray, gt: np.ndarray, a: float, b: float, out_dir: str):
    """Generate scatter plot and residual plot."""
    if not HAS_PLT:
        return

    section("7. Generating Plots")

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    # 1. Scatter: CV vs GT with regression line
    ax = axes[0]
    ax.scatter(cv, gt, alpha=0.6, s=30, label="Measurements")
    lim = [min(cv.min(), gt.min()) - 0.1, max(cv.max(), gt.max()) + 0.1]
    ax.plot(lim, lim, "k--", alpha=0.3, label="y=x (perfect)")
    x_fit = np.linspace(lim[0], lim[1], 100)
    ax.plot(x_fit, a * x_fit + b, "r-", linewidth=2,
            label=f"Fit: y={a:.3f}x{b:+.3f}")
    ax.set_xlabel("CV Measured Diameter (cm)")
    ax.set_ylabel("Actual Diameter (cm)")
    ax.set_title("CV Measured vs Actual (Caliper)")
    ax.legend(fontsize=8)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)

    # 2. Error distribution
    ax = axes[1]
    errors = cv - gt
    cal_errors = (a * cv + b) - gt
    ax.hist(errors, bins=15, alpha=0.5, label=f"Raw (μ={np.mean(errors):+.3f})")
    ax.hist(cal_errors, bins=15, alpha=0.5, label=f"Calibrated (μ={np.mean(cal_errors):+.3f})")
    ax.axvline(0, color="k", linestyle="--", alpha=0.3)
    ax.set_xlabel("Error (cm)")
    ax.set_ylabel("Count")
    ax.set_title("Error Distribution: Before vs After Calibration")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    # 3. Residuals vs predicted
    ax = axes[2]
    calibrated = a * cv + b
    ax.scatter(calibrated, cal_errors, alpha=0.6, s=30)
    ax.axhline(0, color="k", linestyle="--", alpha=0.3)
    ax.set_xlabel("Calibrated Diameter (cm)")
    ax.set_ylabel("Residual (cm)")
    ax.set_title("Residuals After Calibration")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plot_path = os.path.join(out_dir, "calibration_analysis.png")
    plt.savefig(plot_path, dpi=150)
    print(f"  Saved plot: {plot_path}")
    plt.close()


def main():
    base_dir = Path(__file__).resolve().parent.parent
    results_path = base_dir / "output" / "batch" / "batch_results.json"
    out_dir = str(base_dir / "output" / "batch")

    results = load_results(str(results_path))
    print(f"Loaded {len(results)} results")

    # Phase 3
    analyze_scale_stability(results)
    analyze_repeatability(results)
    check_ground_truth_sanity(results)

    # Phase 4
    cv, gt, errors = bias_analysis(results)
    a, b = linear_regression(cv, gt, results)
    generate_plots(cv, gt, a, b, out_dir)

    # Summary
    section("SUMMARY — Calibration Coefficients")
    print(f"  actual_diameter = {a:.6f} × measured_diameter + ({b:.6f})")
    print(f"  slope  (a) = {a:.6f}")
    print(f"  offset (b) = {b:.6f}")
    print(f"\n  Save these to the pipeline configuration.")

    # Write coefficients to file
    coeff_path = os.path.join(out_dir, "calibration_coefficients.json")
    with open(coeff_path, "w") as f:
        json.dump({
            "slope": round(a, 6),
            "intercept": round(b, 6),
            "description": "actual = slope * measured + intercept",
            "n_samples": len(cv),
            "dataset": "input/sample (10 people × 3 fingers × 2 shots)",
        }, f, indent=2)
    print(f"  Saved coefficients: {coeff_path}")


if __name__ == "__main__":
    main()
