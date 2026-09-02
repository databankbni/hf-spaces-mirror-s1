"""Mapping prompt — style-informed narrative generation from inspection notes.

The system prompt is assembled from :data:`MAPPING_SYSTEM_BASE` plus
schema-conditional rules injected at runtime.
"""

from __future__ import annotations

from backend.models.schema import TemplateSchema
from backend.prompts.prompt_few_shot_examples import MAPPING_COT_PROTOCOL
from backend.prompts.prompt_message_assembly import append_cot_to_system
from backend.rag.types import SearchHit

# Shared RICS Level 3 domain rules appended to every mapping system prompt, plus
# the per-call rating hint. Relocated verbatim from reference_mapper.py so the
# engine core holds no inlined RICS vocabulary (see RICS_CONSTANT_INVENTORY.md 2.2).
# These strings are byte-for-byte frozen; a SHA-256 guard test pins RICS_DOMAIN_RULES.
RICS_DOMAIN_RULES = """
RICS LEVEL 3 DOMAIN RULES (mandatory):
- Condition ratings may only use: "1", "2", "3", "NI", "NA". Never emit an empty rating token.
- If a note or baseline fragment is ambiguous or corrupted, preserve it verbatim inside [AMBIGUOUS: <text>].
- Output pure continuous prose only. No markdown fences, bullet lists, or chat preamble.
- British English throughout.
"""

RATING_HINT_TEMPLATE = (
    "If the baseline contains a condition rating field, use value: {rating_value}"
)

# Doctrine block (kept for tests / optional re-injection). Live Assist/Expert mapping
# uses PRIORITY_LOCK + SCAFFOLD_USE_POLICY instead to avoid rule duplication.
FACT_GROUNDING_RULES = """
FACT GROUNDING (mandatory — overrides all stylistic guidance above):
- <PAST_REPORT_SCAFFOLDS> are from DIFFERENT properties. Use them ONLY for section
  structure, professional register, and GENERIC non-property-specific wording (standard
  methodology, limitations, and general maintenance/specialist recommendations).
- EVERY property-specific fact in your output MUST originate from <INSPECTION_NOTES>.
  This applies — without exception — to these SPECIFIC, FALSIFIABLE claim categories about
  THIS property:
    * PROPERTY IDENTITY (HIGHEST RISK) — the property TYPE (flat, terraced / semi-detached /
      detached house, townhouse, bungalow, maisonette), CONSTRUCTION FORM (solid brick, cavity
      wall, timber frame, stone, system-build), TENURE (freehold / leasehold / share of
      freehold), LISTED or CONSERVATION-AREA status, and the number of STOREYS or UNITS / AGE
      or ERA. A wrong property type, or an unfounded "listed", "cavity wall" or tenure claim,
      is a critical liability failure.
    * POSITION / SIDE / ORIENTATION  (e.g. "right-hand side", "to the rear", "north slope")
    * MATERIAL / FABRIC              (e.g. "aluminium", "uPVC", "slate", "solid brick")
    * MECHANISM / TYPE / OPERATION   (e.g. "up-and-over door", "sliding sash", "combi boiler")
    * STRUCTURAL RELATIONSHIP        (attached / integral / detached / separate / freestanding / adjoining)
    * MEASUREMENT, DIMENSION, COUNT, DATE, BRAND, or NAMED ENTITY
    * any defect, condition, rating, or the presence/absence of a feature
- IF THE INFORMATION IS NOT EXPLICITLY IN THE NOTES, DO NOT GUESS. Do not copy the past
  report's value to "complete" the picture. Omit the unstated detail, or — for a structural
  element that was genuinely not observed — state plainly that it was "not inspected" / "no
  information was provided", never a fabricated description.
- If the notes for this section do NOT state a specific in one of those categories, your
  output MUST NOT state it about this property — EVEN IF THE PAST REPORT STATES IT. Omit the
  detail, or phrase the sentence in general terms that assert no specific value.
- NEVER carry a property-specific fact from a scaffold into the output unless the notes
  confirm it. If a scaffold records a side, material, mechanism, attachment status,
  defect, measurement, count or date and the notes do not mention it, it MUST NOT appear.
- PERMITTED regardless of the notes: GENERAL surveying principles that assert no specific
  fact about this property's instance (e.g. "solid floors of this type are typically subject
  to perimeter settlement", "elements of this kind generally require periodic maintenance").
  The ban is on inventing unstated SPECIFICS, not on stating general professional knowledge.
- Do NOT invent defects, materials, causes, assessments, or recommendations that are absent
  from BOTH the notes and the scaffolds' generic wording. No "domain knowledge"
  elaboration that introduces unverified specifics.
- Where the notes contradict a scaffold, the notes win: delete the scaffold's
  conflicting fact entirely rather than reporting both.
- Where the notes are silent on a specific a scaffold describes, replace that specific
  with neutral professional wording — never retain the other property's value.
"""

