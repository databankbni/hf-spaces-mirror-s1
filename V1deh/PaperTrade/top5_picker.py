#!/usr/bin/env python3
"""
top5_picker.py — Finds the top 5 NSE stocks to invest in for the week,
with predictions across three timeframes (1D, 3D, 5D) run concurrently.

Usage (programmatic):
    from top5_picker import get_top5_picks
    result = get_top5_picks()
"""

from __future__ import annotations
import sys, os, warnings
import datetime as _dt
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Callable

from predictor_core import predict_stock_v2, DEFAULT_UNIVERSE, timeframe_to_dates

TIMEFRAMES = ["INTRADAY", "1D"]  # 3D + 5D removed — INTRADAY/1D are the shown horizons


def _slim_ml_tf(m: Optional[dict]) -> Optional[dict]:
    """Extract the frontend-facing subset of an ml_predictor TF object (predict_all_tf['tfs'][tf])."""
    if not m:
        return None
    return {
        "direction":             m.get("direction"),
        "confidence":            m.get("confidence"),
        "confidence_prob":       m.get("confidence_prob"),
        "high_conviction":       m.get("high_conviction"),
        "predicted_return_lo":   m.get("predicted_return_lo"),
        "predicted_return_hi":   m.get("predicted_return_hi"),
        "target_price_lo":       m.get("target_price_lo"),
        "target_price_hi":       m.get("target_price_hi"),
        "expected_target_price": m.get("expected_target_price"),
        "current_price":         m.get("current_price"),
    }


def _ml_conviction_score(ml_res: Optional[dict]) -> float:
    """ML selection score for a stock — INTRADAY/1D (matches the AI ranking horizons).
    confidence_prob × |expected return| × direction multiplier."""
    if not ml_res or not ml_res.get("available"):
        return 0.0
    tfs = ml_res.get("tfs", {}) or {}
    best = 0.0
    for tf in ("INTRADAY", "1D"):
        d = tfs.get(tf) or {}
        prob = d.get("confidence_prob") or 0.5
        cur = d.get("current_price") or 0
        exp = 0.0
        if cur and d.get("expected_target_price"):
            exp = (d["expected_target_price"] / cur - 1) * 100
        elif d.get("predicted_return_hi") is not None:
            exp = d["predicted_return_hi"]
        direction = d.get("direction")
        dir_mult = 1.0 if direction == "BULLISH" else 0.2 if direction == "BEARISH" else 0.4
        s = prob * abs(exp) * dir_mult
        if s > best:
            best = s
    return best

# Universe for top picks — the WHOLE NSE market (all cap tiers), sourced via
# universe.get_universe() (NSE full equity list → Nifty-500 CSV → static fallback),
# so mid/small-caps are included, not just the top 500 by market cap. Never empty even
# when Yahoo blocks the Hugging Face Spaces datacenter IP.
def _build_top5_universe(n: int = 0) -> list[str]:
    try:
        from universe import get_universe
        tickers = [t for t in get_universe().keys() if t.endswith(".NS")]
        return tickers[:n] if n and n > 0 else tickers
    except Exception:
        return []

_TOP5_UNIVERSE: list[str] = []

def _get_top5_universe(force_refresh: bool = False) -> list[str]:
    global _TOP5_UNIVERSE
    if force_refresh:
        _TOP5_UNIVERSE = []
    if not _TOP5_UNIVERSE:
        _TOP5_UNIVERSE = _build_top5_universe()
    return _TOP5_UNIVERSE or DEFAULT_UNIVERSE


# ── SECTOR-DRIVEN CANDIDATE POOL (replaces ML scoring for Top Picks) ──────────────────────────
# Instead of ranking the whole market by an ML score, Top Picks now draws from the most VOLATILE
# ("violent") NSE sectors and lets AI pick the good stocks. The candidate pool = large-cap
# constituents of every tracked sector, ORDERED by their sector's realized volatility (most
# volatile first), so AI scans the hot sectors' stocks first. Env TOP5_SECTOR_MODE=0 restores the
# old whole-market ML-scored scan.
# DEFAULT OFF: Top Picks now scans the WHOLE NSE market ranked by stock ATR% volatility
# (see _score_scan / _score_tf) with sector diversity applied to the final picks, instead of
# restricting the candidate pool to a handful of large-cap sector constituents. Set
# TOP5_SECTOR_MODE=1 to restore the restricted sector-pool scan.
_TOP5_SECTOR_MODE = os.getenv("TOP5_SECTOR_MODE", "0") != "0"

# ── Candidate-pool ROTATION (so refreshes surface different volatile names) ─────────────────────
# Without rotation, sector mode scans the SAME ~88 large-caps every time and — because every
# constituent is scored and the best top-N always win — the picks are identical each refresh.
# Rotation fixes this: each compute takes a *rotating window* of every volatile sector's stocks
# (offset from `_rotation_offset()`), so you keep scanning the most 'violent' sectors but see FRESH
# names. The offset is the IST CALENDAR DAY (so a NEW DAY rotates on a plain browser reload, and
# reloads WITHIN a day stay stable) plus a manual bump that ticks up on each force-refresh (so the
# refresh button also rotates within a day). Env TOP5_ROTATE=0 restores identical-every-time.
_SECTOR_ROTATE = os.getenv("TOP5_ROTATE", "1") != "0"
# Max constituents drawn from each sector per refresh. Must be < a typical sector's size for the
# rotation to actually change the winners (avg tracked sector has ~8-9 large-caps in the map), so 6
# leaves room to rotate a few in/out each refresh. Env TOP5_SECTOR_PER overrides.
_SECTOR_PER_SECTOR = int(os.getenv("TOP5_SECTOR_PER", "6") or "6")
# Manual bump advanced once per FORCE-refresh (the /api/top5?refresh=1 button) so the button varies
# picks within a single day, on top of the day-based baseline.
_SECTOR_MANUAL_BUMP = 0


def _ist_day_index() -> int:
    """Whole days elapsed (IST) since a fixed epoch — a stable per-calendar-day integer."""
    ist = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
    return (_dt.datetime.now(ist).date() - _dt.date(2020, 1, 1)).days


def _rotation_offset(force_refresh: bool = False) -> int:
    """Rotation offset = IST calendar day + manual bump.

    Day component → a new trading day rotates automatically on a plain reload (cache expires at IST
    midnight, so the next reload recomputes with a new day index); reloads within the same day reuse
    the same offset (stable picks). Manual bump → each force-refresh advances it so the refresh
    button surfaces fresh names within a day. Survives process restarts (day is calendar-derived).
    """
    global _SECTOR_MANUAL_BUMP
    if force_refresh:
        _SECTOR_MANUAL_BUMP += 1
    return _ist_day_index() + _SECTOR_MANUAL_BUMP

# Only surface affordable stocks: Top Picks excludes any stock trading ABOVE this price (₹). Keeps
# the picks actionable for smaller position sizes and filters out very high-priced scrips.
# Env TOP5_MAX_PRICE overrides; set 0 to disable the cap.
_TOP5_MAX_PRICE = float(os.getenv("TOP5_MAX_PRICE", "5000") or "5000")

# Excludes penny stocks (₹ below this floor). Ranking is ATR-as-%-of-price PRIMARY (see
# _score_scan/_score_tf below) — on penny stocks that % is inflated by tick-size granularity and
# thin, wide-spread order books rather than real tradeable momentum, so they kept rising to the
# top while being unreliable to hit any predicted intraday range. Env TOP5_MIN_PRICE overrides;
# set 0 to disable the floor.
_TOP5_MIN_PRICE = float(os.getenv("TOP5_MIN_PRICE", "100") or "100")

