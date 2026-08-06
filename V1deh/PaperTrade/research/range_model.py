"""research/range_model.py — arithmetic (√days) range model, replacing hardcoded per-TF tables.

WHY: the per-TF magnitude tables in ai_forecast.py / database.py are "magic numbers" that in fact
track a √time volatility law (volatility ~ √horizon). This module derives them from a handful of
COEFFICIENTS × √days, so tuning is ~5 numbers instead of dozens of per-TF cells, and it generalizes
to any horizon. Values reproduce the calibrated backup (research/range_tables_backup.json): the
hit-rate-critical BULLISH hi-bound reproduces 1D exactly and 3D/INTRADAY within tolerance.

WHAT STAYS NON-ARITHMETIC (by design, see backup notes):
  • NEUTRAL band — flat by policy (falsifiability), NOT a volatility magnitude.
  • The conservative lo-bound — a fee-clearing floor (~NSE round-trip cost), horizon-independent.

Reusability / PROD PORT (see research/PRODUCTION_DELTA.md): pure functions, no deps beyond math.
To ship: `ai_forecast.py` (`_build_synthesis_prompt`, `_generate_range_from_point`,
`_atr_clamp_range`, `_apply_calibrated_range`) and `database.py` (`_SNAP_*`) import from here —
which also removes the "must match" duplication between those two files.

Run `python research/range_model.py` to self-test reproduction against the backup JSON.
"""
from __future__ import annotations

import math

# ── Effective volatility-days per horizon (the ONE source of horizon length) ──────────────
# INTRADAY modeled as a partial session (~0.5 day) — reproduces the calibrated intraday values.
_TF_VOL_DAYS: dict[str, float] = {"INTRADAY": 0.5, "1D": 1.0, "3D": 3.0, "5D": 5.0, "1W": 7.0}

# ── Coefficients (the ~handful of tunables). Each magnitude = COEFF × √days. ───────────────
_BULL_HI_COEFF   = 1.30    # calibrated BULLISH optimistic bound: 1.30·√days (reproduces 1D=1.30)
_BULL_LO_COEFF   = 0.19    # conservative bound slope; floored by cost below
_ATR_LO_COEFF    = 0.25    # prompt ATR target: conservative multiplier
_ATR_HI_COEFF    = 0.60    # prompt ATR target: optimistic multiplier
_MID_CEIL_COEFF  = 1.15    # clamp: max |midpoint| in ATR units
_MAX_WIDTH_COEFF = 0.65    # clamp: max band width in ATR units
_HARD_CAP_COEFF  = 4.0     # clamp/prompt: hard %-cap
_INTRADAY_HARD_CAP = 2.0   # deliberate tight same-session cap (overrides the formula for INTRADAY)

# NSE round-trip cost floors (%) — the conservative bound must clear these (delivery ~0.22%,
# intraday ~0.11%). Horizon-independent; NOT scaled.
_COST_FLOOR_PCT: dict[str, float] = {"INTRADAY": 0.11, "1D": 0.22, "3D": 0.22, "5D": 0.22, "1W": 0.22}

# NEUTRAL band — flat by policy (falsifiability). Not scaled.
_NEUT_FLAT: dict[str, tuple[float, float]] = {
    "INTRADAY": (-0.50, 0.50), "1D": (-1.5, 1.5), "3D": (-1.0, 1.0), "5D": (-1.0, 1.0), "1W": (-1.0, 1.0),
}


def horizon_scale(tf_label: str) -> float:
    """√(effective days) — the volatility-scaling factor for a horizon."""
    return math.sqrt(_TF_VOL_DAYS.get(tf_label, 1.0))


def _cost_floor(tf_label: str) -> float:
    return _COST_FLOOR_PCT.get(tf_label, 0.22)


