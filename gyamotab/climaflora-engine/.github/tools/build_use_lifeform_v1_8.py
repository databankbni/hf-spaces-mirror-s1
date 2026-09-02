from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

CATALOG_VERSION = "1.8.0"
BASE_VERSION = "1.7.0"
WCUPS_SOURCE = "WCUPS2020"
GROWTHFORM_SOURCE = "GROWTHFORM_GLOBAL"
EXACT_MATCH_METHODS = ("IPNI_LSID_EXACT", "SCIENTIFIC_NAME_EXACT")
MIN_USE_TAXA = 39000
MIN_LIFE_FORM_ADDED = 1000


def _meta(conn: sqlite3.Connection) -> dict[str, str]:
    return dict(conn.execute("SELECT key,value FROM climaflora_catalog_metadata"))


def _require_tables(conn: sqlite3.Connection, names: set[str]) -> None:
    present = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    missing = names - present
    if missing:
        raise RuntimeError(f"missing required base tables: {sorted(missing)}")


def build(base: Path, output: Path, report_path: Path) -> dict[str, Any]:
    if output.exists():
        output.unlink()
    shutil.copy2(base, output)
    with sqlite3.connect(output) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        meta = _meta(conn)
        if meta.get("catalog_version") != BASE_VERSION:
            raise RuntimeError(f"expected base catalog {BASE_VERSION}, got {meta.get('catalog_version')}")
        if meta.get("scientific_ready") != "true":
            raise RuntimeError("base catalog is not scientific_ready")
        _require_tables(
            conn,
            {
                "plant_index",
                "plant_profile",
                "legacy_sources",
                "legacy_use_types",
                "legacy_species_uses",
                "legacy_species_evidence",
                "legacy_species_wcvp_map",
                "climat_enrichment_preferred",
                "soil_geographic_prior",
            },
        )

        wcups = conn.execute(
            "SELECT title,organization,year,url,doi,license,reliability_level FROM legacy_sources WHERE source_id=?",
            (WCUPS_SOURCE,),
        ).fetchone()
        if not wcups:
            raise RuntimeError("WCUPS source provenance missing")
        if str(wcups[5] or "").strip().upper() != "CC BY 4.0":
            raise RuntimeError(f"unexpected WCUPS license: {wcups[5]!r}")
        growth = conn.execute(
            "SELECT title,organization,year,url,doi,license,reliability_level FROM legacy_sources WHERE source_id=?",
            (GROWTHFORM_SOURCE,),
        ).fetchone()
        if not growth:
            raise RuntimeError("growth-form source provenance missing")

        conn.executescript(
            """
            DROP TABLE IF EXISTS plant_use_reference;
            DROP TABLE IF EXISTS plant_use;
            DROP TABLE IF EXISTS plant_trait_evidence;
            CREATE TABLE plant_use (
              taxon_id TEXT NOT NULL,
              use_code TEXT NOT NULL,
              use_category_en TEXT NOT NULL,
              use_category_fr TEXT,
              source_id TEXT NOT NULL,
              source_reference TEXT NOT NULL,
              source_license TEXT,
              taxonomy_match_method TEXT NOT NULL,
              taxonomy_match_confidence TEXT NOT NULL,
              evidence_level TEXT,
              refinement_status TEXT,
              PRIMARY KEY (taxon_id,use_code,source_id)
            ) WITHOUT ROWID;
            CREATE INDEX idx_plant_use_taxon ON plant_use(taxon_id);
            CREATE INDEX idx_plant_use_code ON plant_use(use_code,taxon_id);

            CREATE TABLE plant_use_reference (
              taxon_id TEXT NOT NULL,
              use_code TEXT NOT NULL,
              source_id TEXT NOT NULL,
              source_subref TEXT NOT NULL,
              source_page INTEGER,
              confidence TEXT,
              PRIMARY KEY (taxon_id,use_code,source_id,source_subref)
            ) WITHOUT ROWID;
            CREATE INDEX idx_plant_use_reference_taxon ON plant_use_reference(taxon_id);

            CREATE TABLE plant_trait_evidence (
              taxon_id TEXT NOT NULL,
              trait_name TEXT NOT NULL,
              trait_value TEXT NOT NULL,
              source_id TEXT NOT NULL,
              source_reference TEXT NOT NULL,
              source_license TEXT,
              taxonomy_match_method TEXT NOT NULL,
              taxonomy_match_confidence TEXT NOT NULL,
              extraction_method TEXT NOT NULL,
              confidence TEXT,
              notes TEXT,
              PRIMARY KEY (taxon_id,trait_name,source_id)
            ) WITHOUT ROWID;
            CREATE INDEX idx_plant_trait_evidence_taxon ON plant_trait_evidence(taxon_id);
            """
        )

        # Project WCUPS categories only through deterministic exact WCVP mappings.
        conn.execute(
            """
            INSERT OR IGNORE INTO plant_use(
              taxon_id,use_code,use_category_en,use_category_fr,source_id,source_reference,
              source_license,taxonomy_match_method,taxonomy_match_confidence,evidence_level,refinement_status
            )
            SELECT CAST(m.accepted_taxon_id AS TEXT), u.use_code, t.label_en, t.label_fr,
                   ?, 'doi:10.5063/F1CV4G34', 'CC BY 4.0',
                   m.match_method, m.match_confidence, u.evidence_level, u.refinement_status
            FROM legacy_species_uses u
            JOIN legacy_use_types t ON t.use_code=u.use_code
            JOIN legacy_species_wcvp_map m ON m.old_species_id=u.species_id
            JOIN plant_index p ON p.taxon_id=CAST(m.accepted_taxon_id AS TEXT)
            WHERE m.match_method IN ('IPNI_LSID_EXACT','SCIENTIFIC_NAME_EXACT')
              AND m.match_confidence IN ('A','B')
              AND u.use_code IN ('AF','EU','FU','GS','HF','IF','MA','ME','PO','SU')
            """,
            (WCUPS_SOURCE,),
        )

        # Preserve the underlying WCUPS reference identifiers where present. These
        # references document reported use, not safety, efficacy or preparation.
        conn.execute(
            """
            INSERT OR IGNORE INTO plant_use_reference(taxon_id,use_code,source_id,source_subref,source_page,confidence)
            SELECT CAST(m.accepted_taxon_id AS TEXT), u.use_code, ?, ev.source_subref, ev.source_page, ev.confidence
            FROM legacy_species_uses u
            JOIN legacy_species_wcvp_map m ON m.old_species_id=u.species_id
            JOIN legacy_species_evidence ev ON ev.species_id=u.species_id
            JOIN plant_index p ON p.taxon_id=CAST(m.accepted_taxon_id AS TEXT)
            WHERE m.match_method IN ('IPNI_LSID_EXACT','SCIENTIFIC_NAME_EXACT')
              AND m.match_confidence IN ('A','B')
              AND ev.source_id=?
              AND ev.evidence_type='underlying_source_reference'
              AND ev.source_subref IS NOT NULL AND trim(ev.source_subref)<>''
              AND (' ' || trim(coalesce(ev.asserted_value,'')) || ' ') LIKE '% ' || u.use_code || ' %'
            """,
            (WCUPS_SOURCE, WCUPS_SOURCE),
        )

        before_life = conn.execute(
            "SELECT COUNT(*) FROM plant_profile WHERE life_form IS NOT NULL AND trim(life_form)<>''"
        ).fetchone()[0]

        # Fill only missing WCVP life forms from preexisting exact-linked global
        # growth-form evidence. No free-text parsing and no fuzzy taxonomy are used.
        conn.execute(
            """
            INSERT OR IGNORE INTO plant_trait_evidence(
              taxon_id,trait_name,trait_value,source_id,source_reference,source_license,
              taxonomy_match_method,taxonomy_match_confidence,extraction_method,confidence,notes
            )
            SELECT CAST(e.taxon_id AS TEXT), 'life_form', trim(e.life_form), ?,
                   'doi:10.1002/ecy.2614', NULL, e.match_method, e.match_confidence,
                   'preexisting deterministic support/woodiness derivation', ev.confidence, ev.notes
            FROM climat_enrichment_preferred e
            JOIN plant_profile pp ON pp.taxon_id=CAST(e.taxon_id AS TEXT)
            JOIN legacy_species_evidence ev ON ev.species_id=e.species_id
            WHERE (pp.life_form IS NULL OR trim(pp.life_form)='')
              AND e.life_form IS NOT NULL AND trim(e.life_form)<>''
              AND e.match_method IN ('IPNI_LSID_EXACT','SCIENTIFIC_NAME_EXACT')
              AND e.match_confidence IN ('A','B')
              AND ev.source_id=? AND ev.evidence_type='growth_form_traits'
              AND ev.confidence='A'
            """,
            (GROWTHFORM_SOURCE, GROWTHFORM_SOURCE),
        )
        conn.execute(
            """
            UPDATE plant_profile
               SET life_form=(
                 SELECT trait_value FROM plant_trait_evidence e
                 WHERE e.taxon_id=plant_profile.taxon_id AND e.trait_name='life_form' AND e.source_id=?
               )
             WHERE (life_form IS NULL OR trim(life_form)='')
               AND EXISTS (
                 SELECT 1 FROM plant_trait_evidence e
                 WHERE e.taxon_id=plant_profile.taxon_id AND e.trait_name='life_form' AND e.source_id=?
               )
            """,
            (GROWTHFORM_SOURCE, GROWTHFORM_SOURCE),
        )
        after_life = conn.execute(
            "SELECT COUNT(*) FROM plant_profile WHERE life_form IS NOT NULL AND trim(life_form)<>''"
        ).fetchone()[0]

        # Keep the coarse navigation filters synchronized with directly corresponding
        # WCUPS categories while retaining any existing independently sourced flags.
        code_to_function = {
            "HF": "FOOD_HUMAN",
            "AF": "FOOD_ANIMAL",
            "ME": "MEDICINAL",
            "MA": "MATERIALS",
            "FU": "FUEL",
        }
        use_codes_by_taxon: dict[str, list[str]] = {}
        for taxon_id, code in conn.execute("SELECT taxon_id,use_code FROM plant_use ORDER BY taxon_id,use_code"):
            use_codes_by_taxon.setdefault(str(taxon_id), []).append(str(code))
        additions = 0
        updates: list[tuple[str, str]] = []
        for taxon_id, current in conn.execute("SELECT taxon_id,functions_json FROM plant_index"):
            codes = use_codes_by_taxon.get(str(taxon_id))
            if not codes:
                continue
            try:
                functions = list(json.loads(current or "[]"))
            except Exception:
                functions = []
            present = set(functions)
            changed = False
            for code in codes:
                label = code_to_function.get(code)
                if label and label not in present:
                    functions.append(label)
                    present.add(label)
                    additions += 1
                    changed = True
            if changed:
                updates.append((json.dumps(functions,separators=(",", ":")), str(taxon_id)))
        conn.executemany("UPDATE plant_index SET functions_json=? WHERE taxon_id=?", updates)

        stats = {
            "plant_count": conn.execute("SELECT COUNT(*) FROM plant_index").fetchone()[0],
            "wcups_use_rows": conn.execute("SELECT COUNT(*) FROM plant_use").fetchone()[0],
            "wcups_use_taxa": conn.execute("SELECT COUNT(DISTINCT taxon_id) FROM plant_use").fetchone()[0],
            "wcups_reference_rows": conn.execute("SELECT COUNT(*) FROM plant_use_reference").fetchone()[0],
            "wcups_ipni_exact_taxa": conn.execute("SELECT COUNT(DISTINCT taxon_id) FROM plant_use WHERE taxonomy_match_method='IPNI_LSID_EXACT'").fetchone()[0],
            "wcups_name_exact_taxa": conn.execute("SELECT COUNT(DISTINCT taxon_id) FROM plant_use WHERE taxonomy_match_method='SCIENTIFIC_NAME_EXACT'").fetchone()[0],
            "life_form_taxa_before": int(before_life),
            "life_form_taxa_after": int(after_life),
            "life_form_taxa_added": int(after_life-before_life),
            "life_form_evidence_rows": conn.execute("SELECT COUNT(*) FROM plant_trait_evidence WHERE trait_name='life_form'").fetchone()[0],
            "coarse_function_labels_added": additions,
            "function_taxa_after": conn.execute("SELECT COUNT(*) FROM plant_index WHERE functions_json<>'[]'").fetchone()[0],
            "scoring_enabled_geographic_priors": conn.execute("SELECT COUNT(*) FROM soil_geographic_prior WHERE scoring_enabled<>0").fetchone()[0],
        }
        if stats["scoring_enabled_geographic_priors"] != 0:
            raise RuntimeError("geographic priors unexpectedly scoring-enabled")
        if stats["wcups_use_taxa"] < MIN_USE_TAXA:
            raise RuntimeError(f"unexpectedly low WCUPS exact-linked coverage: {stats['wcups_use_taxa']}")
        if stats["life_form_taxa_added"] < MIN_LIFE_FORM_ADDED:
            raise RuntimeError(f"unexpectedly low life-form supplementation: {stats['life_form_taxa_added']}")

        metadata = {
            "catalog_version": CATALOG_VERSION,
            "catalog_schema_version": CATALOG_VERSION,
            "scientific_ready": "true",
            "use_evidence_source": "WCUPS2020 doi:10.5063/F1CV4G34",
            "use_evidence_taxonomy_policy": "IPNI_LSID_EXACT_A + SCIENTIFIC_NAME_EXACT_B only; no fuzzy matching",
            "use_evidence_interpretation": "reported use category only; not safety, efficacy, edibility preparation, or recommendation evidence",
            "life_form_supplement_source": "GROWTHFORM_GLOBAL doi:10.1002/ecy.2614",
            "life_form_supplement_policy": "fill missing values only from preexisting exact-linked growth-form evidence",
            "image_identification_evidence": "false",
            "geographic_priors_scoring_enabled": "false",
        }
        for key, value in metadata.items():
            conn.execute("INSERT OR REPLACE INTO climaflora_catalog_metadata(key,value) VALUES(?,?)", (key, value))
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='build_metadata'").fetchone():
                conn.execute("INSERT OR REPLACE INTO build_metadata(key,value) VALUES(?,?)", (key, value))
        conn.commit()
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    report = {
        "catalog_version": CATALOG_VERSION,
        "base_catalog_version": BASE_VERSION,
        "stats": stats,
        "sources": {
            WCUPS_SOURCE: {
                "title": wcups[0], "organization": wcups[1], "year": wcups[2], "url": wcups[3],
                "doi": wcups[4], "license": wcups[5], "reliability_level": wcups[6],
            },
            GROWTHFORM_SOURCE: {
                "title": growth[0], "organization": growth[1], "year": growth[2], "url": growth[3],
                "doi": growth[4], "license": growth[5], "reliability_level": growth[6],
            },
        },
    }
    report_path.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return report


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--base",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--report",type=Path,required=True)
    args=ap.parse_args()
    print(json.dumps(build(args.base,args.output,args.report),indent=2,ensure_ascii=False))


if __name__ == "__main__":
    main()
