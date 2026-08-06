"""Pipeline orchestration — wire data → matchup → simulator → betting.

Mirrors mrsim's pipeline.py: a thin layer the CLI and API both call so they
stay free of business logic. Given a game, it assembles lineups and the
batter-vs-pitcher PA distributions, then runs the Monte Carlo.

Falls back to league-average synthetic fingerprints whenever the Repository has
no row for a player (or no repo is provided), so the full pipeline always
produces a result — essential before real Statcast data is ingested.
"""
from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import Optional

import numpy as np

from .data.ingest import team_bullpen_pid
from .data.models import LineupCard
from .data.repository import GameRepository
from .matchup.adapters import batter_dna_from_statline, pitcher_dna_from_statline
from .matchup.context import GameContext
from .matchup.dna import (
    BatterDNA,
    LeagueAverages,
    PitcherDNA,
    shrink_batter_dna,
    shrink_pitcher_dna,
    synthetic_batter,
    synthetic_pitcher,
)
from .data.park_factors import weather_hr_multiplier
from .matchup.calibration import PlattCalibrator, TotalsCalibrator
from .matchup.log5 import league_averages_default, pa_distribution
from .data.sources.sprint_speed import speed_factor as _speed_factor
from .simulator.advancement import PersonalizedAdvancementMatrix
from .simulator.aggregate import (
    GameSimulationRaw,
    GameSimulationResult,
    aggregate,
    aggregate_conditioned,
    run_games,
    run_games_conditioned,
)
from .simulator.config import SimulationKnobs
from .simulator.outcome import PAOutcomeDistribution
from .simulator.state import InningState

# Win-probability calibrator (Platt). Fit offline on the 2023→2024 holdout and
# shipped as data/calibrator.json so the simulator's overconfident raw win probs
# are de-biased before they reach the UI / API / CLI / betting layer.
_CALIBRATOR_PATH = os.environ.get(
    "THEBEAST_CALIBRATOR_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "calibrator.json"),
)
_calibrator_cache: dict[str, Optional[PlattCalibrator]] = {}


def _load_calibrator() -> Optional[PlattCalibrator]:
    """Lazily load the shipped Platt calibrator; None if absent (→ raw probs)."""
    if "cal" not in _calibrator_cache:
        try:
            _calibrator_cache["cal"] = PlattCalibrator.load(_CALIBRATOR_PATH)
        except (FileNotFoundError, ValueError, KeyError):
            _calibrator_cache["cal"] = None
    return _calibrator_cache["cal"]


# Totals calibrator — removes the simulator's ~0.5-run total over-prediction.
_TOTALS_CALIBRATOR_PATH = os.environ.get(
    "THEBEAST_TOTALS_CALIBRATOR_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "totals_calibrator.json"),
)
_totals_cache: dict[str, Optional[TotalsCalibrator]] = {}


def _load_totals_calibrator() -> Optional[TotalsCalibrator]:
    if "cal" not in _totals_cache:
        try:
            _totals_cache["cal"] = TotalsCalibrator.load(_TOTALS_CALIBRATOR_PATH)
        except (FileNotFoundError, ValueError, KeyError):
            _totals_cache["cal"] = None
    return _totals_cache["cal"]


def _teams_from_game_id(game_id: str) -> tuple[Optional[str], Optional[str]]:
    """Parse '<date>-<away>-<home>[-g{N}]' → (home, away); (None, None) if no match."""
    import re
    base = re.sub(r"-g\d+$", "", game_id)  # drop doubleheader suffix
    parts = base.rsplit("-", 2)
    if len(parts) == 3:
        _, away, home = parts
        return home, away
    return None, None


def is_placeholder(player_id: int) -> bool:
    """True for a stand-in id rather than a real MLB player.

    Two conventions exist and both have to be recognised together, because
    anything that treats one as a person gets nonsense: the 9,000,000 block is
    what the schedule source stores for a game whose card isn't posted yet, and
    the 1000/2000 block is `_synthetic_lineup`'s fallback nine. Real MLB player
    ids are six digits and comfortably above either.
    """
    return player_id >= 9_000_000 or player_id < 100_000


def _synthetic_lineup(game_id: str, team_id: str, base: int) -> LineupCard:
    """A nine-batter synthetic lineup with one starter and one reliever."""
    return LineupCard(
        game_id=game_id,
        team_id=team_id,
        batting_order=list(range(base, base + 9)),
        starter_id=base + 100,
        bullpen_ids=[base + 200],
        confirmed=False,
        confirmed_at=None,
    )


