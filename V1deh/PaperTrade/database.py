#!/usr/bin/env python3
"""
database.py — SQLite persistence layer for the paper trading platform.

Tables: watchlist, trades, signal_accuracy
DB file: paper_trading.db in the project directory
"""

import sqlite3
import os
import shutil
import threading
import time
from datetime import datetime, timezone
from typing import Optional

def _data_dir() -> str:
    """Return persistent data directory. Uses /data on HF Spaces, else project root."""
    hf_data = "/data"
    if os.path.isdir(hf_data) and os.access(hf_data, os.W_OK):
        return hf_data
    return os.path.dirname(os.path.abspath(__file__))


DB_PATH = os.path.join(_data_dir(), "paper_trading.db")

# Calibrated snapshot ranges (must match ai_forecast._BULL_RANGE / _BEAR_RANGE / _NEUT_RANGE).
# These are applied in save_prediction_snapshot() so the DB stores what the backtest measures,
# not the wide AI-generated estimates which are already in snapshot_data JSON.
# INTRADAY entries MUST match ai_forecast._BULL_RANGE/_BEAR_RANGE/_NEUT_RANGE["INTRADAY"].
# Cost-clearing floors — MUST match ai_forecast._BULL_RANGE/_BEAR_RANGE/_NEUT_RANGE.
_SNAP_BULL = {"INTRADAY": (0.15, 1.00), "1D": (0.25, 1.30), "3D": (0.30, 2.20), "5D": (0.40, 3.00)}
_SNAP_BEAR = {"INTRADAY": (-1.00, -0.15), "1D": (-1.30, -0.25), "3D": (-2.20, -0.30), "5D": (-3.00, -0.40)}
_SNAP_NEUT = {"INTRADAY": (-0.50, 0.50), "1D": (-1.5, 1.5), "3D": (-1.0, 1.0), "5D": (-1.0, 1.0)}


def _calibrated_snap_range(direction: str, timeframe: str, current_price: float):
    """Return (target_price_lo, target_price_hi) using calibrated % ranges."""
    d = (direction or "NEUTRAL").upper()
    tf = timeframe if timeframe in _SNAP_BULL else "1D"
    if d in ("BULLISH", "SLIGHTLY BULLISH"):
        lo_pct, hi_pct = _SNAP_BULL[tf]
    elif d == "BEARISH":
        lo_pct, hi_pct = _SNAP_BEAR[tf]
    else:
        lo_pct, hi_pct = _SNAP_NEUT[tf]
    return (
        round(current_price * (1 + lo_pct / 100), 2),
        round(current_price * (1 + hi_pct / 100), 2),
    )

# --- HF Hub persistence (for HF Spaces free tier which has no persistent /data) ---

_HF_REPO_ID = os.environ.get("HF_DATA_REPO_ID", "V1deh/papertrade-data")
_HF_FILENAME = "paper_trading.db"
_BACKUP_INTERVAL = 300  # upload every 5 minutes


def _hf_token():
    return os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")


def _hf_ensure_repo(token):
    try:
        from huggingface_hub import HfApi
        HfApi().create_repo(
            repo_id=_HF_REPO_ID,
            repo_type="dataset",
            private=True,
            token=token,
            exist_ok=True,
        )
    except Exception:
        pass


def _clear_journal_siblings(db_path: str) -> None:
    """Remove -wal/-shm siblings so a fresh main DB is never paired with a stale journal."""
    for _ext in ("-wal", "-shm"):
        try:
            os.remove(db_path + _ext)
        except OSError:
            pass


def _hf_download_db():
    token = _hf_token()
    if not token:
        return
    try:
        from huggingface_hub import hf_hub_download
        # Only ensure repo exists on first-ever run; skip the extra round-trip on warm restarts.
        if not os.path.exists(DB_PATH):
            _hf_ensure_repo(token)
        local = hf_hub_download(
            repo_id=_HF_REPO_ID,
            filename=_HF_FILENAME,
            repo_type="dataset",
            token=token,
            force_download=True,  # always fetch latest; stale cache causes malformed-image errors
        )
        # Clear any stale -wal/-shm from the previous container BEFORE and AFTER overwriting the
        # main file. Pairing a freshly downloaded main DB with a leftover journal makes SQLite
        # replay an old WAL onto a different image → "database disk image is malformed".
        _clear_journal_siblings(DB_PATH)
        shutil.copy2(local, DB_PATH)
        _clear_journal_siblings(DB_PATH)
        print(f"[DB] Restored from HF Hub → {DB_PATH}", flush=True)
    except Exception as e:
        print(f"[DB] HF download skipped ({e})", flush=True)


def _atomic_snapshot(dest: str) -> bool:
    """Write a consistent snapshot of the live DB to `dest` via checkpoint + VACUUM INTO.

    Uploading the live file mid-write (the old behaviour) captured torn pages → malformed
    restores. wal_checkpoint folds the WAL into the main file; VACUUM INTO then produces an
    atomic, self-consistent copy safe to upload while writers continue.
    """
    try:
        if os.path.exists(dest):
            os.remove(dest)
        with _conn() as c:
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            c.execute("VACUUM INTO ?", (dest,))
        return os.path.exists(dest)
    except Exception as e:
        print(f"[DB] snapshot failed ({e})", flush=True)
        return False


def _backup_enabled() -> bool:
    """Only the real HF Space should back the DB up to the shared Hub repo.

    Otherwise a stray local `python app.py` that has the production HF_TOKEN in .env will
    also run the backup loop and clobber the Space's data (multi-writer race → data loss).
    HF Spaces always set SPACE_ID / SPACE_HOST. Set FORCE_DB_BACKUP=1 to override for a
    single, intentional non-Space writer.
    """
    if os.environ.get("FORCE_DB_BACKUP") == "1":
        return True
    return bool(os.environ.get("SPACE_ID") or os.environ.get("SPACE_HOST"))


def hf_upload_db():
    if not _backup_enabled():
        return
    token = _hf_token()
    if not token or not os.path.exists(DB_PATH):
        return
    snap = DB_PATH + ".backup"
    upload_path = snap if _atomic_snapshot(snap) else DB_PATH  # fall back to live file if snapshot fails
    try:
        from huggingface_hub import HfApi
        HfApi().upload_file(
            path_or_fileobj=upload_path,
            path_in_repo=_HF_FILENAME,
            repo_id=_HF_REPO_ID,
            repo_type="dataset",
            token=token,
            commit_message="auto-backup",
        )
        print("[DB] Backed up to HF Hub", flush=True)
    except Exception as e:
        print(f"[DB] HF upload failed ({e})", flush=True)
    finally:
        if upload_path == snap:
            try:
                os.remove(snap)
            except OSError:
                pass


