from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

CATALOG_VERSION = "1.9.0"
BUILD_VERSION = "1.0"
METHOD = "CLIMAFLORA_EDAPHIC_CONSOLIDATION"
METHOD_VERSION = "1.0"
ECO_METHOD = "FAO_ECOCROP_BULK_DOCUMENTED"
SPLOT_METHOD = "SPLOTOPEN_SOILGRIDS_REALIZED_NICHE"
EIVE_METHOD = "EIVE_1_0_EUROPE_CONSENSUS"
NATIVE_METHOD = "WCVP_NATIVE_TDWG3_SOILGRIDS_GEOGRAPHIC_PRIOR"

SOURCES = [
    {
        "source_id": "FAO_ECOCROP",
        "source_name": "FAO ECOCROP",
        "source_version": "legacy database / ClimaFlora import method 2.1",
        "source_url": "https://www.fao.org/geospatial/data-and-tools/data-portals/ecocrop/",
        "license": "FAO terms apply; source is publicly accessible through FAO/GAEZ; redistribution limited to derived ClimaFlora envelopes and provenance",
        "citation": "FAO ECOCROP database of crop constraints and characteristics",
        "source_type": "EXPERT",
        "notes": "Direct expert soil constraints. Source rows inherited unchanged from validated ClimaFlora v1.8.",
    },
    {
        "source_id": "EIVE_1_0",
        "source_name": "Ecological Indicator Values for Europe (EIVE) 1.0",
        "source_version": "1.0",
        "source_url": "https://doi.org/10.5281/zenodo.7534792",
        "license": "Open-access dataset; reuse subject to the rights stated on the Zenodo record and source systems; attribution retained",
        "citation": "Dengler et al. (2023), Ecological Indicator Values for Europe (EIVE) 1.0, Vegetation Classification and Survey 4:7–29",
        "source_type": "EXPERT_INDICATOR",
        "notes": "Ecological indicator values remain on their harmonised 0–10 scales and are never converted to physical pH/moisture/nutrient units.",
    },
    {
        "source_id": "SPLOTOPEN",
        "source_name": "sPlotOpen",
        "source_version": "1.0 legacy ClimaFlora source",
        "source_url": "https://doi.org/10.25829/idiv.3474-40-3292",
        "license": "Open-access dataset; citation and original-source attribution requirements retained",
        "citation": "Sabatini, Lenoir, Bruelheide & sPlot Consortium (2021), sPlotOpen",
        "source_type": "OCCURRENCE",
        "notes": "Vegetation-plot realized niche evidence. Not physiological tolerance. v1.9 requires >=10 usable plots for numerical scoring.",
    },
    {
        "source_id": "SOILGRIDS_2",
        "source_name": "SoilGrids",
        "source_version": "2.0",
        "source_url": "https://soilgrids.org/",
        "license": "CC BY 4.0",
        "citation": "Poggio et al. (2021), SoilGrids 2.0, SOIL 7:217–240",
        "source_type": "SOIL_ATLAS",
        "notes": "Global modelled soil properties; source ClimaFlora v1.8 used 5–15 cm, 1 km mean aggregation for sPlot/native-range derivations.",
    },
    {
        "source_id": "WCVP",
        "source_name": "World Checklist of Vascular Plants",
        "source_version": "ClimaFlora v1.8 embedded snapshot",
        "source_url": "https://powo.science.kew.org/about-wcvp",
        "license": "CC BY 3.0 for Kew Names/Taxonomic Backbone and Kew Backbone Distributions as exposed by POWO; citation retained",
        "citation": "Govaerts R. (ed.), World Checklist of Vascular Plants, Royal Botanic Gardens, Kew",
        "source_type": "TAXONOMY_NATIVE_RANGE",
        "notes": "Existing exact deterministic taxon IDs and native distribution links are reused; no fuzzy matching is introduced in v1.9.",
    },
    {
        "source_id": "WGSRPD",
        "source_name": "World Geographical Scheme for Recording Plant Distributions",
        "source_version": "Edition 2 / TDWG level 3",
        "source_url": "https://www.tdwg.org/standards/wgsrpd/",
        "license": "TDWG standard; citation and provenance retained",
        "citation": "Brummitt et al. (2001), World Geographic Scheme for Recording Plant Distributions, Edition 2",
        "source_type": "GEOGRAPHIC_STANDARD",
        "notes": "Used only to structure native-range geographic priors.",
    },
]

