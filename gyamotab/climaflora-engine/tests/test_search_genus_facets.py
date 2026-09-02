from __future__ import annotations

import sqlite3

import numpy as np

from app.services.search_genus_facets import (
    GENUS_FUNCTION_PREFIX,
    apply_genus_initial_facet,
    split_genus_navigation,
)


def test_genus_facet_counts_full_matching_population_before_pagination(tmp_path):
    db = tmp_path / "catalog.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE plant_index(taxon_id TEXT PRIMARY KEY,scientific_name TEXT)")
        conn.executemany(
            "INSERT INTO plant_index(taxon_id,scientific_name) VALUES(?,?)",
            [
                ("001", "Acer campestre"),
                ("002", "Acer rubrum"),
                ("003", "Betula pendula"),
                ("004", "× Cupressocyparis leylandii"),
                ("005", "Diospyros kaki"),
                ("006", "Diospyros lotus"),
            ],
        )

    taxon_ids = np.asarray(["001", "002", "003", "004", "005", "006"], dtype=object)
    ordered = np.asarray([5, 0, 3, 1, 2], dtype=np.int64)

    filtered, page, facets, _elapsed = apply_genus_initial_facet(
        db,
        taxon_ids,
        ordered,
        genus_initial="ALL",
        offset=0,
        limit=2,
    )
    assert filtered.tolist() == ordered.tolist()
    assert page.tolist() == [5, 0]
    assert facets == {"ALL": 5, "A": 2, "B": 1, "C": 1, "D": 1}

    filtered_a, page_a, facets_a, _elapsed = apply_genus_initial_facet(
        db,
        taxon_ids,
        ordered,
        genus_initial="A",
        offset=0,
        limit=100,
    )
    assert filtered_a.tolist() == [0, 1]
    assert page_a.tolist() == [0, 1]
    assert facets_a == facets


def test_genus_navigation_token_is_removed_from_scientific_functions():
    functions, genus = split_genus_navigation(
        ["FOOD_HUMAN", f"{GENUS_FUNCTION_PREFIX}M", "POLLINATOR"]
    )
    assert functions == ["FOOD_HUMAN", "POLLINATOR"]
    assert genus == "M"
