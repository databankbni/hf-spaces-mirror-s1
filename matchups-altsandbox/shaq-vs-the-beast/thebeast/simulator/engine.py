"""simulate_game — the main PA-level loop.

Mirrors mrsim's simulator.py structure exactly:
  - simulate_game()  ← the entry point
  - _execute_pa()   ← draws one PA outcome and applies it to state
  - _apply_outcome() ← mutates InningState, accumulates box score

Pitching transition (U-005 MVP heuristic): starter pitches through inning
`knobs.starter_innings`; after that, the first bullpen_id in the lineup card
is used for all remaining PAs. If no bullpen ID exists, the starter continues.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from ..data.models import LineupCard
from .advancement import LeagueAverageMatrix, RunnerAdvancementMatrix
from .config import SimulationKnobs
from .outcome import PAOutcomeDistribution, sample_batting_form
from .state import InningState

_DEFAULT_KNOBS = SimulationKnobs()
_DEFAULT_ADV = LeagueAverageMatrix()


@dataclass
class GameResult:
    """Box score for one simulated game (analogous to mrsim GameResult)."""
    home: str
    away: str
    home_score: int
    away_score: int
    innings_played: int
    extra_innings: bool
    home_by_inning: list[int] = field(default_factory=list)
    away_by_inning: list[int] = field(default_factory=list)
    play_log: list[str] = field(default_factory=list)
    # Per-player box score keyed by (team_id, player_id)
    player_stats: dict = field(default_factory=dict)
    # Per-pitcher box score keyed by (team_id, player_id)
    pitcher_stats: dict = field(default_factory=dict)

    @property
    def winner(self) -> Optional[str]:
        if self.home_score > self.away_score:
            return self.home
        if self.away_score > self.home_score:
            return self.away
        return None


_STAT_FIELDS = ("pa", "ab", "hits", "singles", "doubles", "triples", "home_runs",
                "rbi", "bb", "hbp", "k", "ipo")

# Pitcher counting stats accumulated against the pitcher on the mound.
_PITCHER_FIELDS = ("bf", "outs", "hits_allowed", "hr_allowed",
                   "bb_allowed", "k", "runs_allowed", "pitches")

# Expected pitches to complete a plate appearance, by how it ended. A strikeout
# needs at least three pitches and a walk at least four, so both run long; balls
# in play end sooner. Values are round MLB averages (2023-24) and weight out to
# ~3.8 pitches per PA against league-average outcome rates, matching the real
# league figure. Pitch counts are what actually get a starter removed, so these
# drive the hook below as well as the projected line.
_PITCH_COST = {
    "K": 4.8,
    "BB": 5.5,
    "HBP": 3.4,
    "HR": 3.4,
    "1B": 3.3,
    "2B": 3.3,
    "3B": 3.3,
    "IPO": 3.3,
}
_PITCH_COST_DEFAULT = 3.8


def _new_stat_line(team: str, player_id: int) -> dict:
    line: dict = {"team": team, "player_id": player_id}
    for f in _STAT_FIELDS:
        line[f] = 0
    return line


def _new_pitcher_line(team: str, player_id: int) -> dict:
    line: dict = {"team": team, "player_id": player_id}
    for f in _PITCHER_FIELDS:
        line[f] = 0
    return line


def _trouble_pressure(knobs: SimulationKnobs, runs_allowed: int,
                      inning_runs: int, consecutive_on: int) -> float:
    """Pitches of leash a starter has lost by how the outing is going.

    Three signals, each counted only past what a manager sits through without
    reaching for the phone — two runs across a start, a run in an inning, two
    men reaching back to back are all ordinary and cost nothing. Past that the
    rope shortens in proportion to the trouble, so a bad inning brings the hook
    forward by a few batters rather than ending the start outright.

    Capped, because even a battering leaves a starter some rope: the bullpen is
    finite and somebody has to eat the innings.
    """
    over = max(0, runs_allowed - knobs.starter_trouble_free_runs)
    inning_over = max(0, inning_runs - knobs.starter_trouble_free_inning_runs)
    traffic = max(0, consecutive_on - knobs.starter_trouble_free_baserunners)
    pressure = (over * knobs.starter_trouble_per_run
                + inning_over * knobs.starter_trouble_per_inning_run
                + traffic * knobs.starter_trouble_per_baserunner)
    return min(pressure, knobs.starter_trouble_max)


def _starter_is_done(inning: int, knobs: SimulationKnobs,
                     starter_pitches: float,
                     pitch_limit: Optional[float] = None,
                     runs_allowed: int = 0,
                     inning_runs: int = 0,
                     consecutive_on: int = 0) -> bool:
    """Whether the starter's day is over.

    The day ends at the inning ceiling — a hard backstop, rarely the binding
    rule — or at his pitch count, against this start's own limit.

    How the start is *going* moves that limit rather than overriding it. A
    manager weighs trouble against everything else he is managing, so a
    battered pitcher is on a shorter rope, not an expired one: he may finish
    the inning, and a good one often finishes the next. Treating trouble as a
    threshold instead ended every rough start at the same instant, which both
    over-shortened the left tail and made the hook deterministic — the one
    thing a real hook is not.

    `pitch_limit` is this start's own hook, drawn once per game; it falls back
    to the configured average when a caller doesn't supply one.
    """
    if inning > knobs.starter_innings:
        return True
    if not knobs.use_pitch_counts:
        return False
    limit = knobs.starter_pitch_limit if pitch_limit is None else pitch_limit
    return starter_pitches >= limit - _trouble_pressure(
        knobs, runs_allowed, inning_runs, consecutive_on)


def _current_pitcher(
    lineup: LineupCard,
    inning: int,
    knobs: SimulationKnobs,
    starter_pitches: float = 0.0,
    relief_idx: int = 0,
    relief_pitches: float = 0.0,
    starter_limit: Optional[float] = None,
    runs_allowed: int = 0,
    inning_runs: int = 0,
    consecutive_on: int = 0,
) -> tuple[int, int]:
    """(pitcher_id, relief_index) for the arm that should be on the mound.

    Once the starter is done the bullpen is worked through in the order given,
    each arm handed roughly `reliever_pitch_limit` pitches before the next
    comes in. The final arm listed absorbs whatever remains, so a one-entry
    bullpen behaves exactly as it did before this became a sequence.
    """
    if not lineup.bullpen_ids:
        return lineup.starter_id, relief_idx
    if not _starter_is_done(inning, knobs, starter_pitches, starter_limit,
                            runs_allowed, inning_runs, consecutive_on):
        return lineup.starter_id, relief_idx
    idx = relief_idx
    if (knobs.use_pitch_counts
            and idx < len(lineup.bullpen_ids) - 1
            and relief_pitches >= knobs.reliever_pitch_limit):
        idx += 1
    return lineup.bullpen_ids[idx], idx


def _get_dist(
    pa_distributions: dict[tuple[int, int], PAOutcomeDistribution],
    batter_id: int,
    pitcher_id: int,
) -> PAOutcomeDistribution:
    key = (batter_id, pitcher_id)
    if key in pa_distributions:
        return pa_distributions[key]
    # Fallback: any distribution for this batter (ignores pitcher)
    for (b, _), dist in pa_distributions.items():
        if b == batter_id:
            return dist
    # Last resort: return first available distribution
    return next(iter(pa_distributions.values()))


def simulate_game(
    home_lineup: LineupCard,
    away_lineup: LineupCard,
    pa_distributions: dict[tuple[int, int], PAOutcomeDistribution],
    advancement: RunnerAdvancementMatrix = _DEFAULT_ADV,
    rng: Optional[np.random.Generator] = None,
    knobs: Optional[SimulationKnobs] = None,
    log: bool = False,
    initial_state: Optional[InningState] = None,
    initial_pitch_counts: Optional[dict[str, float]] = None,
    starter_pitch_limits: Optional[dict[str, float]] = None,
) -> GameResult:
    """Simulate one 9-inning game and return the box score.

    `pa_distributions` maps (batter_id, pitcher_id) → PAOutcomeDistribution.
    Missing pairs fall back to any distribution for that batter, then to the
    first available distribution in the dict.

    `initial_state` resumes from a partially-played game (the live-sim path):
    the loop picks up at that inning/half/outs/baserunners with the runs already
    on the board, and only the rest of the game is simulated. The returned box
    score therefore covers the *remainder*, while `home_score`/`away_score` are
    the projected final (already-scored runs included). Defaults to a fresh
    game when omitted.
    """
    if rng is None:
        rng = np.random.default_rng()
    if knobs is None:
        knobs = _DEFAULT_KNOBS

    state = (initial_state.clone() if initial_state is not None
             else InningState(home=home_lineup.team_id, away=away_lineup.team_id))
    lineups = {home_lineup.team_id: home_lineup, away_lineup.team_id: away_lineup}
    play_log: list[str] = []
    player_stats: dict[tuple[str, int], dict] = {}
    pitcher_stats: dict[tuple[str, int], dict] = {}

    def stat(team: str, pid: int) -> dict:
        key = (team, pid)
        if key not in player_stats:
            player_stats[key] = _new_stat_line(team, pid)
        return player_stats[key]

    def pstat(team: str, pid: int) -> dict:
        key = (team, pid)
        if key not in pitcher_stats:
            pitcher_stats[key] = _new_pitcher_line(team, pid)
        return pitcher_stats[key]

    # Pitches thrown by each team's starter. Seeded for a live game already
    # underway, so a starter resumed at 80 pitches is hooked promptly.
    starter_pitches: dict[str, float] = {
        home_lineup.team_id: 0.0, away_lineup.team_id: 0.0}
    if initial_pitch_counts:
        for team, thrown in initial_pitch_counts.items():
            if team in starter_pitches:
                starter_pitches[team] = float(thrown)

    # This start's hook, drawn once per game per side. A single fixed limit
    # ends nearly every outing on the same pitch, which collapses the outs
    # distribution onto one value; the spread is what makes a line like
    # "17.5 outs" a real question rather than a foregone one.
    def _draw_limit(team: str) -> float:
        # This pitcher's own leash when the caller worked one out from his
        # statline, the league average otherwise.
        base = float((starter_pitch_limits or {}).get(team, knobs.starter_pitch_limit))
        jitter = float(getattr(knobs, "starter_pitch_jitter", 0.0))
        if jitter <= 0:
            return base
        # Clipped so a draw can't produce an absurd outing in either direction.
        return float(np.clip(rng.normal(base, jitter), base - 25.0, base + 25.0))

    starter_limit: dict[str, float] = {
        home_lineup.team_id: _draw_limit(home_lineup.team_id),
        away_lineup.team_id: _draw_limit(away_lineup.team_id)}

    # How the start is going, which is the other half of the hook. Runs in the
    # current inning and men reaching back-to-back both reset when the inning
    # turns over; cumulative runs come off the pitcher's own line.
    starter_inning_runs: dict[str, int] = {
        home_lineup.team_id: 0, away_lineup.team_id: 0}
    starter_consec_on: dict[str, int] = {
        home_lineup.team_id: 0, away_lineup.team_id: 0}
    last_inning_seen: dict[str, tuple] = {
        home_lineup.team_id: (0, ""), away_lineup.team_id: (0, "")}

    # Which relief arm is in, and how much he has thrown. Each is handed about
    # an inning before the next warms up; the last one listed finishes the game.
    relief_idx: dict[str, int] = {
        home_lineup.team_id: 0, away_lineup.team_id: 0}
    relief_pitches: dict[str, float] = {
        home_lineup.team_id: 0.0, away_lineup.team_id: 0.0}

    # Per-half-inning form multipliers (Cholesky correlation)
    contact_form, power_form = 1.0, 1.0

    max_pas = 1000  # safety cap (prevents infinite loops in edge cases)
    pa_count = 0

    while not state.game_over and pa_count < max_pas:
        team = state.possession
        lineup = lineups[team]

        # Resample form at the start of each half-inning
        if state.outs == 0 and state.runners_bitmap == 0 and pa_count > 0:
            if knobs.use_cholesky:
                contact_form, power_form = sample_batting_form(
                    rng, rho=knobs.cholesky_rho, sigma=knobs.cholesky_sigma,
                )
            else:
                contact_form, power_form = 1.0, 1.0

        batter_id = lineup.batting_order[state.batting_position[team]]
        # Capture the defending team now: an inning-ending out below flips the
        # half before the box score is recorded, so reading state.defense later
        # would charge this PA to the wrong team's pitcher.
        defense_team = state.defense
        # A new half-inning wipes the in-inning counters for this pitcher.
        here = (state.inning, state.half)
        if last_inning_seen[defense_team] != here:
            last_inning_seen[defense_team] = here
            starter_inning_runs[defense_team] = 0
            starter_consec_on[defense_team] = 0
        starter_line = pitcher_stats.get(
            (defense_team, lineups[defense_team].starter_id))
        pitcher_id, new_idx = _current_pitcher(
            lineups[defense_team], state.inning, knobs,
            starter_pitches[defense_team],
            relief_idx[defense_team], relief_pitches[defense_team],
            starter_limit[defense_team],
            int(starter_line["runs_allowed"]) if starter_line else 0,
            starter_inning_runs[defense_team],
            starter_consec_on[defense_team],
        )
        if new_idx != relief_idx[defense_team]:
            relief_idx[defense_team] = new_idx
            relief_pitches[defense_team] = 0.0  # fresh arm

        dist = _get_dist(pa_distributions, batter_id, pitcher_id)
        if knobs.use_cholesky:
            dist = dist.with_form(contact_form, power_form)

        outcome = dist.sample(rng)

        # Apply home field advantage: small HR boost for home batters
        if team == home_lineup.team_id and knobs.home_field_advantage != 1.0:
            if outcome == "HR" or (rng.random() < (knobs.home_field_advantage - 1.0) * 10):
                pass  # HFA already baked into dist via knobs; kept simple for MVP

        new_runners, runs = advancement.advance(
            state.runners_bitmap, outcome, state.outs, rng
        )

        # Update state
        state.runners_bitmap = new_runners
        if runs:
            state.add_runs(runs)
            # Walk-off check
            state._check_walk_off()
            if state.game_over:
                break

        # Record out for strikeout or IPO
        if outcome in ("K", "IPO"):
            state.record_out()

        # Accumulate box score
        ps = stat(team, batter_id)
        ps["pa"] += 1
        if outcome not in ("BB", "HBP"):
            ps["ab"] += 1
        if outcome == "1B":
            ps["hits"] += 1; ps["singles"] += 1
        elif outcome == "2B":
            ps["hits"] += 1; ps["doubles"] += 1
        elif outcome == "3B":
            ps["hits"] += 1; ps["triples"] += 1
        elif outcome == "HR":
            ps["hits"] += 1; ps["home_runs"] += 1
        elif outcome == "BB":
            ps["bb"] += 1
        elif outcome == "HBP":
            ps["hbp"] += 1
        elif outcome == "K":
            ps["k"] += 1
        elif outcome == "IPO":
            ps["ipo"] += 1
        ps["rbi"] += runs

        # Charge this PA to the pitcher on the mound (the defending team's).
        pp = pstat(defense_team, pitcher_id)
        pp["bf"] += 1
        if outcome in ("K", "IPO"):
            pp["outs"] += 1
        if outcome == "K":
            pp["k"] += 1
        elif outcome == "BB":
            pp["bb_allowed"] += 1
        if outcome in ("1B", "2B", "3B", "HR"):
            pp["hits_allowed"] += 1
        if outcome == "HR":
            pp["hr_allowed"] += 1
        pp["runs_allowed"] += runs
        thrown = _PITCH_COST.get(outcome, _PITCH_COST_DEFAULT)
        pp["pitches"] += thrown
        if pitcher_id == lineups[defense_team].starter_id:
            starter_pitches[defense_team] += thrown
            starter_inning_runs[defense_team] += runs
            # A streak of men reaching is what actually brings the manager out;
            # any out ends it, whether or not anyone scored.
            if outcome in ("1B", "2B", "3B", "HR", "BB", "HBP"):
                starter_consec_on[defense_team] += 1
            else:
                starter_consec_on[defense_team] = 0
        else:
            relief_pitches[defense_team] += thrown

        if log:
            inn = f"{'Bot' if state.half == 'bottom' else 'Top'} {state.inning}"
            play_log.append(
                f"{inn} | {team} {batter_id} vs {pitcher_id} → {outcome} "
                f"({runs}R, runners={state.runners_bitmap:03b}, outs={state.outs})"
            )

        state.advance_batting_position()
        pa_count += 1

    # Pad inning line scores to 9 if game ended early (walk-off)
    while len(state.home_by_inning) < 9:
        state.home_by_inning.append(0)
    while len(state.away_by_inning) < 9:
        state.away_by_inning.append(0)

    return GameResult(
        home=state.home,
        away=state.away,
        home_score=state.score[state.home],
        away_score=state.score[state.away],
        innings_played=min(state.inning, 9),
        extra_innings=state.inning > 10,
        home_by_inning=state.home_by_inning,
        away_by_inning=state.away_by_inning,
        play_log=play_log,
        player_stats=player_stats,
        pitcher_stats=pitcher_stats,
    )
