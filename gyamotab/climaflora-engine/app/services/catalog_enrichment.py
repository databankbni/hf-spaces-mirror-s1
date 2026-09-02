from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CATALOG_VERSION = "1.2.0"
SOIL_METHOD = "FAO_ECOCROP_DOCUMENTED"
SOIL_METHOD_VERSION = "1.0"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _lookup_taxon(conn: sqlite3.Connection, scientific_name: str) -> str | None:
    row = conn.execute(
        "SELECT taxon_id FROM plant_index WHERE scientific_name=? COLLATE NOCASE LIMIT 1",
        (scientific_name,),
    ).fetchone()
    if row:
        return str(row[0])
    # Conservative synonym fallback through WCVP; only activate the accepted name if it is in plant_index.
    row = conn.execute(
        """
        SELECT CAST(COALESCE(n.accepted_name_usage_id,n.taxon_id) AS TEXT)
        FROM wcvp_names n
        JOIN plant_index p ON p.taxon_id=CAST(COALESCE(n.accepted_name_usage_id,n.taxon_id) AS TEXT)
        WHERE n.scientific_name=? COLLATE NOCASE
        ORDER BY CASE WHEN lower(COALESCE(n.taxonomic_status,''))='accepted' THEN 0 ELSE 1 END
        LIMIT 1
        """,
        (scientific_name,),
    ).fetchone()
    return str(row[0]) if row else None


