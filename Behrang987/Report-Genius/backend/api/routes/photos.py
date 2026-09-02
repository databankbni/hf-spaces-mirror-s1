"""Report draft section photo upload and AI selection (max 5 stored, max 2 for vision)."""

from __future__ import annotations

import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field

from backend.api import security
from backend.api.deps import get_current_tenant
from backend.config import settings
from backend.storage import photo_store
from backend.storage.photo_store import ALLOWED_CONTENT_TYPES

router = APIRouter(prefix="/api/report/drafts", tags=["report-photos"])


def _resolve_tenant_from_token(
    authorization: str = Header(default=""),
    access_token: str = Query(default=""),
) -> str:
    """Bearer header or ?access_token= for image tags."""
    token = ""
    if authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    elif access_token.strip():
        token = access_token.strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = security.decode_token(token)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    tenant_id = payload.get("sub")
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing subject"
        )
    return tenant_id


def _photo_dict(
    photo: photo_store.SectionPhoto, draft_id: str, section_id: str
) -> dict:
    return photo.to_dict(draft_id=draft_id, section_id=section_id)


class AiSelectionBody(BaseModel):
    photo_ids: list[str] = Field(default_factory=list)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_draft(tenant_id: str = Depends(get_current_tenant)) -> dict:
    """Create a report draft id for associating section photos before generation."""
    draft_id = uuid.uuid4().hex
    return {
        "draft_id": draft_id,
        "max_photos_per_section": settings.max_section_photos_per_section,
        "max_photos_for_ai": settings.max_section_photos_for_ai,
    }


@router.post(
    "/{draft_id}/sections/{section_id}/photos",
    status_code=status.HTTP_201_CREATED,
)
async def upload_section_photos(
    draft_id: str,
    section_id: str,
    files: list[UploadFile] = File(...),
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    saved = []
    for upload in files:
        ct = (upload.content_type or "image/jpeg").lower().split(";")[0].strip()
        if ct not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported content type: {upload.content_type}",
            )
        data = await upload.read()
        try:
            row = photo_store.add_section_photo(
                tenant_id,
                draft_id,
                section_id,
                data,
                content_type=ct,
                original_filename=upload.filename or "",
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        saved.append(_photo_dict(row, draft_id, section_id))

    rows = photo_store.list_section_photos(tenant_id, draft_id, section_id)
    return {
        "draft_id": draft_id,
        "section_id": section_id,
        "uploaded": saved,
        "photos": [_photo_dict(p, draft_id, section_id) for p in rows],
        "max_photos_per_section": settings.max_section_photos_per_section,
        "max_photos_for_ai": settings.max_section_photos_for_ai,
    }


@router.get("/{draft_id}/sections/{section_id}/photos")
def list_section_photos(
    draft_id: str,
    section_id: str,
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    rows = photo_store.list_section_photos(tenant_id, draft_id, section_id)
    return {
        "draft_id": draft_id,
        "section_id": section_id,
        "photos": [_photo_dict(p, draft_id, section_id) for p in rows],
        "max_photos_per_section": settings.max_section_photos_per_section,
        "max_photos_for_ai": settings.max_section_photos_for_ai,
    }


@router.get("/{draft_id}/sections/{section_id}/photos/{photo_id}")
def get_section_photo(
    draft_id: str,
    section_id: str,
    photo_id: str,
    tenant_id: str = Depends(_resolve_tenant_from_token),
) -> Response:
    rows = photo_store.list_section_photos(tenant_id, draft_id, section_id)
    row = next((r for r in rows if r.id == photo_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="Photo not found.")
    path = photo_store.photo_file_path(
        tenant_id, draft_id, section_id, photo_id, content_type=row.content_type
    )
    if not path or not path.is_file():
        raise HTTPException(status_code=404, detail="Photo file missing.")
    data = path.read_bytes()
    return Response(content=data, media_type=row.content_type)


@router.put("/{draft_id}/sections/{section_id}/photos/ai-selection")
def set_ai_selection(
    draft_id: str,
    section_id: str,
    body: AiSelectionBody,
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    try:
        rows = photo_store.set_ai_selection(
            tenant_id, draft_id, section_id, body.photo_ids
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "draft_id": draft_id,
        "section_id": section_id,
        "selected_photo_ids": body.photo_ids,
        "max_photos_for_ai": settings.max_section_photos_for_ai,
        "photos": [_photo_dict(p, draft_id, section_id) for p in rows],
    }


@router.delete(
    "/{draft_id}/sections/{section_id}/photos/{photo_id}",
    status_code=status.HTTP_200_OK,
)
def delete_section_photo(
    draft_id: str,
    section_id: str,
    photo_id: str,
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    if not photo_store.delete_section_photo(tenant_id, draft_id, section_id, photo_id):
        raise HTTPException(status_code=404, detail="Photo not found.")
    return {
        "draft_id": draft_id,
        "section_id": section_id,
        "photo_id": photo_id,
        "deleted": True,
    }
