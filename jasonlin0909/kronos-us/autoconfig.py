"""
Per-ticker auto-configuration + trust report.

Instead of guessing lookback/T, this searches a small grid by *walk-forward evidence* on
the ticker's own recent history, rejects configs whose fed window violates Kronos'
normalisation assumption (wide price range), and picks the one that best beats a
random-walk baseline. It writes a profile JSON the dashboard consumes so every served
forecast carries a validated track record, a calibrated band, and an honest verdict.

Example
-------
  python us/autoconfig.py --ticker COHR --pred_len 20 --n_windows 6 --n_paths 15
  python us/autoconfig.py --ticker AAPL          # defaults

Note: this is an *offline* step (grid x windows x paths predictions ~ minutes on CPU).
The result is cached; serving then loads it instantly.
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from predict_us import fetch_ohlcv
from engine import get_predictor, _RANGE_THRESH
import validation


def profile_path(outdir: Path, ticker: str, interval: str) -> Path:
    return outdir / f"{ticker.upper()}_{interval}.json"


def _num(x, default):
    """None/NaN -> a sentinel so it sorts as the worst option."""
    return x if isinstance(x, (int, float)) and x == x else default


def select_best(results: list, objective: str = "blend") -> dict:
    """
    Pick a config (all objectives reject out-of-distribution windows first):
      * blend : (default) among in-distribution configs that beat a random walk
                (skill < 1.1), take the lowest MAPE — MAPE-driven but guarded against
                persistence-mimics / normalisation-broken windows.
      * mape  : lowest MAPE (naive: a 'tomorrow = today' mimic also scores low).
      * skill : lowest skill_vs_rw (best at genuinely beating persistence).
      * ic    : highest Information Coefficient (predicted-vs-realised return correlation)
                — how the Kronos paper judges skill; direction/ranking, not price level.
      * dir   : highest directional accuracy.
    """
    def key(r):
        ind = 0 if r["_in_distribution"] else 1
        m = r["metrics"]
        mape = _num(m.get("MAPE%"), 1e9)
        skill = _num(m.get("skill_vs_rw"), 1e9)
        ic = _num(m.get("IC"), -1e9)
        da = _num(m.get("DirAcc%"), -1e9)
        if objective == "mape":
            return (ind, mape)
        if objective == "skill":
            return (ind, skill, mape)
        if objective == "ic":
            return (ind, -ic)
        if objective == "dir":
            return (ind, -da)
        competitive = 0 if skill < 1.1 else 1
        return (ind, competitive, mape)
    return sorted(results, key=key)[0]


def _grade(sel: dict) -> dict:
    """Turn the selected config's evidence into an honest verdict."""
    m = sel["metrics"]
    in_dist = sel["_in_distribution"]
    skill = _num(m.get("skill_vs_rw"), 1e9)
    da = _num(m.get("DirAcc%"), 0.0)
    ic = _num(m.get("IC"), float("nan"))
    reasons = []

    if not in_dist:
        reasons.append(f"視窗價格範圍 {sel['validity']['range_ratio_mean']}× 超出 Kronos "
                       f"正規化可靠區(≥{_RANGE_THRESH}×),預測可能失真")
        return {"grade": "D", "trust": "unreliable-ood", "reasons": reasons}

    reasons.append(f"vs 隨機漫步 skill={skill:.2f}（<1 才算贏過『明天=今天』）")
    reasons.append(f"方向命中 {da:.0f}%（50% 為亂猜）"
                   + (f" · IC={ic:.2f}" if ic == ic else ""))
    if skill < 0.97 and da >= 55:
        grade, trust = "A", "usable"
    elif skill < 1.0:
        grade, trust = "B", "marginal"
    elif skill <= 1.05:
        grade, trust = "C", "no-edge"
        reasons.append("點預測未能勝過隨機漫步 → 別當方向訊號用,只看校準後的區間")
    else:
        grade, trust = "D", "worse-than-naive"
        reasons.append("比隨機漫步還差 → 不建議使用此預測")
    return {"grade": grade, "trust": trust, "reasons": reasons}


