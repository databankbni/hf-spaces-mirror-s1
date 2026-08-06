"""InningState — the live game snapshot the simulator mutates each PA.

Directly mirrors mrsim's GameState with baseball semantics:
  - yard_line/down/distance → runners_bitmap/outs
  - quarter/clock          → inning/half
  - flip_possession        → next_half_inning

Convention:
  runners_bitmap is a 3-bit integer:
    bit 0 (value 1) = runner on 1B
    bit 1 (value 2) = runner on 2B
    bit 2 (value 4) = runner on 3B
  outs: 0, 1, or 2 (inning ends when 3 outs are recorded)
  inning: 1..9; extra innings not in scope for MVP
  half: "top" (away bats) | "bottom" (home bats)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass
class InningState:
    home: str
    away: str

    inning: int = 1
    half: Literal["top", "bottom"] = "top"
    outs: int = 0
    runners_bitmap: int = 0   # 3-bit: 0b000..0b111

    score: dict = field(default_factory=dict)
    # Batting order position (0-8) for each team — persists across innings
    batting_position: dict = field(default_factory=dict)
    game_over: bool = False

    # Per-inning run totals for the box score
    home_by_inning: list[int] = field(default_factory=list)
    away_by_inning: list[int] = field(default_factory=list)
    _inning_runs: int = 0  # runs scored in current half-inning

    def __post_init__(self) -> None:
        if not self.score:
            self.score = {self.home: 0, self.away: 0}
        if not self.batting_position:
            self.batting_position = {self.home: 0, self.away: 0}

    def clone(self) -> "InningState":
        """An independent copy — used to re-run many games from one live state
        without each simulated game mutating the shared starting snapshot."""
        return InningState(
            home=self.home, away=self.away,
            inning=self.inning, half=self.half,
            outs=self.outs, runners_bitmap=self.runners_bitmap,
            score=dict(self.score),
            batting_position=dict(self.batting_position),
            game_over=self.game_over,
            home_by_inning=list(self.home_by_inning),
            away_by_inning=list(self.away_by_inning),
            _inning_runs=self._inning_runs,
        )

    # ── Derived helpers ───────────────────────────────────────────────────────

    @property
    def possession(self) -> str:
        return self.away if self.half == "top" else self.home

    @property
    def defense(self) -> str:
        return self.home if self.half == "top" else self.away

    def runner_count(self) -> int:
        return bin(self.runners_bitmap).count("1")

    # ── Mutations ─────────────────────────────────────────────────────────────

    def add_runs(self, n: int) -> None:
        self.score[self.possession] += n
        self._inning_runs += n

    def record_out(self) -> None:
        self.outs += 1
        if self.outs >= 3:
            self._end_half_inning()

    def advance_batting_position(self) -> None:
        team = self.possession
        self.batting_position[team] = (self.batting_position[team] + 1) % 9

    def _end_half_inning(self) -> None:
        # Record inning runs for box score
        if self.half == "top":
            self.away_by_inning.append(self._inning_runs)
        else:
            self.home_by_inning.append(self._inning_runs)
        self._inning_runs = 0

        if self.half == "top":
            self.half = "bottom"
        else:
            self.inning += 1
            if self.inning > 9:
                self.game_over = True
                return
            self.half = "top"

        self.outs = 0
        self.runners_bitmap = 0

    def _check_walk_off(self) -> None:
        """Call after scoring in the bottom of the 9th (or later) — ends game
        if home is now winning.

        The half ends right here, so its runs have to be flushed to the line
        score the same way `_end_half_inning` does. Without that a walk-off
        simply vanished from the box: the winning runs counted toward the score
        but never appeared in an inning, so the line score didn't add up to the
        final in roughly one game in seven.
        """
        if self.game_over:
            return
        if self.half == "bottom" and self.inning >= 9:
            if self.score[self.home] > self.score[self.away]:
                self.home_by_inning.append(self._inning_runs)
                self._inning_runs = 0
                self.game_over = True
