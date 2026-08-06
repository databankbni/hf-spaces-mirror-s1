#!/usr/bin/env python3
"""research/ml_backtest.py — accuracy backtest for the ml_predictor model.

Evaluates the trained quantile model on the TRUE out-of-sample rows (dates on/after
manifest.holdout_start) already present in ml_predictor/training_data.csv — those rows
carry both the point-in-time features AND the realized forward excursions
(up_INTRADAY/dn_INTRADAY/up_1D/dn_1D/up_3D/dn_3D), so grading needs no re-fetch.

It reuses the model's OWN derivation (MLPredictor._predict_tf, the exact production path,
called with a normalized price=100) and grades with _graded_hit / _evaluate_intraday_hit —
copied verbatim from research/backtest.py so ML numbers are directly comparable to the LLM's.

Metrics per timeframe (and per confidence bucket):
  • direction accuracy (predicted 3-class == realized 3-class)
  • direction_hit / graded hit rate (MIDPOINT_HIT / RANGE_HIT / MISS)
  • estimated-high MAE & bias (up_q90 vs realized max-up)
  • quantile calibration/coverage (up_q90 ≈90%, down_q10 ≈90% below) + pinball loss
  • dip-level-reached % (bearish) and stop-would-hit %

Usage (after dataset.py + train.py):
    python research/ml_backtest.py
    python research/ml_backtest.py --csv ml_predictor/training_data.csv
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from ml_predictor.features import FEATURE_COLUMNS, TIMEFRAMES  # noqa: E402
from ml_predictor.infer import MLPredictor  # noqa: E402

DEFAULT_CSV = os.path.join(_PROJ_ROOT, "ml_predictor", "training_data.csv")
OUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ml_backtest_results.csv")

_UP = {"INTRADAY": "up_INTRADAY", "1D": "up_1D", "3D": "up_3D"}
_DN = {"INTRADAY": "dn_INTRADAY", "1D": "dn_1D", "3D": "dn_3D"}
_DIRC = {"INTRADAY": "dir_INTRADAY", "1D": "dir_1D", "3D": "dir_3D"}


# ── Grading — copied verbatim from research/backtest.py (kept in sync) ─────────
def _evaluate_intraday_hit(direction, price, target_lo, target_hi, max_up, min_down, tf_label, ret_for_tf):
    direction = (direction or "NEUTRAL").upper()
    try:
        target_point = (float(target_lo) + float(target_hi)) / 2.0
        req_move = (target_point / float(price) - 1.0) * 100.0
    except Exception:
        req_move = float("nan")
    if direction == "BULLISH":
        direction_hit = max_up > 0
        target_hit = direction_hit and (not pd.isna(req_move)) and (req_move >= 0) and (max_up >= req_move)
        return direction_hit, target_hit
    if direction == "BEARISH":
        direction_hit = min_down < 0
        target_hit = direction_hit and (not pd.isna(req_move)) and (req_move <= 0) and (min_down <= req_move <= max_up)
        return direction_hit, target_hit
    if direction == "NEUTRAL":
        neutral_caps = {"INTRADAY": 0.90, "1D": 1.0, "3D": 1.0, "5D": 1.0}
        cap = neutral_caps.get(tf_label, 1.0)
        direction_hit = (abs(ret_for_tf) <= cap)
        target_hit = (direction_hit and (not pd.isna(req_move)) and (abs(req_move) <= cap / 3.0)
                      and (min_down <= req_move <= max_up))
        return direction_hit, target_hit
    return False, False


def _graded_hit(direction, price, target_lo, target_hi, max_up, min_down) -> str:
    try:
        d = (direction or "NEUTRAL").upper()
        lo_pct = (float(target_lo) / float(price) - 1.0) * 100.0
        hi_pct = (float(target_hi) / float(price) - 1.0) * 100.0
        mid_pct = (lo_pct + hi_pct) / 2.0
    except Exception:
        return "MISS"
    if d in ("BULLISH", "SLIGHTLY BULLISH"):
        if max_up >= mid_pct:
            return "MIDPOINT_HIT"
        if max_up >= lo_pct:
            return "RANGE_HIT"
        return "MISS"
    if d in ("BEARISH", "SLIGHTLY BEARISH"):
        if min_down <= mid_pct:
            return "MIDPOINT_HIT"
        if min_down <= hi_pct:
            return "RANGE_HIT"
        return "MISS"
    if min_down <= hi_pct and max_up >= lo_pct:
        return "MIDPOINT_HIT"
    return "MISS"


def _pinball(y, q_pred, tau):
    d = y - q_pred
    return float(np.mean(np.maximum(tau * d, (tau - 1) * d)))


def run(csv_path: str = DEFAULT_CSV, sweep: bool = False, target_winrate: float = 0.85) -> pd.DataFrame:
    predictor = MLPredictor()
    if not predictor.available:
        raise SystemExit("ml_predictor model not loaded — run `python ml_predictor/train.py` first.")

    df = pd.read_csv(csv_path)
    df["date"] = pd.to_datetime(df["date"])
    holdout_start = predictor.manifest.get("holdout_start")
    if holdout_start:
        oos = df[df["date"] >= pd.to_datetime(holdout_start)].copy()
        print(f"  Out-of-sample rows (date ≥ {holdout_start}): {len(oos):,}")
    else:
        oos = df
        print(f"  (no holdout_start in manifest — grading all {len(oos):,} rows)")
    if oos.empty:
        raise SystemExit("No out-of-sample rows to evaluate.")

    feat_mat = oos[FEATURE_COLUMNS].to_numpy(dtype=float)
    atr_arr = oos["atr_pct"].to_numpy(dtype=float)  # price normalized to 100 → atr14 ≈ atr_pct
    records = []
    for tf in TIMEFRAMES:
        # Batch-predict all rows through the estimators ONCE (fast), then derive per row.
        q, proba_m, classes = predictor._raw_predict(tf, feat_mat)
        median_w = float(predictor.manifest.get("tf", {}).get(tf, {}).get("median_train_width", 1.5)) or 1.5
        up_col, dn_col = oos[_UP[tf]].to_numpy(float), oos[_DN[tf]].to_numpy(float)
        ret_col = (np.zeros(len(oos)) if tf == "INTRADAY" else oos[f"ret_{tf}"].to_numpy(float))
        for pos in range(len(oos)):
            row = oos.iloc[pos]
            up_real, dn_real, ret_real = float(up_col[pos]), float(dn_col[pos]), float(ret_col[pos])
            atr14 = float(atr_arr[pos]) if np.isfinite(atr_arr[pos]) else None
            row_q = {k: float(v[pos]) for k, v in q.items()}
            pred = predictor._derive(
                row_q, proba_m[pos], classes, tf, price=100.0, atr14=atr14, median_w=median_w,
                live_price=None, today_high=None, news_score=0, anchor_close=100.0)
            tlo, thi = pred["target_price_lo"], pred["target_price_hi"]
            direction = pred["direction"]
            dir_hit, tgt_hit = _evaluate_intraday_hit(direction, 100.0, tlo, thi, up_real, dn_real, tf, ret_real)
            grade = _graded_hit(direction, 100.0, tlo, thi, up_real, dn_real)
            pq = pred["quantiles"]
            records.append({
                "date": row["date"].strftime("%Y-%m-%d"), "ticker": row["ticker"], "tf": tf,
                "direction": direction, "confidence": pred["confidence"],
                "true_direction": str(row[_DIRC[tf]]),
                "up_real": up_real, "dn_real": dn_real, "ret_real": ret_real,
                "up_q10": pq["up_q10"], "up_q50": pq["up_q50"], "up_q90": pq["up_q90"],
                "down_q10": pq["down_q10"], "down_q50": pq["down_q50"], "down_q90": pq["down_q90"],
                "stop_loss_pct": pred["stop_loss_pct"],
                # expected (median) take-profit return %, entry normalized to price=100.
                # range-bound NEUTRAL now returns expected_target_price=None → 0% expected move.
                "expected_ret_pct": round((pred["expected_target_price"] or 100.0) - 100.0, 3),
                "should_buy": int(pred["should_buy"]),
                "direction_hit": int(dir_hit), "target_hit": int(tgt_hit),
                "hit_grade": grade,
                "graded_hit": int(grade in ("MIDPOINT_HIT", "RANGE_HIT")),
                "midpoint_hit": int(grade == "MIDPOINT_HIT"),
                "dir_correct": int(direction == str(row[_DIRC[tf]])),
            })
    res = pd.DataFrame(records)
    res.to_csv(OUT_CSV, index=False)
    _summary(res)
    _pnl_simulation(res)
    if sweep:
        _pnl_sweep(res, target_winrate=target_winrate)
        _dip_entry_compare(res)
    print(f"\n  ✓ Wrote per-row results → {OUT_CSV}")
    return res


# ── P&L trade simulation (doc-1 metrics: total return, win rate, max DD, PF, #trades) ──
ROUND_TRIP_COST_PCT = 0.30  # 0.10% fees + 0.05% slippage per side × 2 (matches research/db_backtest.py)


def _simulate_trade(tp_pct, stop_pct, up_real, dn_real, ret_real, order: str = "stop_first"):
    """Long trade, market entry (price=100). Exit at take-profit, stop, or window close.

    Excursion-only data (daily bars) cannot tell us whether the target or the stop was
    touched FIRST when both lie inside the horizon's range. So we bracket the truth:
      • order="stop_first"  → pessimistic: assume the stop fills first (lower bound)
      • order="target_first"→ optimistic:  assume the target fills first (upper bound)
    The real P&L is guaranteed to sit between the two. Returns net-of-cost P&L in %.
    """
    hit_stop = bool(stop_pct and dn_real <= -stop_pct)
    hit_tp = bool(tp_pct and tp_pct > 0 and up_real >= tp_pct)
    if order == "target_first":
        if hit_tp:
            gross = tp_pct
        elif hit_stop:
            gross = -stop_pct
        else:
            gross = ret_real
    else:  # stop_first (default, pessimistic)
        if hit_stop:
            gross = -stop_pct
        elif hit_tp:
            gross = tp_pct
        else:
            gross = ret_real  # exit at window close (INTRADAY ret≈0 → ≈flat)
    return gross - ROUND_TRIP_COST_PCT


def _equity_metrics(daily_rets_pct):
    """(total_return%, max_drawdown%) from a DAILY equity curve: each element is the
    equal-weighted mean P&L of all signals on one date, compounded day-over-day. This
    reflects concurrent cross-sectional positions — unlike compounding 20k trades one at
    a time (which explodes), this stays a sane, portfolio-like figure."""
    eq = 1.0
    peak = 1.0
    max_dd = 0.0
    for p in daily_rets_pct:
        eq *= (1 + p / 100.0)
        peak = max(peak, eq)
        max_dd = min(max_dd, (eq - peak) / peak)
    return (eq - 1.0) * 100.0, max_dd * 100.0


def _pnl_simulation(res: pd.DataFrame):
    """Simulate taking the model's LONG (BULLISH / should_buy) calls, net of fees.

    Reports a PESSIMISTIC↔OPTIMISTIC bracket: since daily-bar excursions can't tell us
    whether the stop or the target was touched first, we show both orderings. The real
    P&L sits between them. WinRate/Expect columns are the pessimistic (honest lower) bound.
    """
    print("\n" + "=" * 78)
    print("  P&L TRADE SIMULATION — long-only BULLISH signals, market entry")
    print(f"  Take-profit = expected(median) target · stop = model stop · cost = {ROUND_TRIP_COST_PCT}% round-trip")
    print("  Bracket = [stop-first pessimistic … target-first optimistic]; truth sits between.")
    print("=" * 78)
    hdr = f"  {'TF':<9}{'#Trades':>8}{'WinRate':>9}{'Expect↓':>9}{'Expect↑':>9}{'AvgWin':>9}{'AvgLoss':>9}"
    hdr += f"{'PF':>7}{'DayRet':>9}{'MaxDD':>9}"
    print(hdr)
    print("  " + "-" * 84)
    for tf in TIMEFRAMES:
        d = res[(res["tf"] == tf) & (res["should_buy"] == 1)].copy()
        if d.empty:
            print(f"  {tf:<9}{'0':>8}  (no BULLISH signals)")
            continue
        pess = np.array([_simulate_trade(r.expected_ret_pct, r.stop_loss_pct, r.up_real, r.dn_real, r.ret_real, "stop_first")
                         for r in d.itertuples()])
        opt = np.array([_simulate_trade(r.expected_ret_pct, r.stop_loss_pct, r.up_real, r.dn_real, r.ret_real, "target_first")
                        for r in d.itertuples()])
        d["pnl"] = pess
        wins, losses = pess[pess > 0], pess[pess < 0]
        pf = (wins.sum() / abs(losses.sum())) if losses.sum() < 0 else 99.0
        # Equal-weighted daily equity curve (mean P&L per date, compounded across dates).
        daily = d.groupby("date")["pnl"].mean().sort_index()
        total_ret, max_dd = _equity_metrics(daily.tolist())
        print(f"  {tf:<9}{len(pess):>8}{np.mean(pess > 0):>9.0%}{np.mean(pess):>+9.2f}{np.mean(opt):>+9.2f}"
              f"{(np.mean(wins) if len(wins) else 0):>+9.2f}{(np.mean(losses) if len(losses) else 0):>+9.2f}"
              f"{min(pf, 99.0):>7.2f}{total_ret:>+9.1f}{max_dd:>9.1f}")
    print("\n  Expect↓ = pessimistic (stop-first) mean net P&L/trade — the honest headline.")
    print("  Expect↑ = optimistic (target-first) upper bound. DayRet uses Expect↓.")


# ── Stop × take-profit sweep — find the profit-maximizing exit at each accuracy level ──
# TP candidates are the model's own up-move quantiles (how ambitious the target is); a
# LOWER quantile is reached more often (higher win rate) but banks a smaller gain.
_TP_LEVELS = [("q10", "up_q10"), ("q50", "up_q50"), ("q90", "up_q90")]
_STOP_MULTS = [0.5, 0.7, 1.0, 1.3]   # ×model stop; <1 = "bring the stop down" (tighter)


def _pnl_sweep(res: pd.DataFrame, target_winrate: float = 0.85):
    """Grid-search take-profit level × stop multiplier per TF to maximize profit.

    For each config, WinRate + Expect↓ (pessimistic) and Expect↑ (optimistic) are shown.
    Then per TF we highlight (a) the max-expectancy config and (b) the best config whose
    win rate ≥ target_winrate — so the profit↔accuracy trade-off is explicit.
    """
    print("\n" + "=" * 90)
    print(f"  STOP × TAKE-PROFIT SWEEP — long BULLISH, net {ROUND_TRIP_COST_PCT}% cost · "
          f"target win rate ≥ {target_winrate:.0%}")
    print("  TP = model up-move quantile (lower = hit more often, banks less). Stop× scales the model stop.")
    print("=" * 90)
    for tf in TIMEFRAMES:
        d = res[(res["tf"] == tf) & (res["should_buy"] == 1)].copy()
        if d.empty:
            print(f"\n  {tf}: (no BULLISH signals)")
            continue
        print(f"\n  {tf}  (n={len(d)})")
        print(f"    {'TP':>5}{'Stop×':>7}{'WinRate':>9}{'Expect↓':>9}{'Expect↑':>9}{'AvgWin':>8}{'AvgLoss':>9}{'PF':>7}")
        print("    " + "-" * 62)
        rows = []
        for tp_name, tp_col in _TP_LEVELS:
            for sm in _STOP_MULTS:
                tp = d[tp_col].to_numpy(float)
                stop = d["stop_loss_pct"].to_numpy(float) * sm
                pess = np.array([_simulate_trade(tp[i], stop[i], d.iloc[i].up_real, d.iloc[i].dn_real,
                                                 d.iloc[i].ret_real, "stop_first") for i in range(len(d))])
                opt = np.array([_simulate_trade(tp[i], stop[i], d.iloc[i].up_real, d.iloc[i].dn_real,
                                                d.iloc[i].ret_real, "target_first") for i in range(len(d))])
                wins, losses = pess[pess > 0], pess[pess < 0]
                pf = (wins.sum() / abs(losses.sum())) if losses.sum() < 0 else 99.0
                wr = float(np.mean(pess > 0))
                rows.append({"tp": tp_name, "sm": sm, "wr": wr, "exp_lo": float(np.mean(pess)),
                             "exp_hi": float(np.mean(opt)), "avg_win": float(np.mean(wins)) if len(wins) else 0.0,
                             "avg_loss": float(np.mean(losses)) if len(losses) else 0.0, "pf": min(pf, 99.0)})
                print(f"    {tp_name:>5}{sm:>7.1f}{wr:>9.0%}{np.mean(pess):>+9.2f}{np.mean(opt):>+9.2f}"
                      f"{(np.mean(wins) if len(wins) else 0):>+8.2f}{(np.mean(losses) if len(losses) else 0):>+9.2f}{min(pf,99.0):>7.2f}")
        best = max(rows, key=lambda r: r["exp_lo"])
        constrained = [r for r in rows if r["wr"] >= target_winrate]
        best_c = max(constrained, key=lambda r: r["exp_lo"]) if constrained else None
        print(f"    → MAX PROFIT: TP={best['tp']} Stop×{best['sm']} → Expect↓ {best['exp_lo']:+.2f}% "
              f"(win {best['wr']:.0%}, PF {best['pf']:.2f})")
        if best_c:
            print(f"    → BEST @≥{target_winrate:.0%} win: TP={best_c['tp']} Stop×{best_c['sm']} → "
                  f"Expect↓ {best_c['exp_lo']:+.2f}% (win {best_c['wr']:.0%}, PF {best_c['pf']:.2f})")
        else:
            print(f"    → No config reaches {target_winrate:.0%} win rate at any stop/TP "
                  f"(max win {max(r['wr'] for r in rows):.0%}).")


# ── Market-entry vs DIP-entry (limit buy at the modeled pullback) ─────────────
# The model already outputs buy_price_suggestion = price*(1+down_q50/100) — i.e. buy on the
# modeled median dip instead of at market. Entering lower gives a cushion above the stop AND
# puts the target closer, so filled trades should win more often. The cost: you only get
# filled when the price actually dips (fill-rate < 100%), and you miss runaway winners that
# never pulled back. This measures the trade-off with the same excursion data.
def _dip_entry_compare(res: pd.DataFrame):
    print("\n" + "=" * 90)
    print("  MARKET-ENTRY vs DIP-ENTRY (limit buy at model's suggested dip = down_q50)")
    print("  DIP fills only if price reached the dip; win/expectancy shown for FILLED trades,")
    print("  plus expectancy PER SIGNAL (unfilled = 0, since you couldn't deploy capital).")
    print("=" * 90)
    for tf in TIMEFRAMES:
        d = res[(res["tf"] == tf) & (res["should_buy"] == 1)].copy()
        if d.empty:
            print(f"\n  {tf}: (no BULLISH signals)")
            continue
        up_real = d["up_real"].to_numpy(float)
        dn_real = d["dn_real"].to_numpy(float)
        ret_real = d["ret_real"].to_numpy(float)
        dip = np.minimum(d["down_q50"].to_numpy(float), 0.0)   # modeled dip, % (<0)
        print(f"\n  {tf}  (n={len(d)}) — dip median {np.median(dip):+.2f}%")
        print(f"    {'TP':>5}{'Stop×':>7}{'Entry':>8}{'Fill%':>7}{'Win%':>7}{'Exp/fill':>9}{'Exp/sig':>9}{'PF':>7}")
        print("    " + "-" * 60)
        for tp_name, tp_col in _TP_LEVELS:
            for sm in (1.0, 1.3):
                tp = d[tp_col].to_numpy(float)
                stop = d["stop_loss_pct"].to_numpy(float) * sm
                # MARKET entry: entry=close(0), excursions as-is, all rows filled.
                mkt = np.array([_simulate_trade(tp[i], stop[i], up_real[i], dn_real[i], ret_real[i], "stop_first")
                                for i in range(len(d))])
                # DIP entry: fill only if dn_real <= dip; shift excursions by -dip (cushion).
                filled = dn_real <= dip
                u = up_real - dip          # larger upside from lower entry
                dd = dn_real - dip         # smaller (<=0) downside from entry
                rc = ret_real - dip
                dip_pnl = np.array([_simulate_trade(tp[i], stop[i], u[i], dd[i], rc[i], "stop_first")
                                    for i in range(len(d))])
                for label, pnl, fillmask in (("mkt", mkt, np.ones(len(d), bool)), ("dip", dip_pnl, filled)):
                    sub = pnl[fillmask]
                    if not len(sub):
                        continue
                    wins, losses = sub[sub > 0], sub[sub < 0]
                    pf = (wins.sum() / abs(losses.sum())) if losses.sum() < 0 else 99.0
                    fill_rate = float(fillmask.mean())
                    exp_fill = float(np.mean(sub))
                    exp_sig = float(np.sum(sub) / len(d))   # per signal (unfilled=0)
                    print(f"    {tp_name:>5}{sm:>7.1f}{label:>8}{fill_rate:>7.0%}{np.mean(sub > 0):>7.0%}"
                          f"{exp_fill:>+9.2f}{exp_sig:>+9.2f}{min(pf, 99.0):>7.2f}")


def _summary(res: pd.DataFrame):
    print("\n" + "=" * 78)
    print("  ML MODEL BACKTEST — out-of-sample")
    print("=" * 78)
    hdr = f"  {'TF':<9}{'N':>6}{'DirAcc':>8}{'DirHit':>8}{'Graded':>8}{'MidHit':>8}"
    hdr += f"{'up90cov':>9}{'dn10cov':>9}{'HighMAE':>9}{'HighBias':>9}"
    print(hdr)
    print("  " + "-" * 76)
    for tf in TIMEFRAMES:
        d = res[res["tf"] == tf]
        if d.empty:
            continue
        up_cov = float(np.mean(d["up_real"] <= d["up_q90"]))       # target ≈ .90
        dn_cov = float(np.mean(d["dn_real"] >= d["down_q10"]))     # target ≈ .90
        high_mae = float(np.mean(np.abs(d["up_q90"] - d["up_real"])))
        high_bias = float(np.mean(d["up_q90"] - d["up_real"]))
        print(f"  {tf:<9}{len(d):>6}{d['dir_correct'].mean():>8.0%}{d['direction_hit'].mean():>8.0%}"
              f"{d['graded_hit'].mean():>8.0%}{d['midpoint_hit'].mean():>8.0%}"
              f"{up_cov:>9.0%}{dn_cov:>9.0%}{high_mae:>9.2f}{high_bias:>+9.2f}")

    # Pinball loss per quantile
    print("\n  Pinball loss (lower=better):")
    for tf in TIMEFRAMES:
        d = res[res["tf"] == tf]
        if d.empty:
            continue
        pb = {
            "up_q50": _pinball(d["up_real"].values, d["up_q50"].values, 0.50),
            "up_q90": _pinball(d["up_real"].values, d["up_q90"].values, 0.90),
            "dn_q50": _pinball(d["dn_real"].values, d["down_q50"].values, 0.50),
            "dn_q10": _pinball(d["dn_real"].values, d["down_q10"].values, 0.10),
        }
        print(f"    {tf:<9} " + " ".join(f"{k}={v:.3f}" for k, v in pb.items()))

    # Graded hit by confidence bucket
    print("\n  Graded hit rate by confidence:")
    for conf in ("HIGH", "MEDIUM", "LOW"):
        d = res[res["confidence"] == conf]
        if len(d) >= 10:
            print(f"    {conf:<7} N={len(d):>5}  graded={d['graded_hit'].mean():.0%}  "
                  f"dir_correct={d['dir_correct'].mean():.0%}")

    # Dip-level-reached % (bearish) and stop-would-hit %
    print("\n  Directional diagnostics:")
    for tf in TIMEFRAMES:
        d = res[res["tf"] == tf]
        bear = d[d["direction"] == "BEARISH"]
        dip_reached = float(np.mean(bear["dn_real"] <= bear["down_q50"])) if len(bear) else float("nan")
        # stop would hit if realized worst-down over window breaches -stop_loss_pct
        stop_hit = float(np.mean(d["dn_real"] <= -d["stop_loss_pct"])) if len(d) else float("nan")
        n_bear = len(bear)
        print(f"    {tf:<9} bearish N={n_bear:>4} dip_reached={dip_reached:.0%}"
              f"   stop_would_hit={stop_hit:.0%}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=DEFAULT_CSV)
    ap.add_argument("--sweep", action="store_true", help="run the stop×take-profit profit-maximization grid")
    ap.add_argument("--target-winrate", type=float, default=0.85, help="win-rate floor for the sweep's constrained best")
    args = ap.parse_args()
    run(args.csv, sweep=args.sweep, target_winrate=args.target_winrate)


if __name__ == "__main__":
    main()
