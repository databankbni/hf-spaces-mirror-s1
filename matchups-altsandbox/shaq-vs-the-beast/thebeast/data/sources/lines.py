"""A posted game line, as a value.

Its own module because the thing and the place it comes from are separate
facts. This used to live inside the ESPN source, so removing that source would
have taken the type every consumer speaks with it — which is the sort of
coupling that makes swapping a provider feel like surgery instead of a
deletion.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class GameLine:
    """One game's posted market, as of a moment, from one book."""

    game_id: str
    home: str
    away: str
    home_ml: Optional[int] = None
    away_ml: Optional[int] = None
    total: Optional[float] = None
    over_price: Optional[int] = None
    under_price: Optional[int] = None
    book: Optional[str] = None

    @property
    def usable(self) -> bool:
        """Enough to be worth recording — a moneyline pair or a total."""
        return (self.home_ml is not None and self.away_ml is not None) \
            or self.total is not None
