# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FAANG-Robotrader is an automated AI-driven virtual trading system that benchmarks the FAANG Pulse AI machine learning model in a real-world simulation. Four virtual investors (Safe Sam, Optimal Owen, Brave Beth, Random Randy) each start with $500,000 and trade FAANG stocks (AAPL, AMZN, GOOGL, NFLX, META) based on trend predictions from an external ML API. GitHub Actions runs trading logic daily at 22:00 UTC (Mon–Fri) and commits the results back to the repo.

## Commands

```powershell
# Activate virtual environment (Python 3.13)
.venv\Scripts\activate

# Run the Gradio dashboard (opens at http://localhost:7860)
uv run app.py

# Run live trading (fetches today's prices and executes trades)
uv run trading_logic.py

# Sync dependencies after modifying pyproject.toml
uv lock
uv pip compile pyproject.toml -o requirements.txt
```

**Backtesting:** In `trading_logic.py`, change the `__main__` block to call `test_trading()` instead of `live_trading()`. Set `next_trade_date` in `data/trader_attributes.json` to control the start date. `test_trading()` simulates 15 trading days forward.

There is no automated test suite — validation is done through backtesting and visual inspection of the Gradio dashboard.

## Architecture

| File | Role |
|------|------|
| `app.py` | Gradio dashboard with 3 chart views: Trade Actions Summary, Cash Status, Per Stock Returns |
| `trading_logic.py` | Core trading engine — fetches prices/predictions, executes investor strategies, writes CSV logs |
| `data_server.py` | `investmentRecords` class — reads CSV logs and builds analytics DataFrames for the GUI |
| `data/*.csv` | Persistent trade history, one file per investor |
| `data/trader_attributes.json` | Per-investor config: `decision_threshold`, `next_trade_date`, initial capital |
| `.github/workflows/daily_cron.yml` | Scheduler: runs `uv run trading_logic.py`, commits updated CSVs |
| `.github/workflows/sync_to_hf.yml` | Mirrors repo to Hugging Face Space on every push to `main` |

### Data Flow

1. GitHub Actions triggers at market close (22:00 UTC weekdays)
2. `trading_logic.py` → `TradingEngine` fetches OHLCV data from FAANG Pulse AI (`/get_prices_on_date`)
3. For each investor × stock: calls `/run_trend_prediction` → `TREND_UP` / `TREND_DOWN` / `NO_TREND`
4. Investor strategy function executes BUY / SELL / HOLD and appends a row to the investor's CSV
5. Workflow commits updated CSVs; `sync_to_hf.yml` pushes to Hugging Face, which rebuilds the live app

### Key Patterns

- **Strategy pattern** — `get_trading_strategy(investor_name)` returns the correct strategy function; all strategies share `build_new_transaction_row()` for constructing CSV rows.
- **Duplicate prevention** — before inserting, each strategy checks whether a row already exists for the same date + ticker combination.
- **HOLD fallback** — any BUY/SELL that would exceed available cash or shares falls back to HOLD automatically.
- **Random Randy** — uses `seed = hash(date_str + ticker)` for deterministic randomness; serves as the control benchmark to measure ML model value.
- **External ML API** — called via `gradio-client`; the Hugging Face Space URL is configured in `trading_logic.py`.
- **Transient timeout retry** — `_with_retry(fn, max_attempts=3, delay=30)` at the top of `trading_logic.py` wraps both `Client(...)` construction and `api_client.predict(...)` calls. The HF Space is sometimes cold/sleeping at cron time, causing `httpx.ReadTimeout`; this retries up to 3 times with 30s gaps before propagating the error. The workflow step also wraps `uv run trading_logic.py` in a bash retry loop (3 attempts, 60s gap) as a second layer of defence.

### The 4 Investors

| Investor | `decision_threshold` | BUY qty | SELL qty | Style |
|----------|----------------------|---------|----------|-------|
| Safe Sam | −0.135 | 50 | 100 | Conservative |
| Optimal Owen | 0.0 | 20 | 20 | Balanced |
| Brave Beth | 0.045 | 10 | 10 | Aggressive |
| Random Randy | 0.0 | random 1–20 | random 1–20 | Control/random |