def run_ticker(predictor, df, ticker, interval, period, pred_len, lookbacks, temps,
               top_p, n_paths, n_windows, n_outer, target_coverage, objective, seed,
               verbose=False) -> dict:
    """
    Nested walk-forward for one ticker → JSON trust profile.

    Rolling origins are split in time: the earlier *inner* windows drive config selection
    and band-scale calibration; the most recent *outer* windows — which the selection never
    saw — are used ONLY to report the honest track record. This removes the selection-bias
    optimism you'd get from grading a config on the same windows you picked it with.
    """
    max_lb = max(lookbacks)
    windows = validation.make_windows(len(df), max_lb, pred_len, n_windows)
    if len(windows) < n_outer + 2:
        raise ValueError(f"need >= {n_outer + 2} windows to nest; got {len(windows)} "
                         f"(raise --n_windows or --period)")
    n_inner = len(windows) - n_outer

    configs = []
    for lb in lookbacks:
        if len(df) < max_lb + pred_len * 2:
            continue
        for T in temps:
            recs = validation.run_windows(predictor, df, lb, pred_len, T=T, top_p=top_p,
                                          n_paths=n_paths, windows=windows, seed=seed)
            if len(recs) < len(windows):
                continue
            inner, outer = recs[:n_inner], recs[n_inner:]
            r_in = validation.aggregate(inner, target_coverage)   # fits band_scale on inner
            item = {"config": {"lookback": lb, "pred_len": pred_len, "T": T, "top_p": top_p,
                               "top_k": 0, "n_paths": n_paths},
                    "metrics": r_in["metrics"], "calibration": r_in["calibration"],
                    "validity": r_in["validity"], "n_windows": r_in["n_windows"],
                    "_in_distribution": r_in["validity"]["range_ratio_mean"] < _RANGE_THRESH,
                    "_outer": outer}
            configs.append(item)
            if verbose:
                m = r_in["metrics"]
                print(f"  [inner] lb={lb:>3} T={T}  MAPE={m['MAPE%']}% skill={m['skill_vs_rw']} "
                      f"IC={m['IC']} Dir={m['DirAcc%']}%  range={item['validity']['range_ratio_mean']}x"
                      f"{'' if item['_in_distribution'] else '  ⚠OOD'}")
    if not configs:
        raise ValueError("no runnable configs (need more history / smaller pred_len)")

    sel = select_best(configs, objective)
    # honest report: apply the inner-fitted band scale to the untouched outer windows
    r_out = validation.aggregate(sel["_outer"], target_coverage,
                                 band_scale=sel["calibration"]["band_scale"])
    verdict = _grade({"metrics": r_out["metrics"], "_in_distribution": sel["_in_distribution"],
                      "validity": r_out["validity"]})

    return {
        "ticker": ticker.upper(), "interval": interval, "period": period,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "objective": objective,
        "validation": {"scheme": "nested", "n_windows": len(windows),
                       "n_inner": n_inner, "n_outer": n_outer},
        "recommended": {"lookback": sel["config"]["lookback"], "pred_len": pred_len,
                        "T": sel["config"]["T"], "top_p": sel["config"]["top_p"],
                        "top_k": 0, "n_paths": n_paths},
        "calibration": {"target_coverage": target_coverage,
                        "band_scale": sel["calibration"]["band_scale"],
                        "coverage_raw": r_out["calibration"]["coverage_raw"],
                        "coverage_calibrated": r_out["calibration"]["coverage_calibrated"]},
        "track_record": {**r_out["metrics"], "n_windows": n_outer,
                         "note": "honest: outer windows the selection never saw"},
        "selection_metrics": {**sel["metrics"], "n_windows": n_inner},
        "validity": {**sel["validity"], "in_distribution": sel["_in_distribution"],
                     "range_thresh": _RANGE_THRESH},
        "verdict": verdict,
        "all_configs": [
            {"lookback": c["config"]["lookback"], "T": c["config"]["T"],
             **c["metrics"], **c["calibration"],
             "range_ratio_mean": c["validity"]["range_ratio_mean"],
             "in_distribution": c["_in_distribution"]}
            for c in configs],
    }


