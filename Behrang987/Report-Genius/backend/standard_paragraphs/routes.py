"""Internal + tenant JWT routes for standard paragraph memory."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import JSONResponse

from backend.api.deps import get_internal_tenant
from backend.config import settings
from backend.standard_paragraphs import jobs as sp_jobs
from backend.standard_paragraphs import service as sp_service
from backend.standard_paragraphs.models import AddToMemoryRequest
from backend.storage import tenant_store

router = APIRouter(
    prefix="/internal/v1/standard-paragraphs",
    tags=["standard-paragraphs"],
)

_ALLOWED = {".docx", ".docm", ".doc", ".pdf"}
_ALLOWED_LABEL = ".docx, .docm, .doc, .pdf"


def _envelope(*, data: dict | list | None = None, error: dict | None = None) -> dict:
    return {"ok": error is None, "data": data, "error": error}


def _error_response(
    code: str,
    message: str,
    *,
    status_code: int = 400,
    details: dict | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=_envelope(
            error={"code": code, "message": message, "details": details or {}}
        ),
    )


@router.post(
    "/memory",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
)
def add_to_memory(
    body: AddToMemoryRequest,
    tenant_id: str = Depends(get_internal_tenant),
) -> Any:
    try:
        result = sp_service.ingest_runtime_memory(
            tenant_id,
            subsection_id=body.subsection_id,
            text=body.text,
            section_id=body.section_id,
            section_name=body.subsection_name or body.section_name,
        )
    except ValueError as exc:
        return _error_response("VALIDATION_ERROR", str(exc), status_code=422)
    except Exception as exc:  # noqa: BLE001
        return _error_response("INGEST_FAILED", str(exc), status_code=500)
    return _envelope(data=result)


@router.post(
    "/upload",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=None,
)
async def upload_standard_paragraphs(
    file: UploadFile = File(...),
    tenant_id: str = Depends(get_internal_tenant),
) -> Any:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED:
        return _error_response(
            "VALIDATION_ERROR",
            f"Unsupported file type '{suffix}'. Allowed: {_ALLOWED_LABEL}",
            status_code=400,
        )
    content = await file.read()
    if not content:
        return _error_response("VALIDATION_ERROR", "Empty upload body", status_code=400)
    max_b = int(settings.standard_paragraphs_max_upload_bytes)
    if len(content) > max_b:
        return _error_response(
            "VALIDATION_ERROR",
            f"File exceeds max size of {max_b} bytes",
            status_code=400,
        )

    document_id = f"upload:{uuid.uuid4().hex}"
    safe_name = Path(file.filename or f"upload{suffix}").name
    dest = tenant_store.standard_paragraph_upload_path(tenant_id, document_id, suffix)
    dest.write_bytes(content)

    job = sp_jobs.create_upload_job(
        tenant_id,
        file_path=dest,
        filename=safe_name,
        document_id=document_id,
    )
    sp_jobs.schedule_upload_job(tenant_id, job["job_id"])
    return _envelope(
        data={
            "job_id": job["job_id"],
            "status": job["status"],
            "document_id": document_id,
            "filename": safe_name,
        }
    )


@router.get("/jobs/{job_id}", response_model=None)
def get_job(job_id: str, tenant_id: str = Depends(get_internal_tenant)) -> Any:
    job = sp_jobs.load_job(tenant_id, job_id)
    if not job:
        return _error_response("NOT_FOUND", f"Job not found: {job_id}", status_code=404)
    return _envelope(
        data={
            "job_id": job["job_id"],
            "status": job["status"],
            "progress": job.get("progress"),
            "error": job.get("error"),
            "result": job.get("result"),
            "extraction_json": job.get("extraction_json")
            or (job.get("result") or {}).get("extraction_json"),
            "filename": job.get("filename"),
            "document_id": job.get("document_id"),
            "updated_at": job.get("updated_at"),
        }
    )


@router.get("", response_model=None)
def list_items(
    subsection_id: str | None = None,
    tenant_id: str = Depends(get_internal_tenant),
) -> dict:
    items = sp_service.list_paragraphs(tenant_id, subsection_id=subsection_id)
    return _envelope(data={"items": items, "count": len(items)})


@router.get("/documents/{document_id}/extraction", response_model=None)
def get_extraction_json(
    document_id: str, tenant_id: str = Depends(get_internal_tenant)
) -> Any:
    """Return the extraction debug JSON for an uploaded SP document."""
    import json

    path = tenant_store.standard_paragraph_extract_json_path(tenant_id, document_id)
    if not path.is_file():
        return _error_response(
            "NOT_FOUND",
            f"Extraction JSON not found for document: {document_id}",
            status_code=404,
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _error_response(
            "READ_FAILED", str(exc), status_code=500
        )
    return _envelope(
        data={
            "document_id": document_id,
            "path": str(path),
            "extraction": data,
        }
    )


@router.delete("/documents/{document_id}", response_model=None)
def delete_document(
    document_id: str, tenant_id: str = Depends(get_internal_tenant)
) -> dict:
    removed = sp_service.remove_document_paragraphs(tenant_id, document_id)
    return _envelope(data={"removed": removed, "document_id": document_id})


@router.delete("/{chunk_id}", response_model=None)
def delete_chunk(chunk_id: str, tenant_id: str = Depends(get_internal_tenant)) -> Any:
    removed = sp_service.remove_chunk(tenant_id, chunk_id)
    if removed == 0:
        return _error_response(
            "NOT_FOUND", f"Chunk not found: {chunk_id}", status_code=404
        )
    return _envelope(data={"removed": removed, "chunk_id": chunk_id})
