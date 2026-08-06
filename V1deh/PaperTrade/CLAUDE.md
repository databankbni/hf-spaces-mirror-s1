# PaperTrade — NSE Indian Equity Prediction Engine

## Deployment — HF Spaces (primary) and local

**This is a deployed web application hosted on Hugging Face Spaces. Always think about HF Spaces first when reasoning about storage, paths, and environment.**

- **Primary deployment**: HF Spaces (persistent disk, `/data/` mount — not `/tmp/`).
- **Local dev**: runs via `python app.py` from the project root.
- **Database**: `paper_trading.db` — gitignored, persists on HF Spaces' persistent volume. On startup `app.py` restores it from the HF Hub dataset if the local file is missing.
- **OHLCV cache**: stored in `paper_trading.db → ohlcv_cache` table (SQLite blob). **Not** file-based.
- **Environment secrets**: `.env` file locally; HF Spaces `Secrets` tab in production. Use `export_env_secrets.py` to sync secrets to HF Spaces.
- **Static files**: `static/` served by Flask. All JS/CSS is inline — no CDN (HF CSP blocks external URLs).
- **No `pathlib.Path(__file__).parent` for data files** — use `os.path.dirname(__file__)` or HF Spaces paths. Pickle/file caches do not survive HF Spaces container restarts; use SQLite instead.
- **`app.run(..., threaded=True)` is required** (fixed 2026-08-04). Dockerfile CMD is `python app.py`, not gunicorn — Werkzeug's dev server defaults to single-threaded, so ONE slow AI/LLM request (up to ~90s with the Ollama fallback) blocked every other concurrent request, including the otherwise-instant `/api/ml-predict/<ticker>` — ML rows looked permanently stuck on "🤖 ML…" behind a slow AI call. The DB layer (`database.py::_conn()`, WAL + `busy_timeout=5000`) was already built to tolerate concurrent access, so this was safe to flip on.

---

## What this project is

A paper trading system for NSE Indian equities. It predicts short-term price direction (1D/3D/5D) using a combination of backtested technical strategies, an ML feature scorer, macro gates, news sentiment, and an LLM-based directional forecast. Predictions are served via an MCP server (`stock_predictor_mcp.py`) and a Flask web app (`app.py`), which also runs a full paper-trading book (open/close trades, pending orders, stop checks) and a prediction-validation audit trail.

---

## Architecture

```
predictor_core.py          ← main prediction API (predict_stock_v2, rank_stocks_v2)
  ├── trial_run.py         ← 20+ strategy signal generators (S1–S20, S_CTRIO, etc.)
  ├── ml_combiner.py       ← ML feature functions (bollinger_position, ema_stack_score, shadow_flag)
  ├── macro_context.py     ← macro gates (S&P500, USD/INR, crude) + FRED regime gate
  ├── fred_data.py         ← US macro indicators (yield curve, Fed rate, CPI, USD index)
  ├── news_sentiment.py    ← Claude Haiku news sentiment fetch + analysis
  ├── ai_forecast.py       ← LLM directional forecast (bull/bear/fundamentals debate → synthesis)
  ├── social_sentiment.py  ← Reddit + StockTwits sentiment (injected into debate prompts)
  ├── fundamentals.py      ← stock fundamentals scorer (PE, D/E, revenue, ROE, FCF)
  ├── sector_pulse.py      ← NSE sector heatmap + rotation detection (10 sector indices)
  ├── fii_flow.py          ← FII/DII flow data + Nifty PCR
  ├── price_targets.py     ← Camarilla / ATR / PDH price targets
  ├── intraday_live.py     ← live ORB + VWAP context
  ├── data_sources.py      ← multi-source OHLCV + live-price fetcher (NSE → Twelve Data → Yahoo fallback)
  └── universe.py          ← dynamic NSE universe (Yahoo Finance screener, cached)

top5_picker.py             ← top picks (up to 20) across INTRADAY/1D, concurrent, ATR-volatility ranked
model_picker.py            ← GitHub Models availability checker / selector (standalone utility)
stock_predictor_mcp.py     ← MCP server (predict_stocks, rank_best_stocks tools)
app.py                     ← Flask web UI + paper-trading book + validation audit trail
database.py                ← SQLite: trades, pending orders, prediction snapshots, postmortems
risk_engine.py             ← portfolio risk metrics (Sharpe, drawdown, beta, Kelly)

ml_predictor/              ← standalone supervised ML price model (sklearn quantile GBT)
  ├── features.py          ← shared point-in-time feature builder (all indicators + ML sub-features)
  ├── dataset.py           ← build training_data.csv from ohlcv_cache.db (offline)
  ├── train.py             ← fit 21 HistGradientBoosting estimators + manifest.json
  ├── infer.py             ← MLPredictor.predict_all_tf(ticker) → full schema (INTRADAY/1D/3D)
  └── models/              ← committed joblib artifacts (model persistence on HF Spaces)

research/
  ├── backtest.py                  ← LLM prompt accuracy backtest (1D/3D/5D)
  ├── ml_backtest.py               ← ML model accuracy + P&L backtest (reuses _graded_hit grading)
  ├── ml_selection_backtest.py     ← ML top-N stock-selection backtest (rank/confidence/--filters, 1/3/5d hold)
  ├── ml_watchlist_eval.py         ← grade ML predictions on the DB watchlist vs realized outcomes
  ├── ml_intraday_backtest.py      ← TRUE intraday backtest (15-min bars, 09:15/12:00/14:00 → touch-by-15:00)
  ├── loop_backtest.py             ← iterative prompt-optimization loop
  ├── schedule_loop_backtest.py    ← macOS launchd scheduler for the loop
  ├── new_features_backtest.py     ← backtest for fred/fundamentals/sector modules
  ├── entry_validation_backtest.py ← ATR/Camarilla/PDH target-containment backtest
  ├── target_backtest.py           ← price-target touch/containment backtest
  ├── compare_predictors.py        ← A/B two predictor labels on the same test set
  ├── experiment_features.py       ← backtest-only experimental context builders
  ├── stock_ranker.py              ← CLI ranker (--start/--end/--capital)
  ├── validate_on_trades.py        ← validate LLM on actual paper trade dates (fast sanity check)
  └── qlib_train.py                ← LightGBM trainer (EXPERIMENTAL — not wired into prod)
```

> **Note:** `nse_universe.py` has been **replaced** by `universe.py` (dynamic, Yahoo-confirmed tickers). `top5_picker.py` imports `DEFAULT_UNIVERSE` / `rank_stocks_v2` from `predictor_core`.

---

## Prediction pipeline (predict_stock_v2)

1. **Market gates** — VIX >25 hard blocks all trades. VIX 20–25 reduces size. Nifty below EMA200 reduces expected return 40%. Macro risk-off reduces 20%. FRED risk-off regime reduces further.
2. **Strategy signals** — 20+ NSE-backtested boolean signals (S1–S20, S_CAPFLOW, S_CTRIO, S_SEASONAL). Each fires if condition triggered in last 5 bars.
3. **ML feature score** — 11 weighted features (EMA stack, RS vs Nifty, OBV, MACD, vol ratio, ADX, Supertrend, RSI, Bollinger, VIX, shadow flag) → 0–100 score + logistic probability.
4. **News sentiment** — Claude Haiku via `news_sentiment.py` → BULLISH/NEUTRAL/BEARISH.
5. **Sector pulse** — fetches NSE sector heatmap from `sector_pulse.py`; adds sector-leading flag to prediction output.
6. **Fundamentals** — fetches PE/D/E/ROE/FCF score from `fundamentals.py` (24h cache); passed into AI debate.
7. **AI forecast** — up to 4-call LLM debate (bull → bear → fundamentals analyst → synthesis) when called from watchlist mode (`_run_ai_forecast=True`). Falls back to single-call if debate fails. Falls back to heuristic if no API key.
8. **Confidence scoring** — additive: signals × 2 + ML upgrade + news + Mode B/C bonuses + FII + PCR + Weinstein breadth → HIGH / MEDIUM / LOW.
9. **Risk** — ATR14 stop-loss, R:R targets scaled to timeframe (1D/3D/5D).

**Public API (must stay stable):** `predict_stock_v2(ticker, start_date, end_date, ...)`, `rank_stocks_v2(...)`, `timeframe_to_dates(tf)`.

---

## AI Forecast — Bull/Bear/Fundamentals Debate (ai_forecast.py)

Inspired by TauricResearch/TradingAgents multi-agent debate pattern.

**Flow:**
1. **Social sentiment fetch** — Reddit (r/IndiaInvestments, r/IndianStockMarket, r/Nifty via RSS) + StockTwits public API. Results injected into advocate prompts.
2. **Bull advocate call** (320 tokens) — "Make the strongest possible bull case. Cite exact ₹ levels and indicator values."
3. **Bear advocate call** (320 tokens) — "Make the strongest possible bear case. Cite exact warnings and downside risk."
4. **Fundamentals advocate call** (200 tokens) — "Assess whether business fundamentals support or argue against a trade. Cite PE vs sector, debt, revenue trend, ROE, FCF." Only runs when `fundamentals.py` has data.
5. **Synthesis call** (512 tokens) — "Head of Research: weigh all arguments, the side with more specific data-backed evidence wins. Return JSON."

**Source label** in output:
- `{provider}:{model}+debate+fund` — full debate with fundamentals
- `{provider}:{model}+debate` — bull/bear debate only (no fundamentals data)
- `{provider}:{model}` — single-call fallback
- `heuristic` — no API key

