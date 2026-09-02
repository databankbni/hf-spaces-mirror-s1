from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import quantiles
from typing import Any, Iterable

import numpy as np

from app.domain.models import Horizon, Scenario
from app.services.climate import ChelsaCogProvider

METHOD = "WCVP_TDWG3_CHELSA_REGION_PROXY"
METHOD_VERSION = "1.2"
SOURCE_REF = "WCVP native TDWG level-3 distribution + TDWG WGSRPD polygons + CHELSA-bioclim v2.1"
CORE_VARIABLES = ("bio01", "bio05", "bio06", "bio12", "bio15")
VARIABLE_WEIGHTS = {"bio01": 1.0, "bio05": 1.0, "bio06": 1.2, "bio12": 0.8, "bio15": 0.7}
VARIABLE_GROUPS = {"bio01": "V", "bio05": "M", "bio06": "M", "bio12": "E", "bio15": "E"}

DERIVED_SCHEMA = """
PRAGMA foreign_keys=OFF;
CREATE TABLE IF NOT EXISTS build_metadata (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS plant_index (
  taxon_id TEXT PRIMARY KEY,
  scientific_name TEXT NOT NULL,
  common_name TEXT,
  functions_json TEXT NOT NULL DEFAULT '[]',
  regulatory_veto INTEGER NOT NULL DEFAULT 0,
  regulatory_reason TEXT,
  confidence TEXT NOT NULL DEFAULT 'UNKNOWN',
  powo_id TEXT,
  scientific_name_id TEXT,
  references_url TEXT
);
CREATE TABLE IF NOT EXISTS plant_profile (
  taxon_id TEXT PRIMARY KEY,
  family TEXT,
  genus TEXT,
  taxon_rank TEXT,
  taxonomic_status TEXT,
  life_form TEXT,
  plant_scope TEXT,
  wcvp_climate TEXT,
  references_url TEXT,
  native_region_count INTEGER NOT NULL DEFAULT 0,
  introduced_region_count INTEGER NOT NULL DEFAULT 0,
  legacy_enrichment_available INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS taxon_native_region (
  taxon_id TEXT NOT NULL,
  location_id TEXT NOT NULL,
  PRIMARY KEY (taxon_id, location_id)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS region_climate_summary (
  location_id TEXT NOT NULL,
  variable TEXT NOT NULL,
  sample_count INTEGER NOT NULL,
  q05 REAL,
  q20 REAL,
  q50 REAL,
  q80 REAL,
  q95 REAL,
  PRIMARY KEY (location_id, variable)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS climate_envelope (
  envelope_id INTEGER PRIMARY KEY,
  taxon_id TEXT NOT NULL,
  variable TEXT NOT NULL,
  hard_low REAL,
  optimum_low REAL,
  optimum_high REAL,
  hard_high REAL,
  weight REAL NOT NULL DEFAULT 1.0,
  group_code TEXT NOT NULL CHECK (group_code IN ('M','V','E','A')),
  fatal INTEGER NOT NULL DEFAULT 0,
  confidence TEXT NOT NULL DEFAULT 'UNKNOWN',
  source_ref TEXT,
  method TEXT,
  method_version TEXT,
  UNIQUE(taxon_id, variable, method_version)
);
CREATE TABLE IF NOT EXISTS soil_envelope (
  envelope_id INTEGER PRIMARY KEY,
  taxon_id TEXT NOT NULL,
  variable TEXT NOT NULL,
  hard_low REAL,
  optimum_low REAL,
  optimum_high REAL,
  hard_high REAL,
  weight REAL NOT NULL DEFAULT 1.0,
  group_code TEXT NOT NULL DEFAULT 'E',
  fatal INTEGER NOT NULL DEFAULT 0,
  confidence TEXT NOT NULL DEFAULT 'UNKNOWN',
  source_ref TEXT,
  method TEXT,
  method_version TEXT,
  UNIQUE(taxon_id, variable, method_version)
);
CREATE TABLE IF NOT EXISTS evidence (
  evidence_id INTEGER PRIMARY KEY,
  taxon_id TEXT NOT NULL,
  claim_type TEXT NOT NULL,
  claim_value TEXT,
  source_id TEXT,
  source_reference TEXT,
  source_version TEXT,
  extraction_method TEXT,
  confidence TEXT,
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_plant_scientific_name ON plant_index(scientific_name);
CREATE INDEX IF NOT EXISTS idx_plant_common_name ON plant_index(common_name);
CREATE INDEX IF NOT EXISTS idx_envelope_taxon ON climate_envelope(taxon_id);
CREATE INDEX IF NOT EXISTS idx_envelope_variable_taxon ON climate_envelope(variable, taxon_id);
CREATE INDEX IF NOT EXISTS idx_soil_envelope_taxon ON soil_envelope(taxon_id);
CREATE INDEX IF NOT EXISTS idx_evidence_taxon ON evidence(taxon_id);
CREATE INDEX IF NOT EXISTS idx_native_region_location ON taxon_native_region(location_id, taxon_id);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _functions_expr(alias: str = "e") -> str:
    flags = [
        ("human_food", "FOOD_HUMAN"),
        ("animal_food", "FOOD_ANIMAL"),
        ("medicinal", "MEDICINAL"),
        ("materials", "MATERIALS"),
        ("fuel", "FUEL"),
        ("n_fixer", "N_FIXER"),
        ("pollinator_candidate_broad", "POLLINATOR"),
        ("soil_function_flag", "SOIL_FUNCTION"),
    ]
    pieces = [f"CASE WHEN coalesce({alias}.{col},0)<>0 THEN '\"{label}\",' ELSE '' END" for col, label in flags]
    return "'[' || rtrim(" + " || ".join(pieces) + ", ',') || ']'"


def normalize_tdwg_code(value: Any) -> str:
    """Normalize WCVP/TDWG identifiers to the WGSRPD level-3 code (e.g. TDWG:CLM -> CLM)."""
    code = str(value or "").strip().upper()
    for prefix in ("TDWG:", "TDWG_", "TDWG-"):
        if code.startswith(prefix):
            code = code[len(prefix):]
            break
    return code.strip()


def feature_tdwg_code(feature: dict[str, Any]) -> str:
    props = feature.get("properties") or {}
    for key in ("LEVEL3_COD", "LEVEL3_CODE", "level3_cod", "level3_code", "TDWG3", "tdwg3", "code", "CODE"):
        value = props.get(key)
        if value not in (None, ""):
            return normalize_tdwg_code(value)
    return ""


def _polygon_rings(geometry: dict[str, Any]) -> list[list[list[float]]]:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if gtype == "Polygon":
        return [coords] if coords else []
    if gtype == "MultiPolygon":
        return [poly for poly in coords if poly]
    return []


def _point_in_ring(x: float, y: float, ring: list[list[float]]) -> bool:
    inside = False
    if len(ring) < 3:
        return False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        intersects = ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-15) + xi)
        if intersects:
            inside = not inside
        j = i
    return inside


def _point_in_polygon(x: float, y: float, rings: list[list[float]]) -> bool:
    if not rings or not _point_in_ring(x, y, rings[0]):
        return False
    return not any(_point_in_ring(x, y, hole) for hole in rings[1:])


def _ring_area(ring: list[list[float]]) -> float:
    area = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[i + 1][0], ring[i + 1][1]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def sample_points_for_geometry(geometry: dict[str, Any], max_points: int = 9) -> list[tuple[float, float]]:
    polygons = _polygon_rings(geometry)
    if not polygons:
        return []
    polygons = sorted(polygons, key=lambda rings: _ring_area(rings[0]) if rings else 0.0, reverse=True)
    out: list[tuple[float, float]] = []
    for rings in polygons:
        if len(out) >= max_points:
            break
        outer = rings[0]
        xs = [p[0] for p in outer]
        ys = [p[1] for p in outer]
        if not xs or not ys:
            continue
        minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
        fractions = (0.15, 0.35, 0.5, 0.65, 0.85)
        candidates = [
            (minx + (maxx - minx) * fx, miny + (maxy - miny) * fy)
            for fy in fractions for fx in fractions
        ]
        # Prefer central points, then spread outward deterministically.
        candidates.sort(key=lambda pt: (pt[0] - (minx + maxx) / 2) ** 2 + (pt[1] - (miny + maxy) / 2) ** 2)
        for x, y in candidates:
            if _point_in_polygon(x, y, rings) and all(abs(x-a) > 1e-9 or abs(y-b) > 1e-9 for a, b in out):
                out.append((x, y))
                if len(out) >= max_points:
                    break
        if not out:
            # Last-resort mean vertex coordinate; may be coastal, so CHELSA nodata filtering still applies.
            out.append((sum(xs) / len(xs), sum(ys) / len(ys)))
    return out[:max_points]


def _q(values: list[float], p: float) -> float:
    return float(np.quantile(np.asarray(values, dtype=float), p))


@dataclass
class ScientificBuildService:
    master_db: str
    derived_db: str
    status_path: str
    climate_manifest: str
    tdwg_path: str
    tdwg_urls: list[str]
    sample_points: int = 9
    min_coverage: float = 0.50

    _thread: threading.Thread | None = None
    _lock = threading.Lock()

    def _write_status(self, **updates: Any) -> None:
        path = Path(self.status_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        current: dict[str, Any] = {}
        if path.exists():
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                current = {}
        current.update(updates)
        current["updated_at"] = utcnow()
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def status(self) -> dict[str, Any]:
        path = Path(self.status_path)
        if not path.exists():
            return {"phase": "not_started", "ready": False, "derived_db": self.derived_db}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"phase": "error", "ready": False, "error": f"status read failed: {exc}"}
        data["derived_present"] = Path(self.derived_db).exists()
        return data

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run_guarded, name="climaflora-scientific-build", daemon=True)
            self._thread.start()

    def _run_guarded(self) -> None:
        try:
            self._run()
        except Exception as exc:  # noqa: BLE001
            self._write_status(phase="error", ready=False, error=f"{type(exc).__name__}: {exc}")

    def _wait_master(self) -> None:
        self._write_status(phase="waiting_master", ready=False, error=None, started_at=utcnow())
        master = Path(self.master_db)
        for _ in range(900):
            if master.exists() and master.stat().st_size > 0:
                try:
                    with sqlite3.connect(f"file:{master.resolve()}?mode=ro", uri=True) as conn:
                        needed = {"plant_taxa", "wcvp_distribution", "climat_enrichment_preferred"}
                        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                        if needed <= tables:
                            return
                except sqlite3.Error:
                    pass
            time.sleep(2)
        raise RuntimeError("master database did not become ready")

    def _download_tdwg(self) -> Path:
        target = Path(self.tdwg_path)
        if target.exists() and target.stat().st_size > 1000:
            return target
        errors = []
        target.parent.mkdir(parents=True, exist_ok=True)
        for url in self.tdwg_urls:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "ClimaFlora/0.6"})
                with urllib.request.urlopen(req, timeout=60) as response, target.open("wb") as out:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                payload = json.loads(target.read_text(encoding="utf-8"))
                if payload.get("type") != "FeatureCollection" or not payload.get("features"):
                    raise RuntimeError("unexpected TDWG GeoJSON payload")
                return target
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{url} -> {type(exc).__name__}: {exc}")
                try:
                    target.unlink()
                except OSError:
                    pass
        raise RuntimeError("TDWG level3 download failed: " + " | ".join(errors))

    @staticmethod
    def _distribution_profile(d: sqlite3.Connection) -> dict[str, Any]:
        def grouped(column: str, limit: int = 20) -> list[dict[str, Any]]:
            rows = d.execute(
                f"""
                SELECT coalesce(trim({column}), '<NULL>') AS value, COUNT(*) AS n
                FROM master.wcvp_distribution
                GROUP BY coalesce(trim({column}), '<NULL>')
                ORDER BY n DESC, value
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [{"value": str(value), "count": int(n)} for value, n in rows]

        case_rows = d.execute(
            """
            SELECT
              SUM(CASE WHEN trim(location_id) <> '' AND trim(location_id)=upper(trim(location_id)) THEN 1 ELSE 0 END),
              SUM(CASE WHEN trim(location_id) <> '' AND trim(location_id)<>upper(trim(location_id)) THEN 1 ELSE 0 END),
              COUNT(*)
            FROM master.wcvp_distribution
            WHERE location_id IS NOT NULL
            """
        ).fetchone()
        return {
            "establishment_means": grouped("establishment_means"),
            "occurrence_status": grouped("occurrence_status"),
            "location_id_samples": grouped("location_id", 20),
            "location_case": {
                "uppercase_rows": int(case_rows[0] or 0),
                "nonuppercase_rows": int(case_rows[1] or 0),
                "rows_with_location": int(case_rows[2] or 0),
            },
        }

    @staticmethod
    def _populate_native_regions(d: sqlite3.Connection, profile: dict[str, Any]) -> dict[str, Any]:
        """Populate native TDWG links using auditable conservative strategies."""
        d.execute("DELETE FROM taxon_native_region")

        d.execute(
            """
            INSERT OR IGNORE INTO taxon_native_region(taxon_id,location_id)
            SELECT CAST(w.taxon_id AS TEXT),
                   CASE
                     WHEN upper(trim(w.location_id)) LIKE 'TDWG:%' THEN substr(upper(trim(w.location_id)), 6)
                     WHEN upper(trim(w.location_id)) LIKE 'TDWG_%' THEN substr(upper(trim(w.location_id)), 6)
                     WHEN upper(trim(w.location_id)) LIKE 'TDWG-%' THEN substr(upper(trim(w.location_id)), 6)
                     ELSE upper(trim(w.location_id))
                   END
            FROM master.wcvp_distribution w
            WHERE w.location_id IS NOT NULL AND trim(w.location_id)<>''
              AND lower(trim(coalesce(w.occurrence_status,'present'))) NOT LIKE '%absent%'
              AND lower(trim(coalesce(w.occurrence_status,'present'))) NOT LIKE '%extinct%'
              AND (
                    lower(trim(coalesce(w.establishment_means,''))) IN ('native','indigenous','endemic')
                 OR lower(trim(coalesce(w.establishment_means,''))) LIKE '%/native'
                 OR lower(trim(coalesce(w.establishment_means,''))) LIKE '%#native'
                 OR lower(trim(coalesce(w.establishment_means,''))) LIKE '%:native'
              )
              AND EXISTS (SELECT 1 FROM plant_index p WHERE p.taxon_id=CAST(w.taxon_id AS TEXT))
            """
        )
        explicit_links = int(d.execute("SELECT COUNT(*) FROM taxon_native_region").fetchone()[0])
        explicit_taxa = int(d.execute("SELECT COUNT(DISTINCT taxon_id) FROM taxon_native_region").fetchone()[0])

        case_info = profile.get("location_case", {})
        case_links = 0
        case_taxa = 0
        if explicit_links == 0 and int(case_info.get("uppercase_rows", 0)) > 0 and int(case_info.get("nonuppercase_rows", 0)) > 0:
            d.execute(
                """
                INSERT OR IGNORE INTO taxon_native_region(taxon_id,location_id)
                SELECT CAST(w.taxon_id AS TEXT),
                   CASE
                     WHEN upper(trim(w.location_id)) LIKE 'TDWG:%' THEN substr(upper(trim(w.location_id)), 6)
                     WHEN upper(trim(w.location_id)) LIKE 'TDWG_%' THEN substr(upper(trim(w.location_id)), 6)
                     WHEN upper(trim(w.location_id)) LIKE 'TDWG-%' THEN substr(upper(trim(w.location_id)), 6)
                     ELSE upper(trim(w.location_id))
                   END
                FROM master.wcvp_distribution w
                WHERE w.location_id IS NOT NULL AND trim(w.location_id)<>''
                  AND trim(w.location_id)=upper(trim(w.location_id))
                  AND lower(trim(coalesce(w.occurrence_status,'present'))) NOT LIKE '%absent%'
                  AND lower(trim(coalesce(w.occurrence_status,'present'))) NOT LIKE '%extinct%'
                  AND EXISTS (SELECT 1 FROM plant_index p WHERE p.taxon_id=CAST(w.taxon_id AS TEXT))
                """
            )
            case_links = int(d.execute("SELECT COUNT(*) FROM taxon_native_region").fetchone()[0])
            case_taxa = int(d.execute("SELECT COUNT(DISTINCT taxon_id) FROM taxon_native_region").fetchone()[0])

        summary_added_before = int(d.execute("SELECT COUNT(*) FROM taxon_native_region").fetchone()[0])
        d.execute(
            """
            INSERT OR IGNORE INTO taxon_native_region(taxon_id,location_id)
            SELECT CAST(w.taxon_id AS TEXT),
                   CASE
                     WHEN upper(trim(w.location_id)) LIKE 'TDWG:%' THEN substr(upper(trim(w.location_id)), 6)
                     WHEN upper(trim(w.location_id)) LIKE 'TDWG_%' THEN substr(upper(trim(w.location_id)), 6)
                     WHEN upper(trim(w.location_id)) LIKE 'TDWG-%' THEN substr(upper(trim(w.location_id)), 6)
                     ELSE upper(trim(w.location_id))
                   END
            FROM master.wcvp_distribution w
            JOIN master.plant_distribution_summary s ON s.taxon_id=w.taxon_id
            WHERE w.location_id IS NOT NULL AND trim(w.location_id)<>''
              AND coalesce(s.native_region_count,0) > 0
              AND coalesce(s.introduced_region_count,0) = 0
              AND coalesce(s.doubtful_region_count,0) = 0
              AND coalesce(s.region_count,0) = coalesce(s.native_region_count,0)
              AND lower(trim(coalesce(w.occurrence_status,'present'))) NOT LIKE '%absent%'
              AND lower(trim(coalesce(w.occurrence_status,'present'))) NOT LIKE '%extinct%'
              AND EXISTS (SELECT 1 FROM plant_index p WHERE p.taxon_id=CAST(w.taxon_id AS TEXT))
            """
        )
        final_links = int(d.execute("SELECT COUNT(*) FROM taxon_native_region").fetchone()[0])
        final_taxa = int(d.execute("SELECT COUNT(DISTINCT taxon_id) FROM taxon_native_region").fetchone()[0])
        summary_added = final_links - summary_added_before

        strategy_parts = []
        if explicit_links:
            strategy_parts.append("explicit_establishment_vocabulary")
        if case_links:
            strategy_parts.append("tdwg_case_convention")
        if summary_added:
            strategy_parts.append("all_regions_native_summary")
        strategy = "+".join(strategy_parts) or "none"

        metadata = {
            "native_region_strategy": strategy,
            "native_explicit_links": str(explicit_links),
            "native_explicit_taxa": str(explicit_taxa),
            "native_case_links": str(case_links),
            "native_case_taxa": str(case_taxa),
            "native_summary_links_added": str(summary_added),
            "native_links_final": str(final_links),
            "native_taxa_final": str(final_taxa),
            "distribution_profile": json.dumps(profile, ensure_ascii=False, separators=(",", ":")),
        }
        for key, value in metadata.items():
            d.execute("INSERT OR REPLACE INTO build_metadata(key,value) VALUES(?,?)", (key, value))
        if final_links == 0:
            raise RuntimeError(
                "no native WCVP distribution links could be classified; "
                f"distribution_profile={metadata['distribution_profile']}"
            )
        return {
            "strategy": strategy,
            "explicit_links": explicit_links,
            "case_links": case_links,
            "summary_links_added": summary_added,
            "final_links": final_links,
            "final_taxa": final_taxa,
            "profile": profile,
        }

    @staticmethod
    def _import_legacy_soil_preferences(d: sqlite3.Connection) -> int:
        """Import only directly documented numeric soil limits from the legacy table.

        The current master snapshot has zero rows in legacy_species_soil; keeping this
        importer in the production schema lets future sourced enrichments become active
        without changing the API. No soil preference is inferred from climate or habitat.
        """
        tables = {r[0] for r in d.execute("SELECT name FROM master.sqlite_master WHERE type='table'")}
        if "legacy_species_soil" not in tables or "legacy_species_wcvp_map" not in tables:
            return 0
        d.execute("DELETE FROM soil_envelope WHERE method='LEGACY_DOCUMENTED_SOIL'")
        d.execute(
            """
            INSERT OR IGNORE INTO soil_envelope(
                taxon_id,variable,hard_low,optimum_low,optimum_high,hard_high,weight,group_code,fatal,confidence,source_ref,method,method_version
            )
            SELECT CAST(m.accepted_taxon_id AS TEXT),'ph',s.ph_min,s.ph_min,s.ph_max,s.ph_max,1.0,'E',0,
                   CASE WHEN upper(coalesce(s.confidence,'')) IN ('A','B','C','D') THEN upper(s.confidence) ELSE 'D' END,
                   coalesce(s.source_id,'legacy_species_soil'),'LEGACY_DOCUMENTED_SOIL','1.0'
            FROM master.legacy_species_soil s
            JOIN master.legacy_species_wcvp_map m ON m.old_species_id=s.species_id
            WHERE m.accepted_taxon_id IS NOT NULL AND s.ph_min IS NOT NULL AND s.ph_max IS NOT NULL
                  AND s.ph_min <= s.ph_max
            """
        )
        return d.execute("SELECT COUNT(*) FROM soil_envelope WHERE method='LEGACY_DOCUMENTED_SOIL'").fetchone()[0]

    def _create_index(self, output: Path) -> dict[str, int]:
        if output.exists():
            output.unlink()
        with sqlite3.connect(output) as d:
            d.execute("PRAGMA journal_mode=OFF")
            d.execute("PRAGMA synchronous=OFF")
            d.execute("PRAGMA temp_store=MEMORY")
            d.executescript(DERIVED_SCHEMA)
            d.execute("ATTACH DATABASE ? AS master", (f"file:{Path(self.master_db).resolve()}?mode=ro",))
            fn_expr = _functions_expr("e")
            plant_columns = {r[1] for r in d.execute("PRAGMA master.table_info(plant_taxa)")}
            powo_expr = "p.powo_id" if "powo_id" in plant_columns else "NULL"
            snid_expr = "p.scientific_name_id" if "scientific_name_id" in plant_columns else "NULL"
            ref_expr = "p.references_url" if "references_url" in plant_columns else "NULL"
            d.execute(f"""
                INSERT INTO plant_index(taxon_id,scientific_name,common_name,functions_json,regulatory_veto,regulatory_reason,confidence,powo_id,scientific_name_id,references_url)
                SELECT CAST(p.taxon_id AS TEXT), p.scientific_name, NULL,
                       {fn_expr},
                       coalesce(e.regulatory_veto, e.risk_veto, 0),
                       NULLIF(trim(coalesce(e.invasive_eu,'') || CASE WHEN e.invasive_eu IS NOT NULL AND e.legal_restriction IS NOT NULL THEN '; ' ELSE '' END || coalesce(e.legal_restriction,'')),''),
                       'UNKNOWN', {powo_expr}, {snid_expr}, {ref_expr}
                FROM master.plant_taxa p
                LEFT JOIN master.climat_enrichment_preferred e ON e.taxon_id=p.taxon_id
                WHERE p.scientific_name IS NOT NULL AND trim(p.scientific_name)<>''
                  AND lower(trim(coalesce(p.taxonomic_status,'accepted')))='accepted'
            """)
            d.execute("""
                INSERT INTO plant_profile(taxon_id,family,genus,taxon_rank,taxonomic_status,life_form,plant_scope,wcvp_climate,references_url,native_region_count,introduced_region_count,legacy_enrichment_available)
                SELECT CAST(p.taxon_id AS TEXT),p.family,p.genus,p.taxon_rank,p.taxonomic_status,p.wcvp_lifeform,p.plant_scope,p.wcvp_climate,p.references_url,
                       coalesce(s.native_region_count,0),coalesce(s.introduced_region_count,0),coalesce(p.legacy_enrichment_available,0)
                FROM master.plant_taxa p
                LEFT JOIN master.plant_distribution_summary s ON s.taxon_id=p.taxon_id
                WHERE lower(trim(coalesce(p.taxonomic_status,'accepted')))='accepted'
            """)
            distribution_profile = self._distribution_profile(d)
            native_strategy = self._populate_native_regions(d, distribution_profile)
            d.execute("""
                INSERT INTO evidence(taxon_id,claim_type,claim_value,source_id,source_reference,source_version,extraction_method,confidence,notes)
                SELECT CAST(p.taxon_id AS TEXT),'WCVP_CLIMATE',p.wcvp_climate,'WCVP',p.references_url,'master-v1.0','direct_field','C',NULL
                FROM master.plant_taxa p WHERE p.wcvp_climate IS NOT NULL AND trim(p.wcvp_climate)<>''
            """)
            # Preserve legacy evidence where a reviewed WCVP map exists.
            d.execute("""
                INSERT INTO evidence(taxon_id,claim_type,claim_value,source_id,source_reference,source_version,extraction_method,confidence,notes)
                SELECT CAST(m.accepted_taxon_id AS TEXT), le.evidence_type, le.asserted_value, le.source_id,
                       coalesce(le.source_subref, CAST(le.source_page AS TEXT)), 'legacy-v1', 'legacy_mapped', le.confidence, le.notes
                FROM master.legacy_species_evidence le
                JOIN master.legacy_species_wcvp_map m ON m.old_species_id=le.species_id
                WHERE m.accepted_taxon_id IS NOT NULL
            """)
            soil_envelopes = self._import_legacy_soil_preferences(d)
            counts = {
                "plants": d.execute("SELECT COUNT(*) FROM plant_index").fetchone()[0],
                "native_links": d.execute("SELECT COUNT(*) FROM taxon_native_region").fetchone()[0],
                "native_taxa": d.execute("SELECT COUNT(DISTINCT taxon_id) FROM taxon_native_region").fetchone()[0],
                "evidence": d.execute("SELECT COUNT(*) FROM evidence").fetchone()[0],
                "soil_envelopes": soil_envelopes,
                "native_strategy": native_strategy["strategy"],
                "native_summary_links_added": native_strategy["summary_links_added"],
                "distribution_profile": native_strategy["profile"],
            }
            for key, value in {
                "mode": "INDEX_BUILT",
                "schema_version": "0.4.0",
                "source_table": "plant_taxa",
                "master_database": self.master_db,
                "built_at": utcnow(),
                **{f"count_{k}": str(v) for k, v in counts.items()},
            }.items():
                d.execute("INSERT OR REPLACE INTO build_metadata(key,value) VALUES(?,?)", (key, str(value)))
        return counts

    def _sample_regions(self, derived: Path, geojson_path: Path) -> dict[str, int]:
        payload = json.loads(geojson_path.read_text(encoding="utf-8"))
        raw_features = payload.get("features", [])
        features: dict[str, dict[str, Any]] = {}
        for feature in raw_features:
            code = feature_tdwg_code(feature)
            if code:
                features[code] = feature
        with sqlite3.connect(derived) as d:
            used_codes = [normalize_tdwg_code(r[0]) for r in d.execute("SELECT DISTINCT location_id FROM taxon_native_region ORDER BY location_id")]
            used_codes = sorted({code for code in used_codes if code})
        region_points: dict[str, list[tuple[float, float]]] = {}
        missing_geometry = []
        flattened: list[tuple[float, float]] = []
        region_slices: dict[str, tuple[int, int]] = {}
        for code in used_codes:
            feature = features.get(code)
            if not feature:
                missing_geometry.append(code)
                continue
            pts = sample_points_for_geometry(feature.get("geometry") or {}, self.sample_points)
            if not pts:
                missing_geometry.append(code)
                continue
            start = len(flattened)
            flattened.extend(pts)
            region_points[code] = pts
            region_slices[code] = (start, len(flattened))

        if not flattened:
            property_keys = sorted({key for f in raw_features[:50] for key in (f.get("properties") or {}).keys()})
            raise RuntimeError(
                "no TDWG region sample points generated; "
                f"used_codes_sample={used_codes[:20]}; "
                f"geojson_codes_sample={sorted(features)[:20]}; "
                f"geojson_property_keys={property_keys[:40]}"
            )

        provider = ChelsaCogProvider(self.climate_manifest)
        sampled = provider.sample_many_profile(flattened, Horizon.NOW, Scenario.MEDIUM)
        with sqlite3.connect(derived) as d:
            rows = 0
            for code, (start, end) in region_slices.items():
                for variable in CORE_VARIABLES:
                    values = [v for v in sampled.get(variable, [])[start:end] if v is not None and math.isfinite(v)]
                    if not values:
                        continue
                    d.execute(
                        "INSERT OR REPLACE INTO region_climate_summary(location_id,variable,sample_count,q05,q20,q50,q80,q95) VALUES(?,?,?,?,?,?,?,?)",
                        (code, variable, len(values), _q(values,.05), _q(values,.20), _q(values,.50), _q(values,.80), _q(values,.95)),
                    )
                    rows += 1
            d.execute("INSERT OR REPLACE INTO build_metadata(key,value) VALUES('tdwg_source',?)", (self.tdwg_urls[0],))
            d.execute("INSERT OR REPLACE INTO build_metadata(key,value) VALUES('tdwg_geometry_features',?)", (str(len(features)),))
            d.execute("INSERT OR REPLACE INTO build_metadata(key,value) VALUES('tdwg_geojson_feature_count',?)", (str(len(raw_features)),))
            d.execute("INSERT OR REPLACE INTO build_metadata(key,value) VALUES('tdwg_used_regions',?)", (str(len(used_codes)),))
            d.execute("INSERT OR REPLACE INTO build_metadata(key,value) VALUES('tdwg_matched_regions',?)", (str(len(region_points)),))
            d.execute("INSERT OR REPLACE INTO build_metadata(key,value) VALUES('tdwg_missing_geometry',?)", (json.dumps(missing_geometry),))
            d.execute("INSERT OR REPLACE INTO build_metadata(key,value) VALUES('region_sample_points_total',?)", (str(len(flattened)),))
        return {"used_regions": len(used_codes), "sample_points": len(flattened), "summary_rows": rows, "missing_geometry": len(missing_geometry)}

    def _build_envelopes(self, derived: Path) -> dict[str, float | int]:
        with sqlite3.connect(derived) as d:
            d.execute("PRAGMA synchronous=OFF")
            d.execute("DELETE FROM climate_envelope WHERE method=?", (METHOD,))
            for variable in CORE_VARIABLES:
                d.execute(
                    """
                    INSERT INTO climate_envelope(taxon_id,variable,hard_low,optimum_low,optimum_high,hard_high,weight,group_code,fatal,confidence,source_ref,method,method_version)
                    SELECT nr.taxon_id, ?, MIN(rs.q05), MIN(rs.q20), MAX(rs.q80), MAX(rs.q95), ?, ?, 0,
                           CASE WHEN COUNT(DISTINCT nr.location_id)>=3 THEN 'C' ELSE 'D' END,
                           ?, ?, ?
                    FROM taxon_native_region nr
                    JOIN region_climate_summary rs ON rs.location_id=nr.location_id AND rs.variable=?
                    GROUP BY nr.taxon_id
                    """,
                    (variable, VARIABLE_WEIGHTS[variable], VARIABLE_GROUPS[variable], SOURCE_REF, METHOD, METHOD_VERSION, variable),
                )
            plants = d.execute("SELECT COUNT(*) FROM plant_index").fetchone()[0]
            envelopes = d.execute("SELECT COUNT(*) FROM climate_envelope WHERE method=?", (METHOD,)).fetchone()[0]
            taxa = d.execute("SELECT COUNT(DISTINCT taxon_id) FROM climate_envelope WHERE method=?", (METHOD,)).fetchone()[0]
            coverage = taxa / plants if plants else 0.0
            vars_present = {r[0] for r in d.execute("SELECT DISTINCT variable FROM climate_envelope WHERE method=?", (METHOD,))}
            ready = coverage >= self.min_coverage and set(CORE_VARIABLES) <= vars_present
            mode = "SCIENTIFIC_PROXY_TDWG3" if ready else "SCIENTIFIC_PROXY_INCOMPLETE"
            metadata = {
                "mode": mode,
                "scientific_ready": "true" if ready else "false",
                "scientific_method": METHOD,
                "scientific_method_version": METHOD_VERSION,
                "scientific_source_ref": SOURCE_REF,
                "scientific_limitations": "Regional realized-niche proxy from WCVP native TDWG-3 presence; not a physiological tolerance model and not point-occurrence SDM.",
                "envelope_taxa": str(taxa),
                "envelope_rows": str(envelopes),
                "envelope_coverage": f"{coverage:.6f}",
                "completed_at": utcnow(),
            }
            for key, value in metadata.items():
                d.execute("INSERT OR REPLACE INTO build_metadata(key,value) VALUES(?,?)", (key, value))
            return {"plants": plants, "envelopes": envelopes, "taxa": taxa, "coverage": coverage, "ready": int(ready)}

    def _run(self) -> None:
        self._wait_master()
        final = Path(self.derived_db)
        # Reuse a completed scientific derived DB if it survived a restart.
        if final.exists():
            try:
                with sqlite3.connect(final) as conn:
                    meta = {r[0]: r[1] for r in conn.execute("SELECT key,value FROM build_metadata")}
                    if meta.get("scientific_ready") == "true" and meta.get("scientific_method_version") == METHOD_VERSION:
                        self._write_status(phase="ready", ready=True, reused=True, completed_at=meta.get("completed_at"), error=None)
                        return
            except sqlite3.Error:
                pass

        tmp = final.with_suffix(final.suffix + ".building")
        self._write_status(phase="building_index", ready=False, error=None)
        index_counts = self._create_index(tmp)
        self._write_status(phase="fetching_tdwg", ready=False, index=index_counts)
        geojson = self._download_tdwg()
        self._write_status(phase="sampling_regions", ready=False)
        region_counts = self._sample_regions(tmp, geojson)
        self._write_status(phase="building_envelopes", ready=False, regions=region_counts)
        envelope_counts = self._build_envelopes(tmp)
        if not envelope_counts.get("ready"):
            self._write_status(phase="incomplete", ready=False, envelopes=envelope_counts, error="scientific coverage threshold not met")
            # Keep the incomplete DB for diagnostics/search, but do not publish analysis.
            os.replace(tmp, final)
            return
        os.replace(tmp, final)
        self._write_status(phase="ready", ready=True, index=index_counts, regions=region_counts, envelopes=envelope_counts, completed_at=utcnow(), error=None)


_services: dict[tuple[str, str], ScientificBuildService] = {}
_services_lock = threading.Lock()


def get_scientific_build(
    master_db: str,
    derived_db: str,
    status_path: str,
    climate_manifest: str,
    tdwg_path: str,
    tdwg_urls: list[str],
    sample_points: int = 9,
    min_coverage: float = 0.50,
) -> ScientificBuildService:
    key = (master_db, derived_db)
    with _services_lock:
        service = _services.get(key)
        if service is None:
            service = ScientificBuildService(
                master_db=master_db,
                derived_db=derived_db,
                status_path=status_path,
                climate_manifest=climate_manifest,
                tdwg_path=tdwg_path,
                tdwg_urls=tdwg_urls,
                sample_points=sample_points,
                min_coverage=min_coverage,
            )
            _services[key] = service
        return service
