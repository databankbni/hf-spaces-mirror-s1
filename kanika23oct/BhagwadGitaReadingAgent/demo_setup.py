# ---------------------------------------------------------------------------
# demo_setup.py — fast bootstrap for a Chapter-1 demo.
#
# A full run synthesizes ~1400 mp3s (one gTTS network call each), which is
# too slow to wait for before a demo. This script instead:
#
#   1. Builds the full corpus (SQLite + Chroma) — needed for verse text,
#      ordered reading, and the "Ask the Sage" semantic search.
#   2. Synthesizes REAL audio only for Chapter 1 (~47 verses).
#   3. Fills every other verse's duration columns with a text-length
#      ESTIMATE so app.py's ensure_audio() sees a complete table and does
#      NOT try to synthesize the whole book on launch.
#
# A 10-minute session starting at BG1.1 only spans ~20 verses, so the demo
# stays entirely within Chapter 1, where the audio is real. The estimated
# durations on later chapters are never reached during the demo.
#
# Run once:  python demo_setup.py
# Then:      python app.py
# ---------------------------------------------------------------------------

import sqlite3

from config import AUDIO_ENGLISH_DIR, AUDIO_SANSKRIT_DIR, DB_PATH
from ingestion.build_audio import _duration_seconds, _synthesize
from ingestion.build_corpus import ensure_corpus

DEMO_CHAPTER = 1

# Rough spoken-word rate for the duration estimate (~150 words/min).
_WORDS_PER_SECOND = 2.5
_MIN_ESTIMATE_SECONDS = 4.0


def _estimate_seconds(text: str) -> float:
    words = len((text or "").split())
    return max(_MIN_ESTIMATE_SECONDS, words / _WORDS_PER_SECOND)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def synth_chapter(conn: sqlite3.Connection, chapter: int) -> int:
    """Synthesize real Sanskrit + English audio for one chapter and write
    the measured durations back to SQLite. Returns the verse count."""
    rows = conn.execute(
        "SELECT verse_id, sanskrit, english FROM verses "
        "WHERE chapter = ? ORDER BY verse",
        (chapter,),
    ).fetchall()
    total = len(rows)
    print(f"[demo] synthesizing real audio for Chapter {chapter} "
          f"({total} verses)...")

    for i, row in enumerate(rows, start=1):
        vid = row["verse_id"]
        sa_path = AUDIO_SANSKRIT_DIR / f"{vid}.mp3"
        en_path = AUDIO_ENGLISH_DIR / f"{vid}.mp3"

        _synthesize(row["sanskrit"], "hi", sa_path)
        _synthesize(row["english"], "en", en_path)

        conn.execute(
            "UPDATE verses SET sa_seconds = ?, en_seconds = ? "
            "WHERE verse_id = ?",
            (_duration_seconds(sa_path), _duration_seconds(en_path), vid),
        )
        if i % 10 == 0 or i == total:
            conn.commit()
            print(f"[demo]   {i}/{total} done")
    conn.commit()
    return total


def fill_estimates(conn: sqlite3.Connection) -> int:
    """Give every still-unmeasured verse an estimated duration so the app
    treats the audio table as complete. These verses are outside the demo
    window and never actually played."""
    rows = conn.execute(
        "SELECT verse_id, sanskrit, english FROM verses "
        "WHERE sa_seconds IS NULL OR en_seconds IS NULL"
    ).fetchall()
    for row in rows:
        conn.execute(
            "UPDATE verses SET sa_seconds = ?, en_seconds = ? "
            "WHERE verse_id = ?",
            (
                _estimate_seconds(row["sanskrit"]),
                _estimate_seconds(row["english"]),
                row["verse_id"],
            ),
        )
    conn.commit()
    return len(rows)


def main() -> None:
    print("[demo] building corpus (dataset download + embeddings)...")
    ensure_corpus()

    conn = _connect()
    try:
        synthesized = synth_chapter(conn, DEMO_CHAPTER)
        estimated = fill_estimates(conn)
    finally:
        conn.close()

    print(
        f"[demo] ready: {synthesized} verses with real audio, "
        f"{estimated} verses with estimated durations."
    )
    print("[demo] now run:  python app.py")


if __name__ == "__main__":
    main()
