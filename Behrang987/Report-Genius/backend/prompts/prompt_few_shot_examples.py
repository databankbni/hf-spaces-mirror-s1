"""Curated few-shot demonstrations from *My literature April 2026.docx*.

Verbatim RICS surveyor prose and note→paragraph transformations extracted from
the operator literature corpus. Used as in-context learning examples and CoT
anchors across mapping, expansion, audit, and repair prompts.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "FewShotTurn",
    "MAPPING_FEW_SHOT",
    "EXPANDER_FEW_SHOT",
    "AUDITOR_FEW_SHOT",
    "REPAIR_FEW_SHOT",
    "VISION_FEW_SHOT",
    "ENHANCE_FEW_SHOT",
    "MAPPING_COT_PROTOCOL",
    "EXPANDER_COT_PROTOCOL",
    "AUDITOR_COT_PROTOCOL",
    "REPAIR_COT_PROTOCOL",
    "VISION_COT_PROTOCOL",
    "DISCOVERY_COT_PROTOCOL",
    "STYLE_COT_PROTOCOL",
    "ENHANCE_COT_PROTOCOL",
    "PROOFREAD_COT_PROTOCOL",
]

# ── Chain-of-thought protocols (internal reasoning; final output contract unchanged) ──

MAPPING_COT_PROTOCOL = """
<CHAIN_OF_THOUGHT_PROTOCOL>
Work through these steps INTERNALLY before writing the final paragraph. Do NOT
print Steps 1–6 — emit ONLY the continuous prose required by the OUTPUT_CONTRACT.
Obey <PRIORITY> and <SCAFFOLD_USE_POLICY> throughout.

Step 1 — NOTE INVENTORY: Parse each bullet in <INSPECTION_NOTES> into atomic facts
(side/position, material, mechanism, defect, measurement, recommendation).

Step 2 — SCAFFOLD TRIAGE: For each sentence in <PAST_REPORT_SCAFFOLDS>, label KEEP
(generic methodology), MODIFY (a note updates a detail), or DELETE (a note
contradicts it, or <INSPECTION_NOTES> are silent on a property-specific the
scaffold asserts).

Step 3 — MAP: Assign every note atom to a scaffold sentence or plan a short
literal professional sentence. Include every note as a fact; do not expand to
fill scaffold length. No note may remain unassigned.

Step 4 — FOREIGN-FACT GATE: Reject any property-specific from
<PAST_REPORT_SCAFFOLDS> that <INSPECTION_NOTES> do not confirm (position,
material, mechanism, relationship, measurement, date).

Step 5 — REGISTER PASS: Expand shorthand into formal passive British English while
preserving note severity; apply Condition Rating rules if present.

Step 6 — OUTPUT: Write the unified paragraph only.
</CHAIN_OF_THOUGHT_PROTOCOL>
"""

EXPANDER_COT_PROTOCOL = """
<CHAIN_OF_THOUGHT_PROTOCOL>
Internally for each raw note line:
  1) Identify abbreviations and decode only when unambiguous.
  2) Separate confirmed facts from ambiguous fragments.
  3) Flag ambiguity as [AMBIGUOUS: <original>] — never invent detail.
  4) Emit one normalized observation per line (bulleted for medium/maximum).
Do NOT print this reasoning — output observations only.
</CHAIN_OF_THOUGHT_PROTOCOL>
"""

AUDITOR_COT_PROTOCOL = """
<CHAIN_OF_THOUGHT_PROTOCOL>
Before emitting JSON, internally execute:
  1) Decompose MUTATED_REPORT_PARAGRAPH into atomic claim triads
     [Element + Condition + Location/Modifier].
  2) For each triad, locate explicit support in CURRENT_INSPECTION_NOTES.
  3) Compare against BASELINE_PARAGRAPH for stale/contradicted legacy facts.
  4) Classify each failure into exactly one VIOLATION_TAXONOMY label.
  5) Set passed=true only when violations is empty.
Return JSON only — never print the intermediate claim list.
</CHAIN_OF_THOUGHT_PROTOCOL>
"""

REPAIR_COT_PROTOCOL = """
<CHAIN_OF_THOUGHT_PROTOCOL>
Before emitting repaired prose, internally:
  1) Sort violations by REPAIR_HIERARCHY order (dialect → placeholders → prune → amputate).
  2) For each violation, locate offending_text in MUTATED_REPORT_PARAGRAPH.
  3) Apply the minimum edit that removes the fault while keeping grounded content.
  4) Verify no new nouns, defects, or specifics were introduced.
