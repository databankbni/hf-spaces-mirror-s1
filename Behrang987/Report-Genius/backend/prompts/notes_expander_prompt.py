"""Tier-aware notes-expander prompts (pre-mapping shorthand normalization).

Expands terse surveyor shorthand before paragraph mapping. Rating shorthand guidance
is schema-conditional. Gated by ``settings.notes_expansion_enabled``.
"""

from __future__ import annotations

from backend.models.schema import TemplateSchema
from backend.prompts.prompt_few_shot_examples import (
    EXPANDER_COT_PROTOCOL,
    EXPANDER_FEW_SHOT,
)
from backend.prompts.prompt_message_assembly import (
    append_cot_to_system,
    apply_dynamic_literature,
    inject_few_shot_turns,
)
from backend.rag.retriever import InterferenceLevel

_COMMON_SHORTHAND = """
COMMON SHORTHAND (building survey terms):
- det / dett        → deterioration noted
- NI               → not inspected
- rep reqd         → repair required
- v. limited       → very limited access / visibility
- n/a              → not applicable / not present
- gen              → generally / general condition
- DPC              → damp proof course
- MC               → moisture content reading
- UV / uPVC        → unplasticised polyvinyl chloride (plastic) material
- conc             → concrete
- s/s              → stainless steel
- pt / part        → part of / partial
- approx           → approximately
- ext              → external / exterior
- int              → internal / interior
- org              → original
- prev             → previous / previously
"""

EXPANDER_SYSTEM_BASE_MINIMUM = """
<ROLE>
You are a zero-inference RICS field-note normalizer preparing shorthand for strict uploaded-report mapping.
</ROLE>

<TIER DIRECTIVES — MINIMUM>
- Decode abbreviations to plain words ONLY where the expansion is unambiguous.
- Do NOT add defects, materials, measurements, implications, or new sentences.
- Do NOT write narrative prose — output one normalized observation per line (no bullets required).
- Preserve ambiguous shorthand verbatim inside [AMBIGUOUS: <original>].
- British English throughout.
</TIER DIRECTIVES — MINIMUM>
"""

EXPANDER_SYSTEM_BASE_MEDIUM = """
<ROLE>
You are a technical proofreading assistant expanding RICS Level 3 field shorthand before baseline mapping.
</ROLE>

<TIER DIRECTIVES — MEDIUM>
- Expand abbreviations into formal passive British English (e.g., "deterioration was noted", "repair is required").
- Output a clean bulleted list — one observation per bullet.
- Expand only what is clearly implied by the shorthand. Never add defects, materials, or measurements not mentioned.
- Preserve ambiguous items as [AMBIGUOUS: <original>].
- British English throughout.
""" + _COMMON_SHORTHAND.strip()

EXPANDER_SYSTEM_BASE_MAXIMUM = """
<ROLE>
You are an expert UK RICS surveyor expanding field shorthand into comprehensive professional observations before narrative composition.
</ROLE>

<TIER DIRECTIVES — MAXIMUM>
- Expand shorthand into fuller RICS Level 3 observations, contextualizing within standard structural survey vocabulary where clearly implied by the note.
- You may reference general UK property surveying concepts (structural condition, moisture, compliance) ONLY to clarify what the note already states — never to invent new facts.
- Include remediation or compliance framing ONLY when explicitly stated in the shorthand.
- Output a bulleted list — one observation per bullet. British English throughout.
""" + _COMMON_SHORTHAND.strip()

# Backward-compatible alias — prefer select_expander_prompt() for new code.
EXPANDER_SYSTEM_BASE = EXPANDER_SYSTEM_BASE_MEDIUM


def select_expander_prompt(interference_level: str | InterferenceLevel | None) -> str:
    """Return the tier-specific expander system prompt base."""
    level = (interference_level or "maximum").strip().lower()
    if level == "minimum":
        return EXPANDER_SYSTEM_BASE_MINIMUM
    if level == "medium":
        return EXPANDER_SYSTEM_BASE_MEDIUM
    return EXPANDER_SYSTEM_BASE_MAXIMUM


def _rating_system_addition(schema: TemplateSchema) -> str:
    if schema.rating_system.detected and schema.rating_system.values:
        values_shorthand = "\n".join(
            f"- {rv.value}  → rating value: {rv.value}"
            + (f" ({rv.meaning})" if rv.meaning else "")
            for rv in schema.rating_system.values
        )
        format_hint = schema.rating_system.format_template or "[VALUE]"
        return f"""

RATING SYSTEM SHORTHAND:
This template uses the following rating values. Expand shorthand rating references
using these exact values:
{values_shorthand}

When a rating value appears in the notes, expand it as: {format_hint}
with the appropriate value substituted for [VALUE].
"""

    return """

RATING SYSTEM:
This template does not use a rating system. Do not expand any shorthand as a rating,
condition score, or similar classification.
"""


def build_expander_system_prompt(
    schema: TemplateSchema,
    *,
    interference_level: str | InterferenceLevel | None = None,
) -> str:
    """Append rating-system shorthand only when the schema defines one."""
    return select_expander_prompt(interference_level).strip() + _rating_system_addition(
        schema
    )


def build_expander_messages(
    schema: TemplateSchema,
    notes_text: str,
    *,
    interference_level: str | InterferenceLevel | None = None,
) -> list[dict[str, str]]:
    messages = inject_few_shot_turns(
        [
            {
                "role": "system",
                "content": append_cot_to_system(
                    build_expander_system_prompt(
                        schema, interference_level=interference_level
                    ),
                    EXPANDER_COT_PROTOCOL,
                ),
            },
            {"role": "user", "content": notes_text},
        ],
        EXPANDER_FEW_SHOT,
    )
    return apply_dynamic_literature(messages, query=notes_text)
