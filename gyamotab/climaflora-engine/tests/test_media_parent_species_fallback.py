from __future__ import annotations

import sqlite3
from pathlib import Path

from app.services.media_taxonomy import (
    load_media_assets_with_species_fallback,
    parent_species_name,
)


def _catalog(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE plant_index(taxon_id TEXT PRIMARY KEY, scientific_name TEXT NOT NULL);
            INSERT INTO plant_index VALUES('sp1','Acer saccharum');
            INSERT INTO plant_index VALUES('var1','Acer saccharum var. schneckii');
            INSERT INTO plant_index VALUES('sub1','Acer saccharum subsp. floridanum');
            INSERT INTO plant_index VALUES('hyb1','Acer × martinii');
            """
        )


def _media(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE media_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO media_metadata VALUES('media_version','2.2.0');
            INSERT INTO media_metadata VALUES('source','plantnet_gbif');
            INSERT INTO media_metadata VALUES('catalog_taxa_total','4');

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
              verified_taxon_name TEXT,
              local_filename TEXT,
              materialized INTEGER NOT NULL DEFAULT 0,
              materialization_error TEXT
            );
            INSERT INTO plant_image_asset(
              asset_id,taxon_id,thumbnail_url,image_url,source,license,author,
              attribution_url,is_primary,quality_rank,verified_taxon_name
            ) VALUES(
              'plantnet:acer','sp1','https://img.example/acer-thumb.jpg','https://img.example/acer.jpg',
              'plantnet_gbif','CC BY-SA 4.0','Photo Author',
              'https://identify.plantnet.org/observations/acer',1,200,'Acer saccharum'
            );
            """
        )


def test_parent_species_name_is_conservative():
    assert parent_species_name('Acer saccharum var. schneckii') == 'Acer saccharum'
    assert parent_species_name('Acer saccharum subsp. floridanum') == 'Acer saccharum'
    assert parent_species_name('Acer × martinii') is None
    assert parent_species_name('Acer saccharum') is None


def test_infraspecific_taxon_uses_explicit_parent_species_illustration(tmp_path: Path):
    catalog = tmp_path / 'catalog.sqlite'
    media = tmp_path / 'media.sqlite'
    _catalog(catalog)
    _media(media)

    assets = load_media_assets_with_species_fallback(media, catalog, ['sp1', 'var1', 'sub1', 'hyb1'])

    assert assets['sp1']['taxonomic_fallback'] is False
    assert assets['var1']['taxonomic_fallback'] is True
    assert assets['var1']['illustrated_taxon_name'] == 'Acer saccharum'
    assert assets['var1']['requested_taxon_name'] == 'Acer saccharum var. schneckii'
    assert assets['var1']['match_method'] == 'parent_species_illustration'
    assert 'Photo de l’espèce de référence Acer saccharum' in assets['var1']['attribution']
    assert assets['sub1']['taxonomic_fallback'] is True
    assert 'hyb1' not in assets


def test_exact_infraspecific_image_always_wins(tmp_path: Path):
    catalog = tmp_path / 'catalog.sqlite'
    media = tmp_path / 'media.sqlite'
    _catalog(catalog)
    _media(media)
    with sqlite3.connect(media) as conn:
        conn.execute(
            """
            INSERT INTO plant_image_asset(
              asset_id,taxon_id,thumbnail_url,image_url,source,license,author,
              attribution_url,is_primary,quality_rank,verified_taxon_name
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                'plantnet:var1','var1','https://img.example/var-thumb.jpg','https://img.example/var.jpg',
                'plantnet_gbif','CC BY-SA 4.0','Exact Author',
                'https://identify.plantnet.org/observations/var1',1,210,
                'Acer saccharum var. schneckii',
            ),
        )

    assets = load_media_assets_with_species_fallback(media, catalog, ['var1'])
    assert assets['var1']['asset_id'] == 'plantnet:var1'
    assert assets['var1']['taxonomic_fallback'] is False
