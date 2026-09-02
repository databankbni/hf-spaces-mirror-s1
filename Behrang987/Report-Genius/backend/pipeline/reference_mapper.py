"""In-place fact update on REFERENCE-tier baseline text — no scratch generation."""

from __future__ import annotations

import logging

from backend.config import settings
from backend.domain.interference import ExpertPreferences, GenerationMode
from backend.llm import openai_client
from backend.models.schema import TemplateSchema
from backend.pipeline.composition_output import (
    accept_narrative_section_output,
    sanitize_section_prose,
)
from backend.pipeline.condition_rating_filter import apply_condition_rating_policy
from backend.pipeline.paragraph_merge import merge_observations_into_paragraph
from backend.prompts.mapping_prompt import (
    ASSIST_WRITING_QUALITY_RULES,
    MAPPING_SYSTEM_BASE_MAXIMUM,
    MAPPING_SYSTEM_BASE_MEDIUM,
    MAPPING_SYSTEM_BASE_MINIMUM,
    MAPPING_USER_TEMPLATE,
    PRIORITY_LOCK,
    RATING_HINT_TEMPLATE,
    RICS_DOMAIN_RULES,
    SCAFFOLD_USE_POLICY,
    _observations_bulleted,
)
from backend.prompts.prompt_few_shot_examples import MAPPING_COT_PROTOCOL
from backend.prompts.prompt_message_assembly import append_cot_to_system
from backend.rag.retriever import InterferenceLevel

logger = logging.getLogger(__name__)

# Relocated verbatim to backend/prompts/mapping_prompt.py (test-exempt). Aliased
# here to preserve the existing internal/private reference and import surface.
_RICS_DOMAIN_RULES = RICS_DOMAIN_RULES


def select_mapping_prompt(interference_level: str) -> str:
    """Return the tier-specific mapping system prompt base for the given level."""
    level = (interference_level or "maximum").strip().lower()
    if level == "minimum":
        return MAPPING_SYSTEM_BASE_MINIMUM
    if level == "medium":
        return MAPPING_SYSTEM_BASE_MEDIUM
    return MAPPING_SYSTEM_BASE_MAXIMUM


def _normalize_interference_level(
    interference_level: str | InterferenceLevel | None,
) -> InterferenceLevel:
    """Map caller input to a supported composition tier; default maximum."""
    raw = str(interference_level or "").strip().lower()
    if raw in ("minimum", "medium", "maximum"):
        return raw  # type: ignore[return-value]
    # New mode names accepted for compatibility with mode-aware callers.
    if raw == "assist":
        return "minimum"
    if raw == "expert":
        return "maximum"
    return "maximum"


def _mode_system_base(
    mode: GenerationMode,
    preferences: ExpertPreferences,
) -> str:
    """Assist/Expert role base (minimum weave only).

    Writing-quality polish is appended *after* PRIORITY / SCAFFOLD_USE_POLICY in
    ``compose_mapping_system_prompt`` so facts-lock outranks style. Expert
    preference enrichment remains disabled; ``mode`` / ``preferences`` stay for
    callers and auditor relaxations elsewhere.
    """
    _ = (mode, preferences)
    return MAPPING_SYSTEM_BASE_MINIMUM.strip()


def compose_mapping_system_prompt(
    interference_level: str | InterferenceLevel | None,
    *,
    mode: GenerationMode | None = None,
    preferences: ExpertPreferences | None = None,
    style_block: str = "",
) -> str:
    """Full mapping system prompt.

    Uses the revised Past Reports system prompt (SP-adapted process + QC) from
    ``past_report_mapping_prompt``. Optional ``style_block`` may carry
    ``<PRIMARY_SCAFFOLD_STYLE_CUES>`` derived from PAST REPORT 1. The mined
    ``<USER_STYLE_PROFILE>`` JSON cache is not injected on this path — scaffolds
    already supply voice. Legacy tier bases / PRIORITY_LOCK blocks remain in
    ``mapping_prompt.py`` for tests and rollback but are not injected live.
    """
    _ = (interference_level, mode, preferences)
    from backend.prompts.past_report_mapping_prompt import PAST_REPORT_MAPPING_SYSTEM

    parts = [PAST_REPORT_MAPPING_SYSTEM.strip()]
    if style_block.strip():
        parts.append(style_block.strip())
    return "\n\n".join(parts)