# Sector diversity: cap how many final picks may come from any one mapped NSE sector so a single
# hot sector can't fill the whole list. Stocks with no sector mapping (most mid/small-caps) are
# never capped. Env TOP5_MAX_PER_SECTOR overrides; 0 disables the cap.
_MAX_PER_SECTOR = int(os.getenv("TOP5_MAX_PER_SECTOR", "3") or "3")


def _diversify_by_sector(picks: list[dict], top_n: int, max_per_sector: int) -> list[dict]:
    """Spread the final picks across NSE sectors.

    Walks the already-ranked ``picks`` and caps classified stocks at ``max_per_sector`` per
    sector; stocks whose sector can't be resolved are never capped. If diversity leaves the list
    short of ``top_n``, the capped-out overflow is used to backfill (in rank order). Order is
    otherwise preserved, so the volatility ranking is honored.
    """
    if max_per_sector <= 0:
        return picks[:top_n]
    try:
        from sector_pulse import get_sector_for_ticker
    except Exception:
        return picks[:top_n]
    out: list[dict] = []
    counts: dict[str, int] = {}
    overflow: list[dict] = []
    for p in picks:
        sec = get_sector_for_ticker(p.get("ticker", ""))
        if sec is not None:
            if counts.get(sec, 0) >= max_per_sector:
                overflow.append(p)
                continue
            counts[sec] = counts.get(sec, 0) + 1
        out.append(p)
        if len(out) >= top_n:
            return out
    for p in overflow:
        if len(out) >= top_n:
            break
        out.append(p)
    return out[:top_n]


def _sector_ranked_universe(rotate: bool = False, per_sector: int = 0, offset: int = 0) -> tuple[list[str], dict[str, float]]:
    """Return (ordered_tickers, {ticker: sector_volatility_pct}) for the sector-driven scan.

    Tickers are the large-cap constituents of the tracked NSE sectors, ordered by their sector's
    realized volatility (descending). Sectors missing a volatility read (e.g. a broken index
    ticker) sort last. Returns ([], {}) on failure so the caller falls back to the market scan.

    When ``rotate`` is True, each sector's constituent list is rotated by ``offset`` (typically the
    IST calendar day + manual bump, see _rotation_offset) and — when ``per_sector`` > 0 — trimmed
    to a rotating window of that many stocks. Sector (volatility) ORDER is always preserved, so
    every refresh keeps scanning the most volatile sectors first while surfacing DIFFERENT stocks
    from them. With rotate=False it behaves exactly as before (deterministic full list).
    """
    try:
        from sector_pulse import get_sector_volatility, get_sector_constituents
        vols = get_sector_volatility()
        cons = get_sector_constituents()
    except Exception:
        return [], {}
    if not cons:
        return [], {}
    vol_by_sector = {r["name"]: r["volatility_pct"] for r in vols}
    _default_vol = min((r["volatility_pct"] for r in vols), default=0.0)
    # Sectors WITH a volatility read first (vol-desc), then any unread sectors (default vol).
    ordered_sectors = [r["name"] for r in vols] + [s for s in cons if s not in vol_by_sector]
    off = offset if rotate else 0
    ordered: list[str] = []
    vol_by_ticker: dict[str, float] = {}
    for sec in ordered_sectors:
        sv = vol_by_sector.get(sec, _default_vol)
        members = [tk for tk in cons.get(sec, []) if tk not in vol_by_ticker]
        if not members:
            continue
        if rotate and len(members) > 1:
            k = off % len(members)
            members = members[k:] + members[:k]      # rotate this sector's stocks by the offset
        if per_sector and per_sector > 0:
            members = members[:per_sector]            # keep only a rotating window per sector
        for tk in members:
            ordered.append(tk)
            vol_by_ticker[tk] = sv
    return ordered, vol_by_ticker
    return ordered, vol_by_ticker


# Round-robin cursor over the cold (uncached) tail of the universe so successive scans
# sweep different cold stocks and gradually warm the whole market.
_SCAN_COLD_OFFSET = 0


def _order_and_cap_scan(universe: list[str], cap: int) -> list[str]:
    """Order the scan universe cache-first, then cap it.

    Already-cached stocks (watchlist mid/small-caps + prior scans) are scanned first so
    they resolve instantly, giving fast and complete first results. The cold remainder is
    rotated by a persistent cursor so each run scans a different cold slice — over
    successive runs the whole market is swept and the OHLCV cache fully warms.
    """
    global _SCAN_COLD_OFFSET
    try:
        # Match the period the scan (predict_stock_v2 → _load_ticker_data) actually
        # caches: "2y". Checking "1y" here (the old value) meant the warm set was almost
        # always empty, so cache-first ordering silently no-op'd. Phase 1b's ML pass also
        # reads the same "2y" row, so warm stocks skip the OHLCV re-fetch entirely.
        from data_sources import cached_tickers
        warm = cached_tickers("2y")
    except Exception:
        warm = set()

    warm_list = [t for t in universe if t in warm]
    cold_list = [t for t in universe if t not in warm]
    # Whole-market scan (cap<=0): keep every stock, just ordered cache-first so warm names
    # resolve instantly and the cold remainder still gets scanned (and warmed) this run.
    if cap <= 0 or len(universe) <= cap:
        return warm_list + cold_list
    n_cold = len(cold_list)
    if n_cold:
        off = _SCAN_COLD_OFFSET % n_cold
        cold_list = cold_list[off:] + cold_list[:off]

    selected = (warm_list + cold_list)[:cap]

    # Advance the cursor by how many cold stocks we actually scanned this run.
    cold_scanned = max(0, len(selected) - len(warm_list))
    if n_cold:
        _SCAN_COLD_OFFSET = (_SCAN_COLD_OFFSET + cold_scanned) % n_cold
    return selected



def _run_predict_with_ctx(
    ticker: str,
    tf: str,
    market_ctx: Optional[dict],
    run_ai: bool = False,
    ai_fast_mode: bool = False,
    skip_news: bool = False,
) -> tuple[str, str, dict]:
    """Run one timeframe prediction using shared market context when available."""
    start, end = timeframe_to_dates(tf)
    pred = predict_stock_v2(
        ticker,
        start,
        end,
        _market_ctx=market_ctx,
        _run_ai_forecast=run_ai,
        _ai_fast_mode=ai_fast_mode,
        _ai_fast_fail_on_rate_limit=True,
        _skip_news=skip_news,
    )
    return ticker, tf, pred


