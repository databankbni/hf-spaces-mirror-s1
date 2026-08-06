# ---------------------------------------------------------------------------
# tests/test_session_budget.py
#
# Verifies the reading-session budget logic WITHOUT any audio or network.
# We build a tiny in-memory SQLite database with known per-verse durations
# and assert the session stops at the right verse for a given budget.
# ---------------------------------------------------------------------------

import sqlite3

import pytest

from reader.session import ReadingSession
from reader.verse_store import VerseStore


def _make_store(tmp_path, durations):
    """Create a temp SQLite DB with verses BG1.1.. each having a fixed
    total duration (split evenly across sa/en). `durations` is a list of
    total seconds per verse, in reading order."""
    db_path = tmp_path / "test_gita.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE verses (
            verse_id TEXT PRIMARY KEY, chapter INTEGER, verse INTEGER,
            title TEXT, sanskrit TEXT, english TEXT, hindi TEXT,
            sa_seconds REAL, en_seconds REAL
        );
        """
    )
    for i, total in enumerate(durations, start=1):
        conn.execute(
            "INSERT INTO verses VALUES (?,?,?,?,?,?,?,?,?)",
            (f"BG1.{i}", 1, i, "Test", f"sa{i}", f"en{i}", "", total / 2, total / 2),
        )
    conn.commit()
    conn.close()
    return VerseStore(db_path=db_path)


def test_session_stops_when_budget_exhausted(tmp_path):
    # Five verses, 60s each. Budget 150s → fits 2 full verses (120s),
    # the 3rd (would be 180s) doesn't fit → stop, bookmark BG1.3.
    store = _make_store(tmp_path, [60, 60, 60, 60, 60])
    session = ReadingSession(store, "BG1.1", budget_seconds=150)
    played = [pb.verse_id for pb in session.iter_verses()]
    assert played == ["BG1.1", "BG1.2"]
    assert session.next_bookmark == "BG1.3"


def test_at_least_one_verse_plays_on_short_budget(tmp_path):
    # First verse (100s) exceeds the whole 30s budget, but we still play
    # one verse so the user makes progress; next bookmark is BG1.2.
    store = _make_store(tmp_path, [100, 50])
    session = ReadingSession(store, "BG1.1", budget_seconds=30)
    played = [pb.verse_id for pb in session.iter_verses()]
    assert played == ["BG1.1"]
    assert session.next_bookmark == "BG1.2"


def test_finishing_book_loops_to_start(tmp_path):
    store = _make_store(tmp_path, [10, 10])
    session = ReadingSession(store, "BG1.1", budget_seconds=10_000)
    played = [pb.verse_id for pb in session.iter_verses()]
    assert played == ["BG1.1", "BG1.2"]
    assert session.finished_book is True
    assert session.next_bookmark == "BG1.1"


def test_resume_from_middle(tmp_path):
    store = _make_store(tmp_path, [60, 60, 60, 60])
    session = ReadingSession(store, "BG1.3", budget_seconds=60)
    played = [pb.verse_id for pb in session.iter_verses()]
    assert played == ["BG1.3"]
    assert session.next_bookmark == "BG1.4"
