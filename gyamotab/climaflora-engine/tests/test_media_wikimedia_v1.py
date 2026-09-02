from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

from app.config import Settings
from app.routers.enrichment import plant_enrichment
from app.services.media import (
    canonical_open_license,
    load_media_assets,
    media_quality_rank,
    media_status,
    safe_image_url,
    safe_source_url,
)


def _load_ingester_module():
    path = Path(__file__).resolve().parents[1] / ".github" / "tools" / "media_ingest_wikimedia.py"
    spec = importlib.util.spec_from_file_location("media_ingest_wikimedia", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _create_media_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE plant_image_asset(
              taxon_id TEXT NOT NULL,
              asset_id TEXT PRIMARY KEY,
              source_name TEXT NOT NULL,
              source_page_url TEXT NOT NULL,
              image_url TEXT,
              thumbnail_url TEXT NOT NULL,
              license TEXT NOT NULL,
              license_url TEXT,
              author TEXT,
              attribution TEXT,
              width INTEGER,
              height INTEGER,
              mime_type TEXT,
              is_primary INTEGER NOT NULL DEFAULT 0,
              materialized INTEGER NOT NULL DEFAULT 0,
              match_method TEXT NOT NULL,
              match_confidence REAL NOT NULL,
              quality_rank REAL NOT NULL DEFAULT 0,
              retrieved_at TEXT NOT NULL,
              last_checked_at TEXT,
              source_metadata_json TEXT
            );
            CREATE UNIQUE INDEX uq_plant_image_asset_primary
              ON plant_image_asset(taxon_id) WHERE is_primary=1;
            CREATE TABLE media_ingest_attempt(
              taxon_id TEXT PRIMARY KEY,
              scientific_name TEXT NOT NULL,
              result TEXT NOT NULL,
              reason TEXT,
              source_asset_id TEXT,
              license TEXT,
              duration_ms INTEGER NOT NULL DEFAULT 0,
              checked_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO plant_image_asset(
              taxon_id,asset_id,source_name,source_page_url,image_url,thumbnail_url,
              license,license_url,author,attribution,width,height,mime_type,is_primary,
              materialized,match_method,match_confidence,quality_rank,retrieved_at,last_checked_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1,0,?,?,?,?,?)
            """,
            (
                "t1",
                "commons-valid",
                "wikimedia_commons",
                "https://commons.wikimedia.org/wiki/File:Akebia_trifoliata.jpg",
                "https://upload.wikimedia.org/wikipedia/commons/a/ab/Akebia_trifoliata_960.jpg",
                "https://upload.wikimedia.org/wikipedia/commons/a/ab/Akebia_trifoliata_480.jpg",
                "CC BY-SA 4.0",
                "https://creativecommons.org/licenses/by-sa/4.0/",
                "Example Author",
                "Example Author · CC BY-SA 4.0 · Wikimedia Commons",
                1920,
                1280,
                "image/jpeg",
                "exact_scientific_name",
                0.95,
                125.0,
                "2026-08-21T10:00:00Z",
                "2026-08-21T10:00:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO media_ingest_attempt(
              taxon_id,scientific_name,result,reason,source_asset_id,license,duration_ms,checked_at
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                "t1",
                "Akebia trifoliata",
                "selected",
                None,
                "commons-valid",
                "CC BY-SA 4.0",
                12,
                "2026-08-21T10:00:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO media_ingest_attempt(
              taxon_id,scientific_name,result,reason,source_asset_id,license,duration_ms,checked_at
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                "t2",
                "Taxon absent",
                "no_result",
                "no_exact_p225_with_p18",
                None,
                None,
                8,
                "2026-08-21T10:00:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO media_ingest_attempt(
              taxon_id,scientific_name,result,reason,source_asset_id,license,duration_ms,checked_at
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                "t3",
                "Taxon interdit",
                "rejected_license",
                "no_whitelisted_candidate",
                None,
                None,
                9,
                "2026-08-21T10:00:00Z",
            ),
        )


def _create_catalog(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE plant_index(
              taxon_id TEXT PRIMARY KEY,
              scientific_name TEXT NOT NULL
            );
            INSERT INTO plant_index(taxon_id,scientific_name)
              VALUES('t1','Akebia trifoliata');
            """
        )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("CC0 1.0", "CC0 1.0"),
        ("Public domain", "Public domain"),
        ("CC BY 4.0", "CC BY 4.0"),
        ("CC BY-SA 4.0", "CC BY-SA 4.0"),
        ("CC BY-NC 4.0", None),
        ("CC BY-NC-SA 4.0", None),
        ("CC BY-ND 4.0", None),
        ("CC BY-NC-ND 4.0", None),
        ("", None),
        (None, None),
        ("All rights reserved", None),
        ("Unknown", None),
    ],
)
def test_license_whitelist_is_conservative(raw, expected):
    assert canonical_open_license(raw) == expected


