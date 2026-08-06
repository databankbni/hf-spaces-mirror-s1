"""ml_predictor — standalone supervised ML price-prediction model for NSE equities.

A quantile-regression predictor (sklearn HistGradientBoosting) that outputs, per
timeframe (INTRADAY / 1D / 3D): a price estimate, buy-price suggestion, stop-loss,
and trend (BULLISH / BEARISH / NEUTRAL). Independent of the LLM debate pipeline.

Modules:
  features.py  — shared point-in-time numeric feature builder (all indicators + ML sub-features)
  dataset.py   — build training_data.csv from the ohlcv_cache.db (offline)
  train.py     — fit the 15 HistGBM estimators + manifest.json
  infer.py     — MLPredictor: predict(ticker, tf) / predict_all_tf(ticker)

See CLAUDE.md and the plan for the full design.
"""

from .features import FEATURE_COLUMNS, TIMEFRAMES, compute_features  # noqa: F401
