"""File-backed section photo storage for report drafts (up to 5 per section)."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from backend.config import settings
from backend.storage import tenant_store

logger = logging.getLogger(__name__)

_ALLOWED_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "image/heif": ".heif",
}
ALLOWED_CONTENT_TYPES = frozenset(_ALLOWED_EXT.keys())


@dataclass
class SectionPhoto:
    id: str
    filename: str
    content_type: str
    selected_for_ai: bool
    created_at: str

    def to_dict(self, *, draft_id: str = "", section_id: str = "") -> dict:
        url = ""
        if draft_id and section_id:
            url = (
                f"/api/report/drafts/{draft_id}/sections/{section_id}/photos/{self.id}"
            )
        return {
            "photo_id": self.id,
            "filename": self.filename,
            "content_type": self.content_type,
            "selected_for_ai": self.selected_for_ai,
            "created_at": self.created_at,
            "url": url,
        }


def _manifest_path(tenant_id: str, draft_id: str, section_id: str) -> Path:
    return (
        tenant_store.photo_section_dir(tenant_id, draft_id, section_id)
        / "manifest.json"
    )


def _load_manifest(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return list(data.get("photos") or [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read photo manifest %s: %s", path, exc)
        return []


def _save_manifest(path: Path, photos: list[dict]) -> None:
    path.write_text(
        json.dumps({"photos": photos}, indent=2),
        encoding="utf-8",
    )


def _row_to_photo(row: dict) -> SectionPhoto:
    return SectionPhoto(
        id=str(row["id"]),
        filename=str(row.get("filename") or row["id"]),
        content_type=str(row.get("content_type") or "image/jpeg"),
        selected_for_ai=bool(row.get("selected_for_ai")),
        created_at=str(row.get("created_at") or ""),
    )


def list_section_photos(
    tenant_id: str,
    draft_id: str,
    section_id: str,
) -> list[SectionPhoto]:
    rows = _load_manifest(_manifest_path(tenant_id, draft_id, section_id))
    return [_row_to_photo(r) for r in rows]


def photo_file_path(
    tenant_id: str,
    draft_id: str,
    section_id: str,
    photo_id: str,
    *,
    content_type: str | None = None,
) -> Path | None:
    folder = tenant_store.photo_section_dir(tenant_id, draft_id, section_id)
    if content_type:
        ext = _ALLOWED_EXT.get(content_type.lower(), ".jpg")
        candidate = folder / f"{photo_id}{ext}"
        if candidate.is_file():
            return candidate
    for p in folder.glob(f"{photo_id}.*"):
        if p.is_file() and p.name != "manifest.json":
            return p
    return None


def add_section_photo(
    tenant_id: str,
    draft_id: str,
    section_id: str,
    data: bytes,
    *,
    content_type: str,
    original_filename: str = "",
) -> SectionPhoto:
    max_count = settings.max_section_photos_per_section
    manifest = _manifest_path(tenant_id, draft_id, section_id)
    rows = _load_manifest(manifest)
    if len(rows) >= max_count:
        raise ValueError(f"Maximum {max_count} photos per section.")

    ct = content_type.lower().split(";")[0].strip()
    if ct not in _ALLOWED_EXT:
        raise ValueError(f"Unsupported image type: {content_type}")

    if len(data) > settings.max_section_photo_bytes:
        raise ValueError("Photo exceeds max_section_photo_bytes.")

    photo_id = uuid.uuid4().hex[:16]
    ext = _ALLOWED_EXT[ct]
    folder = tenant_store.photo_section_dir(tenant_id, draft_id, section_id)
    out_path = folder / f"{photo_id}{ext}"
    out_path.write_bytes(data)

    row = {
        "id": photo_id,
        "filename": original_filename or f"{photo_id}{ext}",
        "content_type": ct,
        "selected_for_ai": False,
        "created_at": datetime.now(UTC).isoformat(),
    }
    rows.append(row)
    _save_manifest(manifest, rows)
    return _row_to_photo(row)


def set_ai_selection(
    tenant_id: str,
    draft_id: str,
    section_id: str,
    photo_ids: list[str],
) -> list[SectionPhoto]:
    max_ai = settings.max_section_photos_for_ai
    requested = [pid.strip() for pid in photo_ids if pid and pid.strip()]
    if len(requested) > max_ai:
        raise ValueError(f"At most {max_ai} photo(s) may be selected for AI analysis.")
    if len(requested) != len(set(requested)):
        raise ValueError("Duplicate photo_ids in selection.")

    manifest = _manifest_path(tenant_id, draft_id, section_id)
    rows = _load_manifest(manifest)
    known = {str(r["id"]) for r in rows}
    missing = [pid for pid in requested if pid not in known]
    if missing:
        raise ValueError(f"Unknown photo_id(s): {', '.join(missing[:5])}")

    selected = set(requested)
    for row in rows:
        row["selected_for_ai"] = str(row["id"]) in selected
    _save_manifest(manifest, rows)
    return [_row_to_photo(r) for r in rows]


def delete_section_photo(
    tenant_id: str,
    draft_id: str,
    section_id: str,
    photo_id: str,
) -> bool:
    manifest = _manifest_path(tenant_id, draft_id, section_id)
    rows = _load_manifest(manifest)
    kept: list[dict] = []
    deleted = False
    for row in rows:
        if str(row["id"]) == photo_id:
            deleted = True
            path = photo_file_path(
                tenant_id,
                draft_id,
                section_id,
                photo_id,
                content_type=str(row.get("content_type") or ""),
            )
            if path and path.is_file():
                path.unlink(missing_ok=True)
        else:
            kept.append(row)
    if deleted:
        _save_manifest(manifest, kept)
    return deleted


def all_section_photo_paths(
    tenant_id: str,
    draft_id: str,
    section_id: str,
) -> list[tuple[Path, str]]:
    """Return all uploaded photos for DOCX export (up to max per section)."""
    out: list[tuple[Path, str]] = []
    for photo in list_section_photos(tenant_id, draft_id, section_id):
        path = photo_file_path(
            tenant_id, draft_id, section_id, photo.id, content_type=photo.content_type
        )
        if path and path.is_file():
            out.append((path, photo.content_type))
    return out[: settings.max_section_photos_per_section]


def selected_photo_paths(
    tenant_id: str,
    draft_id: str,
    section_id: str,
) -> list[tuple[Path, str]]:
    """Return (path, content_type) for photos ticked for AI analysis."""
    out: list[tuple[Path, str]] = []
    for photo in list_section_photos(tenant_id, draft_id, section_id):
        if not photo.selected_for_ai:
            continue
        path = photo_file_path(
            tenant_id, draft_id, section_id, photo.id, content_type=photo.content_type
        )
        if path and path.is_file():
            out.append((path, photo.content_type))
    return out[: settings.max_section_photos_for_ai]


def draft_section_photo_paths(
    tenant_id: str,
    draft_id: str | None,
    section_ids: list[str],
) -> dict[str, list[str]]:
    """Map section_id -> filesystem paths for all uploaded photos in a draft."""
    if not draft_id:
        return {}
    out: dict[str, list[str]] = {}
    for sid in section_ids:
        paths = all_section_photo_paths(tenant_id, draft_id, sid)
        if paths:
            out[sid] = [str(p) for p, _ in paths]
    return out
