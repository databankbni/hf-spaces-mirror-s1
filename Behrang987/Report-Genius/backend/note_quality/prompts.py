"""Prompt construction for the note-quality judge.

The whole point of this module is that the practice's rubric reaches the model
*unchanged*, and *only* for the sub-topics in this call. Each chip contributes
its own entry from :mod:`backend.note_quality.rubric` — the Green definition,
the "relevant information may include" list, the caveats and the worked
examples — and nothing from another chip or another group. The system prompt
tells the model that this text is the entire standard. Anything the rubric does
not ask for must not count against a surveyor.
"""

from __future__ import annotations

import json

from backend.note_quality.rubric import rubric_for, rubric_label

SYSTEM_PROMPT = (
    "You are grading a UK residential surveyor's site notes for completeness.\n\n"
    "For each sub-topic you are given that sub-topic's own rubric and the notes "
    "filed under it. Decide green, yellow or red.\n\n"
    "RULES\n"
    "1. The supplied rubric is the ONLY standard. Do not apply RICS guidance, your "
    "own view of good practice, or any benchmark the rubric does not state.\n"
    "2. If the rubric does not ask for something, its absence is not a fault.\n"
    "3. The 'relevant information may include' list is a guide, not a checklist. "
    "The rubric says not every item needs to be mentioned; judge whether the "
    "combined information gives a meaningful inspection picture.\n"
    "4. Where a rubric says an express negative finding can be green (for example "
    "recording that no outbuildings are present), honour that.\n"
    "5. Where a rubric forbids requiring something that could not reasonably be "
    "established on a visual inspection, honour that too.\n"
    "6. Judge only the notes given for that sub-topic. Do not credit it for "
    "information filed under a different sub-topic, even when they share a "
    "report group.\n"
    "7. Return one judgment per sub-topic, in the order supplied, with the code "
    "copied exactly.\n"
    "8. 'present' and 'missing' must quote items from that sub-topic's own "
    "relevant-information list verbatim. Give at most four in 'missing': the ones "
    "that would most improve these notes."
)


def _rubric_block(code: str, notes: str) -> str:
    rubric = rubric_for(code)
    if rubric is None:  # pragma: no cover — orchestrator filters these out first
        raise KeyError(f"No rubric for sub-topic {code!r}")
    return (
        f"### SUB-TOPIC: {rubric_label(code)}  (code: {code})\n\n"
        "RUBRIC\n"
        f"{rubric.text}\n\n"
        "SITE NOTES FILED HERE\n"
        f"{notes.strip() or '(none)'}\n"
    )


def build_judge_messages(
    items: list[tuple[str, str]],
    group_label: str = "",
) -> list[dict[str, str]]:
    """System + user messages for one report group's ``(code, notes)`` pairs.

    Only these items' rubric texts are included. Neighbouring groups, empty
    chips and ungraded chips never reach the model.
    """
    body = "\n\n---\n\n".join(_rubric_block(code, notes) for code, notes in items)
    expected = json.dumps([code for code, _ in items], ensure_ascii=False)
    where = f' from the report group "{group_label}"' if group_label else ""
    user = (
        f"Grade these {len(items)} sub-topic(s){where}. "
        "Each sub-topic is paired with its own rubric only; do not apply a "
        "neighbour's criteria. "
        f"Return exactly these codes, in this order: {expected}\n\n"
        f"{body}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
