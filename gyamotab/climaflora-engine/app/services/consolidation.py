from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.scientific_build import CORE_VARIABLES

CATALOG_VERSION = "1.1.0"
CATALOG_FILENAME = "climaflora_global_plants_v1_1.sqlite"
DERIVED_TABLES = (
    "build_metadata",
    "plant_index",
    "plant_profile",
    "taxon_native_region",
    "region_climate_summary",
    "climate_envelope",
    "soil_envelope",
    "evidence",
)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def qident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _clone_table_schema(dst: sqlite3.Connection, source_schema: str, table: str) -> None:
    cols = dst.execute(f"PRAGMA {qident(source_schema)}.table_info({qident(table)})").fetchall()
    if not cols:
        raise RuntimeError(f"missing derived table schema: {table}")

    column_defs: list[str] = []
    pk_cols: list[tuple[int, str]] = []
    for _, name, col_type, notnull, default_value, pk_pos in cols:
        parts = [qident(name)]
        if col_type:
            parts.append(str(col_type))
        if notnull:
            parts.append("NOT NULL")
        if default_value is not None:
            parts.extend(["DEFAULT", str(default_value)])
        if pk_pos:
            pk_cols.append((int(pk_pos), str(name)))
        column_defs.append(" ".join(parts))

    if pk_cols:
        ordered = [qident(name) for _, name in sorted(pk_cols)]
        column_defs.append("PRIMARY KEY (" + ", ".join(ordered) + ")")

    dst.execute(f"CREATE TABLE {qident(table)} (" + ", ".join(column_defs) + ")")