Output continuous prose only — never print the repair plan.
</CHAIN_OF_THOUGHT_PROTOCOL>
"""

VISION_COT_PROTOCOL = """
<CHAIN_OF_THOUGHT_PROTOCOL>
Internally, before emitting JSON, for each photograph:
  1) Isolate the physical property elements; discard sky, weather, vehicles, people.
  2) For each candidate anomaly, decide CLEARLY VISIBLE vs AMBIGUOUS — ambiguous
     items go to limitations, never observations.
  3) Choose the correct certainty trigger: absolute ("was observed") only for
     geometrically unambiguous macro facts; cautious ("appears to display") for
     stains, moisture footprints, and complex degradation.
  4) Classify materials by broad visual class only (no chemical/era subtypes).
  5) Build each observation: [Location/Orientation] + [Broad Material] + [Anomaly
     with certainty trigger] + [Footprint extent]. Deduplicate across images.
Return JSON only — never print this reasoning.
</CHAIN_OF_THOUGHT_PROTOCOL>
"""

DISCOVERY_COT_PROTOCOL = """
<CHAIN_OF_THOUGHT_PROTOCOL>
Internally before emitting JSON:
  1) Walk the heading outline top-to-bottom; assign clean parent-child IDs.
  2) Detect any rating/condition legend from literal document text only.
  3) Identify placeholder syntax actually present (never assume).
  4) Extract per-section keywords from labels and opening sentences only.
  5) Where structure is OCR-scrambled, flag it rather than inventing hierarchy.
Return JSON only — never print the walkthrough. Extract only what is present;
never invent sections, ratings, or keywords from general domain knowledge.
</CHAIN_OF_THOUGHT_PROTOCOL>
"""

STYLE_COT_PROTOCOL = """
<CHAIN_OF_THOUGHT_PROTOCOL>
Internally: sample the supplied prose; infer tone, formality, sentence
complexity, and vocabulary from observed patterns only; extract verbatim short
extracts as example_paragraphs. Do not invent phrasing the corpus does not show.
Return JSON only.
</CHAIN_OF_THOUGHT_PROTOCOL>
"""

ENHANCE_COT_PROTOCOL = """
<CHAIN_OF_THOUGHT_PROTOCOL>
Internally: list the fact bullets; map each to a sentence in the expanded prose;
draw register/phrasing from the evidence extracts; expand shorthand into formal
British English WITHOUT adding any defect, material, measurement, or cause not in
the bullets. Output enhanced prose only — never print the mapping.
</CHAIN_OF_THOUGHT_PROTOCOL>
"""

PROOFREAD_COT_PROTOCOL = """
<CHAIN_OF_THOUGHT_PROTOCOL>
Internally: scan for grammar/clarity issues and non-British spellings (color→colour,
analyze→analyse, aluminum→aluminium, gray→grey); correct them WITHOUT adding,
removing, or altering any fact. Output corrected text only — never print the scan.
</CHAIN_OF_THOUGHT_PROTOCOL>
"""


@dataclass(frozen=True)
class FewShotTurn:
    user: str
    assistant: str


# ── Mapping: notes + baseline → mapped prose (literature April 2026) ─────────

_MAPPING_EX1_USER = """\
SECTION: E1 — Roof structure & coverings
<PAST_REPORT_SCAFFOLDS>
The roof coverings comprise natural slate tiles. The roof was inspected from ground level using binoculars where accessible. No significant defects were noted to the roof coverings at the time of inspection.
</PAST_REPORT_SCAFFOLDS>

<INSPECTION_NOTES>
* small area damp on timber boarded floor under eaves cupboard 2nd floor
* unable to open defective roof window left side main attic room
* possible defective flashing or slipped roof tile above leak area
</INSPECTION_NOTES>

<TASK>
Apply <PRIORITY> and <SCAFFOLD_USE_POLICY>. Include every note as a fact (short
literal sentence is enough when no scaffold matches). Do not expand to fill
scaffold length. Output subsection prose only.
</TASK>"""

_MAPPING_EX1_ASSISTANT = """\
As described in Section E1 below, we noted the presence of a small area of damp on the timber boarded floor of the under eaves storage cupboard on the second floor. Our investigation into the source of this damp was severely hampered by our inability to open the defective roof window on the left side of the main attic room, which otherwise would have allowed us to examine the roofing tiles and flashing in the area immediately above the leak. However, it is possible that the damp originates from defective flashing or a slipped roof tile, and we would recommend that when the defective window has been repaired or replaced, you commission a reputable roofing contractor to examine this area for possible defects and to carry out any appropriate repairs."""

_MAPPING_EX2_USER = """\
SECTION: E3 — Main walls
<PAST_REPORT_SCAFFOLDS>
The external walls of the single-storey rear extension were inspected where accessible. The walls appeared to be in satisfactory condition with no significant defects noted.
</PAST_REPORT_SCAFFOLDS>

