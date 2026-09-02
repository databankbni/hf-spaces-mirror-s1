#!/usr/bin/env python3
"""ml_predictor/infer.py — live inference for the ML price model.

MLPredictor lazy-loads the 15 joblib estimators + manifest.json once (module
singleton), computes the point-in-time feature vector for the latest bar, runs
the quantile regressors + direction classifier per timeframe, and derives the
full predict_stock_v2-compatible output: direction, confidence, return band,
target prices, buy-price suggestion, stop-loss, and — for INTRADAY — the
estimated high and an "already gone" flag against an optional live price.

Model artifacts load from ml_predictor/models/ (git-committed baseline). If a
newer set exists in the HF Hub dataset repo named by $HF_ML_MODEL_REPO_ID, it is
preferred. Missing artifacts degrade gracefully (source="ml_unavailable"), never
crashing the caller.

News sentiment is applied here as a live confidence adjustment only (it is not a
trained feature — see features.py).
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time

import numpy as np
import pandas as pd

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from ml_predictor.features import FEATURE_COLUMNS, TIMEFRAMES, compute_features, features_to_row  # noqa: E402

_MODEL_DIR = os.environ.get("ML_MODEL_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "models"))
_HF_MODEL_REPO_ID = os.environ.get("HF_ML_MODEL_REPO_ID", "")  # optional newer-model source

# ATR stop multiplier per TF (matches predictor_core's tightening by horizon).
_ATR_MULT = {"INTRADAY": 0.4, "1D": 0.7, "3D": 1.1}
_STOP_BUFFER_PCT = 0.3          # extra room below the modeled worst-down quantile
_NEWS_ALIGN_THRESHOLD = 8       # |news_score| >= this downgrades a conflicting direction
_MODEL_NAMES = ["up_q10", "up_q50", "up_q90", "down_q10", "down_q50", "down_q90", "direction"]

# NOTE: the ML INTRADAY range is a high-hit PREDICTION INTERVAL, not a >=1% directional target — it
# is deliberately NOT floored to 1% (see the range-derivation block below). The >=1% "meaningful
# move" floor lives only on the AI directional target (predictor_core / ai_forecast).

# ── High-conviction gate (rare but ~85%+-reliable directional calls) ────────────
# The per-stock 1D/3D next-day DIRECTION has a hard signal ceiling (~74% at any usable
# coverage — see research/ml_confidence_sweep.py; RF/KNN, meta-labeling, sector & delivery
# features all failed to move it). So instead of a permanent HIGH bucket (kept DISABLED via
# manifest conf_hi=1.01 to avoid lucky false-HIGH), we flag the RARE tail where the calibrated
# max-class probability clears an empirically-reliable threshold — the only region where 1D/3D
# direction actually reaches ~83-90% (1D dir-only 83% @ proba≥0.60, 3D 89-93% @ proba≥0.55 on
# the 6-month OOS holdout). This fires seldom (~0.1-0.4% of rows) by design — it's a precision
# flag, not a coverage lever. INTRADAY (the reliable TF) uses its own calibrated conf_hi=0.72.
# `high_conviction` is a SEPARATE bool from `confidence` so the honest LOW/MEDIUM buckets are
# unchanged; consumers can surface a "high-conviction" badge only on these tail rows. Env-tunable.
_HIGH_CONVICTION_PROBA = {
    "INTRADAY": float(os.environ.get("ML_HICONV_PROBA_INTRADAY", "0.72")),
    "1D":       float(os.environ.get("ML_HICONV_PROBA_1D", "0.60")),
    "3D":       float(os.environ.get("ML_HICONV_PROBA_3D", "0.55")),
}

_INDEX_TTL = 1800               # 30-min cache for ^NSEI / ^INDIAVIX

# ── Intraday session-time scaling (make mid-session targets reachable) ──────────
_SESSION_OPEN_MIN = 9 * 60 + 15     # 09:15 IST
_SESSION_CLOSE_MIN = 15 * 60        # 15:00 IST (same validation cutoff as the intraday backtest)
_SESSION_TOTAL = _SESSION_CLOSE_MIN - _SESSION_OPEN_MIN   # 345 min

# INTRADAY magnitude calibration. The model predicts a FULL-DAY excursion (its labels are
# the entry day's own High/Low vs close), but at deployment the features are as-of the
# PREVIOUS daily close and the entry is mid-session, so the raw quantiles are miscalibrated
# for the session that actually remains — AND not by a single factor: measured on the true
# 15-min backtest (research/ml_intraday_backtest.py, 30 tickers × 57 days), the model's q90
# is about right once √time-scaled (a genuine ~90% ceiling), but its q50 systematically
# OVERSHOOTS the realized median move and its q10 is too ambitious for the reachable floor.
# So we calibrate the three roles of the reported band INDEPENDENTLY, each on top of the
# √time session scaling above, to the realized excursion distribution:
#   • _INTRADAY_FAR_MULT  (≈1.0)  — far/optimistic edge = true q90 ceiling (~90% not exceeded;
#     the old uniform-shrink left this at a q65, understating the achievable high).
#   • _INTRADAY_MED_MULT  (≈0.42) — the EXPECTED/headline target = realized MEDIAN move (reached
#     ~50% of the time). This is the HONEST, tradeable setting. WARNING: "expected-target hit %"
#     is monotonic in the target level, so you can push it to ~85% by dropping this to ≈0.08 —
#     BUT that makes the target ~0.15%, which is SMALLER than the ~0.30% round-trip cost, so the
#     backtest win-rate collapses to ~5% (the target is "hit" but you still lose to fees). 85%
#     expected-target accuracy and profitability are mutually exclusive here. Set
#     ML_INTRADAY_MED_MULT=0.08 only if you explicitly want the high-hit-rate display target.
#   • _INTRADAY_NEAR_MULT (≈0.12) — reachable near edge, so the range's near bound (RANGE_HIT)
#     is genuinely touched ≥85% of the session.
# Result (default): graded (range) hit ≈88%, expected-target hit ≈51%, far-bound coverage ≈90%.
# All three are env-overridable for A/B.
_INTRADAY_FAR_MULT = float(os.environ.get("ML_INTRADAY_FAR_MULT", "1.0"))
_INTRADAY_MED_MULT = float(os.environ.get("ML_INTRADAY_MED_MULT", "0.42"))
_INTRADAY_NEAR_MULT = float(os.environ.get("ML_INTRADAY_NEAR_MULT", "0.12"))

# 1D range-only policy (mirrors predictor_core FORCE_1D_RANGE_ONLY): next-day 1D direction has a
# proven accuracy ceiling (~46-49% for the excess-of-Nifty label — no better than raw returns;
# research/ml_backtest.py + repo memory), so a directional 1D target is unreliable. The live path
# forces 1D into an honest RANGE-ONLY (NEUTRAL) call with a FLAT ±1% falsifiable band (NOT
# ATR-scaled), matching the AI path. Backtests call _derive WITHOUT force_range_only, so their raw
# 1D direction metric is unaffected. Env-overridable.
_FORCE_1D_RANGE_ONLY = os.environ.get("ML_FORCE_1D_RANGE_ONLY", "1") != "0"
_ONE_D_RANGE_HALF_PCT = float(os.environ.get("ONE_D_RANGE_HALF_PCT", "1.0"))  # flat, shared with the AI path

# ── Per-TF VOLATILITY-SCALED cap on the REPORTED range (extrapolation guard, NOT a flat limit) ──
# A violent stock SHOULD be able to show a big move — that's the whole point of a volatility model.
# So the cap is a multiple of the STOCK'S OWN ATR% (× floor/ceiling), not a flat number. This lets a
# high-ATR name (e.g. an ~8% ATR stock → ±~12% intraday) keep its wide, honest range, while still
# catching a pathological extrapolation that is absurd RELATIVE TO THAT STOCK'S volatility (e.g. a
# calm 2%-ATR stock somehow emitting a +11% intraday q90). cap = clamp(mult×ATR%, floor, ceiling).
# The RAW quantiles (in `quantiles`, used by backtests) are left untouched. All env-overridable.
_TF_CAP_ATR_MULT = {
    "INTRADAY": float(os.environ.get("ML_CAP_ATR_MULT_INTRADAY", "2.5")),
    "1D":       float(os.environ.get("ML_CAP_ATR_MULT_1D", "3.0")),
    "3D":       float(os.environ.get("ML_CAP_ATR_MULT_3D", "4.5")),
}
_TF_CAP_FLOOR_PCT = {"INTRADAY": 2.0, "1D": 3.0, "3D": 5.0}   # cap never tighter than this
_TF_CAP_CEIL_PCT  = {"INTRADAY": 14.0, "1D": 18.0, "3D": 30.0}  # hard sanity ceiling for any ATR
# A/B toggle: ML_DISABLE_RANGE_CAP=1 skips the cap entirely (uncapped raw quantiles), so the
# volatility-scaled cap can be backtested against no-cap.
_DISABLE_RANGE_CAP = os.environ.get("ML_DISABLE_RANGE_CAP", "0") == "1"

# Low-history / recently-listed guard: a stock with less than ~1 trading year of bars (a recent
# IPO) is OUTSIDE the model's training distribution — EMA200, 3-month RS, 90-day returns and the
# calibrated confidence are all unreliable, so a HIGH-confidence call on it is misleading. Below
# this bar count the confidence is capped and a `low_history` flag is surfaced. Env-overridable.
_MIN_FULL_HISTORY_BARS = int(os.environ.get("ML_MIN_FULL_HISTORY_BARS", "250"))

# Flat NEUTRAL bands (mirror research.range_model._NEUT_FLAT) — used as a fallback when the
# research package is absent from the deployment image (research/ is excluded from the HF
# Spaces Docker build via .dockerignore). Without this fallback the NEUTRAL branch import
# raised ModuleNotFoundError and crashed the whole ML endpoint (HTTP 500) in production.
_NEUTRAL_FALLBACK = {"INTRADAY": (-0.50, 0.50), "1D": (-1.5, 1.5), "3D": (-1.0, 1.0)}


def _neutral_range(tf: str) -> tuple[float, float]:
    """Calibrated NEUTRAL return band, resilient to the research/ package being unpackaged."""
    try:
        from research.range_model import calibrated_range
        return calibrated_range("NEUTRAL", tf)
    except Exception:
        return _NEUTRAL_FALLBACK.get(tf, (-1.0, 1.0))


def intraday_session_scale(now_minutes: float) -> float:
    """√(remaining session fraction) for a prediction made at `now_minutes` (mins since IST
    midnight). Volatility ~ √time, so the full-day target is scaled to what's left of the
    session. 1.0 at/near the open; smaller later in the day; floored so it never hits 0."""
    remaining = _SESSION_CLOSE_MIN - now_minutes
    remaining = max(20.0, min(remaining, float(_SESSION_TOTAL)))   # clamp to [20min, full session]
    return (remaining / _SESSION_TOTAL) ** 0.5


def _live_intraday_scale() -> float:
    """Scale for a live prediction: √(remaining session) during market hours, else 1.0
    (before the open → full day ahead; after close → next session, full day)."""
    try:
        from datetime import datetime, timezone, timedelta
        ist = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5, minutes=30)))
        now_min = ist.hour * 60 + ist.minute
        if now_min <= _SESSION_OPEN_MIN or now_min >= _SESSION_CLOSE_MIN:
            return 1.0
        return intraday_session_scale(now_min)
    except Exception:
        return 1.0


class MLPredictor:
    """Singleton wrapper over the trained artifacts."""
    _instance: "MLPredictor | None" = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_once()
            return cls._instance

    def _init_once(self):
        self.models: dict[str, dict] = {}     # tf -> {name: estimator}
        self.manifest: dict = {}
        self.available = False
        self.feature_columns = FEATURE_COLUMNS
        self._idx_cache = {"ts": 0.0, "nifty": None, "vix": None}
        self._load()

    # ── Loading ───────────────────────────────────────────────────────────
    def _maybe_download_hub(self):
        """If an HF Hub model repo is configured, download newer artifacts into _MODEL_DIR."""
        if not _HF_MODEL_REPO_ID:
            return
        try:
            from huggingface_hub import hf_hub_download
            token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")
            os.makedirs(_MODEL_DIR, exist_ok=True)
            files = ["manifest.json"] + [f"{tf}_{n}.joblib" for tf in TIMEFRAMES for n in _MODEL_NAMES]
            for fn in files:
                path = hf_hub_download(repo_id=_HF_MODEL_REPO_ID, filename=fn,
                                       repo_type="dataset", token=token)
                # hf_hub_download returns a cache path; copy into _MODEL_DIR for uniform loading.
                import shutil
                shutil.copy2(path, os.path.join(_MODEL_DIR, fn))
            logging.info("ml_predictor: pulled models from HF Hub %s", _HF_MODEL_REPO_ID)
        except Exception as e:
            logging.warning("ml_predictor: HF Hub model pull failed (%s) — using local artifacts", e)

    def _load(self):
        import json
        self._maybe_download_hub()
        manifest_path = os.path.join(_MODEL_DIR, "manifest.json")
        if not os.path.exists(manifest_path):
            logging.warning("ml_predictor: no manifest at %s — model unavailable", manifest_path)
            return
        try:
            import joblib
            import sklearn
            with open(manifest_path) as f:
                self.manifest = json.load(f)
            trained_v = self.manifest.get("sklearn_version")
            if trained_v and trained_v != sklearn.__version__:
                logging.warning("ml_predictor: sklearn version mismatch (trained %s, running %s) — "
                                "unpickling may fail", trained_v, sklearn.__version__)
            self.feature_columns = self.manifest.get("feature_columns", FEATURE_COLUMNS)
            for tf in self.manifest.get("timeframes", TIMEFRAMES):
                self.models[tf] = {}
                for name in _MODEL_NAMES:
                    p = os.path.join(_MODEL_DIR, f"{tf}_{name}.joblib")
                    self.models[tf][name] = joblib.load(p)
            self.available = True
            logging.info("ml_predictor: loaded models (train_cutoff=%s)",
                         self.manifest.get("train_cutoff"))
        except Exception as e:
            logging.warning("ml_predictor: model load failed (%s) — unavailable", e)
            self.available = False

    # ── Index (Nifty/VIX) helper with TTL cache ─────────────────────────────
    def _indices(self):
        now = time.time()
        if now - self._idx_cache["ts"] < _INDEX_TTL and self._idx_cache["nifty"] is not None:
            return self._idx_cache["nifty"], self._idx_cache["vix"]
        nifty = vix = None
        try:
            # yf.download has no built-in timeout — a stalled Yahoo connection would
            # otherwise block this request forever. _yf_download_timed bounds it (15s)
            # via a worker thread the same way data_sources.py's own fetches are bounded.
            from data_sources import _yf_download_timed
            raw = _yf_download_timed(["^NSEI", "^INDIAVIX"], timeout=15, period="1y",
                                     auto_adjust=True, progress=False)
            if raw is None:
                raise ValueError("index download timed out")
            nifty = raw["Close"]["^NSEI"].dropna()
            vix = raw["Close"]["^INDIAVIX"].dropna()
        except Exception:
            try:
                from data_sources import fetch_market_data
                nifty, vix = fetch_market_data(period_days=365)
            except Exception:
                pass
        self._idx_cache = {"ts": now, "nifty": nifty, "vix": vix}
        return nifty, vix

    # ── Core prediction ──────────────────────────────────────────────────
    def _raw_predict(self, tf: str, X: np.ndarray):
        """Batch model outputs for a feature matrix X (rows × features).
        Returns dict of monotonic quantile arrays + (proba matrix, class list)."""
        m = self.models[tf]
        up10 = m["up_q10"].predict(X)
        up50 = np.maximum(m["up_q50"].predict(X), up10)             # monotonic
        up90 = np.maximum(m["up_q90"].predict(X), up50)
        dn90 = m["down_q90"].predict(X)                             # shallowest (closest to 0)
        dn50 = np.minimum(m["down_q50"].predict(X), dn90)
        dn10 = np.minimum(m["down_q10"].predict(X), dn50)           # deepest (most negative)
        clf = m["direction"]
        q = {"up10": up10, "up50": up50, "up90": up90, "dn10": dn10, "dn50": dn50, "dn90": dn90}
        return q, clf.predict_proba(X), list(clf.classes_)

    def _predict_tf(self, feat_row: list[float], tf: str, price: float,
                    atr14: float | None, live_price: float | None,
                    today_high: float | None, news_score: int,
                    anchor_close: float | None = None, intraday_scale: float = 1.0) -> dict:
        X = np.array([feat_row], dtype=float)
        q, proba_m, classes = self._raw_predict(tf, X)
        row_q = {k: float(v[0]) for k, v in q.items()}
        median_w = float(self.manifest.get("tf", {}).get(tf, {}).get("median_train_width", 1.5)) or 1.5
        return self._derive(row_q, proba_m[0], classes, tf, price, atr14,
                            median_w, live_price, today_high, news_score, anchor_close, intraday_scale,
                            force_range_only=(_FORCE_1D_RANGE_ONLY and tf == "1D"))

    def _derive(self, q, proba, classes, tf, price, atr14,
                median_w, live_price, today_high, news_score, anchor_close, intraday_scale=1.0,
                force_range_only=False):
        # Pure derivation of the output schema from raw model outputs (no model calls).
        # Shared by _predict_tf (live) and research/ml_backtest.py (batch) — one source of truth.
        # INTRADAY time-of-day scaling: the model predicts a FULL-DAY excursion, but a mid-session
        # entry only has part of the day left. Scale all quantiles by √(remaining session fraction)
        # (volatility ~ √time) so 12:00/14:00 targets are reachable in the hours that remain. The
        # per-role recalibration (near/median/far, see the *_MULT constants) is applied below.
        if tf == "INTRADAY" and intraday_scale != 1.0:
            q = {k: v * intraday_scale for k, v in q.items()}
        up10, up50, up90 = q["up10"], q["up50"], q["up90"]
        dn10, dn50, dn90 = q["dn10"], q["dn50"], q["dn90"]
        order = np.argsort(proba)[::-1]
        direction = str(classes[order[0]])
        margin = float(proba[order[0]] - proba[order[1]]) if len(order) > 1 else float(proba[order[0]])

        # 1D range-only policy: force NEUTRAL so 1D is a range-bound call, never a coin-flip
        # directional bet (see _FORCE_1D_RANGE_ONLY). The live path sets force_range_only for 1D;
        # backtests leave it False so their raw direction metric is untouched.
        if force_range_only and tf == "1D":
            direction = "NEUTRAL"

        # Sanity downgrade: weak-margin BULLISH with bigger modeled downside → NEUTRAL.
        if direction == "BULLISH" and margin < 0.15 and up50 < abs(dn50) * 0.8:
            direction = "NEUTRAL"
        if direction == "BEARISH" and margin < 0.15 and abs(dn50) < up50 * 0.8:
            direction = "NEUTRAL"

        # ── Confidence: from the ISOTONIC-CALIBRATED max-class probability ────
        # (improvement "c") — a trustworthy P(direction correct). Thresholds are ABSOLUTE,
        # tied to the calibrated probability's reliability vs the random baseline (stored at
        # train time as conf_hi/conf_mid), so HIGH/MEDIUM/LOW mean the same thing across TFs
        # and stocks — not a per-TF tertile that forced 1/3 of every TF to LOW. Falls back to
        # margin if absent.
        max_proba = float(np.max(proba))
        tf_meta = self.manifest.get("tf", {}).get(tf, {})
        conf_hi = tf_meta.get("conf_hi")
        conf_mid = tf_meta.get("conf_mid")
        if conf_hi is not None and conf_mid is not None:
            confidence = "HIGH" if max_proba >= conf_hi else ("MEDIUM" if max_proba >= conf_mid else "LOW")
        else:  # legacy fallback (uncalibrated models)
            band_w = up90 - up10
            confidence = "HIGH" if (margin >= 0.30 and band_w <= median_w) else (
                "LOW" if (margin < 0.15 or band_w > 2 * median_w) else "MEDIUM")

        # ── News alignment (live-only adjustment) ────────────────────────────
        if abs(news_score) >= _NEWS_ALIGN_THRESHOLD:
            conflict = ((news_score < 0 and direction == "BULLISH") or
                        (news_score > 0 and direction == "BEARISH"))
            if conflict:
                if abs(news_score) >= 20:
                    direction = "NEUTRAL"
                elif confidence == "HIGH":
                    confidence = "MEDIUM"
                elif confidence == "MEDIUM":
                    confidence = "LOW"

        # ── Return band = a prediction INTERVAL (near easily-reached bound … far optimistic) ──
        # so the reported range is honestly hit most of the time, not a coin-flip median band.
        # INTRADAY: the near/median/far levels are calibrated INDEPENDENTLY to the realized
        # 15-min excursion distribution (see the _INTRADAY_*_MULT constants) — near edge is a
        # reachable floor (~85% touched), far edge is a true q90 ceiling, and the expected
        # target is pulled to the realized median (~50% touched). Other TFs use the raw quantiles.
        near_m = _INTRADAY_NEAR_MULT if tf == "INTRADAY" else 1.0
        far_m = _INTRADAY_FAR_MULT if tf == "INTRADAY" else 1.0
        med_m = _INTRADAY_MED_MULT if tf == "INTRADAY" else 1.0
        if direction == "BULLISH":
            ret_lo, ret_hi = round(up10 * near_m, 2), round(up90 * far_m, 2)  # 0 < lo < hi
            expected_pct = up50 * med_m                                       # median expected high
        elif direction == "BEARISH":
            ret_lo, ret_hi = round(dn10 * far_m, 2), round(dn90 * near_m, 2)  # lo < hi < 0 (deep … shallow)
            expected_pct = dn50 * med_m                                       # median expected dip
        else:
            n_lo, n_hi = _neutral_range(tf)
            if force_range_only and tf == "1D":
                # Range-only 1D: a FLAT ±1% falsifiable band (matches the AI path's
                # ONE_D_RANGE_HALF_PCT) — actionable "stays within 1%", not a wide ATR band.
                n_lo, n_hi = -_ONE_D_RANGE_HALF_PCT, _ONE_D_RANGE_HALF_PCT
            ret_lo, ret_hi = round(n_lo, 2), round(n_hi, 2)
            expected_pct = 0.0

        # ── INTRADAY range = a high-hit PREDICTION INTERVAL (do NOT floor to >=1%) ──
        # The [up10*near_m, up90*far_m] band is deliberately calibrated so the NEAR bound is a
        # reachable floor (~85% touched) and the far bound a q90 ceiling → the range is genuinely
        # contained ~87% of the time (research/ml_intraday_results.csv, 4.5k rows). Flooring the
        # near bound to >=1% would raise it to a level reached only ~39% of the time (median intraday
        # favorable move is just ~0.72%), collapsing the containment/hit rate — so the ML row keeps
        # its honest wide interval. The expected target (`expected_pct`, ~median) is the clear number;
        # a >=1% "meaningful move" floor is applied to the AI directional TARGET, not to this interval.

        # ── Per-TF sanity cap ────────────────────────────────────────────────
        # ── Per-TF volatility-scaled cap ─────────────────────────────────────
        # cap = clamp(mult × the stock's OWN ATR%, floor, ceiling). A violent stock keeps its wide
        # range; the cap only catches a value absurd relative to that stock's own volatility. The
        # raw quantiles (exposed in `quantiles`, used by backtests) are left untouched.
        _atr_pct_local = (atr14 / price * 100.0) if (atr14 and price and price > 0) else 0.0
        _mult = _TF_CAP_ATR_MULT.get(tf)
        if _DISABLE_RANGE_CAP:
            _cap = None
        elif _mult and _atr_pct_local > 0:
            _cap = min(_TF_CAP_CEIL_PCT.get(tf, 20.0),
                       max(_TF_CAP_FLOOR_PCT.get(tf, 2.0), _mult * _atr_pct_local))
        else:
            _cap = _TF_CAP_CEIL_PCT.get(tf)  # ATR unknown → fall back to the generous ceiling
        if _cap:
            ret_lo = round(max(-_cap, min(_cap, ret_lo)), 2)
            ret_hi = round(max(-_cap, min(_cap, ret_hi)), 2)
            expected_pct = max(-_cap, min(_cap, expected_pct))
        # Capped optimistic up-move used for the "estimated high" (bull q90, ceiling at _cap).
        _est_high_pct = up90 * far_m
        if _cap:
            _est_high_pct = min(_est_high_pct, _cap)

        target_price_lo = round(price * (1 + ret_lo / 100.0), 2)
        target_price_hi = round(price * (1 + ret_hi / 100.0), 2)
        midpoint = round((ret_lo + ret_hi) / 2.0, 2)
        # NEUTRAL = "expected to stay range-bound": there is NO directional target, so the
        # "expected target" would just be the current price (expected_pct == 0), which reads as
        # "predicting a price that's already there". Emit range_bound + a null headline target so
        # consumers show "range-bound (no edge)" instead of a bogus target == current price.
        is_range_bound = (direction == "NEUTRAL")

        # ── High-conviction gate ─────────────────────────────────────────────
        # A directional call in the rare, empirically-reliable tail (calibrated max-proba clears
        # the per-TF threshold where OOS direction accuracy is ~83-90%). Separate from `confidence`
        # so the honest LOW/MEDIUM buckets stay intact; fires seldom by design.
        _hiconv_thr = _HIGH_CONVICTION_PROBA.get(tf, 1.01)
        high_conviction = bool(direction in ("BULLISH", "BEARISH") and max_proba >= _hiconv_thr)

        # Expected (most-likely) target = the median quantile — the headline price estimate.
        expected_target_price = None if is_range_bound else round(price * (1 + expected_pct / 100.0), 2)
        # "Estimated high the stock can reach" = optimistic up-quantile (INTRADAY: far-calibrated),
        # capped to the per-TF ceiling (_est_high_pct) so it stays realistic for extreme-ATR names.
        estimated_high = round(price * (1 + _est_high_pct / 100.0), 2)

        # ── Buy-price suggestion: the modeled median dip (buy on the pullback) ─
        dip_entry = round(price * (1 + dn50 / 100.0), 2)
        entry_price = dip_entry if dip_entry < price else round(price, 2)

        # ── Stop-loss: below the modeled worst-down, with an ATR floor ───────
        if atr14 is None or not np.isfinite(atr14) or atr14 <= 0:
            atr14 = price * 0.015
        atr_stop = entry_price - _ATR_MULT.get(tf, 0.7) * atr14
        q_stop = price * (1 + (dn10 - _STOP_BUFFER_PCT) / 100.0)
        stop_loss = round(min(atr_stop, q_stop), 2)
        stop_loss_pct = round((entry_price - stop_loss) / entry_price * 100.0, 2) if entry_price else None

        out = {
            "timeframe": tf,
            "direction": direction,
            "confidence": confidence,
            "predicted_return_lo": ret_lo,
            "predicted_return_hi": ret_hi,
            "expected_return_range": f"{ret_lo:+.2f}% to {ret_hi:+.2f}%",
            "midpoint": midpoint,
            "current_price": round(price, 2),
            "target_price_lo": target_price_lo,
            "target_price_hi": target_price_hi,
            "expected_target_price": expected_target_price,
            "range_bound": is_range_bound,
            "high_conviction": high_conviction,
            "estimated_high": estimated_high,
            "expected_entry_price": entry_price,
            "buy_price_suggestion": entry_price,
            "stop_loss": stop_loss,
            "stop_loss_pct": stop_loss_pct,
            "should_buy": bool(direction == "BULLISH"),
            "quantiles": {"up_q10": round(up10, 2), "up_q50": round(up50, 2), "up_q90": round(up90, 2),
                          "down_q10": round(dn10, 2), "down_q50": round(dn50, 2), "down_q90": round(dn90, 2)},
            "direction_proba": {str(c): round(float(p), 3) for c, p in zip(classes, proba)},
            "confidence_prob": round(float(np.max(proba)), 3),  # calibrated P(direction correct)
            # dir_basis tells the UI what the direction MEANS: 1D/3D are trained on
            # EXCESS-of-Nifty labels (BULLISH = outperform the market, BEARISH = underperform),
            # while INTRADAY is absolute (BULLISH = actually rises). Without this the UI shows a
            # relative "BEARISH" next to an absolute down-target and it reads like a crash call.
            "dir_basis": ("vs_nifty" if (tf in ("1D", "3D")
                          and self.manifest.get("excess_labels", True)) else "absolute"),
            "source": "ml:hgbt-quantile",
        }

        # ── INTRADAY "already gone" against a live price ─────────────────────
        # Anchor the estimated high to the SESSION reference (previous close), NOT the
        # live price — otherwise the ceiling floats up with the price and can never be
        # "reached". up90 was trained on the entry day's High vs its close (daily proxy).
        if tf == "INTRADAY":
            anchor = anchor_close if (anchor_close and anchor_close > 0) else price
            intraday_est_high = round(anchor * (1 + _est_high_pct / 100.0), 2)
            ref = live_price if (live_price and live_price > 0) else None
            hi_today = today_high if (today_high and today_high > 0) else None
            already_gone = False
            headroom_pct = None
            if ref is not None:
                already_gone = ref >= intraday_est_high or (hi_today is not None and hi_today >= intraday_est_high)
                headroom_pct = round((intraday_est_high / ref - 1) * 100.0, 2)
            out["intraday"] = {
                "session_anchor": round(anchor, 2),
                "live_price": round(ref, 2) if ref else None,
                "today_high": round(hi_today, 2) if hi_today else None,
                "estimated_high": intraday_est_high,
                "already_gone": already_gone,
                "headroom_pct": headroom_pct,
            }
        return out

    def predict_all_tf(self, ticker: str, live_price: float | None = None,
                       today_high: float | None = None, news_score: int = 0) -> dict:
        """Predict all 3 timeframes for `ticker`. Returns {ticker, price, tfs:{TF:{...}}}."""
        if not self.available:
            return {"ticker": ticker, "available": False, "source": "ml_unavailable",
                    "error": "model artifacts not loaded"}
        try:
            from data_sources import fetch_ohlcv
            sc, sh, sl, sv = fetch_ohlcv(ticker, "2y")
            def _series(df, tk):
                s = df[tk]
                # Guard against duplicate ticker columns (df[tk] → DataFrame): merge
                # row-wise so a sparse duplicate can't shrink the history via dropna().
                if isinstance(s, pd.DataFrame):
                    s = s.bfill(axis=1).iloc[:, 0]
                return s.dropna()
            c, h, l, v = _series(sc, ticker), _series(sh, ticker), _series(sl, ticker), _series(sv, ticker)
        except Exception as e:
            return {"ticker": ticker, "available": False, "source": "ml_unavailable",
                    "error": f"OHLCV fetch failed: {e}"}
        if len(c) < 26:
            return {"ticker": ticker, "available": False, "source": "ml_unavailable",
                    "error": "insufficient history"}

        nifty_c, vix_c = self._indices()
        feat = compute_features(c, h, l, v, nifty_c, vix_c, date=c.index[-1])
        if feat is None:
            return {"ticker": ticker, "available": False, "source": "ml_unavailable",
                    "error": "feature computation failed"}
        feat_row = [feat.get(k, float("nan")) for k in self.feature_columns]

        last_close = float(c.iloc[-1])
        price = float(live_price) if (live_price and live_price > 0) else last_close
        atr_pct = feat.get("atr_pct")
        atr14 = (atr_pct / 100.0 * price) if (atr_pct and np.isfinite(atr_pct)) else None

        scale = _live_intraday_scale()  # √(remaining session) if mid-session, else 1.0
        tfs = {}
        for tf in TIMEFRAMES:
            lp = live_price if tf == "INTRADAY" else None
            th = today_high if tf == "INTRADAY" else None
            tfs[tf] = self._predict_tf(feat_row, tf, price, atr14, lp, th, news_score,
                                       anchor_close=last_close,
                                       intraday_scale=(scale if tf == "INTRADAY" else 1.0))

        # ── Low-history / recently-listed guard ──────────────────────────────
        # A stock with < ~1 trading year of bars (a recent IPO like BlueStone) is outside the
        # model's training distribution, so its calibrated confidence and long-window features are
        # unreliable — a HIGH-confidence call would be misleading. Cap confidence at MEDIUM, drop
        # the high-conviction flag, and surface `low_history` so the UI can warn the user.
        _bars = int(len(c))
        _low_history = _bars < _MIN_FULL_HISTORY_BARS
        if _low_history:
            for _d in tfs.values():
                if _d.get("confidence") == "HIGH":
                    _d["confidence"] = "MEDIUM"
                _d["high_conviction"] = False
                _d["low_history"] = True
                _d["low_history_bars"] = _bars

        return {
            "ticker": ticker,
            "available": True,
            "current_price": round(price, 2),
            "last_close": round(last_close, 2),
            "as_of": pd.Timestamp(c.index[-1]).strftime("%Y-%m-%d"),
            "model_cutoff": self.manifest.get("train_cutoff"),
            "low_history": _low_history,
            "history_bars": _bars,
            "tfs": tfs,
        }

    def predict(self, ticker: str, tf: str, price: float | None = None,
                today_high: float | None = None, news_score: int = 0) -> dict:
        """Single-timeframe prediction (thin wrapper over predict_all_tf)."""
        res = self.predict_all_tf(ticker, live_price=price, today_high=today_high, news_score=news_score)
        if not res.get("available"):
            return res
        return res["tfs"].get(tf.upper(), {"error": f"unknown timeframe {tf}"})


def get_ml_predictor() -> MLPredictor:
    return MLPredictor()


if __name__ == "__main__":
    import json
    tk = sys.argv[1] if len(sys.argv) > 1 else "RELIANCE.NS"
    print(json.dumps(get_ml_predictor().predict_all_tf(tk), indent=2, default=str))
