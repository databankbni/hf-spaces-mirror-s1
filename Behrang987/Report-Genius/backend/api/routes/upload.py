"""Reference document upload (scrub + ingest into the REFERENCE tier)."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status

from backend.api.deps import get_current_tenant
from backend.config import settings


def _upload_temp_dir() -> Path:
    from backend.utils.runtime_paths import ensure_data_drive_runtime_dirs

    ensure_data_drive_runtime_dirs()
    d = settings.data_dir_path / "tmp" / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


from backend.ingest import pipeline as ingest  # noqa: E402

router = APIRouter(prefix="/api/upload", tags=["upload"])

_ALLOWED = {".pdf", ".docx", ".docm", ".doc"}


@router.post("/reference", status_code=status.HTTP_201_CREATED)
async def upload_reference(
    file: UploadFile,
    property_type: str = Form(...),
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    """Scrub and ingest a past report as style reference. Never structural."""
    from backend.domain.property_type import PropertyTypeError, normalize_property_type

    try:
        canonical_pt = normalize_property_type(property_type)
    except PropertyTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{suffix}'. Allowed: {sorted(_ALLOWED)}",
        )

    tmp_dir = Path(tempfile.mkdtemp(prefix="rics_v2_ref_", dir=str(_upload_temp_dir())))
    safe_name = Path(file.filename or f"upload{suffix}").name
    tmp_path = tmp_dir / safe_name
    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Empty upload body")
        tmp_path.write_bytes(content)
        result = ingest.ingest_reference_report(
            tenant_id,
            tmp_path,
            source_filename=safe_name,
            property_type=canonical_pt,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {
        "ingested_chunks": result["chunks"],
        "filename": file.filename,
        "tier": "reference",
        "property_type": canonical_pt,
        "verification": result["verification"],
        "extraction_method": result.get("extraction_method"),
        "segmentation_method": result.get("segmentation_method"),
    }


@router.get("/reference/status")
def reference_status(tenant_id: str = Depends(get_current_tenant)) -> dict:
    """Summarise ingested past reports for the demo UI."""
    from backend.rag.store import get_rag_store
    from backend.rag.types import TIER_REFERENCE

    store = get_rag_store()
    count = store.count(tenant_id, TIER_REFERENCE)
    return {
        "reference_chunk_count": count,
        "reference_documents": store.list_source_filenames(tenant_id, TIER_REFERENCE),
        "ready_for_generation": count > 0,
    }