def starter_leashes(repo, home_lineup, away_lineup, season: int,
                    knobs) -> dict[str, float]:
    """{team: pitch limit} for each side's starter, set by his own quality.

    A manager's hook is not a league constant: a pitcher getting outs is left
    in and one who isn't comes out, so a good starter's projected workload
    should be visibly longer than a poor one's. Shifting each limit off the
    league average by the pitcher's FIP is what produces that — with a single
    shared limit, every starter projected within half an inning of every other
    when the real range runs from roughly 4.4 to 6.2 IP per start.

    Falls back to the league-average limit for anyone with no usable statline
    (a placeholder starter, or a callup with nothing on file), which is the
    honest answer when there's nothing to distinguish him by.
    """
    from .data.sources.fangraphs import compute_fip
    from .simulator.config import SimulationKnobs

    if knobs is None:
        knobs = SimulationKnobs()
    base = float(knobs.starter_pitch_limit)
    slope = float(getattr(knobs, "starter_leash_per_fip", 0.0))
    ref = float(getattr(knobs, "starter_leash_reference_fip", 4.0))
    lo, hi = getattr(knobs, "starter_leash_bounds", (68, 105))

    out: dict[str, float] = {}
    for lineup in (home_lineup, away_lineup):
        limit = base
        if slope and repo is not None and lineup.starter_id > 0:
            try:
                p = repo.get_pitcher(lineup.starter_id, season)
                fip = compute_fip(p) if p is not None else 0.0
            except Exception:
                fip = 0.0
            # compute_fip returns 0.0 when it has nothing to work with; a real
            # FIP is never that low, so it doubles as the "no data" signal.
            if fip > 0.0:
                limit = float(np.clip(base - slope * (fip - ref), lo, hi))
        out[lineup.team_id] = limit
    return out


def ensure_lineups(repo, game_id: str, home: Optional[str],
                   away: Optional[str], season: int) -> None:
    """Back a game with roster lineups when none were posted/fetched yet.

    Without this, `resolve_lineups` falls through to a synthetic nine of
    placeholder ids. Those simulate fine — the run totals are sane — but they
    are not *people*, so nothing downstream that works by player can attach to
    them: a prop quoted on a real hitter has nothing to match, and the panel
    comes back empty for reasons that look nothing like the cause.

    Called by every path that simulates a game, so the cards and the betting
    pipeline agree on who is playing.

    Note this only *stores* a projection. Filtering out players who can't play
    happens in `resolve_lineups`, on the way back out — see there for why.
    """
    import dataclasses as _dc
    from .data.ingest import ROSTER_GAME_ID
    for team in (home, away):
        if not team:
            continue
        lc = repo.get_lineup(game_id, team)
        has_real = (lc is not None and lc.batting_order
                    and lc.batting_order[0] < 9_000_000)
        if has_real:
            continue
        roster = repo.get_lineup(f"{ROSTER_GAME_ID}-{season}", team)
        if roster is None or not roster.batting_order:
            continue
        if lc is None:
            repo.save_lineup(_dc.replace(roster, game_id=game_id))
        else:
            lc.batting_order = roster.batting_order
            repo.save_lineup(lc)


def available_order(repo, team: str, projected: list[int], season: int,
                    source=None) -> list[int]:
    """`projected`, with anyone not on the active roster swapped out.

    A projected order is the season's nine most-used hitters — a claim about who
    bats, and none at all about who is *available*. So a player who went on the
    IL in July stayed in it, kept being simulated, and kept showing up in the
    ranked plays.

    The active roster is the test, rather than a status code: it is the complete
    list of players eligible to appear tonight, so a projected hitter missing
    from it cannot play whatever the reason and whatever codes MLB invents.

    Replacements come from that same roster, most plate appearances first — the
    best proxy we have for who actually plays. Two things a candidate must have,
    and the second one I got wrong the first time:

    A **statline**, or the simulator falls back to league-average rates and
    quietly invents a hitter.

    A **name**. Requiring only a statline let ids through that nothing could
    resolve, and they rendered as bare numbers on the card — a lineup of
    integers, which is worse than the injured player it replaced. If we can't
    say who someone is, he does not go in the lineup.

    **The result is always the same length as what came in.** This returned a
    short lineup when it ran out of candidates, and a lineup of fewer than nine
    doesn't simulate at all — it raises, the game is marked unsimulatable, and
    it drops out of the cards, the ranked plays and the assistant together.
    That is a far worse outcome than the injured player it was avoiding, so a
    slot with nobody to fill it keeps its original occupant. Filtering a lineup
    must never cost the game.

    Returns `projected` unchanged whenever the source can't be reached, which is
    the behaviour this had before the check existed.
    """
    from .data.names import player_name
    from .data.sources.availability import MLBAvailabilitySource

    if not projected:
        return projected
    try:
        roster = (source or MLBAvailabilitySource()).roster(team)
    except Exception:
        return projected
    if not roster.usable:
        return projected

    if all(roster.can_play(pid) for pid in projected):
        return projected

    def plate_appearances(pid: int) -> float:
        try:
            b = repo.get_batter(pid, season)
        except Exception:
            return -1.0
        return float(getattr(b, "pa", 0) or 0) if b is not None else -1.0

    def nameable(pid: int) -> bool:
        try:
            return bool(player_name(repo, pid, season))
        except Exception:
            return False

    staying = {pid for pid in projected if roster.can_play(pid)}
    bench = [pid for pid in sorted(roster.active, key=lambda p: -plate_appearances(p))
             if pid not in staying and plate_appearances(pid) > 0 and nameable(pid)]

    # Substitute in place so the batting order keeps its shape, and so the
    # length is fixed by construction rather than by a check afterwards.
    out, spare = [], iter(bench)
    for pid in projected:
        if roster.can_play(pid):
            out.append(pid)
            continue
        replacement = next(spare, None)
        # Nobody to bring in. Keep the man who was there: a lineup that
        # simulates with a doubtful name beats a game that doesn't simulate.
        out.append(replacement if replacement is not None else pid)
    return out


