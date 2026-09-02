"""Merge-agent orchestrator: drafts in → merged section text out."""

from __future__ import annotations

from backend import config
from backend.llm import openai_client
from backend.merge_agent.models import DualPathDraft, MergeResult
from backend.merge_agent.prompts import build_merge_messages, normalize_prompt_version


def _resolved_model(override: str | None = None) -> str:
    if (override or "").strip():
        return override.strip()
    s = config.settings
    return (s.merge_agent_model or "").strip() or s.mapping_model


def _resolved_max_tokens() -> int:
    s = config.settings
    return int(s.merge_agent_max_tokens or s.max_tokens_mapping)


def _resolved_temperature(override: float | None = None) -> float:
    if override is not None:
        return float(override)
    return float(config.settings.merge_agent_temperature)


def merge_dual_path_drafts(
    draft: DualPathDraft,
    *,
    temperature: float | None = None,
    prompt_version: str | None = None,
    model: str | None = None,
) -> MergeResult:
    """Merge past-report + standard-paragraph drafts for one section.

    Does not regenerate from notes. Soft-fails to the surviving draft when
    only one side has prose. Optional ``temperature`` / ``prompt_version`` /
    ``model`` override settings.
    """
    s = config.settings
    past = (draft.past_report_draft or "").strip()
    sp = (draft.standard_paragraph_draft or "").strip()
    sid = (draft.section_id or "").strip().upper() or "—"
    title = (draft.section_title or "").strip() or sid
    version = normalize_prompt_version(
        prompt_version or s.merge_agent_prompt_version
    )
    resolved_model = _resolved_model(model)

    if not past and not sp:
        return MergeResult(
            section_id=sid,
            section_title=title,
            merged_text="",
            past_report_draft=past,
            standard_paragraph_draft=sp,
            past_report_source=draft.past_report_source,
            standard_paragraph_source=draft.standard_paragraph_source,
            model=resolved_model,
            meta={"status": "EMPTY", "prompt_version": version},
        )
    if past and not sp:
        return MergeResult(
            section_id=sid,
            section_title=title,
            merged_text=past,
            past_report_draft=past,
            standard_paragraph_draft=sp,
            past_report_source=draft.past_report_source,
            standard_paragraph_source=draft.standard_paragraph_source,
            model=resolved_model,
            meta={"status": "PAST_ONLY", "prompt_version": version},
        )
    if sp and not past:
        return MergeResult(
            section_id=sid,
            section_title=title,
            merged_text=sp,
            past_report_draft=past,
            standard_paragraph_draft=sp,
            past_report_source=draft.past_report_source,
            standard_paragraph_source=draft.standard_paragraph_source,
            model=resolved_model,
            meta={"status": "SP_ONLY", "prompt_version": version},
        )

    messages = build_merge_messages(
        section_id=sid,
        section_title=title,
        past_report_draft=past,
        standard_paragraph_draft=sp,
        inspection_notes=draft.inspection_notes or "",
        prompt_version=version,
    )
    temp = _resolved_temperature(temperature)
    effort = (s.merge_agent_reasoning_effort or "none")
    text, usage = openai_client.chat_text_with_usage(
        messages,
        model=resolved_model,
        temperature=temp,
        max_tokens=_resolved_max_tokens(),
        call_label=f"dual_path_merge_{version}",
        reasoning_effort=effort,
    )
    return MergeResult(
        section_id=sid,
        section_title=title,
        merged_text=(text or "").strip(),
        llm_usage=usage,
        past_report_draft=past,
        standard_paragraph_draft=sp,
        past_report_source=draft.past_report_source,
        standard_paragraph_source=draft.standard_paragraph_source,
        model=resolved_model,
        meta={
            "status": "MERGED",
            "temperature": temp,
            "reasoning_effort": effort,
            "prompt_version": version,
        },
    )
