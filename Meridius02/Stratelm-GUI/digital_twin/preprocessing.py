"""
Data preprocessing & feature engineering for the MPC/DL predictors and the
Stratelm-GUI live-inference path.

Turns raw digital-twin telemetry (or real logged car telemetry) into a clean, scaled,
optionally windowed feature matrix, and persists the fitted scaler so inference applies
the EXACT same transform as training.

Grounded in what actually flows through the system:
  * digital_twin telemetry columns (simulate()/mpc.run_closed_loop output)
  * the features Stratelm-GUI's backend serves (`_downsample_chart`: speed, a_ms2,
    grade_pct, forces, powers) -- so a model trained here can score GUI data
  * the real car's MQTT/logged fields (data/real_Telemetry_Example.csv: Velocity,
    Power, arusM, ...) -- see REAL_TELEMETRY_MAP for alignment

PHYSICS NOTE: r_min_m (corner radius) is +inf on straights, which is meaningless to a
scaler. We engineer it into bounded CURVATURE (1/r, 0 on a straight) -- the physically
correct, scale-safe representation of "how hard is this corner".

scikit-learn is preferred (StandardScaler/MinMaxScaler) but NOT required: if it is
absent this module falls back to numpy scalers with the identical fit/transform/
inverse_transform API, and both persist to scaler.pkl. Train on a machine WITH sklearn
to produce a portable sklearn scaler; the fallback keeps the pipeline runnable anywhere.
"""

import os
import pickle

import numpy as np
import pandas as pd

# The user-requested core feature set (all present in digital_twin telemetry).
DEFAULT_FEATURES = ["v_kmh", "a_ms2", "grade_pct", "r_min_m", "active_motor"]

# Real car logged/MQTT field -> digital-twin feature name (best-effort alignment for
# live inference; fields the log doesn't carry, e.g. grade/curvature, come from the
# track model by matching GPS position, not from the payload).
REAL_TELEMETRY_MAP = {
    "Velocity": "v_kmh",
    "Power": "p_motor_elec_w",
    "arusM": "motor_current_a",
    "vinM": "motor_voltage_v",
    "vinBattery": "battery_voltage_v",
    "Distance": "distance_km",
    "EnergyWh": "energy_wh",
}

R_MIN_CAP_M = 1000.0   # radii above this are effectively straight (curvature ~ 0)


# --------------------------------------------------------------------------- #
# Scalers: prefer sklearn, fall back to numpy (identical API, both picklable). #
# --------------------------------------------------------------------------- #
class StandardScalerNP:
    """Zero-mean/unit-variance scaler, sklearn-compatible subset. Module-level so
    pickle can round-trip it without sklearn installed."""

    def fit(self, X):
        X = np.asarray(X, dtype=float)
        self.mean_ = X.mean(axis=0)
        self.scale_ = X.std(axis=0)
        self.scale_[self.scale_ < 1e-8] = 1.0
        return self

    def transform(self, X):
        return (np.asarray(X, dtype=float) - self.mean_) / self.scale_

    def fit_transform(self, X):
        return self.fit(X).transform(X)

    def inverse_transform(self, Xs):
        return np.asarray(Xs, dtype=float) * self.scale_ + self.mean_


class MinMaxScalerNP:
    """Scale each feature to [0, 1] (sklearn-compatible subset)."""

    def __init__(self, feature_range=(0.0, 1.0)):
        self.feature_range = feature_range

    def fit(self, X):
        X = np.asarray(X, dtype=float)
        self.data_min_ = X.min(axis=0)
        self.data_max_ = X.max(axis=0)
        span = self.data_max_ - self.data_min_
        span[span < 1e-8] = 1.0
        self._span = span
        return self

    def transform(self, X):
        lo, hi = self.feature_range
        norm = (np.asarray(X, dtype=float) - self.data_min_) / self._span
        return norm * (hi - lo) + lo

    def fit_transform(self, X):
        return self.fit(X).transform(X)

    def inverse_transform(self, Xs):
        lo, hi = self.feature_range
        norm = (np.asarray(Xs, dtype=float) - lo) / (hi - lo)
        return norm * self._span + self.data_min_


