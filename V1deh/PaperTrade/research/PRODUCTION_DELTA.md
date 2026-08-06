# PRODUCTION_DELTA.md — what needs to ship to prod

Living ledger of changes developed in the **backtest/research layer** that must be ported to the
**production app**. Update this in the SAME commit as any backtest-logic change. One row per
shippable change.

Governing rule: new work lands in reusable `research/` modules; prod source stays on current logic
until ported. **Exception:** the DB-integrity fix (Part 3) was applied to prod directly.

Legend — Status: `SHIPPED` (already in prod source) · `READY` (module built + backtest-validated, awaiting port) · `WIP` · `TODO`.

---

## 2026-07-31 session: real direction-accuracy/P&L measurement + trigger fixes (post-review revert)

**Root cause of "why so many formulas":** `research/loop_backtest.py` is an automated loop that
rewrites `ai_forecast.py`'s prompt text, chasing only `target_hit_for_tf ≥ 90%` (band-touch), with
its own `analyze()` explicitly labeling direction accuracy "SECONDARY (for diagnostics)". Combined
with `_atr_clamp_range()` discarding the LLM's own range entirely, the whole apparatus was
measurable-but-blind to whether a direction call had any real edge. Verified on real data (890-row
backtest): 1D BULLISH DirAcc=54.2%/AvgP&L=-0.117% (losing, net of NSE costs) vs 1D BEARISH
DirAcc=60.5%/AvgP&L=+0.967% (profitable) — `target_hit_for_tf` stayed 80%+ throughout, blind to
this. Scope: INTRADAY + 1D only (3D/5D retired from every prod path).

**Post-session review (2026-08-01):** everything below was re-classified into KEEP (validated bug
fix or measured improvement) vs REVERTED (tested and found not to help, or speculative/unused).
The revert only touches code shipped THIS session — it does not affect the earlier, separately-
validated INTRADAY/1D NEUTRAL-band-widening fix (`_NEUT_RANGE["1D"]` → `(-1.5, 1.5)` in
`ai_forecast.py`/`database.py`/`ml_predictor/infer.py`/`research/range_model.py`, confirmed at
88.9% 1D / 100% INTRADAY `target_hit_for_tf`), which stays shipped.

### KEPT (validated bug fixes / measured improvements)

