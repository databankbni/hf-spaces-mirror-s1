"""Reading a game id: '<date>-<away>-<home>[-g{N}]'.

This was open-coded in five places — `_base_game_id` copy-pasted verbatim into
two modules, and three separate functions pulling the date out of an id, each
with slightly different tolerance. Nothing had gone wrong because of it yet, but
the shape of the id is one fact and it was written down five times, which is
five things to remember to change and four chances to miss one.

The two tolerances are kept, deliberately, because both are wanted:

`parse` is **strict** — the id must split cleanly into date, away and home, so
a caller that needs teams gets None rather than a guess.

`date_of` is **lenient** — it reads the leading date and ignores the rest, which
is what lets the assistant resolve something a model typed as
"2026-08-03 STL at NYY" instead of refusing it.
"""
from __future__ import annotations

import re
from datetime import date as _date, datetime
from typing import Optional

_DOUBLEHEADER = re.compile(r"-g\d+$")


def base_id(game_id: str) -> str:
    """Drop a doubleheader '-g{N}' suffix so date/team parsing sees the base."""
    return _DOUBLEHEADER.sub("", game_id or "")


def parse(game_id: str) -> tuple[Optional[_date], Optional[str], Optional[str]]:
    """'<date>-<away>-<home>[-g{N}]' → (date, home, away). Strict."""
    parts = base_id(game_id).rsplit("-", 2)
    if len(parts) != 3:
        return None, None, None
    day, away, home = parts
    try:
        parsed = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError:
        return None, None, None
    return parsed, home, away


def teams_of(game_id: str) -> tuple[Optional[str], Optional[str]]:
    """(home, away), or (None, None) if the id doesn't parse."""
    parts = base_id(game_id).rsplit("-", 2)
    if len(parts) == 3:
        _, away, home = parts
        return home, away
    return None, None


def date_of(game_id: str) -> Optional[_date]:
    """The date an id starts with, ignoring whatever follows it. Lenient."""
    try:
        return datetime.strptime((game_id or "")[:10], "%Y-%m-%d").date()
    except (ValueError, IndexError, TypeError):
        return None


def season_of(game_id: str) -> int:
    """The season an id falls in; today's year when it can't be read."""
    day = date_of(game_id)
    return day.year if day is not None else _date.today().year
