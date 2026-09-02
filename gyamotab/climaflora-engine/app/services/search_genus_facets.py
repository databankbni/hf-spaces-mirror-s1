from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
import sqlite3
from time import perf_counter

import numpy as np

GENUS_FUNCTION_PREFIX = "__CF_GENUS_INITIAL_"


def normalize_genus_initial(value: str | None) -> str:
    initial = str(value or "ALL").strip().upper()
    if initial == "ALL":
        return "ALL"
    return initial if len(initial) == 1 and "A" <= initial <= "Z" else "ALL"


def scientific_name_genus_initial(scientific_name: str | None) -> str:
    text = str(scientific_name or "").strip()
    text = re.sub(r"^[×x]\s+", "", text, flags=re.IGNORECASE)
    if text.startswith("×"):
        text = text[1:].lstrip()
    if not text:
        return "#"
    initial = text[0].upper()
    return initial if "A" <= initial <= "Z" else "#"


def split_genus_navigation(functions: list[str] | tuple[str, ...] | None) -> tuple[list[str], str]:
    scientific: list[str] = []
    selected = "ALL"
    for raw in functions or []:
        value = str(raw)
        if value.startswith(GENUS_FUNCTION_PREFIX):
            candidate = normalize_genus_initial(value[len(GENUS_FUNCTION_PREFIX) :])
            if candidate != "ALL":
                selected = candidate
            continue
        scientific.append(value)
    return scientific, selected


@lru_cache(maxsize=4)
def _load_genus_initials_cached(
    catalog_path: str,
    catalog_size: int,
    catalog_mtime_ns: int,
) -> tuple[np.ndarray, np.ndarray]:
    del catalog_size, catalog_mtime_ns
    path = Path(catalog_path)
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as conn:
        rows = conn.execute(
            "SELECT taxon_id,scientific_name FROM plant_index ORDER BY taxon_id"
        ).fetchall()
    taxon_ids = np.asarray([str(row[0]) for row in rows], dtype=object)
    initials = np.asarray(
        [scientific_name_genus_initial(row[1]) for row in rows],
        dtype="<U1",
    )
    return taxon_ids, initials


def load_genus_initials(
    catalog_path: str | Path,
    expected_taxon_ids: np.ndarray,
) -> np.ndarray:
    path = Path(catalog_path).resolve()
    stat = path.stat()
    taxon_ids, initials = _load_genus_initials_cached(
        str(path),
        stat.st_size,
        stat.st_mtime_ns,
    )
    if taxon_ids.shape != expected_taxon_ids.shape or not np.array_equal(taxon_ids, expected_taxon_ids):
        raise RuntimeError("Genus facet taxonomy ordinals are misaligned with the scientific runtime")
    return initials


def apply_genus_initial_facet(
    catalog_path: str | Path,
    expected_taxon_ids: np.ndarray,
    ordered_ordinals: np.ndarray,
    *,
    genus_initial: str = "ALL",
    offset: int = 0,
    limit: int = 50,
) -> tuple[np.ndarray, np.ndarray, dict[str, int], float]:
    """Count initials over the whole matched population, then filter and paginate."""
    started = perf_counter()
    initials = load_genus_initials(catalog_path, expected_taxon_ids)
    matching_initials = initials[ordered_ordinals]

    valid = (matching_initials >= "A") & (matching_initials <= "Z")
    values, counts = np.unique(matching_initials[valid], return_counts=True)
    facets = {"ALL": int(ordered_ordinals.shape[0])}
    facets.update({str(value): int(count) for value, count in zip(values, counts, strict=True)})

    selected = normalize_genus_initial(genus_initial)
    if selected == "ALL":
        filtered = ordered_ordinals
    else:
        filtered = ordered_ordinals[matching_initials == selected]

    safe_offset = max(0, int(offset))
    safe_limit = max(1, int(limit))
    page = filtered[safe_offset : safe_offset + safe_limit]
    return filtered, page, facets, perf_counter() - started
