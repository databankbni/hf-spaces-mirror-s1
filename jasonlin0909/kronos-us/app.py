"""
Hosted US-stock Kronos dashboard for HuggingFace Spaces (Docker SDK).

Same Flask app as ../dashboard.py, adapted for hosting:
  * binds 0.0.0.0:7860 (the port HF Spaces expects),
  * pre-loads the model at startup so the first request isn't slow,
  * a lower default n_paths keeps a request comfortably under proxy timeouts.
"""
import os

from flask import Flask, jsonify, render_template, request

import engine

app = Flask(__name__, template_folder="templates")

# Ceiling on ensemble size so a single hosted request can't run for minutes.
MAX_PATHS = int(os.environ.get("MAX_PATHS", "30"))


@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/api/health")
def health():
    return jsonify({"ok": True, "model_loaded": engine.is_loaded()})


@app.route("/api/profile")
def profile():
    ticker = request.args.get("ticker", "AAPL").upper().strip()
    interval = request.args.get("interval", "1d")
    prof = engine.load_profile(ticker, interval)
    return jsonify({"exists": prof is not None, "profile": prof})


@app.route("/api/forecast", methods=["POST"])
def forecast():
    p = request.get_json(force=True) or {}
    try:
        n_paths = min(int(p.get("n_paths", 20)), MAX_PATHS)
        result = engine.run_ensemble(
            ticker=str(p.get("ticker", "AAPL")).upper().strip(),
            interval=str(p.get("interval", "1d")),
            period=str(p.get("period", "3y")),
            lookback=int(p.get("lookback", 400)),
            pred_len=int(p.get("pred_len", 20)),
            mode=str(p.get("mode", "backtest")),
            n_paths=n_paths,
            T=float(p.get("T", 0.7)),
            top_p=float(p.get("top_p", 0.9)),
            top_k=int(p.get("top_k", 0)),
            seed=int(p.get("seed", 123)),
            band_scale=float(p.get("band_scale", 1.0)),
        )
        return jsonify({"ok": True, "result": result})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


if __name__ == "__main__":
    # Warm the model before serving so the first user request is fast.
    print("[startup] pre-loading Kronos model ...", flush=True)
    try:
        engine.get_predictor()
        print("[startup] model ready.", flush=True)
    except Exception as exc:
        print(f"[startup] model preload failed (will retry on first request): {exc}", flush=True)
    app.run(host="0.0.0.0", port=7860, threaded=True)