def build_interference_messages(
    interference_level: str | InterferenceLevel | None,
    *,
    observations: list[str],
    baseline: str,
    schema: TemplateSchema,
    section_id: str = "",
    section_title: str = "",
    rating_value: str | None = None,
    extra_references: list[str] | None = None,
    reference_blocks: list[str] | None = None,
    add_to_memory_blocks: list[str] | None = None,
    mode: GenerationMode | None = None,
    preferences: ExpertPreferences | None = None,
    tenant_id: str = "",
) -> list[dict[str, str]]:
    """Select the prompt builder for the requested mode / interference level.

    When ``reference_blocks`` is supplied, each past report's version of the
    subsection is rendered as its own labelled scaffold (never merged). Otherwise the
    single ``baseline`` string is used. Voice comes from those scaffolds (plus
    optional ``<PRIMARY_SCAFFOLD_STYLE_CUES>`` from report 1). The mined
    ``style_profile.json`` / ``<USER_STYLE_PROFILE>`` block is not injected —
    it duplicated the same past-report signal.
    """
    _ = tenant_id  # retained for call-site compatibility / future hooks
    from backend.prompts.mapping_prompt import (
        render_add_to_memory_block,
        render_reference_scaffolds,
    )

    level = _normalize_interference_level(interference_level)
    primary_scaffold = ""
    if reference_blocks:
        clean_blocks = [b.strip() for b in reference_blocks if b and b.strip()]
        primary_scaffold = clean_blocks[0] if clean_blocks else ""
        baseline_text = render_reference_scaffolds(reference_blocks)
    else:
        baseline_text = baseline.strip()
        primary_scaffold = baseline_text
    if extra_references:
        extras = "\n\n".join(item.strip() for item in extra_references if item.strip())
        if extras:
            baseline_text = f"{baseline_text}\n\n{extras}".strip()

    rating_line = ""
    if schema.rating_system.detected and rating_value:
        rating_line = RATING_HINT_TEMPLATE.format(rating_value=rating_value)

    style_block = ""
    if primary_scaffold:
        from backend.domain.style_profile import build_scaffold_style_cues

        style_block = build_scaffold_style_cues(primary_scaffold)

    user_preferred_paragraphs_block = render_add_to_memory_block(
        add_to_memory_blocks
    )

    system = append_cot_to_system(
        compose_mapping_system_prompt(
            level,
            mode=mode,
            preferences=preferences,
            style_block=style_block,
        ),
        MAPPING_COT_PROTOCOL,
    )
    user = MAPPING_USER_TEMPLATE.format(
        section_id=section_id or "—",
        section_label=section_title or section_id or "—",
        rating_line=rating_line,
        first_reference_baseline_paragraph=baseline_text or "(none)",
        user_preferred_paragraphs_block=user_preferred_paragraphs_block,
        observations_bulleted=_observations_bulleted(observations),
    )

    # Leaf-scoped: system rules (+ optional primary-scaffold voice cues) + this
    # subsection's past-report scaffolds + optional user-preferred paragraphs +
    # notes. Past-report prose appears only in the user message — never
    # duplicated as mined style-profile JSON.
    return [
        {"role": "system", "content": system.strip()},
        {"role": "user", "content": user.strip()},
    ]


