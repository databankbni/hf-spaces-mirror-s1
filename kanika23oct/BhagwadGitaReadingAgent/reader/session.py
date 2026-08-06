# ---------------------------------------------------------------------------
# reader/session.py — Phase B2.
#
# The reading engine. This is the heart of the app and it is DELIBERATELY
# free of any LLM: timing, verse order, and the resume bookmark must be
# deterministic.
#
# A ReadingSession plays verses one after another until the wall-clock
# audio budget (e.g. 10 minutes) runs out. Before yielding each verse it
# checks whether the verse's audio fits in the remaining budget:
#
#   - If it fits  → yield it, subtract its duration.
#   - If it does not fit → stop. The verse that didn't fit becomes the
#     new bookmark, so the next session resumes exactly there.
#
# Edge case: if the very FIRST verse is longer than the whole budget, we
# still play it (otherwise the user would make no progress on a short
# budget) and the next verse becomes the bookmark.
# ---------------------------------------------------------------------------

from dataclasses import dataclass

from reader.audio import (
    english_audio_path,
    hindi_audio_path,
    sanskrit_audio_path,
)
from reader.verse_store import Verse, VerseStore


@dataclass(frozen=True)
class VersePlayback:
    """Everything the UI needs to render and play one verse."""

    verse_id: str
    ref: str
    title: str
    sanskrit_text: str
    english_text: str
    hindi_text: str
    sanskrit_audio: str | None  # filesystem path as str (Gradio-friendly)
    english_audio: str | None
    hindi_audio: str | None
    total_seconds: float


def _path_if_exists(path) -> str | None:
    """Return the path as a string only if the file is actually on disk.
    Verses beyond Chapter 1 have no audio yet, so we hand Gradio None rather
    than a broken path."""
    return str(path) if path.exists() else None


def _to_playback(verse: Verse) -> VersePlayback:
    return VersePlayback(
        verse_id=verse.verse_id,
        ref=verse.ref,
        title=verse.title,
        sanskrit_text=verse.sanskrit,
        english_text=verse.english,
        hindi_text=verse.hindi,
        sanskrit_audio=_path_if_exists(sanskrit_audio_path(verse.verse_id)),
        english_audio=_path_if_exists(english_audio_path(verse.verse_id)),
        hindi_audio=_path_if_exists(hindi_audio_path(verse.verse_id)),
        total_seconds=verse.total_seconds,
    )


class ReadingSession:
    """A single bounded reading session over the book.

    Parameters
    ----------
    store:
        VerseStore for ordered verse access.
    start_verse_id:
        Where to begin reading (the user's saved bookmark).
    budget_seconds:
        Wall-clock audio budget for this session (e.g. 600 = 10 min).
    """

    def __init__(self, store: VerseStore, start_verse_id: str, budget_seconds: float):
        self._store = store
        self._start_verse_id = start_verse_id
        self._budget = float(budget_seconds)
        # The verse to resume from next time. Updated as the session runs.
        # Defaults to the start verse (nothing played yet).
        self.next_bookmark: str = start_verse_id
        # True once the book has been fully read in this session.
        self.finished_book: bool = False

    def iter_verses(self):
        """Yield VersePlayback items until the budget is exhausted.

        After iteration completes, `self.next_bookmark` holds the verse the
        next session should resume from, and `self.finished_book` is True
        if the end of the book was reached.
        """
        remaining = self._budget
        verse = self._store.get_verse(self._start_verse_id)

        # Defensive: an unknown bookmark falls back to the first verse.
        if verse is None:
            verse = self._store.first_verse()

        played_any = False
        while verse is not None:
            cost = verse.total_seconds

            # Before yielding, check the verse fits the remaining budget.
            # Exception: always play at least one verse so a short budget
            # still makes progress.
            if played_any and cost > remaining:
                self.next_bookmark = verse.verse_id
                return

            yield _to_playback(verse)
            played_any = True
            remaining -= cost

            nxt = self._store.next_verse_after(verse.verse_id)
            if nxt is None:
                # Reached the end of the book. Loop back to the start so the
                # user can begin a fresh pass next time.
                self.finished_book = True
                self.next_bookmark = self._store.first_verse_id()
                return

            # Remember where we'd resume if the loop stops on the next pass.
            self.next_bookmark = nxt.verse_id
            verse = nxt
