from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

from app.services.media import load_media_assets, media_status


def _load_ingester():
    path = Path(__file__).resolve().parents[1] / ".github" / "tools" / "media_ingest_wikimedia_v1_1.py"
    spec = importlib.util.spec_from_file_location("media_ingest_wikimedia_v1_1", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_uncertain_media_is_retained_for_blurred_display():
    ingester = _load_ingester()
    blurred, reason = ingester.display_uncertainty(
        "Aa maderoi or paleacea.jpg", "Aa maderoi", "wikidata_p18"
    )
    assert blurred is True
    assert reason == "ambiguous_media_label"

    blurred, reason = ingester.display_uncertainty(
        "IMG 2048.jpg", "Akebia trifoliata", "wikidata_p373_category"
    )
    assert blurred is True
    assert reason == "category_member_without_explicit_taxon_name"

    blurred, reason = ingester.display_uncertainty(
        "Akebia trifoliata flowers.jpg", "Akebia trifoliata", "wikidata_p373_category"
    )
    assert blurred is False
    assert reason is None


def test_media_v11_loader_exposes_blur_metadata(tmp_path: Path):
    db = tmp_path / "media.sqlite"
    with sqlite3.connect(db) as conn:
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
              display_blurred INTEGER NOT NULL DEFAULT 0,
              ambiguity_reason TEXT,
              match_method TEXT NOT NULL,
              match_confidence REAL NOT NULL,
              quality_rank REAL NOT NULL DEFAULT 0,
              retrieved_at TEXT NOT NULL,
              last_checked_at TEXT,
              source_metadata_json TEXT
            );
            CREATE UNIQUE INDEX uq_media_primary ON plant_image_asset(taxon_id) WHERE is_primary=1;
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
              materialized,display_blurred,ambiguity_reason,match_method,match_confidence,
              quality_rank,retrieved_at,last_checked_at,source_metadata_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1,0,1,?,?,?,?,?,?,?)
            """,
            (
                "t1", "asset", "wikimedia_commons",
                "https://commons.wikimedia.org/wiki/File:Example.jpg",
                "https://upload.wikimedia.org/wikipedia/commons/a/ab/Example_960.jpg",
                "https://upload.wikimedia.org/wikipedia/commons/a/ab/Example_480.jpg",
                "CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/",
                "A", "A · CC BY 4.0 · Wikimedia Commons", 1200, 800, "image/jpeg",
                "ambiguous_media_label", "exact_scientific_name", 0.95, 120.0,
                "2026-08-21T11:00:00Z", "2026-08-21T11:00:00Z", "{}",
            ),
        )
        conn.execute(
            "INSERT INTO media_ingest_attempt VALUES(?,?,?,?,?,?,?,?)",
            ("t1", "Example taxon", "selected_blurred", "ambiguous_media_label", "asset", "CC BY 4.0", 1, "2026-08-21T11:00:00Z"),
        )

    asset = load_media_assets(db, ["t1"])["t1"]
    assert asset["display_blurred"] is True
    assert asset["ambiguity_reason"] == "ambiguous_media_label"

    status = media_status(db)
    assert status["ready"] is True
    assert status["media_blurred_primary"] == 1
    assert status["media_clear_primary"] == 0
    assert status["uncertain_media_policy"] == "retain_blurred"