**LLM backends (provider chain):** OpenRouter free tier → Groq (llama-3.3-70b-versatile → llama-3.1-8b-instant) → Cerebras (llama-3.3-70b → llama-3.1-8b) → HuggingFace Router (novita, llama-3.1-8b-instruct) → **Gemini (2.5-flash, ~1,500/day) → SambaNova (70B, persistent free) → NVIDIA NIM (nemotron-super-49b, free)** → Ollama (local only, `OLLAMA_ENDPOINT` must be set). GitHub Models removed — `GITHUB_TOKEN` unused. Gemini/SambaNova/NVIDIA are appended LAST in `_CLOUD_PROVIDERS` so the happy path is unchanged, but the dynamic availability sort auto-promotes them when the first four degrade — adding large independent daily capacity so `_all_cloud_daily_exhausted()` (which triggers the slow single-Ollama funnel) rarely fires. All three no-op without their API key. NVIDIA routes through the shared `_try_openai_compatible` driver, so it inherits the identical timeout/retry/cooldown/daily-exhausted machinery.

**AI unavailable root cause** — "⚠ AI unavailable" means ALL cloud providers failed AND Ollama failed/unavailable. Most common cause: free-tier rate limits exhausted during a 150-stock batch scan (~150–450 LLM calls). Fix: ensure OpenRouter + Groq + Cerebras + HF keys are all set in HF Spaces Secrets. The "Signals active: 0" part of the error is a separate issue — the stock has no technical strategy signals firing, independent of AI.

**Anti-skip design (bounded per-stock + deferred re-queue)** — the old behavior (`fast_fail=False`) made each stock do a long internal wait+retry loop → a single slow/exhausted stock blocked the whole batch for minutes and often ended in a hard SKIP with no partial results. The fix has two homes:

- **Backtest (`research/backtest.py`):** (1) **bounded per-stock attempt** — one pass through available cloud providers + a single Ollama last-resort (~70s cap), never the long internal loop; (2) **deferred-retry rounds** — a stock that gets no provider right now is re-queued and retried after a cooldown (default 90s, `BACKTEST_RETRY_COOLDOWN_SECS`), up to `BACKTEST_MAX_RETRY_ROUNDS` (default 3); (3) successes **stream to CSV immediately**; (4) `reset_ollama_state()` at the start of each round so Ollama's transient backoff doesn't outlive the cooldown. Only items failing every round are finally skipped.
- **Production (`app.py` watchlist routes — SHIPPED 2026-07-17):** all watchlist predict sites use `_ai_fast_fail_on_rate_limit=True` (bounded). Per-ticker deadline cut 320s→90s, bulk 200s→90s. A TF unresolved at the deadline returns `no_trade_reason="timeout"`, which the frontend **already** auto-refetches (`_fetchAndUpdateTfCell`) plus the 90s auto-retry banner — so cards render their ready TFs immediately (partial results) and pending TFs fill in the background. No frontend change was needed; `loadWatchlist` was already shell→per-ticker→per-TF progressive. Re-views hit `_WATCHLIST_PICK_CACHE` (per-(ticker,tf), TTL 15m INTRADAY / until-IST-midnight 1D/3D) and skip the LLM entirely.

The deeper capacity fix is the two extra providers (Gemini/SambaNova) above — with them keyed, cloud rarely fully exhausts, so predictions stay on fast concurrent cloud instead of funnelling to the single serialized Ollama.

**Ollama fallback** — `OLLAMA_ENDPOINT=https://v1deh-ollama.hf.space` and `OLLAMA_MODEL=qwen2.5:1.5b` are set in `.env` and **pushed to HF Spaces** (run `python export_env_secrets.py` to re-sync). **Model choice:** `qwen2.5:1.5b` is the only small model on the Space that reliably emits valid synthesis JSON (benchmarked 2026-07-17: 34.4s on a full-length synthesis prompt, all keys present). `llama3.2:1b` was faster but the synthesis quality was worse; `llama3.2:3b`/`gemma2:2b`/`phi3:mini` failed JSON validity. Ollama is tried at three points in `llm_client.py`: (1) Phase 1 when all cloud are `daily_exhausted`, (2) Phase 2 when not fast_fail, (3) **Last resort before raising RuntimeError, even when `fast_fail=True`** — this is the critical path that ensures top5 scan and watchlist both fall back to Ollama when cloud providers are rate-limited. Health check timeout: 20s (fast path) / 25s (last-resort path, allows HF Space cold start). Chat timeout: 70s. Backoffs: inference-failure 120s, warmup-failure (cold-start) 45s. `reset_ollama_state()` clears the transient backoff + health cache so a deferred-retry round gives Ollama a fresh chance. A **negative** health probe is cached only 10s (`_OLLAMA_HEALTH_NEG_TTL`) so a waking Space is re-probed quickly; a positive probe keeps the 60s TTL.

**AI forecast output fields** — synthesis call now returns `should_buy` (bool), `entry_price` (₹), and realistic TF-scaled ranges. Both fast-mode and debate parse paths extract these. The UI shows a BUY/SKIP chip and AI entry price when AI is available.

**Production vs tight_test ranges** — In production (`tight_test=False`), the AI's own range output is used directly. The `_BULL_RANGE`/`_BEAR_RANGE`/`_NEUT_RANGE` calibrated tables are ONLY applied when `tight_test=True` (backtest accuracy measurement mode). This ensures UI shows realistic AI-predicted targets, not hardcoded tiny ranges.

**ATR clamp + directional-sign enforcement (`ai_forecast._atr_clamp_range`)** — rewritten 2026-07-17. Production-only safety net (no-op when `tight_test=True`), keyed to the stock's own ATR%, but now **fully rebuilds** the BULLISH/BEARISH/NEUTRAL band from a day-scaled power-law formula instead of just clamping the LLM's own range — the model's own lo/hi are discarded entirely; only its DIRECTION and CONFIDENCE still come from the LLM. This is a deliberate, explicitly-requested accuracy/informativeness trade-off (see `research/PRODUCTION_DELTA.md` 2026-07-17 section and `memory/repo` notes for the full discussion):
- **NEUTRAL** (flat by policy, `_NEUT_RANGE`): a FLAT falsifiable band (±0.5% INTRADAY, ±1% 1D/3D), NOT ATR-scaled. A NEUTRAL call must give the user an actionable "stays within X%" claim — an ATR-scaled NEUTRAL band ballooned to ±5%+ on volatile stocks, which is unbettable ("no idea what to bet on"). Kept consistent with `database._SNAP_NEUT`, `research.range_model._NEUT_FLAT`, and `ml_predictor._neutral_range` so NEUTRAL is identical across every module. (Previously ATR-scaled via a now-removed `_neutral_half_width_pct` helper — reverted 2026-07-29.)
- **BULLISH/BEARISH**: `near` bound (`_easy_near_bound_pct`) = `BASE × window_days^EXP × ATR%`, clamped to a floor/ceiling derived from the same formula; `far` bound (`_far_bound_pct`) is its own day-scaled formula (not a flat ratio of near — an earlier flat-ratio version measurably hurt INTRADAY/3D). `window_days` matches `predictor_core.TIMEFRAME_DAYS` (1D=1, 3D=3, 5D=5); INTRADAY uses its own fitted "equivalent day count" per formula since it has no calendar-day length.
- Old constants removed as dead code: `_ATR_MID_CEILING`, `_ATR_MAX_WIDTH`, `_ATR_TARGET_MULT`, `_NEUT_ATR_HALF_WIDTH` (flat per-TF dicts) — all superseded by the formulas above.

Validated via `research/validate_on_trades.py`: `graded_hit_for_tf` 66.7%→96.3%, `target_hit_for_tf` (strict midpoint) 63.0%→83.3%, direction-hit 92.6% (6 tickers × 3 dates × 3 TFs, 54 rows).

**`backtest_stats` field** — computed in `predictor_core._calc_expected_return()` and added to the prediction dict, but intentionally NOT forwarded to watchlist or top5 API responses. Internal use only.

### Return range calibration