def resolve_lineups(
    game_id: str,
    repo: Optional[GameRepository],
    home_team: Optional[str],
    away_team: Optional[str],
    check_availability: bool = True,
) -> tuple[LineupCard, LineupCard]:
    """Return (home_lineup, away_lineup), falling back to synthetic lineups.

    Availability is filtered *here*, on read, and that placement is the whole
    point. Filtering where lineups are written meant doing it in every writer,
    and there turned out to be more than one — `_fill_roster` on the upcoming
    route wrote a raw projection straight past the check, so injured players
    kept appearing however carefully `ensure_lineups` was patched. This is the
    single door every consumer already comes through: the cards, the ranked
    plays, the assistant, and the simulation cache's lineup fingerprint, which
    means a mid-afternoon IL move invalidates the cached run by itself.

    Read-time also means nothing stale is persisted. The stored projection stays
    the honest "who usually bats"; who can play tonight is applied fresh each
    time it is asked for.

    A confirmed card is never touched. The team has posted who is playing, and
    no roster endpoint improves on that.
    """
    home_lineup = away_lineup = None
    if repo is not None and home_team and away_team:
        home_lineup = repo.get_lineup(game_id, home_team)
        away_lineup = repo.get_lineup(game_id, away_team)
    if home_lineup is None:
        home_lineup = _synthetic_lineup(game_id, home_team or "HOME", base=1000)
    if away_lineup is None:
        away_lineup = _synthetic_lineup(game_id, away_team or "AWAY", base=2000)
    if check_availability and repo is not None:
        season = _season_of(game_id)
        home_lineup = _drop_unavailable(repo, home_lineup, season)
        away_lineup = _drop_unavailable(repo, away_lineup, season)
    return home_lineup, away_lineup


def _season_of(game_id: str) -> int:
    from datetime import date as _date, datetime as _dt
    try:
        return _dt.strptime(game_id[:10], "%Y-%m-%d").date().year
    except (ValueError, IndexError):
        return _date.today().year


def _drop_unavailable(repo, lineup: LineupCard, season: int) -> LineupCard:
    """One card with unavailable players replaced. Never raises."""
    import dataclasses as _dc

    if lineup is None or lineup.confirmed or not lineup.batting_order:
        return lineup
    # Placeholders aren't people, and there are two conventions for them: the
    # 9,000,000-block MLB pre-lineup fillers and the 1000/2000-block synthetic
    # nine. Checking only the first left the second to be "filtered" — every id
    # dropped as not-on-the-roster, then nine strangers promoted in their place.
    if is_placeholder(lineup.batting_order[0]):
        return lineup
    original = list(lineup.batting_order)
    try:
        order = available_order(repo, lineup.team_id, original, season)
    except Exception:
        return lineup
    if order == original:
        return lineup
    # A lineup shorter than the one that came in does not simulate — it raises,
    # and the game drops out of the cards, the ranked plays and the assistant
    # together. `available_order` guarantees the length; this refuses to pass on
    # a short one anyway, because the cost of getting that wrong is a game
    # missing from the whole app and the cost of this check is nothing.
    if len(order) != len(original):
        return lineup
    return _dc.replace(lineup, batting_order=order)


