"""Report generation: JSON preview and DOCX export from surveyor notes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import AliasChoices, BaseModel, Field, model_validator

from backend.api.deps import get_current_tenant
from backend.domain import template_discoverer
from backend.domain.interference import resolve_generation_mode
from backend.domain.section_scope import (
    NOTES_PARENT_IDS,
    PARENT_INTRO_SECTION_IDS,
    PARENT_STORAGE_PARENT_IDS,
)
from backend.prompts.notes_guidance import NOTES_INPUT_GUIDANCE
from backend.models.schema import TemplateSchema
from backend.pii import scrubber as pii_scrubber
from backend.pipeline import report_assembler, section_mapper
from backend.storage.photo_store import draft_section_photo_paths

router = APIRouter(prefix="/api/report", tags=["report"])

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class GenerateRequest(BaseModel):
    raw_notes: str = Field(
        default="",
        description="Surveyor field notes (any format). May be empty when using photos only.",
    )
    property_type: str = Field(
        min_length=1,
        description="Generic property descriptor, e.g. semi-detached house.",
    )
    tenure: str = Field(min_length=1, description="e.g. freehold or leasehold.")
    title: str = Field(default="Survey Report", max_length=200)
    include_footer: bool = Field(default=False)
    report_draft_id: str | None = Field(
        default=None,
        description=(
            "Draft id from POST /api/report/drafts. When set, selected section photos "
            "(max 2 per section) are analyzed and mapped into the relevant sections."
        ),
    )
    survey_level: int = Field(
        default=3,
        ge=1,
        le=3,
        description=(
            "RICS survey product tier (1/2/3). When mode is omitted, "
            "Level 1/2→assist, Level 3→expert."
        ),
    )
    interference_level: (
        Literal["assist", "expert", "minimum", "medium", "maximum"] | None
    ) = Field(
        default=None,
        alias="mode",
        validation_alias=AliasChoices("mode", "interference_level"),
        description=(
            "Generation mode. 'assist' (default): preserve the surveyor's writing — "
            "weave notes onto the retrieved baseline plus a grammar/flow pass, no new "
            "facts. 'expert': assist plus the enrichment behaviours enabled in "
            "expert_preferences. Legacy values minimum/medium→assist, maximum→expert."
        ),
    )
    expert_preferences: dict[str, bool] | None = Field(
        default=None,
        description=(
            "Expert-mode enrichment flags (ignored under assist): explain_causes, "
            "implications, maintenance_advice, building_regs, health_safety, "
            "planning_legal."
        ),
    )
    knowledge_source: Literal["both", "past_report", "standard_paragraph"] = Field(
        default="both",
        description=(
            "Knowledge path(s) for generation. 'both' (default): use past reports "
            "and standard paragraphs when each is available; merge only when both "
            "produce a draft for the section. 'past_report' / 'standard_paragraph' "
            "force a single path (falls back to the other if the chosen index is empty)."
        ),
    )

    @model_validator(mode="after")
    def notes_or_draft(self) -> GenerateRequest:
        if not self.raw_notes.strip() and not self.report_draft_id:
            raise ValueError("raw_notes or report_draft_id is required")
        return self

    @model_validator(mode="after")
    def canonical_property_type_for_past_report(self) -> GenerateRequest:
        ks = (self.knowledge_source or "both").strip().lower()
        if ks not in ("past_report", "both"):
            return self
        from backend.domain.property_type import PropertyTypeError, normalize_property_type

        try:
            self.property_type = normalize_property_type(self.property_type)
        except PropertyTypeError as exc:
            raise ValueError(str(exc)) from exc
        return self


def _require_generation_ready(
    tenant_id: str,
    mode: str,
    *,
    knowledge_source: str = "both",
) -> TemplateSchema:
    from backend.pipeline.knowledge_source import (
        resolve_knowledge_source,
        tenant_has_past_reports,
        tenant_has_standard_paragraphs,
    )

    schema = template_discoverer.ensure_canonical_schema(tenant_id)
    has_past = tenant_has_past_reports(tenant_id)
    has_sp = tenant_has_standard_paragraphs(tenant_id)
    if not has_past and not has_sp:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No past reports or standard paragraphs have been ingested. "
                "Upload reference reports and/or a standard-paragraph Word file "
                f"before {mode}-mode generation."
            ),
        )
    ks = resolve_knowledge_source(tenant_id, knowledge_source)
    if ks == "past_report" and not has_past:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No past reports have been ingested. Upload reference reports "
                f"for {mode}-mode mapping."
            ),
        )
    if ks == "standard_paragraph" and not has_sp:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No standard paragraphs have been ingested. Upload a Word file "
                "before standard_paragraph generation."
            ),
        )
    return schema


@router.get("/notes-guidance")
def notes_guidance() -> dict:
    """Notes-input contract for the UI: which sections take notes, and how."""
    return {
        "guidance": NOTES_INPUT_GUIDANCE,
        "notes_sections": sorted(NOTES_PARENT_IDS | PARENT_INTRO_SECTION_IDS),
        "scaffold_only_sections": sorted(PARENT_STORAGE_PARENT_IDS),
    }


@router.post("/preview")
def preview(
    req: GenerateRequest,
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    mode = resolve_generation_mode(req.interference_level, req.survey_level)
    schema = _require_generation_ready(
        tenant_id, mode, knowledge_source=req.knowledge_source
    )
    result = section_mapper.generate_report(
        tenant_id,
        req.raw_notes,
        property_type=req.property_type,
        tenure=req.tenure,
        interference_level=mode,
        survey_level=req.survey_level,
        report_draft_id=req.report_draft_id,
        expert_preferences=req.expert_preferences,
        knowledge_source=req.knowledge_source,
    )
    if req.report_draft_id:
        from backend.storage.generation_run_export import export_ui_generation_run

        export_ui_generation_run(
            tenant_id=tenant_id,
            draft_id=req.report_draft_id,
            property_type=req.property_type,
            knowledge_source=req.knowledge_source,
            interference_level=mode,
            raw_notes=req.raw_notes,
            sections=list(result.sections or []),
        )
    return report_assembler.to_preview(result, schema)


@router.post("/generate")
def generate(
    req: GenerateRequest,
    tenant_id: str = Depends(get_current_tenant),
) -> Response:
    mode = resolve_generation_mode(req.interference_level, req.survey_level)
    schema = _require_generation_ready(
        tenant_id, mode, knowledge_source=req.knowledge_source
    )
    result = section_mapper.generate_report(
        tenant_id,
        req.raw_notes,
        property_type=req.property_type,
        tenure=req.tenure,
        interference_level=mode,
        survey_level=req.survey_level,
        report_draft_id=req.report_draft_id,
        expert_preferences=req.expert_preferences,
        knowledge_source=req.knowledge_source,
    )
    if req.report_draft_id:
        from backend.storage.generation_run_export import export_ui_generation_run

        export_ui_generation_run(
            tenant_id=tenant_id,
            draft_id=req.report_draft_id,
            property_type=req.property_type,
            knowledge_source=req.knowledge_source,
            interference_level=mode,
            raw_notes=req.raw_notes,
            sections=list(result.sections or []),
        )
    section_photos = draft_section_photo_paths(
        tenant_id,
        req.report_draft_id,
        schema.section_ids(),
    )
    try:
        data = report_assembler.to_docx(
            result,
            schema,
            title=req.title,
            include_footer=req.include_footer,
            section_photo_paths=section_photos,
        )
    except pii_scrubber.PiiDetectedError:
        for s in result.sections:
            s.text = pii_scrubber.scrub(s.text).text
        result.unassigned_text = pii_scrubber.scrub(result.unassigned_text).text
        data = report_assembler.to_docx(
            result,
            schema,
            title=req.title,
            include_footer=req.include_footer,
            section_photo_paths=section_photos,
        )
    return Response(
        content=data,
        media_type=_DOCX_MIME,
        headers={
            "Content-Disposition": 'attachment; filename="survey_report_draft.docx"'
        },
    )