def main():
    try:  # Windows consoles default to cp950/utf-16; make Chinese output readable
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", default="AAPL")
    ap.add_argument("--interval", default="1d")
    ap.add_argument("--period", default="5y")
    ap.add_argument("--pred_len", type=int, default=20)
    ap.add_argument("--n_windows", type=int, default=8, help="total rolling origins (inner+outer)")
    ap.add_argument("--n_outer", type=int, default=3, help="most-recent windows held out for the honest report")
    ap.add_argument("--n_paths", type=int, default=15, help="ensemble size (also used for serving, keeps calibration valid)")
    ap.add_argument("--lookbacks", default="60,120,240,400")
    ap.add_argument("--temps", default="0.7,1.0")
    ap.add_argument("--top_p", type=float, default=0.9)
    ap.add_argument("--target_coverage", type=float, default=0.8)
    ap.add_argument("--objective", choices=["blend", "mape", "skill", "ic", "dir"], default="blend",
                    help="blend=lowest MAPE among in-dist configs that beat RW; ic=max Information Coefficient; dir=max direction")
    ap.add_argument("--seed", type=int, default=123)
    ap.add_argument("--outdir", default=str(Path(__file__).resolve().parent / "out" / "profiles"))
    args = ap.parse_args()

    lookbacks = [int(x) for x in args.lookbacks.split(",") if x.strip()]
    temps = [float(x) for x in args.temps.split(",") if x.strip()]

    df = fetch_ohlcv(args.ticker, args.interval, args.period)
    print(f"[data] {args.ticker} {args.interval}: {len(df)} bars -> {df['timestamps'].iloc[-1].date()}")
    predictor = get_predictor()

    grid = len(lookbacks) * len(temps)
    print(f"[search] {grid} configs x {args.n_windows} windows x {args.n_paths} paths "
          f"(nested: {args.n_windows-args.n_outer} inner / {args.n_outer} outer)\n")

    t0 = time.time()
    profile = run_ticker(predictor, df, args.ticker, args.interval, args.period,
                         args.pred_len, lookbacks, temps, args.top_p, args.n_paths,
                         args.n_windows, args.n_outer, args.target_coverage,
                         args.objective, args.seed, verbose=True)

    outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)
    pth = profile_path(outdir, args.ticker, args.interval)
    pth.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")

    rec = profile["recommended"]; v = profile["verdict"]
    tr = profile["track_record"]; sm = profile["selection_metrics"]; c = profile["calibration"]
    print(f"\n=== TRUST REPORT · {profile['ticker']} (objective={args.objective}) ===")
    print(f"grade {v['grade']}  ({v['trust']})")
    for r in v["reasons"]:
        print("  -", r)
    print(f"recommended: lookback={rec['lookback']} T={rec['T']} top_p={rec['top_p']} "
          f"pred_len={rec['pred_len']} n_paths={rec['n_paths']}")
    print(f"HONEST (outer {tr['n_windows']} win, unseen): MAPE={tr['MAPE%']}% "
          f"skill={tr['skill_vs_rw']} IC={tr['IC']} Dir={tr['DirAcc%']}% "
          f"cover={c['coverage_calibrated']*100:.0f}%")
    print(f"selection (inner {sm['n_windows']} win, optimistic): MAPE={sm['MAPE%']}% "
          f"skill={sm['skill_vs_rw']} IC={sm['IC']}")
    print(f"[done] {time.time()-t0:.0f}s  profile -> {pth}")


if __name__ == "__main__":
    main()