def _blend_rates(
    entries: list[tuple[tuple[float, ...], int, float]]
) -> tuple[dict[str, float], int]:
    """Blend per-season rate tuples weighted by (sample × season weight).

    `entries` is [(rates8, sample, weight)]. Returns (blended_rates, eff_sample)
    where eff_sample = Σ sample·weight (drives downstream shrinkage).
    """
    from .matchup.dna import OUTCOMES
    acc = {o: 0.0 for o in OUTCOMES}
    wsum = 0.0
    eff = 0.0
    for rates, sample, weight in entries:
        w = sample * weight
        wsum += w
        eff += w
        for o, r in zip(OUTCOMES, rates):
            acc[o] += r * w
    blended = {o: acc[o] / wsum for o in OUTCOMES} if wsum > 0 else acc
    return blended, int(round(eff))


def _batter_dna(
    repo: Optional[GameRepository], player_id: int,
    season_weights: list[tuple[int, float]],
    league: LeagueAverages, shrink_pa: int
) -> BatterDNA:
    entries: list[tuple[tuple[float, ...], int, float]] = []
    template: Optional[BatterDNA] = None
    if repo is not None:
        for season, weight in season_weights:
            s = repo.get_batter(player_id, season)
            if s is not None:
                d = batter_dna_from_statline(s)
                if template is None:
                    template = d  # most-recent (first) season for hand/platoon
                entries.append((d.as_tuple(), s.pa, weight))
    if not entries or template is None:
        dna = synthetic_batter()
        dna.player_id = player_id
        return dna
    blended, eff_pa = _blend_rates(entries)
    dna = BatterDNA(
        player_id=template.player_id, season=template.season, hand=template.hand,
        pa=eff_pa,
        single_rate=blended["single"], double_rate=blended["double"],
        triple_rate=blended["triple"], hr_rate=blended["hr"], bb_rate=blended["bb"],
        hbp_rate=blended["hbp"], k_rate=blended["k"], ipo_rate=blended["ipo"],
        platoon_mult=dict(template.platoon_mult), xwoba=template.xwoba,
    )
    return shrink_batter_dna(dna, league, shrink_pa) if shrink_pa > 0 else dna


def _pitcher_dna(
    repo: Optional[GameRepository], player_id: int,
    season_weights: list[tuple[int, float]],
    league: LeagueAverages, shrink_bf: int
) -> PitcherDNA:
    entries: list[tuple[tuple[float, ...], int, float]] = []
    template: Optional[PitcherDNA] = None
    if repo is not None:
        for season, weight in season_weights:
            s = repo.get_pitcher(player_id, season)
            if s is not None:
                d = pitcher_dna_from_statline(s)
                if template is None:
                    template = d
                entries.append((d.as_tuple(), s.bf, weight))
    if not entries or template is None:
        dna = synthetic_pitcher()
        dna.player_id = player_id
        return dna
    blended, eff_bf = _blend_rates(entries)
    dna = PitcherDNA(
        player_id=template.player_id, season=template.season, hand=template.hand,
        bf=eff_bf, role=template.role,
        single_allowed=blended["single"], double_allowed=blended["double"],
        triple_allowed=blended["triple"], hr_allowed=blended["hr"],
        bb_allowed=blended["bb"], hbp_allowed=blended["hbp"],
        k_rate=blended["k"], ipo_rate=blended["ipo"],
        platoon_mult=dict(template.platoon_mult), xfip=template.xfip,
    )
    return shrink_pitcher_dna(dna, league, shrink_bf) if shrink_bf > 0 else dna


def apply_batter_override(dna: BatterDNA, mult: dict[str, float]) -> BatterDNA:
    """Return a copy of `dna` with user multipliers applied to its outcome rates.

    `mult` keys use box-score semantics: "hits" scales the non-HR hit rates
    (1B/2B/3B) together, "home_runs" scales hr_rate, "bb" bb_rate, "k" k_rate.
    The eight rates are renormalized to sum to 1 (the delta is absorbed by
    in-play outs), so an edit dominoes through the sim rather than breaking the
    distribution. Missing/1.0 multipliers leave a rate untouched.
    """
    if not mult:
        return dna
    hf = float(mult.get("hits", 1.0))
    single = max(0.0, dna.single_rate * hf)
    double = max(0.0, dna.double_rate * hf)
    triple = max(0.0, dna.triple_rate * hf)
    hr = max(0.0, dna.hr_rate * float(mult.get("home_runs", 1.0)))
    bb = max(0.0, dna.bb_rate * float(mult.get("bb", 1.0)))
    k = max(0.0, dna.k_rate * float(mult.get("k", 1.0)))
    hbp = max(0.0, dna.hbp_rate)
    parts = [single, double, triple, hr, bb, hbp, k]
    s = sum(parts)
    # Leave at least a little room for in-play outs; if edits pushed the
    # non-out mass too high, scale them back proportionally.
    if s > 0.98:
        scale = 0.98 / s
        parts = [x * scale for x in parts]
        s = sum(parts)
    single, double, triple, hr, bb, hbp, k = parts
    ipo = max(0.0, 1.0 - s)
    return replace(
        dna, single_rate=single, double_rate=double, triple_rate=triple,
        hr_rate=hr, bb_rate=bb, hbp_rate=hbp, k_rate=k, ipo_rate=ipo,
    )


