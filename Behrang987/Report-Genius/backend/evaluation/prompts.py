"""LLM prompts for post-generation evaluation (Approach 2 coverage + Approach 3 faithfulness)."""

from __future__ import annotations

import json

from backend.config import settings
from backend.models.validation_loop import ViolationType

_TAXONOMY = ", ".join(v.value for v in ViolationType)

COVERAGE_SYSTEM_PROMPT = (
    "You are a RICS Home Survey report QA judge for COVERAGE only.\n"
    "Task: for ONE section, check whether each surveyor field note is reflected "
    "in the AI-generated subsection prose.\n\n"
    "INPUTS (user JSON):\n"
    "- surveyor_notes: list of atomic field notes (GROUND TRUTH — only facts to check)\n"
    "- generated_section: AI prose for this section only\n"
    "- section / title: identifiers; do not invent facts from the title\n\n"
    "WHAT COVERAGE MEANS:\n"
    "A note is covered when a reader of the prose would learn the same "
    "property-specific fact (defect, material, location, condition, rating cue, "
    "limitation, or recommended action) that the note records. "
    "British English paraphrase and synonymy are allowed "
    "(e.g. 'flaking paint' ↔ 'paint is peeling'; "
    "'water is lit' ↔ 'water supply was on').\n\n"
    "LABELS — use exactly one per note:\n"
    "- covered: the note's concrete fact is clearly present in the prose\n"
    "- partial: the topic appears but a material detail from the note is "
    "missing, softened, or contradicted (e.g. note says 'CR3 / Condition 3' "
    "but prose implies Condition 2; note names 'rear elevation' but prose is "
    "vague; note says 'lead flashing failed' but prose only says 'flashing "
    "requires attention')\n"
    "- missing: the note's fact is not stated in the prose\n\n"
    "HARD RULES:\n"
    "1. Judge ONLY notes vs generated_section. Do not assume past-report "
    "content, photos, or other sections.\n"
    "2. Emit exactly one judgment object for EVERY item in surveyor_notes, "
    "in the same order, copying each note string verbatim into \"note\".\n"
    "3. Do not merge, split, drop, or rewrite notes.\n"
    "4. Rating / condition tokens in notes (CR1–CR3, Condition 1–3, NI, NA) "
    "must be reflected if present — otherwise partial or missing.\n"
    "5. Shorthand and telegram-style notes still count as facts.\n"
    "6. Generic RICS methodology, access limitations, or boilerplate that "
    "does not come from a note does NOT create coverage and does NOT "
    "excuse a dropped note.\n"
    "7. Do not reward lexical echo alone: shared words without the same "
    "fact → missing or partial.\n"
    "8. \"evidence\": for covered/partial, quote a short span from "
    "generated_section (≤25 words); for missing, use \"\".\n\n"
    "OUTPUT: respond using the provided structured schema only "
    "(judgments + missing_facts). "
    "missing_facts must list every note whose status is missing or partial, "
    "verbatim, same strings as in judgments."
)

FAITHFULNESS_SYSTEM_PROMPT = (
    "You are a meticulous RICS report QA judge for FAITHFULNESS / leakage. "
    "You are given surveyor notes, the AI-generated prose, and the past-report "
    "baseline scaffold used during mapping.\n\n"
    "Notes are the only source of property-specific facts. The baseline is style/"
    "structure only — any property-specific claim in the generated prose that is "
    "not supported by the notes is unfaithful "
    f"(taxonomy: {_TAXONOMY}).\n\n"
    "Generic RICS methodology / limitation boilerplate is allowed and is NOT an "
    "unsupported claim.\n\n"
    "Score faithfulness in [0,1]: 1.0 means every property-specific claim in the "
    "generated prose is supported by the notes.\n\n"
    "Respond using the provided structured schema only "
    "(faithfulness + unsupported_claims)."
)

# Backward-compatible combined judge (golden nightly). Prefer coverage + faithfulness
# split for production evaluation.
COMBINED_JUDGE_SYSTEM_PROMPT = (
    "You are a meticulous RICS report QA judge. You are given a surveyor's field "
    "notes for one section and the AI-generated prose for that section. Judge ONLY "
    "against the notes (the notes are the ground truth; generic RICS methodology / "
    "limitation boilerplate is allowed and is NOT an unsupported claim).\n\n"
    "Score two dimensions in [0,1]:\n"
    "- faithfulness: 1.0 means every property-specific claim in the generated prose "
    "is supported by the notes; lower it for each invented/ungrounded specific "
    f"(taxonomy: {_TAXONOMY}).\n"
    "- answer_correctness: 1.0 means every concrete fact in the notes is reflected "
    "in the generated prose; lower it for each dropped surveyor fact.\n\n"
    "Respond using the provided structured schema only "
    "(faithfulness, answer_correctness, unsupported_claims, missing_facts)."
)


def build_coverage_messages(
    *,
    section_id: str,
    title: str,
    observations: list[str],
    generated_text: str,
) -> list[dict[str, str]]:
    payload = {
        "section": section_id,
        "title": title,
        "surveyor_notes": [o for o in observations if str(o).strip()],
        "generated_section": generated_text or "",
    }
    return [
        {"role": "system", "content": COVERAGE_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def build_faithfulness_messages(
    *,
    section_id: str,
    title: str,
    observations: list[str],
    generated_text: str,
    baseline_text: str,
) -> list[dict[str, str]]:
    payload = {
        "section": section_id,
        "title": title,
        "surveyor_notes": [o for o in observations if str(o).strip()],
        "generated_section": generated_text or "",
        "past_report_baseline": baseline_text or "",
    }
    return [
        {"role": "system", "content": FAITHFULNESS_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def prompt_record(
    messages: list[dict[str, str]],
    *,
    model: str,
    reasoning_effort: str,
    max_tokens: int | None,
    provider: str = "openai",
) -> dict:
    """Persistable prompt artifact (same shape family as retrieval manifests)."""
    system = ""
    user = ""
    for msg in messages:
        role = msg.get("role")
        if role == "system" and not system:
            system = msg.get("content") or ""
        elif role == "user":
            user = msg.get("content") or ""
    return {
        "provider": provider,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "max_tokens": max_tokens,
        "temperature": float(settings.evaluation_temperature),
        "system": system,
        "final_user_prompt": user,
        "messages": messages,
    }


def build_combined_judge_messages(
    *,
    section_id: str,
    surveyor_notes: str | list[str],
    generated_text: str,
) -> list[dict[str, str]]:
    notes: str | list[str]
    if isinstance(surveyor_notes, list):
        notes = [o for o in surveyor_notes if str(o).strip()]
    else:
        notes = surveyor_notes
    payload = {
        "section": section_id,
        "surveyor_notes": notes,
        "generated_section": generated_text or "",
    }
    return [
        {"role": "system", "content": COMBINED_JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