def _copy_derived_tables(dst: sqlite3.Connection, derived_path: Path) -> dict[str, int]:
    dst.execute("ATTACH DATABASE ? AS derived", (f"file:{derived_path.resolve()}?mode=ro",))
    try:
        source_tables = {
            row[0]
            for row in dst.execute("SELECT name FROM derived.sqlite_master WHERE type='table'")
        }
        missing = [name for name in DERIVED_TABLES if name not in source_tables]
        if missing:
            raise RuntimeError("derived database missing required tables: " + ", ".join(missing))

        master_tables = {
            row[0]
            for row in dst.execute("SELECT name FROM main.sqlite_master WHERE type='table'")
        }
        collisions = [name for name in DERIVED_TABLES if name in master_tables]
        if collisions:
            raise RuntimeError("master/derived table collision: " + ", ".join(collisions))

        counts: dict[str, int] = {}
        for table in DERIVED_TABLES:
            _clone_table_schema(dst, "derived", table)
            dst.execute(
                f"INSERT INTO {qident(table)} SELECT * FROM derived.{qident(table)}"
            )
            counts[table] = int(dst.execute(f"SELECT COUNT(*) FROM {qident(table)}").fetchone()[0])

        # Read-optimized indexes used by the production repository.
        dst.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_cf_plant_scientific_name ON plant_index(scientific_name);
            CREATE INDEX IF NOT EXISTS idx_cf_plant_common_name ON plant_index(common_name);
            CREATE INDEX IF NOT EXISTS idx_cf_envelope_taxon ON climate_envelope(taxon_id);
            CREATE INDEX IF NOT EXISTS idx_cf_envelope_variable_taxon ON climate_envelope(variable, taxon_id);
            CREATE INDEX IF NOT EXISTS idx_cf_soil_envelope_taxon ON soil_envelope(taxon_id);
            CREATE INDEX IF NOT EXISTS idx_cf_evidence_taxon ON evidence(taxon_id);
            CREATE INDEX IF NOT EXISTS idx_cf_native_region_location ON taxon_native_region(location_id, taxon_id);
            """
        )
        dst.commit()
        return counts
    finally:
        try:
            dst.commit()
        finally:
            dst.execute("DETACH DATABASE derived")


def _derived_metadata(path: Path) -> dict[str, str]:
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "build_metadata" not in tables:
            return {}
        return {str(k): str(v) for k, v in conn.execute("SELECT key,value FROM build_metadata")}


def build_consolidated_database(master_path: Path, derived_path: Path, output_path: Path) -> dict[str, Any]:
    """Create immutable v1.1 catalog by copying v1.0 then embedding scientific derived tables."""
    if not master_path.exists():
        raise FileNotFoundError(master_path)
    if not derived_path.exists():
        raise FileNotFoundError(derived_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(output_path.suffix + ".building")
    if tmp.exists():
        tmp.unlink()

    master_sha = sha256_file(master_path)
    derived_sha = sha256_file(derived_path)
    derived_meta = _derived_metadata(derived_path)
    if derived_meta.get("scientific_ready", "false").lower() != "true":
        raise RuntimeError("derived database is not scientific_ready")

    with sqlite3.connect(f"file:{master_path.resolve()}?mode=ro", uri=True) as source, sqlite3.connect(tmp) as dest:
        source.backup(dest)

    with sqlite3.connect(tmp) as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        counts = _copy_derived_tables(conn, derived_path)
        conn.execute(
            """
            CREATE TABLE climaflora_catalog_metadata (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            )
            """
        )
        metadata = {
            "catalog_version": CATALOG_VERSION,
            "catalog_role": "ClimaFlora consolidated scientific master",
            "base_master_filename": master_path.name,
            "base_master_sha256": master_sha,
            "derived_filename": derived_path.name,
            "derived_sha256": derived_sha,
            "scientific_ready": derived_meta.get("scientific_ready", "false"),
            "scientific_mode": derived_meta.get("mode", "UNKNOWN"),
            "scientific_method": derived_meta.get("scientific_method", "UNKNOWN"),
            "scientific_method_version": derived_meta.get("scientific_method_version", "UNKNOWN"),
            "scientific_source_ref": derived_meta.get("scientific_source_ref", ""),
            "scientific_limitations": derived_meta.get("scientific_limitations", ""),
            "envelope_coverage": derived_meta.get("envelope_coverage", ""),
            "created_at": utcnow(),
        }
        conn.executemany(
            "INSERT INTO climaflora_catalog_metadata(key,value) VALUES(?,?)",
            metadata.items(),
        )
        conn.commit()
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"consolidated integrity_check failed: {integrity}")
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"plant_taxa", "wcvp_distribution", "plant_index", "climate_envelope", "climaflora_catalog_metadata"}
        missing = sorted(required - tables)
        if missing:
            raise RuntimeError("consolidated database missing required tables: " + ", ".join(missing))
        variables = {row[0] for row in conn.execute("SELECT DISTINCT variable FROM climate_envelope")}
        missing_vars = sorted(set(CORE_VARIABLES) - variables)
        if missing_vars:
            raise RuntimeError("consolidated database missing climate variables: " + ", ".join(missing_vars))

    os.chmod(tmp, 0o444)
    os.replace(tmp, output_path)
    return {
        "catalog_version": CATALOG_VERSION,
        "master_sha256": master_sha,
        "derived_sha256": derived_sha,
        "sqlite_sha256": sha256_file(output_path),
        "sqlite_bytes": output_path.stat().st_size,
        "copied_tables": counts,
        "derived_metadata": derived_meta,
    }


@dataclass
class ConsolidationService:
    master_db: str
    derived_db: str
    output_db: str
    output_zst: str
    status_path: str
    manifest_path: str
    zstd_level: int = 10

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
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                data = {"phase": "error", "ready": False, "error": f"status read failed: {exc}"}
        else:
            data = {"phase": "not_started", "ready": False}
        output = Path(self.output_db)
        compressed = Path(self.output_zst)
        data.update(
            {
                "catalog_version": CATALOG_VERSION,
                "output_db": str(output),
                "output_zst": str(compressed),
                "sqlite_present": output.exists(),
                "compressed_present": compressed.exists(),
                "sqlite_bytes": output.stat().st_size if output.exists() else None,
                "compressed_bytes": compressed.stat().st_size if compressed.exists() else None,
            }
        )
        return data

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run_guarded, name="climaflora-consolidation", daemon=True)
            self._thread.start()

    def _run_guarded(self) -> None:
        try:
            self._run()
        except Exception as exc:  # noqa: BLE001
            self._write_status(phase="error", ready=False, error=f"{type(exc).__name__}: {exc}")

    def _wait_sources(self) -> tuple[Path, Path]:
        master = Path(self.master_db)
        derived = Path(self.derived_db)
        self._write_status(phase="waiting_sources", ready=False, error=None, started_at=utcnow())
        for _ in range(1800):
            if master.exists() and derived.exists():
                try:
                    meta = _derived_metadata(derived)
                    if meta.get("scientific_ready", "false").lower() == "true":
                        return master, derived
                except sqlite3.Error:
                    pass
            time.sleep(2)
        raise RuntimeError("master/derived sources did not become scientific-ready")

    def _compress(self, source: Path, target: Path) -> dict[str, Any]:
        tmp = target.with_suffix(target.suffix + ".part")
        if tmp.exists():
            tmp.unlink()
        level = max(1, min(19, int(self.zstd_level)))
        result = subprocess.run(
            ["zstd", f"-{level}", "-T0", "-f", str(source), "-o", str(tmp)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"zstd compression failed: {result.stderr.strip()}")
        os.replace(tmp, target)
        return {
            "compressed_sha256": sha256_file(target),
            "compressed_bytes": target.stat().st_size,
        }

    def _run(self) -> None:
        master, derived = self._wait_sources()
        output = Path(self.output_db)
        compressed = Path(self.output_zst)
        manifest = Path(self.manifest_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        if output.exists() and compressed.exists() and manifest.exists():
            try:
                existing = json.loads(manifest.read_text(encoding="utf-8"))
                if existing.get("catalog_version") == CATALOG_VERSION:
                    self._write_status(phase="ready", ready=True, reused=True, manifest=existing, error=None)
                    return
            except Exception:
                pass

        self._write_status(phase="consolidating", ready=False, error=None)
        result = build_consolidated_database(master, derived, output)
        self._write_status(phase="compressing", ready=False, sqlite=result)
        compressed_info = self._compress(output, compressed)
        artifact = {
            **result,
            **compressed_info,
            "catalog_version": CATALOG_VERSION,
            "filename": compressed.name,
            "generated_at": utcnow(),
        }
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
        self._write_status(phase="ready", ready=True, manifest=artifact, completed_at=utcnow(), error=None)


_services: dict[tuple[str, str, str], ConsolidationService] = {}
_services_lock = threading.Lock()


def get_consolidation_service(
    master_db: str,
    derived_db: str,
    output_db: str,
    output_zst: str,
    status_path: str,
    manifest_path: str,
    zstd_level: int = 10,
) -> ConsolidationService:
    key = (master_db, derived_db, output_db)
    with _services_lock:
        service = _services.get(key)
        if service is None:
            service = ConsolidationService(
                master_db=master_db,
                derived_db=derived_db,
                output_db=output_db,
                output_zst=output_zst,
                status_path=status_path,
                manifest_path=manifest_path,
                zstd_level=zstd_level,
            )
            _services[key] = service
        return service
