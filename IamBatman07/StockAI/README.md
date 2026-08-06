---
title: Stock Price Forecaster
emoji: "📈"
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# Stock Price Forecaster

Flask app for historical stock analysis, correlation heatmaps and next-day return
forecasting. Market data comes from Yahoo Finance via `yfinance` — no API key needed.

**What you can do here**

- Chart a ticker's history and compare correlations across a basket
- Run a forecast and see split-conformal prediction intervals derived from the
  model's own held-out errors (measured coverage 80.8% / 99.2%)
- Run a cost-aware long/flat backtest that always reports buy-and-hold beside the
  strategy — zero-cost runs are refused at the schema level

**Measured result:** across a 10-ticker walk-forward at 5 bps per side, no
forecaster beats buy-and-hold — best net Sharpe 1.34 (ARIMA) against 1.83.
That is the finding, not a caveat.

Nothing here is investment advice.

Source and evaluation harness: https://github.com/Mark007-R/Stock-Price-Forecaster