def _get_specialist_recommendation(ticker: str) -> Optional[dict]:
    """
    Check if this stock is a specialist for a specific timeframe (Intraday vs 1D).
    Returns {best_tf, accuracy, reason} if specialist found, else None.
    """
    try:
        from database import get_connection
        conn = get_connection()
        cursor = conn.cursor()

        query = """
        SELECT
          timeframe,
          COUNT(*) as total,
          SUM(CASE WHEN validation_result = 'HIT' THEN 1 ELSE 0 END) as hits,
          ROUND(CAST(SUM(CASE WHEN validation_result = 'HIT' THEN 1 ELSE 0 END) AS REAL) / COUNT(*), 3) as win_rate
        FROM prediction_snapshots
        WHERE ticker = ? AND validation_status = 'VALIDATED'
          AND validation_result IN ('HIT', 'MISS')
          AND timeframe IN ('INTRADAY', '1D')
        GROUP BY timeframe
        HAVING COUNT(*) >= 10
        """

        cursor.execute(query, (ticker,))
        rows = cursor.fetchall()
        conn.close()

        if len(rows) < 2:
            return None

        data = {row[0]: {"win_rate": row[3], "hits": row[2], "total": row[1]} for row in rows}

        intraday_wr = data.get("INTRADAY", {}).get("win_rate", 0)
        one_d_wr = data.get("1D", {}).get("win_rate", 0)

        if abs(intraday_wr - one_d_wr) >= 0.05:
            if intraday_wr > one_d_wr:
                return {
                    "best_tf": "INTRADAY",
                    "accuracy": f"{int(intraday_wr*100)}%",
                    "reason": f"Specialist: INTRADAY {int(intraday_wr*100)}% vs 1D {int(one_d_wr*100)}%"
                }
            else:
                return {
                    "best_tf": "1D",
                    "accuracy": f"{int(one_d_wr*100)}%",
                    "reason": f"Specialist: 1D {int(one_d_wr*100)}% vs INTRADAY {int(intraday_wr*100)}%"
                }
        return None
    except Exception:
        return None


