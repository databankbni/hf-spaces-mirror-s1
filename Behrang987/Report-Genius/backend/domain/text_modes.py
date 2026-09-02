"""Proofread and enhance modes for legacy UI compatibility."""

from __future__ import annotations

from backend.domain.notes.note_bullets import format_bullets_for_prompt
from backend.domain.style_profile import StyleProfile
from backend.llm import openai_client
from backend.models.schema import TemplateSchema
from backend.pipeline.paragraph_merge import merge_observations_into_paragraph
from backend.prompts.prompt_few_shot_examples import (
    ENHANCE_COT_PROTOCOL,
    ENHANCE_FEW_SHOT,
    PROOFREAD_COT_PROTOCOL,
)
from backend.prompts.prompt_message_assembly import (
    append_cot_to_system,
    apply_dynamic_literature,
    inject_few_shot_turns,
)

PROOFREAD_SYSTEM = """\
You are a professional RICS survey report editor and proofreader. \
Fix grammar, clarity, and British English spellings. Do not add new facts. \
Output plain text only.\
"""

ENHANCE_SYSTEM = """\
You are an expert RICS surveyor and technical writer. \
Expand the section using supplied evidence only — do not invent facts. \
Use British English. Output plain text only.\
"""


def _profile_fields(profile: StyleProfile) -> dict[str, str]:
    return {
        "tone": profile.tone,
        "formality_level": profile.formality_level,
        "avg_sentence_complexity": profile.avg_sentence_complexity,
        "vocabulary_level": profile.vocabulary_level,
        "writing_style_summary": profile.writing_style_summary,
    }


def proofread_text(
    text: str,
    bullets: list[str],
    *,
    style_profile: StyleProfile | None = None,
) -> str:
    clean = text.split("\n\n[Editor notes:")[0].strip()
    if not clean:
        return text

    profile = style_profile or StyleProfile()
    pf = _profile_fields(profile)
    bullets_text = format_bullets_for_prompt(bullets)

    if not openai_client.is_available():
        return clean

    user = f"""AUTHOR'S WRITING STYLE PROFILE:
- Tone: {pf['tone']}
- Formality: {pf['formality_level']}
- Sentence complexity: {pf['avg_sentence_complexity']}
- Vocabulary: {pf['vocabulary_level']}
- Style summary: {pf['writing_style_summary']}

ORIGINAL FACT BULLETS:
{bullets_text}

TEXT TO PROOFREAD:
{clean}

TASK: Proofread and improve the text. Do NOT add new facts.
Return corrected text, then "---NOTES---" and 1–3 brief editor notes."""

    out = openai_client.chat_text(
        [
            {
                "role": "system",
                "content": append_cot_to_system(
                    PROOFREAD_SYSTEM, PROOFREAD_COT_PROTOCOL
                ),
            },
            {"role": "user", "content": user},
        ],
        temperature=0.15,
        max_tokens=max(700, min(2400, len(clean.split()) * 3)),
    )
    if "---NOTES---" in out:
        corrected, notes = out.split("---NOTES---", 1)
        corrected = corrected.strip()
        notes_block = f"\n\n[Editor notes: {notes.strip()}]"
    else:
        corrected = out.strip()
        notes_block = ""
    return corrected + notes_block


def enhance_text(
    text: str,
    bullets: list[str],
    snippets: list[str],
    *,
    style_profile: StyleProfile | None = None,
    schema: TemplateSchema | None = None,
) -> str:
    base = text.split("\n\n[Editor notes:")[0].strip()
    if not base:
        base = text.strip()
    profile = style_profile or StyleProfile()
    pf = _profile_fields(profile)
    bullets_text = format_bullets_for_prompt(bullets)
    examples = "\n\n---\n\n".join(s.strip() for s in snippets if s.strip())[:3500]

    if openai_client.is_available():
        user = f"""AUTHOR'S WRITING STYLE PROFILE:
- Tone: {pf['tone']}
- Formality: {pf['formality_level']}
- Vocabulary: {pf['vocabulary_level']}
- Style summary: {pf['writing_style_summary']}

ORIGINAL FACT BULLETS:
{bullets_text}

ADDITIONAL EVIDENCE:
{examples or '(No additional evidence available.)'}

CURRENT TEXT:
{base}

TASK: Rewrite and expand the current text using evidence only. Aim for 80–200 words.
Output only the enhanced text."""

        enhance_messages = inject_few_shot_turns(
            [
                {
                    "role": "system",
                    "content": append_cot_to_system(
                        ENHANCE_SYSTEM, ENHANCE_COT_PROTOCOL
                    ),
                },
                {"role": "user", "content": user},
            ],
            ENHANCE_FEW_SHOT,
        )
        enhance_query = "\n".join([*(b.strip() for b in bullets), base]).strip()
        enhance_messages = apply_dynamic_literature(
            enhance_messages, query=enhance_query
        )
        out = openai_client.chat_text(
            enhance_messages,
            temperature=0.2,
            max_tokens=max(900, min(2400, len(base.split()) + 800)),
        )
        enhanced = (out or "").strip()
        if enhanced:
            return enhanced

    sch = schema or TemplateSchema()
    merged = merge_observations_into_paragraph(base, bullets, sch)
    if snippets and snippets[0].strip() not in merged:
        extra = snippets[0].strip()
        if len(extra) > 40:
            merged = f"{merged.rstrip()} {extra}"
    return merged