def apply_pitcher_override(dna: PitcherDNA, mult: dict[str, float]) -> PitcherDNA:
    """Return a copy of `dna` with user multipliers applied to its allowed rates.

    The pitcher mirror of ``apply_batter_override``. `mult` keys use box-score
    semantics from the pitcher's side: "hits_allowed" scales the non-HR hits he
    gives up (1B/2B/3B) together, "hr_allowed" his home runs, "bb_allowed" his
    walks, "k" his strikeouts. The eight rates are renormalized to sum to 1
    with the delta absorbed by in-play outs, so an edit dominoes through the
    matchup model rather than breaking the distribution.

    Note the direction: raising a pitcher's strikeout rate makes him *better*,
    whereas raising his hits/HR/walks makes him worse.
    """
    if not mult:
        return dna
    hf = float(mult.get("hits_allowed", 1.0))
    single = max(0.0, dna.single_allowed * hf)
    double = max(0.0, dna.double_allowed * hf)
    triple = max(0.0, dna.triple_allowed * hf)
    hr = max(0.0, dna.hr_allowed * float(mult.get("hr_allowed", 1.0)))
    bb = max(0.0, dna.bb_allowed * float(mult.get("bb_allowed", 1.0)))
    k = max(0.0, dna.k_rate * float(mult.get("k", 1.0)))
    hbp = max(0.0, dna.hbp_allowed)
    parts = [single, double, triple, hr, bb, hbp, k]
    s = sum(parts)
    # Keep room for in-play outs if edits pushed the rest too high.
    if s > 0.98:
        scale = 0.98 / s
        parts = [x * scale for x in parts]
        s = sum(parts)
    single, double, triple, hr, bb, hbp, k = parts
    ipo = max(0.0, 1.0 - s)
    return replace(
        dna, single_allowed=single, double_allowed=double, triple_allowed=triple,
        hr_allowed=hr, bb_allowed=bb, hbp_allowed=hbp, k_rate=k, ipo_rate=ipo,
    )


def _season_weights(season: int, train_seasons: Optional[list[int]],
                    decay: float) -> list[tuple[int, float]]:
    """Geometric per-season decay weights, most-recent first.

    Single-season default: [(season, 1.0)]. Multi-season blend weights each
    prior year by `decay ** years_back` so recent form dominates but older
    seasons add sample size (stabilizing per-player rate estimates).
    """
    if not train_seasons:
        return [(season, 1.0)]
    ordered = sorted(train_seasons, reverse=True)
    return [(s, decay ** i) for i, s in enumerate(ordered)]


def build_pa_distributions(
    home_lineup: LineupCard,
    away_lineup: LineupCard,
    repo: Optional[GameRepository],
    season: int,
    context: Optional[GameContext] = None,
    shrink_pa: int = 200,
    shrink_bf: int = 300,
    train_seasons: Optional[list[int]] = None,
    season_decay: float = 0.6,
    rate_overrides: Optional[dict[int, dict[str, float]]] = None,
    pitcher_overrides: Optional[dict[int, dict[str, float]]] = None,
    bullpen_by_team: Optional[dict[str, list[int]]] = None,
) -> dict[tuple[int, int], PAOutcomeDistribution]:
    """Build a Log5 PA distribution for every batter vs every relevant pitcher.

    Stored statlines hold raw rates; shrinking them toward league average by
    sample size (shrink_pa / shrink_bf pseudo-observations) curbs the
    overconfidence the 2023→2024 backtest exposed. Pass 0 to disable.

    `train_seasons` blends multiple prior seasons (decayed by `season_decay`)
    for steadier per-player estimates; default uses `season` alone.
    """
    league = league_averages_default(season)
    sw = _season_weights(season, train_seasons, season_decay)
    pitchers = {
        pid: _pitcher_dna(repo, pid, sw, league, shrink_bf)
        for lineup in (home_lineup, away_lineup)
        for pid in [lineup.starter_id, *lineup.bullpen_ids]
    }
    batters = {
        bid: _batter_dna(repo, bid, sw, league, shrink_pa)
        for lineup in (home_lineup, away_lineup)
        for bid in lineup.batting_order
    }
    # User "what-if" edits: apply per-batter rate multipliers before the matchup
    # model so the change dominoes through the whole simulation.
    if rate_overrides:
        batters = {
            bid: (apply_batter_override(dna, rate_overrides[bid])
                  if bid in rate_overrides else dna)
            for bid, dna in batters.items()
        }
    if pitcher_overrides:
        pitchers = {
            pid: (apply_pitcher_override(dna, pitcher_overrides[pid])
                  if pid in pitcher_overrides else dna)
            for pid, dna in pitchers.items()
        }
    # Fielding factors: when away team bats, home team fields (and vice versa).
    home_batter_ids = set(home_lineup.batting_order)
    home_ff = context.home_fielding_factor if context is not None else 1.0
    away_ff = context.away_fielding_factor if context is not None else 1.0

    dists: dict[tuple[int, int], PAOutcomeDistribution] = {}
    for bid, bdna in batters.items():
        # Batter's opponents are the fielding team; away batter → home team fields
        ff = home_ff if bid not in home_batter_ids else away_ff
        for pid, pdna in pitchers.items():
            dists[(bid, pid)] = pa_distribution(
                bdna, pdna, league, context=context, fielding_factor=ff
            )
    return dists