def make_scaler(kind: str = "standard", prefer_sklearn: bool = True):
    """Return a fitted-later scaler. kind in {"standard","minmax"}. Uses sklearn if
    importable, else the numpy fallback above."""
    kind = kind.lower()
    if prefer_sklearn:
        try:
            from sklearn.preprocessing import StandardScaler, MinMaxScaler
            return StandardScaler() if kind == "standard" else MinMaxScaler()
        except ImportError:
            pass
    if kind == "standard":
        return StandardScalerNP()
    if kind == "minmax":
        return MinMaxScalerNP()
    raise ValueError(f"unknown scaler kind {kind!r} (use 'standard' or 'minmax')")


def save_scaler(scaler, path: str = "data/scaler.pkl", feature_names=None):
    """Persist the fitted scaler (+ the feature order it was fit on) to scaler.pkl.
    Uses joblib when available (sklearn's recommended format), else stdlib pickle."""
    payload = {"scaler": scaler, "feature_names": list(feature_names) if feature_names else None}
    try:
        import joblib
        joblib.dump(payload, path)
    except ImportError:
        with open(path, "wb") as f:
            pickle.dump(payload, f)
    return path


def load_scaler(path: str = "data/scaler.pkl"):
    """Load a scaler saved by save_scaler(). Returns (scaler, feature_names)."""
    try:
        import joblib
        payload = joblib.load(path)
    except (ImportError, Exception):  # noqa: BLE001 -- joblib may not be present
        with open(path, "rb") as f:
            payload = pickle.load(f)
    return payload["scaler"], payload.get("feature_names")


# --------------------------------------------------------------------------- #
# Feature engineering                                                          #
# --------------------------------------------------------------------------- #
def engineer_features(df: pd.DataFrame, features=None, add_derived: bool = True) -> pd.DataFrame:
    """
    Select `features` from a telemetry frame and engineer physics-consistent columns.

    - r_min_m (inf on straights) -> curvature_1pm = 1/r_min_m, plus a capped r_min_m.
    - add_derived also appends v_ms and jerk (d a / d t, from a_ms2 & any t_s column).
    Returns a DataFrame of numeric feature columns (NaN-safe), ready to scale.
    """
    features = list(features) if features is not None else list(DEFAULT_FEATURES)
    out = pd.DataFrame(index=df.index)

    for col in features:
        if col == "r_min_m" and "r_min_m" in df:
            r = df["r_min_m"].to_numpy(dtype=float)
            out["curvature_1pm"] = np.where(np.isfinite(r) & (r > 0), 1.0 / r, 0.0)
            out["r_min_m"] = np.clip(np.where(np.isfinite(r), r, R_MIN_CAP_M), 0.0, R_MIN_CAP_M)
        elif col in df:
            out[col] = pd.to_numeric(df[col], errors="coerce")
        # silently skip a requested feature the frame doesn't have (logged in report)

    if add_derived:
        if "v_kmh" in out:
            out["v_ms"] = out["v_kmh"] / 3.6
        if "a_ms2" in out and "t_s" in df:
            dt = np.diff(df["t_s"].to_numpy(dtype=float), prepend=df["t_s"].iloc[0])
            dt[dt <= 0] = np.nan
            out["jerk_ms3"] = np.nan_to_num(np.diff(out["a_ms2"].to_numpy(),
                                                    prepend=out["a_ms2"].iloc[0]) / dt)

    return out.fillna(0.0)


def make_windows(X, y=None, window: int = 10, horizon: int = 1, stride: int = 1):
    """
    Time-series windowing for sequential models (LSTM/GRU/TCN).

    X: (n, n_features) scaled matrix. Returns Xw: (n_windows, window, n_features).
    If y is given (n,), returns (Xw, yw) where yw[k] = y at the end of window k +
    (horizon-1), i.e. the value `horizon` steps ahead of the window's last input.
    """
    X = np.asarray(X, dtype=float)
    n = len(X)
    xs, ys = [], []
    last = n - horizon  # need a target `horizon` steps past the window end
    for start in range(0, last - window + 1, stride):
        end = start + window
        xs.append(X[start:end])
        if y is not None:
            ys.append(np.asarray(y)[end + horizon - 1])
    Xw = np.asarray(xs, dtype=float)
    if y is None:
        return Xw
    return Xw, np.asarray(ys, dtype=float)


