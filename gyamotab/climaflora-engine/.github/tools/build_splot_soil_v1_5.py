from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rasterio
from rasterio.warp import transform

CATALOG_VERSION = "1.5.0"
METHOD = "SPLOTOPEN_SOILGRIDS_REALIZED_NICHE"
METHOD_VERSION = "1.0"
SPLOT_DOI = "https://doi.org/10.1111/geb.13346"
SPLOT_DATA = "https://doi.org/10.25829/idiv.3474-40-3292"
SOILGRIDS_REF = "https://doi.org/10.5194/soil-7-217-2021"
REGION_SCOPE = "GLOBAL"
MIN_PLOTS = 5

SOIL_SPECS: dict[str, dict[str, Any]] = {
    "ph": {"raster": "phh2o", "factor": 10.0, "min": 0.1, "max": 14.0, "weight": 0.30},
    "cec_cmol_kg": {"raster": "cec", "factor": 10.0, "min": 0.0, "max": 200.0, "weight": 0.12},
    "clay_pct": {"raster": "clay", "factor": 10.0, "min": 0.0, "max": 100.0, "weight": 0.10},
    "sand_pct": {"raster": "sand", "factor": 10.0, "min": 0.0, "max": 100.0, "weight": 0.10},
    "coarse_fragments_pct": {"raster": "cfvo", "factor": 10.0, "min": 0.0, "max": 100.0, "weight": 0.05},
    "soc_g_kg": {"raster": "soc", "factor": 10.0, "min": 0.0, "max": 1000.0, "weight": 0.10},
    "nitrogen_g_kg": {"raster": "nitrogen", "factor": 100.0, "min": 0.0, "max": 100.0, "weight": 0.08},
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def norm_header(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def norm_name(value: Any) -> str:
    return " ".join(str(value or "").strip().replace("×", " x ").split())


def name_variants(name: str) -> list[tuple[str, str]]:
    base = norm_name(name)
    variants: list[tuple[str, str]] = [(base, "exact")]
    current = base
    for pattern, replacement in (
        (r"\bssp\.\s*", "subsp. "),
        (r"\bssp\s+", "subsp. "),
        (r"\bsubspecies\s+", "subsp. "),
        (r"\bvariety\s+", "var. "),
    ):
        changed = re.sub(pattern, replacement, current, flags=re.I)
        changed = " ".join(changed.split())
        if changed != current:
            variants.append((changed, "notation_normalized"))
            current = changed
    tokens = current.split()
    if len(tokens) >= 2 and tokens[1].lower() != "x":
        variants.append((" ".join([tokens[0], "x", *tokens[1:]]), "hybrid_marker_recovered"))
    stop = 2
    if len(tokens) >= 4 and tokens[2].lower() in {"subsp.", "var.", "f."}:
        stop = 4
    if len(tokens) > stop:
        variants.append((" ".join(tokens[:stop]), "authorship_stripped"))
    out: list[tuple[str, str]] = []
    seen = set()
    for candidate, strategy in variants:
        key = candidate.casefold()
        if key and key not in seen:
            seen.add(key)
            out.append((candidate, strategy))
    return out


def build_name_maps(conn: sqlite3.Connection) -> tuple[dict[str, str], dict[str, str]]:
    accepted: dict[str, str] = {}
    for taxon_id, scientific_name in conn.execute("SELECT CAST(taxon_id AS TEXT), scientific_name FROM plant_index"):
        if scientific_name:
            accepted[norm_name(scientific_name).casefold()] = str(taxon_id)
    synonyms: dict[str, str] = {}
    for scientific_name, accepted_id in conn.execute(
        """
        SELECT n.scientific_name, CAST(COALESCE(n.accepted_name_usage_id,n.taxon_id) AS TEXT)
        FROM wcvp_names n
        JOIN plant_index p ON p.taxon_id=CAST(COALESCE(n.accepted_name_usage_id,n.taxon_id) AS TEXT)
        WHERE n.scientific_name IS NOT NULL
        """
    ):
        key = norm_name(scientific_name).casefold()
        if key and key not in synonyms:
            synonyms[key] = str(accepted_id)
    return accepted, synonyms


def lookup_taxon(name: str, accepted: dict[str, str], synonyms: dict[str, str]) -> tuple[str | None, str, str | None]:
    for candidate, transform_name in name_variants(name):
        key = candidate.casefold()
        if key in accepted:
            return accepted[key], "accepted_name" if transform_name == "exact" else transform_name, candidate
        if key in synonyms:
            return synonyms[key], "wcvp_synonym" if transform_name == "exact" else transform_name, candidate
    return None, "unmatched", None


def sniff_csv(path: Path) -> tuple[str, list[str]]:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
        sample = f.read(65536)
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.reader(sample.splitlines(), delimiter=delimiter)
    return delimiter, next(reader, [])


def locate_splot_files(root: Path) -> tuple[Path, str, Path, str]:
    header_candidate = None
    dt_candidate = None
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".csv", ".txt"}:
            continue
        try:
            delimiter, headers = sniff_csv(path)
        except OSError:
            continue
        normalized = {norm_header(h): h for h in headers}
        has_plot = "plotobservationid" in normalized
        if has_plot and "latitude" in normalized and "longitude" in normalized:
            header_candidate = (path, delimiter)
        if has_plot and "species" in normalized:
            dt_candidate = (path, delimiter)
        if header_candidate and dt_candidate:
            break
    if not header_candidate or not dt_candidate:
        raise RuntimeError("Could not locate sPlotOpen header/DT matrices")
    return header_candidate[0], header_candidate[1], dt_candidate[0], dt_candidate[1]


def read_header(path: Path, delimiter: str) -> pd.DataFrame:
    frame = pd.read_csv(path, sep=delimiter, low_memory=False, encoding="utf-8-sig")
    by_norm = {norm_header(c): c for c in frame.columns}
    required = {"plotobservationid", "latitude", "longitude"}
    if not required.issubset(by_norm):
        raise RuntimeError(f"Missing sPlotOpen header columns: {sorted(required - set(by_norm))}")
    plot_col = by_norm["plotobservationid"]
    lat_col = by_norm["latitude"]
    lon_col = by_norm["longitude"]
    country = by_norm.get("country")
    consensus = by_norm.get("resample1consensus")
    uncertainty = by_norm.get("locationuncertainty")
    out = pd.DataFrame({
        "plot_id": frame[plot_col].astype(str),
        "latitude": pd.to_numeric(frame[lat_col], errors="coerce"),
        "longitude": pd.to_numeric(frame[lon_col], errors="coerce"),
        "country": frame[country].fillna("").astype(str) if country else "",
    })
    out["location_uncertainty_m"] = pd.to_numeric(frame[uncertainty], errors="coerce") if uncertainty else np.nan
    if consensus:
        raw = frame[consensus].astype(str).str.strip().str.lower()
        out = out.loc[raw.isin({"true", "t", "1", "yes", "y"})].copy()
    out = out.loc[out["latitude"].between(-90, 90) & out["longitude"].between(-180, 180)].copy()
    out = out.drop_duplicates("plot_id", keep="first")
    out["geo_cell"] = (
        np.floor(out["latitude"] / 2.0).astype(int).astype(str)
        + ":" + np.floor(out["longitude"] / 2.0).astype(int).astype(str)
    )
    return out.reset_index(drop=True)


def sample_raster(path: Path, lats: np.ndarray, lons: np.ndarray, spec: dict[str, Any]) -> np.ndarray:
    with rasterio.Env(GDAL_CACHEMAX=256):
        with rasterio.open(path) as ds:
            if ds.crs is None:
                raise RuntimeError(f"Raster has no CRS: {path}")
            xs, ys = transform("EPSG:4326", ds.crs, lons.tolist(), lats.tolist())
            values = np.full(len(xs), np.nan, dtype="float64")
            nodata = ds.nodata
            for idx, sample in enumerate(ds.sample(zip(xs, ys), masked=True)):
                value = sample[0]
                if np.ma.is_masked(value):
                    continue
                raw = float(value)
                if nodata is not None and raw == float(nodata):
                    continue
                scaled = raw / float(spec["factor"])
                if math.isfinite(scaled) and float(spec["min"]) <= scaled <= float(spec["max"]):
                    values[idx] = scaled
    return values


def read_species_pairs(path: Path, delimiter: str, selected_plot_ids: set[str]) -> pd.DataFrame:
    _, headers = sniff_csv(path)
    by_norm = {norm_header(h): h for h in headers}
    plot_col = by_norm.get("plotobservationid")
    species_col = by_norm.get("species")
    if not plot_col or not species_col:
        raise RuntimeError("sPlotOpen DT matrix lacks PlotObservationID or Species")
    chunks: list[pd.DataFrame] = []
    for chunk in pd.read_csv(path, sep=delimiter, usecols=[plot_col, species_col], chunksize=250_000, low_memory=False, encoding="utf-8-sig"):
        chunk[plot_col] = chunk[plot_col].astype(str)
        chunk = chunk.loc[chunk[plot_col].isin(selected_plot_ids)]
        if chunk.empty:
            continue
        chunk = chunk.rename(columns={plot_col: "plot_id", species_col: "species"})
        chunk["species"] = chunk["species"].map(norm_name)
        chunks.append(chunk.loc[chunk["species"] != "", ["plot_id", "species"]].drop_duplicates())
    if not chunks:
        return pd.DataFrame(columns=["plot_id", "species"])
    return pd.concat(chunks, ignore_index=True).drop_duplicates(["plot_id", "species"])


def quantile_envelope(values: np.ndarray) -> tuple[float, float, float, float]:
    q05, q25, q75, q95 = np.nanquantile(values, [0.05, 0.25, 0.75, 0.95])
    return tuple(round(float(x), 4) for x in (q05, q25, q75, q95))


def inferred_confidence(n: int, geo_cells: int, countries: int) -> str:
    return "C" if n >= 30 and geo_cells >= 5 and countries >= 2 else "D"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--splot-dir", required=True)
    ap.add_argument("--soil-dir", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--splot-sha256", default="")
    args = ap.parse_args()

    base = Path(args.base)
    splot_root = Path(args.splot_dir)
    soil_root = Path(args.soil_dir)
    output = Path(args.output)
    report_path = Path(args.report)
    tmp = output.with_suffix(output.suffix + ".building")
    if tmp.exists():
        tmp.unlink()
    import shutil
    shutil.copyfile(base, tmp)

    header_path, header_sep, dt_path, dt_sep = locate_splot_files(splot_root)
    plots = read_header(header_path, header_sep)
    if len(plots) < 40_000:
        raise RuntimeError(f"Too few usable sPlotOpen consensus plots: {len(plots)}")

    raster_paths: dict[str, Path] = {}
    for variable, spec in SOIL_SPECS.items():
        pattern = f"{spec['raster']}_5-15cm_mean_1000.tif"
        matches = list(soil_root.rglob(pattern))
        if not matches:
            raise RuntimeError(f"Missing SoilGrids raster for {variable}: {pattern}")
        raster_paths[variable] = matches[0]
    for variable, spec in SOIL_SPECS.items():
        plots[variable] = sample_raster(raster_paths[variable], plots["latitude"].to_numpy(dtype=float), plots["longitude"].to_numpy(dtype=float), spec)

    selected_plot_ids = set(plots["plot_id"].astype(str))
    pairs = read_species_pairs(dt_path, dt_sep, selected_plot_ids)
    if len(pairs) < 500_000:
        raise RuntimeError(f"Too few sPlotOpen species-plot records after filtering: {len(pairs)}")

    stats: dict[str, Any] = {
        "header_file": str(header_path.relative_to(splot_root)),
        "dt_file": str(dt_path.relative_to(splot_root)),
        "consensus_plots": int(len(plots)),
        "species_plot_records": int(len(pairs)),
        "source_unique_names": int(pairs["species"].nunique()),
        "matched_species_names": 0,
        "unmatched_species_names": 0,
        "matched_unique_taxa": 0,
        "eligible_taxa": 0,
        "inserted_envelopes": 0,
        "skipped_existing_expert_envelopes": 0,
        "confidence": {"C": 0, "D": 0},
        "match_strategies": {},
        "variable_taxa": {},
    }
    strategy_counts = Counter()
    unmatched_names: list[str] = []

    with sqlite3.connect(tmp) as conn:
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA synchronous=NORMAL")
        accepted, synonyms = build_name_maps(conn)
        name_to_taxon: dict[str, str] = {}
        for name in sorted(set(pairs["species"])):
            taxon_id, strategy, _ = lookup_taxon(name, accepted, synonyms)
            if taxon_id:
                name_to_taxon[name] = taxon_id
                strategy_counts[strategy] += 1
            elif len(unmatched_names) < 500:
                unmatched_names.append(name)
        stats["matched_species_names"] = len(name_to_taxon)
        stats["unmatched_species_names"] = int(pairs["species"].nunique() - len(name_to_taxon))
        stats["match_strategies"] = dict(strategy_counts)
        pairs["taxon_id"] = pairs["species"].map(name_to_taxon)
        pairs = pairs.dropna(subset=["taxon_id"])[["plot_id", "taxon_id"]].drop_duplicates()
        stats["matched_unique_taxa"] = int(pairs["taxon_id"].nunique())

        plot_index = plots.set_index("plot_id", drop=False)
        existing: set[tuple[str, str]] = set((str(t), str(v)) for t, v in conn.execute(
            "SELECT DISTINCT taxon_id, variable FROM soil_envelope WHERE method IS NULL OR method<>?", (METHOD,)
        ))
        conn.execute("DELETE FROM soil_envelope WHERE method=? AND method_version=?", (METHOD, METHOD_VERSION))
        conn.execute("DELETE FROM evidence WHERE claim_type='soil_realized_niche' AND source_id='SPLOTOPEN_SOILGRIDS'")
        variable_taxa = Counter()
        eligible_taxa: set[str] = set()
        evidence_rows = 0

        for taxon_id, group in pairs.groupby("taxon_id", sort=False):
            available_ids = [pid for pid in group["plot_id"].astype(str).tolist() if pid in plot_index.index]
            if len(available_ids) < MIN_PLOTS:
                continue
            site_rows = plot_index.loc[available_ids]
            if isinstance(site_rows, pd.Series):
                site_rows = site_rows.to_frame().T
            unique_sites = site_rows.drop_duplicates("plot_id")
            n_sites = len(unique_sites)
            if n_sites < MIN_PLOTS:
                continue
            geo_cells = int(unique_sites["geo_cell"].nunique())
            countries = int(unique_sites.loc[unique_sites["country"] != "", "country"].nunique())
            confidence = inferred_confidence(n_sites, geo_cells, countries)
            claim_variables: dict[str, Any] = {}
            inserted_for_taxon = 0
            for variable, spec in SOIL_SPECS.items():
                values = pd.to_numeric(unique_sites[variable], errors="coerce").to_numpy(dtype=float)
                values = values[np.isfinite(values)]
                if len(values) < MIN_PLOTS:
                    continue
                q05, q25, q75, q95 = quantile_envelope(values)
                if (str(taxon_id), variable) in existing:
                    stats["skipped_existing_expert_envelopes"] += 1
                    continue
                conn.execute(
                    """INSERT OR REPLACE INTO soil_envelope(
                    taxon_id,variable,hard_low,optimum_low,optimum_high,hard_high,
                    weight,group_code,fatal,confidence,source_ref,method,method_version
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (str(taxon_id), variable, q05, q25, q75, q95, float(spec["weight"]), "E", 0,
                     confidence, f"{SPLOT_DATA} + {SOILGRIDS_REF}", METHOD, METHOD_VERSION),
                )
                inserted_for_taxon += 1
                stats["inserted_envelopes"] += 1
                variable_taxa[variable] += 1
                claim_variables[variable] = {"n": int(len(values)), "p05": q05, "p25": q25, "p75": q75, "p95": q95}
            if not inserted_for_taxon:
                continue
            eligible_taxa.add(str(taxon_id))
            stats["confidence"][confidence] += 1
            claim = {
                "region_scope": REGION_SCOPE, "n_plots": int(n_sites), "geo_cells_2deg": geo_cells,
                "countries": countries, "confidence": confidence, "variables": claim_variables,
                "method": "realized niche robust quantiles from vegetation plots",
                "limitations": ["observational realized niche, not physiological tolerance",
                                "sPlotOpen is environmentally resampled",
                                "SoilGrids values are model predictions at 1 km mean aggregation"],
            }
            conn.execute(
                """INSERT INTO evidence(taxon_id,claim_type,claim_value,source_id,source_reference,
                source_version,extraction_method,confidence,notes) VALUES(?,?,?,?,?,?,?,?,?)""",
                (str(taxon_id), "soil_realized_niche", json.dumps(claim, ensure_ascii=False, sort_keys=True),
                 "SPLOTOPEN_SOILGRIDS", SPLOT_DATA, "sPlotOpen + SoilGrids 2.0 aggregated 1000m",
                 "ROBUST_P05_P25_P75_P95_BY_WCVP_TAXON", confidence,
                 "Observed environmental association; not an experimental survival limit."),
            )
            evidence_rows += 1

        stats["eligible_taxa"] = len(eligible_taxa)
        stats["variable_taxa"] = dict(variable_taxa)
        stats["evidence_rows"] = evidence_rows
        total_plants = conn.execute("SELECT COUNT(*) FROM plant_index").fetchone()[0]
        soil_numeric = conn.execute("SELECT COUNT(*) FROM soil_envelope").fetchone()[0]
        soil_cat = conn.execute("SELECT COUNT(*) FROM soil_categorical_preference").fetchone()[0]
        has_indicator = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='soil_indicator_preference'").fetchone()[0]
        soil_indicator = conn.execute("SELECT COUNT(*) FROM soil_indicator_preference").fetchone()[0] if has_indicator else 0
        union_sql = "SELECT taxon_id FROM soil_envelope UNION SELECT taxon_id FROM soil_categorical_preference"
        if has_indicator:
            union_sql += " UNION SELECT taxon_id FROM soil_indicator_preference"
        soil_taxa = conn.execute(f"SELECT COUNT(DISTINCT taxon_id) FROM ({union_sql})").fetchone()[0]
        metadata = {
            "catalog_version": CATALOG_VERSION,
            "soil_splot_source": "sPlotOpen + SoilGrids 2.0",
            "soil_splot_method": METHOD,
            "soil_splot_method_version": METHOD_VERSION,
            "soil_splot_region_scope": REGION_SCOPE,
            "soil_splot_consensus_plots": str(len(plots)),
            "soil_splot_matched_taxa": str(stats["matched_unique_taxa"]),
            "soil_splot_eligible_taxa": str(stats["eligible_taxa"]),
            "soil_splot_min_plots": str(MIN_PLOTS),
            "soil_splot_source_sha256": args.splot_sha256,
            "soil_splot_integrated_at": utcnow(),
            "soil_splot_confidence_ceiling": "C",
            "scientific_ready": "true",
        }
        conn.executemany("INSERT OR REPLACE INTO climaflora_catalog_metadata(key,value) VALUES(?,?)", metadata.items())
        conn.commit()
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("integrity_check failed")

    os.chmod(tmp, 0o444)
    os.replace(tmp, output)
    report = {
        "catalog_version": CATALOG_VERSION,
        "built_at": utcnow(),
        "source": {"splot_scientific_reference": SPLOT_DOI, "splot_dataset": SPLOT_DATA,
                   "splot_archive_sha256": args.splot_sha256, "soilgrids_reference": SOILGRIDS_REF,
                   "soilgrids_depth": "5-15cm", "soilgrids_resolution_m": 1000, "soilgrids_summary": "mean"},
        "stats": stats,
        "soil_taxa_total": int(soil_taxa),
        "soil_taxa_coverage": soil_taxa / total_plants if total_plants else 0,
        "soil_envelope_rows": int(soil_numeric),
        "soil_categorical_rows": int(soil_cat),
        "soil_indicator_rows": int(soil_indicator),
        "unmatched_sample": unmatched_names,
        "sqlite_bytes": output.stat().st_size,
        "sqlite_sha256": sha256_file(output),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
