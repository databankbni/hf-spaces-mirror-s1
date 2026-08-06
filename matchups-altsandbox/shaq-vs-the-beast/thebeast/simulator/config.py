"""Tunable constants for the simulator pipeline.

All simulation parameters live here — nothing is hardcoded in the engine.
Matches mrsim's config.py pattern exactly: dataclass-of-dataclasses, each
sub-knob governing one aspect of context adjustment.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class WindKnobs:
    """Wind adjusts HR probability for outdoor parks."""
    threshold_mph: float = 8.0
    cap_mph: float = 20.0
    hr_headwind_penalty: float = 0.12   # fraction lost at cap (blowing in)
    hr_tailwind_bonus: float = 0.10     # fraction gained at cap (blowing out)


@dataclass
class SimulationKnobs:
    """All tunable constants for a single game simulation.

    Defaults reproduce realistic MLB behavior for league-average inputs.
    Pass a custom instance to /api/sim or run_backtest to explore sensitivity.
    """
    n_iterations: int = 5000
    home_field_advantage: float = 1.02   # HR probability multiplier for home batters
    use_context: bool = True             # apply park + weather adjustments
    use_platoon: bool = True             # apply platoon splits
    use_cholesky: bool = True            # per-inning batting form correlation
    cholesky_rho: float = 0.30          # ρ for (contact_form, power_form) correlation
    cholesky_sigma: float = 0.18        # σ for form multipliers (same as mrsim)
    cholesky_clip: tuple[float, float] = (0.55, 1.55)  # same bounds as mrsim
    # Pitcher transition (U-005 resolved to heuristic for MVP)
    # Hard ceiling on a start. Deliberately well beyond a normal outing: the
    # pitch count below is what should end it. When this was 5 it *was* the
    # binding rule, so no simulated starter ever recorded an 18th out and every
    # "under 17.5 outs" prop priced at a certainty.
    starter_innings: int = 8
    # Pitch counts — the real hook. A start ends at the limit, so an
    # inefficient outing finishes early rather than running to the ceiling.
    use_pitch_counts: bool = True
    starter_pitch_limit: int = 95       # league-average hook
    # Managers do not all pull at the same count: the leash varies with the
    # pitcher, the score and the matchup. Drawing each start's limit around the
    # average reproduces the real spread of outings — without it every start
    # ends at nearly the same pitch, which piles the outs distribution onto one
    # value and makes any prop line near it read as a lock.
    starter_pitch_jitter: float = 12.0
    # A manager's leash is not the same for everyone: a pitcher who is getting
    # outs is left in, and one who isn't comes out. Each starter's limit is
    # therefore shifted off the league average by his own quality (FIP), which
    # is what turns a single league-wide projection into a per-pitcher one.
    # Without it every starter projects to within half an inning of every
    # other, when the real range runs from about 4.4 to 6.2 IP per start.
    starter_leash_per_fip: float = 9.0     # pitches gained per run of better FIP
    starter_leash_reference_fip: float = 4.00   # league-average FIP
    starter_leash_bounds: tuple[int, int] = (68, 105)
    # How the start is *going* shortens the leash rather than ending the day.
    # A manager weighs trouble, he does not run a checklist: a pitcher who has
    # given up five is on a shorter rope than one cruising, but he is not
    # automatically gone — he may well finish the inning, and a good one often
    # finishes the next. Modelling trouble as a hard threshold made every
    # battered start end at the same instant; modelling it as pressure on the
    # count keeps the effect while letting the rest of the game have a say.
    #
    # Each term is measured against what a manager tolerates without reaching
    # for the phone, so ordinary trouble costs nothing: two runs over a start,
    # a run in an inning, two men reaching back to back.
    starter_trouble_free_runs: int = 2
    starter_trouble_free_inning_runs: int = 1
    starter_trouble_free_baserunners: int = 2
    # Pitches of leash given up per unit of trouble beyond that. Roughly a
    # batter or two per run — enough to bring the hook forward materially over
    # a bad inning without deciding the outing on its own.
    starter_trouble_per_run: float = 5.0
    starter_trouble_per_inning_run: float = 4.0
    starter_trouble_per_baserunner: float = 3.0
    # Trouble never fully erases the leash — even a battering leaves a starter
    # some rope, because the bullpen is finite and somebody has to eat innings.
    starter_trouble_max: float = 30.0
    # Relief arms are worked through in order, each handed roughly one inning
    # before the next comes in. The last arm listed absorbs whatever is left, so
    # a short list still covers the game.
    reliever_pitch_limit: int = 20
    # Shrinkage parameters (U-001 resolved to these empirical values)
    shrink_pa: int = 200                # batter: PA count at which weight = 0.5
    shrink_bf: int = 300                # pitcher: BF count at which weight = 0.5
    wind: WindKnobs = field(default_factory=WindKnobs)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class BacktestKnobs:
    """All knobs for one walk-forward backtest run.

    Mirrors mrsim's BacktestKnobs exactly, substituting calendar-day decay
    for week-based decay (baseball season is 26 weeks vs NFL's 18).
    """
    train_seasons: list[int] = field(default_factory=lambda: [2021, 2022, 2023])
    holdout_season: int = 2024
    n_sims: int = 200               # simulations per game (fewer than live for speed)
    decay_halflife_days: float = 42.0   # prior-season weight half-life (6-week analog)
    pipeline: SimulationKnobs = field(default_factory=SimulationKnobs)

    def as_dict(self) -> dict:
        return asdict(self)


def prior_weight(days_into_season: int, halflife_days: float) -> float:
    """Exponential decay weight for prior-season plays. Same formula as mrsim."""
    return float(0.5 ** (days_into_season / halflife_days))
