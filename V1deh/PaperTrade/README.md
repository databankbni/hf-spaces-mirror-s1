---
title: PaperTrade
emoji: 📈
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
app_port: 7860
---

# PaperTrade — NSE Indian Equity Prediction Engine

A paper trading system for NSE Indian equities. Predicts short-term price direction (1D/3D/5D) using backtested technical strategies, an ML feature scorer, macro gates, news sentiment, and an LLM-based directional forecast.

## Recent Reliability Improvements

- Manual trade entries now attempt a best-effort auto-scan at order time to populate missing strategy, timeframe, and prediction context.
- Post-mortems for manual trades now include concrete trade-window price diagnostics (swing, MFE, MAE, trend) to avoid generic commentary.
- Frontend trade submit now waits for in-flight watchlist context fetch before posting, reducing empty post-mortem context.
- Timeframe calibration in the AI forecast path was tightened to use shallow bearish midpoint ranges and safer weak-bear handling.