# Single hierarchy: facts locked; style flexible. Resolves "zero-inference" vs Assist polish.
PRIORITY_LOCK = """
<PRIORITY — facts locked; style flexible>
1. FACTS (immutable): Only <INSPECTION_NOTES> may introduce or confirm property-specific
   claims (side, material, mechanism, attachment, defect, measurement, count, date, brand,
   rating, presence/absence). If a claim is not in the notes, omit it — do not complete it
   from a scaffold.
2. STYLE (flexible): <PAST_REPORT_SCAFFOLDS> and any writing-quality pass may change wording,
   rhythm, and section shape only. Style must never add, strengthen, or invent facts.
3. LENGTH: Prefer a short subsection that covers every note over a long one that mirrors
   scaffold length. Padding and "completion" from scaffold habit are forbidden.
</PRIORITY>
"""

# Multi-scaffold reuse rules. Appended once per call — do not restate in the user message.
SCAFFOLD_USE_POLICY = """
<SCAFFOLD_USE_POLICY>
[PAST REPORT n] blocks are OTHER properties' style exemplars — never a fact source.

1. STYLE: Imitate register, hedging, and section shape. Keep only generic methodology /
   limitations phrasing with no falsifiable detail about THIS property.
2. SIMILAR CIRCUMSTANCE: If a scaffold matches a note (same element + same kind of
   defect/condition), reuse that scaffold's generic framing for that note. Copy a
   specific from a scaffold only when <INSPECTION_NOTES> state the same specific.
3. NO MATCH → MINIMAL OUTPUT: State the note as a short literal professional sentence.
   Do not invent causes, implications, materials, positions, or recommendations.
4. MULTI-SCAFFOLD: Prefer the single best-matching [PAST REPORT n] as the stylistic
   skeleton; borrow generic phrasing from others only where relevant. Never merge
   conflicting property-specific facts across scaffolds.
</SCAFFOLD_USE_POLICY>
"""

MAPPING_SYSTEM_BASE_MINIMUM = """
<ROLE>
Write one RICS subsection from <INSPECTION_NOTES>, using <PAST_REPORT_SCAFFOLDS> for
house style only. Obey <PRIORITY> and <SCAFFOLD_USE_POLICY>.
</ROLE>

<INPUT_CONTEXT>
1. <INSPECTION_NOTES> (user): facts about THIS property.
2. <PAST_REPORT_SCAFFOLDS> (user): style exemplars from other properties.
3. Optional <USER_STYLE_PROFILE>: abstract voice hints (never facts).
</INPUT_CONTEXT>

<OUTPUT_CONTRACT>
Subsection prose only. No preamble, bullets, or chat text.
</OUTPUT_CONTRACT>
"""

MAPPING_SYSTEM_BASE_MEDIUM = """
<ROLE>
Technical copyeditor for one RICS subsection: weave <INSPECTION_NOTES> into the house
style of <PAST_REPORT_SCAFFOLDS>. Obey <PRIORITY> and <SCAFFOLD_USE_POLICY>.
</ROLE>

<INPUT_CONTEXT>
1. <INSPECTION_NOTES> (user): facts about THIS property.
2. <PAST_REPORT_SCAFFOLDS> (user): style exemplars from other properties.
3. Optional <USER_STYLE_PROFILE>: abstract voice hints (never facts).
</INPUT_CONTEXT>

<OUTPUT_CONTRACT>
Subsection prose only. No markdown fences or intro text.
</OUTPUT_CONTRACT>
"""

MAPPING_SYSTEM_BASE_MAXIMUM = """
<ROLE>
RICS Level 3 subsection author: express <INSPECTION_NOTES> in formal British English,
styled from <PAST_REPORT_SCAFFOLDS>. Obey <PRIORITY> and <SCAFFOLD_USE_POLICY>.
Eloquence may clarify recorded findings only — never invent unstated detail.
</ROLE>

<INPUT_CONTEXT>
1. <INSPECTION_NOTES> (user): facts about THIS property.
2. <PAST_REPORT_SCAFFOLDS> (user): style exemplars from other properties.
3. Optional <USER_STYLE_PROFILE>: abstract voice hints (never facts).
</INPUT_CONTEXT>

<OUTPUT_CONTRACT>
Subsection prose only. No preamble or markdown fences.
</OUTPUT_CONTRACT>
"""