def map_inplace_baseline(
    baseline_text: str,
    observations: list[str],
    schema: TemplateSchema,
    *,
    section_id: str = "",
    section_title: str = "",
    rating_value: str | None = None,
    messages: list[dict[str, str]] | None = None,
) -> tuple[str, dict | None]:
    """Apply in-place fact updates to the retrieved past-report baseline only.

    Returns ``(prose, llm_usage)`` where ``llm_usage`` is the provider token
    payload from the mapping call (same shape as standard paragraphs), or
    ``None`` when no LLM call ran / usage was omitted.
    """
    baseline = (baseline_text or "").strip()
    if not baseline:
        return "", None
    if not observations:
        return baseline, None

    merged = merge_observations_into_paragraph(baseline, observations, schema)

    if settings.use_llm_paragraph_mapping and openai_client.is_available():
        llm_messages = messages or build_interference_messages(
            "maximum",
            observations=observations,
            baseline=baseline,
            schema=schema,
            section_id=section_id,
            section_title=section_title,
            rating_value=rating_value,
        )
        try:
            out, llm_usage = openai_client.chat_text_with_usage(
                llm_messages,
                model=settings.mapping_model,
                max_tokens=settings.max_tokens_mapping,
                temperature=float(settings.mapping_temperature),
                call_label="mapping",
                reasoning_effort=(
                    settings.mapping_reasoning_effort or "none"
                ),
            )
            if llm_usage:
                logger.info(
                    "Past-report LLM usage section=%s prompt_tokens=%s "
                    "completion_tokens=%s total_tokens=%s source=%s model=%s "
                    "temperature=%s max_tokens=%s",
                    section_id or "—",
                    llm_usage.get("prompt_tokens"),
                    llm_usage.get("completion_tokens"),
                    llm_usage.get("total_tokens"),
                    llm_usage.get("source"),
                    settings.mapping_model,
                    float(settings.mapping_temperature),
                    settings.max_tokens_mapping,
                )
            text = sanitize_section_prose((out or "").strip())
            text = apply_condition_rating_policy(
                text,
                notes_text=" ".join(observations or []),
                rating_value=rating_value,
            )
            if accept_narrative_section_output(text, observations):
                return text, llm_usage
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "In-place LLM mapping failed (%s); using deterministic merge.", exc
            )

    return merged, None


def map_reference_paragraph(
    reference_paragraph: str,
    observations: list[str],
    schema: TemplateSchema,
    interference_level: InterferenceLevel,
    *,
    section_id: str = "",
    section_title: str = "",
    rating_value: str | None = None,
    extra_references: list[str] | None = None,
    reference_blocks: list[str] | None = None,
    add_to_memory_blocks: list[str] | None = None,
    mode: GenerationMode | None = None,
    preferences: ExpertPreferences | None = None,
    tenant_id: str = "",
    capture_messages: list[dict[str, str]] | None = None,
) -> tuple[str, dict | None]:
    """Map notes onto the assembled REFERENCE baseline using tier-specific prompts.

    When ``reference_blocks`` is supplied, each past report's version of the
    subsection is fed to the prompt as its own separate scaffold (never merged); the
    positional ``reference_paragraph`` remains the combined text used only by the
    deterministic merge fallback. When ``capture_messages`` is provided, the exact
    messages array sent to the LLM is copied into it for the retrieval manifest.

    Returns ``(prose, llm_usage)`` — provider token counts when the LLM ran.
    """
    level = _normalize_interference_level(interference_level)
    messages = build_interference_messages(
        level,
        observations=observations,
        baseline=reference_paragraph,
        schema=schema,
        section_id=section_id,
        section_title=section_title,
        rating_value=rating_value,
        extra_references=extra_references,
        reference_blocks=reference_blocks,
        add_to_memory_blocks=add_to_memory_blocks,
        mode=mode,
        preferences=preferences,
        tenant_id=tenant_id,
    )
    if capture_messages is not None:
        capture_messages[:] = messages
    return map_inplace_baseline(
        reference_paragraph,
        observations,
        schema,
        section_id=section_id,
        section_title=section_title,
        rating_value=rating_value,
        messages=messages,
    )