def _game_context(
    game_id: str,
    repo: Optional[GameRepository],
    season: int,
    home_team: Optional[str],
    park_season: int,
    oaa_map: Optional[dict[str, float]] = None,
    away_team: Optional[str] = None,
) -> Optional[GameContext]:
    """Build park/weather/fielding context from stored data + optional OAA map.

    Park runs factor is keyed by home team (one park per club); weather adds an
    HR multiplier; `oaa_map` supplies team fielding factors from Baseball Savant.
    Returns None when no adjustments are available (→ neutral sim).
    """
    if repo is None and oaa_map is None:
        return None

    runs_factor = 1.0
    if repo is not None and home_team:
        pf = repo.get_park_factor(home_team, park_season)
        if pf is not None:
            runs_factor = pf.runs_factor

    hr_factor = 1.0
    temp = wind_mph = wind_deg = None
    if repo is not None:
        weather = repo.get_weather(game_id)
        if weather is not None:
            temp, wind_mph, wind_deg = (
                weather.temperature_f, weather.wind_mph, weather.wind_direction_deg,
            )
            hr_factor = weather_hr_multiplier(temp, wind_mph, wind_deg)

    home_ff = away_ff = 1.0
    if oaa_map:
        if home_team:
            home_ff = oaa_map.get(home_team.upper(), 1.0)
        if away_team:
            away_ff = oaa_map.get(away_team.upper(), 1.0)

    if (runs_factor == 1.0 and hr_factor == 1.0
            and home_ff == 1.0 and away_ff == 1.0):
        return None
    return GameContext(
        game_id=game_id, venue_id=home_team or "",
        temperature_f=temp, wind_mph=wind_mph, wind_direction_deg=wind_deg,
        hr_factor=hr_factor, runs_factor=runs_factor,
        home_fielding_factor=home_ff, away_fielding_factor=away_ff,
    )


def _with_bullpen(lineup: LineupCard) -> LineupCard:
    """Give a lineup its team bullpen for the late innings when it carries none.

    Resolves to the team's aggregate bullpen statline if one is stored, else
    _pitcher_dna falls back to a league-average synthetic reliever.
    """
    if lineup.bullpen_ids:
        return lineup
    return replace(lineup, bullpen_ids=[team_bullpen_pid(lineup.team_id)])


def _prepare_sim(
    game_id: str,
    repo: Optional[GameRepository],
    home_team: Optional[str],
    away_team: Optional[str],
    season: int,
    shrink_pa: int,
    shrink_bf: int,
    use_bullpen: bool,
    train_seasons: Optional[list[int]],
    season_decay: float,
    use_context: bool,
    park_season: Optional[int],
    oaa_map: Optional[dict[str, float]],
    speed_map: Optional[dict[int, float]],
    rate_overrides: Optional[dict[int, dict[str, float]]] = None,
    pitcher_overrides: Optional[dict[int, dict[str, float]]] = None,
    bullpen_by_team: Optional[dict[str, list[int]]] = None,
) -> tuple[LineupCard, LineupCard, dict, object]:
    """Build the lineups, PA distributions, and advancement matrix shared by both
    the standard and conditioned simulation paths."""
    if home_team is None:
        parsed_home, parsed_away = _teams_from_game_id(game_id)
        home_team = home_team or parsed_home
        away_team = away_team or parsed_away
    home_lineup, away_lineup = resolve_lineups(game_id, repo, home_team, away_team)
    if use_bullpen:
        # A caller that knows the real relief arms (the live-sim path reads them
        # off the box score) supplies them here; otherwise fall back to the
        # team's aggregate bullpen.
        pens = bullpen_by_team or {}
        home_lineup = (replace(home_lineup, bullpen_ids=list(pens[home_lineup.team_id]))
                       if pens.get(home_lineup.team_id) else _with_bullpen(home_lineup))
        away_lineup = (replace(away_lineup, bullpen_ids=list(pens[away_lineup.team_id]))
                       if pens.get(away_lineup.team_id) else _with_bullpen(away_lineup))
    context = (
        _game_context(game_id, repo, season, home_team, park_season or season,
                      oaa_map=oaa_map, away_team=away_team)
        if use_context else None
    )
    dists = build_pa_distributions(home_lineup, away_lineup, repo, season, context,
                                   shrink_pa=shrink_pa, shrink_bf=shrink_bf,
                                   train_seasons=train_seasons, season_decay=season_decay,
                                   rate_overrides=rate_overrides,
                                   pitcher_overrides=pitcher_overrides)
    # Sprint-speed advancement: compute mean lineup speed relative to league avg.
    if speed_map:
        all_batter_ids = list(home_lineup.batting_order) + list(away_lineup.batting_order)
        sf = _speed_factor(speed_map, all_batter_ids)
        advancement = PersonalizedAdvancementMatrix(sf) if sf != 1.0 else None
    else:
        advancement = None
    return home_lineup, away_lineup, dists, advancement


