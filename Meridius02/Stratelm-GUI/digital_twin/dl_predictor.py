"""
Inference wrapper for the deep-learning predictors trained by
scripts/train_dl_model.py. This is the bridge MPC_SPEC.md section 6 calls for:
the MPC controller asks a DLPredictor "where is the driver headed next?" (and,
optionally, "what will this cost in H2?") during its horizon rollout.

DESIGN: graceful degradation. Training needs PyTorch, but neither PyTorch nor the
trained .pth files may exist when the MPC pipeline first runs. So this module NEVER
hard-fails: if torch or a model artifact is missing, each predictor transparently
falls back to a cheap analytic estimate and reports `.<x>_available == False`. That
lets mpc.py / optimize_ga.py run end-to-end today and automatically pick up the
neural nets the moment they are trained -- no code change at the call site.

    from digital_twin.dl_predictor import DLPredictor
    dl = DLPredictor()                       # loads data/dl_*.pth if present
    v_next = dl.predict_next_state(state)    # driver's predicted next speed (km/h)
    h2 = dl.predict_h2_flow_gs(state)        # surrogate H2 flow, or None if physics-only
"""

import json
import os

import numpy as np

OUT_DIR = "data"


class _SingleModel:
    """One trained MLP (driver-intent OR h2-surrogate) + its normalization stats.
    Loads lazily; `available` is False when torch or the artifact is absent."""

    def __init__(self, artifact: str, out_dir: str = OUT_DIR):
        self.artifact = artifact
        self.available = False
        self.features = []
        self.target = None
        self._model = None
        self._torch = None
        self._meta = None
        self._load(out_dir)

    def _load(self, out_dir):
        pth = os.path.join(out_dir, self.artifact + ".pth")
        meta = os.path.join(out_dir, self.artifact + ".meta.json")
        if not (os.path.exists(pth) and os.path.exists(meta)):
            return
        try:
            import torch
            import torch.nn as nn
        except ImportError:
            return
        try:
            with open(meta) as f:
                m = json.load(f)
            layers, prev = [], len(m["features"])
            for h in m.get("hidden", [64, 64]):
                layers += [nn.Linear(prev, h), nn.ReLU()]
                prev = h
            layers += [nn.Linear(prev, 1)]
            model = nn.Sequential(*layers)
            model.load_state_dict(torch.load(pth, map_location="cpu"))
            model.eval()
            self._torch, self._model, self._meta = torch, model, m
            self.features, self.target = m["features"], m["target"]
            self._x_mean = np.asarray(m["x_mean"], dtype=np.float32)
            self._x_std = np.asarray(m["x_std"], dtype=np.float32)
            self._y_mean = np.asarray(m["y_mean"], dtype=np.float32)
            self._y_std = np.asarray(m["y_std"], dtype=np.float32)
            self.available = True
        except Exception as exc:   # corrupt artifact, arch mismatch, etc.
            print(f"DLPredictor: failed to load {self.artifact} ({exc!r}); using fallback.")

    def predict(self, state: dict) -> float:
        """Run the net on a state dict. Missing features default to 0.0."""
        x = np.array([[float(state.get(f, 0.0)) for f in self.features]], dtype=np.float32)
        xn = (x - self._x_mean) / self._x_std
        with self._torch.no_grad():
            yn = self._model(self._torch.from_numpy(xn)).numpy()
        return float(yn[0, 0] * self._y_std[0] + self._y_mean[0])


class DLPredictor:
    """
    Bundle of the two MPC-facing predictors. Instantiate once and pass into the
    MPC controller; query per step during horizon rollout.

    Attributes:
        driver_available : True if the trained driver-intent net loaded.
        h2_available     : True if the trained H2-surrogate net loaded.
    """

    def __init__(self, out_dir: str = OUT_DIR, fallback_dt_s: float = 0.1):
        self.fallback_dt_s = fallback_dt_s
        self._driver = _SingleModel("dl_driver_intent", out_dir)
        self._h2 = _SingleModel("dl_h2_surrogate", out_dir)

    @property
    def driver_available(self) -> bool:
        return self._driver.available

    @property
    def h2_available(self) -> bool:
        return self._h2.available

    def predict_next_state(self, current_state: dict, track_features: dict = None) -> float:
        """
        Predicted ACTUAL driver speed at the next step, in km/h.

        `current_state` should carry at least speed_kmh and acceleration_ms2 (plus
        throttle_pct/brake_pct/steering_angle_deg/ambient_temp_c/wind_speed_ms if the
        trained model uses them). `track_features` is accepted for API symmetry
        (grade/heading ahead) and folded in when present.

        Fallback (no trained net): kinematic persistence
        v_next = v + a*dt, clamped to >= 0.
        """
        if self._driver.available:
            state = dict(current_state)
            if track_features:
                state.update(track_features)
            return max(0.0, self._driver.predict(state))
        # analytic fallback -- see docstring
        v = float(current_state.get("speed_kmh", 0.0))
        a = float(current_state.get("acceleration_ms2", 0.0))
        return max(0.0, v + a * 3.6 * self.fallback_dt_s)

    def predict_h2_flow_gs(self, current_state: dict):
        """
        Surrogate instantaneous H2 flow (g/s). Returns None when no surrogate net is
        loaded, which is the signal for MPC to use the exact powertrain physics
        instead (the surrogate is only a speed optimization, never a correctness
        dependency)."""
        if self._h2.available:
            return max(0.0, self._h2.predict(current_state))
        return None

    def __repr__(self):
        return (f"DLPredictor(driver_available={self.driver_available}, "
                f"h2_available={self.h2_available})")
