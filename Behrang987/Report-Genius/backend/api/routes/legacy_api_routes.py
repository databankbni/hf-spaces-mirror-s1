"""Legacy frontend API compatibility layer backed by v2 services."""

from __future__ import annotations

import logging
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from backend.api import security
from backend.api.deps import get_current_tenant
from backend.compat.legacy_report_generation import run_legacy_generation
from backend.config import settings
from backend.domain import template_discoverer
from backend.domain.notes.extract import extract_notes_from_upload
from backend.domain.notes.routing import route_lines_to_level3_sections
from backend.pipeline.report_assembler import to_docx
from backend.rag.content_similarity import scan_similar_content
from backend.rag.reference_filter import list_registered_reference_document_ids
from backend.rag.store import get_rag_store
from backend.rag.types import TIER_REFERENCE
from backend.storage import document_library, photo_store
from backend.storage.photo_store import ALLOWED_CONTENT_TYPES
from backend.storage.report_session import (
    ReportSession,
    create_report_session,
    get_document,
    list_documents,
    load_session,
    save_session,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["legacy-compat"])

_GROUP_LABELS = {
    "A": "A — About the inspection",
    "B": "B — Overall opinion and summary of ratings",
    "C": "C — About the property",
    "D": "D — Outside the property",
    "E": "E — Inside the property",
    "F": "F — Services",
    "G": "G — Grounds (including shared areas for flats)",
    "H": "H — Issues for your legal advisers",
    "I": "I — Risks",
    "J": "J — Energy matters",
    "K": "K — Surveyor's declaration",
    "L": "L — What to do now",
    "M": "M — Description of the RICS Home Survey - Level 3 service and terms of engagement",
    "N": "N — Typical house diagram",
}


class LegacyGenerateBody(BaseModel):
    template_id: str
    template_ids: list[str] = Field(default_factory=list)
    bullets: list[str] = Field(default_factory=list)
    bullets_by_section: dict[str, list[str]] = Field(default_factory=dict)
    mode: str = "generate"
    interference_level: str | None = None
    retrieval_level: str = "paragraph"
    force_regenerate: bool = True
    strict_uploaded_only: bool = False
    reference_document_ids: list[str] = Field(default_factory=list)
    draft_paragraph: str | None = None
    knowledge_source: str = Field(
        default="both",
        description=(
            "both (default) = past reports + standard paragraphs when available, "
            "merge only when both drafts exist; past_report / standard_paragraph "
            "force a single path."
        ),
    )
    property_type: str | None = Field(
        default=None,
        description=(
            "Canonical house|flat when knowledge_source is past_report; "
            "overrides the session value for retrieval scoping."
        ),
    )
    property_type: str | None = Field(
        default=None,
        description=(
            "Canonical house|flat when knowledge_source is past_report; "
            "overrides the session value for retrieval scoping."
        ),
    )
    structure_mode: str | None = Field(
        default=None,
        description=(
            "rics | content. Overrides the session's structure mode for this run; "
            "defaults to the session value when omitted."
        ),
    )


class BatchStatusBody(BaseModel):
    document_ids: list[str] = Field(default_factory=list)


class RouteNotesBody(BaseModel):
    lines: list[str] = Field(
        default_factory=list, description="Raw note lines to route into L3 sections."
    )
    structure_mode: str = Field(
        default="rics",
        description="rics = RICS L3 section buckets; content = topic buckets.",
    )


class NoteIntakeBody(BaseModel):
    notes: str = Field(
        default="",
        description="Raw dictated site notes to tidy into content-mode sub-topics.",
    )
    property_type: str = Field(
        default="",
        description=(
            "house | flat — which schema to file against. Empty or unrecognised "
            "means house, matching the generate screen's default."
        ),
    )


class NoteQualityItem(BaseModel):
    code: str = Field(description="Review sub-topic id, e.g. chimney_stacks.")
    notes: str = Field(default="", description="Notes filed under that sub-topic.")


class NoteQualityBody(BaseModel):
    items: list[NoteQualityItem] = Field(
        default_factory=list,
        description="Sub-topics to grade against the practice's note-quality rubric.",
    )


class SurveyClassifyBody(BaseModel):
    document_ids: list[str] = Field(default_factory=list)
    force_refresh_corpus: bool = False


class SurveyApplyBody(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)


class PhotoAiSelectionBody(BaseModel):
    photo_ids: list[str] = Field(default_factory=list)


class SimilarContentBody(BaseModel):
    text: str = ""
    section_code: str | None = None
    peer_sections: dict[str, str] = Field(default_factory=dict)
    limit: int = 8
    min_relevance_percent: float = 28.0
    exclude_document_ids: list[str] = Field(default_factory=list)


