"""Runner advancement logic.

Encodes the probabilistic transition from (runners_bitmap, outcome) →
(new_runners_bitmap, runs_scored). The LeagueAverageMatrix uses empirical
MLB 2021-2024 Retrosheet frequencies; a future Retrosheet-loaded matrix
will implement the same interface.

Bit convention: bit 0 = 1B, bit 1 = 2B, bit 2 = 3B.
"""
from __future__ import annotations

from typing import Protocol

import numpy as np


class RunnerAdvancementMatrix(Protocol):
    def advance(
        self,
        runners: int,
        outcome: str,
        outs: int,
        rng: np.random.Generator,
    ) -> tuple[int, int]:
        """Return (new_runners_bitmap, runs_scored)."""
        ...


class LeagueAverageMatrix:
    """Hardcoded league-average runner advancement probabilities.

    Derived from Retrosheet 2021-2024 play-by-play. Resolves U-002 for MVP.
    Each method follows: (runners_bitmap, outs, rng) → (new_runners, runs).
    """

    def advance(
        self,
        runners: int,
        outcome: str,
        outs: int,
        rng: np.random.Generator,
    ) -> tuple[int, int]:
        if outcome == "HR":
            return 0, bin(runners).count("1") + 1
        if outcome == "3B":
            return 0b100, bin(runners).count("1")
        if outcome == "2B":
            return self._double(runners, rng)
        if outcome == "1B":
            return self._single(runners, rng)
        if outcome in ("BB", "HBP"):
            return self._walk(runners)
        if outcome in ("K", "IPO"):
            return self._out(runners, outs, outcome, rng)
        raise ValueError(f"unknown outcome: {outcome!r}")

    # ── Hit advancement ───────────────────────────────────────────────────────

    def _single(self, runners: int, rng: np.random.Generator) -> tuple[int, int]:
        runs = 0
        new_runners = 0b001  # batter to 1B

        # 3B runner always scores on a single
        if runners & 0b100:
            runs += 1

        # 2B runner: 64% score, 36% stop at 3B (Retrosheet average)
        if runners & 0b010:
            if rng.random() < 0.64:
                runs += 1
            else:
                new_runners |= 0b100

        # 1B runner: 45% stretch to 3B, 55% stop at 2B
        if runners & 0b001:
            if rng.random() < 0.45:
                new_runners |= 0b100
            else:
                new_runners |= 0b010

        return new_runners, runs

    def _double(self, runners: int, rng: np.random.Generator) -> tuple[int, int]:
        runs = 0
        new_runners = 0b010  # batter to 2B

        # 3B runner always scores
        if runners & 0b100:
            runs += 1

        # 2B runner always scores
        if runners & 0b010:
            runs += 1

        # 1B runner: 40% score, 60% advance to 3B (Retrosheet average)
        if runners & 0b001:
            if rng.random() < 0.40:
                runs += 1
            else:
                new_runners |= 0b100

        return new_runners, runs

    # ── Walk/HBP (force advances only) ───────────────────────────────────────

    def _walk(self, runners: int) -> tuple[int, int]:
        runs = 0
        if runners & 0b001:  # 1B occupied → force chain
            if runners & 0b010:  # 2B also occupied → 2B runner forced
                if runners & 0b100:  # Bases loaded → 3B runner scores
                    runs = 1
                    new_runners = 0b111  # all bases full again
                else:
                    new_runners = 0b111  # 1B→2B, 2B→3B, batter→1B
            else:
                # Only 1B occupied: 1B→2B, batter→1B, 3B holds
                new_runners = 0b001 | 0b010 | (runners & 0b100)
        else:
            # No force: batter takes 1B, all existing runners hold
            new_runners = runners | 0b001
        return new_runners, runs

    # ── Outs (K and IPO) ─────────────────────────────────────────────────────

    def _out(
        self,
        runners: int,
        outs: int,
        outcome: str,
        rng: np.random.Generator,
    ) -> tuple[int, int]:
        """Strikeouts: runners freeze. IPO: small probability of advancement."""
        if outcome == "K":
            return runners, 0

        # IPO: groundout-like vs flyout-like mix
        # ~25% of IPOs with a runner on 3B and < 2 outs → runner scores (sac fly)
        # ~10% with runner on 2B and < 2 outs → runner advances to 3B
        runs = 0
        new_runners = runners

        if outs < 2:
            if runners & 0b100:
                if rng.random() < 0.25:  # tag up from 3B
                    runs += 1
                    new_runners &= ~0b100  # 3B runner scored
            if runners & 0b010 and not (runners & 0b100 and runs):
                if rng.random() < 0.10:  # advance from 2B to 3B
                    new_runners = (new_runners & ~0b010) | 0b100

        return new_runners, runs


_LEAGUE_SPEED_FT_S = 27.0  # approximate 2021-2024 MLB sprint speed average


class PersonalizedAdvancementMatrix(LeagueAverageMatrix):
    """Sprint-speed-adjusted runner advancement.

    Scales the base League Average advancement probabilities (1st→3rd on single,
    scoring from 2nd on single, scoring from 1st on double) by `speed_factor`,
    which is the mean sprint speed of the batting team's lineup divided by the
    league average (27 ft/s). Values > 1.0 boost advancement; < 1.0 reduces it.
    Capped at ±30% relative to base to prevent extreme distortions.
    """

    def __init__(self, speed_factor: float = 1.0) -> None:
        self._sf = max(0.70, min(1.30, speed_factor))

    def _p(self, base: float) -> float:
        return min(0.95, max(0.05, base * self._sf))

    def _single(self, runners: int, rng: np.random.Generator) -> tuple[int, int]:
        runs = 0
        new_runners = 0b001
        if runners & 0b100:
            runs += 1
        if runners & 0b010:
            if rng.random() < self._p(0.64):
                runs += 1
            else:
                new_runners |= 0b100
        if runners & 0b001:
            if rng.random() < self._p(0.45):
                new_runners |= 0b100
            else:
                new_runners |= 0b010
        return new_runners, runs

    def _double(self, runners: int, rng: np.random.Generator) -> tuple[int, int]:
        runs = 0
        new_runners = 0b010
        if runners & 0b100:
            runs += 1
        if runners & 0b010:
            runs += 1
        if runners & 0b001:
            if rng.random() < self._p(0.40):
                runs += 1
            else:
                new_runners |= 0b100
        return new_runners, runs