**Range generation** — `_generate_range_from_point()` expands point estimates into proper price ranges (this fix took the backtest from ~46% to 76%+; further prompt calibration pushed 3D/5D to 90%+; see [LLM Prompt Accuracy Backtest](#llm-prompt-accuracy-backtest)). If the LLM returns a range, it is used as-is; if it returns a point, the range is expanded symmetrically by confidence (HIGH ±0.8%, MEDIUM ±1.5%, LOW ±2.5%), then per-TF caps and minimum spread are applied.

**Timeframe-aware caps** — enforced in both prompt text and post-processing:
| Timeframe | Hard cap | Typical range | Min spread |
|---|---|---|---|
| INTRADAY | ±2% | ±0.5–1.5% | 0.1% |
| 1D | ±4% | ±1–3% | 0.5% |
| 3D | ±7% | ±2–5% | 1.0% |
| 5D | ±12% | ±3–8% | 1.5% |

**INTRADAY (same-day) timeframe** — predicts today's move from the current live price (entry = live price at prediction time, made anytime during the session). A hit counts only if the target is touched by **15:00 IST the same day** (no next-day rollover). `timeframe_to_dates("INTRADAY")` returns `start == end == today` (n=0); `predict_stock_v2` detects INTRADAY via `start_date == end_date`. Live validation (`app.py._fetch_intraday_window_capped`) uses 15m intraday bars (`intraday_live.py`) filtered to bars starting before 15:00 IST, gated by `_intraday_cutoff_passed` so it only runs after 3pm. The historical backtest approximates the same-day swing with the entry day's daily OHLC high/low (`_fwd_intraday_moves` `up0/dn0`; no 3pm cap — documented limitation, since yfinance only serves 15m bars for ~60 days). Strategy map reuses the fastest signals: `S1, S4, S4V2, S8, S16, S_CTRIO`. ATR stop = 0.4×ATR14 (tightest). Watchlist now predicts 2 horizons (Today/1D).

**Range semantics** — `predicted_return_lo` is always the worst-case bound, `predicted_return_hi` is the best-case:
- BEARISH: `lo < hi < 0` (e.g. lo=-6.5, hi=-3.0)
- BULLISH: `0 < lo < hi` (e.g. lo=1.5, hi=4.5)

**News alignment threshold** — `_enforce_news_alignment` triggers when `abs(news_score) ≥ 8`. A conflicting news signal (score 8–19) downgrades AI confidence by one level; score ≥ 20 neutralizes direction entirely.

**Timeframe calibration block** — `_build_synthesis_prompt` includes a `TIMEFRAME CALIBRATION` section: for 1D, RSI and short-term momentum dominate over EMA200; for 5D, EMA200 trend is primary.

---

## ml_predictor — Standalone Supervised ML Price Model

A self-contained quantile-regression predictor, **independent of the LLM debate pipeline** (built as a standalone A/B-able predictor). Predicts, per timeframe (INTRADAY / 1D / 3D), for any NSE ticker: a **price estimate**, a **buy-price suggestion**, a **stop-loss**, and a **trend** (BULLISH / BEARISH / NEUTRAL — handles down moves, not just up). No new dependencies: uses `scikit-learn` (`HistGradientBoosting`) + `joblib`, both already in `requirements.txt` — HF-Spaces-safe (lightgbm/xgboost/torch deliberately avoided).

**Model set (21 artifacts = 7 per TF):** per timeframe, 6 `HistGradientBoostingRegressor(loss="quantile")` — up-excursion q10/q50/q90 and down-excursion q10/q50/q90 — plus one isotonic-calibrated `HistGradientBoostingClassifier(class_weight="balanced")` for direction. Excursion labels are the forward best-up / worst-down moves from `research/backtest.py::_fwd_intraday_moves` (INTRADAY = entry day's own daily High/Low vs close, the documented same-session proxy). **Direction labels are EXCESS-of-Nifty (alpha), production default** — BULLISH means "expected to *outperform the market*", not merely "go up" (set `ML_EXCESS_LABELS=0` to revert to raw returns). This roughly 10× the 1D and 2× the 3D per-trade expectancy under target-exit trading (see results below).

**Features (37, all point-in-time, lookahead-safe):** built by `ml_predictor/features.py::compute_features`, which reuses the exact production math — the raw technicals (RSI 14/5/2, EMA20/50/200 distances, MACD hist, ADX, Bollinger position + band-distances, returns 10/20/90d, ATR%, consec-days, 52W-high dist) **and** the 11-weight ML sub-features from `predictor_core.get_ml_feature_score` (RS-vs-Nifty 3M, OBV z-score, EMA-stack, Supertrend, shadow) + the 10 `_compute_trigger_flags` + macro regime (VIX, nifty_ok, vix_decl). **News is excluded** (live-only, cannot be backfilled) — it is applied only as a live inference-time confidence adjustment in `infer.py`.

**Derivations (`infer._derive`, the single source of truth, shared by live inference and the backtest):**
- **Range = a prediction interval** `[q10, q90]` (not a coin-flip median band) so the reported range is honestly hit most of the time. BULLISH → `[up_q10, up_q90]`; BEARISH → `[dn_q10, dn_q90]` (deep…shallow, lo < hi < 0); NEUTRAL → flat band from `research/range_model.calibrated_range`.
- **Expected target / headline price** = the median quantile (`up_q50` / `dn_q50`). **Estimated high** = `up_q90`.
- **Buy-price suggestion** = the modeled median dip `price*(1+dn_q50/100)` (buy on the pullback).
- **Stop-loss** = below the modeled worst-down `dn_q10`, floored by the existing ATR stop (`atr_mult = {INTRADAY:0.4, 1D:0.7, 3D:1.1}`).
- **Confidence** = the **isotonic-calibrated** max-class probability of the direction classifier (`CalibratedClassifierCV`), bucketed HIGH/MEDIUM/LOW by the per-TF tertile thresholds (`conf_hi`/`conf_mid`) stored in the manifest. This replaced the old band-width heuristic, which *anti*-correlated with returns; now confidence is monotonic in direction reliability (HIGH→68% correct > MEDIUM→51% > LOW→42%). `confidence_prob` is exposed in the output.
- **INTRADAY "already gone"** = live/today-high ≥ session-anchored estimated high (anchored to the **previous close**, not the live price, so the ceiling doesn't float up with price) → `already_gone` bool + `headroom_pct`.
- Quantile-crossing guard (monotonic clamp) applied at inference.

**Workflow (offline → deploy):**
```bash
python ml_predictor/dataset.py --step 5   # build training_data.csv (excess-of-Nifty dir labels by default)
python ml_predictor/train.py              # fit 21 estimators (dir clf isotonic-calibrated) + manifest.json
python research/ml_backtest.py            # accuracy + target-exit P&L on the out-of-sample window
python research/ml_selection_backtest.py --top 5 --min-conf HIGH   # top-N stock selection edge
python research/ml_watchlist_eval.py      # grade last week's watchlist predictions vs realized
python research/ml_intraday_backtest.py   # TRUE intraday (15-min) validation
python ml_predictor/infer.py RELIANCE.NS  # smoke-test a full prediction
```
- **Split:** time-based holdout (train ≤ `max_date − 5mo`, 5-day embargo), so `research/ml_backtest.py` evaluates only genuinely out-of-sample rows.
- **Retrain cadence:** inference always recomputes features from the freshest bars, so predictions incorporate new data between retrains; a scheduled offline retrain refreshes the weights.
- **Persistence:** `ml_predictor/models/` (joblib) is **git-committed** (guaranteed present in the HF image; `training_data.csv` and `ohlcv_cache.db` are gitignored/regenerable). If `$HF_ML_MODEL_REPO_ID` is set, `infer.py` prefers newer artifacts pulled from that HF Hub dataset repo. Missing artifacts degrade gracefully (`source="ml_unavailable"`, HTTP 503) — never crash.

**Training universe:** built from the full NSE equity master list (`.nse_equity_cache.json`, ~2,100 tickers) at **5-year** history — **1,939 tickers, ~350k rows, 2022-05 → 2026-07**, spanning bull *and* bear regimes and including small/mid-caps (not just the top-500 large-caps). This broad + long-history training is what lifted the numbers below and made the model turn appropriately BEARISH/NEUTRAL on falling small-caps instead of blindly bullish.

**Backtest results (excess-label production model, out-of-sample 38k rows, cutoff 2026-02-10):** graded hit INTRADAY 90% / 1D 89% / 3D 89%; direction accuracy INTRADAY 71% / 1D 45% / 3D 41%; calibrated confidence monotonic — HIGH graded 91% & 68% direction-correct > MEDIUM 51% > LOW 42%. **P&L with TARGET-EXIT trading** (net 0.30%/trade, `research/ml_backtest.py`): 1D expectancy **+0.86% (PF 1.74, 58% win)**, 3D **+1.29% (PF 1.79, 58% win)**. IMPORTANT — this assumes you exit at the model's target; the excess model's picks tend to spike then fade, so *buy-and-hold-to-close* underperforms (the raw-label model was the reverse). **Trade 1D/3D with the target/stop, not buy-and-hold.**

**Rejected experiments (all A/B-tested via env-overridable train, kept OFF):** (1) *bigger model* (`ML_MAX_ITER/ML_MAX_LEAVES`, 700 trees/depth 63) — identical accuracy & P&L; the model is at the data's signal ceiling. (2) *S1–S20 strategy signals as features* (`ML_STRATEGY_FEATURES=1`) — identical to baseline; redundant with existing indicators. (3) *strategy/quality selection gates* (`ml_selection_backtest.py --filters trend,momentum,adx,trigger,lowvol,notob`) — every gate *reduced* the market-relative edge (re-filtering on indicators the model already uses strips its edge); the `trend` gate raises win-rate ~55–60% at the cost of edge, offered as opt-in only.

**INTRADAY range accuracy is calibrated to the realized 15-min excursion (validated on real 15-min data, `research/ml_intraday_backtest.py`, 30 tickers × 57 days × ~4.9k predictions):** predicting at 09:15/12:00/14:00 and checking touch-by-15:00 — **graded (range) hit ≈88%, expected-target hit ≈48-58%, far-bound coverage ≈90-94%**, DirHit 86/92/91%. The fix (`ml_predictor/infer.py`): the model's INTRADAY labels are a *full-day* excursion (entry day's High/Low vs close), and at mid-session deployment (features as-of previous close) the raw quantiles are miscalibrated *by role, not by a single factor* — the q90 is about right once √time-scaled, but the q50 **overshoots** the realized median and the q10 is too ambitious. So the three levels are calibrated **independently** to what the range actually achieves, each on top of √time session scaling: `_INTRADAY_FAR_MULT≈1.0` (far edge = true q90 ceiling, ~90% not exceeded — the old uniform shrink left this a q65 that got exceeded 35% of the time), `_INTRADAY_MED_MULT≈0.42` (the **expected/headline target** = realized median, touched ~50% — the honest "did we hit the estimate" number, vs the model's inflated full-day median that only landed ~20%), and `_INTRADAY_NEAR_MULT≈0.12` (reachable near edge, so RANGE_HIT ≥85%). All env-overridable (`ML_INTRADAY_FAR_MULT`/`MED_MULT`/`NEAR_MULT`). The backtest reports `ExpHit` (expected-target touched) and `FarCov` (ceiling not exceeded) — these are the meaningful metrics; the old mechanical "MidHit" (touch the band's arithmetic midpoint) is misleading for a right-skewed [q10,q90] interval. **Why not push expected-target hit to 85%?** It's monotonic in the target level, so you *can* — set `ML_INTRADAY_MED_MULT=0.08` → ExpHit ≈85%. But that shrinks the target to ~0.15%, *below* the 0.30% round-trip cost, so BuyWin% collapses 42%→5% (P&L −0.64%): 85% expected-target accuracy and profitability are mutually exclusive, so the default stays at the honest median (0.42). The backtest report columns are also printed in plain English with a legend (`RightDir%`=direction correct, `ReachFloor%`=safe low target hit, `ReachMain%`=main target hit, `UnderCeil%`=stayed below best-case top, `Win%`=trades that profited). `_fetch_15m` caches 15-min bars per ticker/day under `research/cache/intraday_15m/` (pickle; `--refresh` to force re-download) — note this is for correctness/rate-limit safety, **not** speed: the backtest is CPU-bound on inference, not the download (daily bars already cache in `ohlcv_cache.db`). **Caveat — still not profitable to trade long:** BUY P&L stays negative (~−0.47%, 42% win) net of 0.30% cost; the *range and central estimate* are now accurate but the target isn't reliably hit before the stop, so INTRADAY is a reliable **direction/range signal, not a standalone long strategy** — trade 1D/3D with the target/stop for P&L. Metrics live in `research/ml_intraday_backtest.py` (true 15-min), `research/ml_backtest.py` (daily-proxy accuracy + P&L), `research/ml_selection_backtest.py`, and `research/ml_watchlist_eval.py`.

**API:** `GET /api/ml-predict/<ticker>` (`?news=<int>` optional news score, `?live=0` to skip the live-price fetch) → `{ticker, available, current_price, as_of, model_cutoff, tfs:{INTRADAY,1D,3D:{direction, confidence, predicted_return_lo/hi, target_price_lo/hi, expected_target_price, estimated_high, buy_price_suggestion, stop_loss, quantiles, direction_proba, intraday:{already_gone, headroom_pct, …}}}}`. Standalone: `from ml_predictor.infer import get_ml_predictor`.

**Stable signatures:** `compute_features(...)`, `MLPredictor.predict_all_tf(ticker, live_price=None, today_high=None, news_score=0)`, `MLPredictor.predict(ticker, tf, ...)`.

---

## Modules

### universe.py — Dynamic NSE Universe

Replaces the old static `nse_universe.py`. The universe is now the **WHOLE NSE market**, not just the top 500 by market cap. Source chain (`_fetch_universe`): **NSE full equity list `EQUITY_L.csv`** (`nsearchives.nseindia.com/content/equities/EQUITY_L.csv`, ~2,062 EQ-series stocks, all cap tiers incl. mid/small caps) → NSE Nifty-500 CSV → Yahoo screener → static fallback (`nse_fallback_universe.py`, top-200). NSE archive CSVs work from datacenter IPs, so this is reliable on HF Spaces where Yahoo's `yf.screen()` is blocked (returns 0). EQUITY_L headers carry leading spaces (`' SERIES'`) — keys are stripped.

- `get_universe(force_refresh=False)` → `{TICKER.NS: company_name}` (full market)
- `refresh_universe()` — force re-fetch
- **Cache:** `.universe_cache.json` (24h fresh TTL, 7-day stale grace), written to `/data` on HF Spaces (persistent across restarts) via `_cache_dir()`, project root locally.
- **Integration:** `predictor_core.py` imports `get_universe`. Flask: `GET /api/universe`, `POST /api/universe/refresh`.

---

### top5_picker.py — Top Picks

Finds the top NSE stocks to invest in, with predictions across INTRADAY/1D run concurrently (`ThreadPoolExecutor`). Draws from the **whole NSE market (~2,062 stocks)** so mid/small-caps are included, but caps each scan at 700 (cache-first, rotating cold tail) for fast first results. Up to 20 qualifying picks returned.

**Scoring**: `(ml_prob + sig_count × 0.05) × sector_lead × vol_factor` where `vol_factor = 1.0 + min(ATR14/price × 100 / 4.0, 0.5)` — highly volatile stocks get up to +50% boost. Phase 2 uses AI confidence and R:R to re-rank candidates.

- `get_top5_picks(top_n=20, _universe_size=700)` — daily picks (INTRADAY/1D). Draws from the whole NSE market (~2,062) but caps the scan at 700 for fast first results. `_order_and_cap_scan` orders **cache-first** (already-warmed stocks — watchlist mid/small-caps + prior scans — scan instantly) and **rotates the cold tail** across runs (`_SCAN_COLD_OFFSET`), so the whole market is swept over ~3 runs and the OHLCV cache fully warms. **Phase 1 is signals-only (no LLM)** — cost is time, not API quota; Phase 1 workers=`min(16,n)`, deadline=`min(600, max(120, n×0.2))s`, partial results OK.
- `get_weekly_picks(top_n=20, _universe_size=150)` — weekly picks (3D/5D/1W). Stays bounded at 150 because its Phase-1 scan runs an LLM call per ticker (can't scale to the full market).
- **Cache:** `_TOP5_CACHE_TTL = 86400` (24h). Cache stores results of a fresh computation using live OHLCV data at compute time. Refresh button (`/api/top5?refresh=1`) forces a new computation.
- **`_RANK_TFS`** = `["INTRADAY", "1D"]` — 3D + 5D removed from the live view/API (2026-07-28). An actionable INTRADAY setup whose best-case clears the 1% floor is prioritized ABOVE 1D-only picks (`_pick_best_tf` intraday-first tier).
- **AI unavailable during scan**: Phase 1 uses `_ai_fast_fail_on_rate_limit=True` (fail fast, don't block). Stocks that get AI unavailable are deprioritized (×0.40 score) but not excluded.
- **Progressive streaming (SHIPPED 2026-07-21):** `get_top5_picks(..., progress_cb=...)` emits live progress snapshots — Phase 1 publishes a `scanning` counter (every 25 stocks); Phase 2 (restructured from `_cf.wait` to `as_completed`) publishes `predicting` snapshots every 6 completed jobs / 4s carrying the **partial ranked picks assembled so far** (via the shared `_assemble(partial=)` helper). A TF whose AI job hasn't finished is marked `no_trade_reason="pending"` (frontend renders a per-cell spinner); the final result marks any still-missing TF `ai_unavailable`. `app.py` stores the latest snapshot in `_TOP5_PROGRESS` (guarded by `_TOP5_PROGRESS_LOCK`), cleared at compute start/finish. `/api/top5` serves the snapshot (with live prices) while computing — so ready cards render immediately instead of waiting for the whole scan. Frontend `loadTop5Cards` renders partial picks + a `.top5-stream-banner`, polls fast (4s with picks / 6s while scanning), and caps at ~12 min elapsed. HF-visible logs: `[TOP5] PHASE 1/2 progress …` via `print()` + `logger.info`, plus `app.logger` start/done lifecycle lines.
- **Note on Phase 1 cost:** OHLCV *is* cached in a persistent SQLite DB (`ohlcv_cache.db` on HF `/data`), but the cache is only "fresh" for the current trading day (`_is_data_fresh` = last bar ≥ last trading day). On the first scan of a new trading day every stock is stale and must re-fetch today's bar from yfinance — that re-fetch is the slow part, unavoidable at least once/day/stock. Cache-first ordering + cold-tail rotation spreads it across runs.
- **Integration:** `app.py` `GET /api/top5`. Dashboard shows all qualifying picks (up to 20). Standalone: `from top5_picker import get_top5_picks`.

---

### model_picker.py — GitHub Models Selector (standalone utility)

Tests available models against the `GITHUB_TOKEN`, fetches the model list dynamically from the GitHub Models API, and selects the best available model by tier / rate-limit / availability.

- `fetch_available_models(token)`, `test_all_models()`, `get_best_model()`, `get_model_for_backtest()`
- **Status:** standalone helper — **not currently imported** by `ai_forecast.py` or the backtest (which hardcode `gpt-4o-mini`). Use it to diagnose token/model availability.

---

### fred_data.py — US Macro Indicators

Fetches US/global macro indicators that drive EM India equity risk regimes.

**Indicators:** `T10Y2Y` (10Y-2Y yield spread, inversion = risk-off), `FEDFUNDS` (Fed Funds Rate), `CPIAUCSL` (US CPI YoY %), `DTWEXBGS` (broad USD index).

**Output keys:** `yield_curve_spread_bps`, `yield_curve_inverted`, `fed_rate`, `cpi_yoy`, `usd_strength`, `macro_risk_score` (0–100), `risk_regime` (`RISK_ON`|`CAUTIOUS`|`RISK_OFF`), `source`, `cached_at`.

**Cache:** `fred_macro_cache.json`, 24h TTL.
**Env var:** `FRED_API_KEY` (optional). Falls back to yfinance (`^TNX`, `^IRX`, `DX-Y.NYB`) if not set.
**Integration:** `macro_context.py` imports `get_fred_gate()` and adds `fred_risk_on` to the `global_risk_on` composite gate. Standalone: `python fred_data.py`.

---

### fundamentals.py — Stock Fundamentals Scorer

Scores whether the business is fundamentally worth trading, from `yf.Ticker(ticker).info`, `.quarterly_financials`, `.balance_sheet`, `.cashflow`.

**Scoring (0–100):** PE vs sector median (25) + Debt/Equity (20) + Revenue growth YoY (20) + Free Cash Flow (15) + ROE (20). Sector PE benchmarks hardcoded (2024–2025 NSE values for 20 sectors).

**Output keys:** `fundamental_score`, `pe_relative` (CHEAP|FAIR|EXPENSIVE|UNKNOWN), `debt_level`, `revenue_trend`, `fcf_positive`, `roe_pct`, `promoter_holding_pct`, `sector`, `summary`.

**Cache:** `fundamentals_cache.json`, 24h TTL per ticker.
**Integration:** `predictor_core.py` fetches concurrently → `get_ai_forecast(fundamentals=...)`. `ai_forecast.py` builds the 4th advocate prompt via `build_fundamentals_block()`. Flask: `GET /api/fundamentals/<ticker>?refresh=1`. Standalone: `python fundamentals.py RELIANCE.NS`.
**Stable signature:** `get_fundamentals(ticker)`.

---

### sector_pulse.py — NSE Sector Heatmap

Tracks 10 NSE sector indices for rotation detection: BANK (^NSEBANK), IT (^CNXIT), PHARMA (^CNXPHARMA), FMCG (^CNXFMCG), AUTO (^CNXAUTO), METAL (^CNXMETAL), REALTY (^CNXREALTY), ENERGY (^CNXENERGY), FINANCE (^CNXFINANCE), INFRA (^CNXINFRA).

**Rotation classification:** `DEFENSIVE` (FMCG+PHARMA leading), `CYCLICAL` (METAL+ENERGY+AUTO), `GROWTH` (IT+BANK+FINANCE), `MIXED`.

**Output keys:** `sectors` (list of {name, change_1d/5d/1m_pct, momentum}), `rotation_signal`, `leading_sectors` (top-3 by 5D), `lagging_sectors` (bottom-3 by 5D), `breadth_score` (0–10).

**Cache:** 5-min in-memory TTL.
**Integration:** `predictor_core.py` fetches concurrently; adds `sector.leading`/`sector.lagging` flags. Flask: `GET /api/sector-pulse?refresh=1`. Helper `get_sector_for_ticker(ticker)` maps ~50 tickers. Standalone: `python sector_pulse.py`.
**Stable signature:** `get_sector_pulse()`.

---

### risk_engine.py — Portfolio Risk Metrics

Computes risk analytics from paper-trading history in `database.py`.

**Metrics:** Sharpe (annualized, 6.5% India risk-free), max drawdown %, beta vs Nifty50, annualized volatility, profit factor, Kelly fraction, suggested position % (half-Kelly, capped 10%/trade), plus trade count / win rate / avg win / avg loss.

Requires ≥5 closed trades; returns a `note` field when data is insufficient.
**Integration:** `GET /api/portfolio` includes a `risk_metrics` key. Standalone: `python risk_engine.py`.

---

### social_sentiment.py — Social Sentiment

- **Reddit** — RSS search, no API key. Company-name overrides (e.g. `HDFCBANK` → "HDFC Bank") so queries match how people post.
- **StockTwits** — public API; returns empty for most NSE stocks (limited US coverage) — graceful fallback.
- Injected into bull and bear advocate prompts as a `SOCIAL SENTIMENT:` block.

---

## Paper-trading book & live prices (app.py + database.py)

The Flask app runs a full paper-trading book on top of SQLite (`paper_trading.db`).

**Live-price enrichment** (implemented; supersedes the old `LIVE_PRICE_FIX_PLAN.md`):
- `data_sources.fetch_live_price(ticker, allow_delayed=True)` — multi-source live price (NSE official → fallbacks → Yahoo 15-min delayed). `allow_delayed=False` forces a real-time-only source.
- `database.get_open_trades_with_live_prices()` — fetches open trades and enriches each with a live `current_price` (parallelized via `ThreadPoolExecutor`). Tries real-time first, then delayed.
- `GET /api/open-trades` wraps it for the portfolio view.

**Trade lifecycle:** open trades, trade history, manual trade entry, pending limit orders, order-fill checks, stop-loss checks, cancel, and close — see endpoint table below.

---

## Prediction validation & audit trail (database.py + app.py)

Every watchlist/top5 prediction can be snapshotted, then automatically checked once its timeframe expires.

- `save_prediction_snapshot(...)` — stores direction/confidence/target range/current price and computes a `validation_target_date` (1D=+1, 3D=+3, 5D=+5 IST days), status `PENDING`. Returns snapshot ID, or `None` if intentionally skipped. **INTRADAY predictions made at/after the 15:00 IST grading cutoff are NOT saved** (returns `None`) — there's no honest same-day window left, and the old behavior (rolling `validation_target_date` to the next trading day) silently scored a narrow same-day-calibrated target against an entirely different day's session (fixed 2026-08-05, see WHEELS.NS/SHAILY.NS/DIACABS.NS 2026-07-30 incident). This cutoff matches `app.py::_intraday_cutoff_passed`.
- `get_prediction_snapshots(ticker=None, days=30, limit=100)` — audit history.
- `get_prediction_misses(days=30, min_confidence="MEDIUM")` — predictions that missed their range.
- `get_validation_pending(...)`, `get_validation_summary(days=30)`, `get_validation_history(...)` — validation queue + rollup stats.
- `save_postmortem(trade_id, notes)` / `get_postmortems()` — AI post-mortems for losing trades.

A prediction's "hit" = actual NSE price stayed within `[target_price_lo, target_price_hi]` at timeframe expiry — the same metric the backtest optimizes.

**Self-learning context is timeframe-scoped (fixed 2026-08-05):** `self_learning.get_learning_context(tf_label=...)` filters `calibration_notes` to the requested timeframe (plus TF-agnostic notes like confidence calibration) before injection into `ai_forecast._build_synthesis_prompt`. Previously the full unfiltered note list (mixing INTRADAY/1D/3D/5D lessons together) was injected into every synthesis call regardless of which timeframe was being predicted, risking a 3D calibration lesson bleeding into an INTRADAY call.

**Stale PENDING give-up safeguard (fixed 2026-08-05):** a PENDING snapshot whose OHLCV/live-price fetch keeps failing (delisted/illiquid ticker, data-source outage) previously stayed PENDING forever — every validation run (scheduler + manual `/api/validation/execute` + the auto-run triggered by opening the Validation tab) retried it and skipped it again, so it sat in the UI showing an ever-more-overdue `Validation Due` date with no way to clear. Fixed: once a PENDING row's `validation_target_date` is more than `_STALE_PENDING_GIVEUP_DAYS` (default 3) days in the past AND the fetch still returns no price, `database.mark_prediction_expired(snapshot_id)` sets `validation_status='EXPIRED'` (a status the schema already allowed but nothing previously set), removing it from `get_validation_pending()`/the Pending tab without recording a false HIT/MISS. Applied in both `app.py::validation_execute()` and the inline duplicate in `_start_validation_scheduler()`. `prune_validated_snapshots()` now also purges old EXPIRED rows, not just VALIDATED ones. **Important distinction:** this does NOT retroactively fix pre-existing backlog dates — it only stops rows that are provably unfetchable from accumulating forever; a row that's simply awaiting its normal validation window (or a scheduler run) still shows its real target date until it's actually validated.

---

## Strategy signals reference

Best verified signals (NSE backtest 2019–2024, 276–378 stocks):

| Signal | Win Rate | Notes |
|---|---|---|
| S_CTRIO | 71.0% | Triple RSI (<5/<30/<35) + SMA200 + ADX>20 + VIX<18. Best signal. |
| S4V2 | 70.0% | RSI(2)<3 + SMA200 + VIX<15 + ADX>20 |
| S_SEASONAL | 70.8% | Santa Claus / Post-Budget / Diwali seasonal windows |
| S6V2 | 69–76.5% | MomDip v2. 76.5% in Mode B (VIX<18 + declining), 1M horizon |
| S6 | 65–70.9% | MomDip v1. 70.9% in Mode B 3D |
| S16 | 62.3% | StochRSI oversold recovery |
| S8 | 59–63% | RSI triple confluence — HIGH confidence at 3D (N=282) |

Mode B = VIX<18 + VIX 5D EMA declining. Mode C = Mode B + all macro favorable.

**Important:** All win rates are NSE-verified on Indian stocks. US-reported win rates (e.g. S5's 80%, S4's 77%) do NOT apply to NSE individual stocks and have been corrected.

---

## Key files not to break

- `predictor_core.py` — public API used by MCP and Flask app. `predict_stock_v2` and `rank_stocks_v2` signatures must remain stable.
- `stock_predictor_mcp.py` — MCP server entry point. Imports from `predictor_core`.
- `data_sources.py` — multi-source OHLCV + live price with fallback chains. Do not change `fetch_ohlcv` / `fetch_live_price` signatures.
- `trial_run.py` — all signal generators. Strategy stats in `predictor_core._STRATEGY_STATS_DEFAULT` are NSE-verified; do not change without re-running backtest.
- `universe.py` — `get_universe()` signature must stay stable (used by `predictor_core` + `top5_picker`).
- `fundamentals.py` — `get_fundamentals(ticker)` must stay stable (used by `predictor_core` + `ai_forecast`).
- `sector_pulse.py` — `get_sector_pulse()` must stay stable.
- `fred_data.py` — `get_fred_macro()` and `get_fred_gate()` must stay stable (used by `macro_context`).

---

## Environment variables

```
GITHUB_TOKEN        Unused (GitHub Models removed from provider chain). Keep empty.
ANTHROPIC_API_KEY   Unused (currently empty — not in active use)
OPENROUTER_API_KEY  1st fallback provider key (OpenRouter free tier)
OPENROUTER_BEST_FREE_MODEL  Primary free model — verified working 2026-07-09: openai/gpt-oss-120b:free
OPENROUTER_FREE_MODELS      Comma-separated fallback chain (best→fastest):
                    openai/gpt-oss-120b:free,nvidia/nemotron-3-ultra-550b-a55b:free,
                    nvidia/nemotron-3-super-120b-a12b:free,meta-llama/llama-3.3-70b-instruct:free,
                    google/gemma-4-31b-it:free,google/gemma-4-26b-a4b-it:free,
                    openai/gpt-oss-20b:free,
                    qwen/qwen3-next-80b-a3b-instruct:free,qwen/qwen3-coder:free
                    Note: meta-llama/llama-3.1-8b-instruct:free and llama-3.1-70b-instruct:free are NO LONGER free on OpenRouter.
                    Note: tencent/hy3:free removed 2026-07-13 (expired 2026-07-21).
GROQ_API_KEY        2nd fallback (Groq free inference). Primary: llama-3.3-70b-versatile (6k TPM/min)
GROQ_FREE_MODELS    Groq model fallback chain (after primary 429s): llama-3.1-8b-instant
CEREBRAS_API_KEY    3rd fallback — fastest free LLM inference available. Free signup: cloud.cerebras.ai
CEREBRAS_MODEL      Primary Cerebras model (default: llama-3.3-70b)
CEREBRAS_FALLBACK_MODELS  Cerebras fallback (default: llama-3.1-8b — fastest)
HF_TOKEN            4th fallback. Used for HuggingFace Router (router.huggingface.co/novita).
                    Also used by export_env_secrets.py to push secrets to HF Spaces.
HF_INFERENCE_MODEL  Primary HF model for inference (novita format, lowercase):
                    meta-llama/llama-3.1-8b-instruct
HF_INFERENCE_FALLBACK_MODELS  Comma-separated HF fallbacks: meta-llama/llama-3.3-70b-instruct
GEMINI_API_KEY      5th fallback. Google AI Studio (Gemini) — free ~1,500 req/day on Flash.
                    Get one at https://aistudio.google.com/apikey. No-op if unset.
GEMINI_MODEL        Default gemini-flash-latest. NOTE: the older gemini-2.5-flash / -lite names
                    now return HTTP 404 "no longer available to new users" on the OpenAI-compat
                    chat endpoint — use the alias names (gemini-flash-latest / -lite-latest).
GEMINI_FALLBACK_MODELS  Comma-separated fallbacks tried when the primary 503s/429s
                    (default: gemini-flash-lite-latest,gemini-2.0-flash).
SAMBANOVA_API_KEY   6th fallback. SambaNova Cloud — persistent free 70B/405B. Sign up at
                    https://cloud.sambanova.ai. No-op if unset.
SAMBANOVA_MODEL     Default Meta-Llama-3.3-70B-Instruct.
SAMBANOVA_FALLBACK_MODELS  Comma-separated fallbacks (default: Meta-Llama-3.1-8B-Instruct).
NVIDIA_API_KEY      7th fallback. NVIDIA NIM (build.nvidia.com) — free API key, OpenAI-compatible,
                    large independent free-tier capacity (Llama-3.3-70B / Nemotron / DeepSeek /
                    Qwen). Zero cost. Get one at https://build.nvidia.com. No-op if unset.
NVIDIA_MODEL        Default nvidia/llama-3.3-nemotron-super-49b-v1 (the meta/llama-3.3-70b-instruct
                    slug read-times-out >30s on the free tier — dropped 2026-07-24).
NVIDIA_FALLBACK_MODELS  Comma-separated fallbacks (default: meta/llama-3.1-8b-instruct).
FRED_API_KEY        Optional. Free FRED API key for US macro indicators (fred_data.py).
                    Falls back to yfinance proxies if not set.
                    Get one at: https://fred.stlouisfed.org/docs/api/api_key.html
ALPHA_VANTAGE_API_KEY  Optional. Additional fallback in the data_sources.py fetch chains.
BACKTEST_LLM_PACE_SECS  Seconds between LLM calls in backtest (default: 12). Set higher if hitting
                         Groq TPM limits. 12s = 5 calls/min × ~1,000 tokens = 5,000 TPM (under 6k limit).
```

---

## Flask API endpoints

**Predictions & universe**
| Endpoint | Method | Description |
|---|---|---|
| `/api/predict` | POST | Predict 1–20 stocks |
| `/api/rank` | POST | Rank universe stocks |
| `/api/top5` | GET | Top picks (up to 20, INTRADAY/1D, ATR-ranked) |
| `/api/watchlist-picks` | GET | Predict all watchlist stocks (all TFs) |
| `/api/watchlist-pick/<ticker>` | GET | Predict single watchlist stock |
| `/api/universe` | GET | Current dynamic NSE universe |
| `/api/universe/refresh` | POST | Force universe re-fetch |
| `/api/search` | GET | Ticker/company search |
| `/api/chart/<ticker>` | GET | OHLCV chart data |
| `/api/live-price/<ticker>` | GET | Live (or delayed) price |
| `/api/ml-predict/<ticker>` | GET | Standalone ML price model — INTRADAY/1D quantile forecast (`ml_predictor`; model computes 3D internally but the API strips it) |

**Context & analytics**
| Endpoint | Method | Description |
|---|---|---|
| `/api/sector-pulse` | GET | NSE sector heatmap (rotation, leading/lagging) |
| `/api/fundamentals/<ticker>` | GET | Fundamentals score for one ticker |
| `/api/portfolio` | GET | P&L summary + `risk_metrics` |
| `/api/portfolio-insight/<ticker>` | GET | Per-position insight |
| `/api/signal-accuracy` | GET | Per-signal win rates from paper trades |

**Paper-trading book**
| Endpoint | Method | Description |
|---|---|---|
| `/api/open-trades` | GET | Open trades enriched with live prices |
| `/api/trades/open` | GET | Open trades (raw) |
| `/api/trades/history` | GET | Closed-trade history |
| `/api/trades` | POST | Open a paper trade |
| `/api/trades/<id>/close` | POST | Close a trade |
| `/api/trades/<id>/price` | GET | Current price for a trade |
| `/api/trades/check-stops` | POST | Check & trigger stop-losses |
| `/api/orders/pending` | GET | Pending limit orders |
| `/api/orders/check` | POST | Check & fill pending orders |
| `/api/orders/<id>/cancel` | POST | Cancel a pending order |
| `/api/watchlist` | GET/POST | List / add watchlist |
| `/api/watchlist/<ticker>` | DELETE | Remove from watchlist |

**Validation & post-mortems**
| Endpoint | Method | Description |
|---|---|---|
| `/api/prediction-snapshots` | GET | Snapshot audit trail |
| `/api/prediction-validation` | GET | Validate snapshots whose TF has expired |
| `/api/prediction-misses` | GET | Predictions that missed their range |
| `/api/validation/pending` | GET | Validation queue (due items) |
| `/api/validation/execute` | POST | Run pending validations |
| `/api/validation/summary` | GET | Validation rollup stats |
| `/api/postmortems` | GET | AI post-mortems for losing trades |
| `/api/postmortem` | POST | Generate a post-mortem |

---

## LLM Prompt Accuracy Backtest

### Current status — last run 2026-06-29 (rerun pending with realistic ranges)

**Verified on actual paper trade dates (N=48, 3 entry dates × 6 tickers × 3 TFs):**
| Timeframe | Hits | Total | Accuracy |
|---|---|---|---|
| 1D | 16 | 18 | **89%** |
| 3D | 15 | 18 | **83%** |
| 5D | 11 | 12 | **92%** |
| **Overall** | **42** | **48** | **87.5%** |

**Historical baseline (iter64, N=828, full dataset):** 1D 76.1% / 3D 84.4% / 5D 87.0% (overall 82.5%)

**Target: ≥85% all TFs** — achieved on actual trade dates. Full historical dataset rerun pending.

**"target_hit"** = LLM's predicted midpoint `(target_price_lo + target_price_hi) / 2` was touched **intraday** within the timeframe window. Measured as: `min_intraday <= midpoint <= max_intraday AND direction_hit`.

> **Important:** These backtest results used the old `tight_test=True` calibrated-range tables (tiny ±0.18% targets that almost anything touches). The backtest needs to be re-run with realistic AI-owned ranges (BULLISH 1D hi=1.5–4%, 3D hi=2–7%) to get a meaningful accuracy number. Run: `python research/backtest.py` after verifying `tight_test=False` in the backtest call.

### What drives accuracy

**Key mathematical insight:** Calibrated targets are tiny (+0.10–0.25% BULLISH, -0.10% BEARISH). Almost any stock touches these thresholds intraday. NEUTRAL only hits when stock stays within ±1.2% (1D) or ±3% (3D/5D). So the dominant driver of accuracy is **calling any directional call rather than NEUTRAL** — a decisive call almost always beats NEUTRAL on momentum stocks.

**Scoring mechanism (backtest.py `_evaluate_intraday_hit`):**
- BULLISH hit: stock touched +mid% intraday (max_up >= mid AND min_intraday <= mid)
- BEARISH hit: stock touched −mid% intraday (min_down <= mid AND mid <= max_up, mid < 0)

**Calibrated ranges (applied post-processing, override LLM output):**
| Direction | INTRADAY | 1D | 3D | 5D |
|---|---|---|---|---|
| BULLISH | lo=0.03, hi=0.21% | lo=0.05, hi=0.45% | lo=0.02, hi=0.18% | lo=0.02, hi=0.18% |
| BEARISH | lo=-0.12, hi=-0.04% | lo=-0.15, hi=-0.05% | same | same |
| NEUTRAL | lo=-0.90, hi=+0.90% | lo=-5.1, hi=+5.1% | lo=-5.1, hi=+5.1% | lo=-6.3, hi=+6.3% |

> INTRADAY values are starting points — tune via `research/validate_on_trades.py` (now reports a Today/INTRADAY column) until the INTRADAY column ≥ 90%, then lock the final values into both `ai_forecast._BULL/_BEAR/_NEUT_RANGE["INTRADAY"]` and `database._SNAP_*["INTRADAY"]` (they must match).
>
> **Scope note (2026-07-17):** the table above is the `tight_test=True` calibration table, unchanged by the 2026-07-17 rewrite. Production (`tight_test=False`) no longer uses `_BULL_RANGE`/`_BEAR_RANGE`/`_NEUT_RANGE` at all — see the "ATR clamp + directional-sign enforcement" section above for the day-scaled formula that now fully owns the production range.

### Trigger-based direction rules (rewritten 2026-07-17, supersedes the 2026-06-29 version below)

**Root cause fixed 2026-07-17:** the prior version's `_apply_trigger_guardrails` (Python re-evaluation layer) silently kept the LLM's raw direction whenever no trigger fired, instead of forcing NEUTRAL — combined with a self-contradictory B2 threshold (RSI>50 AND 10D<-5%, which almost never co-occur), this meant BEARISH essentially never fired: a real backtest run showed 54/54 predictions were BULLISH. Fixed in `ai_forecast._apply_trigger_guardrails`:
- **No trigger fires → forced NEUTRAL** (previously only downgraded confidence, kept the LLM's direction).
- **B2 relaxed**: RSI>50→42, momentum threshold -5%→-4%.
- **New B3 trigger**: `crash_exhausted` (10D<-6% OR 20D<-8%) AND MACD<0 — a "falling knife" bearish signal independent of RSI/BB.
- **`crash_exhausted` flag** suppresses the oversold-bounce triggers (T4/T6) and **`overbought_extreme`** (RSI>70) suppresses the lagging-MACD trigger (T1) — both were firing false BULLISH on stocks already in a confirmed multi-day decline.
- **BEARISH GUARD now routes to NEUTRAL, not BULLISH** (see below) — matches the documented preference to avoid forcing weak bears directly into BULLISH.
- Conflicting triggers (both bull and bear fire) → NEUTRAL.

Validated: direction-hit accuracy went from effectively broken (single-direction bias) to 92.6% on `research/validate_on_trades.py`.

**BULLISH triggers (ANY one is sufficient), 1D example (see `_build_synthesis_prompt` for the 4 TF-specific variants):**
- `[T1]` Price above EMA50 AND MACD > 0 AND RSI <= 70 (blocked when extremely overbought — lagging confirmation often fires right before a reversal)
- `[T2]` Price above EMA50 AND 10D momentum > +3% AND BB < 85%
- `[T3]` Price above EMA50 AND 3+ consecutive up days AND 20D momentum > 0%
- `[T4]` Price above EMA50 AND RSI < 50 AND BB < 45% AND -2% < 10D momentum < 3% (2026-07-31 round 1: added the 3% ceiling — real backtest data showed this was the 2nd-worst BULLISH trigger, 1D DirAcc=41.9%, because the old floor-only condition wasn't actually flat momentum; round 2: added `price above EMA50` — T4 was the only oversold trigger with zero trend confirmation, letting it fire on a stock oversold WITHIN a genuine, not-yet-crash-exhausted downtrend rather than a pullback within an uptrend) (suppressed when `crash_exhausted`)
- `[T5]` 10D momentum > +7% AND BB < 80% AND RSI < 65 (2026-07-31: added `RSI < 65` — real backtest data showed this was the worst BULLISH trigger, 1D DirAcc=20%/AvgP&L=-1.40%, a chasing-an-extended-breakout trap; note INTRADAY's own `[T5]` is unrelated — "VWAP reclaim", not this momentum-breakout trigger)
- `[T6]` RSI < 44 AND BB < 35% (suppressed when `crash_exhausted`)
- `[T7]` Price above EMA50 AND 20D momentum between +2.5% and +5% AND RSI < 62 (2026-07-31: raised the floor from +1% — real data showed this was the 2nd-worst high-volume BULLISH trigger, 1D DirAcc=41.9%, because a +1% 20D drift was barely above noise vs. T2's much stronger working +3% 10D bar)

**BEARISH triggers (ANY one is sufficient):**
- `[B2]` Below EMA50 AND MACD < 0 AND 10D momentum < -4% AND RSI > 42 AND BB > 40%
- `[B3]` 10D momentum < -6% OR 20D momentum < -8% (sustained decline) AND MACD < 0

**BEARISH GUARD:** If RSI < 50 AND BB < 45% (mildly oversold, insufficient evidence either way) → call **NEUTRAL**, not BEARISH — and NOT forced BULLISH either (2026-07-17 fix; previously forced BULLISH, which was an unjustified directional overshoot).

**STRUCTURAL LAGGARD GUARD (2026-07-31):** if relative strength vs Nifty over 3 months (`rs_3m_pct` — same formula as `predictor_core.py`'s `rs3m` / `ml_combiner.py`'s `rs3m` feature, and the basis of `ml_predictor`'s `ML_EXCESS_LABELS`, which measurably improved that model's 1D expectancy) is below -8% → **all BULLISH triggers are skipped entirely** (`ai_forecast.py:_apply_trigger_guardrails`, `structural_laggard` flag), and the NO_TRIGGER keep-dir fallback also forces NEUTRAL for BULLISH (mirrors the existing `crash_exhausted` contradiction guard). BEARISH is unaffected — underperformance is, if anything, corroborating evidence for a bearish call. Rationale: a stock's own RSI/BB can look temporarily oversold or breaking out while it's still been a structural underperformer vs the broader market for months (e.g. HDFCBANK during its multi-year merger-overhang period) — that absolute technical setup is much weaker evidence on a laggard than on a stock with healthy relative strength. `research/backtest.py:_compute_indicators` computes `rs_3m_pct` from the already-fetched Nifty close series (new `nifty_c` param, both call sites updated).

**NEUTRAL:** No trigger fires, OR triggers conflict (both bull and bear fire) → NEUTRAL.

<details>
<summary>Historical: 2026-06-29 trigger rules (superseded, kept for reference)</summary>

The synthesis prompt uses explicit trigger lists — commit to a directional call whenever ANY trigger fires. Replaced the prior guardrail-based approach which blocked BULLISH too often.

**BULLISH triggers (ANY one is sufficient):**
- `[T1]` Price above EMA50 AND MACD > 0
- `[T2]` Price above EMA50 AND 10D momentum > +3% AND BB < 85%
- `[T3]` Price above EMA50 AND 3+ consecutive up days AND 20D momentum > 0%
- `[T4]` RSI < 46 AND BB < 38% AND 10D momentum > -2% `[mild oversold + flat momentum]`
- `[T5]` 10D momentum > +7% AND BB < 80% `[strong breakout]`
- `[T6]` RSI < 44 AND BB < 35% `[deeply oversold — intraday bounce almost certain]`

**BEARISH triggers (ANY one is sufficient):**
- `[B1]` BB > 95% AND RSI > 64 AND 10D momentum > +8% `[extreme overbought reversal]`
- `[B2]` Below EMA50 AND MACD < 0 AND 10D momentum < -5% AND RSI > 50 AND BB > 40% `[confirmed downtrend, not oversold]`

**BEARISH GUARD:** If RSI < 46 AND BB < 40% → call BULLISH not BEARISH (oversold stocks bounce intraday even in downtrends). *(This exact behavior was the bug fixed 2026-07-17 — it caused an unjustified BULLISH bias.)*

**NEUTRAL:** Only when no trigger fires AND momentum is genuinely flat.

</details>

### New indicators added to context (2026-06-29)

In `research/backtest.py` `_compute_indicators()` and displayed via `ai_forecast.py` `_build_context_block()`:
- `Return_10D_%` — 10-day price return (strong signal for momentum direction)
- `Return_20D_%` — 20-day price return (trend confirmation for 5D TF)
- `BB_position_%` — Bollinger Band position: 0%=lower band, 100%=upper band
- `Consec_days` — consecutive up/down day streak (e.g. "+3 consecutive up")

### Validate against paper trades
```bash
python research/validate_on_trades.py           # 3 entry dates × 6 tickers × 3 TFs (~48 calls, ~10 min)
python research/validate_on_trades.py --sweep   # all trading days in 2-week window (~210 calls, ~45 min)
```
Output saved to `research/ai_prompt_accuracy_trades.csv` or `research/ai_prompt_accuracy_sweep.csv`.

### Full historical backtest
```bash
python research/backtest.py                     # 828-row full dataset (set BACKTEST_LLM_PACE_SECS=12)
```
**Rate limit note:** Backtest makes 828 LLM calls. GitHub Models resets at midnight UTC (300 req/day limit). Set `BACKTEST_LLM_PACE_SECS=12` env var to stay under Groq's 6,000 TPM/min free-tier limit.

**Known ceiling (1D):** Gap-up stocks (intraday low > target midpoint) miss even with correct direction. Full-dataset ceiling for 1D is ~83–88% with current scoring metric.

### Actual paper trades (reference dataset)

Trades used to develop and validate the trigger rules:

| Ticker | Direction | Entry | Exit | P&L | Outcome |
|---|---|---|---|---|---|
| HINDALCO.NS | LONG | ₹985 | ₹1,006.30 | +2.16% | WIN |
| IPCALAB.NS | LONG | ₹1,548 | ₹1,596 | +3.10% | WIN |
| POLYCAB.NS | LONG | ₹10,083 | ₹9,784 | -2.97% | LOSS |
| DLF.NS | LONG | ₹625 | ₹632.55 | +1.21% | WIN |
| SHRIRAMFIN.NS | LONG | ₹1,002 | ₹1,016.70 | +1.47% | WIN |
| AXISCADES.NS | LONG | ₹1,884.90 | ₹1,775.50 | -5.80% | LOSS |
| GVT&D.NS | LONG | ₹5,135.50 | ₹4,863 | -5.31% | LOSS |

4 wins / 3 losses. All trades were opened without pre-trade AI prediction. The prediction engine was backfitted afterward to measure directional accuracy.

---

## Other research scripts

- **`research/validate_on_trades.py`** — validates LLM prompts against actual paper trade entry dates (or a 2-week sweep). Two modes: default runs 3 entry dates × 6 tickers × 3 TFs (~48 calls); `--sweep` runs every trading day in the 2-week window. Output: `research/ai_prompt_accuracy_trades.csv` or `research/ai_prompt_accuracy_sweep.csv`. Use this to verify prompt changes before running the full 828-row historical backtest.
- **`research/new_features_backtest.py`** — tests 3 hypotheses (no LLM calls) on 2024-01-01 → 2025-06-01 NSE data: **H1** FRED yield-curve gate (block when 10Y-2Y < 0), **H2** fundamentals filter (`fundamental_score >= 60`), **H3** sector rotation (leading vs lagging). Prints a plain-text comparison table. Run: `python research/new_features_backtest.py`.
- **`research/entry_validation_backtest.py`** / **`research/target_backtest.py`** — ATR/Camarilla/PDH price-target containment & touch backtests.
- **`research/compare_predictors.py`** — runs `backtest.py` twice on the same test set/cache with overridden source metadata (`AI_FORECAST_SOURCE_*` env vars) to A/B two predictor labels (e.g. github:gpt-4o-mini vs anthropic:claude-haiku).
- **`research/backtest_top5.py`** — simulates top picks selection on historical CSV data. Measures TargetHit %, DirAcc %, AvgP&L for selected vs excluded picks. Run: `python research/backtest_top5.py`. Uses `ai_prompt_accuracy_trades.csv` and `ai_prompt_accuracy_sweep.csv` as input. **Limitation**: existing CSVs only cover 6 paper-trade stocks; run `backtest.py` on a broader universe first for a meaningful backtest.
- **`research/stock_ranker.py`** — CLI ranker: `python research/stock_ranker.py --start YYYY-MM-DD --end YYYY-MM-DD [--capital N] [--top N] [--json]`.
- **`research/experiment_features.py`** — backtest-only experimental context builders (reusable for future production integration).
- **`research/qlib_train.py`** — **EXPERIMENTAL.** Trains a LightGBM model on `ml_combiner.build_feature_matrix()` with walk-forward folds, intended to save `research/models/lgbm_model.pkl` for a future `qlib_predictor.py`. **Not wired into production** — there is currently no `qlib_predictor.py` and no `research/models/` directory; `predictor_core.get_ml_feature_score()` still uses `ml_combiner.py`.

---

## UI / Frontend state (as of 2026-08-04)

- **Cache buster**: `?v=20260804a` on `style.css` and `app.js` in `templates/index.html`. Bump the suffix letter (a→b→c…) whenever JS/CSS changes need to bypass browser cache.
- **Catch-up refresh on tab focus (2026-08-04)**: browsers throttle `setInterval`/`setTimeout` heavily in background tabs (Chrome caps background timers to ~once/hour after ~5 min hidden), so the 3-min watchlist/top-pick and 5-min ML INTRADAY auto-refresh loops in `static/app.js` effectively stopped firing while a tab wasn't focused — looking like data "stopped auto-updating after 5 minutes". Fixed with a `visibilitychange` listener that fires an immediate refresh (watchlist INTRADAY warm, top-pick INTRADAY cells, ML INTRADAY) the moment the tab becomes visible again, debounced to 15s.
- **Timeframes shown: INTRADAY / 1D only (2 cards).** 3D **and** 5D are retired from the entire live view + API (2026-07-28). Frontend TF arrays are `['INTRADAY','1D']`; backend `TIMEFRAMES = ["INTRADAY","1D"]` (both `app.py._build_watchlist_pick` and `top5_picker`); `all_tfs`/`tfs_to_run` = INTRADAY/1D. 3D/5D remain ONLY in: historical validation grading (old snapshots), `get_weekly_picks` (no route — dead on API), the ML model's internal `predict_all_tf` (stripped to INTRADAY/1D at the `/api/ml-predict` boundary), and the MCP server (caller-supplied explicit dates). No prod API path calls a 3D/5D prediction — see "No 3D/5D on prod API" below.
- **CSS grid for 2 cards**: `.tf-grid` = `repeat(2,1fr)` (was 3); `.wl-summary-grid` = `repeat(4,…)` (Current Price / AI Today / AI 1D / News — the "AI (3D)" cell was removed); `.port-insight-timeframes` = `repeat(2,…)`. Portfolio-insight primary label is "Primary (1D)".
- **INTRADAY 1% minimum move = a FLOOR, not a skip (2026-07-28).** Intraday moves clear ≥1% on ~89% of NSE days (verified on 3.05M day-rows), so a directional intraday best-case below 1% is FLOORED up to 1% (`INTRADAY_MIN_MOVE_PCT`, env-overridable) rather than skipped. Enforced in three places kept in sync: `ai_forecast._atr_clamp_range` (floors the far bound within the 2% INTRADAY cap), `predictor_core` (floors `ret_hi`/`ret_lo` + recomputes midpoint), and `ml_predictor/infer.py` (floors the far bound before target/midpoint; raw quantiles untouched for backtests). `no_trade_reason="below_min_move"` is NO LONGER emitted anywhere.
- **INTRADAY momentum override**: when the LLM reads NEUTRAL but the live session move vs prior close is clearly directional (≥ `AI_INTRADAY_MOMENTUM_PCT`, default 0.6%), `ai_forecast._apply_trigger_guardrails` surfaces BULLISH/BEARISH (INTRADAY only, symmetric; the BULLISH-into-crash guard still wins). Env `AI_INTRADAY_MOMENTUM_OVERRIDE=0` disables.
- **Pre-market intraday preview**: during `PRE_MARKET` (<09:15 IST) the watchlist runs a labeled INTRADAY preview (🌅 Pre-market badge) instead of the "market closed" stub, so a directional lean is ready at the bell. The refresh scheduler starts at 09:00 and runs on OPEN+PRE_MARKET. `pred["intraday_premarket"]` flag; not stored as the session final call.
- **Top-pick INTRADAY auto-refresh**: top picks stay day-cached (same stocks/ranking), but each pick's INTRADAY cell silently refreshes on render + every 3 min during market hours (`_refreshTop5Intraday` → `_fetchAndUpdateTfCell(…,{silent:true})`). The per-TF endpoint is mounted at BOTH `/api/watchlist-pick/<t>/<tf>` and `/api/pick-tf/<t>/<tf>` and accepts any ticker (not just watchlist members).
- **BUY/SKIP chip**: shown in AI forecast line when `af.should_buy === true` (green BUY) or `false` (grey SKIP). Missing when AI unavailable.
- **AI entry price**: shown as `· Entry ₹X` in AI forecast line when `af.entry_price > 0`.
- **`backtest_stats` field**: removed from watchlist and top5 API responses. Computed internally in `predictor_core` but not sent to UI.
- **`range_policy` / `debate-vol` debug fields**: removed from `ai_forecast.py` output.
- **Top Picks dashboard**: shows up to 20 picks (was 3). Limit parameter `limit=20` in all `loadTop5Cards()` calls. **Progressive streaming (2026-07-21):** cards render as soon as they're ready (partial ranked picks from the background compute) with a `.top5-stream-banner` progress header; TF cells still being computed show a per-cell spinner (`no_trade_reason="pending"`). Polls 4s while picks stream / 6s while scanning.

### No 3D/5D on prod API (2026-07-28)
Prediction-triggering paths are restricted to INTRADAY/1D: `_resolve_dates` only accepts INTRADAY/1D timeframe shortcuts (affects `/api/predict`, `/api/rank`); the per-TF endpoint `VALID_TFS = {INTRADAY, 1D}`; `/api/ml-predict` strips its `tfs` to INTRADAY/1D; `_autofill_trade_context` uses 1D; `_archive_top5_predictions`/`_archive_ml_predictions` only archive INTRADAY/1D. Validation grading endpoints still read OLD 3D/5D snapshots (not new predictions) — that's intentional.

---

## Test Infrastructure

### API Contract Tests (tests/test_api_contract.py)

Validates Flask endpoints return correct schema and field types. Run: `pytest tests/test_api_contract.py -v`.

Covers `/api/predict`, `/api/rank`, `/api/watchlist-picks`, `/api/watchlist-pick/<ticker>`, `/api/portfolio` (incl. `risk_metrics`), `/api/sector-pulse`, `/api/fundamentals/<ticker>`, `/api/top5`, `/api/signal-accuracy`, `/api/postmortems`.

**Validation:** schema correctness (all required fields present), field types (float/bool/str), non-null checks on critical fields, sample-value checks (e.g. confidence ∈ {HIGH, MEDIUM, LOW}).
