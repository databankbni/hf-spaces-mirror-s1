"""Async Word/PDF ingest jobs for standard paragraphs (local disk + daemon thread)."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from backend.storage import tenant_store

logger = logging.getLogger(__name__)

_job_lock = threading.Lock()
_running_tenants: set[str] = set()


def _utcnow_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _job_path(tenant_id: str, job_id: str) -> Path:
    return tenant_store.standard_paragraph_jobs_dir(tenant_id) / f"{job_id}.json"


def save_job(tenant_id: str, job: dict) -> None:
    path = _job_path(tenant_id, job["job_id"])
    path.write_text(json.dumps(job, indent=2), encoding="utf-8")


def load_job(tenant_id: str, job_id: str) -> dict | None:
    path = _job_path(tenant_id, job_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def create_upload_job(
    tenant_id: str,
    *,
    file_path: Path,
    filename: str,
    document_id: str,
) -> dict:
    job_id = uuid.uuid4().hex
    job = {
        "job_id": job_id,
        "tenant_id": tenant_id,
        "status": "queued",
        "created_at": _utcnow_iso(),
        "updated_at": _utcnow_iso(),
        "filename": filename,
        "document_id": document_id,
        "file_path": str(file_path),
        "progress": {"discovered": 0, "ingested": 0, "deduplicated": 0},
        "error": None,
        "result": None,
    }
    save_job(tenant_id, job)
    return job


def _run_job(tenant_id: str, job_id: str) -> None:
    from backend.standard_paragraphs import service

    job = load_job(tenant_id, job_id)
    if not job:
        return
    job["status"] = "running"
    job["updated_at"] = _utcnow_iso()
    save_job(tenant_id, job)

    try:
        path = Path(job["file_path"])
        result = service.ingest_from_word(
            tenant_id,
            path,
            document_id=job["document_id"],
            source_filename=job.get("filename") or path.name,
            ingestion_source="upload",
            replace_all=False,
            blob_key=str(path),
            update_schema_aliases=False,
        )
        job["status"] = "complete"
        job["progress"] = {
            "discovered": result.get("discovered", 0),
            "ingested": result.get("chunks", 0),
            "deduplicated": result.get("deduplicated", 0),
            "extraction_json": result.get("extraction_json"),
            "extraction_stats": result.get("extraction_stats"),
        }
        job["result"] = result
        job["extraction_json"] = result.get("extraction_json")
        job["error"] = None
    except Exception as exc:  # noqa: BLE001
        logger.exception("standard_paragraph upload job failed job_id=%s", job_id)
        job["status"] = "failed"
        job["error"] = str(exc)
    job["updated_at"] = _utcnow_iso()
    save_job(tenant_id, job)

    with _job_lock:
        _running_tenants.discard(tenant_id)


def schedule_upload_job(tenant_id: str, job_id: str) -> None:
    def _target() -> None:
        with _job_lock:
            _running_tenants.add(tenant_id)
        try:
            _run_job(tenant_id, job_id)
        finally:
            with _job_lock:
                _running_tenants.discard(tenant_id)

    t = threading.Thread(
        target=_target,
        name=f"sp-upload-{tenant_id}-{job_id[:8]}",
        daemon=True,
    )
    t.start()


def recover_stale_jobs(tenant_id: str) -> int:
    """Mark orphaned running jobs as failed when no worker is active."""
    with _job_lock:
        if tenant_id in _running_tenants:
            return 0
    jobs_dir = tenant_store.standard_paragraph_jobs_dir(tenant_id)
    recovered = 0
    for path in jobs_dir.glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(job, dict):
            continue
        if job.get("status") == "running":
            job["status"] = "failed"
            job["error"] = "Worker interrupted; job recovered on startup"
            job["updated_at"] = _utcnow_iso()
            path.write_text(json.dumps(job, indent=2), encoding="utf-8")
            recovered += 1
    return recovered