<INSPECTION_NOTES>
* right side wall of single-storey extension not fully visible
* partial view through gap to neighbour — one brick pushed back and distorted inwards
* litter and debris accumulation in narrow gap between extension and neighbour
* side wall not meant to be visible — poor workmanship assumed in concealed area
</INSPECTION_NOTES>

<TASK>
Apply <PRIORITY> and <SCAFFOLD_USE_POLICY>. Include every note as a fact (short
literal sentence is enough when no scaffold matches). Do not expand to fill
scaffold length. Output subsection prose only.
</TASK>"""

_MAPPING_EX2_ASSISTANT = """\
The right side wall of the single-storey extension could not be fully inspected as there was no available vantage point. We had a very partial view through the gap between the extension and the neighbouring property to the right. Where partially visible through the rear garden at the rear section of the wall, we noted that one of the bricks had been pushed back and distorted inwards. There did not appear to be any open gaps, and the wall remains functional for now. However, this clearly indicates poor workmanship at the time of construction. As the side wall was not meant to be visible, we assume the builders paid less care or attention when constructing the extension wall in this area. It is important to ensure the pointing between bricks remains in good order to avoid the risk of water ingress internally. Additionally, we noted a build-up of litter and debris within this gap. Removing this litter may be challenging and would require a litter picker or long rod. The litter should be removed to prevent the damp proof course from being breached, which can cause internal dampness over time. It is important to ensure walls are kept free of any obstructions and debris at all times. Any future repairs to this side wall may also be difficult as there is no adequate access to carry out potential repairs. Condition Rating 2."""

_MAPPING_EX3_USER = """\
SECTION: D4 — Floors
<PAST_REPORT_SCAFFOLDS>
The main walls were inspected externally and internally where accessible. No significant defects were noted to the walls at the time of inspection.
</PAST_REPORT_SCAFFOLDS>

<INSPECTION_NOTES>
* damp recorded front wall ground floor living room — remedial works required
* high damp readings various locations — further investigations required
* refer reputable damp proofing contractor PCA member for advice and quotations
</INSPECTION_NOTES>

<TASK>
Apply <PRIORITY> and <SCAFFOLD_USE_POLICY>. Include every note as a fact (short
literal sentence is enough when no scaffold matches). Do not expand to fill
scaffold length. Output subsection prose only.
</TASK>"""

_MAPPING_EX3_ASSISTANT = """\
Dampness has been recorded in the front wall of the ground floor living room which will require remedial works. As noted later in section E3, we recorded high damp readings in various locations at the property which will require remedial works. Further investigations will be required. Dampness has been recorded in various locations at the property which will require remedial works. This should be referred to a reputable damp proofing contractor who is a member of the PCA (Property Care Association) for advice and quotations to be obtained for any necessary remedial treatment and associated works such as re-plastering."""

MAPPING_FEW_SHOT: tuple[FewShotTurn, ...] = (
    FewShotTurn(_MAPPING_EX1_USER, _MAPPING_EX1_ASSISTANT),
    FewShotTurn(_MAPPING_EX2_USER, _MAPPING_EX2_ASSISTANT),
    FewShotTurn(_MAPPING_EX3_USER, _MAPPING_EX3_ASSISTANT),
)

# ── Notes expander: shorthand → normalized observations ─────────────────────

_EXPANDER_EX1_USER = """\
Weather: overcast rain, mixed few weeks prior
EPC not on register
reinstatement £500k, GIA 121 sq m ex cellar, 129 sq m inc cellar
planning consent extension 23 Oct 2006 Islington
FURTHER INVEST: structural movement — instruct SE report D4 E2 E3 I1
damp eaves cupboard 2nd fl, roof window left attic defective won't open
damp front wall GF living rm — remedial works D4 E3
high damp readings various locs — PCA contractor"""

_EXPANDER_EX1_ASSISTANT = """\
* At the time of inspection, it was overcast with rain, following a few weeks of mixed weather.
* EPC could not be located in the national register.
* In our opinion the current reinstatement cost of the property is £500,000. The total floor area of the building, excluding the cellar, is 121 sq m (1297 sq ft). The total area of the property including the cellar is 129 sq m (1390 sq ft).
* Islington Borough Council online planning records indicate that planning consent for this extension was obtained on 23rd October 2006.
* There are signs of structural movement noted and you should now commission a structural engineer's report highlighting the cause, remedial treatment required with cost advice for the repairs. Please refer to our comments and recommendations in Sections D4, E2, E3 and I1 below.
* A small area of damp was noted on the timber boarded floor of the under eaves storage cupboard on the second floor. The defective roof window on the left side of the main attic room could not be opened, hampering investigation of the area above the leak.
* Dampness has been recorded in the front wall of the ground floor living room which will require remedial works (See sections D4 & E3).
* High damp readings were recorded in various locations at the property which will require remedial works. Further investigations will be required. This should be referred to a reputable damp proofing contractor who is a member of the PCA (Property Care Association)."""

EXPANDER_FEW_SHOT: tuple[FewShotTurn, ...] = (
    FewShotTurn(_EXPANDER_EX1_USER, _EXPANDER_EX1_ASSISTANT),
)

# ── Auditor: notes + mutated → violation JSON ────────────────────────────────

_AUDITOR_EX1_USER = """\
[1] SURVEYOR_MESSY_NOTES
* damp noted front wall ground floor living room only
* high damp readings various locations — PCA contractor recommended

