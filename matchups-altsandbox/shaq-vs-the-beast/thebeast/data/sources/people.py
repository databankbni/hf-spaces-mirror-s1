"""Player-name lookup from the MLB Stats API `people` endpoint.

Names live in this app's batter/pitcher statlines, so a player who appears in a
confirmed lineup or as a probable starter but has no stored statline for the
season (a callup, a recent trade, a rookie) would otherwise render as his bare
numeric id. This resolves those ids to real names in one batched call and caches
them process-wide, so a name is fetched at most once for the life of the server.

Best-effort: an unreachable/changed source just leaves the id unresolved, and
the caller falls back to the numeric id exactly as before.
"""
from __future__ import annotations

from typing import Any, Iterable

import requests

_PEOPLE_URL = "https://statsapi.mlb.com/api/v1/people"


class MLBPeopleSource:
    """Batched id → full-name lookup with a process-wide cache."""

    # id -> name (or "" when the source was reached but had no name, so a known
    # miss isn't retried on every request). Small and long-lived, like the
    # other request-scoped caches in this app.
    _cache: dict[int, str] = {}

    def _fetch_json(self, ids: list[int]) -> Any:
        # Tight timeout: this can fire on a page load, so a slow/unreachable
        # host must fail fast rather than hang the box score.
        resp = requests.get(
            _PEOPLE_URL,
            params={"personIds": ",".join(str(i) for i in ids)},
            timeout=(3, 5),
        )
        resp.raise_for_status()
        return resp.json()

    def names(self, ids: Iterable[int]) -> dict[int, str]:
        """{id: name} for every resolvable id; ids with no name are omitted.

        Only ids not already cached trigger a network call, and they're fetched
        in a single batched request. Never raises.
        """
        wanted = [int(i) for i in ids if int(i) > 0]
        missing = [i for i in wanted if i not in self._cache]
        if missing:
            try:
                data = self._fetch_json(missing)
                for person in data.get("people", []) or []:
                    pid = person.get("id")
                    name = person.get("fullName") or person.get("firstLastName")
                    if pid is not None:
                        self._cache[int(pid)] = name or ""
            except Exception:
                pass  # leave them uncached-as-missing; caller falls back to id
            # Mark any still-unresolved id as a known miss so we don't refetch
            # it every request (the source was reached but had nothing).
            for i in missing:
                self._cache.setdefault(i, "")
        return {i: self._cache[i] for i in wanted if self._cache.get(i)}