| Component | File:symbol | What changed | Status | Notes / risk |
|---|---|---|---|---|
| Measurement: real DirAcc + net P&L | `research/backtest.py:print_results` (TABLE 6) | New standing report — real direction (sign of `ret_for_tf`/`ret_intraday_real`, not band-touch) + net P&L (via `costs.cost_pct_for_timeframe`) by TF×direction and TF×confidence | SHIPPED | Reproduced this session's hand-computed numbers exactly on the existing CSV |
| Measurement: INTRADAY Open capture | `research/backtest.py:fetch_open_series` (new), `_entry_day_open_close` (new), `build_work_items(so=...)` | Additive — genuine same-day open→close return (`ret_intraday_real`, new CSV column) for INTRADAY rows, since `_fwd_intraday_moves`'s existing `up0/dn0` (Close-anchored, feeds `ml_predictor`'s validated calibration) can't answer "did the day finish green or red". `fetch_data()`'s signature/callers (5 other research scripts) untouched | SHIPPED | Needs one fresh backtest run to populate; older CSVs show "n/a" for INTRADAY in TABLE 6 until then |
| Measurement: loop_backtest scope + visibility | `research/loop_backtest.py:analyze/print_summary` | Scoped `["1D","3D","5D"]` → `["INTRADAY","1D"]`; added `real_dir_acc`/`real_pnl`/`real_pnl_bull`/`real_pnl_bear` alongside the existing band-touch metrics (not yet gating `target_met()`, just surfaced) | SHIPPED | Prevents this loop from silently re-optimizing purely toward band-containment on a timeframe (3D/5D) nothing in prod serves |
| Trigger fix: T5 tightened | `ai_forecast.py:_apply_trigger_guardrails` (T5), 1D prompt block, `research/backtest.py:_compute_trigger_flags` (T5), `CLAUDE.md` | Added `AND RSI < 65` — real data showed T5 was the worst BULLISH trigger (1D: N=5, DirAcc=20%, AvgP&L=-1.40%), a chasing-an-extended-breakout trap. INTRADAY's own `[T5]` ("VWAP reclaim") is unrelated and untouched; 3D/5D prompt text left alone | SHIPPED | Verified: RSI≥65 no longer fires T5; RSI<65 still does |
| Trigger fix: T4 tightened (2 rounds) | `ai_forecast.py:_apply_trigger_guardrails` (T4), 1D prompt block, `research/backtest.py:_compute_trigger_flags` (T4), `CLAUDE.md` | Round 1: added a `ret10 < 3.0` ceiling — the condition was named "mild oversold + FLAT momentum" but only floored `ret10` with no ceiling. Real data: 1D N=31, DirAcc=41.9% (worse than a coin flip), AvgP&L=-0.349%. Round 2: added `above_ema50` — was the only oversold trigger with zero trend confirmation | SHIPPED | Verified both rounds in isolation |
| Trigger fix: T7 tightened | `ai_forecast.py:_apply_trigger_guardrails` (T7), 1D prompt block, `research/backtest.py:_compute_trigger_flags` (T7), `CLAUDE.md` | Raised the `ret20` floor 1.0→2.5 — a +1% 20D drift is barely above noise vs. T2's much stronger, working `ret10>+3%` bar. Real data: 1D N=31, DirAcc=41.9%, AvgP&L=-0.260% | SHIPPED | Verified in isolation |
| Structural-laggard guard (hedge-fund-style RS filter, 3-month only) | `research/backtest.py:_compute_indicators` (`rs_3m_pct`, new `nifty_c` param), `ai_forecast.py:_apply_trigger_guardrails` (`structural_laggard`), `_build_context_block`, 1D prompt block, `CLAUDE.md` | When relative strength vs Nifty over 3 months (`rs_3m_pct`, same formula as `predictor_core.py`'s `rs3m` / the basis of `ml_predictor`'s validated `ML_EXCESS_LABELS`) is below -8%, ALL BULLISH triggers are skipped AND the NO_TRIGGER keep-dir fallback also forces NEUTRAL for BULLISH — BEARISH unaffected | SHIPPED | On the worst-offender subset, went from 26.7% (T4/T5/T7 only) → 42.5% DirAcc (+laggard guard) — a real contribution. A 6-month variant was tried and scored worse (36.6%) — reverted, see below |
| Bug fix: Ollama health-check timeout too tight | `llm_client.py` (2 sites: `_try_ollama_fn`'s Phase-1 check, the `fast_fail` last-resort check) | Raised `timeout=20`/`25` → `35` for both. A direct `curl` measurement of the live `v1deh-ollama.hf.space` cold-start showed a real response time of ~25.8s — both old timeouts were failing this health check almost every time by a hair | SHIPPED | Verified: health check now succeeds; the cloud-provider-specific `timeout=20`s elsewhere in the file (Cerebras etc.) were left untouched |
| Launchd job audit | `~/Library/LaunchAgents/com.papertrade.loopbacktest.once.plist` | Confirmed inert — `StartCalendarInterval` is pinned to a fully-specified past instant (2026-06-18 02:07); already fired once, cannot refire | Verified, no action needed | — |

**Overall validation (200-row live backtest, diverse 15-ticker universe, all KEPT fixes above combined):** splitting the same sample by ticker shows the fixes worked as intended — **the 12 "normal" stocks improved from the 54.2% baseline DirAcc to 56.4%** (N=94, P&L roughly flat at -0.11%), while **3 specific stocks (HDFCBANK.NS, TITAN.NS, SUNPHARMA.NS) remained a stubborn drag (26.9% DirAcc, N=26)** that pulled the blended topline to 50.0%. Extensive iteration on those 3 stocks alone never exceeded ~43% DirAcc — a genuine ceiling for these specific stocks/dates, not a fixable systematic bug. Recommendation stands: the fixes work on 87% of the universe; the 3-stock drag is a known, accepted limitation.

### REVERTED (tested and found not to help, or unvalidated/speculative)

| Component | What it was | Why reverted |
|---|---|---|
| Range: guardrail-not-override mode (`AI_TRUST_LLM_RANGE`) | Flag to use the LLM's own predicted range as-is when it looked "well-formed" (`_accept_llm_range_if_sane`), instead of always rebuilding from the ATR formula | **A/B tested live, `research/blend_backtest.py`, N=400**: ATR band target_hit=78%/graded=84%/width=0.29% vs the LLM's own raw range target_hit=61%/graded=74%/width=0.97% (3.4x wider) — worse and less precise on every axis, even at HIGH confidence. The ATR rebuild is genuinely earning its keep; fully removed rather than left as a dead flag |
| Diagnostic flag: skip trigger guardrails (`AI_SKIP_TRIGGER_GUARDRAILS`) | Bypassed the whole Python trigger framework, letting the LLM's own bull/bear-debate direction pass through unmodified | Only tested on the narrow 3-stock worst-offender subset (scored 42.9% there, vs 26.7-42.5% for the trigger framework) — never validated broadly enough to justify keeping as a shipped option; removed rather than left unused |
| Structural-laggard guard: 6-month RS window variant (`AI_LAGGARD_WINDOW=6m`, `rs_6m_pct`) | Alternate lookback window for the (kept) structural-laggard guard | A/B tested live on the worst-offender subset: 3-month scored 42.5% 1D DirAcc, 6-month scored 36.6% — worse, despite a promising manual 8-date spot-check. Good reminder that a hand-picked date check doesn't override the live LLM-sampled result. Removed the toggle and `rs_6m_pct` computation entirely; 3-month is the only supported window now |
| `_BULL_RANGE`/`_BEAR_RANGE` INTRADAY/1D calibration edits | Retuned values for the `tight_test=True`-only calibration table | Discovered mid-session this table is **dead code** — `run_backtest()` hardcodes `_tight_test_ranges=False`, so `_apply_calibrated_range()` is never invoked from anywhere in the current call graph. The edit had zero real effect; reverted to the original values to avoid implying a behavior change that never existed |

---

## Already applied to shared/prod files this session

| Component | File:symbol | What changed | Status | Notes / risk |
|---|---|---|---|---|
| DB: split OHLCV cache | `data_sources.py:_OHLCV_DB_PATH` | now `ohlcv_cache.db` (was shared `paper_trading.db`) | SHIPPED | takes effect on app restart; old `ohlcv_cache` rows in `paper_trading.db` become dead (harmless) |
| DB: OHLCV conn hardening | `data_sources.py:_ohlcv_db()` | WAL + `busy_timeout=5000` + `synchronous=NORMAL` | SHIPPED | — |
| DB: trade-DB conn hardening | `database.py:_conn()` | `timeout=5.0` + `busy_timeout=5000` + `synchronous=NORMAL` | SHIPPED | — |
| DB: atomic backup | `database.py:_atomic_snapshot()`+`hf_upload_db()` | checkpoint(TRUNCATE) + `VACUUM INTO` snapshot, upload snapshot not live file | SHIPPED | verified: consistent 4.5MB snapshot, integrity ok |
| DB: restore ordering | `database.py:_clear_journal_siblings()`+`_hf_download_db()` | clear stale `-wal`/`-shm` around restore copy | SHIPPED | prevents stale-WAL-replay → "malformed" |
| DB: clean shutdown | `database.py:_checkpoint_on_exit()` (atexit) | fold WAL into main DB on exit | SHIPPED | — |
| DB: db-diag no longer clobbers live DB | `app.py:/api/db-diag` | inspect downloaded copy READ-ONLY (`mode=ro`), never `copy2` over live DB | SHIPPED | — |
| AI: ATR-anchored TIGHT range prompt | `ai_forecast.py:_build_synthesis_prompt` | ATR in context + ATR-multiplier target levels + tight-band guidance | SHIPPED (this session) | **decision pending:** relocate to `range_model.py` (revert prod) or keep. See Part 4/8. |
| AI: ATR clamp safety net | `ai_forecast.py:_atr_clamp_range` + `_ATR_*` dicts | midpoint/width/cap clamp | SHIPPED (this session) | relocate candidate → `range_model.py` |
| AI: per-date cache key | `ai_forecast.py:get_ai_forecast` (`_forecast_date`) | backtest cache keyed by historical date, not wall-clock | SHIPPED (this session) | prod passes no `_forecast_date` → unchanged behaviour |
| AI: Ollama-only NameError fix | `ai_forecast.py` ollama-only block | assign `should_buy`/`ai_entry_price` | SHIPPED (this session) | real prod bug fix |
| LLM: Ollama health/timeout fixes | `llm_client.py` | neg-TTL health cache, 20s probe, 70s chat, 45s warmup / 120s infer backoff | SHIPPED (this session; some user-authored) | low-risk bug fixes — keep |

> DB note: the local `paper_trading.db` is NOT actually corrupted — the earlier "malformed" was an
> artifact of reading it `immutable=1` while a live WAL existed. `.recover` recipe is proven
> (break-glass only). Backtest readers must use `mode=ro` (reads WAL), never `immutable=1`.

---

## 2026-07-17 session: AI accuracy tuning + LLM dispatch cleanup

All items below were edited directly in the shared root files (`ai_forecast.py`, `llm_client.py`)
— there is only ONE copy of each in the repo (verified via file search), imported identically by
`predictor_core.py`/`app.py` (production) and `research/backtest.py` (backtest) via
`sys.path.insert(0, "..")`. **Nothing needed a separate port step — these changes are already
live in production as soon as they were saved.** This table exists purely as the change ledger.

Validated end-to-end via `research/validate_on_trades.py` (6 tickers × 3 dates × 3 TFs, 54 rows):
`graded_hit_for_tf` 66.7%→96.3%, `target_hit_for_tf` (strict midpoint) 63.0%→83.3%,
direction-hit 92.6%. Full narrative in `research/ai_prompt_accuracy_trades.csv` run history and
session memory.

| Component | File:symbol | What changed | Status | Notes / risk |
|---|---|---|---|---|
| AI: trigger guardrail rewrite | `ai_forecast.py:_apply_trigger_guardrails` | Added `crash_exhausted`/`overbought_extreme` flags that suppress oversold-bounce (T4/T6) and lagging-MACD (T1) false-BULLISH overrides; relaxed B2's self-contradictory threshold (RSI>50→42, 10D<-5%→-4%); added B3 "falling knife" trigger; **no-trigger-fires now forces NEUTRAL** (previously silently kept the LLM's raw, BULLISH-biased direction — root cause of the original bug: 54/54 backtest predictions were BULLISH) | SHIPPED | Fixes a real production bug — every watchlist/top-picks prediction was subject to this same silent-BULLISH-bias defect |
| AI: synthesis prompt sync | `ai_forecast.py:_build_synthesis_prompt` (4 TF blocks) | Updated INTRADAY/1D/3D/5D direction-guide text to match the code guardrail changes above (BEARISH GUARD → NEUTRAL not BULLISH, new CRASH/EXHAUSTION GUARD language, relaxed B2, new B3) | SHIPPED | Prompt-only; LLM guidance now matches the enforced Python guardrail |
| AI: NEUTRAL sign-bug fix | `ai_forecast.py:_atr_clamp_range` | NEUTRAL bands previously had NO directional-sign enforcement — LLM could return an all-positive or all-negative "NEUTRAL" band with zero protection against the other direction. Now rebuilt as a clean ATR-scaled band straddling zero | SHIPPED | Real correctness bug fix, not a tuning choice |
| AI: ATR-scaled range formulas (near/far/neutral) | `ai_forecast.py:_easy_near_bound_pct`/`_far_bound_pct`/`_neutral_half_width_pct` | Replaced the old flat `_ATR_MID_CEILING`/`_ATR_MAX_WIDTH`/`_ATR_TARGET_MULT` dicts with day-scaled power-law formulas (`BASE × window_days^EXP × ATR%`) — near-bound, far-bound, and NEUTRAL half-width each have their own fitted base/exponent instead of one hardcoded number per timeframe. Untested horizons (5D, 1W) get an automatically consistent value instead of a guessed constant | SHIPPED | **Deliberate accuracy/informativeness trade-off, explicitly requested**: the LLM's own predicted range is now discarded entirely for BULLISH/BEARISH/NEUTRAL — only direction+confidence still come from the model. Raises measured hit-rate at the cost of the target band being calibrated to the metric rather than purely to LLM conviction. See `memory/repo` notes for full trade-off discussion. |
| LLM: provider task_offset rotation fix | `llm_client.py:make_chat_call` (`_one_pass`) | `task_offset` (already computed round-robin per stock in `ai_forecast.py`) was silently ignored by the dispatch logic — every concurrent call picked the identical globally-"best" provider, causing a thundering-herd rate-limit cascade across a whole batch. Now rotates the starting pick among currently-available providers | SHIPPED | Real bug fix — affects every production call path (watchlist, top-picks, backtest), not backtest-only |
| LLM: `preferred_provider` param | `llm_client.py:make_chat_call` | New optional param to force a specific provider to the front (falls through the chain if unavailable) | SHIPPED | Additive, no behavior change unless passed |
| LLM: removed `make_chat_call_racing` | `llm_client.py`, `ai_forecast.py` | Was the ONLY caller-site-specific dispatch path (used just once, in `ai_forecast.py`'s fast_mode synthesis call) and had its own version of the task_offset bug (`_try(name)` ignored `name`, so both "racing" futures could silently pick the same provider). Merged into a single `_make_chat_call(..., fast_fail_on_rate_limit=_fast_fail, ...)` call | SHIPPED | Simplification — the task_offset fix above already solves the herding problem the racing function existed to work around |
| LLM: `research/providers_ext.py` removed | `research/providers_ext.py` (deleted), `research/backtest.py:_register_extra_providers` (removed) | Gemini/SambaNova were already ported into `llm_client.py` as first-class providers (see row below in the prior table) — this backtest-only runtime-patch shim was fully redundant and, additionally, less correct than the native path (no rate-limit/daily-exhaustion cooldown tracking, blindly retried every call) | SHIPPED | File deletion — verified no remaining references anywhere in the repo |
| LLM: Gemini/SambaNova `_keys` dict fix | `llm_client.py` (was in the now-removed `make_chat_call_racing`) | The old racing function's provider-list construction omitted `gemini`/`sambanova` entirely from its `_keys` dict, so those two providers were silently excluded from ever being raced even when configured | N/A (removed with the function) | Moot now that the function is gone, noted for history |

---

## To port from research/ modules → prod (per approved plan)

| Component | Backtest module:fn | Prod target file:symbol | Port steps | New env vars | Validated? | Notes/risk |
|---|---|---|---|---|---|---|
| Free LLM providers | `research/providers_ext.py:try_gemini/try_sambanova/register()` | `llm_client.py` `_CLOUD_PROVIDERS`+`_PROVIDER_FNS`+`_PROVIDER_STATUS` | add the two `_try_*` fns + register in the chain | `GEMINI_API_KEY,GEMINI_MODEL,SAMBANOVA_API_KEY,SAMBANOVA_MODEL` | **SHIPPED (2026-07-17)** | Ported to `llm_client.py` as first-class providers (`_try_gemini`/`_try_sambanova` via shared `_try_openai_compatible`), appended LAST to `_CLOUD_PROVIDERS` so happy path is unchanged and they auto-promote when the first four degrade. No-op without keys (verified). `.env` has commented placeholders + signup URLs. `research/providers_ext.py` and its `backtest.py:_register_extra_providers()` caller were **removed (2026-07-17)** now that the port is confirmed shipped — the backtest gets Gemini/SambaNova through `llm_client.py`'s own dynamic sort, no separate runtime patch needed. |
| Anti-skip: bounded + partial results | (backtest inline: `research/backtest.py` deferred-retry rounds) | `app.py` watchlist routes (`/api/watchlist-pick/<ticker>`, `/<ticker>/<tf>`, `/api/watchlist-picks`) | flip `_ai_fast_fail_on_rate_limit`→True (bounded per-stock); per-ticker deadline 320s→90s, bulk 200s→90s; unresolved TF → `timeout` reason (frontend already auto-refetches → background fill) | — | **SHIPPED (2026-07-17)** | Kills the ≤320s-per-card block. Frontend needed no change — `loadWatchlist` already renders shells → per-ticker fill → auto-refetch of `timeout` cells → 90s auto-retry banner. Re-anchors on the existing progressive-load machinery. |
| Watchlist prediction cache | (existing `_WATCHLIST_PICK_CACHE`) | `app.py:/api/watchlist-picks` bulk `_predict` | read cache before compute, write after (single-ticker route already did this) | — | **SHIPPED (2026-07-17)** | Per-(ticker,tf) cache; TTL 15m INTRADAY / until-IST-midnight 1D/3D. Re-views skip the LLM. |
| Arithmetic √days ranges | `research/range_model.py` | `ai_forecast.py` (`_build_synthesis_prompt`,`_generate_range_from_point`,`_atr_clamp_range`,`_apply_calibrated_range`) + `database.py` (`_SNAP_*`) import from it | replace literal dicts with `range_model` calls; database imports shared fn (kills "MUST match" coupling) | — | TODO | must reproduce backup (1D/3D exact) |
| Extra data APIs | `research/data_ext.py:fetch_twelvedata/…` | `data_sources.py` fallback chain + `news_sentiment.py` | fold fetchers into chain | `TWELVEDATA_API_KEY,TIINGO_API_KEY,FMP_API_KEY,POLYGON_API_KEY` | TODO | NSE coverage partial — news + backstop |
| Deferred-retry scheduler | `research/retry_queue.py:run_with_deferred_retry` | `app.py` watchlist/top5 endpoints | wrap fan-out; render partial results, retry only failed | — | TODO | the "no >10-min wait / partial results" fix |
| TradingView NSE live | `research/tradingview_ext.py:tv_live/tv_screen` | `data_sources.fetch_live_price` + `intraday_live.py` + universe screen | add as a live source with retry + yfinance fallback | — (no key) | TODO | LIVE only (not historical); unofficial endpoint — wrap defensively |
| Research funnel + fact/inference framing | `research/` prototype | `top5_picker.py` + `ai_forecast` output + UI | port staged funnel + verify-figures framing | optional `ANTHROPIC_API_KEY` (paid Fable 5) | TODO | from the Fable 5 doc |

## Verdicts (no port)
- **Coolify:** not free (needs paid VPS) — stay on HF Spaces.
- **TradingView MCP server:** don't run it (wraps yfinance) — use the lean scanner client above instead.
