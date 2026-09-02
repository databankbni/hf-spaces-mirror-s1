"""Adversarial semantic auditor prompt — read-only diagnostic judge (Prompt 3A).

Regex PII pass runs first in ``core.grounding_checker``; the LLM pass returns
``passed`` and ``violations`` JSON only — no text mutation.
"""

from __future__ import annotations

from backend.prompts.prompt_few_shot_examples import AUDITOR_COT_PROTOCOL
from backend.prompts.prompt_message_assembly import append_cot_to_system

AUDITOR_SYSTEM_PROMPT = """
<ROLE>
You are an isolated, read-only semantic audit engine for a UK Chartered Surveying firm.
Cross-examine claims in the mutated report paragraph against the surveyor notes and
emit a JSON violation register. You are a diagnostic judge, not an editor — never
alter, repair, or rewrite the text.
</ROLE>

<INPUT_CONTRACT>
Inputs for each audit:
  - <CURRENT_INSPECTION_NOTES>
  - <BASELINE_PARAGRAPH> (optional; used only for stale/contradiction checks)
  - <MUTATED_REPORT_PARAGRAPH>
</INPUT_CONTRACT>

<GROUNDING_RULE>
Flag any property-specific claim in the mutated paragraph that is not backed by the
notes. NEVER benign without notes backing: side / hand / orientation / position;
material or fabric; mechanism, operation or product type; structural relationship
(attached / integral / detached / separate); measurement, dimension, count, date,
brand or named entity; defect or condition state; specialist action; engineering
cause; or monitoring instruction the notes did not order.

Benign when notes are silent: generic hedging with NO specific value (e.g. "appears
generally sound"), and GENERAL surveying principles that assert nothing about this
property's instance.

Actionable specialist recommendations (consult / instruct / obtain quotes /
engineer / contractor) require notes backing. Legacy baseline wording that
contradicts the notes (e.g. "satisfactory" vs noted deterioration) is
stale_historical_data / stale_condition_rating as appropriate.
</GROUNDING_RULE>

<VIOLATION_TAXONOMY>
Categorize each failure as exactly one of:
  - "invented_defect"
  - "invented_material"
  - "invented_mechanism"
  - "invented_structural_relationship"
  - "ungrounded_location"
  - "ungrounded_specific_detail"
  - "invented_specialist_action"
  - "unsupported_cause"
  - "stale_historical_data"
  - "stale_condition_rating"
  - "placeholder_leakage"
  - "non_british_english"
  - "unsupported_monitoring"
</VIOLATION_TAXONOMY>

<OUTPUT_CONTRACT>
Return EXACTLY ONE valid JSON object. No markdown fences. No preamble.

{
  "passed": boolean,
  "violations": [
    {
      "violation_type": "string (from VIOLATION_TAXONOMY)",
      "offending_text": "string (exact phrase from the mutated paragraph)",
      "reason": "string (one sentence)"
    }
  ]
}
</OUTPUT_CONTRACT>
"""

# Backward-compatible aliases used by tests and inventory.
GROUNDING_SYSTEM_PROMPT = AUDITOR_SYSTEM_PROMPT
GROUNDING_SYSTEM = AUDITOR_SYSTEM_PROMPT

GROUNDING_USER_TEMPLATE = """
[1] SURVEYOR_MESSY_NOTES
{observations_bulleted}

[2] GENERATED_REPORT_PARAGRAPH
{mapped_paragraph}

Return the JSON Output Contract only.
"""


def _observations_bulleted(observations: list[str]) -> str:
    lines = [o.strip() for o in observations if o.strip()]
    if not lines:
        return "(none)"
    return "\n".join(f"* {line}" for line in lines)


# Re-audit anchor: on the 2nd+ pass the auditor sees the prior violation
# register so it confirms earlier faults are fixed instead of raising fresh
# stylistic nits.
_REAUDIT_ANCHOR_TEMPLATE = """
[4] PRIOR_VIOLATIONS_ALREADY_FLAGGED
The following were raised on the previous pass and the text has since been
repaired. Confirm each is resolved and catch any remaining ungrounded property
fact. Do NOT raise new purely stylistic objections against already-grounded text.
{prior_violations_bulleted}
"""


def _prior_violations_bulleted(prior_violations: list[dict[str, str]] | None) -> str:
    if not prior_violations:
        return ""
    lines: list[str] = []
    for item in prior_violations:
        if not isinstance(item, dict):
            continue
        vtype = str(item.get("violation_type") or "").strip() or "violation"
        offending = str(item.get("offending_text") or "").strip()
        snippet = f': "{offending[:120]}"' if offending else ""
        lines.append(f"* [{vtype}]{snippet}")
    return "\n".join(lines)


def build_grounding_messages(
    mutated_paragraph: str,
    source_observations: list[str],
    source_rag_paragraphs: list[str] | None = None,
    *,
    baseline_paragraph: str | None = None,
    prior_violations: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Build OpenAI messages for the read-only adversarial semantic auditor.

    Leaf-scoped only: system instructions + this section's notes/draft/baseline.
    No cross-section few-shots. CoT is appended only when
    ``PROMPT_CHAIN_OF_THOUGHT_ENABLED`` is true.
    """
    baseline = (baseline_paragraph or "").strip()
    if not baseline and source_rag_paragraphs:
        baseline = (source_rag_paragraphs[0] or "").strip()

    audit_message = GROUNDING_USER_TEMPLATE.format(
        observations_bulleted=_observations_bulleted(source_observations),
        mapped_paragraph=mutated_paragraph.strip(),
    ).strip()
    if baseline:
        audit_message += f"""

[3] BASELINE_PARAGRAPH
{baseline}"""

    prior_bulleted = _prior_violations_bulleted(prior_violations)
    if prior_bulleted:
        audit_message += (
            "\n"
            + _REAUDIT_ANCHOR_TEMPLATE.format(
                prior_violations_bulleted=prior_bulleted
            ).rstrip()
        )

    return [
        {
            "role": "system",
            "content": append_cot_to_system(
                AUDITOR_SYSTEM_PROMPT.strip(), AUDITOR_COT_PROTOCOL
            ),
        },
        {"role": "user", "content": audit_message.strip()},
    ]
