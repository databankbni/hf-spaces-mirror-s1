from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.warp import transform

CATALOG_VERSION = "1.6.0"
METHOD = "WCVP_NATIVE_TDWG3_SOILGRIDS_GEOGRAPHIC_PRIOR"
METHOD_VERSION = "1.0"
REGION_SCOPE = "GLOBAL_NATIVE_RANGE_PRIOR"
SOILGRIDS_REF = "https://doi.org/10.5194/soil-7-217-2021"
WGSRPD_REF = "https://www.tdwg.org/standards/wgsrpd/"

SOIL_SPECS: dict[str, dict[str, Any]] = {
    "ph": {"raster": "phh2o", "factor": 10.0, "min": 0.1, "max": 14.0},
    "cec_cmol_kg": {"raster": "cec", "factor": 10.0, "min": 0.0, "max": 200.0},
    "clay_pct": {"raster": "clay", "factor": 10.0, "min": 0.0, "max": 100.0},
    "sand_pct": {"raster": "sand", "factor": 10.0, "min": 0.0, "max": 100.0},
    "coarse_fragments_pct": {"raster": "cfvo", "factor": 10.0, "min": 0.0, "max": 100.0},
    "soc_g_kg": {"raster": "soc", "factor": 10.0, "min": 0.0, "max": 1000.0},
    "nitrogen_g_kg": {"raster": "nitrogen", "factor": 100.0, "min": 0.0, "max": 100.0},
}


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def normalize_code(value: Any) -> str:
    code = str(value or "").strip().upper()
    for prefix in ("TDWG:", "TDWG_", "TDWG-"):
        if code.startswith(prefix):
            code = code[len(prefix):]
            break
    return code.strip()


def feature_code(feature: dict[str, Any]) -> str:
    props = feature.get("properties") or {}
    for key in (
        "code", "CODE", "LEVEL3_COD", "LEVEL3_CODE", "level3_cod", "level3_code", "TDWG3", "tdwg3"
    ):
        if props.get(key) not in (None, ""):
            return normalize_code(props[key])
    return ""


def polygon_rings(geometry: dict[str, Any]) -> list[list[list[list[float]]]]:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if gtype == "Polygon":
        return [coords] if coords else []
    if gtype == "MultiPolygon":
        return [poly for poly in coords if poly]
    return []


def point_in_ring(x: float, y: float, ring: list[list[float]]) -> bool:
    inside = False
    if len(ring) < 3:
        return False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-15) + xi):
            inside = not inside
        j = i
    return inside


def point_in_polygon(x: float, y: float, rings: list[list[list[float]]]) -> bool:
    if not rings or not point_in_ring(x, y, rings[0]):
        return False
    return not any(point_in_ring(x, y, hole) for hole in rings[1:])


def ring_area(ring: list[list[float]]) -> float:
    area = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[i + 1][0], ring[i + 1][1]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def sample_points_for_geometry(geometry: dict[str, Any], max_points: int = 64) -> list[tuple[float, float]]:
    polygons = polygon_rings(geometry)
    if not polygons:
        return []
    polygons = sorted(polygons, key=lambda rings: ring_area(rings[0]) if rings else 0.0, reverse=True)
    out: list[tuple[float, float]] = []
    for rings in polygons:
        if len(out) >= max_points:
            break
        outer = rings[0]
        xs = [float(p[0]) for p in outer]
        ys = [float(p[1]) for p in outer]
        if not xs or not ys:
            continue
        minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
        fractions = np.linspace(0.04, 0.96, 15)
        cx, cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0
        candidates = [
            (minx + (maxx - minx) * float(fx), miny + (maxy - miny) * float(fy))
            for fy in fractions for fx in fractions
        ]
        candidates.sort(key=lambda pt: (pt[0] - cx) ** 2 + (pt[1] - cy) ** 2)
        for x, y in candidates:
            if point_in_polygon(x, y, rings):
                if all(abs(x - a) > 1e-9 or abs(y - b) > 1e-9 for a, b in out):
                    out.append((x, y))
                    if len(out) >= max_points:
                        break
        if not any(point_in_polygon(x, y, rings) for x, y in out):
            # Tiny-island fallback. SoilGrids nodata filtering still protects the result.
            out.append((sum(xs) / len(xs), sum(ys) / len(ys)))
    return out[:max_points]