def simulate_matchup_conditioned(
    game_id: str,
    target_away: int,
    target_home: int,
    repo: Optional[GameRepository] = None,
    home_team: Optional[str] = None,
    away_team: Optional[str] = None,
    seed: Optional[int] = None,
    season: int = 2024,
    shrink_pa: int = 200,
    shrink_bf: int = 300,
    use_bullpen: bool = True,
    train_seasons: Optional[list[int]] = None,
    season_decay: float = 0.6,
    use_context: bool = True,
    park_season: Optional[int] = None,
    calibrate_totals: bool = True,
    speed_map: Optional[dict[int, float]] = None,
    oaa_map: Optional[dict[str, float]] = None,
    rate_overrides: Optional[dict[int, dict[str, float]]] = None,
    pitcher_overrides: Optional[dict[int, dict[str, float]]] = None,
    bullpen_by_team: Optional[dict[str, list[int]]] = None,
    target_matches: int = 120,
    max_games: int = 10000,
) -> tuple[GameSimulationResult, GameSimulationRaw, dict]:
    """A *true* Monte Carlo conditioned on a user-chosen final score.

    Runs real games (identical model to ``simulate_matchup``) and keeps only
    those that finish exactly ``target_away``–``target_home`` at the displayed
    (totals-calibrated) score, then averages the box score over just those
    games. Returns (summary, raw, meta) where meta = {matches, games_run};
    ``matches == 0`` means no simulated game ended that way within the budget.
    """
    home_lineup, away_lineup, dists, advancement = _prepare_sim(
        game_id, repo, home_team, away_team, season, shrink_pa, shrink_bf,
        use_bullpen, train_seasons, season_decay, use_context, park_season,
        oaa_map, speed_map, rate_overrides=rate_overrides,
        pitcher_overrides=pitcher_overrides,
        bullpen_by_team=bullpen_by_team,
    )
    # Condition on the displayed score, i.e. after the same totals-calibration
    # scaling the standard path applies to its run arrays.
    score_scale = 1.0
    if calibrate_totals:
        tc = _load_totals_calibrator()
        if tc is not None:
            score_scale = tc.scale
    raw, meta = run_games_conditioned(
        home_lineup, away_lineup, dists, target_away, target_home,
        score_scale=score_scale, advancement=advancement, seed=seed,
        target_matches=target_matches, max_games=max_games,
    )
    result = aggregate_conditioned(
        game_id, home_lineup.team_id, away_lineup.team_id, raw, target_home, target_away
    )
    return result, raw, meta


