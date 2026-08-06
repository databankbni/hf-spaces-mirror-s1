"""
Train the deep-learning predictors that feed the MPC controller (MPC_SPEC.md
section 6, driver-awareness, and the surrogate-rollout option in section 3.2).

Two models are trained from the 10 Hz synthetic telemetry produced by the sister
project Constraint-SImulation (fuzzy-driven, ~19k rows):

  1. DRIVER-INTENT model  -> predicts the driver's ACTUAL speed at the next step
     (speed_kmh[t+1]) from the current driving state. MPC uses this to anticipate
     how far the human will deviate from its setpoint and correct ahead of time.

  2. H2 SURROGATE model   -> predicts instantaneous hydrogen flow (h2_flow_gs) from
     the current state. MPC can call this instead of the full physics chain during
     horizon rollout for a faster inner loop.

Both are small MLPs (this is tabular per-step regression, not a sequence task, so an
MLP is the right tool; swap in an LSTM here if you later move to windowed inputs).

Requires PyTorch (NOT installed in the CI/dev sandbox this was written in -- install
locally and run):

    pip install torch
    python3 scripts/train_dl_model.py                 # trains both, saves to data/
    python3 scripts/train_dl_model.py --epochs 200 --model driver
    python3 scripts/train_dl_model.py --telemetry path/to/telemetry.csv

Artifacts written to data/ (consumed by digital_twin/dl_predictor.py):
    dl_driver_intent.pth   + dl_driver_intent.meta.json
    dl_h2_surrogate.pth    + dl_h2_surrogate.meta.json
The .meta.json holds feature/target column names and the input/output
normalization stats, so inference reproduces training-time scaling exactly.
"""

import argparse
import json
import os

import numpy as np
import pandas as pd

# Repo-root-relative defaults (Constraint-SImulation is nested inside Fp_Webpro).
DEFAULT_TELEMETRY = "Constraint-SImulation/outputs/telemetry.csv"
OUT_DIR = "data"

# Feature/target schema per model. Features are columns MPC can supply at inference;
# targets are what the model predicts.
MODELS = {
    "driver": {
        "artifact": "dl_driver_intent",
        "features": ["speed_kmh", "acceleration_ms2", "throttle_pct", "brake_pct",
                     "steering_angle_deg", "ambient_temp_c", "wind_speed_ms"],
        "target": "speed_kmh_next",   # engineered below: speed_kmh shifted by -1
        "desc": "driver intent: next-step speed_kmh",
    },
    "h2": {
        "artifact": "dl_h2_surrogate",
        "features": ["speed_kmh", "acceleration_ms2", "motor_power_w", "ambient_temp_c"],
        "target": "h2_flow_gs",
        "desc": "energy surrogate: instantaneous H2 flow (g/s)",
    },
}


def load_telemetry(path):
    df = pd.read_csv(path)
    # Engineered target for the driver model: the NEXT row's speed within the same lap.
    df["speed_kmh_next"] = df["speed_kmh"].shift(-1)
    df = df.dropna(subset=["speed_kmh_next"]).reset_index(drop=True)
    return df


def build_mlp(torch, nn, n_in, n_out, hidden=(64, 64)):
    layers, prev = [], n_in
    for h in hidden:
        layers += [nn.Linear(prev, h), nn.ReLU()]
        prev = h
    layers += [nn.Linear(prev, n_out)]
    return nn.Sequential(*layers)


def standardize(arr):
    mean = arr.mean(axis=0)
    std = arr.std(axis=0)
    std[std < 1e-8] = 1.0            # guard constant columns
    return (arr - mean) / std, mean, std


def train_one(model_key, df, epochs, lr, batch_size, seed):
    import torch
    import torch.nn as nn

    torch.manual_seed(seed)
    np.random.seed(seed)
    spec = MODELS[model_key]

    X = df[spec["features"]].to_numpy(dtype=np.float32)
    y = df[[spec["target"]]].to_numpy(dtype=np.float32)

    Xn, x_mean, x_std = standardize(X)
    yn, y_mean, y_std = standardize(y)

    # deterministic 85/15 train/val split
    n = len(Xn)
    idx = np.random.permutation(n)
    n_val = max(1, int(0.15 * n))
    val_idx, tr_idx = idx[:n_val], idx[n_val:]
    Xt, yt = torch.from_numpy(Xn[tr_idx]), torch.from_numpy(yn[tr_idx])
    Xv, yv = torch.from_numpy(Xn[val_idx]), torch.from_numpy(yn[val_idx])

    model = build_mlp(torch, nn, len(spec["features"]), 1)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.MSELoss()

    best_val, best_state = float("inf"), None
    for epoch in range(epochs):
        model.train()
        perm = torch.randperm(len(Xt))
        for b in range(0, len(Xt), batch_size):
            bi = perm[b:b + batch_size]
            opt.zero_grad()
            loss = loss_fn(model(Xt[bi]), yt[bi])
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            val = loss_fn(model(Xv), yv).item()
        if val < best_val:
            best_val, best_state = val, {k: v.clone() for k, v in model.state_dict().items()}
        if epoch % 20 == 0 or epoch == epochs - 1:
            # report val RMSE back in real units
            rmse_real = float(np.sqrt(val) * y_std[0])
            print(f"  [{model_key}] epoch {epoch:4d}  val_mse(norm)={val:.5f}  "
                  f"val_rmse~={rmse_real:.4f} {spec['target']} units")

    model.load_state_dict(best_state)

    os.makedirs(OUT_DIR, exist_ok=True)
    pth = os.path.join(OUT_DIR, spec["artifact"] + ".pth")
    meta = os.path.join(OUT_DIR, spec["artifact"] + ".meta.json")
    torch.save(model.state_dict(), pth)
    with open(meta, "w") as f:
        json.dump({
            "model_key": model_key,
            "description": spec["desc"],
            "features": spec["features"],
            "target": spec["target"],
            "hidden": [64, 64],
            "x_mean": x_mean.tolist(), "x_std": x_std.tolist(),
            "y_mean": y_mean.tolist(), "y_std": y_std.tolist(),
            "val_mse_norm": best_val,
            "n_train": int(len(tr_idx)), "n_val": int(len(val_idx)),
        }, f, indent=2)
    print(f"  [{model_key}] saved {pth} + {meta}  (best val_mse={best_val:.5f})")


def main():
    ap = argparse.ArgumentParser(description="Train MPC deep-learning predictors.")
    ap.add_argument("--telemetry", default=DEFAULT_TELEMETRY)
    ap.add_argument("--model", choices=["driver", "h2", "both"], default="both")
    ap.add_argument("--epochs", type=int, default=120)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    try:
        import torch  # noqa: F401
    except ImportError:
        raise SystemExit(
            "PyTorch is required to train. Install it first:\n    pip install torch\n"
            "(digital_twin/dl_predictor.py still runs WITHOUT torch via its analytic "
            "fallback, so the MPC pipeline works before these models exist.)")

    if not os.path.exists(args.telemetry):
        raise SystemExit(f"Telemetry not found: {args.telemetry}")

    print(f"Loading telemetry: {args.telemetry}")
    df = load_telemetry(args.telemetry)
    print(f"  {len(df)} usable rows (after next-step target engineering)")

    keys = ["driver", "h2"] if args.model == "both" else [args.model]
    for k in keys:
        print(f"\nTraining {k}: {MODELS[k]['desc']}")
        train_one(k, df, args.epochs, args.lr, args.batch_size, args.seed)

    print("\nDone. digital_twin/dl_predictor.py will now load these instead of "
          "falling back to the analytic predictor.")


if __name__ == "__main__":
    main()