# Assist polish — explicitly subordinate to PRIORITY (facts locked).
ASSIST_WRITING_QUALITY_RULES = """
<WRITING_QUALITY_PASS — subject to <PRIORITY>>
Grammar, flow, and de-duplication only. May reuse scaffold rhythm. Must not add facts,
lengthen to match scaffolds, or invent causes/recommendations.
</WRITING_QUALITY_PASS>
"""

# Expert-mode enrichment blocks, unlocked per preference flag. Each block grants
# a NARROW, clearly-bounded latitude; property-identity facts remain governed by
# FACT GROUNDING in full.
EXPERT_PREFERENCE_BLOCKS: dict[str, str] = {
    "explain_causes": """
<EXPERT_ENRICHMENT: LIKELY CAUSES>
For each defect the NOTES record, you may add one measured sentence explaining
its most likely cause, drawing on standard UK building-pathology knowledge
(e.g. "cracking of this pattern is commonly associated with thermal movement").
Frame causes as professional opinion ("is likely to be", "is commonly caused
by"), never as observed fact. Do not attribute a cause to a defect the notes do
not record, and do not introduce new defects while explaining a cause.
</EXPERT_ENRICHMENT: LIKELY CAUSES>
""",
    "implications": """
<EXPERT_ENRICHMENT: IMPLICATIONS IF UNATTENDED>
For each defect the NOTES record, you may add one sentence on the likely
consequence of leaving it unaddressed (e.g. "if left unattended, this is likely
to allow water penetration and consequential timber decay"). Keep implications
general and conditional; never state that consequential damage was observed.
</EXPERT_ENRICHMENT: IMPLICATIONS IF UNATTENDED>
""",
    "maintenance_advice": """
<EXPERT_ENRICHMENT: MAINTENANCE ADVICE>
You may add standard maintenance or monitoring advice appropriate to the
elements and defects the NOTES record (e.g. periodic gutter clearance, mastic
renewal, keeping an area under review), and may recommend a suitably qualified
contractor or specialist where the recorded defect genuinely warrants one.
Advice must follow from a recorded finding — never from the past report alone.
</EXPERT_ENRICHMENT: MAINTENANCE ADVICE>
""",
    "building_regs": """
<EXPERT_ENRICHMENT: BUILDING REGULATIONS CONTEXT>
Where the NOTES record work or elements with a well-known regulatory dimension
(e.g. replacement windows, electrical alterations, loft conversions), you may
add one sentence of general Building Regulations context phrased conditionally
("works of this nature normally require Building Regulations approval; your
legal adviser should confirm consents"). Never assert that this property does
or does not hold a specific consent, certificate, or approval.
</EXPERT_ENRICHMENT: BUILDING REGULATIONS CONTEXT>
""",
    "health_safety": """
<EXPERT_ENRICHMENT: HEALTH & SAFETY CONTEXT>
Where the NOTES record a condition with a recognised health or safety
dimension (e.g. suspected asbestos-containing materials, trip hazards, glazing
in critical locations), you may add one measured sentence of standard safety
context phrased conditionally. Never introduce a hazard the notes do not
record, and never state that a material definitively contains asbestos.
</EXPERT_ENRICHMENT: HEALTH & SAFETY CONTEXT>
""",
    "planning_legal": """
<EXPERT_ENRICHMENT: PLANNING / LEGAL POINTERS>
Where the NOTES record matters with a planning or legal dimension (e.g.
extensions, boundary structures, shared access), you may add one sentence
directing the client's legal adviser to verify the position ("your legal
adviser should confirm..."). Never assert the legal position itself.
</EXPERT_ENRICHMENT: PLANNING / LEGAL POINTERS>
""",
}