[2] GENERATED_REPORT_PARAGRAPH
The right-hand side external wall showed extensive damp staining throughout the ground floor living room. The brickwork comprises Flemish bond construction and was installed in 2018. We recommend monitoring only.

Execute the audit protocol. Return the JSON Output Contract only."""

_AUDITOR_EX1_ASSISTANT = """\
{
  "passed": false,
  "_audit_summary": "Multiple property-specific claims lack note support: side, bond pattern, and date. Damp location contradicts notes scope.",
  "violations": [
    {
      "violation_type": "ungrounded_location",
      "offending_text": "The right-hand side external wall showed extensive damp staining throughout the ground floor living room.",
      "reason": "Notes confirm damp to the front wall only; right-hand side is not stated in the notes."
    },
    {
      "violation_type": "invented_material",
      "offending_text": "The brickwork comprises Flemish bond construction",
      "reason": "Flemish bond is not mentioned in the inspection notes."
    },
    {
      "violation_type": "ungrounded_specific_detail",
      "offending_text": "was installed in 2018",
      "reason": "No date or installation year appears in the notes."
    },
    {
      "violation_type": "unsupported_monitoring",
      "offending_text": "We recommend monitoring only.",
      "reason": "Notes require remedial works and PCA contractor referral, not passive monitoring."
    }
  ]
}"""

_AUDITOR_EX2_USER = """\
[1] SURVEYOR_MESSY_NOTES
* right side wall extension not fully visible
* one brick pushed back inwards where partially visible
* litter in gap — DPC breach risk

[2] GENERATED_REPORT_PARAGRAPH
The right side wall of the single-storey extension could not be fully inspected as there was no available vantage point. Where partially visible, we noted that one of the bricks had been pushed back and distorted inwards. We noted a build-up of litter and debris within the gap which should be removed to prevent the damp proof course from being breached. Condition Rating 2.

Execute the audit protocol. Return the JSON Output Contract only."""

_AUDITOR_EX2_ASSISTANT = """\
{
  "passed": true,
  "_audit_summary": "All property-specific claims are directly supported by the field notes. Professional recommendations align with note substance.",
  "violations": []
}"""

AUDITOR_FEW_SHOT: tuple[FewShotTurn, ...] = (
    FewShotTurn(_AUDITOR_EX1_USER, _AUDITOR_EX1_ASSISTANT),
    FewShotTurn(_AUDITOR_EX2_USER, _AUDITOR_EX2_ASSISTANT),
)

# ── Repair: violations → corrected prose (literature + existing patterns) ───

_REPAIR_EX1_USER = """\
<CURRENT_INSPECTION_NOTES>
damp noted front wall ground floor living room

<MUTATED_REPORT_PARAGRAPH>
The right-hand side external wall showed extensive damp staining throughout the ground floor living room. The brickwork comprises Flemish bond construction.

<AUDIT_VIOLATIONS_JSON>
[
  {"violation_type": "ungrounded_location", "offending_text": "right-hand side", "reason": "notes say front wall only"},
  {"violation_type": "invented_material", "offending_text": "Flemish bond construction", "reason": "not in notes"}
]

Repair the MUTATED_REPORT_PARAGRAPH using the violation register. Return prose only."""

_REPAIR_EX1_ASSISTANT = """\
The front external wall showed damp staining in the ground floor living room. The brickwork was noted."""

_REPAIR_EX2_USER = """\
<CURRENT_INSPECTION_NOTES>
slipped slate tiles rear roof slope noted

