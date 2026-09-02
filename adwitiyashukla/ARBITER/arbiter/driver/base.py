from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

from ..models import Action


class Driver:
    name = "base"

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def goto(self, url: str) -> None:
        raise NotImplementedError

    def snapshot(self) -> Tuple[List[Dict[str, Any]], bytes]:
        raise NotImplementedError

    def act(self, action: Action) -> str:
        raise NotImplementedError

    def act_with_burst(self, action: Action, frames: int, interval_ms: int
                       ) -> Tuple[str, List[Any], List[float]]:
        raise NotImplementedError

    @property
    def url(self) -> str:
        raise NotImplementedError
