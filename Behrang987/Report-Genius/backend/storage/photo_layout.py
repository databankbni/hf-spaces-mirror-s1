"""Learn and apply photo placement patterns from uploaded past-report DOCX files."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from backend.storage import tenant_store

logger = logging.getLogger(__name__)

PhotoPlacement = Literal["after_heading", "after_body"]

_SECTION_CODE_RE = re.compile(
    r"^\s*([A-L]|[A-Z]\d{1,2})\b",
    re.IGNORECASE,
)
_CAPTION_RE = re.compile(
    r"^(photograph|photo|illustration|figure|image)s?\b",
    re.IGNORECASE,
)


@dataclass
class SectionPhotoLayout:
    placement: PhotoPlacement = "after_heading"
    caption: str | None = "Photographs"
    width_inches: float = 5.8
    spacing_after_pt: float = 6.0

    @classmethod
    def from_dict(cls, data: dict | None) -> SectionPhotoLayout:
        if not data:
            return cls()
        placement = data.get("placement", "after_heading")
        if placement not in ("after_heading", "after_body"):
            placement = "after_heading"
        return cls(
            placement=placement,
            caption=data.get("caption") or "Photographs",
            width_inches=float(data.get("width_inches") or 5.8),
            spacing_after_pt=float(data.get("spacing_after_pt") or 6.0),
        )


def _layout_path(tenant_id: str) -> Path:
    return tenant_store.tenant_root(tenant_id) / "photo_layout.json"


def load_tenant_photo_layout(tenant_id: str) -> dict[str, SectionPhotoLayout]:
    path = _layout_path(tenant_id)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        sections = raw.get("sections") or {}
        return {
            str(k).upper(): SectionPhotoLayout.from_dict(v) for k, v in sections.items()
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read photo layout for %s: %s", tenant_id, exc)
        return {}


def save_tenant_photo_layout(
    tenant_id: str, layouts: dict[str, SectionPhotoLayout]
) -> None:
    path = _layout_path(tenant_id)
    payload = {
        "sections": {k: asdict(v) for k, v in sorted(layouts.items())},
        "default": asdict(SectionPhotoLayout()),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def get_section_photo_layout(tenant_id: str, section_id: str) -> SectionPhotoLayout:
    layouts = load_tenant_photo_layout(tenant_id)
    key = (section_id or "").strip().upper()
    if key in layouts:
        return layouts[key]
    default = layouts.get("DEFAULT")
    if default:
        return default
    return SectionPhotoLayout()


def _para_has_image(para) -> bool:
    try:
        for run in para.runs:
            xml = run._element.xml  # noqa: SLF001
            if (
                "wp:inline" in xml
                or "wp:anchor" in xml
                or "a:blip" in xml
                or "pic:pic" in xml
            ):
                return True
    except Exception:  # noqa: BLE001
        return False
    return False


def _section_token(text: str, valid_codes: set[str]) -> str | None:
    txt = (text or "").strip()
    if not txt:
        return None
    token = txt.split()[0].strip().strip(".").upper()
    if token in valid_codes:
        return token
    m = _SECTION_CODE_RE.match(txt.upper())
    if m and m.group(1).upper() in valid_codes:
        return m.group(1).upper()
    return None


def analyze_docx_photo_layout(
    docx_path: Path,
    valid_section_ids: set[str] | None = None,
) -> dict[str, SectionPhotoLayout]:
    """Detect per-section photo placement from a past-report DOCX."""
    from docx import Document

    valid = {s.upper() for s in (valid_section_ids or set())}
    doc = Document(str(docx_path))

    # Per section: track order of first body vs first image; optional caption line.
    first_body_idx: dict[str, int] = {}
    first_image_idx: dict[str, int] = {}
    caption: dict[str, str] = {}
    current: str | None = None

    for idx, para in enumerate(doc.paragraphs):
        txt = (para.text or "").strip()
        style_name = str(getattr(para.style, "name", "") or "")

        sid = _section_token(txt, valid) if valid else None
        if sid and ("Heading" in style_name or len(txt.split()) <= 6):
            current = sid
            continue

        if current is None:
            continue

        if _para_has_image(para):
            first_image_idx.setdefault(current, idx)
            continue

        if not txt:
            continue

        if _CAPTION_RE.match(txt) and current not in caption:
            caption[current] = txt
            continue

        if "Heading" in style_name:
            continue

        first_body_idx.setdefault(current, idx)

    layouts: dict[str, SectionPhotoLayout] = {}
    for sid in set(first_body_idx) | set(first_image_idx):
        body_i = first_body_idx.get(sid, 10**9)
        img_i = first_image_idx.get(sid, 10**9)
        placement: PhotoPlacement = "after_heading" if img_i < body_i else "after_body"
        layouts[sid] = SectionPhotoLayout(
            placement=placement,
            caption=caption.get(sid) or "Photographs",
        )

    return layouts


def merge_layout_from_reference_docx(
    tenant_id: str,
    docx_path: Path,
    *,
    valid_section_ids: set[str] | None = None,
) -> dict[str, SectionPhotoLayout]:
    """Update tenant layout cache from an ingested past-report DOCX."""
    if docx_path.suffix.lower() not in (".docx", ".docm"):
        return {}

    try:
        detected = analyze_docx_photo_layout(docx_path, valid_section_ids)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Photo layout analysis failed for %s: %s", docx_path.name, exc)
        return {}

    if not detected:
        return {}

    existing = load_tenant_photo_layout(tenant_id)
    existing.update(detected)
    save_tenant_photo_layout(tenant_id, existing)
    logger.info(
        "Photo layout updated for tenant=%s from %s (%d sections)",
        tenant_id,
        docx_path.name,
        len(detected),
    )
    return detected
