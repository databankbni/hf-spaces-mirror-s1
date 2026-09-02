from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FINALIZER = ROOT / '.github' / 'tools' / 'finalize_media_v2_catalog.py'


def _catalog(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE plant_index(taxon_id TEXT PRIMARY KEY, scientific_name TEXT NOT NULL)')
        conn.executemany(
            'INSERT INTO plant_index(taxon_id,scientific_name) VALUES(?,?)',
            [('t1', 'Acer nigrum'), ('t2', 'Acer rubrum'), ('t3', 'Acer saccharum')],
        )


def _sidecar(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            '''
            CREATE TABLE media_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE plant_image_asset(
              asset_id TEXT PRIMARY KEY, taxon_id TEXT NOT NULL, thumbnail_url TEXT,
              image_url TEXT NOT NULL, source TEXT NOT NULL, source_record_id TEXT,
              source_dataset_id TEXT, license TEXT NOT NULL, license_raw TEXT, author TEXT,
              attribution_url TEXT, is_primary INTEGER NOT NULL DEFAULT 0,
              quality_rank REAL NOT NULL DEFAULT 0, verified_taxon_name TEXT NOT NULL,
              local_filename TEXT, materialized INTEGER NOT NULL DEFAULT 0,
              materialization_error TEXT
            );
            '''
        )
        conn.executemany(
            'INSERT INTO media_metadata(key,value) VALUES(?,?)',
            [('media_version', '2.3.0'), ('source', 'test'), ('catalog_taxa_total', '3')],
        )
        rows = [
            ('a1', 't1', 300.0, 'plantnet_gbif', 'CC BY-SA 4.0', 1),
            ('a2', 't1', 250.0, 'atlas_living_australia_apii', 'CC BY 3.0 AU', 0),
            ('a3', 't1', 200.0, 'dryades_flora_italia', 'CC BY-SA 4.0', 0),
            ('a4', 't1', 150.0, 'wikimedia_commons', 'CC0', 0),
            ('a5', 't1', 100.0, 'world_flora_online', 'CC BY 4.0', 0),
            ('b1', 't3', 180.0, 'wikimedia_commons', 'Public domain', 1),
        ]
        conn.executemany(
            '''
            INSERT INTO plant_image_asset(
              asset_id,taxon_id,thumbnail_url,image_url,source,source_record_id,source_dataset_id,
              license,license_raw,author,attribution_url,is_primary,quality_rank,verified_taxon_name,
              local_filename,materialized,materialization_error
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''',
            [
                (
                    asset_id,
                    taxon_id,
                    f'https://images.example/{asset_id}-thumb.jpg',
                    f'https://images.example/{asset_id}.jpg',
                    source,
                    asset_id,
                    'dataset',
                    licence,
                    licence,
                    f'Author {asset_id}',
                    f'https://source.example/{asset_id}',
                    primary,
                    rank,
                    'Acer nigrum' if taxon_id == 't1' else 'Acer saccharum',
                    None,
                    0,
                    None,
                )
                for asset_id, taxon_id, rank, source, licence, primary in rows
            ],
        )


def test_media_v24_indexes_every_taxon_and_keeps_top_three(tmp_path: Path):
    catalog = tmp_path / 'catalog.sqlite'
    sidecar = tmp_path / 'media.sqlite'
    before = tmp_path / 'before.json'
    report_path = tmp_path / 'report.json'
    _catalog(catalog)
    _sidecar(sidecar)
    before.write_text(
        json.dumps(
            {
                'status': 'ready',
                'media_version': '2.3.0',
                'catalog_taxa_total': 3,
                'scoring_effect': False,
                'matrix': {'cumulative_unique_taxa': 2, 'cumulative_coverage_pct': 66.6667},
            }
        ),
        encoding='utf-8',
    )

    subprocess.run(
        [
            sys.executable,
            str(FINALIZER),
            '--catalog',
            str(catalog),
            '--sidecar',
            str(sidecar),
            '--base-report',
            str(before),
            '--report',
            str(report_path),
        ],
        check=True,
        cwd=ROOT,
    )

    report = json.loads(report_path.read_text(encoding='utf-8'))
    assert report['status'] == 'ready'
    assert report['media_version'] == '2.4.0'
    assert report['storage']['catalog_taxa_rows'] == 3
    assert report['storage']['max_images_per_taxon'] == 3
    assert report['storage']['input_asset_rows'] == 6
    assert report['storage']['retained_asset_rows'] == 4
    assert report['storage']['pruned_asset_rows'] == 2
    assert report['storage']['taxa_with_images'] == 2
    assert report['storage']['taxa_without_images'] == 1
    assert report['storage']['image_count_distribution'] == {'0': 1, '1': 1, '3': 1}

    with sqlite3.connect(sidecar) as conn:
        meta = dict(conn.execute('SELECT key,value FROM media_metadata'))
        assert meta['media_version'] == '2.4.0'
        assert meta['storage_model'] == 'media_taxon+plant_image_asset_top3'
        assert meta['media_taxa_indexed'] == '3'
        assert meta['max_images_per_taxon'] == '3'

        taxa = conn.execute(
            'SELECT taxon_id,image_count,status FROM media_taxon ORDER BY taxon_id'
        ).fetchall()
        assert taxa == [('t1', 3, 'ready'), ('t2', 0, 'no_image'), ('t3', 1, 'ready')]

        t1 = conn.execute(
            'SELECT asset_id,position,is_primary,source,license,author FROM plant_image_asset WHERE taxon_id=? ORDER BY position',
            ('t1',),
        ).fetchall()
        assert [row[0] for row in t1] == ['a1', 'a2', 'a3']
        assert [row[1] for row in t1] == [1, 2, 3]
        assert [row[2] for row in t1] == [1, 0, 0]
        assert t1[1][3:] == ('atlas_living_australia_apii', 'CC BY 3.0 AU', 'Author a2')

        assert conn.execute(
            'SELECT COUNT(*) FROM (SELECT taxon_id FROM plant_image_asset GROUP BY taxon_id HAVING COUNT(*)>3)'
        ).fetchone()[0] == 0
        assert conn.execute(
            'SELECT COUNT(*) FROM plant_image_asset WHERE (position=1)!=(is_primary=1)'
        ).fetchone()[0] == 0
