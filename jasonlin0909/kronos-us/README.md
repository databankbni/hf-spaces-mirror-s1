---
title: Kronos US Forecast
emoji: 📈
colorFrom: red
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# Kronos · US-stock Forecast Dashboard

Interactive CPU dashboard for the [Kronos](https://github.com/shiyu-coder/Kronos)
financial time-series model, applied to US stocks (data via yfinance).

Pick a ticker and sampling parameters → the server draws an ensemble of sample
paths from Kronos-small → the page shows the **median forecast** with a **10–90%
uncertainty band**, plus accuracy metrics in `backtest` mode.

- **Model / prediction**: 100% original Kronos (`model/`, unmodified).
- **This app**: US data adapter, hold-out accuracy backtest, ensemble median+band,
  metrics, and the interactive UI.

⚠️ Runs on CPU — each sample path is ~1–2s, so an ensemble takes tens of seconds.
The UI shows a spinner and elapsed time. `n_paths` is capped at 30 for hosting.