def preprocess_telemetry(df: pd.DataFrame, features=None, scaler_kind: str = "standard",
                         target: str = None, window: int = None, horizon: int = 1,
                         add_derived: bool = True, scaler=None):
    """
    Full pipeline: engineer -> scale -> (optional) window.

    Returns a dict:
        X            : scaled feature matrix (or windowed (n,window,feat) if window set)
        y            : target vector aligned to X (present iff `target` given)
        scaler       : the fitted scaler (fit here unless one is passed in)
        feature_names: engineered feature column order (what the scaler expects)
        skipped      : requested features absent from df
    Pass a previously fitted `scaler` (e.g. loaded from scaler.pkl) to transform new
    data without refitting -- essential for live inference matching training.
    """
    features = list(features) if features is not None else list(DEFAULT_FEATURES)
    feats_df = engineer_features(df, features=features, add_derived=add_derived)
    feature_names = list(feats_df.columns)
    skipped = [f for f in features if f not in df.columns and f != "r_min_m"]

    if scaler is None:
        scaler = make_scaler(scaler_kind)
        X = scaler.fit_transform(feats_df.to_numpy())
    else:
        X = scaler.transform(feats_df.to_numpy())

    y = None
    if target is not None:
        if target not in df:
            raise KeyError(f"target column {target!r} not in telemetry")
        y = df[target].to_numpy(dtype=float)

    if window:
        if y is not None:
            X, y = make_windows(X, y, window=window, horizon=horizon)
        else:
            X = make_windows(X, window=window, horizon=horizon)

    return {"X": X, "y": y, "scaler": scaler, "feature_names": feature_names, "skipped": skipped}


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
_TELEMETRY_CANDIDATES = [
    "data/simulated_telemetry_mpc.csv", "data/simulated_telemetry_ga.csv",
    "data/simulated_telemetry_pso.csv", "data/simulated_telemetry_cma.csv",
    "data/simulated_telemetry_crude.csv",
]


def _autodetect():
    for p in _TELEMETRY_CANDIDATES:
        if os.path.exists(p):
            return p
    raise SystemExit("No telemetry CSV in data/. Run a simulate/mpc first.")


def _tag_from_path(path: str) -> str:
    """Per-algorithm tag from a telemetry filename so scalers/arrays never overwrite
    across algorithms. e.g. data/simulated_telemetry_ga.csv -> 'ga'."""
    base = os.path.splitext(os.path.basename(path))[0]
    return base.replace("simulated_telemetry_", "") or "telemetry"


def _run_one(path, scaler_kind, target, window, horizon):
    tag = _tag_from_path(path)
    df = pd.read_csv(path)
    res = preprocess_telemetry(df, scaler_kind=scaler_kind, target=target,
                               window=(window or None), horizon=horizon)
    out_scaler = f"data/scaler_{tag}.pkl"
    out_data = f"data/preprocessed_{tag}.npz"
    save_scaler(res["scaler"], out_scaler, feature_names=res["feature_names"])
    np.savez_compressed(out_data, X=res["X"],
                        y=(res["y"] if res["y"] is not None else np.array([])),
                        feature_names=np.array(res["feature_names"]))
    print(f"[{tag}] {path} ({len(df)} rows) -> {out_scaler}, {out_data}")
    print(f"  features ({len(res['feature_names'])}): {res['feature_names']}"
          + (f"  | skipped {res['skipped']}" if res["skipped"] else ""))
    print(f"  scaler {type(res['scaler']).__name__}  X {np.asarray(res['X']).shape}"
          + (f"  y {np.asarray(res['y']).shape}" if res["y"] is not None else ""))
    return tag


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Preprocess telemetry: feature-engineer, scale, window.")
    ap.add_argument("--telemetry", default=None)
    ap.add_argument("--all", action="store_true", help="run for every telemetry CSV found in data/")
    ap.add_argument("--scaler", choices=["standard", "minmax"], default="standard")
    ap.add_argument("--target", default="v_kmh", help="target column for supervised windowing")
    ap.add_argument("--window", type=int, default=10, help="0 disables windowing")
    ap.add_argument("--horizon", type=int, default=1)
    args = ap.parse_args()

    if args.all:
        paths = [p for p in _TELEMETRY_CANDIDATES if os.path.exists(p)]
        if not paths:
            raise SystemExit("No telemetry CSVs found in data/.")
        for p in paths:
            _run_one(p, args.scaler, args.target, args.window, args.horizon)
    else:
        path = args.telemetry or _autodetect()
        _run_one(path, args.scaler, args.target, args.window, args.horizon)


if __name__ == "__main__":
    main()