def calibrated_range(direction: str, tf_label: str) -> tuple[float, float]:
    """(lo_pct, hi_pct) calibrated return band — the arithmetic replacement for
    _BULL_RANGE/_BEAR_RANGE/_NEUT_RANGE (and database._SNAP_*)."""
    d = (direction or "NEUTRAL").upper()
    s = horizon_scale(tf_label)
    if d in ("BULLISH", "SLIGHTLY BULLISH"):
        lo = max(_cost_floor(tf_label), _BULL_LO_COEFF * s)
        hi = _BULL_HI_COEFF * s
        return (round(lo, 2), round(hi, 2))
    if d in ("BEARISH", "SLIGHTLY BEARISH"):
        lo, hi = calibrated_range("BULLISH", tf_label)
        return (round(-hi, 2), round(-lo, 2))   # mirror below entry: lo < hi < 0
    return _NEUT_FLAT.get(tf_label, (-1.0, 1.0))


def atr_target_mults(tf_label: str) -> tuple[float, float]:
    """(lo_mult, hi_mult) in ATR units for the synthesis-prompt target band."""
    s = horizon_scale(tf_label)
    return (round(_ATR_LO_COEFF * s, 3), round(_ATR_HI_COEFF * s, 3))


def atr_safety_nets(tf_label: str) -> dict:
    """Clamp safety-net values (ATR-unit ceiling/width + %-cap) for _atr_clamp_range."""
    s = horizon_scale(tf_label)
    cap = _INTRADAY_HARD_CAP if tf_label == "INTRADAY" else round(_HARD_CAP_COEFF * s, 2)
    return {
        "mid_ceiling": round(_MID_CEIL_COEFF * s, 3),   # max |midpoint| in ATR units
        "max_width":   round(_MAX_WIDTH_COEFF * s, 3),  # max band width in ATR units
        "hard_cap_pct": cap,
    }


# ── Self-test: reproduction vs the calibrated backup ──────────────────────────────────────
if __name__ == "__main__":
    import json, os
    bpath = os.path.join(os.path.dirname(__file__), "range_tables_backup.json")
    backup = json.load(open(bpath))
    bull = backup["ai_forecast"]["_BULL_RANGE"]
    mults = backup["ai_forecast"]["atr_target_mults__build_synthesis_prompt"]
    ceil = backup["ai_forecast"]["_ATR_MID_CEILING"]
    width = backup["ai_forecast"]["_ATR_MAX_WIDTH"]
    cap = backup["ai_forecast"]["_TF_HARD_CAP_PCT"]

    print(f"{'TF':<9} {'BULL(formula)':<16} {'BULL(backup)':<16} {'ATRmul(f)':<14} {'ATRmul(bk)':<14} "
          f"{'ceil f/bk':<12} {'width f/bk':<12} {'cap f/bk':<10}")
    ok = True
    for tf in ("INTRADAY", "1D", "3D"):
        cr = calibrated_range("BULLISH", tf)
        am = atr_target_mults(tf)
        sn = atr_safety_nets(tf)
        print(f"{tf:<9} {str(cr):<16} {str(tuple(bull[tf])):<16} {str(am):<14} {str(tuple(mults[tf])):<14} "
              f"{sn['mid_ceiling']}/{ceil[tf]:<7} {sn['max_width']}/{width[tf]:<7} {sn['hard_cap_pct']}/{cap[tf]}")
    # Assert the hit-rate-critical 1D BULLISH hi reproduces exactly; 3D/INTRADAY within 10%.
    assert calibrated_range("BULLISH", "1D")[1] == 1.30, "1D bull-hi must reproduce 1.30"
    for tf in ("INTRADAY", "3D"):
        f_hi = calibrated_range("BULLISH", tf)[1]; b_hi = bull[tf][1]
        assert abs(f_hi - b_hi) / b_hi <= 0.10, f"{tf} bull-hi drift >10%: {f_hi} vs {b_hi}"
    # BEARISH mirror + NEUTRAL flat
    assert calibrated_range("BEARISH", "1D") == (-1.30, -0.22)
    assert calibrated_range("NEUTRAL", "1D") == (-1.5, 1.5)
    print("\nrange_model self-test PASSED (1D bull-hi exact; 3D/INTRADAY within 10%; bear mirror; neut flat)")
