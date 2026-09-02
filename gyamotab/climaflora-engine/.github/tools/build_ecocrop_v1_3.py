from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CATALOG_VERSION = "1.3.0"
METHOD = "FAO_ECOCROP_BULK_DOCUMENTED"
METHOD_VERSION = "2.1"
FAO_BASE = "https://ecocrop.apps.fao.org/ecocrop/srv/en/dataSheet?id={}"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def norm_header(value: str) -> str:
    return "".join(ch for ch in value.upper().strip() if ch.isalnum())


def find_col(headers: list[str], *aliases: str) -> str | None:
    lookup = {norm_header(h): h for h in headers}
    for alias in aliases:
        key = norm_header(alias)
        if key in lookup:
            return lookup[key]
    return None


def parse_float(value: Any) -> float | None:
    text = str(value or "").strip().replace(",", ".")
    if not text or text.lower() in {"na", "n/a", "none", "null", "-", "--"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def split_values(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    for sep in (";", "|", "/"):
        text = text.replace(sep, ",")
    values = []
    for part in text.split(","):
        cleaned = " ".join(part.strip().lower().split())
        if cleaned and cleaned not in values:
            values.append(cleaned)
    return values


def read_ecocrop_csv(path: Path) -> tuple[list[str], list[dict[str, str]], str]:
    raw = path.read_bytes()
    text: str | None = None
    source_encoding = ""
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(encoding)
            source_encoding = encoding
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("latin-1")
        source_encoding = "latin-1"

    reader = csv.DictReader(io.StringIO(text, newline=""))
    headers = reader.fieldnames or []
    return headers, list(reader), source_encoding


def _resolve_exact_taxon(conn: sqlite3.Connection, name: str) -> tuple[str | None, str]:
    row = conn.execute(
        "SELECT taxon_id FROM plant_index WHERE scientific_name=? LIMIT 1",
        (name,),
    ).fetchone()
    if row:
        return str(row[0]), "accepted_name"

    row = conn.execute(
        """
        SELECT CAST(COALESCE(n.accepted_name_usage_id,n.taxon_id) AS TEXT)
        FROM wcvp_names n
        JOIN plant_index p ON p.taxon_id=CAST(COALESCE(n.accepted_name_usage_id,n.taxon_id) AS TEXT)
        WHERE n.scientific_name=?
        ORDER BY CASE WHEN lower(COALESCE(n.taxonomic_status,''))='accepted' THEN 0 ELSE 1 END
        LIMIT 1
        """,
        (name,),
    ).fetchone()
    if row:
        return str(row[0]), "wcvp_synonym"
    return None, "unmatched"


def _notation_candidates(name: str) -> list[tuple[str, str]]:
    """Return deterministic botanical-notation variants only; never fuzzy matches."""
    candidates: list[tuple[str, str]] = []
    seen = {name}

    def add(value: str, strategy: str) -> None:
        value = " ".join(value.split())
        if value and value not in seen:
            seen.add(value)
            candidates.append((value, strategy))

    normalized = re.sub(r"\bssp\.\s+", "subsp. ", name, flags=re.IGNORECASE)
    normalized = re.sub(r"\bvar\s+", "var. ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(
        r"^(\S+\s+\S+)\s+sp\.\s+",
        r"\1 subsp. ",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"\s+[xX]\s+", " × ", normalized)
    add(normalized, "notation_normalized")

    tokens = normalized.split()
    if len(tokens) >= 2 and tokens[1] != "×" and tokens[1].lower() not in {"sp", "sp."}:
        add(" ".join([tokens[0], "×", *tokens[1:]]), "hybrid_marker_recovered")

    return candidates


def _norm_authorship(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "").replace(".", "").lower()


def _authorship_candidates(conn: sqlite3.Connection, source_name: str) -> list[str]:
    tokens = source_name.split()
    candidates: list[str] = []
    for split_at in range(2, len(tokens)):
        base = " ".join(tokens[:split_at])
        source_author = " ".join(tokens[split_at:])
        rows = conn.execute(
            "SELECT scientific_name_authorship FROM wcvp_names WHERE scientific_name=?",
            (base,),
        ).fetchall()
        if any(auth and _norm_authorship(auth) == _norm_authorship(source_author) for (auth,) in rows):
            candidates.append(base)
    return candidates


def lookup_taxon(conn: sqlite3.Connection, name: str) -> tuple[str | None, str, str | None]:
    taxon_id, exact_strategy = _resolve_exact_taxon(conn, name)
    if taxon_id:
        return taxon_id, exact_strategy, name

    for candidate, strategy in _notation_candidates(name):
        taxon_id, _ = _resolve_exact_taxon(conn, candidate)
        if taxon_id:
            return taxon_id, strategy, candidate

    for candidate in _authorship_candidates(conn, name):
        taxon_id, _ = _resolve_exact_taxon(conn, candidate)
        if taxon_id:
            return taxon_id, "authorship_stripped", candidate

    return None, "unmatched", None


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS soil_categorical_preference (
          preference_id INTEGER PRIMARY KEY,
          taxon_id TEXT NOT NULL,
          variable TEXT NOT NULL,
          optimum_values_json TEXT NOT NULL,
          accepted_values_json TEXT NOT NULL,
          weight REAL NOT NULL DEFAULT 1.0,
          confidence TEXT NOT NULL DEFAULT 'UNKNOWN',
          source_ref TEXT,
          method TEXT,
          method_version TEXT,
          UNIQUE(taxon_id, variable, method_version)
        );
        CREATE INDEX IF NOT EXISTS idx_cf_soil_categorical_taxon
          ON soil_categorical_preference(taxon_id);
        CREATE TABLE IF NOT EXISTS climaflora_catalog_metadata (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        """
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--report", required=True)
    args = ap.parse_args()

    base = Path(args.base)
    csv_path = Path(args.csv)
    output = Path(args.output)
    report_path = Path(args.report)
    tmp = output.with_suffix(output.suffix + ".building")
    if tmp.exists():
        tmp.unlink()
    shutil.copyfile(base, tmp)

    headers, rows, source_encoding = read_ecocrop_csv(csv_path)

    name_col = find_col(headers, "SCIENTIFIC_NAME", "SCIENTIFIC NAME", "SPECIES", "SPNAME", "NAME")
    id_col = find_col(headers, "ID", "ECOCROP_ID", "ECOCROP ID", "CROPID", "CROP ID", "ECOPORTCODE")
    if not name_col:
        raise RuntimeError(f"No scientific-name column found. Headers: {headers}")

    cols = {
        "ph_opt_min": find_col(headers, "PHOPMN"),
        "ph_opt_max": find_col(headers, "PHOPMX"),
        "ph_abs_min": find_col(headers, "PHMIN"),
        "ph_abs_max": find_col(headers, "PHMAX"),
        "texture_opt": find_col(headers, "TEXT"),
        "texture_abs": find_col(headers, "TEXTR"),
        "depth_opt": find_col(headers, "DEP"),
        "depth_abs": find_col(headers, "DEPR"),
        "fertility_opt": find_col(headers, "FER"),
        "fertility_abs": find_col(headers, "FERR"),
        "salinity_opt": find_col(headers, "SAL"),
        "salinity_abs": find_col(headers, "SALR"),
        "drainage_opt": find_col(headers, "DRA"),
        "drainage_abs": find_col(headers, "DRAR"),
    }

    match_strategies = {
        "accepted_name": 0,
        "wcvp_synonym": 0,
        "notation_normalized": 0,
        "hybrid_marker_recovered": 0,
        "authorship_stripped": 0,
    }
    stats = {
        "source_rows": len(rows),
        "accepted_name_matches": 0,
        "synonym_matches": 0,
        "normalized_matches": 0,
        "unmatched": 0,
        "numeric_preferences": 0,
        "categorical_preferences": 0,
        "evidence_rows": 0,
        "skipped_without_soil_data": 0,
        "match_strategies": match_strategies,
    }
    unmatched_names: list[str] = []
    matched_taxa: set[str] = set()

    with sqlite3.connect(tmp) as conn:
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA synchronous=NORMAL")
        ensure_schema(conn)

        conn.execute("DELETE FROM soil_envelope WHERE method LIKE 'FAO_ECOCROP%'")
        conn.execute("DELETE FROM soil_categorical_preference WHERE method LIKE 'FAO_ECOCROP%'")
        conn.execute("DELETE FROM evidence WHERE claim_type='soil_preference' AND source_id='FAO_ECOCROP'")

        for row in rows:
            name = " ".join(str(row.get(name_col) or "").strip().split())
            if not name:
                continue
            taxon_id, strategy, matched_name = lookup_taxon(conn, name)
            if not taxon_id:
                stats["unmatched"] += 1
                if len(unmatched_names) < 500:
                    unmatched_names.append(name)
                continue

            match_strategies[strategy] += 1
            if strategy == "accepted_name":
                stats["accepted_name_matches"] += 1
            elif strategy == "wcvp_synonym":
                stats["synonym_matches"] += 1
            else:
                stats["normalized_matches"] += 1
            matched_taxa.add(taxon_id)

            ecocrop_id = str(row.get(id_col) or "").strip() if id_col else ""
            source_ref = FAO_BASE.format(ecocrop_id) if ecocrop_id.isdigit() else "https://ecocrop.apps.fao.org/"

            p = {k: parse_float(row.get(v)) if v else None for k, v in cols.items() if k.startswith("ph_")}
            numeric_inserted = False
            if all(p.get(k) is not None for k in ("ph_opt_min", "ph_opt_max", "ph_abs_min", "ph_abs_max")):
                if 0 <= p["ph_abs_min"] <= p["ph_opt_min"] <= p["ph_opt_max"] <= p["ph_abs_max"] <= 14:
                    conn.execute(
                        """INSERT OR REPLACE INTO soil_envelope(
                        taxon_id,variable,hard_low,optimum_low,optimum_high,hard_high,
                        weight,group_code,fatal,confidence,source_ref,method,method_version
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (taxon_id, "ph", p["ph_abs_min"], p["ph_opt_min"], p["ph_opt_max"], p["ph_abs_max"],
                         0.45, "E", 0, "C", source_ref, METHOD, METHOD_VERSION),
                    )
                    stats["numeric_preferences"] += 1
                    numeric_inserted = True

            categorical_inserted = 0
            for variable, opt_key, abs_key, weight in (
                ("texture_class", "texture_opt", "texture_abs", 0.20),
                ("drainage", "drainage_opt", "drainage_abs", 0.15),
                ("depth", "depth_opt", "depth_abs", 0.08),
                ("fertility", "fertility_opt", "fertility_abs", 0.05),
                ("salinity", "salinity_opt", "salinity_abs", 0.07),
            ):
                optimum = split_values(row.get(cols[opt_key])) if cols.get(opt_key) else []
                accepted = split_values(row.get(cols[abs_key])) if cols.get(abs_key) else []
                if not optimum and not accepted:
                    continue
                conn.execute(
                    """INSERT OR REPLACE INTO soil_categorical_preference(
                    taxon_id,variable,optimum_values_json,accepted_values_json,weight,confidence,
                    source_ref,method,method_version) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (taxon_id, variable, json.dumps(optimum, ensure_ascii=False), json.dumps(accepted, ensure_ascii=False),
                     weight, "C", source_ref, METHOD, METHOD_VERSION),
                )
                stats["categorical_preferences"] += 1
                categorical_inserted += 1

            if not numeric_inserted and not categorical_inserted:
                stats["skipped_without_soil_data"] += 1
                continue

            claim = {
                "taxon_match": {"source_name": name, "matched_name": matched_name, "strategy": strategy},
                "ph": p,
                "texture": {"optimal": split_values(row.get(cols["texture_opt"])) if cols.get("texture_opt") else [],
                            "absolute": split_values(row.get(cols["texture_abs"])) if cols.get("texture_abs") else []},
                "drainage": {"optimal": split_values(row.get(cols["drainage_opt"])) if cols.get("drainage_opt") else [],
                             "absolute": split_values(row.get(cols["drainage_abs"])) if cols.get("drainage_abs") else []},
                "depth": {"optimal": split_values(row.get(cols["depth_opt"])) if cols.get("depth_opt") else [],
                          "absolute": split_values(row.get(cols["depth_abs"])) if cols.get("depth_abs") else []},
                "fertility": {"optimal": split_values(row.get(cols["fertility_opt"])) if cols.get("fertility_opt") else [],
                              "absolute": split_values(row.get(cols["fertility_abs"])) if cols.get("fertility_abs") else []},
                "salinity": {"optimal": split_values(row.get(cols["salinity_opt"])) if cols.get("salinity_opt") else [],
                             "absolute": split_values(row.get(cols["salinity_abs"])) if cols.get("salinity_abs") else []},
            }
            conn.execute(
                """INSERT INTO evidence(taxon_id,claim_type,claim_value,source_id,source_reference,
                source_version,extraction_method,confidence,notes) VALUES(?,?,?,?,?,?,?,?,?)""",
                (taxon_id, "soil_preference", json.dumps(claim, ensure_ascii=False, sort_keys=True), "FAO_ECOCROP",
                 source_ref, "FAO ECOCROP / GAEZ online service", "BULK_EXPORT_MATCHED_TO_WCVP", "C",
                 "Bulk ECOCROP import; source characteristics are broad agronomic requirements, not physiological absolutes."),
            )
            stats["evidence_rows"] += 1

        metadata = {
            "catalog_version": CATALOG_VERSION,
            "soil_preferences_source": "FAO ECOCROP",
            "soil_preferences_method": METHOD,
            "soil_preferences_method_version": METHOD_VERSION,
            "soil_preferences_source_rows": str(stats["source_rows"]),
            "soil_preferences_matched_taxa": str(len(matched_taxa)),
            "soil_preferences_unmatched_rows": str(stats["unmatched"]),
            "soil_preferences_normalized_matches": str(stats["normalized_matches"]),
            "soil_preferences_confidence_ceiling": "C",
            "soil_enriched_at": utcnow(),
            "scientific_ready": "true",
        }
        conn.executemany("INSERT OR REPLACE INTO climaflora_catalog_metadata(key,value) VALUES(?,?)", metadata.items())
        conn.commit()
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"integrity_check failed: {integrity}")

        soil_taxa = conn.execute("SELECT COUNT(DISTINCT taxon_id) FROM (SELECT taxon_id FROM soil_envelope UNION SELECT taxon_id FROM soil_categorical_preference)").fetchone()[0]
        soil_numeric = conn.execute("SELECT COUNT(*) FROM soil_envelope").fetchone()[0]
        soil_cat = conn.execute("SELECT COUNT(*) FROM soil_categorical_preference").fetchone()[0]
        total_plants = conn.execute("SELECT COUNT(*) FROM plant_index").fetchone()[0]

    os.chmod(tmp, 0o444)
    os.replace(tmp, output)

    report = {
        "catalog_version": CATALOG_VERSION,
        "built_at": utcnow(),
        "source": {
            "scientific_reference": "FAO ECOCROP",
            "official_portal": "https://www.fao.org/geospatial/data-and-tools/data-portals/ecocrop/en",
            "official_app": "https://ecocrop.apps.fao.org/",
            "bulk_transport": "OpenCLIM/ecocrop EcoCrop_DB.csv",
            "source_encoding": source_encoding,
        },
        "stats": stats,
        "matched_unique_taxa": len(matched_taxa),
        "soil_taxa_total": soil_taxa,
        "soil_taxa_coverage": soil_taxa / total_plants if total_plants else 0,
        "soil_envelope_rows": soil_numeric,
        "soil_categorical_rows": soil_cat,
        "unmatched_sample": unmatched_names,
        "sqlite_bytes": output.stat().st_size,
        "sqlite_sha256": sha256_file(output),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