NUMERIC_LIMITS = {
    "ph": (0.0, 14.0),
    "cec_cmol_kg": (0.0, 250.0),
    "clay_pct": (0.0, 100.0),
    "sand_pct": (0.0, 100.0),
    "coarse_fragments_pct": (0.0, 100.0),
    "soc_g_kg": (0.0, 1500.0),
    "nitrogen_g_kg": (0.0, 100.0),
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def finite(value: Any) -> float | None:
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def confidence_class(score: float) -> str:
    if score >= 0.85:
        return "A"
    if score >= 0.70:
        return "B"
    if score >= 0.50:
        return "C"
    return "D"


def occurrence_confidence(n: int, geo_cells: int, countries: int) -> float:
    if n >= 100:
        base = 0.82
    elif n >= 30:
        base = 0.72
    elif n >= 10:
        base = 0.58
    else:
        base = 0.35
    if geo_cells >= 5:
        base += 0.03
    if countries >= 2:
        base += 0.03
    return round(clamp01(base), 4)


def source_id_for_method(method: str | None) -> str:
    if method == ECO_METHOD:
        return "FAO_ECOCROP"
    if method == EIVE_METHOD:
        return "EIVE_1_0"
    if method == SPLOT_METHOD:
        return "SPLOTOPEN+SOILGRIDS_2"
    if method == NATIVE_METHOD:
        return "WCVP+WGSRPD+SOILGRIDS_2"
    return "CLIMAFLORA_V18"


def normalize_ecocrop_categories(variable: str, raw_json: str) -> str:
    """Repair deterministic legacy tokenisation defects without inventing categories.

    v1.3 treated every slash as a multi-value delimiter. That split unit strings
    such as dS/m and the documented drainage label dry/moderately dry. The source
    table is preserved separately in v1.9; only the runtime/canonical projection
    is repaired here.
    """
    try:
        values = [str(x).strip().lower() for x in json.loads(raw_json or "[]")]
    except (TypeError, ValueError, json.JSONDecodeError):
        return raw_json
    out: list[str] = []
    i = 0
    while i < len(values):
        cur = values[i]
        nxt = values[i + 1] if i + 1 < len(values) else None
        if variable == "salinity" and nxt in {"m)", "m))"} and cur in {
            "low (<4 ds", "medium (4-10 ds", "high (>10 ds"
        }:
            out.append(cur + "/m)")
            i += 2
            continue
        if variable == "drainage" and cur == "excessive (dry" and nxt == "moderately dry)":
            out.append("excessive (dry/moderately dry)")
            i += 2
            continue
        out.append(cur)
        i += 1
    # Stable de-duplication preserves source order.
    dedup: list[str] = []
    seen: set[str] = set()
    for value in out:
        if value and value not in seen:
            seen.add(value)
            dedup.append(value)
    return json.dumps(dedup, ensure_ascii=False, separators=(",", ":"))


def validate_numeric(variable: str, values: Iterable[Any]) -> bool:
    low_high = NUMERIC_LIMITS.get(variable)
    for value in values:
        x = finite(value)
        if x is None:
            continue
        if low_high and not (low_high[0] <= x <= low_high[1]):
            return False
    return True


def overlap_ratio(a_low: float | None, a_high: float | None, b_low: float | None, b_high: float | None) -> float | None:
    vals = [a_low, a_high, b_low, b_high]
    if any(v is None for v in vals):
        return None
    assert a_low is not None and a_high is not None and b_low is not None and b_high is not None
    intersection = max(0.0, min(a_high, b_high) - max(a_low, b_low))
    union = max(a_high, b_high) - min(a_low, b_low)
    if union <= 0:
        return 1.0 if intersection == 0 and a_low == b_low else 0.0
    return intersection / union


def create_build_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        PRAGMA temp_store=MEMORY;

        CREATE TABLE edaphic_sources (
          source_id TEXT PRIMARY KEY,
          source_name TEXT NOT NULL,
          source_version TEXT,
          source_url TEXT,
          license TEXT NOT NULL,
          access_date TEXT NOT NULL,
          citation TEXT,
          source_type TEXT NOT NULL,
          notes TEXT
        ) WITHOUT ROWID;

        CREATE TABLE edaphic_expert_values (
          expert_value_id INTEGER PRIMARY KEY,
          taxon_id TEXT NOT NULL,
          source_id TEXT NOT NULL,
          source_row_type TEXT NOT NULL,
          source_row_id TEXT,
          variable TEXT NOT NULL,
          value_min REAL,
          value_opt_min REAL,
          value_opt_max REAL,
          value_max REAL,
          categorical_value TEXT,
          indicator_value REAL,
          niche_width REAL,
          unit TEXT,
          confidence TEXT,
          source_ref TEXT,
          method TEXT,
          method_version TEXT
        );

        CREATE TABLE edaphic_occurrence_stats (
          taxon_id TEXT NOT NULL,
          variable TEXT NOT NULL,
          n_occurrences INTEGER NOT NULL,
          geo_cells INTEGER NOT NULL DEFAULT 0,
          countries INTEGER NOT NULL DEFAULT 0,
          p05 REAL,
          p10 REAL,
          p25 REAL,
          median REAL,
          p75 REAL,
          p90 REAL,
          p95 REAL,
          mean REAL,
          stddev REAL,
          source_id TEXT NOT NULL,
          method TEXT,
          method_version TEXT,
          confidence_score REAL NOT NULL,
          confidence_class TEXT NOT NULL,
          scoring_eligible INTEGER NOT NULL,
          PRIMARY KEY (taxon_id, variable)
        ) WITHOUT ROWID;

        CREATE TABLE edaphic_native_range_stats (
          taxon_id TEXT NOT NULL,
          variable TEXT NOT NULL,
          native_region_count INTEGER NOT NULL,
          covered_region_count INTEGER NOT NULL,
          p05 REAL,
          p10 REAL,
          p25 REAL,
          median REAL,
          p75 REAL,
          p90 REAL,
          p95 REAL,
          mean REAL,
          stddev REAL,
          source_id TEXT NOT NULL,
          method TEXT,
          method_version TEXT,
          confidence_score REAL NOT NULL,
          confidence_class TEXT NOT NULL,
          scoring_eligible INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY (taxon_id, variable)
        ) WITHOUT ROWID;

        CREATE TABLE edaphic_envelopes (
          taxon_id TEXT NOT NULL,
          variable TEXT NOT NULL,
          core_min REAL,
          core_max REAL,
          tolerance_min REAL,
          tolerance_max REAL,
          median REAL,
          source_level TEXT NOT NULL,
          confidence_score REAL NOT NULL,
          confidence_class TEXT NOT NULL,
          n_evidence INTEGER NOT NULL,
          scoring_enabled INTEGER NOT NULL,
          conflict_flag INTEGER NOT NULL DEFAULT 0,
          conflict_notes TEXT,
          updated_at TEXT NOT NULL,
          PRIMARY KEY (taxon_id, variable)
        ) WITHOUT ROWID;

        CREATE TABLE edaphic_evidence (
          evidence_id INTEGER PRIMARY KEY,
          taxon_id TEXT NOT NULL,
          variable TEXT,
          source_id TEXT NOT NULL,
          evidence_type TEXT NOT NULL,
          source_table TEXT,
          source_row_id TEXT,
          evidence_json TEXT,
          weight REAL,
          notes TEXT
        );

        CREATE TABLE edaphic_build_metadata (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        ) WITHOUT ROWID;
        """
    )


def create_production_schema(conn: sqlite3.Connection) -> None:
    # Preserve the complete original scoring/source table before replacing the runtime projection.
    tables = {str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "soil_source_envelope" not in tables:
        conn.execute("ALTER TABLE soil_envelope RENAME TO soil_source_envelope")
    else:
        conn.execute("DROP TABLE IF EXISTS soil_envelope")
    if "soil_source_categorical_preference" not in tables:
        conn.execute("CREATE TABLE soil_source_categorical_preference AS SELECT * FROM soil_categorical_preference")

    conn.executescript(
        """
        CREATE TABLE soil_envelope (
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
          UNIQUE(taxon_id, variable)
        );

        CREATE TABLE soil_sources (
          source_id TEXT PRIMARY KEY,
          source_name TEXT NOT NULL,
          source_version TEXT,
          source_url TEXT,
          license TEXT NOT NULL,
          access_date TEXT NOT NULL,
          citation TEXT,
          source_type TEXT NOT NULL,
          notes TEXT
        ) WITHOUT ROWID;

        CREATE TABLE soil_envelopes (
          taxon_id TEXT NOT NULL,
          variable TEXT NOT NULL,
          core_min REAL,
          core_max REAL,
          tolerance_min REAL,
          tolerance_max REAL,
          median REAL,
          source_level TEXT NOT NULL,
          confidence_score REAL NOT NULL,
          confidence_class TEXT NOT NULL,
          n_evidence INTEGER NOT NULL,
          scoring_enabled INTEGER NOT NULL,
          conflict_flag INTEGER NOT NULL DEFAULT 0,
          conflict_notes TEXT,
          updated_at TEXT NOT NULL,
          PRIMARY KEY (taxon_id, variable)
        ) WITHOUT ROWID;

        CREATE TABLE soil_preferences (
          taxon_id TEXT NOT NULL,
          variable TEXT NOT NULL,
          preference_type TEXT NOT NULL,
          optimum_values_json TEXT,
          accepted_values_json TEXT,
          indicator_value REAL,
          niche_width REAL,
          scale_min REAL,
          scale_max REAL,
          source_id TEXT NOT NULL,
          confidence_score REAL NOT NULL,
          confidence_class TEXT NOT NULL,
          source_ref TEXT,
          method TEXT,
          method_version TEXT,
          PRIMARY KEY (taxon_id, variable, preference_type, source_id)
        ) WITHOUT ROWID;

        CREATE TABLE soil_evidence (
          evidence_id INTEGER PRIMARY KEY,
          taxon_id TEXT NOT NULL,
          variable TEXT,
          source_id TEXT NOT NULL,
          evidence_type TEXT NOT NULL,
          source_table TEXT,
          source_row_id TEXT,
          evidence_json TEXT,
          weight REAL,
          notes TEXT
        );
        """
    )


def add_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_soil_envelope_taxon ON soil_envelope(taxon_id);
        CREATE INDEX IF NOT EXISTS idx_soil_envelope_variable ON soil_envelope(variable);
        CREATE INDEX IF NOT EXISTS idx_soil_envelopes_scoring ON soil_envelopes(scoring_enabled, variable);
        CREATE INDEX IF NOT EXISTS idx_soil_preferences_taxon ON soil_preferences(taxon_id);
        CREATE INDEX IF NOT EXISTS idx_soil_evidence_taxon ON soil_evidence(taxon_id);
        """
    )