def simulate_live_remainder(
    game_id: str,
    initial_state: InningState,
    repo: Optional[GameRepository] = None,
    home_team: Optional[str] = None,
    away_team: Optional[str] = None,
    n: int = 3000,
    seed: Optional[int] = None,
    season: int = 2024,
    knobs: Optional[SimulationKnobs] = None,
    shrink_pa: int = 200,
    shrink_bf: int = 300,
    use_bullpen: bool = True,
    train_seasons: Optional[list[int]] = None,
    season_decay: float = 0.6,
    use_context: bool = True,
    park_season: Optional[int] = None,
    initial_pitch_counts: Optional[dict[str, float]] = None,
    bullpen_by_team: Optional[dict[str, list[int]]] = None,
) -> tuple[GameSimulationResult, GameSimulationRaw]:
    """Simulate only the rest of a game already in progress.

    Identical model to ``simulate_matchup``, but every game resumes from
    ``initial_state`` — the live inning/half/outs/baserunners, the runs already
    on the board, and each side's real spot in the batting order. The resulting
    run arrays are therefore projected *finals*, and the player/pitcher lines
    cover only the plate appearances still to come.

    Two calibrations that apply to a pregame forecast are deliberately skipped
    here, because both would corrupt a mid-game number:

    * totals calibration rescales whole-game run arrays, which would also
      rescale runs that have already physically scored;
    * the Platt win-probability calibrator was fit on pregame predictions, and
      a live win probability legitimately approaches 0 or 1 — squashing it
      toward the middle would make a nearly-decided game look competitive.
    """
    home_lineup, away_lineup, dists, advancement = _prepare_sim(
        game_id, repo, home_team, away_team, season, shrink_pa, shrink_bf,
        use_bullpen, train_seasons, season_decay, use_context, park_season,
        None, None, bullpen_by_team=bullpen_by_team,
    )
    raw = run_games(home_lineup, away_lineup, dists, advancement=advancement,
                    n=n, seed=seed, knobs=knobs, initial_state=initial_state,
                    initial_pitch_counts=initial_pitch_counts,
                    starter_pitch_limits=starter_leashes(
                        repo, home_lineup, away_lineup, season, knobs))
    result = aggregate(game_id, home_lineup.team_id, away_lineup.team_id, raw)
    return result, raw


def simulate_matchup(
    game_id: str,
    repo: Optional[GameRepository] = None,
    home_team: Optional[str] = None,
    away_team: Optional[str] = None,
    n: int = 5000,
    seed: Optional[int] = None,
    season: int = 2024,
    knobs: Optional[SimulationKnobs] = None,
    shrink_pa: int = 200,
    shrink_bf: int = 300,
    use_bullpen: bool = True,
    train_seasons: Optional[list[int]] = None,
    season_decay: float = 0.6,
    calibrate: bool = True,
    use_context: bool = True,
    park_season: Optional[int] = None,
    calibrate_totals: bool = True,
    speed_map: Optional[dict[int, float]] = None,
    oaa_map: Optional[dict[str, float]] = None,
    rate_overrides: Optional[dict[int, dict[str, float]]] = None,
    pitcher_overrides: Optional[dict[int, dict[str, float]]] = None,
    bullpen_by_team: Optional[dict[str, list[int]]] = None,
    representative: bool = False,
) -> tuple[GameSimulationResult, GameSimulationRaw]:
    """Run a full game simulation, returning both the summary and raw arrays.

    `use_bullpen` hands innings after `knobs.starter_innings` to a league-average
    reliever instead of letting the starter pitch all nine — closer to real usage
    and a check on starter over-weighting. `train_seasons` blends multiple prior
    seasons (decayed) for steadier per-player rate estimates.

    `use_context` applies park-factor (runs) and weather (HR) adjustments — these
    move total runs, not win probability. `park_season` selects which season's
    park factors to use (defaults to `season`).

    `calibrate` (default on) de-biases the raw, overconfident home win
    probability through the shipped Platt calibrator; the pre-calibration value
    is preserved on `result.home_win_probability_raw`. No-op if no calibrator is
    available.
    """
    home_lineup, away_lineup, dists, advancement = _prepare_sim(
        game_id, repo, home_team, away_team, season, shrink_pa, shrink_bf,
        use_bullpen, train_seasons, season_decay, use_context, park_season,
        oaa_map, speed_map, rate_overrides=rate_overrides,
        pitcher_overrides=pitcher_overrides,
        bullpen_by_team=bullpen_by_team,
    )
    raw = run_games(home_lineup, away_lineup, dists, advancement=advancement,
                    n=n, seed=seed, knobs=knobs, representative=representative,
                    starter_pitch_limits=starter_leashes(
                        repo, home_lineup, away_lineup, season, knobs))

    # Totals calibration: scale both teams' run distributions so the projected
    # total matches reality (removes the simulator's over-prediction). Equal
    # scaling preserves the home/away comparison, so win probability is unchanged.
    if calibrate_totals:
        tc = _load_totals_calibrator()
        if tc is not None and tc.scale != 1.0:
            raw.home_runs = np.rint(raw.home_runs * tc.scale).astype(np.int32)
            raw.away_runs = np.rint(raw.away_runs * tc.scale).astype(np.int32)
            raw.totals = (raw.home_runs + raw.away_runs).astype(np.int32)

    result = aggregate(game_id, home_lineup.team_id, away_lineup.team_id, raw)

    if calibrate:
        cal = _load_calibrator()
        if cal is not None:
            result.home_win_probability_raw = result.home_win_probability
            result.home_win_probability = cal.transform_one(result.home_win_probability)

    return result, raw
