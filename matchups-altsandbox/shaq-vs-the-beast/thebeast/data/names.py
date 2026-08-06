"""Resolve MLB player ids to names.

The simulator works entirely in player ids; anything user-facing — a box
score, a prop that has to be matched to a book's player name — needs the name
back. Stored statlines are the first stop because they cost nothing, and only
the leftovers (callups, recent trades, anyone without a statline yet) go out to
the MLB people endpoint, in one batched call.

Lives here rather than in the API layer because both the API and the betting
pipeline need it.
"""
from __future__ import annotations

import unicodedata

# Statlines are stored per season; a player missing from the current one may
# still be named in a recent past season, so fall back through them.
_NAME_SEASONS = tuple(range(2026, 2019, -1))


def player_name(repo, pid: int, season: int) -> str:
    """Name for `pid` from stored statlines (any season); '' if not found."""
    for s in (season, *(x for x in _NAME_SEASONS if x != season)):
        b = repo.get_batter(pid, s)
        if b is not None and b.name:
            return b.name
        p = repo.get_pitcher(pid, s)
        if p is not None and p.name:
            return p.name
    return ""


def player_names(repo, ids, season: int) -> dict[int, str]:
    """{id: name} for `ids`; ids that stay unresolved are simply omitted."""
    out: dict[int, str] = {}
    unresolved: list[int] = []
    for pid in ids:
        pid = int(pid)
        if pid < 0 or pid in out:
            continue
        nm = player_name(repo, pid, season)
        if nm:
            out[pid] = nm
        else:
            unresolved.append(pid)
    if unresolved:
        try:
            from .sources.people import MLBPeopleSource
            out.update(MLBPeopleSource().names(unresolved))
        except Exception:
            pass  # best-effort — callers fall back to the numeric id
    return out


def normalize_name(name: str) -> str:
    """Accent-, case- and punctuation-insensitive key for matching names.

    Books and our statlines disagree on accents and punctuation ("Jose Ramirez"
    vs "José Ramírez", "J.T. Realmuto" vs "JT Realmuto"), so matching happens
    on this key rather than the raw string.
    """
    n = unicodedata.normalize("NFKD", name or "")
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = "".join(c if (c.isalnum() or c.isspace()) else " " for c in n.lower())
    return " ".join(n.split())