def insert_sources(conn: sqlite3.Connection, table: str) -> None:
    today = datetime.now(timezone.utc).date().isoformat()
    conn.executemany(
        f"""INSERT OR REPLACE INTO {table}(
        source_id,source_name,source_version,source_url,license,access_date,citation,source_type,notes
        ) VALUES(?,?,?,?,?,?,?,?,?)""",
        [
            (
                s["source_id"], s["source_name"], s["source_version"], s["source_url"], s["license"],
                today, s["citation"], s["source_type"], s["notes"],
            )
            for s in SOURCES
        ],
    )


def expert_score(confidence: str | None) -> float:
    # Expert evidence sits highest in the hierarchy; inherited confidence modulates within that tier.
    c = (confidence or "").upper()
    if c == "A":
        return 0.96
    if c == "B":
        return 0.92
    if c == "C":
        return 0.88
    return 0.84


def eive_score(confidence: str | None) -> float:
    c = (confidence or "").upper()
    if c == "A":
        return 0.88
    if c == "B":
        return 0.80
    if c == "C":
        return 0.66
    return 0.55


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--build-db", required=True)
    ap.add_argument("--report", required=True)
    args = ap.parse_args()

    base = Path(args.base)
    output = Path(args.output)
    build_db = Path(args.build_db)
    report_path = Path(args.report)
    for p in (output, build_db, report_path):
        if p.exists():
            p.unlink()

    base_sha = sha256_file(base)
    shutil.copyfile(base, output)
    os.chmod(output, 0o644)

    source = sqlite3.connect(f"file:{base.resolve()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    out = sqlite3.connect(output)
    out.row_factory = sqlite3.Row
    build = sqlite3.connect(build_db)
    build.row_factory = sqlite3.Row
    for conn in (out, build):
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-65536")

    started = utcnow()
    create_build_schema(build)
    create_production_schema(out)
    insert_sources(build, "edaphic_sources")
    insert_sources(out, "soil_sources")
    build.commit()
    out.commit()

    stats: dict[str, Any] = {
        "total_taxa": int(source.execute("SELECT COUNT(*) FROM plant_index").fetchone()[0]),
        "expert_raw_rows": 0,
        "occurrence_taxa": 0,
        "occurrence_rows": 0,
        "occurrence_taxa_scoring_eligible": 0,
        "occurrence_taxa_below_10": 0,
        "native_range_taxa": int(source.execute("SELECT COUNT(*) FROM soil_geographic_prior").fetchone()[0]),
        "native_range_rows": 0,
        "expert_numeric_conflicts": 0,
        "expert_vs_occurrence_conflicts": 0,
        "canonical_rows": 0,
        "scoring_rows": 0,
        "source_level_counts": {},
        "confidence_class_counts": {},
    }

    # ------------------------------------------------------------------
    # Expert evidence: raw numeric EcoCrop + categorical EcoCrop + EIVE.
    # ------------------------------------------------------------------
    expert_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    expert_taxa: set[str] = set()

    for row in source.execute(
        "SELECT * FROM soil_source_envelope WHERE method=?" if "soil_source_envelope" in {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")} else
        "SELECT * FROM soil_envelope WHERE method=?",
        (ECO_METHOD,),
    ):
        d = dict(row)
        tid, var = str(d["taxon_id"]), str(d["variable"])
        expert_taxa.add(tid)
        expert_groups[(tid, var)].append(d)
        build.execute(
            """INSERT INTO edaphic_expert_values(
            taxon_id,source_id,source_row_type,source_row_id,variable,value_min,value_opt_min,value_opt_max,value_max,
            unit,confidence,source_ref,method,method_version
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (tid, "FAO_ECOCROP", "NUMERIC_ENVELOPE", str(d["envelope_id"]), var,
             d["hard_low"], d["optimum_low"], d["optimum_high"], d["hard_high"],
             "pH" if var == "ph" else None, d["confidence"], d["source_ref"], d["method"], d["method_version"]),
        )
        build.execute(
            """INSERT INTO edaphic_evidence(taxon_id,variable,source_id,evidence_type,source_table,source_row_id,evidence_json,weight,notes)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            (tid, var, "FAO_ECOCROP", "EXPERT_NUMERIC", "soil_source_envelope", str(d["envelope_id"]),
             json.dumps({k: d[k] for k in ("hard_low","optimum_low","optimum_high","hard_high","confidence","source_ref")}, separators=(",", ":"), sort_keys=True),
             d["weight"], "Inherited source row; preserved non-destructively."),
        )
        stats["expert_raw_rows"] += 1

    categorical_repairs = 0
    for row in source.execute("SELECT * FROM soil_categorical_preference"):
        d = dict(row)
        tid, var = str(d["taxon_id"]), str(d["variable"])
        expert_taxa.add(tid)
        raw_optimum = str(d["optimum_values_json"] or "[]")
        raw_accepted = str(d["accepted_values_json"] or "[]")
        norm_optimum = normalize_ecocrop_categories(var, raw_optimum)
        norm_accepted = normalize_ecocrop_categories(var, raw_accepted)
        if norm_optimum != raw_optimum or norm_accepted != raw_accepted:
            categorical_repairs += 1
        payload = json.dumps({"raw_optimum": json.loads(raw_optimum), "raw_accepted": json.loads(raw_accepted),
                              "normalized_optimum": json.loads(norm_optimum), "normalized_accepted": json.loads(norm_accepted)},
                             separators=(",", ":"), sort_keys=True)
        build.execute(
            """INSERT INTO edaphic_expert_values(
            taxon_id,source_id,source_row_type,source_row_id,variable,categorical_value,confidence,source_ref,method,method_version
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (tid, "FAO_ECOCROP", "CATEGORICAL_PREFERENCE", str(d["preference_id"]), var, payload,
             d["confidence"], d["source_ref"], d["method"], d["method_version"]),
        )
        build.execute(
            """INSERT INTO edaphic_evidence(taxon_id,variable,source_id,evidence_type,source_table,source_row_id,evidence_json,weight,notes)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            (tid, var, "FAO_ECOCROP", "EXPERT_CATEGORICAL", "soil_categorical_preference", str(d["preference_id"]), payload, d["weight"], None),
        )
        score = expert_score(d["confidence"])
        out.execute(
            """INSERT OR REPLACE INTO soil_preferences(
            taxon_id,variable,preference_type,optimum_values_json,accepted_values_json,source_id,confidence_score,confidence_class,source_ref,method,method_version
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (tid, var, "CATEGORICAL", norm_optimum, norm_accepted, "FAO_ECOCROP",
             score, confidence_class(score), d["source_ref"], d["method"], d["method_version"]),
        )
        stats["expert_raw_rows"] += 1

    # Repair the legacy-compatible categorical table used by the runtime while
    # preserving its v1.8 form in soil_source_categorical_preference.
    for pref_id, variable, opt_json, acc_json in out.execute(
        "SELECT preference_id,variable,optimum_values_json,accepted_values_json FROM soil_categorical_preference"
    ).fetchall():
        norm_opt = normalize_ecocrop_categories(str(variable), str(opt_json or "[]"))
        norm_acc = normalize_ecocrop_categories(str(variable), str(acc_json or "[]"))
        if norm_opt != str(opt_json or "[]") or norm_acc != str(acc_json or "[]"):
            out.execute(
                "UPDATE soil_categorical_preference SET optimum_values_json=?,accepted_values_json=? WHERE preference_id=?",
                (norm_opt, norm_acc, pref_id),
            )
    stats["categorical_rows_repaired"] = categorical_repairs

    for row in source.execute("SELECT * FROM soil_indicator_preference"):
        d = dict(row)
        tid, var = str(d["taxon_id"]), str(d["indicator"])
        expert_taxa.add(tid)
        build.execute(
            """INSERT INTO edaphic_expert_values(
            taxon_id,source_id,source_row_type,source_row_id,variable,indicator_value,niche_width,unit,confidence,source_ref,method,method_version
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (tid, "EIVE_1_0", "ECOLOGICAL_INDICATOR", str(d["preference_id"]), var, d["optimum"], d["niche_width"],
             "harmonised_0_10_indicator", d["confidence"], d["source_ref"], d["method"], d["method_version"]),
        )
        build.execute(
            """INSERT INTO edaphic_evidence(taxon_id,variable,source_id,evidence_type,source_table,source_row_id,evidence_json,weight,notes)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            (tid, var, "EIVE_1_0", "EXPERT_INDICATOR", "soil_indicator_preference", str(d["preference_id"]),
             json.dumps({"optimum": d["optimum"], "niche_width": d["niche_width"], "scale_min": d["scale_min"], "scale_max": d["scale_max"], "source_systems": d["source_systems"]}, separators=(",", ":"), sort_keys=True),
             d["weight"], "Ecological indicator scale; not converted to physical soil units."),
        )
        score = eive_score(d["confidence"])
        out.execute(
            """INSERT OR REPLACE INTO soil_preferences(
            taxon_id,variable,preference_type,indicator_value,niche_width,scale_min,scale_max,source_id,confidence_score,confidence_class,source_ref,method,method_version
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (tid, var, "INDICATOR", d["optimum"], d["niche_width"], d["scale_min"], d["scale_max"], "EIVE_1_0",
             score, confidence_class(score), d["source_ref"], d["method"], d["method_version"]),
        )
        stats["expert_raw_rows"] += 1

    build.commit()
    out.commit()

    # ------------------------------------------------------------------
    # Occurrence evidence: parse per-taxon sample-quality metadata first.
    # ------------------------------------------------------------------
    occ_meta: dict[str, tuple[int, int, int, str, str]] = {}
    for row in source.execute(
        "SELECT taxon_id,claim_value,confidence,source_reference FROM evidence WHERE claim_type='soil_realized_niche' AND source_id='SPLOTOPEN_SOILGRIDS'"
    ):
        payload = json.loads(row["claim_value"] or "{}")
        tid = str(row["taxon_id"])
        n = int(payload.get("n_plots") or 0)
        geo = int(payload.get("geo_cells_2deg") or 0)
        countries = int(payload.get("countries") or 0)
        occ_meta[tid] = (n, geo, countries, str(row["confidence"] or ""), str(row["source_reference"] or ""))
        build.execute(
            """INSERT INTO edaphic_evidence(taxon_id,variable,source_id,evidence_type,source_table,source_row_id,evidence_json,weight,notes)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            (tid, None, "SPLOTOPEN+SOILGRIDS_2", "OCCURRENCE_REALIZED_NICHE", "evidence", None,
             row["claim_value"], None, "Observed realized niche; not physiological tolerance."),
        )
        out.execute(
            """INSERT INTO soil_evidence(taxon_id,variable,source_id,evidence_type,source_table,source_row_id,evidence_json,weight,notes)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            (tid, None, "SPLOTOPEN+SOILGRIDS_2", "OCCURRENCE_REALIZED_NICHE", "evidence", None,
             row["claim_value"], None, "Observed realized niche; not physiological tolerance."),
        )

    stats["occurrence_taxa"] = len(occ_meta)
    stats["occurrence_taxa_below_10"] = sum(1 for n, *_ in occ_meta.values() if n < 10)
    stats["occurrence_taxa_scoring_eligible"] = sum(1 for n, *_ in occ_meta.values() if n >= 10)

    occurrence: dict[tuple[str, str], dict[str, Any]] = {}
    src_envelope_table = "soil_source_envelope" if "soil_source_envelope" in {str(r[0]) for r in out.execute("SELECT name FROM sqlite_master WHERE type='table'")} else "soil_envelope"
    for row in out.execute(f"SELECT * FROM {src_envelope_table} WHERE method=?", (SPLOT_METHOD,)):
        d = dict(row)
        tid, var = str(d["taxon_id"]), str(d["variable"])
        n, geo, countries, legacy_conf, _ = occ_meta.get(tid, (0, 0, 0, "", ""))
        score = occurrence_confidence(n, geo, countries)
        eligible = int(n >= 10)
        occurrence[(tid, var)] = {**d, "n": n, "geo": geo, "countries": countries, "score": score, "eligible": eligible}
        build.execute(
            """INSERT OR REPLACE INTO edaphic_occurrence_stats(
            taxon_id,variable,n_occurrences,geo_cells,countries,p05,p25,p75,p95,source_id,method,method_version,
            confidence_score,confidence_class,scoring_eligible
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (tid, var, n, geo, countries, d["hard_low"], d["optimum_low"], d["optimum_high"], d["hard_high"],
             "SPLOTOPEN+SOILGRIDS_2", d["method"], d["method_version"], score, confidence_class(score), eligible),
        )
        stats["occurrence_rows"] += 1
    build.commit()
    out.commit()

    # ------------------------------------------------------------------
    # Native-range prior: compact evidence in production, full rows in build DB.
    # Seed canonical envelopes with lowest-priority, non-scoring context.
    # ------------------------------------------------------------------
    now = utcnow()
    native_batch: list[tuple[Any, ...]] = []
    canonical_batch: list[tuple[Any, ...]] = []
    evidence_batch: list[tuple[Any, ...]] = []
    for row in source.execute("SELECT * FROM soil_geographic_prior"):
        d = dict(row)
        tid = str(d["taxon_id"])
        variables = json.loads(d["variables_json"] or "{}")
        evidence_batch.append((tid, None, "WCVP+WGSRPD+SOILGRIDS_2", "NATIVE_RANGE_AVAILABLE_SOIL", "soil_geographic_prior", tid,
                               json.dumps({"native_region_count": d["native_region_count"], "covered_region_count": d["covered_region_count"]}, separators=(",", ":")),
                               None, "Context only: soils available within native range; never numerical preference evidence."))
        for var, s in variables.items():
            p05 = finite(s.get("outer_low"))
            p25 = finite(s.get("central_low"))
            p50 = finite(s.get("region_median"))
            p75 = finite(s.get("central_high"))
            p95 = finite(s.get("outer_high"))
            if not validate_numeric(var, (p05, p25, p50, p75, p95)):
                continue
            native_batch.append((tid, var, int(d["native_region_count"]), int(d["covered_region_count"]), p05, p25, p50, p75, p95,
                                 "WCVP+WGSRPD+SOILGRIDS_2", d["method"], d["method_version"], 0.30, "D", 0))
            canonical_batch.append((tid, var, p25, p75, p05, p95, p50, "NATIVE_RANGE_DERIVED", 0.30, "D", 1, 0, 0, None, now))
            stats["native_range_rows"] += 1
        if len(native_batch) >= 20000:
            build.executemany(
                """INSERT OR REPLACE INTO edaphic_native_range_stats(
                taxon_id,variable,native_region_count,covered_region_count,p05,p25,median,p75,p95,source_id,method,method_version,
                confidence_score,confidence_class,scoring_eligible
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", native_batch)
            build.executemany(
                """INSERT OR REPLACE INTO edaphic_envelopes(
                taxon_id,variable,core_min,core_max,tolerance_min,tolerance_max,median,source_level,confidence_score,confidence_class,
                n_evidence,scoring_enabled,conflict_flag,conflict_notes,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", canonical_batch)
            out.executemany(
                """INSERT OR REPLACE INTO soil_envelopes(
                taxon_id,variable,core_min,core_max,tolerance_min,tolerance_max,median,source_level,confidence_score,confidence_class,
                n_evidence,scoring_enabled,conflict_flag,conflict_notes,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", canonical_batch)
            native_batch.clear(); canonical_batch.clear()
        if len(evidence_batch) >= 10000:
            build.executemany(
                """INSERT INTO edaphic_evidence(taxon_id,variable,source_id,evidence_type,source_table,source_row_id,evidence_json,weight,notes)
                VALUES(?,?,?,?,?,?,?,?,?)""", evidence_batch)
            out.executemany(
                """INSERT INTO soil_evidence(taxon_id,variable,source_id,evidence_type,source_table,source_row_id,evidence_json,weight,notes)
                VALUES(?,?,?,?,?,?,?,?,?)""", evidence_batch)
            evidence_batch.clear()
    if native_batch:
        build.executemany(
            """INSERT OR REPLACE INTO edaphic_native_range_stats(
            taxon_id,variable,native_region_count,covered_region_count,p05,p25,median,p75,p95,source_id,method,method_version,
            confidence_score,confidence_class,scoring_eligible
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", native_batch)
        build.executemany(
            """INSERT OR REPLACE INTO edaphic_envelopes(
            taxon_id,variable,core_min,core_max,tolerance_min,tolerance_max,median,source_level,confidence_score,confidence_class,
            n_evidence,scoring_enabled,conflict_flag,conflict_notes,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", canonical_batch)
        out.executemany(
            """INSERT OR REPLACE INTO soil_envelopes(
            taxon_id,variable,core_min,core_max,tolerance_min,tolerance_max,median,source_level,confidence_score,confidence_class,
            n_evidence,scoring_enabled,conflict_flag,conflict_notes,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", canonical_batch)
    if evidence_batch:
        build.executemany(
            """INSERT INTO edaphic_evidence(taxon_id,variable,source_id,evidence_type,source_table,source_row_id,evidence_json,weight,notes)
            VALUES(?,?,?,?,?,?,?,?,?)""", evidence_batch)
        out.executemany(
            """INSERT INTO soil_evidence(taxon_id,variable,source_id,evidence_type,source_table,source_row_id,evidence_json,weight,notes)
            VALUES(?,?,?,?,?,?,?,?,?)""", evidence_batch)
    build.commit(); out.commit()

    # ------------------------------------------------------------------
    # Upsert occurrence envelopes over native context. Keep <10 as context,
    # but explicitly disable them for scoring.
    # ------------------------------------------------------------------
    for (tid, var), d in occurrence.items():
        existing = out.execute("SELECT source_level,n_evidence FROM soil_envelopes WHERE taxon_id=? AND variable=?", (tid, var)).fetchone()
        level = "OCCURRENCE_NATIVE_RANGE" if existing else "OCCURRENCE_DERIVED"
        n_evidence = (int(existing["n_evidence"]) if existing else 0) + 1
        row = (tid, var, d["optimum_low"], d["optimum_high"], d["hard_low"], d["hard_high"], None,
               level, d["score"], confidence_class(d["score"]), n_evidence, d["eligible"], 0,
               None if d["eligible"] else "Occurrence sample below n=10; retained as context but excluded from scoring.", now)
        for conn, table in ((out, "soil_envelopes"), (build, "edaphic_envelopes")):
            conn.execute(
                f"""INSERT OR REPLACE INTO {table}(
                taxon_id,variable,core_min,core_max,tolerance_min,tolerance_max,median,source_level,confidence_score,confidence_class,
                n_evidence,scoring_enabled,conflict_flag,conflict_notes,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", row)
    build.commit(); out.commit()

    # ------------------------------------------------------------------
    # Expert numerical consolidation over occurrence/native context.
    # Duplicate ECOCROP rows: use intersection of optimum ranges only when
    # non-empty; otherwise flag conflict and make the numeric claim non-scoring.
    # Absolute tolerances are the union so no source evidence is discarded.
    # ------------------------------------------------------------------
    expert_canonical: dict[tuple[str, str], dict[str, Any]] = {}
    for key, rows in expert_groups.items():
        tid, var = key
        hard_lows = [finite(r["hard_low"]) for r in rows if finite(r["hard_low"]) is not None]
        hard_highs = [finite(r["hard_high"]) for r in rows if finite(r["hard_high"]) is not None]
        opt_lows = [finite(r["optimum_low"]) for r in rows if finite(r["optimum_low"]) is not None]
        opt_highs = [finite(r["optimum_high"]) for r in rows if finite(r["optimum_high"]) is not None]
        tolerance_min = min(hard_lows) if hard_lows else None
        tolerance_max = max(hard_highs) if hard_highs else None
        core_min = max(opt_lows) if opt_lows else None
        core_max = min(opt_highs) if opt_highs else None
        conflict = bool(core_min is not None and core_max is not None and core_min > core_max)
        if conflict:
            stats["expert_numeric_conflicts"] += 1
        if not validate_numeric(var, (tolerance_min, tolerance_max, core_min, core_max)):
            conflict = True
        base_score = max(expert_score(r.get("confidence")) for r in rows)
        previous = out.execute("SELECT * FROM soil_envelopes WHERE taxon_id=? AND variable=?", (tid, var)).fetchone()
        previous_level = str(previous["source_level"]) if previous else ""
        has_occ = (tid, var) in occurrence
        has_native = bool(previous and "NATIVE_RANGE" in previous_level)
        level = "EXPERT"
        if has_occ and has_native:
            level = "EXPERT_OCCURRENCE_NATIVE_RANGE"
        elif has_occ:
            level = "EXPERT_OCCURRENCE"
        elif has_native:
            level = "EXPERT_NATIVE_RANGE"
        conflict_notes: list[str] = []
        if conflict:
            conflict_notes.append("Conflicting direct expert optimum ranges; no automatic scoring.")
        if has_occ:
            od = occurrence[(tid, var)]
            ratio = overlap_ratio(tolerance_min, tolerance_max, finite(od["hard_low"]), finite(od["hard_high"]))
            if ratio is not None and ratio == 0.0:
                stats["expert_vs_occurrence_conflicts"] += 1
                conflict_notes.append("Expert absolute range and occurrence P05–P95 do not overlap.")
                base_score = max(0.70, base_score - 0.10)
            elif ratio is not None and ratio >= 0.25 and od["n"] >= 30:
                base_score = min(0.97, base_score + 0.04)
        score = round(base_score, 4)
        n_evidence = (int(previous["n_evidence"]) if previous else 0) + len(rows)
        scoring_enabled = int(not conflict and tolerance_min is not None and tolerance_max is not None and core_min is not None and core_max is not None)
        row = (tid, var, None if conflict else core_min, None if conflict else core_max, tolerance_min, tolerance_max, None,
               level, score, confidence_class(score), n_evidence, scoring_enabled, int(bool(conflict_notes)),
               " ".join(conflict_notes) if conflict_notes else None, now)
        expert_canonical[key] = {
            "row": row,
            "weight": max(float(r.get("weight") or 1.0) for r in rows),
            "source_ref": " | ".join(sorted({str(r.get("source_ref") or "") for r in rows if r.get("source_ref")})),
        }
        for conn, table in ((out, "soil_envelopes"), (build, "edaphic_envelopes")):
            conn.execute(
                f"""INSERT OR REPLACE INTO {table}(
                taxon_id,variable,core_min,core_max,tolerance_min,tolerance_max,median,source_level,confidence_score,confidence_class,
                n_evidence,scoring_enabled,conflict_flag,conflict_notes,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", row)
    build.commit(); out.commit()

    # ------------------------------------------------------------------
    # Runtime projection: only canonical numerical envelopes explicitly
    # eligible for scoring. One row per taxon-variable, no geographic priors.
    # ------------------------------------------------------------------
    runtime_rows = []
    for row in out.execute("SELECT * FROM soil_envelopes WHERE scoring_enabled=1 ORDER BY taxon_id,variable"):
        tid, var = str(row["taxon_id"]), str(row["variable"])
        level = str(row["source_level"])
        if level.startswith("EXPERT"):
            meta = expert_canonical[(tid, var)]
            weight = meta["weight"]
            source_ref = meta["source_ref"]
        else:
            d = occurrence.get((tid, var))
            if not d or int(d["n"]) < 10:
                continue
            weight = float(d.get("weight") or 1.0)
            source_ref = str(d.get("source_ref") or "")
        runtime_rows.append((
            tid, var, row["tolerance_min"], row["core_min"], row["core_max"], row["tolerance_max"],
            weight, "E", 0, row["confidence_class"], source_ref, METHOD, METHOD_VERSION,
        ))
        if len(runtime_rows) >= 20000:
            out.executemany(
                """INSERT INTO soil_envelope(
                taxon_id,variable,hard_low,optimum_low,optimum_high,hard_high,weight,group_code,fatal,confidence,source_ref,method,method_version
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", runtime_rows)
            runtime_rows.clear()
    if runtime_rows:
        out.executemany(
            """INSERT INTO soil_envelope(
            taxon_id,variable,hard_low,optimum_low,optimum_high,hard_high,weight,group_code,fatal,confidence,source_ref,method,method_version
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", runtime_rows)
    out.commit()

    # Copy expert evidence into production only after source-table rename is stable.
    for row in build.execute("SELECT taxon_id,variable,source_id,evidence_type,source_table,source_row_id,evidence_json,weight,notes FROM edaphic_evidence WHERE evidence_type LIKE 'EXPERT_%'"):
        out.execute(
            """INSERT INTO soil_evidence(taxon_id,variable,source_id,evidence_type,source_table,source_row_id,evidence_json,weight,notes)
            VALUES(?,?,?,?,?,?,?,?,?)""", tuple(row))
    out.commit()

    # ------------------------------------------------------------------
    # Metrics and mandatory controls.
    # ------------------------------------------------------------------
    stats["canonical_rows"] = int(out.execute("SELECT COUNT(*) FROM soil_envelopes").fetchone()[0])
    stats["scoring_rows"] = int(out.execute("SELECT COUNT(*) FROM soil_envelope").fetchone()[0])
    stats["source_level_counts"] = {str(k): int(v) for k, v in out.execute("SELECT source_level,COUNT(*) FROM soil_envelopes GROUP BY source_level")}
    stats["confidence_class_counts"] = {str(k): int(v) for k, v in out.execute("SELECT confidence_class,COUNT(*) FROM soil_envelopes GROUP BY confidence_class")}
    stats["taxa_with_expert_data"] = len(expert_taxa)
    stats["taxa_with_occurrence_data"] = len(occ_meta)
    stats["taxa_with_native_range_data"] = stats["native_range_taxa"]
    stats["taxa_with_scored_numeric_envelope"] = int(out.execute("SELECT COUNT(DISTINCT taxon_id) FROM soil_envelope").fetchone()[0])

    # Any soil context includes categorical/indicators, occurrence, or native prior.
    any_soil = int(out.execute(
        """SELECT COUNT(DISTINCT taxon_id) FROM (
          SELECT taxon_id FROM soil_categorical_preference
          UNION SELECT taxon_id FROM soil_indicator_preference
          UNION SELECT taxon_id FROM soil_source_envelope
          UNION SELECT taxon_id FROM soil_geographic_prior
        )"""
    ).fetchone()[0])
    stats["taxa_with_any_soil_data"] = any_soil
    stats["taxa_without_soil_data"] = stats["total_taxa"] - any_soil
    stats["coverage_any"] = any_soil / stats["total_taxa"]
    stats["coverage_expert"] = len(expert_taxa) / stats["total_taxa"]
    stats["coverage_occurrence"] = len(occ_meta) / stats["total_taxa"]
    stats["coverage_native_range"] = stats["native_range_taxa"] / stats["total_taxa"]
    stats["coverage_by_variable"] = {
        str(var): int(n) / stats["total_taxa"]
        for var, n in out.execute("SELECT variable,COUNT(DISTINCT taxon_id) FROM soil_envelopes GROUP BY variable")
    }

    validation = {
        "duplicate_runtime_taxon_variable": int(out.execute("SELECT COUNT(*) FROM (SELECT taxon_id,variable,COUNT(*) c FROM soil_envelope GROUP BY taxon_id,variable HAVING c>1)").fetchone()[0]),
        "native_priors_scoring_enabled": int(out.execute("SELECT COUNT(*) FROM soil_geographic_prior WHERE scoring_enabled<>0").fetchone()[0]),
        "canonical_native_scoring_enabled": int(out.execute("SELECT COUNT(*) FROM soil_envelopes WHERE source_level='NATIVE_RANGE_DERIVED' AND scoring_enabled<>0").fetchone()[0]),
        "invalid_ph_runtime": int(out.execute("SELECT COUNT(*) FROM soil_envelope WHERE variable='ph' AND (hard_low<0 OR hard_high>14 OR hard_low>optimum_low OR optimum_low>optimum_high OR optimum_high>hard_high)").fetchone()[0]),
        "invalid_numeric_runtime_order": int(out.execute("SELECT COUNT(*) FROM soil_envelope WHERE hard_low IS NULL OR optimum_low IS NULL OR optimum_high IS NULL OR hard_high IS NULL OR hard_low>optimum_low OR optimum_low>optimum_high OR optimum_high>hard_high").fetchone()[0]),
        "occurrence_below_10_scoring": int(out.execute(
            """SELECT COUNT(*) FROM soil_envelope e JOIN soil_envelopes c USING(taxon_id,variable)
            WHERE c.source_level LIKE 'OCCURRENCE%' AND c.scoring_enabled=1 AND c.confidence_score<0.50"""
        ).fetchone()[0]),
        "eive_physical_conversion_rows": int(out.execute("SELECT COUNT(*) FROM soil_envelope WHERE source_ref LIKE '%98324%'").fetchone()[0]),
        "missing_source_license": int(out.execute("SELECT COUNT(*) FROM soil_sources WHERE trim(coalesce(license,''))='' ").fetchone()[0]),
        "runtime_nonconsolidated_method_rows": int(out.execute("SELECT COUNT(*) FROM soil_envelope WHERE method<>? OR method_version<>?", (METHOD, METHOD_VERSION)).fetchone()[0]),
        "broken_salinity_tokens": int(out.execute(
            "SELECT COUNT(*) FROM soil_categorical_preference WHERE variable='salinity' AND (optimum_values_json LIKE '%\"m)\"%' OR accepted_values_json LIKE '%\"m)\"%' OR optimum_values_json LIKE '%\"m))\"%' OR accepted_values_json LIKE '%\"m))\"%')"
        ).fetchone()[0]),
        "broken_drainage_tokens": int(out.execute(
            "SELECT COUNT(*) FROM soil_categorical_preference WHERE variable='drainage' AND (optimum_values_json LIKE '%\"excessive (dry\"%' OR accepted_values_json LIKE '%\"excessive (dry\"%' OR optimum_values_json LIKE '%\"moderately dry)\"%' OR accepted_values_json LIKE '%\"moderately dry)\"%')"
        ).fetchone()[0]),
    }

    # Cross-check every occurrence runtime row against explicit n>=10 metadata.
    bad_n = 0
    for row in out.execute("SELECT taxon_id,variable FROM soil_envelopes WHERE scoring_enabled=1 AND source_level LIKE 'OCCURRENCE%'"):
        meta = occ_meta.get(str(row["taxon_id"]))
        if not meta or meta[0] < 10:
            bad_n += 1
    validation["occurrence_n_lt_10_exact"] = bad_n

    # Manual audit sample values (not hard-coded scientific pass/fail assertions).
    audit_names = [
        "Vaccinium myrtillus", "Rhododendron ponticum", "Buxus sempervirens", "Typha latifolia",
        "Sedum acre", "Salicornia europaea", "Ammophila arenaria", "Quercus robur",
    ]
    manual_sample = []
    for name in audit_names:
        taxon = source.execute("SELECT taxon_id,scientific_name FROM plant_index WHERE scientific_name=?", (name,)).fetchone()
        if not taxon:
            continue
        tid = str(taxon["taxon_id"])
        envs = [dict(r) for r in out.execute("SELECT * FROM soil_envelopes WHERE taxon_id=? ORDER BY variable", (tid,))]
        prefs = [dict(r) for r in out.execute("SELECT * FROM soil_preferences WHERE taxon_id=? ORDER BY variable", (tid,))]
        manual_sample.append({"taxon_id": tid, "scientific_name": name, "envelopes": envs, "preferences": prefs})

    blocking_keys = [
        "duplicate_runtime_taxon_variable", "native_priors_scoring_enabled", "canonical_native_scoring_enabled",
        "invalid_ph_runtime", "invalid_numeric_runtime_order", "occurrence_below_10_scoring",
        "eive_physical_conversion_rows", "missing_source_license", "runtime_nonconsolidated_method_rows", "occurrence_n_lt_10_exact",
        "broken_salinity_tokens", "broken_drainage_tokens",
    ]
    validation["blocking_failures"] = sum(int(validation[k]) for k in blocking_keys)

    metadata = {
        "catalog_version": CATALOG_VERSION,
        "catalog_schema_version": CATALOG_VERSION,
        "scientific_ready": "true" if validation["blocking_failures"] == 0 else "false",
        "edaphic_build_version": BUILD_VERSION,
        "edaphic_consolidation_method": METHOD,
        "edaphic_consolidation_method_version": METHOD_VERSION,
        "edaphic_source_catalog": base.name,
        "edaphic_source_catalog_sha256": base_sha,
        "edaphic_generated_at": utcnow(),
        "edaphic_occurrence_min_n_for_scoring": "10",
        "edaphic_native_range_scoring_enabled": "false",
        "edaphic_eive_physical_conversion": "false",
        "edaphic_taxonomy_policy": "inherited exact deterministic ClimaFlora/WCVP IDs; no new fuzzy matching",
        "edaphic_unknown_policy": "UNKNOWN preferred to unsupported inference",
        "soil_geographic_prior_scoring_enabled": "false",
    }
    out.executemany("INSERT OR REPLACE INTO climaflora_catalog_metadata(key,value) VALUES(?,?)", metadata.items())
    out.executemany("INSERT OR REPLACE INTO build_metadata(key,value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)", [(k, v) for k, v in metadata.items()])
    build_meta = {
        **metadata,
        "source_catalog_path": str(base),
        "output_catalog_path": str(output),
        "build_database_path": str(build_db),
        "blocking_failures": str(validation["blocking_failures"]),
    }
    build.executemany("INSERT OR REPLACE INTO edaphic_build_metadata(key,value) VALUES(?,?)", build_meta.items())
    out.commit(); build.commit()

    add_indexes(out)
    out.commit()
    build.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_expert_taxon ON edaphic_expert_values(taxon_id);
        CREATE INDEX IF NOT EXISTS idx_evidence_taxon ON edaphic_evidence(taxon_id);
        CREATE INDEX IF NOT EXISTS idx_envelopes_scoring ON edaphic_envelopes(scoring_enabled,variable);
        """
    )
    build.commit()

    # Fast and full SQLite checks. Full integrity_check is mandatory before READY.
    quick_out = out.execute("PRAGMA quick_check").fetchone()[0]
    quick_build = build.execute("PRAGMA quick_check").fetchone()[0]
    integrity_out = out.execute("PRAGMA integrity_check").fetchone()[0]
    integrity_build = build.execute("PRAGMA integrity_check").fetchone()[0]
    validation.update({
        "quick_check_catalog": quick_out,
        "quick_check_build": quick_build,
        "integrity_check_catalog": integrity_out,
        "integrity_check_build": integrity_build,
    })
    if quick_out != "ok" or quick_build != "ok" or integrity_out != "ok" or integrity_build != "ok":
        validation["blocking_failures"] += 1

    out.close(); build.close(); source.close()

    # Immutability check after all processing.
    base_sha_after = sha256_file(base)
    source_immutable = base_sha_after == base_sha
    if not source_immutable:
        validation["blocking_failures"] += 1

    status = "ready" if validation["blocking_failures"] == 0 else "failed"
    report = {
        "status": status,
        "catalog_version": CATALOG_VERSION,
        "edaphic_build_version": BUILD_VERSION,
        "started_at": started,
        "completed_at": utcnow(),
        "source_catalog": {"path": str(base), "sha256_before": base_sha, "sha256_after": base_sha_after, "immutable": source_immutable},
        "sources": {s["source_id"]: s for s in SOURCES},
        "stats": stats,
        "validation": validation,
        "manual_scientific_audit_sample": manual_sample,
        "artifacts": {
            "catalog_sqlite": str(output),
            "catalog_sqlite_bytes": output.stat().st_size,
            "catalog_sqlite_sha256": sha256_file(output),
            "edaphic_build_sqlite": str(build_db),
            "edaphic_build_sqlite_bytes": build_db.stat().st_size,
            "edaphic_build_sqlite_sha256": sha256_file(build_db),
        },
        "limitations": [
            "v1.9 consolidates validated edaphic evidence already present in ClimaFlora v1.8; it does not acquire new GBIF/BIEN occurrences.",
            "Legacy sPlotOpen-derived rows contain P05/P25/P75/P95; P10/P50/P90/mean/stddev remain NULL because the raw plots are not re-derived in this consolidation build.",
            "Native-range SoilGrids context represents soil availability within WCVP/TDWG native regions, not species preference, and remains excluded from scoring.",
            "EIVE moisture/nutrient/reaction values remain ecological indicators on harmonised scales and are not converted to physical units.",
        ],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "stats": stats, "validation": validation, "artifacts": report["artifacts"]}, ensure_ascii=False, indent=2))
    if status != "ready":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
