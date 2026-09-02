from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.services.media import load_media_assets, media_status


PLANTNET_UNVERIFIED_LICENSE = 'Pl@ntNet : licence non renseignée'


def _create_media_v2(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE media_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO media_metadata VALUES('media_version','2.2.0');
            INSERT INTO media_metadata VALUES('source','plantnet_gbif+atlas_living_australia_apii+dryades_flora_italia+world_flora_online');
            INSERT INTO media_metadata VALUES('catalog_taxa_total','100');

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
            """
        )
        conn.executemany(
            """
            INSERT INTO plant_image_asset(
              asset_id,taxon_id,thumbnail_url,image_url,source,source_record_id,
              source_dataset_id,license,license_raw,author,attribution_url,is_primary,
              quality_rank,verified_taxon_name,materialized
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)
            """,
            [
                (
                    'plantnet:1','t1','https://img.example/p1-thumb.jpg','https://img.example/p1.jpg',
                    'plantnet_gbif','o-1','7a3679ef-5582-4aaa-81f0-8c2545cafc81',
                    'CC BY-SA 4.0','https://creativecommons.org/licenses/by-sa/4.0/',
                    'Photo One','https://identify.plantnet.org/observations/1',1,205.0,'Taxon one'
                ),
                (
                    'wfo:1','t2','https://images.mobot.org/thumb2.jpg','https://images.mobot.org/full2.jpg',
                    'world_flora_online','image-2','MBG Floras Images:2026-06',
                    'CC BY 4.0','http://creativecommons.org/licenses/by/4.0',
                    'Photo Two','https://www.worldfloraonline.org/taxon/wfo-2',1,107.0,'Taxon two'
                ),
                (
                    'wfo:secondary','t1','https://images.mobot.org/thumb3.jpg','https://images.mobot.org/full3.jpg',
                    'world_flora_online','image-3','MBG Floras Images:2026-06',
                    'CC BY-SA 3.0','http://creativecommons.org/licenses/by-sa/3.0',
                    'Photo Three','https://www.worldfloraonline.org/taxon/wfo-1',0,107.0,'Taxon one'
                ),
                (
                    'ala-apii:1','t3',
                    'https://api.ala.org.au/images/image/ala-1/original',
                    'https://api.ala.org.au/images/image/ala-1/original',
                    'atlas_living_australia_apii','ala-1','ALA:dr413:Australian Plant Image Index',
                    'CC BY 3.0 AU','https://creativecommons.org/licenses/by/3.0/au/',
                    'Photo Four','https://images.ala.org.au/image/ala-1',1,158.0,'Taxon three'
                ),
                (
                    'dryades:145:TS193649.jpg','t4',
                    'https://dryades.units.it/dryades/plants/foto/pics/TS193649.jpg',
                    'https://dryades.units.it/dryades/plants/foto/TS193649.jpg',
                    'dryades_flora_italia','145','Dryades:Flora-d-Italia',
                    'CC BY-SA 4.0','Distributed under CC-BY-SA 4.0 license.',
                    'Andrea Moro','https://dryades.units.it/floritaly/index.php?procedure=taxon_page&tipo=all&id=145',
                    1,145.0,'Taxon four'
                ),
            ],
        )


def test_media_v2_loader_preserves_provider_and_attribution(tmp_path: Path):
    path = tmp_path / 'media-v2.sqlite'
    _create_media_v2(path)
    assets = load_media_assets(path, ['t1','t2','t3','t4'])
    assert assets['t1']['source_name'] == 'plantnet_gbif'
    assert assets['t2']['source_name'] == 'world_flora_online'
    assert assets['t3']['source_name'] == 'atlas_living_australia_apii'
    assert assets['t4']['source_name'] == 'dryades_flora_italia'
    assert assets['t1']['match_method'] == 'exact_scientific_name'
    assert assets['t1']['match_confidence'] == pytest.approx(1.0)
    assert 'Pl@ntNet / GBIF' in assets['t1']['attribution']
    assert 'World Flora Online' in assets['t2']['attribution']
    assert 'Australian Plant Image Index / ALA' in assets['t3']['attribution']
    assert 'Dryades / Flora d’Italia' in assets['t4']['attribution']
    assert assets['t3']['license'] == 'CC BY 3.0 AU'
    assert assets['t3']['license_url'] == 'https://creativecommons.org/licenses/by/3.0/au/'
    assert assets['t4']['license'] == 'CC BY-SA 4.0'
    assert assets['t4']['license_url'] == 'https://creativecommons.org/licenses/by-sa/4.0/'
    assert assets['t1']['materialized'] is False


def test_media_v2_status_reports_global_coverage_and_sources(tmp_path: Path):
    path = tmp_path / 'media-v2.sqlite'
    _create_media_v2(path)
    status = media_status(path)
    assert status['ready'] is True
    assert status['scoring_effect'] is False
    assert status['source'] == 'plantnet_gbif+atlas_living_australia_apii+dryades_flora_italia+world_flora_online'
    assert status['media_taxa_total'] == 4
    assert status['media_catalog_taxa_total'] == 100
    assert status['media_primary_taxa'] == 4
    assert status['media_coverage_pct'] == pytest.approx(4.0)
    assert status['media_source_plantnet_gbif'] == 1
    assert status['media_source_atlas_living_australia_apii'] == 1
    assert status['media_source_dryades_flora_italia'] == 1
    assert status['media_source_world_flora_online'] == 1
    assert status['media_source_gbif'] == 0
    assert status['media_unverified_license'] == 0
    assert status['media_primary_duplicate_taxa'] == 0


def test_media_v2_runtime_allows_unverified_plantnet_primary(tmp_path: Path):
    path = tmp_path / 'media-v2.sqlite'
    _create_media_v2(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE plant_image_asset SET license=?, license_raw='' WHERE taxon_id='t1' AND is_primary=1",
            (PLANTNET_UNVERIFIED_LICENSE,),
        )
    assets = load_media_assets(path, ['t1'])
    assert assets['t1']['license'] == PLANTNET_UNVERIFIED_LICENSE
    assert assets['t1']['license_url'] is None
    assert PLANTNET_UNVERIFIED_LICENSE in assets['t1']['attribution']
    status = media_status(path)
    assert status['ready'] is True
    assert status['media_unverified_license'] == 1
    assert status['media_rejected_license'] == 0


def test_media_v2_runtime_rejects_noncommercial_primary(tmp_path: Path):
    path = tmp_path / 'media-v2.sqlite'
    _create_media_v2(path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE plant_image_asset SET license='CC BY-NC-SA 4.0' WHERE taxon_id='t2' AND is_primary=1")
    assets = load_media_assets(path, ['t1','t2','t3','t4'])
    assert 't1' in assets
    assert 't2' not in assets
    assert 't3' in assets
    assert 't4' in assets
    status = media_status(path)
    assert status['ready'] is False
    assert status['media_rejected_license'] == 1
