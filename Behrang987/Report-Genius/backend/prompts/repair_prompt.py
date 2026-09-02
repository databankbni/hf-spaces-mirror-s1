"""Surgical repair engine prompt — write-only text remediation (Prompt 3B)."""

from __future__ import annotations

import json
from typing import Any

from backend.prompts.prompt_few_shot_examples import REPAIR_COT_PROTOCOL
from backend.prompts.prompt_message_assembly import append_cot_to_system

REPAIR_SYSTEM_PROMPT = """
<ROLE>
You are a deterministic, write-only text repair engine. Accept a draft paragraph and a
JSON list of grounding/stylistic violations, apply targeted corrections, and output a
clean report paragraph. Follow the violation register; do not analyse or comment.
</ROLE>

<INPUT_CONTRACT>
  - <CURRENT_INSPECTION_NOTES>
  - <MUTATED_REPORT_PARAGRAPH>
  - <AUDIT_VIOLATIONS_JSON>
</INPUT_CONTRACT>

<REPAIR_RULES>
Process only the items in <AUDIT_VIOLATIONS_JSON>, in this order when they overlap:

1. DIALECT: swap non-British spellings to UK forms (colour, centre, aluminium, grey,
   analyse, mould, etc.).
2. PLACEHOLDERS / STALE RATINGS: remove placeholder_leakage tokens (XXX, TBC, …) and
   stale_condition_rating blocks.
3. MODIFIER PRUNE: for invented_material, ungrounded_location, invented_mechanism,
   invented_structural_relationship, or ungrounded_specific_detail — remove only the
   ungrounded words/clause, keep the grounded subject, heal grammar.
4. CLAUSE DROP: for invented_defect, invented_specialist_action, or unsupported_cause —
   remove the whole independent clause/sentence. Do not leave broken fragments.

CRITICAL:
- Do not invent facts, materials, causes, or soft generalisations ("typical for this age").
- If a phrase must be replaced to stay grammatical, use only: "the type/material could
  not be verified within the scope of this inspection" or "the element was observed."
- You may only subtract text or use those exact fallbacks — never add new nouns/defects.
</REPAIR_RULES>

<OUTPUT_CONTRACT>
Output the repaired continuous prose paragraph ONLY.
No JSON, markdown fences, preamble, or tracking tags.
</OUTPUT_CONTRACT>
"""


def build_repair_messages(
    *,
    mutated_paragraph: str,
    observations: list[str],
    violations: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Build OpenAI messages for the surgical repair-engine pass.

    Leaf-scoped only: system instructions + this section's notes/draft/violations.
    No cross-section few-shots. CoT appends only when
    ``PROMPT_CHAIN_OF_THOUGHT_ENABLED`` is true.
    """
    obs_text = "\n".join(o.strip() for o in observations if o.strip()) or "(none)"
    violations_json = json.dumps(violations, ensure_ascii=False, indent=2)

    user_message = f"""<CURRENT_INSPECTION_NOTES>
{obs_text}

<MUTATED_REPORT_PARAGRAPH>
{mutated_paragraph.strip()}

<AUDIT_VIOLATIONS_JSON>
{violations_json}
</AUDIT_VIOLATIONS_JSON>

Repair the MUTATED_REPORT_PARAGRAPH using the violation register. Return prose only."""

    return [
        {
            "role": "system",
            "content": append_cot_to_system(
                REPAIR_SYSTEM_PROMPT.strip(), REPAIR_COT_PROTOCOL
            ),
        },
        {"role": "user", "content": user_message.strip()},
    ]
