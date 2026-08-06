"""PA outcomes and the Cholesky batting form sampler.

Mirrors mrsim's outcome.py:
  - PAOutcomeEnum    ↔  play-type literals
  - PAOutcomeDistribution ↔  per-play probability struct with .sample()
  - sample_batting_form   ↔  sample_drive_form (correlated form multipliers)

The Cholesky correlation captures the "hot inning" effect: if the leadoff
batter reaches base, subsequent batters in that half-inning see a correlated
lift in their contact and power form. ρ = 0.30 (same as mrsim default).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


class PAOutcomeEnum(str, Enum):
    SINGLE = "1B"
    DOUBLE = "2B"
    TRIPLE = "3B"
    HOME_RUN = "HR"
    WALK = "BB"
    HIT_BY_PITCH = "HBP"
    STRIKEOUT = "K"
    IN_PLAY_OUT = "IPO"


# Cholesky factor for a 2×2 with correlation ρ between contact & power form.
# L = [[1, 0], [ρ, sqrt(1 - ρ²)]]  — same construction as mrsim.
_DEFAULT_RHO = 0.30
_L = np.array([[1.0, 0.0], [_DEFAULT_RHO, np.sqrt(1 - _DEFAULT_RHO**2)]])


def sample_batting_form(
    rng: np.random.Generator,
    rho: float = _DEFAULT_RHO,
    sigma: float = 0.18,
    clip: tuple[float, float] = (0.55, 1.55),
) -> tuple[float, float]:
    """Return (contact_form, power_form) multipliers, correlated via Cholesky.

    Resampled once per half-inning. Multiplied into PA outcome probabilities:
      - contact_form scales hit-in-play rates (1B, 2B, 3B)
      - power_form  scales home run rate
    """
    if rho == _DEFAULT_RHO:
        L = _L
    else:
        L = np.array([[1.0, 0.0], [rho, np.sqrt(max(0.0, 1 - rho**2))]])
    z = rng.standard_normal(2)
    cor = L @ z
    contact = float(np.clip(1.0 + sigma * cor[0], clip[0], clip[1]))
    power = float(np.clip(1.0 + sigma * cor[1], clip[0], clip[1]))
    return contact, power


@dataclass
class PAOutcomeDistribution:
    """Pre-computed PA outcome probability distribution for one batter-pitcher pair.

    All eight probabilities must sum to 1.0 ± 1e-6. The .sample() method
    draws one outcome using the multinomial CDF (same efficiency as mrsim's
    per-play rng.random() comparisons).
    """
    batter_id: int
    pitcher_id: int
    single: float
    double: float
    triple: float
    home_run: float
    walk: float
    hit_by_pitch: float
    strikeout: float
    in_play_out: float

    def __post_init__(self) -> None:
        total = (self.single + self.double + self.triple + self.home_run
                 + self.walk + self.hit_by_pitch + self.strikeout + self.in_play_out)
        if abs(total - 1.0) > 1e-4:
            raise ValueError(f"PAOutcomeDistribution probabilities sum to {total:.6f}, expected 1.0")

    def _probs(self) -> np.ndarray:
        return np.array([
            self.single, self.double, self.triple, self.home_run,
            self.walk, self.hit_by_pitch, self.strikeout, self.in_play_out,
        ])

    _OUTCOMES = ["1B", "2B", "3B", "HR", "BB", "HBP", "K", "IPO"]

    def sample(self, rng: np.random.Generator) -> str:
        """Draw one PA outcome string."""
        p = self._probs()
        r = rng.random()
        cumsum = 0.0
        for i, prob in enumerate(p):
            cumsum += prob
            if r < cumsum:
                return self._OUTCOMES[i]
        return self._OUTCOMES[-1]

    def with_form(
        self,
        contact_form: float,
        power_form: float,
    ) -> "PAOutcomeDistribution":
        """Return a new distribution with form multipliers applied and renormalized.

        contact_form scales 1B/2B/3B rates; power_form scales HR.
        Walk, HBP, K, IPO rates hold their weight but renormalize.
        """
        s = self.single * contact_form
        d = self.double * contact_form
        t = self.triple * contact_form
        hr = self.home_run * power_form
        bb = self.walk
        hbp = self.hit_by_pitch
        k = self.strikeout
        ipo = self.in_play_out
        total = s + d + t + hr + bb + hbp + k + ipo
        return PAOutcomeDistribution(
            batter_id=self.batter_id,
            pitcher_id=self.pitcher_id,
            single=s / total,
            double=d / total,
            triple=t / total,
            home_run=hr / total,
            walk=bb / total,
            hit_by_pitch=hbp / total,
            strikeout=k / total,
            in_play_out=ipo / total,
        )