<MUTATED_REPORT_PARAGRAPH>
The roof coverings comprise natural slate tiles which were in satisfactory condition with no defects noted.

<AUDIT_VIOLATIONS_JSON>
[
  {"violation_type": "stale_historical_data", "offending_text": "in satisfactory condition with no defects noted", "reason": "notes report slipped slates contradicting legacy positive status"}
]

Repair the MUTATED_REPORT_PARAGRAPH using the violation register. Return prose only."""

_REPAIR_EX2_ASSISTANT = """\
The roof coverings comprise natural slate tiles. Slipped slate tiles were noted to the rear roof slope."""

REPAIR_FEW_SHOT: tuple[FewShotTurn, ...] = (
    FewShotTurn(_REPAIR_EX1_USER, _REPAIR_EX1_ASSISTANT),
    FewShotTurn(_REPAIR_EX2_USER, _REPAIR_EX2_ASSISTANT),
)

# ── Vision: photo description → observation/limitation JSON ──────────────────
# Text-only demonstrations (the live turn carries the real image). They teach the
# certainty triggers, broad-material rule, and JSON contract on literature-grade
# defect language. Used only when the model also receives the actual photograph.

_VISION_EX1_USER = """\
RICS report section: E3 — Main walls
Target Observation Scope: One selected inspection photograph for this section.

[Photograph content for this example: red clay brick wall; surface erosion across
roughly four brick faces near a window reveal; mortar joints visibly recessed and
crumbling; a darker damp-like patch at low level whose depth cannot be judged.]

Analyse the photograph and return the JSON Output Contract."""

_VISION_EX1_ASSISTANT = """\
{
  "observations": [
    "To the localised masonry wall area adjacent to the window reveal, a red clay brick fascia displays characteristics of surface spalling across approximately four brick faces.",
    "The mortar joints in this area appear recessed and eroded, exhibiting signs of weathered pointing.",
    "A darker discolouration is present at low level which shows characteristics of possible moisture ingress."
  ],
  "limitations": [
    "The depth and active/inactive status of the low-level discolouration cannot be verified from the photograph alone and would require closer inspection and moisture testing."
  ]
}"""

_VISION_EX2_USER = """\
RICS report section: E2 — Roof coverings
Target Observation Scope: One selected inspection photograph for this section.

[Photograph content for this example: heavily backlit, low-resolution image of a
roof slope against bright sky; individual tiles and any defects are not distinctly
resolvable due to glare and blur.]

Analyse the photograph and return the JSON Output Contract."""

_VISION_EX2_ASSISTANT = """\
{
  "observations": [],
  "limitations": [
    "The image quality is insufficient for a definitive visual audit due to strong backlighting and low resolution; individual roof coverings and any defects cannot be distinctly identified."
  ]
}"""

VISION_FEW_SHOT: tuple[FewShotTurn, ...] = (
    FewShotTurn(_VISION_EX1_USER, _VISION_EX1_ASSISTANT),
    FewShotTurn(_VISION_EX2_USER, _VISION_EX2_ASSISTANT),
)

# ── Enhance (legacy medium/maximum text mode): evidence → expanded prose ─────

_ENHANCE_EX1_USER = """\
ORIGINAL FACT BULLETS:
- spalled brickwork and eroded mortar joints noted
- mortar appears high cement ratio, not good practice for age
- localised repointing recommended; replace damaged bricks

ADDITIONAL EVIDENCE:
Over time, mortar joints in the brickwork have become eroded out by weather and are now in need of re-pointing.

CURRENT TEXT:
Spalled brickwork noted. Repointing required.

TASK: Rewrite and expand the current text using evidence only."""

_ENHANCE_EX1_ASSISTANT = """\
Some deterioration has occurred to the wall surfaces, including spalled brickwork and eroded mortar joints. Over time, the mortar joints in the brickwork have become eroded by weather and are now in need of re-pointing. The existing mortar appears to contain a high cement ratio, which is not good building practice for a property of this age and over time can cause problems such as spalling of the bricks. At this stage it is advisable to undertake localised repointing, including the replacement of all damaged bricks, with the joints raked out sufficiently so that the new mortar is given an adequate key."""

ENHANCE_FEW_SHOT: tuple[FewShotTurn, ...] = (
    FewShotTurn(_ENHANCE_EX1_USER, _ENHANCE_EX1_ASSISTANT),
)