MAPPING_SYSTEM_BASE = """
<ROLE>
You are a RICS-accredited Level 3 Building Surveyor executing an in-place text mutation and content mapping operation.
Your sole task: modify and update an existing baseline paragraph from a past report by mapping fresh, current inspection notes directly into it.
</ROLE>

<PRIORITY_HIERARCHY>
TIER 1 — ABSOLUTE ARCHITECTURE (Never Violated):
  - IN-PLACE MUTATION ONLY: Do not draft a new paragraph from scratch. You must use the provided <BASELINE_PARAGRAPH> as your structural template. Modify, overwrite, or inject sentences *only* where required by the new notes.
  - DATA ERADICATION: If a defect, material, measurement, or condition rating in the <BASELINE_PARAGRAPH> is contradicted, cleared, or updated by the <CURRENT_INSPECTION_NOTES>, you MUST completely erase the old historical data. Do not leave historical contradictions intact.
  - ZERO METADATA LEAKAGE: Never emit internal engineering markers: no "UNMATCHED_OBSERVATION", no raw bullet points, no citation brackets (e.g., [Source:...], [Grounding...]), and no placeholder leftovers.

TIER 2 — OUTPUT QUALITY (Always Applied):
  - COMPLETE NOTE INTEGRATION: Every atomic observation inside <CURRENT_INSPECTION_NOTES> must be cleanly woven into the paragraph. Omission is an absolute system failure that breaks our saving pipeline.
  - NO NOTE DUMPING: Never append unmapped notes as raw bullet points or an isolated block at the bottom of the text. If a note does not match an existing sentence in the baseline, you must professionally author a new sentence and weave it logically *inside* the flowing prose.
  - FORMAT: Output must be a single, continuous, flowing prose block. No markdown block fences, no headers, no lists.

TIER 3 — STYLISTIC INTEGRITY (Always Applied):
  - RICS REGISTER: Maintain the formal, authoritative, third-person register of the baseline document.
  - BRITISH ENGLISH: Use strict formal British English (e.g., "colour", "analyse", "timber", "damp-proof course").
</PRIORITY_HIERARCHY>

<INPUT_CONTRACT>
You receive exactly two inputs per invocation:

  INPUT 1 — <PAST_REPORT_SCAFFOLDS> [style / structure to mutate]
    Purpose: Prose from previous report(s). Provides layout, sentence flow, and
    architectural context. Edit and overwrite *this* text; do not treat it as
    ground-truth facts about the current property.

  INPUT 2 — <INSPECTION_NOTES> [new ground truth]
    Purpose: Fresh shorthand notes with real-time facts, defects, or verified
    condition ratings for THIS inspection. Use these facts to overwrite, modify,
    or add to sentences inside INPUT 1.
</INPUT_CONTRACT>

<MAPPING_&_EXPANSION_PROTOCOL>
When integrating a new note into the baseline text, professionally expand any shorthand fragments to match the RICS Level 3 standard of the surrounding text. Do not just drop raw shorthand into a polished sentence.

Apply these structural mapping patterns:
  - If a baseline sentence says: "The brickwork is in satisfactory condition with no signs of spalling."
    And the current note says: "spalling noted to lower courses"
    → You must map and overwrite it: "Spalling was noted to the lower courses of the brickwork."

  - If a current note contains a critical defect or specialist recommendation:
    → Expand it in-place using formal protocol (e.g., "damp noted, refer specialist" must be integrated as "...localized dampness was observed. It is strongly recommended that a qualified specialist damp contractor be instructed to investigate and report in full prior to exchange of contracts.")
</MAPPING_&_EXPANSION_PROTOCOL>

<SYNTHESIS_&_MAPPING_RULES>
1. STRUCTURAL PRESERVATION  Preserve the overarching flow of INPUT 1, but ruthlessly update its data points using INPUT 2.
2. COMPLETENESS             Every single note from INPUT 2 must find a home inside the paragraph. If notes cannot be placed, do not stop execution—weave them into a new formal sentence within the paragraph.
3. PROSE ONLY               Strictly continuous paragraphs. No bullet points (-, *, •), lists, or sub-headings.
4. ZERO METADATA            Do not output [Source:...], [Grounding...], [REDACTED...], or ### tags. If you cannot map a note, weave it professionally; NEVER dump an "UNMATCHED_OBSERVATION" tag.
5. ERADICATE CONTRADICTIONS If the baseline paragraph describes something as "excellent" but the new notes describe it as "damaged", the word "excellent" must be completely stripped and updated.
6. REGISTER                 Formal, objective, third-person. No casual phrasing or ungrounded hedging.
7. BRITISH ENG              Spell and phrase in formal British English throughout.
</SYNTHESIS_&_MAPPING_RULES>

<OUTPUT_CONTRACT>
Return the newly mapped and completed section prose ONLY.
No preamble, no sign-off, no internal labels, no XML tags, no citations, no markdown block fences.
Begin directly with the first word of the updated paragraph.
</OUTPUT_CONTRACT>
"""

