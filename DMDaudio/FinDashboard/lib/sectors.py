"""Pure selection logic for Sector View's multi-sector picker.

No DB or Streamlit dependencies — just transforms over the curated bucket map
(`{sector: [IdCode, ...]}`) and the sub-sector map (`{IdCode: SubSector}`).
Kept here (rather than inline in app.py) so the union / pool / filter
behaviour is unit-testable in isolation.
"""
from __future__ import annotations


def union_idcodes(curated: dict[str, list[str]], chosen_sectors: list[str]) -> list[str]:
    """Companies in ANY of the chosen sectors, de-duplicated, in selection order.

    Sectors are visited in the order chosen; companies keep each sector's
    existing (revenue-sorted) order. First occurrence wins on the rare overlap.
    Unknown sector names are ignored.
    """
    seen: set[str] = set()
    out: list[str] = []
    for sector in chosen_sectors:
        for idc in curated.get(sector, []):
            if idc not in seen:
                seen.add(idc)
                out.append(idc)
    return out


def subsector_counts(
    idcodes: list[str], sub_sector_map: dict[str, str], unclassified: str
) -> dict[str, int]:
    """Count companies per sub-sector across `idcodes`.

    Companies with no sub-sector are bucketed under `unclassified` so they
    stay reachable from the picker.
    """
    counts: dict[str, int] = {}
    for idc in idcodes:
        sub = sub_sector_map.get(idc, "") or unclassified
        counts[sub] = counts.get(sub, 0) + 1
    return counts


def filter_by_subsectors(
    idcodes: list[str],
    sub_sector_map: dict[str, str],
    chosen_subs: list[str],
    unclassified: str,
) -> list[str]:
    """Keep only the idcodes whose (resolved) sub-sector is in `chosen_subs`.

    Input order is preserved. A company with no sub-sector matches when
    `unclassified` is among the chosen sub-sectors.
    """
    chosen = set(chosen_subs)
    return [
        idc for idc in idcodes
        if (sub_sector_map.get(idc, "") or unclassified) in chosen
    ]
