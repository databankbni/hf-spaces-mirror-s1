"""One-off maintenance: detect & reset intraday prediction snapshots whose stored
validation window is inconsistent with the snapshot's own entry price (a wrong-ticker
data-contamination bug in validation).  Resets them to PENDING so they re-validate.

Usage:
    python research/fix_mismatched_validations.py            # dry-run (report only)
    python research/fix_mismatched_validations.py --apply    # reset the bad rows
"""
import os
import sqlite3
import sys

DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "paper_trading.db")


def is_mismatched(cp, wl, wh) -> bool:
    """A validated intraday window MUST bracket the entry price (same-day move).
    If the entry price is nowhere near the window, the window belongs to another ticker.
    """
    if cp is None or wl is None or wh is None or cp <= 0:
        return False
    return not (wl * 0.85 <= cp <= wh * 1.15)


def main(apply: bool) -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute(
        "SELECT id, ticker, date(created_at) d, timeframe, current_price cp, "
        "window_low wl, window_high wh, validation_result vr "
        "FROM prediction_snapshots "
        "WHERE timeframe='INTRADAY' AND window_low IS NOT NULL AND window_high IS NOT NULL"
    ))
    bad = [r for r in rows if is_mismatched(r["cp"], r["wl"], r["wh"])]
    print(f"Scanned {len(rows)} validated INTRADAY rows; found {len(bad)} mismatched:\n")
    for r in bad:
        print(f"  id={r['id']:>5} {r['d']} {r['ticker']:16} entry={r['cp']:>9.1f} "
              f"window={r['wl']:.1f}-{r['wh']:.1f} result={r['vr']}")
    if not bad:
        print("Nothing to fix.")
        return
    if not apply:
        print("\nDry-run only. Re-run with --apply to reset these rows to PENDING.")
        return
    ids = [r["id"] for r in bad]
    conn.executemany(
        "UPDATE prediction_snapshots SET "
        "validation_status='PENDING', validation_result=NULL, hit_grade=NULL, "
        "actual_price_at_validation=NULL, actual_return_at_validation=NULL, "
        "window_high=NULL, window_low=NULL, point_reached=NULL, validated_at=NULL "
        "WHERE id=?",
        [(i,) for i in ids],
    )
    conn.commit()
    print(f"\nReset {len(ids)} rows to PENDING: {ids}")


if __name__ == "__main__":
    main("--apply" in sys.argv)