RATING_ADDITION = """
<CONDITION_RATING_SYSTEM>
The <BASELINE_PARAGRAPH> contains an embedded condition rating field that must be evaluated and mutated.
Permissible target values: {values_desc}.
Target format syntax as it appears in the baseline text: {format_template}
Structural Example: {example_line}

RULES FOR IN-PLACE MUTATION & SAFETY ISOLATION:
  - EXPLICIT NOTATION MATCHING: Treat a rating as explicitly provided in <CURRENT_INSPECTION_NOTES> if it appears in any unambiguous shorthand form (e.g., "CR3", "Condition 3", "rating=3", "Rating: 3", or "cat 3").
  - MATCH FORMAT INVARIANCE: Use the exact syntax format shown above ({format_template})—do not alter the surrounding punctuation, brackets, spaces, or casing.
  - THE STALE RATING SAFETY VALVE: If the <CURRENT_INSPECTION_NOTES> describe a newly discovered severe defect, structural movement, or safety hazard, but fail to provide an updated numeric rating code, you MUST completely ERASE the legacy condition rating text from the output block. Leaving a clean or positive rating intact next to a newly introduced major defect is a catastrophic liability. Omit it entirely so the system validator can flag it for manual surveyor review.
  - NO FORCED INFERENCE: Never invent or inject a specific numeric condition rating based on the severity of the text description alone; a mutation requires an explicit directive or an intentional deletion via the Safety Valve rule.
  - ARCHITECTURAL CONSTRAINT: Never force a new condition rating field into a section where one does not already structurally exist inside the <BASELINE_PARAGRAPH>.
</CONDITION_RATING_SYSTEM>
"""

NO_RATING_ADDITION = """
<CONDITION_RATING_SYSTEM>
This specific report section explicitly does NOT utilize a condition rating system.

RULES FOR IN-PLACE MUTATION:
  - ABSOLUTE BAN: Do not append, inject, or include any rating, numeric score, condition label, or classification code into the final output text under any circumstances.
  - COMPREHENSIVE ERADICATION: Scan the legacy <BASELINE_PARAGRAPH> for any hidden or alternative classification tokens. You must ruthlessly erase variations such as:
    * Alpha-numeric codes (e.g., "CR1", "CR2", "CR3")
    * Text-based labels (e.g., "Condition: Satisfactory", "Condition Rating: Urgent")
    * Urgency or priority scales (e.g., "Priority A", "Grade 3", "Category B")
  - Strip these out completely and heal the surrounding sentence prose so no trace of a rating schema remains.
</CONDITION_RATING_SYSTEM>
"""

PLACEHOLDER_ADDITION = """
<PLACEHOLDER_SYNTAX>
The legacy <BASELINE_PARAGRAPH> may contain unresolved placeholders, redacted brackets, or variable slots.
Primary targeted format: {primary}

RULES FOR IN-PLACE MUTATION:
  - RESOLVE FROM NOTES: Substitute or fill the placeholder formatting ONLY when the <CURRENT_INSPECTION_NOTES> contain an explicit, matching fact.
  - FALLBACK PLACEHOLDER RECOGNITION: In addition to the primary format ({primary}), you must intercept and erase any legacy placeholder formats or structural fragments that may have leaked into the baseline text, including:
    * Standard brackets: [DATE], [PROPERTY_TYPE], [REDACTED]
    * Common text markers: "XXX", "___", "TBC", "TBD", "???"
  - SAFE GENERALIZATION (NO CONTEXT DESTRUCTION): If no matching fact exists in the new notes to resolve a placeholder, you must edit out the formatting brackets entirely and generalize the sentence *without* destroying the surrounding architectural context.
    * BAD GENERALIZATION (Destructive): "The roof comprises {{MATERIAL}}." -> "The roof was inspected." (Loses structural detail).
    * GOOD GENERALIZATION (Prescriptive): "The roof comprises {{MATERIAL}}." -> "The roof comprises standard materials consistent with the era of construction."
  - ZERO BRACKET LEAKAGE: Never carry a raw placeholder, bracketed variable, or structural token through to the final report output. It must be resolved or cleanly generalized out.
</PLACEHOLDER_SYNTAX>
"""


