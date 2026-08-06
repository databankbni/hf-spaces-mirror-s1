"""Monte Carlo aggregation — run_games + aggregate.

Mirrors mrsim's aggregate.py exactly: separate the batch loop (raw arrays)
from the summary computation. Raw is needed for histograms; summary for API.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from ..data.models import LineupCard
from .advancement import LeagueAverageMatrix, RunnerAdvancementMatrix
from .config import SimulationKnobs
from .engine import GameResult, _PITCHER_FIELDS, _STAT_FIELDS, simulate_game
from .outcome import PAOutcomeDistribution
from .state import InningState

# Per-game distributions are kept for these, not just the mean: a prop asks
# P(stat >= line), which a mean cannot answer. Total bases is derived per game
# from the hit types rather than stored by the engine.
_PROP_BATTER_STATS = ("hits", "singles", "doubles", "triples", "home_runs",
                      "rbi", "bb", "k", "total_bases")
_PROP_PITCHER_STATS = ("k", "outs", "hits_allowed", "bb_allowed", "runs_allowed")


def _batter_prop_value(line: dict, stat: str) -> int:
    if stat == "total_bases":
        return int(line["singles"] + 2 * line["doubles"]
                   + 3 * line["triples"] + 4 * line["home_runs"])
    return int(line[stat])


def prob_at_least(hist: dict, k: int) -> float:
    """P(value >= k) from a {value: count} histogram."""
    total = sum(hist.values())
    if not total:
        return 0.0
    return sum(c for v, c in hist.items() if v >= k) / total


@dataclass
class GameSimulationRaw:
    """Raw per-game arrays (analogous to mrsim MonteCarloRaw)."""
    home_runs: np.ndarray      # int32[n]
    away_runs: np.ndarray      # int32[n]
    totals: np.ndarray         # int32[n]
    extra_inning_flags: np.ndarray  # bool[n]
    sample: list[GameResult] = field(default_factory=list)
    home_players: list[dict] = field(default_factory=list)
    away_players: list[dict] = field(default_factory=list)
    home_pitchers: list[dict] = field(default_factory=list)
    away_pitchers: list[dict] = field(default_factory=list)
    representative: Optional[GameResult] = None
    # {(team, player_id): {stat: {value: games}}} — the shape a prop needs.
    batter_hist: dict = field(default_factory=dict)
    pitcher_hist: dict = field(default_factory=dict)


@dataclass
class GameSimulationResult:
    """Aggregated summary (analogous to mrsim MonteCarloResult)."""
    game_id: str
    home: str
    away: str
    n: int
    home_win_probability: float
    home_run_mean: float
    home_run_median: float
    home_run_p10: float
    home_run_p90: float
    away_run_mean: float
    away_run_median: float
    away_run_p10: float
    away_run_p90: float
    total_mean: float
    total_median: float
    total_p10: float
    total_p90: float
    extra_inning_pct: float
    spread_mean: float   # home - away
    player_lines: list[dict] = field(default_factory=list)
    pitcher_lines: list[dict] = field(default_factory=list)
    # Raw (pre-calibration) win probability, set when a calibrator is applied.
    home_win_probability_raw: Optional[float] = None


def _project_player_stats(
    totals: dict[tuple[str, int], dict],
    home_id: str,
    away_id: str,
    n: int,
) -> tuple[list[dict], list[dict]]:
    """Turn summed-over-games player totals into per-game projected lines."""
    home: list[dict] = []
    away: list[dict] = []
    for (team, pid), line in totals.items():
        proj = {"team": team, "player_id": pid}
        for f in _STAT_FIELDS:
            proj[f] = line[f] / n
        # Show anyone who accumulated *any* stat across the run, not just the
        # regulars — a player who ever came to bat (or reached, walked, etc.)
        # earns a box-score line.
        if all(proj.get(f, 0) <= 0 for f in _STAT_FIELDS):
            continue
        (home if team == home_id else away).append(proj)
    for bucket in (home, away):
        bucket.sort(key=lambda p: -p["pa"])
    return home, away


def _project_pitcher_stats(
    totals: dict[tuple[str, int], dict],
    home_id: str,
    away_id: str,
    n: int,
) -> tuple[list[dict], list[dict]]:
    """Turn summed-over-games pitcher totals into per-game projected lines.

    Outs are converted to innings pitched; runs_allowed is the earned-run
    projection (the sim has no fielding errors, so every run is earned).
    """
    home: list[dict] = []
    away: list[dict] = []
    for (team, pid), line in totals.items():
        proj = {"team": team, "player_id": pid}
        for f in _PITCHER_FIELDS:
            proj[f] = line[f] / n
        proj["ip"] = proj["outs"] / 3.0
        proj["er"] = proj["runs_allowed"]
        # Keep any pitcher who ever faced a batter or recorded any stat.
        if all(proj.get(f, 0) <= 0 for f in _PITCHER_FIELDS):
            continue
        (home if team == home_id else away).append(proj)
    # Show the biggest workload (the starter) first.
    for bucket in (home, away):
        bucket.sort(key=lambda p: -p["outs"])
    return home, away


def run_games(
    home_lineup: LineupCard,
    away_lineup: LineupCard,
    pa_distributions: dict[tuple[int, int], PAOutcomeDistribution],
    advancement: Optional[RunnerAdvancementMatrix] = None,
    n: int = 5000,
    seed: Optional[int] = None,
    keep_sample: int = 3,
    representative: bool = False,
    knobs: Optional[SimulationKnobs] = None,
    initial_state: Optional["InningState"] = None,
    initial_pitch_counts: Optional[dict[str, float]] = None,
    starter_pitch_limits: Optional[dict[str, float]] = None,
) -> GameSimulationRaw:
    """Run `n` independent games and return raw per-game arrays.

    With `initial_state`, every game resumes from that same partially-played
    snapshot, so the arrays are projected *finals* for a game already underway
    and the player lines cover only the remaining plate appearances.
    """
    if advancement is None:
        advancement = LeagueAverageMatrix()
    if knobs is None:
        knobs = SimulationKnobs()

    rng = np.random.default_rng(seed)
    home_runs = np.empty(n, dtype=np.int32)
    away_runs = np.empty(n, dtype=np.int32)
    extra_flags = np.zeros(n, dtype=bool)
    sample: list[GameResult] = []

    game_seeds = np.empty(n, dtype=np.uint64) if representative else None
    stat_totals: dict[tuple[str, int], dict] = {}
    pitcher_totals: dict[tuple[str, int], dict] = {}
    batter_hist: dict[tuple[str, int], dict] = {}
    pitcher_hist: dict[tuple[str, int], dict] = {}

    for i in range(n):
        child_seed = int(rng.integers(0, 2**63 - 1))
        if game_seeds is not None:
            game_seeds[i] = child_seed
        child = np.random.default_rng(child_seed)
        result = simulate_game(
            home_lineup, away_lineup, pa_distributions, advancement,
            rng=child, knobs=knobs, initial_state=initial_state,
            initial_pitch_counts=initial_pitch_counts,
            starter_pitch_limits=starter_pitch_limits,
        )
        home_runs[i] = result.home_score
        away_runs[i] = result.away_score
        extra_flags[i] = result.extra_innings

        for key, line in result.player_stats.items():
            agg = stat_totals.get(key)
            if agg is None:
                stat_totals[key] = dict(line)
            else:
                for f in _STAT_FIELDS:
                    agg[f] += line[f]
            hb = batter_hist.setdefault(key, {})
            for f in _PROP_BATTER_STATS:
                d = hb.setdefault(f, {})
                v = _batter_prop_value(line, f)
                d[v] = d.get(v, 0) + 1
        for key, line in result.pitcher_stats.items():
            agg = pitcher_totals.get(key)
            if agg is None:
                pitcher_totals[key] = dict(line)
            else:
                for f in _PITCHER_FIELDS:
                    agg[f] += line[f]
            hp = pitcher_hist.setdefault(key, {})
            for f in _PROP_PITCHER_STATS:
                d = hp.setdefault(f, {})
                v = int(line[f])
                d[v] = d.get(v, 0) + 1

        if i < keep_sample:
            sample.append(result)

    home_players, away_players = _project_player_stats(
        stat_totals, home_lineup.team_id, away_lineup.team_id, n
    )
    home_pitchers, away_pitchers = _project_pitcher_stats(
        pitcher_totals, home_lineup.team_id, away_lineup.team_id, n
    )

    rep_game: Optional[GameResult] = None
    if game_seeds is not None and n > 0:
        mean_h = float(home_runs.mean())
        mean_a = float(away_runs.mean())
        dist = (home_runs - mean_h) ** 2 + (away_runs - mean_a) ** 2
        idx = int(np.argmin(dist))
        rep_game = simulate_game(
            home_lineup, away_lineup, pa_distributions, advancement,
            rng=np.random.default_rng(int(game_seeds[idx])),
            knobs=knobs, log=True, initial_state=initial_state,
            initial_pitch_counts=initial_pitch_counts,
            starter_pitch_limits=starter_pitch_limits,
        )

    return GameSimulationRaw(
        home_runs=home_runs,
        away_runs=away_runs,
        totals=home_runs + away_runs,
        extra_inning_flags=extra_flags,
        sample=sample,
        home_players=home_players,
        away_players=away_players,
        home_pitchers=home_pitchers,
        away_pitchers=away_pitchers,
        representative=rep_game,
        batter_hist=batter_hist,
        pitcher_hist=pitcher_hist,
    )


def run_games_conditioned(
    home_lineup: LineupCard,
    away_lineup: LineupCard,
    pa_distributions: dict[tuple[int, int], PAOutcomeDistribution],
    target_away: int,
    target_home: int,
    score_scale: float = 1.0,
    advancement: Optional[RunnerAdvancementMatrix] = None,
    seed: Optional[int] = None,
    knobs: Optional[SimulationKnobs] = None,
    target_matches: int = 120,
    max_games: int = 10000,
) -> tuple[GameSimulationRaw, dict]:
    """Rejection-sample games, keeping only those that end exactly the target score.

    A game "ends" at the displayed score, i.e. after applying `score_scale` (the
    totals-calibration factor the pipeline would otherwise scale run arrays by) and
    rounding — so conditioning matches the final the user actually sees. Player
    stats are aggregated over the matching games only. Sampling stops once
    `target_matches` matches are collected or `max_games` have been tried.

    Returns raw arrays (over the matched games) plus meta {matches, games_run}.
    """
    if advancement is None:
        advancement = LeagueAverageMatrix()
    if knobs is None:
        knobs = SimulationKnobs()

    rng = np.random.default_rng(seed)

    def _shown(v: int) -> int:
        return int(round(v * score_scale)) if score_scale != 1.0 else int(v)

    match_home: list[int] = []
    match_away: list[int] = []
    match_extra: list[bool] = []
    stat_totals: dict[tuple[str, int], dict] = {}
    pitcher_totals: dict[tuple[str, int], dict] = {}
    # For the representative game we want one whose *raw* innings already sum to
    # the target, so its line score is internally consistent; fall back to any
    # match if none turns up.
    rep_seed_exact: Optional[int] = None
    rep_seed_any: Optional[int] = None
    games_run = 0

    while len(match_home) < target_matches and games_run < max_games:
        child_seed = int(rng.integers(0, 2**63 - 1))
        child = np.random.default_rng(child_seed)
        result = simulate_game(
            home_lineup, away_lineup, pa_distributions, advancement,
            rng=child, knobs=knobs,
        )
        games_run += 1
        if _shown(result.home_score) != target_home or _shown(result.away_score) != target_away:
            continue

        match_home.append(target_home)
        match_away.append(target_away)
        match_extra.append(result.extra_innings)
        if rep_seed_any is None:
            rep_seed_any = child_seed
        if (rep_seed_exact is None
                and result.home_score == target_home and result.away_score == target_away):
            rep_seed_exact = child_seed

        for key, line in result.player_stats.items():
            agg = stat_totals.get(key)
            if agg is None:
                stat_totals[key] = dict(line)
            else:
                for f in _STAT_FIELDS:
                    agg[f] += line[f]
        for key, line in result.pitcher_stats.items():
            agg = pitcher_totals.get(key)
            if agg is None:
                pitcher_totals[key] = dict(line)
            else:
                for f in _PITCHER_FIELDS:
                    agg[f] += line[f]

    matches = len(match_home)
    home_players, away_players = _project_player_stats(
        stat_totals, home_lineup.team_id, away_lineup.team_id, max(matches, 1)
    )
    home_pitchers, away_pitchers = _project_pitcher_stats(
        pitcher_totals, home_lineup.team_id, away_lineup.team_id, max(matches, 1)
    )

    rep_game: Optional[GameResult] = None
    rep_seed = rep_seed_exact if rep_seed_exact is not None else None
    if rep_seed is not None:
        rep_game = simulate_game(
            home_lineup, away_lineup, pa_distributions, advancement,
            rng=np.random.default_rng(rep_seed), knobs=knobs, log=True,
        )

    ha = np.asarray(match_home, dtype=np.int32)
    aa = np.asarray(match_away, dtype=np.int32)
    raw = GameSimulationRaw(
        home_runs=ha,
        away_runs=aa,
        totals=(ha + aa).astype(np.int32),
        extra_inning_flags=np.asarray(match_extra, dtype=bool),
        sample=[],
        home_players=home_players,
        away_players=away_players,
        home_pitchers=home_pitchers,
        away_pitchers=away_pitchers,
        representative=rep_game,
    )
    return raw, {"matches": matches, "games_run": games_run}


def aggregate_conditioned(
    game_id: str,
    home: str,
    away: str,
    raw: GameSimulationRaw,
    target_home: int,
    target_away: int,
) -> GameSimulationResult:
    """Summary for a conditioned run: run stats are the fixed target, player
    lines are the per-matched-game averages already on `raw`."""
    win = 1.0 if target_home > target_away else 0.0 if target_home < target_away else 0.5
    return GameSimulationResult(
        game_id=game_id,
        home=home,
        away=away,
        n=len(raw.home_runs),
        home_win_probability=win,
        home_run_mean=float(target_home),
        home_run_median=float(target_home),
        home_run_p10=float(target_home),
        home_run_p90=float(target_home),
        away_run_mean=float(target_away),
        away_run_median=float(target_away),
        away_run_p10=float(target_away),
        away_run_p90=float(target_away),
        total_mean=float(target_home + target_away),
        total_median=float(target_home + target_away),
        total_p10=float(target_home + target_away),
        total_p90=float(target_home + target_away),
        extra_inning_pct=float(raw.extra_inning_flags.mean()) if len(raw.home_runs) else 0.0,
        spread_mean=float(target_home - target_away),
        player_lines=raw.home_players + raw.away_players,
        pitcher_lines=raw.home_pitchers + raw.away_pitchers,
    )


def aggregate(
    game_id: str,
    home: str,
    away: str,
    raw: GameSimulationRaw,
) -> GameSimulationResult:
    """Build a GameSimulationResult from raw per-game arrays."""
    n = len(raw.home_runs)
    home_wins = int(np.sum(raw.home_runs > raw.away_runs))
    decisive = int(np.sum(raw.home_runs != raw.away_runs))
    spread = raw.home_runs.astype(np.int32) - raw.away_runs.astype(np.int32)
    all_players = raw.home_players + raw.away_players
    all_pitchers = raw.home_pitchers + raw.away_pitchers

    return GameSimulationResult(
        game_id=game_id,
        home=home,
        away=away,
        n=n,
        home_win_probability=home_wins / decisive if decisive > 0 else 0.5,
        home_run_mean=float(raw.home_runs.mean()),
        home_run_median=float(np.median(raw.home_runs)),
        home_run_p10=float(np.percentile(raw.home_runs, 10)),
        home_run_p90=float(np.percentile(raw.home_runs, 90)),
        away_run_mean=float(raw.away_runs.mean()),
        away_run_median=float(np.median(raw.away_runs)),
        away_run_p10=float(np.percentile(raw.away_runs, 10)),
        away_run_p90=float(np.percentile(raw.away_runs, 90)),
        total_mean=float(raw.totals.mean()),
        total_median=float(np.median(raw.totals)),
        total_p10=float(np.percentile(raw.totals, 10)),
        total_p90=float(np.percentile(raw.totals, 90)),
        extra_inning_pct=float(raw.extra_inning_flags.mean()),
        spread_mean=float(spread.mean()),
        player_lines=all_players,
        pitcher_lines=all_pitchers,
    )