def get_top5_picks(
    universe: Optional[list[str]] = None,
    top_n: int = 20,
    _universe_size: int = 0,
    force_universe_refresh: bool = False,
    progress_cb: Optional[Callable[[dict], None]] = None,
) -> dict:
    """
    Returns top N stocks with 1D/3D/5D predictions.

    Returns dict:
    {
      "picks": [
        {
          ...full prediction dict from 5D run (anchor),
          "rank": int,
          "timeframes": {
            "1D": {"expected_return_range", "midpoint", "ret_lo", "ret_hi", "direction", "confidence"},
            "3D": {...},
            "5D": {...}
          }
        },
        ...
      ],
      "market": {...},
      "generated_at": "YYYY-MM-DD HH:MM",
      "errors": [...]
    }
    """
    from datetime import datetime
    import time
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("top5")

    start_time = time.time()

    def _publish(payload: dict) -> None:
        """Emit a progress snapshot to the caller (best-effort; never raises)."""
        if progress_cb is None:
            return
        try:
            progress_cb(payload)
        except Exception as _pe:
            logger.warning("[TOP5] progress_cb failed: %s", _pe)


    # Step 1: signal-only 1D scan for candidate selection (no LLM).
    # Draws from the WHOLE NSE market so mid/small-caps are eligible, but caps the scan
    # (_universe_size) for fast first results. _order_and_cap_scan orders cache-first —
    # already-warmed stocks (watchlist mid/small-caps + prior scans) scan instantly — and
    # rotates the cold remainder across runs so the whole market is swept over time.
    # Phase 1 makes NO LLM calls, so cost is time, not API quota; LLM quota is spent only
    # on the shortlisted candidates in Phase 2.
    effective_universe = universe or _get_top5_universe(force_refresh=force_universe_refresh) or DEFAULT_UNIVERSE
    # Sector-driven mode: candidate pool = large-cap constituents of the most VOLATILE sectors,
    # ordered by sector volatility. AI (Phase 2) does the picking — ML is out of selection. Only
    # applies when the caller didn't pass an explicit universe. Falls back to the market scan on
    # any failure (e.g. sector index downloads blocked).
    # Rotation (TOP5_ROTATE, default ON) takes a rotating per-sector window each refresh so the
    # picks aren't the identical volatile names every time — see _sector_ranked_universe.
    _sector_vol_by_ticker: dict[str, float] = {}
    _sector_mode_active = False
    if _TOP5_SECTOR_MODE and not universe:
        _rot_off = _rotation_offset(force_universe_refresh)
        _sec_uni, _sector_vol_by_ticker = _sector_ranked_universe(
            rotate=_SECTOR_ROTATE, per_sector=(_SECTOR_PER_SECTOR if _SECTOR_ROTATE else 0),
            offset=_rot_off)
        if _sec_uni:
            effective_universe = _sec_uni
            _sector_mode_active = True
            logger.info("[TOP5] SECTOR MODE: %d stocks from %d volatility-ranked sectors (rotate=%s, offset=%d)",
                        len(_sec_uni), len(set(_sector_vol_by_ticker.values())),
                        _SECTOR_ROTATE, _rot_off)
    if not _sector_mode_active:
        # Whole-market scan, ordered cache-first. _universe_size=0 (default) keeps the entire
        # NSE market; a positive value caps the scan for faster first results.
        effective_universe = _order_and_cap_scan(effective_universe, _universe_size)

    import concurrent.futures as _cf

    # ── Phase 1: signal-only 1D scan for candidate selection (no LLM) ─────────
    # Uses signals + ML score only — fast (2-5s/ticker cold, <1s cached), no LLM.
    # Scan on 1D (not 5D) so the short-term signal set (S1/S4/S8/S16/S_CTRIO…)
    # fires — top5 targets profitable INTRADAY/1D trades, so candidates are
    # ranked on short-horizon merit. LLM quota is preserved for Phase 2.
    # Worker count + deadline scale with universe size so a full-market scan can
    # cover the whole pool once the OHLCV cache is warm; on a cold cache it covers
    # as many as fit within the deadline and the cache warms over successive runs.
    phase1_start = time.time()
    scan_preds: dict[str, dict] = {}
    timeouts = 0
    _uni_n = max(1, len(effective_universe))
    scan_workers = min(16, _uni_n)
    # ~0.2s/ticker of wall-clock budget (warm cache, parallel), floored at 120s and
    # capped at 600s so a stuck run can never hang the background thread forever.
    scan_deadline = min(600, max(120, int(_uni_n * 0.2)))
    logger.info("[TOP5] PHASE 1 start: scanning %d stocks (workers=%d, deadline=%ds)",
                _uni_n, scan_workers, scan_deadline)
    _publish({
        "computing": True, "phase": "scanning",
        "scanned": 0, "scan_total": _uni_n, "picks": [], "generated_at": None,
        "message": f"Scanning the NSE market — 0/{_uni_n} stocks",
    })
    scan_ex = ThreadPoolExecutor(max_workers=scan_workers)
    scan_futs = {
        scan_ex.submit(_run_predict_with_ctx, ticker, "1D", None, False, False, True): ticker
        for ticker in effective_universe
    }
    scan_done_n = 0
    try:
        for f in _cf.as_completed(scan_futs, timeout=scan_deadline):
            ticker = scan_futs[f]
            try:
                _ticker, _tf, pred = f.result()
                scan_preds[_ticker] = pred
            except Exception as e:
                scan_preds[ticker] = {}
                if "timeout" in str(e).lower():
                    timeouts += 1
            scan_done_n += 1
            # Emit scan progress every 25 stocks so the UI + HF logs show a live counter.
            if scan_done_n % 25 == 0 or scan_done_n == _uni_n:
                logger.info("[TOP5] PHASE 1 progress: %d/%d scanned (%.0fs)",
                            scan_done_n, _uni_n, time.time() - phase1_start)
                _publish({
                    "computing": True, "phase": "scanning",
                    "scanned": scan_done_n, "scan_total": _uni_n,
                    "picks": [], "generated_at": None,
                    "message": f"Scanning the NSE market — {scan_done_n}/{_uni_n} stocks",
                })
    except _cf.TimeoutError:
        logger.info("[TOP5] PHASE 1 deadline (%ds) reached at %d/%d scanned",
                    scan_deadline, scan_done_n, _uni_n)
    # Cancel and account for any futures that never completed within the deadline.
    for f, ticker in scan_futs.items():
        if not f.done():
            f.cancel()
            if ticker not in scan_preds:
                scan_preds[ticker] = {}
                timeouts += 1
    scan_ex.shutdown(wait=False)

    phase1_elapsed = time.time() - phase1_start
    msg1 = f"[TOP5] PHASE 1 (signal scan, no LLM): {len(scan_preds)}/{len(effective_universe)} done, {timeouts} timeout, {phase1_elapsed:.1f}s"
    print(msg1)
    logger.info(msg1)

    # ── Composite short-term profit score ─────────────────────────────────────
    # Goal: rank stocks by expected short-horizon (INTRADAY/1D) profit. This is
    # the WITHIN-TIER tiebreak; confidence tier (below) is the primary sort.
    # Score components (all multiplicative on ret_hi so absolute return is preserved):
    #   conf_mult:    HIGH=1.0 / MEDIUM=0.80 / LOW=0.55
    #   ml_factor:    1 + (ml_probability - 0.5) × 0.30   → range [0.85, 1.15]
    #   rr_factor:    1 + 0.12 if actual_rr >= 2.0 else 0  (rewards good risk/reward)
    #   sector_factor: 1.12 if sector leading / 0.90 if sector lagging / 1.0 neutral
    # Backtest findings (research/backtest_top5.py + iter64/sweep on 1D):
    #   BEARISH direction accuracy = 38%, avg P&L = -0.42% → EXCLUDED.
    #   BULLISH HIGH-conf 1D = +0.86%/trade, 69% win; MEDIUM = +0.01% break-even.
    #   Ranking on 1D + confidence-tier vs old 5D-composite lifts realized 1D P&L
    #   +0.22% → +0.43%/trade and win rate 54% → 60% (iter64, top-5/date).
    # → only BULLISH, MEDIUM+ confidence, HIGH tier first, then ret_hi × ML × sector.
    _CONF_MULT = {"HIGH": 1.0, "MEDIUM": 0.80}
    _ACCEPTED_DIRECTIONS = {"BULLISH", "SLIGHTLY BULLISH"}

    def _score_tf(p: dict) -> float:
        """Composite ranking score for a qualified TF prediction. Higher is better.

        Volatility (ATR%) is the PRIMARY term — picks are ranked by how volatile the stock is.
        AI GATES the pick in _pick_best_tf (must be BULLISH/SLIGHTLY BULLISH, MEDIUM+ confidence,
        ret_hi>0); here confidence / ML / R:R / sector apply only a light multiplicative tilt so a
        stronger AI setup ranks above an equally-volatile weaker one. Falls back to AI ret_hi when
        ATR is missing so a pick is never scored zero purely for a missing ATR read.
        """
        price = float(p.get("price") or 0.0)
        atr14 = float((p.get("risk") or {}).get("atr14") or 0.0)
        atr_pct = (atr14 / price * 100.0) if price else 0.0
        base = atr_pct if atr_pct > 0 else float(p.get("ret_hi") or 0.0)

        conf = p.get("confidence", "LOW")
        conf_mult = _CONF_MULT.get(conf, 0.55)

        ml_prob = float((p.get("ml") or {}).get("probability") or 0.5)
        # Sector mode is AI-only: drop the ML feature-score multiplier. Otherwise apply the usual
        # small [0.85,1.15] tilt.
        ml_factor = 1.0 if _sector_mode_active else 1.0 + (ml_prob - 0.5) * 0.30

        risk_data = p.get("risk") or {}
        actual_rr = risk_data.get("actual_rr")
        rr_factor = 1.12 if (actual_rr is not None and actual_rr >= 2.0) else 1.0

        sector_data = p.get("sector") or {}
        if sector_data.get("leading"):
            sector_factor = 1.12
        elif sector_data.get("lagging"):
            sector_factor = 0.90
        else:
            sector_factor = 1.0

        score = base * conf_mult * ml_factor * rr_factor * sector_factor
        # SLIGHTLY BULLISH = downgraded from BULLISH (bear-market Nifty gate or weak signals).
        # Apply a 0.65× penalty so genuine BULLISH picks always rank higher for the same setup.
        if p.get("direction") == "SLIGHTLY BULLISH":
            score *= 0.65
        # When AI is unavailable, apply a heavy penalty — signal-strong stocks still
        # surface but rank below LLM-confirmed ones.
        if p.get("no_trade_reason") == "ai_unavailable":
            score *= 0.40
        return score

    # Phase 1 was signal-only (no AI), so direction = NEUTRAL for many stocks in
    # bear markets. Select candidates by ML probability + signal count instead of
    # direction — Phase 2 AI will assign the real direction.
    def _score_scan(p: dict) -> float:
        # Sector mode: rank purely by the stock's SECTOR volatility (most "violent" sectors
        # first), tie-broken by the stock's own ATR% — no ML score involved. AI picks from this
        # order in Phase 2.
        if _sector_mode_active:
            sv = float(_sector_vol_by_ticker.get(p.get("ticker"), 0.0))
            atr14 = (p.get("risk") or {}).get("atr14") or 0
            price = p.get("price") or 1
            atr_pct = (atr14 / price * 100) if price else 0
            return sv * 100.0 + atr_pct  # sector volatility dominates; stock ATR breaks ties
        ml_prob = float((p.get("ml") or {}).get("probability") or 0.5)
        sig_count = int((p.get("ml") or {}).get("signal_count") or
                        len(p.get("active_strategies") or []))
        sector_lead = 1.1 if (p.get("sector") or {}).get("leading") else 1.0
        # Volatility (ATR%) is the PRIMARY ranker — surface the most volatile movers across the
        # whole NSE market. ML probability + signal count + sector-leading apply only a light
        # multiplicative tilt so, among similarly-volatile names, one with supporting signals
        # ranks above one without.
        atr14 = (p.get("risk") or {}).get("atr14") or 0
        price = p.get("price") or 1
        atr_pct = atr14 / price * 100 if price else 0
        tilt = 1.0 + (ml_prob - 0.5) * 0.4 + min(sig_count, 5) * 0.04
        return atr_pct * tilt * sector_lead

    valid_scan = [p for p in scan_preds.values() if p and not p.get("error")]
    # Price band: keep stocks trading in (_TOP5_MIN_PRICE, _TOP5_MAX_PRICE] (₹) — excludes both
    # penny stocks (unreliable ATR%-driven noise) and unaffordably high-priced scrips.
    if _TOP5_MAX_PRICE and _TOP5_MAX_PRICE > 0:
        _pre_n = len(valid_scan)
        valid_scan = [p for p in valid_scan if 0 < (p.get("price") or 0) <= _TOP5_MAX_PRICE]
        if _pre_n != len(valid_scan):
            logger.info("[TOP5] PRICE CAP ≤₹%.0f: %d/%d candidates kept",
                        _TOP5_MAX_PRICE, len(valid_scan), _pre_n)
    if _TOP5_MIN_PRICE and _TOP5_MIN_PRICE > 0:
        _pre_n = len(valid_scan)
        valid_scan = [p for p in valid_scan if (p.get("price") or 0) >= _TOP5_MIN_PRICE]
        if _pre_n != len(valid_scan):
            logger.info("[TOP5] PENNY FLOOR ≥₹%.0f: %d/%d candidates kept",
                        _TOP5_MIN_PRICE, len(valid_scan), _pre_n)
    valid_scan.sort(key=_score_scan, reverse=True)

    # Volatility-ranked candidate pool for Phase 2. Phase 1 scanned the WHOLE market and ranked
    # every stock by ATR% (volatility); we hand only the top-K most volatile names to the AI so
    # LLM usage stays bounded while the pool is drawn from the entire NSE market. AI then confirms
    # direction on these (Phase 2), and sector diversity is applied to the final picks.
    _PHASE2_POOL = int(os.getenv("TOP5_PHASE2_POOL", "80") or "80")
    candidates = valid_scan[:_PHASE2_POOL] if (_PHASE2_POOL and _PHASE2_POOL > 0) else valid_scan

    # ── Phase 1b: ML conviction pass (standalone quantile model, no LLM) ──────
    # The ml_predictor is local + instant + rate-limit-free, so it can score the
    # market as a genuine SELECTOR (not just a display layer). We score the top
    # signal-ranked candidates, then BLEND: the candidate order fed to Phase 2 is
    # the interleaved union of the signal-top and the ML-top, so AI confirms BOTH
    # sets. ML predictions are stashed per ticker (closure) so _assemble can attach
    # them + compute an ML/AI agreement verdict. Bounded to _ML_SCAN_N + a deadline.
    # SKIPPED in sector mode — there ML is deliberately out of the selection path (AI-only).
    _ML_SCAN_N = 300
    ml_preds_by_ticker: dict[str, dict] = {}
    try:
        from ml_predictor.infer import get_ml_predictor
        _mlp = get_ml_predictor()
    except Exception:
        _mlp = None

    if (not _sector_mode_active and _mlp is not None
            and getattr(_mlp, "available", False) and candidates):
        ml_pool = candidates
        _publish({
            "computing": True, "phase": "scanning",
            "scanned": _uni_n, "scan_total": _uni_n, "picks": [], "generated_at": None,
            "message": f"ML scoring {len(ml_pool)} shortlisted candidates…",
        })

        def _ml_one(p: dict):
            tk = p.get("ticker")
            try:
                return tk, _mlp.predict_all_tf(tk, live_price=p.get("price"))
            except Exception:
                return tk, None

        ml_start = time.time()
        _ml_deadline = 120
        _ml_ex = ThreadPoolExecutor(max_workers=min(8, len(ml_pool)))
        _ml_futs = {_ml_ex.submit(_ml_one, p): p for p in ml_pool}
        try:
            for fut in _cf.as_completed(_ml_futs, timeout=_ml_deadline):
                tk, res = fut.result()
                if res and res.get("available"):
                    ml_preds_by_ticker[tk] = res
        except _cf.TimeoutError:
            logger.info("[TOP5] PHASE 1b ML deadline (%ds) reached", _ml_deadline)
        for fut in _ml_futs:
            if not fut.done():
                fut.cancel()
        _ml_ex.shutdown(wait=False)
        logger.info("[TOP5] PHASE 1b (ML conviction): scored %d/%d in %.1fs",
                    len(ml_preds_by_ticker), len(ml_pool), time.time() - ml_start)

    # `candidates` stays strictly volatility-ranked (set above): the user wants the most volatile
    # stocks surfaced, so Phase 2 AI confirms direction on the top-volatility pool in that order.
    # ML predictions (ml_preds_by_ticker) are still attached per stock in _assemble for the
    # ML/AI-agreement verdict, but they no longer reorder the pool.

    market_from_scan = next((p.get("market", {}) for p in scan_preds.values() if p and p.get("market")), {})
    shared_ctx = {
        "vix_level": market_from_scan.get("vix_level", 18.0),
        "vix_label": market_from_scan.get("vix_label", "UNKNOWN — assume moderate"),
        "nifty_ok": market_from_scan.get("nifty_ok", True),
        "nifty_label": market_from_scan.get("nifty_label", ""),
        "macro_ok": market_from_scan.get("macro_ok", True),
        "macro_label": market_from_scan.get("macro_label", ""),
    } if market_from_scan else None

    if not candidates:
        return {
            "picks": [],
            "market": market_from_scan,
            "no_picks_reason": "No scan results available — universe fetch or OHLCV data failed",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    # ATR multipliers and R:R targets per timeframe (must match predictor_core.py)
    _ATR_MULT = {"INTRADAY": 0.4, "1D": 0.7, "3D": 1.1, "5D": 1.5}
    _RR_MULT  = {"INTRADAY": 1.2, "1D": 1.5, "3D": 1.7, "5D": 2.0}

    def _derive_risk(price, atr14, tf):
        """Derive SL/target from ATR when AI response risk fields are missing."""
        if not price or not atr14 or tf not in _ATR_MULT:
            return None, None, None
        sl_risk  = _ATR_MULT[tf] * atr14
        sl_price = round(price - sl_risk, 2)
        sl_pct   = round(sl_risk / price * 100, 1)
        sl_tgt   = round(price + sl_risk * _RR_MULT[tf], 2)
        return sl_price, sl_pct, sl_tgt

    # For shortlisted top picks, compute full-debate AI predictions for all TFs.
    # 5D is re-run with full debate (not reused from the fast-mode scan) so all
    # three timeframe tabs on the card have consistent, high-quality forecasts.
    ai_jobs: list[tuple[str, str]] = []
    for stock in candidates:
        ticker = stock["ticker"]
        for tf in TIMEFRAMES:
            ai_jobs.append((ticker, tf))

    def _empty_ai_tf(price_val: float, reason: str = "ai_unavailable") -> dict:
        """Represent an unavailable/pending AI forecast for a timeframe cell.

        reason="pending" is used for partial (streaming) snapshots while Phase 2 is
        still running — the frontend renders a spinner for those cells. The FINAL
        result uses reason="ai_unavailable" for any TF that never resolved.
        """
        return {
            "expected_return_range": None,
            "midpoint": 0,
            "ret_lo": None,
            "ret_hi": None,
            "target_price_lo": None,
            "target_price_hi": None,
            "expected_target_price": None,
            "expected_entry_price": price_val,
            "direction": "NO TRADE",
            "confidence": "LOW",
            "no_trade_reason": reason,
            "signal_count": 0,
            "predicted_direction": None,
            "predicted_return_lo": None,
            "predicted_return_hi": None,
            "ai_forecast": None,
            "risk": {},
        }

    # Rank across the shown timeframes — volatility-primary (see _pick_best_tf).
    _RANK_TFS = ["INTRADAY", "1D"]

    def _pick_best_tf(ticker: str) -> tuple[str, float]:
        """Return the best short-term TF (INTRADAY/1D) and its VOLATILITY-primary ranking score.

        AI GATES the pick: the TF must be a resolved BULLISH / SLIGHTLY BULLISH call with MEDIUM+
        confidence and a positive best-case return. Among qualified TFs, the one with the higher
        volatility-primary composite (_score_tf — ATR% × AI-confidence/ML/R:R/sector tilt) wins,
        and that score is used to rank stocks against each other, so the most volatile AI-approved
        movers surface first. Returns ("1D", 0.0) when the stock has no eligible short-term setup
        so it sinks to the bottom of the ranking.
        """
        best, best_score = None, 0.0
        for tf in _RANK_TFS:
            pred = ai_preds.get((ticker, tf), {})
            if not pred or pred.get("error"):
                continue
            if pred.get("no_trade_reason"):
                continue
            if pred.get("direction") not in _ACCEPTED_DIRECTIONS:
                continue
            if pred.get("confidence") not in _CONF_MULT:
                continue
            ret_hi = float(pred.get("ret_hi") or 0.0)
            if ret_hi <= 0:
                continue
            s = _score_tf(pred)
            if s > best_score:
                best, best_score = tf, s
        if best is None:
            return "1D", 0.0
        # Sector mode: tilt the score by the stock's SECTOR volatility so that among AI-approved
        # picks, ones in more "violent" sectors rank higher. +10% per 1% sector ATR, capped at +50%.
        if _sector_mode_active:
            sv = float(_sector_vol_by_ticker.get(ticker, 0.0))
            best_score *= 1.0 + min(sv, 5.0) * 0.10
        return best, best_score

    def _assemble(partial: bool = False) -> list[dict]:
        """Assemble ranked pick cards from candidates + whatever AI predictions exist.

        Reused for both the final result (partial=False) and the streaming progress
        snapshots emitted during Phase 2 (partial=True). During a partial pass, a TF
        whose AI job hasn't finished yet is marked no_trade_reason="pending" (renders
        as a spinner) and only stocks that already have a qualifying resolved setup
        are surfaced — so cards appear as soon as they're ready instead of all at once.
        """
        _missing_reason = "pending" if partial else "ai_unavailable"
        assembled: list[dict] = []
        for stock in candidates:
            ticker = stock["ticker"]
            price = stock.get("price") or 0
            anchor_atr14 = ((ai_preds.get((ticker, "1D"), {}).get("risk") or {}).get("atr14")
                            or (ai_preds.get((ticker, "INTRADAY"), {}).get("risk") or {}).get("atr14"))
            timeframe_data: dict[str, dict] = {}
            ml_res = ml_preds_by_ticker.get(ticker)
            ml_tfs = (ml_res.get("tfs", {}) if (ml_res and ml_res.get("available")) else {}) or {}

            for tf in TIMEFRAMES:
                base_stock = ai_preds.get((ticker, tf), {})
                if not base_stock or base_stock.get("error"):
                    base_stock = _empty_ai_tf(price, _missing_reason)

                tf_risk = base_stock.get("risk", {}) or {}
                sl = tf_risk.get("stop_loss")
                tgt = tf_risk.get("min_target")
                sl_pct = tf_risk.get("stop_loss_pct")
                actual_rr = tf_risk.get("actual_rr")
                if sl is None and anchor_atr14:
                    sl, sl_pct, tgt = _derive_risk(price, anchor_atr14, tf)
                    pred_ret_hi = base_stock.get("ret_hi")
                    if pred_ret_hi and pred_ret_hi > 0 and price > 0:
                        tgt = round(price * (1 + pred_ret_hi / 100), 2)

                timeframe_data[tf] = {
                    "expected_return_range": base_stock.get("expected_return_range"),
                    "midpoint":     base_stock.get("midpoint", 0),
                    "ret_lo":       base_stock.get("ret_lo"),
                    "ret_hi":       base_stock.get("ret_hi"),
                    "target_price_lo": base_stock.get("target_price_lo"),
                    "target_price_hi": base_stock.get("target_price_hi"),
                    "expected_target_price": base_stock.get("expected_target_price"),
                    "expected_entry_price": base_stock.get("expected_entry_price", price),
                    "gapped_past_target": base_stock.get("gapped_past_target", False),
                    "direction":    base_stock.get("direction", "NO TRADE"),
                    "confidence":   base_stock.get("confidence", "LOW"),
                    "no_trade_reason":    base_stock.get("no_trade_reason"),
                    "range_bound":        base_stock.get("range_bound", False),
                    "signal_count":       0,
                    "predicted_direction":    base_stock.get("predicted_direction"),
                    "predicted_return_lo":    base_stock.get("predicted_return_lo"),
                    "predicted_return_hi":    base_stock.get("predicted_return_hi"),
                    "ai_forecast":            base_stock.get("ai_forecast"),
                    "ml":                     _slim_ml_tf(ml_tfs.get(tf)),
                    "stop_loss":     sl,
                    "stop_loss_pct": sl_pct,
                    "min_target":    tgt,
                    "actual_rr":     actual_rr,
                }

            pick = dict(stock)
            best_tf, best_score = _pick_best_tf(ticker)
            pick["best_tf"] = best_tf
            ai_anchor = ai_preds.get((ticker, best_tf), {})
            if ai_anchor and not ai_anchor.get("error"):
                pick["direction"] = ai_anchor.get("direction", pick.get("direction"))
                pick["confidence"] = ai_anchor.get("confidence", pick.get("confidence"))
                pick["news"] = ai_anchor.get("news", pick.get("news", {}))
                pick["risk"] = ai_anchor.get("risk", pick.get("risk", {}))
            pick["signals"] = {}
            pick["signal_count"] = 0
            pick["timeframes"] = timeframe_data

            # ── ML/AI agreement verdict (AI confirms the ML selection, or not) ──
            # ml_selected = this stock was scored by the ML selector this run.
            # Verdict on the best timeframe: confirmed (same dir) → boost so it
            # surfaces; disagree (opposite dir) → kept but flagged; mixed → neutral.
            pick["ml_selected"] = ticker in ml_preds_by_ticker
            ml_best = _slim_ml_tf(ml_tfs.get(best_tf))
            ai_best_dir = (ai_preds.get((ticker, best_tf), {}) or {}).get("direction")
            pick["ml_ai_verdict"] = None
            if ml_best and ml_best.get("direction") and ai_best_dir:
                m = str(ml_best["direction"]).upper()
                a = str(ai_best_dir).upper()
                if m == a and m in ("BULLISH", "BEARISH"):
                    pick["ml_ai_verdict"] = "confirmed"
                    best_score *= 1.10  # reward ML+AI consensus so it ranks higher
                elif (m == "BULLISH" and a == "BEARISH") or (m == "BEARISH" and a == "BULLISH"):
                    pick["ml_ai_verdict"] = "disagree"
                elif m in ("BULLISH", "BEARISH") and a in ("BULLISH", "BEARISH", "NEUTRAL"):
                    pick["ml_ai_verdict"] = "mixed"
            pick["_score_best"] = best_score
            assembled.append(pick)

        assembled.sort(key=lambda x: x.get("_score_best", 0.0), reverse=True)
        qualifying = [p for p in assembled if p.get("_score_best", 0) > 0]
        # Partial snapshots only show already-qualifying cards (progressive reveal);
        # the final result falls back to the raw list if nothing qualifies. Sector diversity
        # spreads the final picks across NSE sectors so one hot sector can't fill the whole list.
        base_pool = qualifying if (qualifying or partial) else assembled
        result_picks = _diversify_by_sector(base_pool, top_n, _MAX_PER_SECTOR)

        for i, p in enumerate(result_picks):
            p["rank"] = i + 1
            p.pop("_score_best", None)
            if not partial:
                # Specialist lookup hits the DB — skip it on partial (streaming) passes.
                specialist = _get_specialist_recommendation(p.get("ticker", ""))
                if specialist:
                    p["specialist_recommendation"] = specialist
        return result_picks

    # ── Phase 2: AI fast-mode predictions for top candidates (150s cap) ────────

    # Uses fast-mode (1 LLM call per ticker shared across TFs) instead of full
    # debate (4 LLM calls) — 4× fewer LLM calls while giving the same AI direction.
    ai_preds: dict[tuple[str, str], dict] = {}  # all TFs filled by Step 2
    phase2_start = time.time()
    phase2_elapsed = 0
    phase2_timeouts = 0

    # Degraded-mode: when all cloud providers are daily-exhausted, Ollama is the
    # sole fallback (semaphore=1, ~90s/call). 150 stocks × 3 TFs = 450 sequential
    # Ollama calls ≈ 11 hours — impossible in any deadline. Instead, promote Phase 1
    # signal+ML results (which already have direction/confidence/ret_lo/ret_hi) to
    # the 1D slot so stocks surface with real directional calls. INTRADAY and 3D
    # show "AI unavailable". Picks are signal-quality, not debate-quality, but
    # infinitely better than zero picks.
    try:
        from llm_client import _all_cloud_daily_exhausted as _cloud_exhausted
        _p2_degraded = _cloud_exhausted()
    except Exception:
        _p2_degraded = False

    if _p2_degraded and ai_jobs:
        for stock in candidates:
            ticker = stock["ticker"]
            p1 = scan_preds.get(ticker, {})
            if p1 and not p1.get("error") and p1.get("direction") in _ACCEPTED_DIRECTIONS:
                ai_preds[(ticker, "1D")] = p1  # real signal+ML data
            # INTRADAY and 3D slots left empty → _empty_ai_tf() below
        ai_jobs = []
        msg2 = f"[TOP5] PHASE 2 DEGRADED (cloud daily-exhausted): promoted Phase 1 data for {len(ai_preds)} stocks"
        print(msg2)
        logger.info(msg2)

    elif ai_jobs:
        logger.info("[TOP5] PHASE 2 start: %d candidates × %d TFs = %d AI jobs",
                    len(candidates), len(TIMEFRAMES), len(ai_jobs))
        _publish({
            "computing": True, "phase": "predicting",
            "predicted": 0, "predict_total": len(ai_jobs), "candidates": len(candidates),
            "picks": [], "market": market_from_scan, "generated_at": None,
            "message": f"Running AI on {len(candidates)} candidates — 0/{len(ai_jobs)}",
        })
        phase2_ex = ThreadPoolExecutor(max_workers=min(len(candidates), 6) * len(TIMEFRAMES))
        p2_futs = {
            phase2_ex.submit(_run_predict_with_ctx, ticker, tf, shared_ctx, True, True): (ticker, tf)
            for ticker, tf in ai_jobs
        }
        p2_done_n = 0
        _last_emit = time.time()
        try:
            for f in _cf.as_completed(p2_futs, timeout=150):
                ticker, tf = p2_futs[f]
                try:
                    _ticker, _tf, pred = f.result()
                    ai_preds[(_ticker, _tf)] = pred
                except Exception as e:
                    ai_preds[(ticker, tf)] = {}
                    if "timeout" in str(e).lower():
                        phase2_timeouts += 1
                p2_done_n += 1
                # Stream partial ranked picks so ready cards render immediately —
                # emit every 6 completions or at least every 4s, whichever first.
                if progress_cb and (p2_done_n % 6 == 0 or time.time() - _last_emit > 4):
                    _last_emit = time.time()
                    _partial = _assemble(partial=True)
                    logger.info("[TOP5] PHASE 2 progress: %d/%d jobs done, %d cards ready (%.0fs)",
                                p2_done_n, len(ai_jobs), len(_partial), time.time() - phase2_start)
                    _publish({
                        "computing": True, "phase": "predicting",
                        "predicted": p2_done_n, "predict_total": len(ai_jobs),
                        "candidates": len(candidates), "picks": _partial,
                        "market": market_from_scan, "generated_at": None,
                        "message": f"Running AI on candidates — {p2_done_n}/{len(ai_jobs)} ({len(_partial)} ready)",
                    })
        except _cf.TimeoutError:
            logger.info("[TOP5] PHASE 2 deadline (150s) reached at %d/%d jobs", p2_done_n, len(ai_jobs))
        # Cancel and account for any jobs that never completed within the deadline.
        for f, key in p2_futs.items():
            if not f.done():
                f.cancel()
                if key not in ai_preds:
                    ai_preds[key] = {}
                    phase2_timeouts += 1
        phase2_ex.shutdown(wait=False)
        phase2_elapsed = time.time() - phase2_start
        msg2 = f"[TOP5] PHASE 2 (AI fast): {len(ai_preds)}/{len(ai_jobs)} done, {phase2_timeouts} timeout, {phase2_elapsed:.1f}s"
        print(msg2)
        logger.info(msg2)

    # Step 3: Assemble the final ranked picks (partial=False → any still-missing TF
    # is marked ai_unavailable, and specialist recommendations are attached).
    picks = _assemble(partial=False)

    total_elapsed = time.time() - start_time
    msg_final = f"[TOP5] TOTAL time: {total_elapsed:.1f}s | Phase1: {phase1_elapsed:.1f}s | Phase2: {phase2_elapsed:.1f}s | {len(picks)} picks generated"
    print(msg_final)
    logger.info(msg_final)

    return {
        "picks": picks,
        "market": market_from_scan,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "_timing": {
            "phase1_sec": round(phase1_elapsed, 1),
            "phase2_sec": round(phase2_elapsed if ai_jobs else 0, 1),
            "total_sec": round(total_elapsed, 1),
            "phase1_timeouts": timeouts,
            "phase1_stocks": len(scan_preds),
            "phase2_jobs": len(ai_jobs),
        }
    }


def get_weekly_picks(
    universe: Optional[list[str]] = None,
    top_n: int = 20,
    _universe_size: int = 150,
    force_universe_refresh: bool = False,
) -> dict:
    """
    Top N NSE stocks for a 5-10 day (1W) hold. Mirrors get_top5_picks() but anchors
    on the 1W timeframe and applies stricter R:R requirements suitable for longer holds.

    Returns same structure as get_top5_picks() with timeframes: {"3D", "5D", "1W"}.
    """
    from datetime import datetime

    _WEEKLY_TIMEFRAMES = ["3D", "5D", "1W"]
    _W_ATR_MULT = {"3D": 1.1, "5D": 1.5, "1W": 1.8}
    _W_RR_MULT  = {"3D": 1.7, "5D": 2.0, "1W": 2.5}

    effective_universe = universe or _get_top5_universe(force_refresh=force_universe_refresh) or DEFAULT_UNIVERSE
    effective_universe = effective_universe[:_universe_size] if _universe_size > 0 else effective_universe

    # Step 1: 1W AI scan for candidate selection
    scan_preds: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=min(20, max(1, len(effective_universe)))) as executor:
        futures = {
            executor.submit(_run_predict_with_ctx, ticker, "1W", None, True, True): ticker
            for ticker in effective_universe
        }
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                _ticker, _tf, pred = future.result(timeout=90)
                scan_preds[_ticker] = pred
            except Exception:
                scan_preds[ticker] = {}

    # Scoring — same formula as _score_5d but anchored on 1W ret_hi
    _W_CONF_MULT = {"HIGH": 1.0, "MEDIUM": 0.80}   # exclude LOW (only 84% hit rate)
    _W_ACCEPTED_DIRECTIONS = {"BULLISH", "SLIGHTLY BULLISH"}
    # _W_MIN_RET_HI / _W_MIN_RR removed — calibrated ret_hi (0.18%) is far below any
    # meaningful magnitude threshold; scoring handles ranking instead.

    def _score_1w(p: dict) -> float:
        ret_hi_val = float(p.get("ret_hi") or 0.0)
        conf_mult = _W_CONF_MULT.get(p.get("confidence", "LOW"), 0.55)
        ml_prob = float((p.get("ml") or {}).get("probability") or 0.5)
        ml_factor = 1.0 + (ml_prob - 0.5) * 0.30
        actual_rr = (p.get("risk") or {}).get("actual_rr")
        rr_factor = 1.12 if (actual_rr is not None and actual_rr >= 2.0) else 1.0
        sector_data = p.get("sector") or {}
        sector_factor = 1.12 if sector_data.get("leading") else (0.90 if sector_data.get("lagging") else 1.0)
        atr14 = (p.get("risk") or {}).get("atr14") or 0
        price = p.get("price") or 1
        atr_pct = atr14 / price * 100 if price else 0
        vol_factor = 1.0 + min(atr_pct / 4.0, 0.5)
        score = ret_hi_val * conf_mult * ml_factor * rr_factor * sector_factor * vol_factor
        if p.get("direction") == "SLIGHTLY BULLISH":
            score *= 0.65
        if p.get("no_trade_reason") == "ai_unavailable":
            score *= 0.40
        return score

    bullish = []
    for p in scan_preds.values():
        if not p or p.get("direction") not in _W_ACCEPTED_DIRECTIONS:
            continue
        if p.get("confidence") not in _W_CONF_MULT:
            continue
        if float(p.get("ret_hi") or 0.0) <= 0:
            continue
        bullish.append(p)

    bullish.sort(key=_score_1w, reverse=True)
    candidates = bullish

    market_from_scan = next((p.get("market", {}) for p in scan_preds.values() if p and p.get("market")), {})
    shared_ctx = {
        "vix_level": market_from_scan.get("vix_level", 18.0),
        "vix_label": market_from_scan.get("vix_label", "UNKNOWN — assume moderate"),
        "nifty_ok": market_from_scan.get("nifty_ok", True),
        "nifty_label": market_from_scan.get("nifty_label", ""),
        "macro_ok": market_from_scan.get("macro_ok", True),
        "macro_label": market_from_scan.get("macro_label", ""),
    } if market_from_scan else None

    if not candidates:
        return {
            "picks": [],
            "market": market_from_scan,
            "no_picks_reason": "No bullish 1W setups available in current market conditions",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    # Step 2: Re-predict 3D/5D for top candidates using shared market context
    def _derive_risk_weekly(price, atr14, tf):
        if not price or not atr14:
            return None, None, None
        sl_risk  = _W_ATR_MULT[tf] * atr14
        sl_price = round(price - sl_risk, 2)
        sl_pct   = round(sl_risk / price * 100, 1)
        sl_tgt   = round(price + sl_risk * _W_RR_MULT[tf], 2)
        return sl_price, sl_pct, sl_tgt

    ai_jobs = [(s["ticker"], tf) for s in candidates for tf in _WEEKLY_TIMEFRAMES if tf != "1W"]
    ai_preds: dict[tuple[str, str], dict] = {(s["ticker"], "1W"): s for s in candidates}
    if ai_jobs:
        with ThreadPoolExecutor(max_workers=min(8, len(ai_jobs))) as executor:
            futures = {
                executor.submit(_run_predict_with_ctx, ticker, tf, shared_ctx, True, False): (ticker, tf)
                for ticker, tf in ai_jobs
            }
            for future in as_completed(futures):
                ticker, tf = futures[future]
                try:
                    _ticker, _tf, pred = future.result(timeout=90)
                    ai_preds[(_ticker, _tf)] = pred
                except Exception:
                    ai_preds[(ticker, tf)] = {}

    def _empty_weekly_tf(price_val: float) -> dict:
        return {
            "expected_return_range": None, "midpoint": 0,
            "ret_lo": None, "ret_hi": None,
            "target_price_lo": None, "target_price_hi": None,
            "expected_target_price": None, "expected_entry_price": price_val,
            "direction": "NO TRADE", "confidence": "LOW",
            "no_trade_reason": "ai_unavailable", "signal_count": 0,
            "predicted_direction": None, "predicted_return_lo": None,
            "predicted_return_hi": None, "ai_forecast": None, "risk": {},
        }

    picks = []
    for stock in candidates:
        ticker  = stock["ticker"]
        price   = stock.get("price") or 0
        anchor_atr14 = (ai_preds.get((ticker, "1W"), {}).get("risk") or {}).get("atr14")
        timeframe_data: dict[str, dict] = {}

        for tf in _WEEKLY_TIMEFRAMES:
            base_stock = ai_preds.get((ticker, tf), {})
            if not base_stock or base_stock.get("error"):
                base_stock = _empty_weekly_tf(price)

            tf_risk = base_stock.get("risk", {}) or {}
            sl = tf_risk.get("stop_loss")
            tgt = tf_risk.get("min_target")
            sl_pct = tf_risk.get("stop_loss_pct")
            actual_rr = tf_risk.get("actual_rr")
            if sl is None and anchor_atr14:
                sl, sl_pct, tgt = _derive_risk_weekly(price, anchor_atr14, tf)
                pred_ret_hi = base_stock.get("ret_hi")
                if pred_ret_hi and pred_ret_hi > 0 and price > 0:
                    tgt = round(price * (1 + pred_ret_hi / 100), 2)

            timeframe_data[tf] = {
                "expected_return_range": base_stock.get("expected_return_range"),
                "midpoint":     base_stock.get("midpoint", 0),
                "ret_lo":       base_stock.get("ret_lo"),
                "ret_hi":       base_stock.get("ret_hi"),
                "target_price_lo": base_stock.get("target_price_lo"),
                "target_price_hi": base_stock.get("target_price_hi"),
                "expected_target_price": base_stock.get("expected_target_price"),
                "expected_entry_price": base_stock.get("expected_entry_price", price),
                "direction":    base_stock.get("direction", "NO TRADE"),
                "confidence":   base_stock.get("confidence", "LOW"),
                "no_trade_reason":    base_stock.get("no_trade_reason"),
                "range_bound":        base_stock.get("range_bound", False),
                "signal_count":       0,
                "predicted_direction":    base_stock.get("predicted_direction"),
                "predicted_return_lo":    base_stock.get("predicted_return_lo"),
                "predicted_return_hi":    base_stock.get("predicted_return_hi"),
                "ai_forecast":            base_stock.get("ai_forecast"),
                "stop_loss":     sl,
                "stop_loss_pct": sl_pct,
                "min_target":    tgt,
                "actual_rr":     actual_rr,
            }

        pick = dict(stock)
        ai_anchor = ai_preds.get((ticker, "1W"), {})
        if ai_anchor and not ai_anchor.get("error"):
            pick["direction"] = ai_anchor.get("direction", pick.get("direction"))
            pick["confidence"] = ai_anchor.get("confidence", pick.get("confidence"))
            pick["news"] = ai_anchor.get("news", pick.get("news", {}))
            pick["risk"] = ai_anchor.get("risk", pick.get("risk", {}))
        pick["signals"] = {}
        pick["signal_count"] = 0
        pick["timeframes"] = timeframe_data
        pick["_score_1w"] = _score_1w(ai_anchor if (ai_anchor and not ai_anchor.get("error")) else stock)
        picks.append(pick)

    picks.sort(key=lambda x: x.get("_score_1w", 0.0), reverse=True)
    picks = picks[:top_n]
    for i, p in enumerate(picks):
        p["rank"] = i + 1
        p.pop("_score_1w", None)

    return {
        "picks": picks,
        "market": market_from_scan,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
