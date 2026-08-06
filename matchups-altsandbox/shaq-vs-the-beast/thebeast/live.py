"""Resuming a game that's already under way.

Everything needed to turn MLB's live feed into the snapshot the simulator can
restart from: which inning/half/outs/baserunners the game sits at, whose turn
it is to bat, how many pitches the starter has thrown, and which arms the
bullpen has left.

Lives here rather than in the API layer because both the live-sim endpoint and
the betting pipeline need it — a live bet has to be priced against the rest of
*this* game, not against a pregame projection of it.
"""
from __future__ import annotations

from typing import Optional

from .data.repository import SQLiteRepository
from .pipeline import resolve_lineups
from .simulator.state import InningState

# Statlines used for in-season projections; mirrors the API's current season.
CURRENT_SEASON = 2026


def _next_batting_slot(team_box) -> int:
    """0-based batting-order slot due up next for one side of a box score.

    Every plate appearance advances the order exactly one slot, so the total
    number of PAs a team has taken, mod 9, *is* the next slot — correct through
    any number of pinch-hitters. Falls back to AB+BB if the feed omits
    plateAppearances (slightly low, since it can't see HBP/sacrifices).
    """
    if team_box is None:
        return 0
    pas = [b.plate_appearances for b in team_box.batters if b.plate_appearances is not None]
    if pas:
        return sum(pas) % 9
    approx = sum((b.at_bats or 0) + (b.walks or 0) for b in team_box.batters)
    return approx % 9


def _live_inning_state(home: str, away: str, linescore, boxscore) -> Optional[InningState]:
    """Build the simulator's starting snapshot from the live feed, or None if
    the game hasn't got a usable in-progress state."""
    inning = linescore.current_inning
    if not inning:
        return None

    phase = (linescore.inning_state or "").strip().lower()
    sit = linescore.situation
    outs = sit.outs or 0
    runners = ((1 if sit.on_first else 0)
               | (2 if sit.on_second else 0)
               | (4 if sit.on_third else 0))

    # "Middle"/"End" mean no half is actually being played right now, so the
    # next one starts clean rather than inheriting outs/runners.
    if phase == "middle":
        half, outs, runners = "bottom", 0, 0
    elif phase == "end":
        inning, half, outs, runners = inning + 1, "top", 0, 0
    else:
        half = "top" if linescore.is_top_inning else "bottom"

    if inning > 9:  # nothing left to play in regulation
        return None

    home_score = linescore.home_totals.runs
    away_score = linescore.away_totals.runs
    if home_score is None or away_score is None:
        return None

    # Seed the per-inning arrays with what's already on the board so the
    # simulated remainder appends onto a real line score. An in-progress half's
    # runs so far go into _inning_runs, which is what gets appended when it ends.
    by_inning = {i.num: (i.away_runs or 0, i.home_runs or 0) for i in linescore.innings}
    away_done = inning - 1 if half == "top" else inning
    home_done = inning - 1
    away_by = [by_inning.get(i, (0, 0))[0] for i in range(1, away_done + 1)]
    home_by = [by_inning.get(i, (0, 0))[1] for i in range(1, home_done + 1)]
    cur = by_inning.get(inning, (0, 0))
    inning_runs = cur[0] if half == "top" else cur[1]

    return InningState(
        home=home, away=away,
        inning=inning, half=half, outs=outs, runners_bitmap=runners,
        score={home: int(home_score), away: int(away_score)},
        batting_position={
            home: _next_batting_slot(getattr(boxscore, "home", None)),
            away: _next_batting_slot(getattr(boxscore, "away", None)),
        },
        home_by_inning=home_by, away_by_inning=away_by,
        _inning_runs=int(inning_runs),
    )


def _live_bullpens(repo: SQLiteRepository, game_id: str,
                   home: Optional[str], away: Optional[str],
                   boxscore) -> dict[str, list[int]]:
    """{team: [relief arm ids, in the order they should pitch]} for a live game.

    A live box score names every pitcher who has already appeared, so the man
    currently on the mound can be projected as *himself* — with his own
    statline — instead of being folded into the team's bullpen average. He is
    put first, followed by the aggregate, which stands in for the arms that
    haven't come in yet and whose identity nobody knows.

    Relievers already used are deliberately excluded: they're pitched and gone.
    """
    out: dict[str, list[int]] = {}
    if boxscore is None:
        return out
    try:
        home_lineup, away_lineup = resolve_lineups(game_id, repo, home, away)
    except Exception:
        return out
    from .data.ingest import team_bullpen_pid
    for team, lineup, side in ((home, home_lineup, "home"), (away, away_lineup, "away")):
        if not team:
            continue
        team_box = getattr(boxscore, side, None)
        if team_box is None:
            continue
        # The last pitcher listed with recorded work who isn't the starter is
        # the reliever currently in the game.
        current: Optional[int] = None
        for p in team_box.pitchers:
            if p.player_id is None:
                continue
            pid = int(p.player_id)
            if pid == lineup.starter_id:
                continue
            current = pid
        pen = [team_bullpen_pid(team)]
        if current is not None and repo.get_pitcher(current, CURRENT_SEASON) is not None:
            pen = [current, *pen]
        out[team] = pen
    return out


def _starter_pitch_counts(repo: SQLiteRepository, game_id: str,
                          home: Optional[str], away: Optional[str],
                          boxscore) -> dict[str, float]:
    """{team: pitches the starter has already thrown}, from the live box score.

    Without this the simulator resumes a game treating the starter as fresh, so
    someone sitting on 90 pitches in the 4th would be projected to keep going.
    Only the listed starter is looked up — once he's out, the inning rule takes
    over and the count no longer matters.
    """
    out: dict[str, float] = {}
    if boxscore is None:
        return out
    try:
        home_lineup, away_lineup = resolve_lineups(game_id, repo, home, away)
    except Exception:
        return out
    for team, lineup, side in ((home, home_lineup, "home"), (away, away_lineup, "away")):
        if not team:
            continue
        team_box = getattr(boxscore, side, None)
        if team_box is None:
            continue
        for p in team_box.pitchers:
            if p.player_id is not None and int(p.player_id) == lineup.starter_id:
                if p.pitches is not None:
                    out[team] = float(p.pitches)
                break
    return out