def _ensure_schema(conn: sqlite3.Connection) -> None:
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
        """
    )


def _insert_source(conn: sqlite3.Connection, dataset: dict[str, Any]) -> None:
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "sources" not in tables:
        return
    columns = {r[1] for r in conn.execute("PRAGMA table_info(sources)")}
    values = {
        "source_id": dataset.get("id", "FAO_ECOCROP"),
        "title": dataset.get("title"),
        "organization": dataset.get("organization"),
        "year": 1999,
        "url": dataset.get("source"),
        "doi": None,
        "license": None,
        "reliability_level": "C",
        "notes": dataset.get("notes"),
    }
    use = [name for name in values if name in columns]
    if not use:
        return
    marks = ",".join("?" for _ in use)
    cols = ",".join(f'"{name}"' for name in use)
    conn.execute(
        f"INSERT OR REPLACE INTO sources({cols}) VALUES({marks})",
        tuple(values[name] for name in use),
    )


def enrich_catalog(base_path: Path, output_path: Path, seed_path: Path) -> dict[str, Any]:
    if not base_path.exists():
        raise FileNotFoundError(base_path)
    if not seed_path.exists():
        raise FileNotFoundError(seed_path)
    seed = _read_json(seed_path)
    dataset = seed.get("dataset", {})
    plants = seed.get("plants", [])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(output_path.suffix + ".building")
    if tmp.exists():
        tmp.unlink()
    shutil.copyfile(base_path, tmp)

    matched = 0
    unmatched: list[str] = []
    numeric_rows = 0
    categorical_rows = 0
    evidence_rows = 0
    with sqlite3.connect(tmp) as conn:
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA synchronous=NORMAL")
        _ensure_schema(conn)
        _insert_source(conn, dataset)

        for item in plants:
            name = str(item.get("scientific_name") or "").strip()
            taxon_id = _lookup_taxon(conn, name)
            if not taxon_id:
                unmatched.append(name)
                continue
            matched += 1
            source_url = f"https://ecocrop.apps.fao.org/ecocrop/srv/en/dataSheet?id={int(item['ecocrop_id'])}"
            confidence = str(dataset.get("confidence") or "C").upper()

            ph = item.get("ph") or {}
            absolute = ph.get("absolute") or []
            optimal = ph.get("optimal") or []
            if len(absolute) == 2 and len(optimal) == 2:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO soil_envelope(
                      taxon_id,variable,hard_low,optimum_low,optimum_high,hard_high,
                      weight,group_code,fatal,confidence,source_ref,method,method_version
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        taxon_id, "ph", float(absolute[0]), float(optimal[0]), float(optimal[1]), float(absolute[1]),
                        0.60, "E", 0, confidence, source_url, SOIL_METHOD, SOIL_METHOD_VERSION,
                    ),
                )
                numeric_rows += 1

            for variable, weight in (("texture_class", 0.30), ("drainage", 0.10)):
                pref = item.get("texture" if variable == "texture_class" else "drainage") or {}
                optimum = [str(v) for v in pref.get("optimal") or []]
                accepted = [str(v) for v in pref.get("absolute") or []]
                if not optimum and not accepted:
                    continue
                conn.execute(
                    """
                    INSERT OR REPLACE INTO soil_categorical_preference(
                      taxon_id,variable,optimum_values_json,accepted_values_json,weight,confidence,
                      source_ref,method,method_version
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        taxon_id, variable, json.dumps(optimum, ensure_ascii=False), json.dumps(accepted, ensure_ascii=False),
                        weight, confidence, source_url, SOIL_METHOD, SOIL_METHOD_VERSION,
                    ),
                )
                categorical_rows += 1

            claim_value = json.dumps(
                {"ph": item.get("ph"), "texture": item.get("texture"), "drainage": item.get("drainage")},
                ensure_ascii=False,
                sort_keys=True,
            )
            conn.execute(
                """
                INSERT INTO evidence(
                  taxon_id,claim_type,claim_value,source_id,source_reference,source_version,
                  extraction_method,confidence,notes
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    taxon_id, "soil_preference", claim_value, dataset.get("id", "FAO_ECOCROP"), source_url,
                    "FAO ECOCROP current online mirror", "CURATED_STRUCTURED_IMPORT", confidence,
                    "Initial ClimaFlora soil-preference batch; broad ECOCROP texture/drainage classes are preserved explicitly.",
                ),
            )
            evidence_rows += 1

        # Catalog provenance is versioned in the master itself.
        conn.execute(
            "CREATE TABLE IF NOT EXISTS climaflora_catalog_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        metadata = {
            "catalog_version": CATALOG_VERSION,
            "soil_preferences_source": "FAO ECOCROP",
            "soil_preferences_method": SOIL_METHOD,
            "soil_preferences_method_version": SOIL_METHOD_VERSION,
            "soil_preferences_seed_count": str(len(plants)),
            "soil_preferences_matched_taxa": str(matched),
            "soil_preferences_confidence_ceiling": str(dataset.get("confidence") or "C"),
            "soil_texture_crosswalk": "ClimaFlora broad EcoCrop class proxy: heavy if clay>=35%; light if sand>=65%; otherwise medium",
            "soil_enriched_at": utcnow(),
        }
        conn.executemany(
            "INSERT OR REPLACE INTO climaflora_catalog_metadata(key,value) VALUES(?,?)",
            metadata.items(),
        )
        conn.commit()
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"v1.2 integrity_check failed: {integrity}")

    os.chmod(tmp, 0o444)
    os.replace(tmp, output_path)
    return {
        "catalog_version": CATALOG_VERSION,
        "seed_taxa": len(plants),
        "matched_taxa": matched,
        "unmatched_taxa": unmatched,
        "numeric_preferences": numeric_rows,
        "categorical_preferences": categorical_rows,
        "evidence_rows": evidence_rows,
        "sqlite_bytes": output_path.stat().st_size,
        "sqlite_sha256": sha256_file(output_path),
    }


@dataclass
class CatalogEnrichmentService:
    base_db: str
    output_db: str
    output_zst: str
    seed_path: str
    status_path: str
    bootstrap_status_path: str
    zstd_level: int = 10

    _thread: threading.Thread | None = None
    _lock = threading.Lock()

    def _write_status(self, **updates: Any) -> None:
        path = Path(self.status_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        current: dict[str, Any] = {}
        if path.exists():
            try:
                current = _read_json(path)
            except Exception:
                current = {}
        current.update(updates)
        current["updated_at"] = utcnow()
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def status(self) -> dict[str, Any]:
        path = Path(self.status_path)
        if path.exists():
            try:
                data = _read_json(path)
            except Exception as exc:  # noqa: BLE001
                data = {"phase": "error", "ready": False, "error": f"status read failed: {exc}"}
        else:
            data = {"phase": "not_started", "ready": False, "error": None}
        out = Path(self.output_db)
        zst = Path(self.output_zst)
        data.update({
            "catalog_version": CATALOG_VERSION,
            "catalog_db": str(out),
            "catalog_present": out.exists(),
            "snapshot_present": zst.exists(),
            "snapshot_bytes": zst.stat().st_size if zst.exists() else 0,
        })
        return data

    def _bootstrap_status(self) -> dict[str, Any]:
        path = Path(self.bootstrap_status_path)
        if not path.exists():
            return {}
        try:
            return _read_json(path)
        except Exception:
            return {}

    def _base_usable(self) -> tuple[bool, str]:
        """Return whether the atomically-decompressed v1.1 catalog is safe to enrich.

        The master bootstrap performs an exhaustive audit that can legitimately take
        much longer than catalog enrichment needs. The enriched catalog only requires
        a complete SQLite file with the expected schema and lineage metadata. The
        compressed SHA-256 is still verified by the bootstrap before the SQLite file is
        atomically promoted into place.
        """
        base = Path(self.base_db)
        if not base.exists():
            return False, "master sqlite not present yet"
        try:
            uri = f"file:{base.resolve()}?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=5) as conn:
                tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                required = {
                    "plant_taxa", "wcvp_distribution", "wcvp_names",
                    "plant_index", "climate_envelope", "soil_envelope",
                    "evidence", "build_metadata",
                }
                missing = sorted(required - tables)
                if missing:
                    return False, "missing required tables: " + ", ".join(missing)
                # v1.1 is pinned by its compressed SHA-256 in the master bootstrap.
                # Some early v1.1 snapshots do not contain climaflora_catalog_metadata;
                # the embedded scientific build_metadata is the authoritative readiness
                # marker for those snapshots. v1.2 will create catalog metadata itself.
                metadata = {str(k): str(v) for k, v in conn.execute("SELECT key,value FROM build_metadata")}
                if metadata.get("scientific_ready", "").lower() != "true":
                    return False, "build_metadata scientific_ready is not true"
                mode = metadata.get("mode", "")
                if not (mode == "SCIENTIFIC" or mode.startswith("SCIENTIFIC_PROXY_")):
                    return False, f"unexpected scientific mode={mode!r}"
                if conn.execute("SELECT 1 FROM plant_index LIMIT 1").fetchone() is None:
                    return False, "plant_index is empty"
                if conn.execute("SELECT 1 FROM climate_envelope LIMIT 1").fetchone() is None:
                    return False, "climate_envelope is empty"
            return True, "schema and embedded scientific build_metadata validated"
        except sqlite3.Error as exc:
            return False, f"sqlite not readable yet: {exc}"

    def _validate_existing(self) -> bool:
        out = Path(self.output_db)
        if not out.exists():
            return False
        try:
            with sqlite3.connect(f"file:{out.resolve()}?mode=ro", uri=True) as conn:
                meta = dict(conn.execute("SELECT key,value FROM climaflora_catalog_metadata"))
                soil_count = int(conn.execute("SELECT COUNT(*) FROM soil_envelope WHERE method=?", (SOIL_METHOD,)).fetchone()[0])
                cat_count = int(conn.execute("SELECT COUNT(*) FROM soil_categorical_preference WHERE method=?", (SOIL_METHOD,)).fetchone()[0])
            return meta.get("catalog_version") == CATALOG_VERSION and soil_count > 0 and cat_count > 0
        except sqlite3.Error:
            return False

    def _run(self) -> None:
        try:
            self._write_status(phase="waiting_master", ready=False, error=None, started_at=utcnow())
            while True:
                usable, reason = self._base_usable()
                master_status = self._bootstrap_status()
                master_phase = str(master_status.get("phase") or "unknown")
                if usable:
                    self._write_status(
                        phase="master_usable", ready=False, master_phase=master_phase,
                        master_gate=reason, master_audit_ready=bool(master_status.get("ready")),
                    )
                    break
                if master_phase == "error":
                    raise RuntimeError(
                        "base v1.1 bootstrap failed: " + str(master_status.get("error") or reason)
                    )
                self._write_status(
                    phase="waiting_master", ready=False, master_phase=master_phase,
                    master_gate=reason, master_audit_ready=bool(master_status.get("ready")),
                )
                time.sleep(2)

            if self._validate_existing():
                result = {"sqlite_sha256": sha256_file(Path(self.output_db)), "reused": True}
            else:
                self._write_status(phase="enriching", ready=False)
                result = enrich_catalog(Path(self.base_db), Path(self.output_db), Path(self.seed_path))

            # The API can already use the validated SQLite while the portable snapshot is compressed.
            self._write_status(phase="compressing", ready=True, catalog_ready=True, result=result)
            zst = Path(self.output_zst)
            tmp_zst = zst.with_suffix(zst.suffix + ".tmp")
            if tmp_zst.exists():
                tmp_zst.unlink()
            subprocess.run(
                ["zstd", "-q", "-f", f"-{int(self.zstd_level)}", str(self.output_db), "-o", str(tmp_zst)],
                check=True,
            )
            os.replace(tmp_zst, zst)
            result.update({
                "compressed_sha256": sha256_file(zst),
                "compressed_bytes": zst.stat().st_size,
            })
            self._write_status(phase="ready", ready=True, catalog_ready=True, error=None, result=result, completed_at=utcnow())
        except Exception as exc:  # noqa: BLE001
            self._write_status(phase="error", ready=False, catalog_ready=False, error=f"{type(exc).__name__}: {exc}")

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name="climaflora-catalog-enrichment", daemon=True)
            self._thread.start()


_services: dict[tuple, CatalogEnrichmentService] = {}
_services_lock = threading.Lock()


def get_catalog_enrichment(
    base_db: str,
    output_db: str,
    output_zst: str,
    seed_path: str,
    status_path: str,
    bootstrap_status_path: str,
    zstd_level: int = 10,
) -> CatalogEnrichmentService:
    key = (base_db, output_db, output_zst, seed_path, status_path, bootstrap_status_path, int(zstd_level))
    with _services_lock:
        service = _services.get(key)
        if service is None:
            service = CatalogEnrichmentService(*key)
            _services[key] = service
        return service