class SectionTextPatch(BaseModel):
    text: str


def _section_group(code: str) -> str:
    code = (code or "").strip().upper()
    if len(code) == 1:
        return code
    return code[0] if code else "A"


def _resolve_tenant_token(
    authorization: str = Header(default=""),
    access_token: str = Query(default=""),
) -> str:
    token = ""
    if authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    elif access_token.strip():
        token = access_token.strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    payload = security.decode_token(token)
    tenant_id = payload.get("sub")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Token missing subject")
    return tenant_id


def _require_session(tenant_id: str, report_id: str) -> ReportSession:
    session = load_session(tenant_id, report_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return session


def _legacy_photo_url(report_id: str, section_id: str, photo_id: str) -> str:
    return f"/reports/{report_id}/sections/{section_id}/photos/{photo_id}"


def _photo_rows(tenant_id: str, session: ReportSession, section_id: str) -> list[dict]:
    rows = photo_store.list_section_photos(tenant_id, session.draft_id, section_id)
    return [
        {
            "photo_id": p.id,
            "original_filename": p.filename,
            "url": _legacy_photo_url(session.report_id, section_id, p.id),
            "selected_for_ai": p.selected_for_ai,
        }
        for p in rows
    ]


async def _run_generation(
    tenant_id: str, report_id: str, body: LegacyGenerateBody
) -> None:
    """Run blocking RAG + LLM generation off the async event loop."""
    await run_in_threadpool(run_legacy_generation, tenant_id, report_id, body)


def _ingest_upload_file(
    tenant_id: str,
    tmp_path: Path,
    original_filename: str,
    *,
    property_type: str,
) -> document_library.IngestRegisterResult:
    return document_library.ingest_and_register(
        tenant_id,
        tmp_path,
        original_filename=original_filename,
        property_type=property_type,
    )


def _upload_item_from_result(
    outcome: document_library.IngestRegisterResult,
    *,
    filename: str | None = None,
) -> dict:
    doc = outcome.document
    if outcome.action == "retagged":
        status = "retagged"
        message = (
            f"Already indexed — tagged as {doc.property_type} "
            f"({outcome.chunks_retagged} chunk(s) updated, no re-embed)."
        )
    elif outcome.action == "unchanged":
        status = "complete"
        tagged = f" (property_type={doc.property_type})" if doc.property_type else ""
        message = f"Already indexed{tagged}; skipped re-ingest."
    else:
        status = "complete"
        message = f"Ingested {doc.ingested_chunks} reference chunks."
    return {
        "document_id": doc.document_id,
        "filename": filename if filename is not None else doc.filename,
        "status": status,
        "property_type": doc.property_type,
        "action": outcome.action,
        "chunks_retagged": outcome.chunks_retagged,
        "message": message,
    }


# ── Upload & documents ───────────────────────────────────────────────────────


@router.post("/upload/batch", status_code=status.HTTP_201_CREATED)
async def upload_batch(
    files: list[UploadFile] = File(...),
    property_type: str = Form(...),
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    from backend.domain.property_type import PropertyTypeError, normalize_property_type
    from backend.ingest.zip_extract import extract_reference_documents

    try:
        canonical_pt = normalize_property_type(property_type)
    except PropertyTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    allowed_ext = {".pdf", ".docx", ".docm", ".doc", ".zip"}
    items: list[dict] = []
    accepted = 0
    rejected = 0

    for upload in files:
        suffix = Path(upload.filename or "").suffix.lower()
        if suffix not in allowed_ext:
            rejected += 1
            items.append(
                {
                    "document_id": None,
                    "filename": upload.filename,
                    "status": "rejected",
                    "message": f"Unsupported type {suffix}. Use PDF, Word, or ZIP.",
                }
            )
            continue

        upload_tmp_root = settings.data_dir_path / "tmp" / "uploads"
        from backend.utils.runtime_paths import ensure_data_drive_runtime_dirs

        ensure_data_drive_runtime_dirs()
        upload_tmp_root.mkdir(parents=True, exist_ok=True)
        tmp_dir = Path(tempfile.mkdtemp(prefix="v2_batch_", dir=str(upload_tmp_root)))
        safe_name = Path(upload.filename or f"upload{suffix}").name
        tmp_path = tmp_dir / safe_name
        try:
            content = await upload.read()
            if not content:
                raise ValueError("Empty upload body")
            tmp_path.write_bytes(content)

            if suffix == ".zip":
                extract_dir = tmp_dir / "extracted"
                extracted = extract_reference_documents(tmp_path, extract_dir)
                if not extracted:
                    rejected += 1
                    items.append(
                        {
                            "document_id": None,
                            "filename": upload.filename,
                            "status": "rejected",
                            "message": "ZIP contained no supported PDF or Word files.",
                        }
                    )
                    continue
                for _inner, extracted_path in extracted:
                    outcome = _ingest_upload_file(
                        tenant_id,
                        extracted_path,
                        extracted_path.name,
                        property_type=canonical_pt,
                    )
                    accepted += 1
                    items.append(_upload_item_from_result(outcome))
            else:
                if tmp_path.stat().st_size > settings.max_single_upload_bytes:
                    rejected += 1
                    items.append(
                        {
                            "document_id": None,
                            "filename": upload.filename,
                            "status": "rejected",
                            "message": f"File exceeds max size ({settings.max_single_upload_bytes} bytes).",
                        }
                    )
                    continue
                outcome = _ingest_upload_file(
                    tenant_id,
                    tmp_path,
                    upload.filename or tmp_path.name,
                    property_type=canonical_pt,
                )
                accepted += 1
                items.append(
                    _upload_item_from_result(
                        outcome, filename=upload.filename
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Batch upload failed for %s", upload.filename)
            rejected += 1
            items.append(
                {
                    "document_id": None,
                    "filename": upload.filename,
                    "status": "failed",
                    "message": str(exc),
                }
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return {
        "accepted": accepted,
        "rejected": rejected,
        "message": f"{accepted} file(s) indexed as past-report reference.",
        "items": items,
    }


@router.post("/documents/batch-status")
def batch_status(
    body: BatchStatusBody,
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    docs = list_documents(tenant_id)
    items = []
    complete = failed = pending = processing = 0
    for doc_id in body.document_ids:
        row = docs.get(doc_id)
        if row is None:
            failed += 1
            items.append(
                {
                    "document_id": doc_id,
                    "status": "not_found",
                    "filename": "",
                    "error": "Unknown document id",
                }
            )
            continue
        st = row.status
        if st in ("complete", "chunked"):
            complete += 1
            # Poll clients stop on "complete"; chunk-only ingest is finished work.
            poll_status = "complete"
        elif st == "failed":
            failed += 1
            poll_status = st
        elif st == "processing":
            processing += 1
            poll_status = st
        else:
            pending += 1
            poll_status = st
        items.append(
            {
                "document_id": doc_id,
                "status": poll_status,
                "filename": row.filename,
                "error": row.error,
            }
        )
    return {
        "pending": pending,
        "processing": processing,
        "complete": complete,
        "failed": failed,
        "items": items,
    }


@router.get("/documents/tenant-chunk-summary")
def tenant_chunk_summary(tenant_id: str = Depends(get_current_tenant)) -> dict:
    store = get_rag_store()
    indexed = store.count(tenant_id, TIER_REFERENCE)
    chunk_only = store.count_chunks_only(tenant_id, TIER_REFERENCE)
    embed_on = bool(settings.ingest_embed_enabled)
    return {
        "tenant_id": tenant_id,
        "indexed_chunk_count": indexed,
        "chunk_only_count": chunk_only,
        # UI gate: FAISS when embedding on; otherwise chunk-sidecar is enough.
        "retrievable_chunk_count": indexed if embed_on else chunk_only,
        "ingest_embed_enabled": embed_on,
    }


@router.get("/documents/extracted-chunks")
def get_extracted_chunks_manifest(tenant_id: str = Depends(get_current_tenant)) -> dict:
    """Per-upload chunk manifest (filename -> metadata + extracted chunks)."""
    from backend.storage import document_library

    path = document_library.chunks_manifest_path(tenant_id)
    if not path.is_file():
        document_library.rebuild_chunks_manifest(tenant_id)
    if not path.is_file():
        return {"tenant_id": tenant_id, "files": {}, "manifest_path": str(path)}
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "tenant_id": tenant_id,
        "manifest_path": str(path),
        "file_count": len(data),
        "files": data,
    }


@router.get("/reports/{report_id}/retrieval-manifest")
def get_retrieval_manifest(
    report_id: str, tenant_id: str = Depends(get_current_tenant)
) -> dict:
    """Per-section retrieval record: messy notes + chunks used to rewrite each section."""
    session = _require_session(tenant_id, report_id)
    from backend.storage import retrieval_manifest

    path = retrieval_manifest.retrieval_manifest_path(tenant_id, session.draft_id)
    if not path.is_file():
        return {
            "report_id": report_id,
            "draft_id": session.draft_id,
            "manifest_path": str(path),
            "sections": {},
        }
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "report_id": report_id,
        "draft_id": session.draft_id,
        "manifest_path": str(path),
        "section_count": len(data.get("sections", {})),
        "sections": data.get("sections", {}),
    }


@router.get("/reports/{report_id}/evaluation")
def get_evaluation_manifest(
    report_id: str, tenant_id: str = Depends(get_current_tenant)
) -> dict:
    """Per-report advisory evaluation (Approach 2 coverage + optional Approach 3)."""
    session = _require_session(tenant_id, report_id)
    from backend.evaluation import evaluation_manifest_path, load_evaluation_manifest

    path = evaluation_manifest_path(tenant_id, session.draft_id)
    data = load_evaluation_manifest(tenant_id, session.draft_id)
    if data is None:
        return {
            "report_id": report_id,
            "draft_id": session.draft_id,
            "manifest_path": str(path),
            "evaluation": None,
            "sections": {},
        }
    return {
        "report_id": report_id,
        "draft_id": session.draft_id,
        "manifest_path": str(path),
        "section_count": len(data.get("sections", {})),
        "evaluation": data.get("evaluation"),
        "sections": data.get("sections", {}),
    }


@router.post("/documents/survey-level/classify")
def survey_level_classify(
    body: SurveyClassifyBody,
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    docs = list_documents(tenant_id)
    items = []
    for doc_id in body.document_ids:
        row = docs.get(doc_id)
        items.append(
            {
                "document_id": doc_id,
                "filename": row.filename if row else doc_id,
                "predicted_survey_level": 3,
                "confidence": 0.85,
                "rationale": "Inferred from template schema (v2 reference mapping).",
            }
        )
    return {"items": items, "corpus_labelled_files": len(items)}


@router.post("/documents/survey-level/apply")
def survey_level_apply(
    body: SurveyApplyBody,
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    return {"updated": body.items}


# ── Reports ──────────────────────────────────────────────────────────────────


@router.post("/reports")
def create_report(
    document_id: str | None = None,
    survey_level: int = 3,
    confirm_tier_mismatch: bool = False,
    structure_mode: str = "rics",
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    """Create a report session.

    Past-report ``document_id`` is optional. Users may work from standard-paragraph
    memory only (Word upload / Add to Memory) without uploading reference reports.

    ``structure_mode`` selects the report structure: ``rics`` (RICS Level 3) or
    ``content`` (content-based topic mode).
    """
    del confirm_tier_mismatch  # retained for UI compat; no longer blocks create
    from backend.rag.types import TIER_REFERENCE, TIER_STANDARD_PARAGRAPHS

    mode = (structure_mode or "rics").strip().lower()
    if mode == "content" and not settings.content_mode_enabled:
        raise HTTPException(status_code=400, detail="Content mode is disabled.")

    template_discoverer.ensure_canonical_schema(tenant_id)
    store = get_rag_store()

    primary = (document_id or "").strip()
    if primary and not get_document(tenant_id, primary):
        raise HTTPException(status_code=404, detail="Document not found")

    registered_ids = list_registered_reference_document_ids(tenant_id)
    all_doc_ids = sorted(set(registered_ids) | ({primary} if primary else set()))
    session = create_report_session(
        tenant_id,
        survey_level=max(1, min(3, survey_level)),
        primary_document_id=primary,
        document_ids=all_doc_ids,
        structure_mode=mode,
    )
    out = {
        "report_id": session.report_id,
        "status": "ready",
        "message": "Report session created.",
        "structure_mode": session.structure_mode,
        "reference_chunk_count": store.count(tenant_id, TIER_REFERENCE),
        "standard_paragraphs_chunk_count": store.count(
            tenant_id, TIER_STANDARD_PARAGRAPHS
        ),
        "has_past_reports": bool(all_doc_ids),
    }
    if mode == "content":
        # Content mode matches notes to chunks by topic id, so both sides must have
        # been tagged under the same taxonomy. Say so up front rather than letting
        # retrieval come back empty for no visible reason.
        warning = _content_tag_warning(
            tenant_id, store, (TIER_REFERENCE, TIER_STANDARD_PARAGRAPHS)
        )
        if warning:
            out["content_tag_warning"] = warning
    return out


def _content_tag_warning(tenant_id: str, store, tiers) -> str:
    """Warn when a tenant's chunks predate the live content taxonomy."""
    from backend.content_based.taxonomy import CONTENT_TAXONOMY_VERSION

    stale = untagged = 0
    for tier in tiers:
        if store.count(tenant_id, tier) == 0:
            continue
        status = store.taxonomy_version_status(tenant_id, tier)
        stale += int(status["stale"])
        untagged += int(status["untagged"])
    if not (stale or untagged):
        return ""
    parts = []
    if untagged:
        parts.append(f"{untagged} untagged")
    if stale:
        parts.append(f"{stale} tagged under an older taxonomy")
    return (
        f"{' and '.join(parts)} chunk(s) will not be retrieved in content mode. "
        f"Run `python -m backend.scripts.backfill_topics {tenant_id}` to re-tag "
        f"against {CONTENT_TAXONOMY_VERSION}."
    )


def _content_catalog(survey_level: int, property_type: str = "") -> dict:
    """Sub-topic catalog for content mode (code=sub-topic, group=review group).

    Serves the review taxonomy, not the v2 knowledge taxonomy: this is the list the
    note-quality rubric is written over, so the chips the surveyor sees and the
    buckets they are graded against are the same thing.

    Scoped by property type. House and flat currently show the same 41 sub-topics,
    so ``property_type`` changes nothing today; it is on the wire so a client is
    already asking the right question when the two schemas do diverge. The
    resolved type is echoed back rather than the raw input.
    """
    from backend.content_based import review_taxonomy

    resolved = review_taxonomy.resolve_property_type(property_type)
    return {
        "survey_level": max(1, min(3, survey_level)),
        "sections": review_taxonomy.catalog_sections(resolved),
        "group_labels": review_taxonomy.group_labels_for(resolved),
        "structure_mode": "content",
        "property_type": resolved,
    }


@router.get("/templates/catalog")
def template_catalog(
    survey_level: int = 3,
    structure_mode: str = "rics",
    property_type: str = "",
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    if (structure_mode or "rics").strip().lower() == "content":
        return _content_catalog(survey_level, property_type)

    schema = template_discoverer.ensure_canonical_schema(tenant_id)
    sections = []
    for sec in schema.ordered_sections():
        grp = _section_group(sec.id)
        hint = ", ".join(sec.keywords[:6]) if sec.keywords else sec.title
        sections.append(
            {
                "code": sec.id,
                "group": grp,
                "title": sec.title,
                "hint": hint,
            }
        )
    labels = {
        k: v for k, v in _GROUP_LABELS.items() if any(s["group"] == k for s in sections)
    }
    return {
        "survey_level": max(1, min(3, survey_level)),
        "sections": sections,
        "group_labels": labels,
        "structure_mode": "rics",
    }


@router.get("/reports/{report_id}/photo-policy")
def photo_policy(report_id: str, tenant_id: str = Depends(get_current_tenant)) -> dict:
    session = _require_session(tenant_id, report_id)
    schema = template_discoverer.ensure_canonical_schema(tenant_id)
    sections = []
    for sec in schema.ordered_sections():
        sections.append(
            {"code": sec.id, "policy": "allowed", "reason": "Photos supported in v2."}
        )
    return {
        "report_id": session.report_id,
        "sections": sections,
        "photo_limits": {
            "max_photos_per_section": settings.max_section_photos_per_section,
            "max_photos_for_ai": settings.max_section_photos_for_ai,
        },
    }


@router.get("/reports/{report_id}/sections/{section_code}/photos")
def list_legacy_photos(
    report_id: str,
    section_code: str,
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    session = _require_session(tenant_id, report_id)
    photos = _photo_rows(tenant_id, session, section_code)
    selected = sum(1 for p in photos if p.get("selected_for_ai"))
    return {
        "report_id": report_id,
        "section_code": section_code,
        "photos": photos,
        "max_photos_per_section": settings.max_section_photos_per_section,
        "max_photos_for_ai": settings.max_section_photos_for_ai,
        "selected_for_ai_count": selected,
    }


@router.post("/reports/{report_id}/sections/{section_code}/photos", status_code=201)
async def upload_legacy_photos(
    report_id: str,
    section_code: str,
    files: list[UploadFile] = File(...),
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    session = _require_session(tenant_id, report_id)
    saved = []
    for upload in files:
        ct = (upload.content_type or "image/jpeg").lower().split(";")[0].strip()
        if ct not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=400, detail=f"Unsupported type: {upload.content_type}"
            )
        data = await upload.read()
        row = photo_store.add_section_photo(
            tenant_id,
            session.draft_id,
            section_code,
            data,
            content_type=ct,
            original_filename=upload.filename or "",
        )
        saved.append(
            {
                "photo_id": row.id,
                "original_filename": row.filename,
            }
        )
    return {
        "report_id": report_id,
        "section_code": section_code,
        "saved": saved,
        "photos": _photo_rows(tenant_id, session, section_code),
    }


@router.put("/reports/{report_id}/sections/{section_code}/photos/ai-selection")
def legacy_photo_ai_selection(
    report_id: str,
    section_code: str,
    body: PhotoAiSelectionBody,
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    session = _require_session(tenant_id, report_id)
    try:
        photo_store.set_ai_selection(
            tenant_id, session.draft_id, section_code, body.photo_ids
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "report_id": report_id,
        "section_code": section_code,
        "photos": _photo_rows(tenant_id, session, section_code),
    }


@router.delete("/reports/{report_id}/sections/{section_code}/photos/{photo_id}")
def delete_legacy_photo(
    report_id: str,
    section_code: str,
    photo_id: str,
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    session = _require_session(tenant_id, report_id)
    if not photo_store.delete_section_photo(
        tenant_id, session.draft_id, section_code, photo_id
    ):
        raise HTTPException(status_code=404, detail="Photo not found")
    return {"deleted": True, "photo_id": photo_id}


@router.get("/reports/{report_id}/sections/{section_code}/photos/{photo_id}")
def get_legacy_photo(
    report_id: str,
    section_code: str,
    photo_id: str,
    tenant_id: str = Depends(_resolve_tenant_token),
) -> Response:
    session = _require_session(tenant_id, report_id)
    rows = photo_store.list_section_photos(tenant_id, session.draft_id, section_code)
    row = next((r for r in rows if r.id == photo_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    path = photo_store.photo_file_path(
        tenant_id,
        session.draft_id,
        section_code,
        photo_id,
        content_type=row.content_type,
    )
    if not path or not path.is_file():
        raise HTTPException(status_code=404, detail="Photo file missing")
    return Response(content=path.read_bytes(), media_type=row.content_type)


@router.post("/reports/{report_id}/generate")
async def generate_report_legacy(
    report_id: str,
    body: LegacyGenerateBody,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    from backend.pipeline.section_mapper import (
        estimate_active_sections_from_generate_body,
    )

    session = _require_session(tenant_id, report_id)
    ks = (body.knowledge_source or "past_report").strip().lower()
    if ks == "past_report":
        from backend.domain.property_type import PropertyTypeError, normalize_property_type

        try:
            session.property_type = normalize_property_type(
                body.property_type or session.property_type
            )
        except PropertyTypeError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
    active = estimate_active_sections_from_generate_body(
        body,
        tenant_id=tenant_id,
        draft_id=session.draft_id,
    )
    total = len(active) if active else 1
    session.status = "generating"
    session.generation_section_total = total
    session.generation_started_at = time.time()
    session.error_message = None
    save_session(session)
    background_tasks.add_task(_run_generation, tenant_id, report_id, body)
    return {
        "report_id": report_id,
        "status": "generating",
        "message": "Generation started (v2 reference mapping).",
    }


@router.get("/reports/{report_id}/status")
def report_status(report_id: str, tenant_id: str = Depends(get_current_tenant)) -> dict:
    session = _require_session(tenant_id, report_id)
    sections_saved = len(session.sections_payload)
    sections_with_text = sum(
        1 for p in session.sections_payload.values() if (p.get("text") or "").strip()
    )
    elapsed = None
    if session.generation_started_at and session.status == "generating":
        elapsed = round(time.time() - session.generation_started_at, 1)
    return {
        "report_id": report_id,
        "status": session.status if session.status != "idle" else "complete",
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "error_message": session.error_message,
        "survey_level": session.survey_level,
        "sections_saved": sections_saved,
        "sections_with_text": sections_with_text,
        "generation_section_total": session.generation_section_total,
        "generation_elapsed_seconds": elapsed,
    }


@router.post("/reports/{report_id}/generation/cancel")
def cancel_generation(
    report_id: str, tenant_id: str = Depends(get_current_tenant)
) -> dict:
    session = _require_session(tenant_id, report_id)
    if session.status == "generating":
        session.status = "failed"
        session.error_message = "Cancelled by user (timeout)."
        save_session(session)
    return {"report_id": report_id, "status": session.status}


@router.get("/reports/{report_id}/sections")
def get_sections(report_id: str, tenant_id: str = Depends(get_current_tenant)) -> dict:
    session = _require_session(tenant_id, report_id)
    return {"report_id": report_id, "sections": session.sections_payload}


@router.patch("/reports/{report_id}/sections/{section_code}")
def patch_section(
    report_id: str,
    section_code: str,
    body: SectionTextPatch,
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    session = _require_session(tenant_id, report_id)
    payload = session.sections_payload.get(
        section_code,
        {
            "text": "",
            "confidence": 0.5,
            "provenance": [],
            "mode": "generate",
        },
    )
    payload["text"] = body.text
    session.sections_payload[section_code] = payload
    save_session(session)
    return payload


@router.get("/reports/{report_id}/export")
def export_report(
    report_id: str,
    format: str = "docx",
    tenant_id: str = Depends(get_current_tenant),
) -> Response:
    if format.lower() != "docx":
        raise HTTPException(status_code=400, detail="Only format=docx is supported.")
    session = _require_session(tenant_id, report_id)
    schema = template_discoverer.ensure_canonical_schema(tenant_id)

    from backend.pipeline.report_assembler import from_sections_payload

    result = from_sections_payload(
        tenant_id,
        schema,
        session.sections_payload,
        property_type=session.property_type,
        tenure=session.tenure,
    )
    from backend.storage.photo_store import draft_section_photo_paths

    photo_paths = draft_section_photo_paths(
        tenant_id, session.draft_id, schema.section_ids()
    )
    data = to_docx(result, schema, section_photo_paths=photo_paths, include_footer=True)
    filename = f"RICS_Report_{report_id[:8]}.docx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Optional stubs (document manager / similarity — off main path) ───────────


@router.get("/documents")
def list_documents_route(
    limit: int = 500,
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    docs = list_documents(tenant_id)
    rows = sorted(docs.values(), key=lambda d: d.filename)[:limit]
    return {
        "documents": [
            {
                "document_id": d.document_id,
                "filename": d.filename,
                "status": d.status,
                "created_at": document_library.document_created_at_iso(d),
                "file_size": d.file_size or None,
                "document_purpose": "reference",
                "property_type": d.property_type or "",
                "error": d.error,
            }
            for d in rows
        ],
        "reingest_running": document_library.is_reingest_running(tenant_id),
        "reingest_progress": document_library.reingest_progress(tenant_id),
    }


@router.delete("/documents/{document_id}")
def delete_document_route(
    document_id: str,
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    session_reports = [
        s for s in _reports_generating_for_document(tenant_id, document_id)
    ]
    if session_reports:
        raise HTTPException(
            status_code=409,
            detail=(
                "A report is still generating from this document. "
                "Wait for it to finish before deleting the source file."
            ),
        )
    try:
        removed = document_library.remove_reference_document(tenant_id, document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc
    return {
        "document_id": document_id,
        "deleted": True,
        "chunks_removed": removed,
    }


@router.post("/documents/delete-batch")
def delete_documents_batch_route(
    body: dict,
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    """Delete many past-report library documents in one request."""
    raw_ids = body.get("document_ids") if isinstance(body, dict) else None
    if not isinstance(raw_ids, list) or not raw_ids:
        raise HTTPException(
            status_code=400,
            detail="document_ids must be a non-empty list",
        )
    skip = {doc_id for doc_id in _all_generating_document_ids(tenant_id)}
    result = document_library.remove_reference_documents(
        tenant_id,
        [str(x) for x in raw_ids],
        skip_document_ids=skip,
    )
    return result


@router.post("/documents/{document_id}/reingest")
def reingest_one_document(
    document_id: str,
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    if _reports_generating_for_document(tenant_id, document_id):
        raise HTTPException(
            status_code=409,
            detail="A report is still generating from this document. Wait before re-ingesting.",
        )
    try:
        result = document_library.schedule_reingest_reference_document(
            tenant_id, document_id
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc
    except FileNotFoundError:
        return {
            "queued": 0,
            "skipped_missing_file": 1,
            "detail": "Source file is no longer on disk; cannot re-ingest.",
        }
    return result


@router.post("/documents/reingest")
def reingest_all_route(tenant_id: str = Depends(get_current_tenant)) -> dict:
    active_doc_ids = {doc_id for doc_id in _all_generating_document_ids(tenant_id)}
    return document_library.schedule_reingest_all_documents(
        tenant_id,
        skip_document_ids=active_doc_ids,
    )


def _reports_dir(tenant_id: str) -> Path:
    from backend.storage.report_session import _reports_dir as rd  # noqa: PLC0415

    return rd(tenant_id)


def _reports_generating_for_document(tenant_id: str, document_id: str) -> list[str]:
    out: list[str] = []
    reports_dir = _reports_dir(tenant_id)
    if not reports_dir.is_dir():
        return out
    import json

    for path in reports_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if data.get("status") != "generating":
            continue
        doc_ids = set(data.get("document_ids") or [])
        if data.get("primary_document_id"):
            doc_ids.add(data["primary_document_id"])
        if document_id in doc_ids:
            out.append(str(data.get("report_id") or path.stem))
    return out


def _all_generating_document_ids(tenant_id: str) -> set[str]:
    ids: set[str] = set()
    reports_dir = _reports_dir(tenant_id)
    if not reports_dir.is_dir():
        return ids
    import json

    for path in reports_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if data.get("status") != "generating":
            continue
        ids.update(data.get("document_ids") or [])
        if data.get("primary_document_id"):
            ids.add(data["primary_document_id"])
    return ids


@router.post("/content/similar")
def content_similar(
    body: SimilarContentBody,
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    return scan_similar_content(
        tenant_id,
        text=body.text,
        section_code=body.section_code,
        peer_sections=body.peer_sections,
        limit=body.limit,
        min_relevance_percent=body.min_relevance_percent,
        exclude_document_ids=body.exclude_document_ids,
    )


@router.post("/content/note-intake")
async def content_note_intake(
    body: NoteIntakeBody,
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    """Stage A: extract and classify a raw note blob into all content-mode chips.

    Each destination receives professionally rewritten British English prose (or
    ``No specific information provided.``). See backend/content_based/intake.py.
    """
    from backend.content_based import intake, stage_dump

    result = await intake.assign_notes(body.notes or "", body.property_type or "")
    payload = {
        "assignments": {
            code: result.assignments[code] for code in result.ordered_codes()
        },
        "unassigned": result.unassigned,
        "discarded": result.discarded,
        "line_count": result.line_count,
        "property_type": result.property_type,
        "assigned_line_count": result.assigned_line_count,
        "method": result.method,
        "llm_available": result.llm_available,
        "unavailable_reason": result.unavailable_reason,
        "unresolved_count": result.unresolved,
    }
    payload["dump_path"] = stage_dump.record_quietly(
        tenant_id,
        stage_a=dict(payload),
        source_notes=body.notes or "",
        llm_io=result.llm_io,
    )
    return payload


@router.post("/content/note-quality")
async def content_note_quality(
    body: NoteQualityBody,
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    """Stage B: grade each sub-topic Green/Yellow/Red against the practice rubric.

    Returns 200 even when the judge is unavailable — an ungraded chip is a much
    better outcome than a surveyor blocked from writing their report.
    """
    from backend.content_based import stage_dump
    from backend.note_quality import GradeItem, grade_subtopics
    from backend.note_quality.rubric import RUBRIC_VERSION

    result = await grade_subtopics(
        [GradeItem(code=item.code, notes=item.notes) for item in body.items]
    )
    payload = {
        "grades": {
            code: grade.model_dump() for code, grade in result.grades.items()
        },
        "not_scored": result.not_scored,
        "tally": result.tally(),
        "judged_count": result.judged_count,
        "call_count": result.call_count,
        "rubric_version": RUBRIC_VERSION,
        "llm_available": result.llm_available,
        "unavailable_reason": result.unavailable_reason,
    }
    payload["dump_path"] = stage_dump.record_quietly(
        tenant_id, stage_b=dict(payload), stage_b_io=result.llm_io
    )
    return payload


@router.post("/route-notes")
async def route_notes_route(body: RouteNotesBody) -> dict:
    """Route raw note lines into section buckets (RICS L3 cascade or topic mode)."""
    lines = [ln.strip() for ln in (body.lines or []) if (ln or "").strip()]
    if (body.structure_mode or "rics").strip().lower() == "content":
        from backend.content_based.router import route_lines_to_topics

        routed, unmatched = route_lines_to_topics(lines)
    else:
        routed, unmatched = route_lines_to_level3_sections(lines)
    return {
        "routed": routed,
        "unmatched": unmatched,
        "line_count": len(lines),
        "routed_line_count": sum(len(v) for v in routed.values()),
    }


@router.post("/extract-notes")
async def extract_notes_route(file: UploadFile = File(...)) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".docx", ".pdf", ".txt"}:
        raise HTTPException(
            status_code=422,
            detail="Unsupported file type. Upload a .docx, .pdf, or .txt notes file.",
        )
    data = await file.read(settings.max_notes_extract_bytes + 1)
    if len(data) > settings.max_notes_extract_bytes:
        raise HTTPException(status_code=413, detail="Notes file too large.")
    try:
        return extract_notes_from_upload(data, file.filename or "unknown")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Failed to parse file: {exc}"
        ) from exc