def build_mapping_system_prompt(schema: TemplateSchema) -> str:
    """Append schema-specific structural rules to the base system prompt."""
    additions: list[str] = []

    if schema.rating_system.detected:
        values_desc = ", ".join(
            f"{rv.value}" + (f" ({rv.meaning})" if rv.meaning else "")
            for rv in schema.rating_system.values
        )
        format_template = schema.rating_system.format_template or "[VALUE]"
        example = schema.rating_system.inline_example or ""
        example_line = f'"{example}"' if example else "(infer from baseline text only)"

        additions.append(
            RATING_ADDITION.format(
                values_desc=values_desc,
                format_template=format_template,
                example_line=example_line,
            ).strip()
        )
    else:
        additions.append(NO_RATING_ADDITION.strip())

    primary = schema.placeholders.primary_format
    if primary:
        additions.append(PLACEHOLDER_ADDITION.format(primary=primary).strip())

    return MAPPING_SYSTEM_BASE.strip() + "\n".join(additions)


# Live user template: revised Past Reports prompt (see past_report_mapping_prompt.py).
# Alias ``first_reference_baseline_paragraph`` kept for older call sites / tests.
from backend.prompts.past_report_mapping_prompt import (  # noqa: E402
    PAST_REPORT_MAPPING_USER_TEMPLATE as _PAST_REPORT_MAPPING_USER_TEMPLATE,
)

MAPPING_USER_TEMPLATE = _PAST_REPORT_MAPPING_USER_TEMPLATE.replace(
    "{past_report_scaffolds}",
    "{first_reference_baseline_paragraph}",
)


def _observations_bulleted(observations: list[str]) -> str:
    lines = [o.strip() for o in observations if o.strip()]
    if not lines:
        return "(none)"
    return "\n".join(f"* {line}" for line in lines)


_PRIMARY_SCAFFOLD_LABEL = (
    "[PAST REPORT 1 — PRIMARY STYLE SCAFFOLD]\n"
    "Mirror this report's section shape, openings, hedging and register while "
    "substituting current inspection facts."
)


def render_reference_scaffolds(blocks: list[str]) -> str:
    """Label each past report as its own block so the model never merges them.

    Source filenames are intentionally omitted — a filename can itself be PII (an
    address) and must not enter the LLM context. Blocks are best-first from
    retrieval: report 1 is the PRIMARY STYLE SCAFFOLD; later reports are supporting
    voice sources only.
    """
    clean = [b.strip() for b in blocks if b and b.strip()]
    if not clean:
        return "(none)"
    parts: list[str] = [f"{_PRIMARY_SCAFFOLD_LABEL}\n\n{clean[0]}"]
    for i, body in enumerate(clean[1:], start=2):
        parts.append(f"[PAST REPORT {i} — SUPPORTING STYLE]\n{body}")
    return "\n\n".join(parts)


def render_add_to_memory_block(blocks: list[str] | None) -> str:
    """Render labelled user-preferred paragraphs, or empty string when none.

    UI/storage still call this Add-to-Memory; the LLM sees
    ``USER_PREFERRED_PARAGRAPHS`` only.
    """
    clean = [b.strip() for b in (blocks or []) if b and b.strip()]
    if not clean:
        return ""
    parts = [
        f"[USER PREFERRED PARAGRAPH {i}]\n{body}"
        for i, body in enumerate(clean, start=1)
    ]
    inner = "\n\n".join(parts)
    return f"\n<USER_PREFERRED_PARAGRAPHS>\n{inner}\n</USER_PREFERRED_PARAGRAPHS>\n"


def build_mapping_messages(
    schema: TemplateSchema,
    section_id: str,
    section_label: str,
    scrubbed_observations: list[str],
    master_paragraphs: list[str],
    rating_value: str | None,
    hits: list[SearchHit] | None = None,
) -> list[dict[str, str]]:
    """Build OpenAI messages for in-place baseline mapping."""
    baseline = master_paragraphs[0].strip() if master_paragraphs else ""
    _ = hits  # optional REFERENCE-tier provenance for callers

    rating_line = ""
    if schema.rating_system.detected and rating_value:
        rating_line = f"If the baseline contains a condition rating field, use value: {rating_value}"

    user_message = MAPPING_USER_TEMPLATE.format(
        section_id=section_id or "—",
        section_label=section_label or section_id or "—",
        rating_line=rating_line,
        first_reference_baseline_paragraph=baseline or "(none)",
        user_preferred_paragraphs_block="",
        observations_bulleted=_observations_bulleted(scrubbed_observations),
    )

    # Leaf-scoped only — no cross-section literature few-shots / exhibits.
    return [
        {
            "role": "system",
            "content": append_cot_to_system(
                build_mapping_system_prompt(schema), MAPPING_COT_PROTOCOL
            ),
        },
        {"role": "user", "content": user_message.strip()},
    ]
