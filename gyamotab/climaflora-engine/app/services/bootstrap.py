import hashlib
import json
import os
import sqlite3
import threading
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_MASTER_URLS = [
    "https://shugoan.com/climaflora/data/climaflora_global_plants_v1_0.sqlite.zst",
    "https://shugoan.com/climaflora/data/climat_global_plants_v1_0.sqlite.zst",
]
EXPECTED_COMPRESSED_SHA256 = "93ea55eb60048b8c08baf6d6b3ecafc74dedcbb9e1bc09d286a8d6b03837eb4c"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _qident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


class MasterBootstrapService:
    """Background retrieval + read-only audit of the immutable master SQLite."""

    def __init__(
        self, master_db: str, status_path: str, audit_path: str,
        source_urls: list[str] | None = None, expected_sha256: str | None = EXPECTED_COMPRESSED_SHA256,
        required_tables: list[str] | None = None, expected_catalog_version: str | None = None,
        expected_sqlite_sha256: str | None = None,
    ):
        self.master_db = Path(master_db)
        self.source_urls = list(source_urls or DEFAULT_MASTER_URLS)
        self.expected_sha256 = (expected_sha256 or "").strip().lower() or None
        self.required_tables = list(required_tables or [])
        self.expected_catalog_version = (expected_catalog_version or "").strip() or None
        self.expected_sqlite_sha256 = (expected_sqlite_sha256 or "").strip().lower() or None
        if not self.source_urls:
            raise ValueError("at least one master source URL is required")
        self.compressed = self.master_db.with_suffix(self.master_db.suffix + ".zst")
        self.status_path = Path(status_path)
        self.audit_path = Path(audit_path)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state: dict[str, Any] = {
            "phase": "idle",
            "started_at": None,
            "updated_at": _utcnow(),
            "ready": self.master_db.exists() and self.audit_path.exists(),
            "master_db": str(self.master_db),
            "audit_path": str(self.audit_path),
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            state = dict(self._state)
        if self.status_path.exists():
            try:
                persisted = json.loads(self.status_path.read_text(encoding="utf-8"))
                state.update(persisted)
            except Exception:
                pass
        state["master_present"] = self.master_db.exists()
        state["audit_present"] = self.audit_path.exists()
        return state

    def _set(self, **updates: Any) -> None:
        with self._lock:
            self._state.update(updates)
            self._state["updated_at"] = _utcnow()
            snapshot = dict(self._state)
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.status_path.with_suffix(self.status_path.suffix + ".tmp")
        tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.status_path)

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, daemon=True, name="climaflora-master-bootstrap")
            self._thread.start()

    def _run(self) -> None:
        try:
            self._set(phase="starting", started_at=_utcnow(), ready=False, error=None)
            self.master_db.parent.mkdir(parents=True, exist_ok=True)
            if not self.master_db.exists():
                self._download_and_decompress()
            self._audit()
            self._set(phase="ready", ready=True, completed_at=_utcnow(), error=None)
        except Exception as exc:  # noqa: BLE001
            self._set(phase="error", ready=False, error=f"{type(exc).__name__}: {exc}")

    def _download_and_decompress(self) -> None:
        part = self.compressed.with_suffix(self.compressed.suffix + ".part")
        last_error: Exception | None = None
        selected_url = None
        digest = None
        errors: dict[str, str] = {}
        for url in self.source_urls:
            try:
                self._set(phase="downloading", source_url=url, bytes_downloaded=0)
                h = hashlib.sha256()
                total = 0
                req = urllib.request.Request(url, headers={"User-Agent": "ClimaFlora/0.5.0"})
                with urllib.request.urlopen(req, timeout=120) as src, part.open("wb") as out:
                    while True:
                        chunk = src.read(8 * 1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                        h.update(chunk)
                        total += len(chunk)
                        self._set(bytes_downloaded=total)
                digest = h.hexdigest()
                if self.expected_sha256 and digest != self.expected_sha256:
                    raise RuntimeError(
                        f"master SHA-256 mismatch: got {digest}; expected {self.expected_sha256}"
                    )
                part.replace(self.compressed)
                selected_url = url
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                errors[url] = f"{type(exc).__name__}: {exc}"
                self._set(download_errors=errors)
                if part.exists():
                    part.unlink()
        if selected_url is None:
            raise RuntimeError(
                "master download failed from all configured URLs: "
                + json.dumps(errors, ensure_ascii=False)
            ) from last_error

        self._set(
            phase="decompressing",
            source_url=selected_url,
            compressed_sha256=digest,
            compressed_bytes=self.compressed.stat().st_size,
        )
        tmp_db = self.master_db.with_suffix(self.master_db.suffix + ".part")
        result = subprocess.run(
            ["zstd", "-d", "-f", str(self.compressed), "-o", str(tmp_db)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"zstd decompression failed: {result.stderr.strip()}")
        if self.expected_sqlite_sha256:
            h = hashlib.sha256()
            with tmp_db.open("rb") as src:
                while True:
                    chunk = src.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    h.update(chunk)
            sqlite_digest = h.hexdigest()
            self._set(sqlite_sha256=sqlite_digest)
            if sqlite_digest != self.expected_sqlite_sha256:
                raise RuntimeError(
                    f"master SQLite SHA-256 mismatch: got {sqlite_digest}; expected {self.expected_sqlite_sha256}"
                )
        os.chmod(tmp_db, 0o444)
        tmp_db.replace(self.master_db)

    def _audit(self) -> None:
        self._set(phase="auditing", sqlite_bytes=self.master_db.stat().st_size)
        uri = f"file:{self.master_db.resolve()}?mode=ro"
        report: dict[str, Any] = {
            "database": str(self.master_db),
            "size_bytes": self.master_db.stat().st_size,
            "audited_at": _utcnow(),
            "read_only": True,
            "compressed_sha256_expected": self.expected_sha256,
            "sqlite_sha256_expected": self.expected_sqlite_sha256,
        }
        if self.expected_sqlite_sha256:
            h = hashlib.sha256()
            with self.master_db.open("rb") as src:
                while True:
                    chunk = src.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    h.update(chunk)
            sqlite_digest = h.hexdigest()
            report["sqlite_sha256"] = sqlite_digest
            self._set(sqlite_sha256=sqlite_digest)
            if sqlite_digest != self.expected_sqlite_sha256:
                raise RuntimeError(
                    f"master SQLite SHA-256 mismatch: got {sqlite_digest}; expected {self.expected_sqlite_sha256}"
                )

        with sqlite3.connect(uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            report["sqlite_version"] = sqlite3.sqlite_version
            integrity = [row[0] for row in conn.execute("PRAGMA integrity_check")]
            foreign_keys = [list(row) for row in conn.execute("PRAGMA foreign_key_check")]
            report["integrity_check"] = integrity
            report["foreign_key_check"] = foreign_keys
            if integrity != ["ok"]:
                raise RuntimeError(f"SQLite integrity_check failed: {integrity[:10]}")
            if foreign_keys:
                raise RuntimeError(f"SQLite foreign_key_check found {len(foreign_keys)} violation(s)")

            objects = conn.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
            ).fetchall()
            report["objects"] = [dict(row) for row in objects]
            tables = [row["name"] for row in objects if row["type"] == "table"]
            if self.required_tables:
                missing_required = sorted(set(self.required_tables) - set(tables))
                report["required_tables"] = self.required_tables
                report["missing_required_tables"] = missing_required
                if missing_required:
                    raise RuntimeError("master database missing required tables: " + ", ".join(missing_required))
            if self.expected_catalog_version:
                build_meta = {}
                if "build_metadata" in tables:
                    build_meta = {str(k): str(v) for k, v in conn.execute("SELECT key,value FROM build_metadata")}
                    report["build_metadata"] = build_meta
                if "climaflora_catalog_metadata" in tables:
                    metadata = {str(k): str(v) for k, v in conn.execute("SELECT key,value FROM climaflora_catalog_metadata")}
                    report["catalog_metadata"] = metadata
                    if metadata.get("catalog_version") != self.expected_catalog_version:
                        raise RuntimeError(
                            f"catalog version mismatch: got {metadata.get('catalog_version')!r}; expected {self.expected_catalog_version!r}"
                        )
                    scientific_flag = metadata.get("scientific_ready", "").lower() == "true" or build_meta.get("scientific_ready", "").lower() == "true"
                    if not scientific_flag:
                        raise RuntimeError("catalog is not scientific_ready in catalog_metadata or build_metadata")
                elif self.expected_catalog_version == "1.1.0" and build_meta:
                    report["catalog_metadata_compatibility"] = "v1.1 build_metadata fallback"
                    if build_meta.get("scientific_ready", "").lower() != "true":
                        raise RuntimeError("v1.1 build_metadata is not scientific_ready")
                else:
                    raise RuntimeError("master database has no climaflora_catalog_metadata table")
            report["tables"] = {}
            for idx, table in enumerate(tables, start=1):
                self._set(phase="auditing", audit_table=table, audit_table_index=idx, audit_table_total=len(tables))
                qname = _qident(table)
                columns = [dict(row) for row in conn.execute(f"PRAGMA table_info({qname})")]
                fks = [dict(row) for row in conn.execute(f"PRAGMA foreign_key_list({qname})")]
                count = conn.execute(f"SELECT COUNT(*) FROM {qname}").fetchone()[0]
                report["tables"][table] = {
                    "row_count": count,
                    "columns": columns,
                    "foreign_keys": fks,
                }

        report["summary"] = {
            "table_count": len(report["tables"]),
            "view_count": sum(1 for o in report["objects"] if o["type"] == "view"),
            "index_count": sum(1 for o in report["objects"] if o["type"] == "index"),
            "trigger_count": sum(1 for o in report["objects"] if o["type"] == "trigger"),
            "row_count_total": sum(v["row_count"] for v in report["tables"].values()),
        }
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.audit_path.with_suffix(self.audit_path.suffix + ".tmp")
        tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.audit_path)

    def audit(self) -> dict[str, Any] | None:
        if not self.audit_path.exists():
            return None
        return json.loads(self.audit_path.read_text(encoding="utf-8"))


_services: dict[tuple, MasterBootstrapService] = {}


def get_master_bootstrap(
    master_db: str, status_path: str, audit_path: str, source_urls: list[str] | None = None,
    expected_sha256: str | None = EXPECTED_COMPRESSED_SHA256, required_tables: list[str] | None = None,
    expected_catalog_version: str | None = None, expected_sqlite_sha256: str | None = None,
) -> MasterBootstrapService:
    urls = tuple(source_urls or DEFAULT_MASTER_URLS)
    required = tuple(required_tables or ())
    expected = (expected_sha256 or "").strip().lower() or None
    catalog_version = (expected_catalog_version or "").strip() or None
    sqlite_expected = (expected_sqlite_sha256 or "").strip().lower() or None
    key = (master_db, status_path, audit_path, urls, expected, required, catalog_version, sqlite_expected)
    if key not in _services:
        _services[key] = MasterBootstrapService(
            master_db, status_path, audit_path, list(urls), expected, list(required), catalog_version, sqlite_expected
        )
    return _services[key]
