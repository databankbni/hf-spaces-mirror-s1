from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

BASEFLOR_SOURCE_ID = "BASEFLOR_2023_10"
BASEFLOR_METHOD = "BASEFLOR_JULVE_INDICATORS"


def table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def table_columns(con: sqlite3.Connection, name: str) -> set[str]:
    return {str(r[1]) for r in con.execute(f"PRAGMA table_info({name})")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--build-db", required=True)
    ap.add_argument("--audit", required=True)
    ap.add_argument("--report", required=True)
    args = ap.parse_args()

    audit = json.loads(Path(args.audit).read_text(encoding="utf-8"))
    conflicts = audit.get("conflicts") or []
    if audit.get("status") != "ready":
        raise SystemExit("Baseflor collision audit is not ready")

    pairs = {(str(x["taxon_id"]), str(x["indicator"])) for x in conflicts}
    cat = sqlite3.connect(args.catalog)
    build = sqlite3.connect(args.build_db)
    cat.row_factory = sqlite3.Row
    build.row_factory = sqlite3.Row

    build.execute(
        """
        CREATE TABLE IF NOT EXISTS v2_baseflor_conflicting_indicator(
          taxon_id TEXT NOT NULL,
          indicator TEXT NOT NULL,
          value REAL NOT NULL,
          accepted_name TEXT,
          source_name TEXT,
          PRIMARY KEY(taxon_id,indicator,value,source_name)
        ) WITHOUT ROWID
        """
    )

    deleted_preferences = deleted_generic_evidence = deleted_soil_evidence = deleted_build_rows = 0
    raw_conflict_rows = 0

    for item in conflicts:
        tid = str(item["taxon_id"])
        indicator = str(item["indicator"])
        details = json.dumps(
            {"values": item.get("values") or [], "names": item.get("names") or []},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        if table_exists(cat, "soil_indicator_preference"):
            cur = cat.execute(
                "DELETE FROM soil_indicator_preference WHERE taxon_id=? AND indicator=? AND method=?",
                (tid, indicator, BASEFLOR_METHOD),
            )
            deleted_preferences += max(0, cur.rowcount)

        if table_exists(cat, "evidence"):
            cols = table_columns(cat, "evidence")
            if {"taxon_id", "claim_type", "source_id"} <= cols:
                cur = cat.execute(
                    "DELETE FROM evidence WHERE taxon_id=? AND claim_type=? AND source_id=?",
                    (tid, f"soil_baseflor_indicator:{indicator}", BASEFLOR_SOURCE_ID),
                )
                deleted_generic_evidence += max(0, cur.rowcount)

        if table_exists(cat, "soil_evidence"):
            cols = table_columns(cat, "soil_evidence")
            if {"taxon_id", "variable", "source_id"} <= cols:
                cur = cat.execute(
                    "DELETE FROM soil_evidence WHERE taxon_id=? AND variable=? AND source_id=?",
                    (tid, indicator, BASEFLOR_SOURCE_ID),
                )
                deleted_soil_evidence += max(0, cur.rowcount)

        if table_exists(build, "v2_baseflor_indicator"):
            cur = build.execute(
                "DELETE FROM v2_baseflor_indicator WHERE taxon_id=? AND indicator=?",
                (tid, indicator),
            )
            deleted_build_rows += max(0, cur.rowcount)

        if table_exists(build, "v2_conflict"):
            build.execute(
                "INSERT INTO v2_conflict(taxon_id,variable,source_a,source_b,details) VALUES(?,?,?,?,?)",
                (tid, indicator, "BASEFLOR_2023_10", "BASEFLOR_2023_10", details),
            )

        names = item.get("names") or []
        values = item.get("values") or []
        # The audit has unique conflicting values and the source names that collapsed to
        # the accepted taxon. Preserve the cross-product explicitly as provenance rather
        # than inventing which original row supplied which value after normalization.
        for value in values:
            for name in names or [{}]:
                source_name = str(name.get("source") or "")
                accepted_name = str(name.get("accepted") or "")
                build.execute(
                    "INSERT OR IGNORE INTO v2_baseflor_conflicting_indicator VALUES(?,?,?,?,?)",
                    (tid, indicator, float(value), accepted_name, source_name),
                )
                raw_conflict_rows += 1

    cat.commit()
    build.commit()

    unresolved = 0
    if table_exists(cat, "soil_indicator_preference"):
        for tid, indicator in pairs:
            unresolved += int(
                cat.execute(
                    "SELECT COUNT(*) FROM soil_indicator_preference WHERE taxon_id=? AND indicator=? AND method=?",
                    (tid, indicator, BASEFLOR_METHOD),
                ).fetchone()[0]
            )

    report_path = Path(args.report)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    stats = report.setdefault("stats", {})
    validation = report.setdefault("validation", {})
    stats.update(
        {
            "baseflor_duplicate_taxa_after_wcvp": int(audit.get("taxa_with_multiple_source_rows", 0)),
            "baseflor_indicator_conflict_groups": len(conflicts),
            "baseflor_conflicting_taxa": int(audit.get("conflicting_taxa", 0)),
            "baseflor_conflict_preferences_removed": deleted_preferences,
            "baseflor_conflict_generic_evidence_removed": deleted_generic_evidence,
            "baseflor_conflict_soil_evidence_removed": deleted_soil_evidence,
            "baseflor_conflict_build_rows_removed": deleted_build_rows,
            "baseflor_conflict_provenance_rows": int(
                build.execute("SELECT COUNT(*) FROM v2_baseflor_conflicting_indicator").fetchone()[0]
            ),
            "baseflor_indicator_rows_final": int(
                cat.execute(
                    "SELECT COUNT(*) FROM soil_indicator_preference WHERE method=?", (BASEFLOR_METHOD,)
                ).fetchone()[0]
            ) if table_exists(cat, "soil_indicator_preference") else 0,
        }
    )
    validation["baseflor_unresolved_conflict_rows"] = unresolved
    validation["blocking_failures"] = int(validation.get("blocking_failures", 0)) + unresolved
    limitations = report.setdefault("limitations", [])
    limitations.append(
        "Baseflor values that conflict after exact WCVP synonym collapse are preserved in the separate provenance database and omitted from the canonical indicator table; no value is arbitrarily selected."
    )
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "conflict_groups": len(conflicts),
                "conflicting_taxa": audit.get("conflicting_taxa", 0),
                "deleted_preferences": deleted_preferences,
                "unresolved": unresolved,
                "provenance_rows": stats["baseflor_conflict_provenance_rows"],
            },
            indent=2,
        )
    )
    cat.close()
    build.close()
    if unresolved:
        raise SystemExit(f"{unresolved} conflicting Baseflor canonical rows remain")


if __name__ == "__main__":
    main()