def test_external_media_urls_are_https_and_host_restricted():
    assert safe_image_url("https://upload.wikimedia.org/wikipedia/commons/a/a1/x.jpg")
    assert safe_source_url("https://commons.wikimedia.org/wiki/File:x.jpg")
    assert safe_image_url("http://upload.wikimedia.org/wikipedia/commons/a/a1/x.jpg") is None
    assert safe_image_url("https://evil.example/x.jpg") is None
    assert safe_source_url("https://evil.example/wiki/File:x.jpg") is None
    assert safe_source_url("javascript:alert(1)") is None


def test_media_rank_prefers_exact_high_quality_assets():
    weak = media_quality_rank(exact_scientific_name=True, width=400, height=300)
    strong = media_quality_rank(
        exact_scientific_name=True,
        width=1200,
        height=800,
        author="A",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        mime_type="image/jpeg",
    )
    exact_id = media_quality_rank(exact_taxon_id=True, width=1200, height=800, mime_type="image/jpeg")
    assert strong > weak
    assert exact_id > weak


def test_sidecar_loader_and_status_are_descriptive_only(tmp_path: Path):
    media_db = tmp_path / "media.sqlite"
    _create_media_db(media_db)

    assets = load_media_assets(media_db, ["t1", "t2"])
    assert list(assets) == ["t1"]
    assert assets["t1"]["source_name"] == "wikimedia_commons"
    assert assets["t1"]["match_method"] == "exact_scientific_name"
    assert assets["t1"]["match_confidence"] == pytest.approx(0.95)
    assert assets["t1"]["materialized"] is False

    status = media_status(media_db)
    assert status["ready"] is True
    assert status["scoring_effect"] is False
    assert status["media_primary_taxa"] == 1
    assert status["media_missing"] == 1
    assert status["media_rejected_license"] == 1
    assert status["media_primary_duplicate_taxa"] == 0
    assert status["licenses"] == {"CC BY-SA 4.0": 1}


def test_descriptive_endpoint_exposes_image_without_scoring_effect(tmp_path: Path):
    catalog = tmp_path / "catalog.sqlite"
    media_db = tmp_path / "media.sqlite"
    _create_catalog(catalog)
    _create_media_db(media_db)
    settings = Settings(
        master_db=str(catalog),
        catalog_db=str(catalog),
        media_db=str(media_db),
        catalog_enrichment_enabled=False,
    )

    payload = plant_enrichment(taxon_id=["t1"], settings=settings)
    item = payload["taxa"]["t1"]
    assert payload["scoring_effect"] is False
    assert payload["image_scoring_effect"] is False
    assert item["image_scoring_effect"] is False
    assert item["image"]["asset_id"] == "commons-valid"
    assert item["image"]["source_name"] == "wikimedia_commons"


def test_ingester_selects_only_unique_exact_scientific_names(tmp_path: Path):
    ingester = _load_ingester_module()
    catalog = tmp_path / "catalog.sqlite"
    with sqlite3.connect(catalog) as conn:
        conn.executescript(
            """
            CREATE TABLE plant_index(taxon_id TEXT PRIMARY KEY, scientific_name TEXT NOT NULL);
            INSERT INTO plant_index VALUES('t1','Akebia trifoliata');
            INSERT INTO plant_index VALUES('t2','Exact unique');
            INSERT INTO plant_index VALUES('t3','Ambiguous name');
            INSERT INTO plant_index VALUES('t4','Ambiguous name');
            """
        )

    all_rows = ingester.select_taxa(catalog, None, 20, 0)
    assert ("t1", "Akebia trifoliata") in all_rows
    assert ("t2", "Exact unique") in all_rows
    assert all(name != "Ambiguous name" for _, name in all_rows)
    assert ingester.select_taxa(catalog, "Akebia trifoliata", 20, 0) == [
        ("t1", "Akebia trifoliata")
    ]
    with pytest.raises(RuntimeError, match="exact taxon lookup must resolve once"):
        ingester.select_taxa(catalog, "Ambiguous name", 20, 0)


def test_ingester_accepts_only_commons_file_path_links():
    ingester = _load_ingester_module()
    assert ingester.filename_from_p18(
        "https://commons.wikimedia.org/wiki/Special:FilePath/Akebia_trifoliata.jpg"
    ) == "Akebia trifoliata.jpg"
    assert ingester.filename_from_p18("https://evil.example/Special:FilePath/x.jpg") is None
