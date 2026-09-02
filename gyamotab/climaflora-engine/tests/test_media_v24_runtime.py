from __future__ import annotations

import sqlite3
from pathlib import Path

from app.services.media_catalog import load_media_asset_sets
from app.services.media_taxonomy import load_media_assets_with_species_fallback


def _media(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            '''
            CREATE TABLE media_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE media_taxon(
              taxon_id TEXT PRIMARY KEY,
              scientific_name TEXT NOT NULL,
              image_count INTEGER NOT NULL,
              status TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE plant_image_asset(
              asset_id TEXT PRIMARY KEY,
              taxon_id TEXT NOT NULL,
              position INTEGER NOT NULL,
              thumbnail_url TEXT NOT NULL,
              image_url TEXT NOT NULL,
              source TEXT NOT NULL,
              source_record_id TEXT,
              source_dataset_id TEXT,
              license TEXT NOT NULL,
              license_raw TEXT,
              author TEXT,
              attribution_url TEXT NOT NULL,
              is_primary INTEGER NOT NULL,
              quality_rank REAL NOT NULL,
              verified_taxon_name TEXT NOT NULL,
              local_filename TEXT,
              materialized INTEGER NOT NULL,
              materialization_error TEXT,
              UNIQUE(taxon_id,position)
            );
            '''
        )
        conn.executemany(
            'INSERT INTO media_taxon VALUES(?,?,?,?,?)',
            [
                ('species', 'Acer saccharum', 3, 'ready', '2026-08-25T00:00:00Z'),
                ('variety', 'Acer saccharum var. schneckii', 0, 'no_image', '2026-08-25T00:00:00Z'),
            ],
        )
        rows = [
            ('i1', 1, 'plantnet_gbif', 'CC BY-SA 4.0', 300.0),
            ('i2', 2, 'wikimedia_commons', 'CC0', 200.0),
            ('i3', 3, 'world_flora_online', 'CC BY 4.0', 100.0),
        ]
        conn.executemany(
            '''
            INSERT INTO plant_image_asset(
              asset_id,taxon_id,position,thumbnail_url,image_url,source,source_record_id,source_dataset_id,
              license,license_raw,author,attribution_url,is_primary,quality_rank,verified_taxon_name,
              local_filename,materialized,materialization_error
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''',
            [
                (
                    asset_id,
                    'species',
                    position,
                    f'https://images.example/{asset_id}-thumb.jpg',
                    f'https://images.example/{asset_id}.jpg',
                    source,
                    asset_id,
                    'dataset',
                    licence,
                    licence,
                    f'Author {asset_id}',
                    f'https://source.example/{asset_id}',
                    1 if position == 1 else 0,
                    rank,
                    'Acer saccharum',
                    None,
                    0,
                    None,
                )
                for asset_id, position, source, licence, rank in rows
            ],
        )


def _catalog(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE plant_index(taxon_id TEXT PRIMARY KEY, scientific_name TEXT NOT NULL)')
        conn.executemany(
            'INSERT INTO plant_index VALUES(?,?)',
            [
                ('species', 'Acer saccharum'),
                ('variety', 'Acer saccharum var. schneckii'),
            ],
        )


def test_media_v24_runtime_exposes_three_ranked_images(tmp_path: Path):
    media = tmp_path / 'media.sqlite'
    _media(media)
    sets = load_media_asset_sets(media, ['species'])
    assert [image['asset_id'] for image in sets['species']] == ['i1', 'i2', 'i3']
    assert [image['position'] for image in sets['species']] == [1, 2, 3]
    assert sets['species'][0]['source_name'] == 'plantnet_gbif'
    assert sets['species'][1]['source_name'] == 'wikimedia_commons'
    assert sets['species'][1]['license_url'] == 'https://creativecommons.org/publicdomain/zero/1.0/'


def test_media_v24_compatibility_view_embeds_alternates_and_parent_fallback(tmp_path: Path):
    media = tmp_path / 'media.sqlite'
    catalog = tmp_path / 'catalog.sqlite'
    _media(media)
    _catalog(catalog)

    exact = load_media_assets_with_species_fallback(media, catalog, ['species'])['species']
    assert exact['asset_id'] == 'i1'
    assert exact['image_count'] == 3
    assert [image['asset_id'] for image in exact['alternates']] == ['i2', 'i3']
    assert exact['taxonomic_fallback'] is False

    fallback = load_media_assets_with_species_fallback(media, catalog, ['variety'])['variety']
    assert fallback['asset_id'] == 'i1'
    assert fallback['image_count'] == 3
    assert fallback['taxonomic_fallback'] is True
    assert fallback['illustrated_taxon_name'] == 'Acer saccharum'
    assert all(image['taxonomic_fallback'] is True for image in fallback['alternates'])