def sample_raster(path: Path, points: list[tuple[float, float]], spec: dict[str, Any]) -> list[float]:
    if not points:
        return []
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    with rasterio.Env(GDAL_CACHEMAX=256):
        with rasterio.open(path) as ds:
            if ds.crs is None:
                raise RuntimeError(f"Raster has no CRS: {path}")
            xs, ys = transform("EPSG:4326", ds.crs, lons, lats)
            nodata = ds.nodata
            values: list[float] = []
            for sample in ds.sample(zip(xs, ys), masked=True):
                value = sample[0]
                if np.ma.is_masked(value):
                    continue
                raw = float(value)
                if nodata is not None and raw == float(nodata):
                    continue
                scaled = raw / float(spec["factor"])
                if math.isfinite(scaled) and float(spec["min"]) <= scaled <= float(spec["max"]):
                    values.append(scaled)
    return values


def q(values: list[float], p: float) -> float:
    return round(float(np.quantile(np.asarray(values, dtype=float), p)), 4)


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS region_soil_summary (
          location_id TEXT NOT NULL,
          variable TEXT NOT NULL,
          sample_count INTEGER NOT NULL,
          q05 REAL,
          q25 REAL,
          q50 REAL,
          q75 REAL,
          q95 REAL,
          source_ref TEXT,
          method TEXT,
          method_version TEXT,
          PRIMARY KEY (location_id, variable)
        ) WITHOUT ROWID;

        CREATE TABLE IF NOT EXISTS soil_geographic_prior (
          taxon_id TEXT PRIMARY KEY,
          native_region_count INTEGER NOT NULL,
          covered_region_count INTEGER NOT NULL,
          variables_json TEXT NOT NULL,
          confidence TEXT NOT NULL DEFAULT 'PRIOR',
          scoring_enabled INTEGER NOT NULL DEFAULT 0,
          source_ref TEXT,
          method TEXT,
          method_version TEXT
        ) WITHOUT ROWID;

        CREATE TABLE IF NOT EXISTS climaflora_catalog_metadata (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        """
    )


def native_link_query(conn: sqlite3.Connection) -> tuple[str, str]:
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "taxon_native_region" in tables:
        count = int(conn.execute("SELECT COUNT(*) FROM taxon_native_region").fetchone()[0])
        if count > 0:
            return (
                "SELECT CAST(taxon_id AS TEXT), location_id FROM taxon_native_region ORDER BY CAST(taxon_id AS TEXT), location_id",
                "catalog_taxon_native_region",
            )
    if "wcvp_distribution" not in tables:
        raise RuntimeError("No taxon_native_region or wcvp_distribution table is available")
    # Conservative fallback: only explicitly native/indigenous/endemic distributions.
    return (
        """
        SELECT CAST(w.taxon_id AS TEXT), w.location_id
        FROM wcvp_distribution w
        JOIN plant_index p ON p.taxon_id=CAST(w.taxon_id AS TEXT)
        WHERE w.location_id IS NOT NULL AND trim(w.location_id)<>''
          AND lower(trim(coalesce(w.occurrence_status,'present'))) NOT LIKE '%absent%'
          AND lower(trim(coalesce(w.occurrence_status,'present'))) NOT LIKE '%extinct%'
          AND (
                lower(trim(coalesce(w.establishment_means,''))) IN ('native','indigenous','endemic')
             OR lower(trim(coalesce(w.establishment_means,''))) LIKE '%/native'
             OR lower(trim(coalesce(w.establishment_means,''))) LIKE '%#native'
             OR lower(trim(coalesce(w.establishment_means,''))) LIKE '%:native'
          )
        ORDER BY CAST(w.taxon_id AS TEXT), w.location_id
        """,
        "explicit_wcvp_native_only",
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--tdwg", required=True)
    ap.add_argument("--soil-dir", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--tdwg-sha256", default="")
    args = ap.parse_args()

    import shutil

    base = Path(args.base)
    tdwg = Path(args.tdwg)
    soil_dir = Path(args.soil_dir)
    output = Path(args.output)
    report_path = Path(args.report)
    tmp = output.with_suffix(output.suffix + ".building")
    if tmp.exists():
        tmp.unlink()
    shutil.copyfile(base, tmp)

    payload = json.loads(tdwg.read_text(encoding="utf-8"))
    features = payload.get("features") or []
    if len(features) < 300:
        raise RuntimeError(f"WGSRPD level-3 file has too few features: {len(features)}")

    raster_paths: dict[str, Path] = {}
    for variable, spec in SOIL_SPECS.items():
        matches = list(soil_dir.rglob(f"{spec['raster']}_5-15cm_mean_1000.tif"))
        if not matches:
            raise RuntimeError(f"Missing SoilGrids raster for {variable}")
        raster_paths[variable] = matches[0]

    region_summaries: dict[str, dict[str, dict[str, float | int]]] = defaultdict(dict)
    regions_with_points = 0
    for feature in features:
        code = feature_code(feature)
        if not code:
            continue
        points = sample_points_for_geometry(feature.get("geometry") or {}, max_points=64)
        if not points:
            continue
        regions_with_points += 1
        for variable, spec in SOIL_SPECS.items():
            values = sample_raster(raster_paths[variable], points, spec)
            if len(values) < 3:
                continue
            region_summaries[code][variable] = {
                "n": len(values),
                "q05": q(values, 0.05),
                "q25": q(values, 0.25),
                "q50": q(values, 0.50),
                "q75": q(values, 0.75),
                "q95": q(values, 0.95),
            }

    with sqlite3.connect(tmp) as conn:
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA synchronous=NORMAL")
        ensure_schema(conn)
        conn.execute("DELETE FROM region_soil_summary WHERE method=?", (METHOD,))
        conn.execute("DELETE FROM soil_geographic_prior WHERE method=?", (METHOD,))

        region_rows = []
        for code, variables in region_summaries.items():
            for variable, s in variables.items():
                region_rows.append((
                    code, variable, int(s["n"]), float(s["q05"]), float(s["q25"]), float(s["q50"]),
                    float(s["q75"]), float(s["q95"]), f"{WGSRPD_REF} + {SOILGRIDS_REF}", METHOD, METHOD_VERSION,
                ))
        conn.executemany(
            """INSERT OR REPLACE INTO region_soil_summary(
            location_id,variable,sample_count,q05,q25,q50,q75,q95,source_ref,method,method_version
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            region_rows,
        )

        link_sql, native_strategy = native_link_query(conn)
        cursor = conn.execute(link_sql)
        total_links = 0
        covered_links = 0
        prior_taxa = 0
        variable_taxa: dict[str, int] = defaultdict(int)
        batch: list[tuple[Any, ...]] = []

        current_taxon: str | None = None
        current_codes: list[str] = []

        def flush_taxon(taxon_id: str | None, codes: list[str]) -> None:
            nonlocal prior_taxa, covered_links, batch
            if not taxon_id or not codes:
                return
            unique_codes = sorted(set(normalize_code(c) for c in codes if normalize_code(c)))
            covered = [c for c in unique_codes if c in region_summaries]
            covered_links += len(covered)
            if not covered:
                return
            variables: dict[str, Any] = {}
            for variable in SOIL_SPECS:
                summaries = [region_summaries[c][variable] for c in covered if variable in region_summaries[c]]
                if not summaries:
                    continue
                variables[variable] = {
                    "outer_low": min(float(s["q05"]) for s in summaries),
                    "central_low": min(float(s["q25"]) for s in summaries),
                    "region_median": round(float(np.median([float(s["q50"]) for s in summaries])), 4),
                    "central_high": max(float(s["q75"]) for s in summaries),
                    "outer_high": max(float(s["q95"]) for s in summaries),
                    "regions": len(summaries),
                }
                variable_taxa[variable] += 1
            if not variables:
                return
            batch.append((
                taxon_id,
                len(unique_codes),
                len(covered),
                json.dumps(variables, separators=(",", ":"), sort_keys=True),
                "PRIOR",
                0,
                f"WCVP native distribution + {WGSRPD_REF} + {SOILGRIDS_REF}",
                METHOD,
                METHOD_VERSION,
            ))
            prior_taxa += 1
            if len(batch) >= 5000:
                conn.executemany(
                    """INSERT OR REPLACE INTO soil_geographic_prior(
                    taxon_id,native_region_count,covered_region_count,variables_json,confidence,
                    scoring_enabled,source_ref,method,method_version
                    ) VALUES(?,?,?,?,?,?,?,?,?)""",
                    batch,
                )
                batch = []

        for taxon_id, location_id in cursor:
            total_links += 1
            taxon_id = str(taxon_id)
            if current_taxon is None:
                current_taxon = taxon_id
            if taxon_id != current_taxon:
                flush_taxon(current_taxon, current_codes)
                current_taxon = taxon_id
                current_codes = []
            current_codes.append(str(location_id))
        flush_taxon(current_taxon, current_codes)
        if batch:
            conn.executemany(
                """INSERT OR REPLACE INTO soil_geographic_prior(
                taxon_id,native_region_count,covered_region_count,variables_json,confidence,
                scoring_enabled,source_ref,method,method_version
                ) VALUES(?,?,?,?,?,?,?,?,?)""",
                batch,
            )

        direct_union = "SELECT taxon_id FROM soil_envelope UNION SELECT taxon_id FROM soil_categorical_preference"
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "soil_indicator_preference" in tables:
            direct_union += " UNION SELECT taxon_id FROM soil_indicator_preference"
        soil_preference_taxa = int(conn.execute(f"SELECT COUNT(DISTINCT taxon_id) FROM ({direct_union})").fetchone()[0])
        total_plants = int(conn.execute("SELECT COUNT(*) FROM plant_index").fetchone()[0])
        context_taxa = int(conn.execute("SELECT COUNT(*) FROM soil_geographic_prior").fetchone()[0])
        any_context_taxa = int(conn.execute(
            f"SELECT COUNT(DISTINCT taxon_id) FROM ({direct_union} UNION SELECT taxon_id FROM soil_geographic_prior)"
        ).fetchone()[0])

        metadata = {
            "catalog_version": CATALOG_VERSION,
            "soil_geographic_prior_method": METHOD,
            "soil_geographic_prior_method_version": METHOD_VERSION,
            "soil_geographic_prior_native_strategy": native_strategy,
            "soil_geographic_prior_scoring_enabled": "false",
            "soil_geographic_prior_confidence": "PRIOR",
            "soil_geographic_prior_taxa": str(context_taxa),
            "soil_geographic_prior_source_sha256": args.tdwg_sha256 or sha256_file(tdwg),
            "soil_geographic_prior_limitation": (
                "Regional soil availability across native WGSRPD areas; not a species-specific realized or physiological niche."
            ),
            "scientific_ready": "true",
        }
        conn.executemany(
            "INSERT OR REPLACE INTO climaflora_catalog_metadata(key,value) VALUES(?,?)",
            metadata.items(),
        )
        conn.commit()
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("integrity_check failed")

    os.chmod(tmp, 0o444)
    os.replace(tmp, output)
    report = {
        "catalog_version": CATALOG_VERSION,
        "sources": {
            "wgsrpd": WGSRPD_REF,
            "wgsrpd_sha256": args.tdwg_sha256 or sha256_file(tdwg),
            "soilgrids": SOILGRIDS_REF,
            "soilgrids_depth": "5-15cm",
            "soilgrids_resolution_m": 1000,
        },
        "native_link_strategy": native_strategy,
        "wgsrpd_features": len(features),
        "regions_with_sample_points": regions_with_points,
        "regions_with_soil_summary": len(region_summaries),
        "region_summary_rows": len(region_rows),
        "native_links_total": total_links,
        "native_links_covered": covered_links,
        "soil_preference_taxa_total": soil_preference_taxa,
        "soil_geographic_prior_taxa": context_taxa,
        "soil_any_context_taxa": any_context_taxa,
        "soil_geographic_prior_coverage": context_taxa / total_plants if total_plants else 0,
        "soil_any_context_coverage": any_context_taxa / total_plants if total_plants else 0,
        "variable_taxa": dict(variable_taxa),
        "scoring_enabled": False,
        "sqlite_bytes": output.stat().st_size,
        "sqlite_sha256": sha256_file(output),
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
