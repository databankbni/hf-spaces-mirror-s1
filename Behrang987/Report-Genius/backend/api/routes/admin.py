"""Gated admin override for the operator master template.

Enabled only when ``master_template_upload_enabled=true`` and a valid admin token
is supplied (see :func:`backend.api.deps.require_admin`). Lets an operator replace
the master at runtime (re-discover schema + rebuild MASTER RAG) without redeploy.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

from backend.api.deps import require_admin
from backend.ingest import pipeline as ingest
from backend.pii import scrubber as pii_scrubber

router = APIRouter(prefix="/admin", tags=["admin"])

_ALLOWED = {".docx", ".docm", ".doc", ".pdf"}


@router.post("/template", status_code=status.HTTP_201_CREATED)
async def override_template(
    file: UploadFile,
    tenant_id: str = Depends(require_admin),
) -> dict:
    """Replace the master template from an uploaded file."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{suffix}'. Allowed: {sorted(_ALLOWED)}",
        )

    tmp_dir = Path(tempfile.mkdtemp(prefix="rics_v2_master_"))
    tmp_path = tmp_dir / (file.filename or f"master{suffix}")
    try:
        with tmp_path.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        result = ingest.ingest_master(tenant_id, tmp_path)
    except pii_scrubber.PiiDetectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {"status": "master_replaced", **result}


@router.post("/template/reingest")
async def reingest_template(tenant_id: str = Depends(require_admin)) -> dict:
    """Re-run schema discovery + standard-paragraph ingest from configured paths."""
    try:
        result = ingest.ingest_operator_bundle(tenant_id)
    except pii_scrubber.PiiDetectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return {"status": "reingested", **result}
