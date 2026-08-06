# ---------------------------------------------------------------------------
# ingestion/build_audio.py — Phase A3.
#
# Generate two mp3 files per verse (Sanskrit + English) with gTTS, probe
# each file's duration with mutagen, and write the durations back into the
# SQLite `verses` table so the reading-session budget loop knows how long
# each verse takes to play.
#
#   sanskrit → gTTS(lang="hi")   (Hindi voice approximates Devanagari)
#   english  → gTTS(lang="en")
#
# Idempotent: a verse whose mp3 already exists on disk is skipped, so a
# re-run only synthesizes what's missing. Mirrors the ensure_index() idea.
# ---------------------------------------------------------------------------

import sqlite3
import re
import os

from config import (
    AUDIO_ENGLISH_DIR,
    AUDIO_SANSKRIT_DIR,
    AUDIO_HINDI_DIR,
    DB_PATH,
)


def clean_for_tts(text: str) -> str:
    """gTTS spells ALL-CAPS words out letter-by-letter (it treats them as
    acronyms). The dataset shouts proper names like SANJAYA / KURUKSHETRA,
    so down-case any all-caps word of 2+ letters to Title Case before
    synthesis. Genuine short initialisms are left alone."""

    def _fix(m: re.Match) -> str:
        word = m.group(0)
        return word.capitalize()

    return re.sub(r"\b[A-Z]{2,}\b", _fix, text)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _synthesize(text: str, lang: str, out_path) -> None:
    """Write a single mp3 via gTTS. No-op if the file already exists."""
    from gtts import gTTS

    if out_path.exists():
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    gTTS(text=text, lang=lang).save(str(out_path))


def _duration_seconds(mp3_path) -> float:
    """Read an mp3's playback length in seconds via mutagen."""
    from mutagen.mp3 import MP3

    return float(MP3(str(mp3_path)).info.length)


def build_audio(chapter: int | None = None) -> None:
    """Synthesize Sanskrit + English + Hindi audio for verses and store
    per-verse durations back into SQLite.

    Pass `chapter` to build just one chapter (e.g. chapter=1 for the demo);
    omit it to build the entire Gita. Idempotent: existing mp3s are skipped,
    so re-running only fills gaps and you can grow coverage incrementally."""
    conn = _connect()
    _ensure_hi_seconds_column(conn)
    try:
        if chapter is None:
            rows = conn.execute(
                "SELECT verse_id, sanskrit, english, hindi FROM verses "
                "ORDER BY chapter, verse"
            ).fetchall()
            scope = "the entire Gita"
        else:
            rows = conn.execute(
                "SELECT verse_id, sanskrit, english, hindi FROM verses "
                "WHERE chapter = ? ORDER BY verse",
                (chapter,),
            ).fetchall()
            scope = f"chapter {chapter}"
        total = len(rows)
        print(f"[build_audio] synthesizing audio for {scope} ({total} verses)...")

        for i, row in enumerate(rows, start=1):
            vid = row["verse_id"]
            sa_path = AUDIO_SANSKRIT_DIR / f"{vid}.mp3"
            en_path = AUDIO_ENGLISH_DIR / f"{vid}.mp3"
            hi_path = AUDIO_HINDI_DIR / f"{vid}.mp3"

            _synthesize(row["sanskrit"], "hi", sa_path)
            _synthesize(clean_for_tts(row["english"]), "en", en_path)
            if (row["hindi"] or "").strip():
                _synthesize(row["hindi"], "hi", hi_path)

            sa_seconds = _duration_seconds(sa_path)
            en_seconds = _duration_seconds(en_path)
            hi_seconds = _duration_seconds(hi_path) if hi_path.exists() else None

            conn.execute(
                "UPDATE verses SET sa_seconds = ?, en_seconds = ?, hi_seconds = ? "
                "WHERE verse_id = ?",
                (sa_seconds, en_seconds, hi_seconds, vid),
            )
            if i % 25 == 0 or i == total:
                conn.commit()
                print(f"[build_audio]   {i}/{total} done")
        conn.commit()
        print("[build_audio] done")
    finally:
        conn.close()


def _ensure_hi_seconds_column(conn: sqlite3.Connection) -> None:
    """Add the hi_seconds column on older databases that predate Hindi audio."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(verses)").fetchall()}
    if "hi_seconds" not in cols:
        conn.execute("ALTER TABLE verses ADD COLUMN hi_seconds REAL")
        conn.commit()


def _audio_complete() -> bool:
    """True if every verse already has Sanskrit + English mp3s and durations.

    Hindi is treated as best-effort (not all verses may have Hindi text), so
    it does not block this check; missing Hindi just won't be offered."""
    if not DB_PATH.exists():
        return False
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS missing FROM verses "
            "WHERE sa_seconds IS NULL OR en_seconds IS NULL"
        ).fetchone()
        return int(row["missing"]) == 0
    finally:
        conn.close()


def ensure_audio() -> None:
    """Synthesize audio only if some verse is still missing it. Safe to
    call repeatedly."""
    if _audio_complete():
        print("[ensure_audio] all verses already have audio, skipping.")
        return
    if os.environ.get("SPACE_ID"):
        # On Hugging Face Spaces we never synthesize at runtime. gTTS hits
        # Google Translate, which rate-limits (HTTP 429) bulk jobs and would
        # crash the app at boot. Audio is a one-time OFFLINE build
        # (`python -m ingestion.build_audio`); the Space ships prebuilt mp3s
        # and simply doesn't play whatever is missing.
        print("[ensure_audio] running on a Space — skipping synthesis; "
              "using prebuilt audio only.")
        return
    build_audio()


if __name__ == "__main__":
    import sys

    chap = int(sys.argv[1]) if len(sys.argv) > 1 else None
    build_audio(chap)
