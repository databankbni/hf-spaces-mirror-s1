from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import Settings
from app.routers.enrichment import plant_enrichment
from app.services.media import load_media_assets, media_status


def _create_integrated_catalog(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE plant_index(
              taxon_id TEXT PRIMARY KEY,
              scientific_name TEXT NOT NULL
            );
            INSERT INTO plant_index VALUES('t1','Alpha plantus');

            CREATE TABLE plant_image_asset(
              asset_id TEXT PRIMARY KEY,
              taxon_id TEXT NOT NULL,
              thumbnail_url TEXT,
              image_url TEXT NOT NULL,
              source TEXT NOT NULL,
              source_record_id TEXT,
              source_dataset_id TEXT,
              license TEXT NOT NULL,
              license_raw TEXT,
              author TEXT,
              attribution_url TEXT,
              is_primary INTEGER NOT NULL DEFAULT 0,
              quality_rank REAL NOT NULL DEFAULT 0,
              verified_taxon_name TEXT NOT NULL,
              local_filename TEXT,
              materialized INTEGER NOT NULL DEFAULT 0,
              materialization_error TEXT
            );
            CREATE INDEX idx_cf_image_taxon
              ON plant_image_asset(taxon_id,is_primary DESC,quality_rank DESC);
            """
        )
        conn.execute(
            """
            INSERT INTO plant_image_asset(
              asset_id,taxon_id,thumbnail_url,image_url,source,source_record_id,
              source_dataset_id,license,license_raw,author,attribution_url,
              is_primary,quality_rank,verified_taxon_name,local_filename,
              materialized,materialization_error
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "gbif-example",
                "t1",
                None,
                "https://images.example.org/alpha.jpg",
                "GBIF Backbone Taxonomy Darwin Core Archive",
                "record-1",
                "dataset-1",
                "CC BY 4.0",
                "https://creativecommons.org/licenses/by/4.0/",
                "Example Author",
                "https://source.example.org/alpha",
                1,
                105.0,
                "Alpha plantus",
                None,
                0,
                None,
            ),
        )


def test_integrated_catalog_media_is_exposed_descriptively(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite"
    _create_integrated_catalog(catalog)

    assets = load_media_assets(catalog, ["t1"])
    assert list(assets) == ["t1"]
    image = assets["t1"]
    assert image["source_name"] == "gbif_backbone"
    assert image["thumbnail_url"] == "https://images.example.org/alpha.jpg"
    assert image["source_page_url"] == "https://source.example.org/alpha"
    assert image["license"] == "CC BY 4.0"
    assert image["match_method"] == "exact_scientific_name"
    assert image["match_confidence"] == 1.0

    status = media_status(catalog)
    assert status["ready"] is True
    assert status["scoring_effect"] is False
    assert status["source"] == "catalog_gbif"
    assert status["media_primary_taxa"] == 1
    assert status["media_source_gbif"] == 1


def test_enrichment_uses_integrated_catalog_media_without_scoring_effect(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite"
    _create_integrated_catalog(catalog)
    settings = Settings(
        master_db=str(catalog),
        catalog_db=str(catalog),
        media_db=str(catalog),
        catalog_enrichment_enabled=False,
    )

    payload = plant_enrichment(taxon_id=["t1"], settings=settings)
    item = payload["taxa"]["t1"]
    assert payload["scoring_effect"] is False
    assert payload["image_scoring_effect"] is False
    assert item["image_scoring_effect"] is False
    assert item["image"]["asset_id"] == "gbif-example"
    assert item["image"]["source_name"] == "gbif_backbone"