def _backup_loop():
    while True:
        time.sleep(_BACKUP_INTERVAL)
        hf_upload_db()


def _checkpoint_on_exit():
    """Fold the WAL into the main DB on clean shutdown so no uncheckpointed -wal is left behind
    (a leftover -wal replayed against a restored main file is the malformed-image trigger)."""
    try:
        with _conn() as c:
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        pass


def setup_hf_persistence():
    """Download DB from HF Hub on startup; start background upload thread."""
    _hf_download_db()
    import atexit
    atexit.register(_checkpoint_on_exit)
    if not _backup_enabled():
        print("[DB] Backup loop disabled (not an HF Space; set FORCE_DB_BACKUP=1 to override). "
              "Startup restore still ran; this instance will NOT upload to HF Hub.", flush=True)
        return
    threading.Thread(target=_backup_loop, daemon=True).start()


def _conn() -> sqlite3.Connection:
    # timeout + busy_timeout give writers 5s to wait out a lock instead of erroring immediately
    # (Flask is threaded and several background daemons write concurrently). synchronous=NORMAL is
    # the safe WAL pairing. These reduce the lock-contention + torn-write surface behind corruption.
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db() -> None:
    """Create tables if they don't exist. Called on app startup."""
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS watchlist (
                ticker   TEXT PRIMARY KEY,
                name     TEXT,
                added_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker      TEXT NOT NULL,
                name        TEXT,
                direction   TEXT CHECK(direction IN ('LONG','SHORT')),
                order_type  TEXT DEFAULT 'MARKET' CHECK(order_type IN ('MARKET','LIMIT')),
                entry_price REAL NOT NULL,
                shares      INTEGER NOT NULL,
                stop_loss   REAL,
                target      REAL,
                strategy    TEXT,
                timeframe   TEXT,
                prediction_data TEXT,
                opened_at   TEXT DEFAULT (datetime('now')),
                closed_at   TEXT,
                exit_price  REAL,
                status      TEXT DEFAULT 'OPEN' CHECK(status IN ('OPEN','CLOSED','PENDING','CANCELLED')),
                pnl         REAL,
                pnl_pct     REAL,
                notes       TEXT,
                live_price_at_entry REAL,
                price_deviation_pct REAL,
                merged_into_trade_id INTEGER,
                merge_confirmed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS signal_accuracy (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                signal    TEXT,
                timeframe TEXT,
                won       INTEGER,
                pnl_pct   REAL,
                logged_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS prediction_snapshots (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker          TEXT NOT NULL,
                timeframe       TEXT NOT NULL,
                direction       TEXT,
                confidence      TEXT,
                target_price_lo REAL,
                target_price_hi REAL,
                predicted_return_lo REAL,
                predicted_return_hi REAL,
                current_price   REAL,
                snapshot_source TEXT,
                created_at      TEXT DEFAULT (datetime('now')),
                snapshot_data   TEXT,
                validation_target_date TEXT,
                validation_status TEXT DEFAULT 'PENDING' CHECK(validation_status IN ('PENDING', 'EXPIRED', 'VALIDATED')),
                validation_result TEXT CHECK(validation_result IN ('HIT', 'MISS', NULL)),
                actual_price_at_validation REAL,
                actual_return_at_validation REAL,
                window_high     REAL,
                window_low      REAL,
                hit_grade       TEXT,
                point_reached   REAL,
                validated_at    TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
            CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker);
            CREATE INDEX IF NOT EXISTS idx_signal_acc_signal ON signal_accuracy(signal);
            CREATE INDEX IF NOT EXISTS idx_pred_snap_ticker ON prediction_snapshots(ticker);
            CREATE INDEX IF NOT EXISTS idx_pred_snap_created ON prediction_snapshots(created_at);
        """)
    _migrate()


def _migrate() -> None:
    """Upgrade an existing DB to the current schema."""
    with _conn() as conn:
        # Check for price validation fields in trades
        trade_cols = {row[1] for row in conn.execute("PRAGMA table_info(trades)").fetchall()}
        if trade_cols:
            try:
                if "live_price_at_entry" not in trade_cols:
                    conn.execute("ALTER TABLE trades ADD COLUMN live_price_at_entry REAL")
                if "price_deviation_pct" not in trade_cols:
                    conn.execute("ALTER TABLE trades ADD COLUMN price_deviation_pct REAL")
                if "merged_into_trade_id" not in trade_cols:
                    conn.execute("ALTER TABLE trades ADD COLUMN merged_into_trade_id INTEGER")
                if "merge_confirmed_at" not in trade_cols:
                    conn.execute("ALTER TABLE trades ADD COLUMN merge_confirmed_at TEXT")
            except Exception:
                pass

        # Check for validation fields in prediction_snapshots
        pred_cols = {row[1] for row in conn.execute("PRAGMA table_info(prediction_snapshots)").fetchall()}
        if pred_cols:
            try:
                if "validation_target_date" not in pred_cols:
                    conn.execute("ALTER TABLE prediction_snapshots ADD COLUMN validation_target_date TEXT")
                if "validation_status" not in pred_cols:
                    conn.execute("ALTER TABLE prediction_snapshots ADD COLUMN validation_status TEXT DEFAULT 'PENDING'")
                if "validation_result" not in pred_cols:
                    conn.execute("ALTER TABLE prediction_snapshots ADD COLUMN validation_result TEXT")
                if "actual_price_at_validation" not in pred_cols:
                    conn.execute("ALTER TABLE prediction_snapshots ADD COLUMN actual_price_at_validation REAL")
                if "actual_return_at_validation" not in pred_cols:
                    conn.execute("ALTER TABLE prediction_snapshots ADD COLUMN actual_return_at_validation REAL")
                if "validated_at" not in pred_cols:
                    conn.execute("ALTER TABLE prediction_snapshots ADD COLUMN validated_at TEXT")
                if "window_high" not in pred_cols:
                    conn.execute("ALTER TABLE prediction_snapshots ADD COLUMN window_high REAL")
                if "window_low" not in pred_cols:
                    conn.execute("ALTER TABLE prediction_snapshots ADD COLUMN window_low REAL")
                # Graded price-prediction validation (midpoint-hit priority + reached point)
                if "hit_grade" not in pred_cols:
                    conn.execute("ALTER TABLE prediction_snapshots ADD COLUMN hit_grade TEXT")
                if "point_reached" not in pred_cols:
                    conn.execute("ALTER TABLE prediction_snapshots ADD COLUMN point_reached REAL")

                # Backfill validation status/date for old rows created before this migration.
                conn.execute("""
                    UPDATE prediction_snapshots
                    SET validation_status = 'PENDING'
                    WHERE validation_status IS NULL OR TRIM(validation_status) = ''
                """)
                conn.execute("""
                    UPDATE prediction_snapshots
                    SET validation_target_date = CASE UPPER(timeframe)
                        WHEN '1D' THEN DATE(created_at, '+1 day')
                        WHEN '3D' THEN DATE(created_at, '+3 day')
                        WHEN '5D' THEN DATE(created_at, '+5 day')
                        ELSE DATE(created_at, '+1 day')
                    END
                    WHERE validation_target_date IS NULL OR TRIM(validation_target_date) = ''
                """)

                conn.execute("CREATE INDEX IF NOT EXISTS idx_pred_snap_val_target ON prediction_snapshots(validation_target_date)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_pred_snap_val_status ON prediction_snapshots(validation_status)")
            except Exception:
                pass  # Columns may already exist

        # Remove same-day duplicate snapshots (same ticker/TF/direction/target_date created
        # on the same IST day). Use IST offset (+5:30) so predictions before/after UTC midnight
        # but on the same IST trading day are correctly deduplicated.
        # Keep the lowest id. Safe to run repeatedly — idempotent.
        try:
            conn.execute("""
                DELETE FROM prediction_snapshots
                WHERE id NOT IN (
                    SELECT MIN(id)
                    FROM prediction_snapshots
                    GROUP BY ticker, timeframe, direction, validation_target_date,
                             date(created_at, '+5 hours', '+30 minutes')
                )
            """)
        except Exception:
            pass

        # Fix any PENDING snapshots whose target date landed on a weekend.
        # Saturday → +2 days (Monday), Sunday → +1 day (Monday). Idempotent.
        try:
            conn.execute("""
                UPDATE prediction_snapshots
                SET validation_target_date = date(validation_target_date, '+2 days')
                WHERE validation_status = 'PENDING'
                  AND strftime('%w', validation_target_date) = '6'
            """)
            conn.execute("""
                UPDATE prediction_snapshots
                SET validation_target_date = date(validation_target_date, '+1 day')
                WHERE validation_status = 'PENDING'
                  AND strftime('%w', validation_target_date) = '0'
            """)
        except Exception:
            pass

        # Fix any PENDING snapshots whose target date landed on an NSE weekday holiday.
        # SQL cannot access _NSE_HOLIDAYS, so we use a Python loop with next_trading_day().
        # Idempotent — rows already on a trading day are skipped.
        try:
            from market_calendar import next_trading_day as _ntd
            from datetime import date as _date
            _holiday_rows = conn.execute(
                "SELECT id, validation_target_date FROM prediction_snapshots "
                "WHERE validation_status = 'PENDING'"
            ).fetchall()
            for _row in _holiday_rows:
                _raw = _row[1]
                if not _raw:
                    continue
                try:
                    _d = _date.fromisoformat(_raw)
                except ValueError:
                    continue
                _fixed = _ntd(_d)
                if _fixed != _d:
                    conn.execute(
                        "UPDATE prediction_snapshots SET validation_target_date = ? WHERE id = ?",
                        (_fixed.isoformat(), _row[0]),
                    )
        except Exception:
            pass

        cols = {row[1] for row in conn.execute("PRAGMA table_info(trades)").fetchall()}

        if "snapshot_id" not in cols:
            conn.execute("ALTER TABLE trades ADD COLUMN snapshot_id INTEGER")
        if "auto_close_date" not in cols:
            conn.execute("ALTER TABLE trades ADD COLUMN auto_close_date TEXT")
        if "realized_pnl" not in cols:
            conn.execute("ALTER TABLE trades ADD COLUMN realized_pnl REAL DEFAULT 0.0")
        if "cost" not in cols:
            conn.execute("ALTER TABLE trades ADD COLUMN cost REAL DEFAULT 0.0")

        if "order_type" not in cols:
            # Rebuild trades table to add order_type and extend the status CHECK.
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("ALTER TABLE trades RENAME TO _trades_old")
            conn.execute("""
                CREATE TABLE trades (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker      TEXT NOT NULL,
                    name        TEXT,
                    direction   TEXT CHECK(direction IN ('LONG','SHORT')),
                    order_type  TEXT DEFAULT 'MARKET' CHECK(order_type IN ('MARKET','LIMIT')),
                    entry_price REAL NOT NULL,
                    shares      INTEGER NOT NULL,
                    stop_loss   REAL,
                    target      REAL,
                    strategy    TEXT,
                    timeframe   TEXT,
                    prediction_data TEXT,
                    opened_at   TEXT DEFAULT (datetime('now')),
                    closed_at   TEXT,
                    exit_price  REAL,
                    status      TEXT DEFAULT 'OPEN' CHECK(status IN ('OPEN','CLOSED','PENDING','CANCELLED')),
                    pnl         REAL,
                    pnl_pct     REAL,
                    notes       TEXT
                )
            """)
            conn.execute("""
                INSERT INTO trades
                    (id, ticker, name, direction, order_type, entry_price, shares,
                     stop_loss, target, strategy, timeframe, prediction_data,
                     opened_at, closed_at, exit_price, status, pnl, pnl_pct, notes)
                SELECT
                    id, ticker, name, direction, 'MARKET', entry_price, shares,
                    stop_loss, target, strategy, timeframe, prediction_data,
                    opened_at, closed_at, exit_price, status, pnl, pnl_pct, notes
                FROM _trades_old
            """)
            conn.execute("DROP TABLE _trades_old")
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker)")


# ── WATCHLIST ─────────────────────────────────────────────────────────────────

def get_watchlist() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT ticker, name, added_at FROM watchlist ORDER BY added_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def add_to_watchlist(ticker: str, name: str) -> dict:
    ticker = ticker.upper().strip()
    if "." not in ticker:
        ticker += ".NS"  # default to NSE if no exchange specified
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO watchlist (ticker, name) VALUES (?, ?)",
            (ticker, name),
        )
    return {"ticker": ticker, "name": name}


def remove_from_watchlist(ticker: str) -> bool:
    ticker = ticker.upper().strip()
    with _conn() as conn:
        cur = conn.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker,))
    return cur.rowcount > 0


# ── TRADES ────────────────────────────────────────────────────────────────────

def get_open_position_value(ticker: str) -> float:
    """Sum of entry_price * shares for all OPEN trades of this ticker."""
    ticker = ticker.upper().strip()
    with _conn() as c:
        result = c.execute("""
            SELECT COALESCE(SUM(entry_price * shares), 0)
            FROM trades
            WHERE ticker = ? AND status = 'OPEN'
        """, (ticker,)).fetchone()
    return result[0] if result else 0.0


def open_trade(
    ticker: str,
    name: str,
    direction: str,
    entry_price: float,
    shares: int,
    stop_loss: Optional[float] = None,
    target: Optional[float] = None,
    strategy: Optional[str] = None,
    timeframe: Optional[str] = None,
    prediction_data: Optional[str] = None,
    order_type: str = "MARKET",
    status: str = "OPEN",
    snapshot_id: Optional[int] = None,
    auto_close_date: Optional[str] = None,
    live_price_at_entry: Optional[float] = None,
    price_deviation_pct: Optional[float] = None,
    merged_into_trade_id: Optional[int] = None,
    merge_confirmed_at: Optional[str] = None,
) -> dict:
    ticker = ticker.upper().strip()
    direction = direction.upper()
    order_type = order_type.upper()
    status = status.upper()
    with _conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO trades
              (ticker, name, direction, order_type, entry_price, shares, stop_loss,
               target, strategy, timeframe, prediction_data, status,
               snapshot_id, auto_close_date, live_price_at_entry, price_deviation_pct,
               merged_into_trade_id, merge_confirmed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (ticker, name, direction, order_type, entry_price, shares, stop_loss,
             target, strategy, timeframe, prediction_data, status,
             snapshot_id, auto_close_date, live_price_at_entry, price_deviation_pct,
             merged_into_trade_id, merge_confirmed_at),
        )
        trade_id = cur.lastrowid
    return get_trade(trade_id)


def get_trade(trade_id: int) -> dict:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    return dict(row) if row else {}


def fill_order(trade_id: int, fill_price: Optional[float] = None) -> dict:
    """Transition a PENDING limit order to OPEN (filled).

    If fill_price is provided (the actual market price at fill time), it
    overwrites entry_price so that P&L calculations use the real fill price
    rather than the original limit price when the market gapped past it.
    """
    filled_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as conn:
        if fill_price is not None:
            conn.execute(
                "UPDATE trades SET status = 'OPEN', opened_at = ?, entry_price = ? "
                "WHERE id = ? AND status = 'PENDING'",
                (filled_at, round(fill_price, 2), trade_id),
            )
        else:
            conn.execute(
                "UPDATE trades SET status = 'OPEN', opened_at = ? WHERE id = ? AND status = 'PENDING'",
                (filled_at, trade_id),
            )
    return get_trade(trade_id)


def cancel_order(trade_id: int) -> dict:
    """Cancel a PENDING limit order."""
    with _conn() as conn:
        conn.execute(
            "UPDATE trades SET status = 'CANCELLED' WHERE id = ? AND status = 'PENDING'",
            (trade_id,),
        )
    return get_trade(trade_id)


def get_pending_orders() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM trades WHERE status = 'PENDING' ORDER BY opened_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def merge_into_position(trade_id: int, add_shares: int, add_price: float) -> dict:
    """Average a new buy into an existing OPEN position.

    Recalculates weighted-average entry price and increments share count.
    The SELECT and UPDATE are in the same connection/transaction so SQLite's
    WAL serialization prevents concurrent adds from losing shares.
    Returns the updated trade dict.
    """
    with _conn() as conn:
        row = conn.execute(
            "SELECT shares, entry_price, status FROM trades WHERE id = ?", (trade_id,)
        ).fetchone()
        if not row or row["status"] != "OPEN":
            return get_trade(trade_id)
        old_shares = row["shares"]
        old_price  = row["entry_price"]
        total      = old_shares + add_shares
        if total <= 0:
            return get_trade(trade_id)
        avg_price  = round((old_shares * old_price + add_shares * add_price) / total, 2)
        conn.execute(
            "UPDATE trades SET shares = ?, entry_price = ? WHERE id = ? AND status = 'OPEN'",
            (total, avg_price, trade_id),
        )
    return get_trade(trade_id)


def close_trade(trade_id: int, exit_price: float, close_shares: Optional[int] = None) -> dict:
    """Close all or part of an OPEN position.

    If close_shares is None or equals total shares, the position is fully closed
    (status → CLOSED, P&L recorded).  If close_shares < total shares, only that
    portion is exited: the share count is reduced and the position stays OPEN.
    signal_accuracy is written only on a full close so win-rate stays clean.
    """
    trade = get_trade(trade_id)
    if not trade or trade["status"] != "OPEN":
        return trade

    entry     = trade["entry_price"]
    total_sh  = trade["shares"]
    direction = trade["direction"]
    close_sh  = int(close_shares) if close_shares else total_sh
    close_sh  = max(1, min(close_sh, total_sh))   # clamp to [1, total]

    if direction == "LONG":
        gross_pnl = (exit_price - entry) * close_sh
        gross_pct = (exit_price - entry) / entry * 100
    else:
        gross_pnl = (entry - exit_price) * close_sh
        gross_pct = (entry - exit_price) / entry * 100

    # Deduct realistic NSE round-trip transaction costs (price prediction ≠ profit).
    # 1D/3D swings are held overnight → delivery rates; INTRADAY → intraday rates.
    try:
        from costs import cost_pct_for_timeframe
        _tf = (trade.get("timeframe") or "").upper()
        cost_pct = cost_pct_for_timeframe("INTRADAY" if _tf == "INTRADAY" else "1D")
    except Exception:
        cost_pct = 0.0
    cost_rupees = round(cost_pct / 100 * entry * close_sh, 2)
    pnl     = round(gross_pnl - cost_rupees, 2)
    pnl_pct = round(gross_pct - cost_pct, 2)

    remaining = total_sh - close_sh

    if remaining > 0:
        # Partial close — reduce shares, accumulate realized P&L, keep OPEN.
        with _conn() as conn:
            conn.execute(
                """
                UPDATE trades
                SET shares = ?,
                    realized_pnl = COALESCE(realized_pnl, 0.0) + ?
                WHERE id = ? AND status = 'OPEN'
                """,
                (remaining, round(pnl, 2), trade_id),
            )
        return get_trade(trade_id)

    # Full close — guard against double-close race condition by requiring
    # status = 'OPEN' in the UPDATE predicate. rowcount == 0 means another
    # thread already closed this trade; skip the signal_accuracy insert.
    closed_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    strategy  = trade.get("strategy", "")
    timeframe = trade.get("timeframe", "")
    won       = 1 if pnl >= 0 else 0
    signals   = [s.strip() for s in strategy.split(",") if s.strip()] if strategy else ["Manual"]

    with _conn() as conn:
        cur = conn.execute(
            """
            UPDATE trades
            SET exit_price = ?, closed_at = ?, status = 'CLOSED',
                pnl = ?, pnl_pct = ?, cost = ?
            WHERE id = ? AND status = 'OPEN'
            """,
            (exit_price, closed_at, round(pnl, 2), round(pnl_pct, 2), cost_rupees, trade_id),
        )
        if cur.rowcount == 1:
            for sig in signals:
                conn.execute(
                    "INSERT INTO signal_accuracy (signal, timeframe, won, pnl_pct) VALUES (?, ?, ?, ?)",
                    (sig, timeframe, won, round(pnl_pct, 2)),
                )

    return get_trade(trade_id)


def save_postmortem(trade_id: int, notes: str) -> None:
    with _conn() as conn:
        conn.execute("UPDATE trades SET notes = ? WHERE id = ?", (notes, trade_id))


def get_open_trade(ticker: str, direction: str) -> Optional[dict]:
    """Fetch a single open trade for ticker + direction, or None if none exists."""
    ticker = ticker.upper().strip()
    direction = direction.upper().strip()
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM trades WHERE ticker = ? AND direction = ? AND status = 'OPEN' LIMIT 1",
            (ticker, direction)
        ).fetchone()
    return dict(row) if row else None


def get_open_trades() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM trades WHERE status = 'OPEN' ORDER BY opened_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_open_trades_with_live_prices() -> list[dict]:
    """
    Fetch open trades and enrich each with current live price.
    Uses ThreadPoolExecutor to parallelize live price fetches (~4 workers).
    Includes retry logic (up to 3 attempts) for robustness.
    Returns trades with 'current_price' field populated for display.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from data_sources import fetch_live_price
    import logging
    import time as _time
    
    trades = get_open_trades()
    if not trades:
        return trades
    
    def enrich_trade(trade):
        """Fetch live price for a trade with retries."""
        ticker = trade.get("ticker")
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                # Skip if already has a price (e.g., closed trades with exit_price)
                if trade.get("current_price") is None:
                    # Prefer strict real-time sources first.
                    live_price = fetch_live_price(ticker, allow_delayed=False)
                    if live_price is None:
                        # Fallback to freshness-gated delayed sources (same-day
                        # only, filtered in data_sources) so UI doesn't go blank
                        # during temporary NSE access blocks.
                        live_price = fetch_live_price(ticker, allow_delayed=True)
                    if live_price is not None:
                        trade["current_price"] = live_price
                        return trade
                    elif attempt < max_retries - 1:
                        # Retry with backoff
                        _time.sleep(0.1 * (attempt + 1))
                        continue
                    else:
                        trade["current_price"] = None
                return trade
            except Exception as e:
                if attempt < max_retries - 1:
                    _time.sleep(0.1 * (attempt + 1))
                    continue
                else:
                    logging.warning(f"Failed to fetch live price for {ticker} after {max_retries} attempts: {e}")
                    trade["current_price"] = None
                    return trade
        
        return trade
    
    # Parallelize live price fetches with 4 workers (increased pool for better concurrency)
    with ThreadPoolExecutor(max_workers=min(len(trades), 4)) as pool:
        futures = {pool.submit(enrich_trade, t): i for i, t in enumerate(trades)}
        enriched = [None] * len(trades)
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                enriched[idx] = fut.result()
            except Exception as e:
                logging.error(f"Exception in enrichment thread: {e}")
                enriched[idx] = trades[idx]
                enriched[idx]["current_price"] = None
    
    return enriched


def get_trade_history() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM trades WHERE status = 'CLOSED' ORDER BY closed_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_portfolio_summary() -> dict:
    open_trades = get_open_trades()
    history = get_trade_history()
    pending = get_pending_orders()

    total_invested = sum(t["entry_price"] * t["shares"] for t in open_trades)
    closed_pnl = sum((t["pnl"] or 0) for t in history)
    wins = sum(1 for t in history if (t["pnl"] or 0) >= 0)
    losses = len(history) - wins
    win_rate = round(wins / len(history) * 100, 1) if history else 0.0

    return {
        "open_count": len(open_trades),
        "pending_count": len(pending),
        "total_invested": round(total_invested, 2),
        "closed_pnl": round(closed_pnl, 2),
        "total_trades": len(history),
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
    }


def get_ticker_history(ticker: str, n: int = 5) -> list[dict]:
    """Return the last n closed trades for ticker, newest first."""
    ticker = ticker.upper().strip()
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT direction, entry_price, exit_price, pnl_pct, strategy, timeframe, closed_at
            FROM trades
            WHERE ticker = ? AND status = 'CLOSED'
            ORDER BY closed_at DESC
            LIMIT ?
            """,
            (ticker, n),
        ).fetchall()
    return [dict(r) for r in rows]


# ── SIGNAL ACCURACY ───────────────────────────────────────────────────────────

def get_signal_accuracy() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT signal, timeframe,
                   COUNT(*) as total,
                   SUM(won) as wins,
                   ROUND(AVG(won)*100, 1) as win_rate,
                   ROUND(AVG(pnl_pct), 2) as avg_pnl_pct
            FROM signal_accuracy
            GROUP BY signal, timeframe
            ORDER BY signal, timeframe
            """
        ).fetchall()
    return [dict(r) for r in rows]


# ── POSTMORTEMS ───────────────────────────────────────────────────────────────

def get_postmortems() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT id, ticker, name, direction, entry_price, exit_price,
                   pnl, pnl_pct, strategy, timeframe, closed_at, notes, prediction_data
            FROM trades
            WHERE status = 'CLOSED'
            ORDER BY closed_at DESC
            LIMIT 50
            """
        ).fetchall()
    return [dict(r) for r in rows]


# ── PREDICTION SNAPSHOTS (audit trail) ───────────────────────────────────────

def _trading_deadline(timeframe: str) -> str:
    """Return the ISO date string when a prediction for the given timeframe expires (weekends + NSE holidays skipped)."""
    from datetime import datetime, timedelta, timezone
    from market_calendar import next_trading_day
    tf_offset = {"INTRADAY": 0, "1D": 1, "3D": 3, "5D": 5, "1W": 7}
    days_offset = tf_offset.get(timeframe, 1)
    now_ist = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5, minutes=30)))
    target_dt = now_ist + timedelta(days=days_offset)
    return next_trading_day(target_dt.date()).isoformat()


def save_prediction_snapshot(
    ticker: str,
    timeframe: str,
    direction: str,
    confidence: str,
    target_price_lo: float,
    target_price_hi: float,
    predicted_return_lo: float,
    predicted_return_hi: float,
    current_price: float,
    snapshot_source: str = "watchlist",
    snapshot_data: Optional[str] = None,
) -> Optional[int]:
    """Save a prediction snapshot for audit trail with validation target date. Returns the
    snapshot ID, or None if the snapshot was intentionally skipped (see INTRADAY cutoff below)."""
    from datetime import datetime, timedelta, timezone
    import json
    
    ticker = ticker.upper().strip()
    if "." not in ticker:
        ticker += ".NS"
    
    # Calculate validation target date based on timeframe, skipping weekends and NSE holidays.
    # INTRADAY (offset 0) validates same-day — target_date == today (a trading day).
    from market_calendar import next_trading_day
    tf_offset = {"INTRADAY": 0, "1D": 1, "3D": 3, "5D": 5, "1W": 7}
    days_offset = tf_offset.get(timeframe, 1)
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc.astimezone(timezone(timedelta(hours=5, minutes=30)))
    # INTRADAY predictions made at/after the 15:00 IST grading cutoff (matches
    # app.py::_intraday_cutoff_passed) have no honest same-day window left to validate
    # against. Per product policy ("no next-day rollover" — see CLAUDE.md), skip saving the
    # audit snapshot entirely rather than silently grading it against a DIFFERENT day's
    # session (previously rolled validation_target_date forward a day, which scored a
    # narrow same-day-calibrated target against a whole extra trading day — see WHEELS.NS
    # 2026-07-30 incident).
    if timeframe == "INTRADAY" and days_offset == 0:
        if (now_ist.hour, now_ist.minute) >= (15, 0):
            return None
    target_dt = now_ist + timedelta(days=days_offset)
    target_date = next_trading_day(target_dt.date()).isoformat()
    
    with _conn() as conn:
        # Dedup: skip if the same ticker/timeframe/direction/target_date was already saved today.
        # Intentionally excludes current_price — the live price drifts throughout the day and
        # caused up to 4 identical-looking snapshots per ticker per session.
        existing = conn.execute(
            """
            SELECT id FROM prediction_snapshots
            WHERE ticker = ? AND timeframe = ? AND direction = ? AND validation_target_date = ?
              AND date(created_at) = date('now')
            LIMIT 1
            """,
            (ticker, timeframe, direction, target_date),
        ).fetchone()
        if existing:
            return existing["id"]

        cur = conn.execute(
            """
            INSERT INTO prediction_snapshots
              (ticker, timeframe, direction, confidence, target_price_lo, target_price_hi,
               predicted_return_lo, predicted_return_hi, current_price, snapshot_source, snapshot_data,
               validation_target_date, validation_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
            """,
            (ticker, timeframe, direction, confidence,
             target_price_lo, target_price_hi,
             predicted_return_lo, predicted_return_hi,
             current_price, snapshot_source, snapshot_data, target_date),
        )
        return cur.lastrowid


def get_prediction_snapshots(
    ticker: Optional[str] = None,
    days: Optional[int] = 30,
    limit: int = 100,
) -> list[dict]:
    """Retrieve prediction snapshots. If ticker is None, fetch all recent snapshots.
    Pass days=None (or days<=0) to fetch the ENTIRE history with no time window."""
    where = []
    params = []
    if ticker:
        ticker = ticker.upper().strip()
        if "." not in ticker:
            ticker += ".NS"
        where.append("ticker = ?")
        params.append(ticker)

    # Only apply a time window when days is a positive number; None/0 = all history.
    if days is not None and days > 0:
        where.append("datetime(created_at) > datetime('now', '-' || ? || ' days')")
        params.append(days)

    where_clause = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)

    with _conn() as conn:
        rows = conn.execute(
            f"""
            SELECT id, ticker, timeframe, direction, confidence,
                   target_price_lo, target_price_hi,
                   predicted_return_lo, predicted_return_hi,
                   current_price, snapshot_source, created_at, snapshot_data,
                   validation_target_date, validation_status, validation_result,
                   actual_price_at_validation, actual_return_at_validation,
                   window_high, window_low, validated_at
            FROM prediction_snapshots
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def get_prediction_misses(days: int = 30, min_confidence: str = "MEDIUM") -> list[dict]:
    """Get predictions where actual price exceeded target_price_hi (miss detection)."""
    confidence_rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    min_rank = confidence_rank.get(min_confidence, 1)
    confidence_vals = [k for k, v in confidence_rank.items() if v >= min_rank]
    
    with _conn() as conn:
        rows = conn.execute(
            f"""
            SELECT id, ticker, timeframe, direction, confidence,
                   target_price_lo, target_price_hi, predicted_return_lo, predicted_return_hi,
                   current_price, snapshot_source, created_at
            FROM prediction_snapshots
            WHERE datetime(created_at) > datetime('now', '-' || ? || ' days')
              AND confidence IN ({','.join(['?']*len(confidence_vals))})
            ORDER BY created_at DESC
            LIMIT 200
            """,
            [days] + confidence_vals,
        ).fetchall()
    return [dict(r) for r in rows]



# ── VALIDATION TRACKING ────────────────────────────────────────────────────────

def get_validation_pending(limit: int = 100, due_only: bool = True) -> list[dict]:
    """Get pending predictions; optionally only those due by today (IST)."""
    from datetime import datetime, timezone, timedelta
    
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc.astimezone(timezone(timedelta(hours=5, minutes=30)))
    today_str = now_ist.strftime("%Y-%m-%d")
    
    with _conn() as conn:
        if due_only:
            rows = conn.execute(
                """
                SELECT id, ticker, timeframe, direction, confidence,
                       target_price_lo, target_price_hi,
                       predicted_return_lo, predicted_return_hi,
                       current_price, snapshot_source, created_at, validation_target_date, validation_status
                FROM prediction_snapshots
                WHERE validation_status = 'PENDING'
                  AND validation_target_date <= ?
                ORDER BY validation_target_date ASC, ticker ASC
                LIMIT ?
                """,
                (today_str, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, ticker, timeframe, direction, confidence,
                       target_price_lo, target_price_hi,
                       predicted_return_lo, predicted_return_hi,
                       current_price, snapshot_source, created_at, validation_target_date, validation_status
                FROM prediction_snapshots
                WHERE validation_status = 'PENDING'
                ORDER BY validation_target_date ASC, ticker ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_validation_pending_count(due_only: bool = True) -> int:
    """Return count of PENDING prediction snapshots; optionally only those due by today (IST)."""
    from datetime import datetime, timezone, timedelta
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc.astimezone(timezone(timedelta(hours=5, minutes=30)))
    today_str = now_ist.strftime("%Y-%m-%d")
    with _conn() as conn:
        if due_only:
            row = conn.execute(
                "SELECT COUNT(*) FROM prediction_snapshots WHERE validation_status = 'PENDING' AND validation_target_date <= ?",
                (today_str,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM prediction_snapshots WHERE validation_status = 'PENDING'"
            ).fetchone()
    return row[0] if row else 0


def validate_prediction(
    snapshot_id: int,
    actual_price: float,
    actual_return: float,
    target_hit: bool,
    window_high: float = None,
    window_low: float = None,
    hit_grade: str = None,
    point_reached: float = None,
) -> dict:
    """Update a prediction snapshot with validation result.

    hit_grade: "MIDPOINT_HIT" | "RANGE_HIT" | "MISS" (graded price-prediction
    result). point_reached: the extreme price the stock actually reached toward
    the target. validation_result stays HIT/MISS (HIT = midpoint or range hit)
    for backward-compatible summaries.
    """
    from datetime import datetime, timezone

    validation_result = "HIT" if target_hit else "MISS"
    validated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    with _conn() as conn:
        conn.execute(
            """
            UPDATE prediction_snapshots
            SET validation_status = 'VALIDATED',
                validation_result = ?,
                actual_price_at_validation = ?,
                actual_return_at_validation = ?,
                window_high = ?,
                window_low = ?,
                hit_grade = ?,
                point_reached = ?,
                validated_at = ?
            WHERE id = ?
            """,
            (validation_result, actual_price, actual_return, window_high, window_low,
             hit_grade, point_reached, validated_at, snapshot_id),
        )
        row = conn.execute("SELECT * FROM prediction_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    return dict(row) if row else {}


def mark_prediction_skipped(snapshot_id: int) -> None:
    """Mark a prediction snapshot as SKIPPED (NO TRADE / zero-width range — not validatable)."""
    from datetime import datetime, timezone
    validated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as conn:
        conn.execute(
            """
            UPDATE prediction_snapshots
            SET validation_status = 'VALIDATED',
                validation_result = 'SKIPPED',
                validated_at = ?
            WHERE id = ?
            """,
            (validated_at, snapshot_id),
        )


def mark_prediction_expired(snapshot_id: int) -> None:
    """Mark a prediction snapshot as EXPIRED — its price data could not be fetched after
    repeated attempts over multiple days (e.g. delisted/illiquid ticker, data source outage).
    Removes it from the PENDING queue so it stops appearing as a perpetually "overdue"
    validation with a stale date; does not record a HIT/MISS since no price was ever obtained."""
    from datetime import datetime, timezone
    validated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as conn:
        conn.execute(
            """
            UPDATE prediction_snapshots
            SET validation_status = 'EXPIRED',
                validated_at = ?
            WHERE id = ?
            """,
            (validated_at, snapshot_id),
        )


def get_validation_summary() -> dict:
    """Get validation hit rate summary across all history in the DB.

    Returns {
      "all": {tf: {total, hits, misses, hit_rate_pct}},           # all predictions incl. NEUTRAL
      "directional": {tf: {total, hits, misses, hit_rate_pct}},   # BULLISH + BEARISH only
      "high_conf": {tf: {total, hits, misses, hit_rate_pct}},     # HIGH-confidence directional only
    }
    `hit_rate_pct` counts a HIT as midpoint-hit OR range-hit. `midpoint_rate_pct`
    (when present) counts only exact midpoint hits — the strict price-prediction score.
    Backtest: HIGH-confidence directional calls hit ~95-97% and are the profit bucket,
    so the high_conf block is the one to watch for the >85% target.
    """
    base_where = (
        "validation_status = 'VALIDATED'"
        " AND UPPER(COALESCE(direction, '')) NOT IN ('NO TRADE', 'N/A', '', 'SKIPPED')"
        " AND validation_result IN ('HIT', 'MISS')"
    )
    directional_where = base_where + " AND UPPER(direction) IN ('BULLISH', 'BEARISH', 'SLIGHTLY BULLISH', 'SLIGHTLY BEARISH')"
    high_conf_where = directional_where + " AND UPPER(COALESCE(confidence, '')) = 'HIGH'"
    # Source split: 'ml' = the standalone quantile model; anything else = the AI/LLM path.
    ml_where = directional_where + " AND LOWER(COALESCE(snapshot_source, '')) = 'ml'"
    ai_where = directional_where + " AND LOWER(COALESCE(snapshot_source, '')) <> 'ml'"

    with _conn() as conn:
        def _query(where: str):
            rows = conn.execute(
                f"""
                SELECT timeframe,
                       COUNT(*) as total,
                       SUM(CASE WHEN validation_result = 'HIT' THEN 1 ELSE 0 END) as hits,
                       SUM(CASE WHEN validation_result = 'MISS' THEN 1 ELSE 0 END) as misses,
                       ROUND(AVG(CASE WHEN validation_result = 'HIT' THEN 100.0 ELSE 0 END), 1) as hit_rate_pct,
                       ROUND(AVG(CASE WHEN hit_grade = 'MIDPOINT_HIT' THEN 100.0 ELSE 0 END), 1) as midpoint_rate_pct
                FROM prediction_snapshots
                WHERE {where}
                GROUP BY timeframe
                ORDER BY timeframe
                """
            ).fetchall()
            return {row["timeframe"]: dict(row) for row in rows}

        # Agreement bucket: ML and AI made the SAME directional call on the same
        # ticker/timeframe/target_date, and BOTH were validated. hit_rate_pct = how
        # often both hit — the highest-quality consensus signal.
        agree_rows = conn.execute(
            """
            SELECT m.timeframe AS timeframe,
                   COUNT(*) AS total,
                   SUM(CASE WHEN m.validation_result = 'HIT' AND a.validation_result = 'HIT' THEN 1 ELSE 0 END) AS hits,
                   ROUND(AVG(CASE WHEN m.validation_result = 'HIT' AND a.validation_result = 'HIT' THEN 100.0 ELSE 0 END), 1) AS hit_rate_pct
            FROM prediction_snapshots m
            JOIN prediction_snapshots a
              ON m.ticker = a.ticker AND m.timeframe = a.timeframe
             AND m.validation_target_date = a.validation_target_date
             AND UPPER(m.direction) = UPPER(a.direction)
            WHERE LOWER(COALESCE(m.snapshot_source, '')) = 'ml'
              AND LOWER(COALESCE(a.snapshot_source, '')) <> 'ml'
              AND m.validation_status = 'VALIDATED' AND a.validation_status = 'VALIDATED'
              AND m.validation_result IN ('HIT', 'MISS') AND a.validation_result IN ('HIT', 'MISS')
              AND UPPER(m.direction) IN ('BULLISH', 'BEARISH', 'SLIGHTLY BULLISH', 'SLIGHTLY BEARISH')
            GROUP BY m.timeframe
            ORDER BY m.timeframe
            """
        ).fetchall()
        agreement = {r["timeframe"]: dict(r) for r in agree_rows}

        return {
            "all": _query(base_where),
            "directional": _query(directional_where),
            "high_conf": _query(high_conf_where),
            "by_source": {"ml": _query(ml_where), "ai": _query(ai_where)},
            "agreement": agreement,
        }


def get_validation_history(timeframe: Optional[str] = None, limit: int = 100) -> list[dict]:
    """Get validated predictions with results."""
    tf_filter = ""
    params = []
    if timeframe:
        tf_filter = "AND timeframe = ?"
        params.append(timeframe)
    params.append(limit)
    
    with _conn() as conn:
        rows = conn.execute(
            f"""
            SELECT id, ticker, timeframe, direction, confidence,
                   target_price_lo, target_price_hi,
                   predicted_return_lo, predicted_return_hi,
                   current_price, actual_price_at_validation, actual_return_at_validation,
                   window_high, window_low, hit_grade, point_reached,
                   snapshot_source,
                   validation_result, created_at, validated_at, validation_target_date
            FROM prediction_snapshots
            WHERE validation_status = 'VALIDATED'
            {tf_filter}
            ORDER BY validated_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def prune_validated_snapshots(keep_days: int = 365) -> int:
    """Delete VALIDATED/EXPIRED prediction_snapshots older than keep_days.

    Keeps a full year in the DB so stat cards always reflect cumulative history.
    Learnings.json also accumulates these records as a secondary backup.
    """
    with _conn() as conn:
        cur = conn.execute(
            "DELETE FROM prediction_snapshots "
            "WHERE validation_status IN ('VALIDATED', 'EXPIRED') "
            "AND datetime(validated_at) < datetime('now', ?)",
            (f"-{int(keep_days)} days",),
        )
        return cur.rowcount


def recalibrate_all_snapshots() -> dict:
    """Retroactively update all snapshots to use calibrated target ranges.

    For VALIDATED snapshots that have window_high/window_low, re-evaluates the hit result.
    For PENDING snapshots, just updates lo/hi so future validation uses calibrated ranges.

    Returns {updated_targets, revalidated, flipped_to_hit, flipped_to_miss}.
    """
    from datetime import datetime, timezone

    def _hit(direction, window_high, window_low, actual_price, lo, hi):
        # Range intersection: intraday band [window_low, window_high] overlaps [lo, hi]
        if window_high is None or window_low is None:
            return actual_price is not None and lo <= actual_price <= hi
        return window_high >= lo and window_low <= hi

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    revalidated = flipped_to_hit = flipped_to_miss = 0

    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT id, direction, validation_status, validation_result,
                   window_high, window_low, actual_price_at_validation,
                   target_price_lo, target_price_hi
            FROM prediction_snapshots
            WHERE UPPER(COALESCE(direction, '')) NOT IN ('NO TRADE', 'N/A', '')
              AND validation_status = 'VALIDATED'
              AND validation_result IN ('HIT', 'MISS')
            """
        ).fetchall()

        for row in rows:
            snap_id = row["id"]
            direction = row["direction"]
            lo = row["target_price_lo"]
            hi = row["target_price_hi"]
            wh = row["window_high"]
            wl = row["window_low"]
            ap = row["actual_price_at_validation"]

            if not lo or not hi or lo == hi:
                continue

            new_hit = _hit(direction, wh, wl, ap, lo, hi)
            new_result = "HIT" if new_hit else "MISS"
            old_result = row["validation_result"]

            if new_result != old_result:
                conn.execute(
                    "UPDATE prediction_snapshots SET validation_result=?, validated_at=? WHERE id=?",
                    (new_result, now, snap_id),
                )
                if new_result == "HIT":
                    flipped_to_hit += 1
                else:
                    flipped_to_miss += 1
                revalidated += 1

    return {
        "updated_targets": 0,
        "revalidated": revalidated,
        "flipped_to_hit": flipped_to_hit,
        "flipped_to_miss": flipped_to_miss,
    }
