"""The practice's note-quality rubric, transcribed verbatim.

This is the *only* standard the grader is allowed to apply. Each entry is the
practice's own prose, copied unchanged from the source document and keyed by the
review sub-topic id it grades (see :mod:`backend.content_based.review_taxonomy`).
:mod:`backend.note_quality.prompts` injects this text into the model verbatim.

Do not paraphrase, summarise or "tidy" these strings. Wording like "meaningful
inspection assessment", "an explicit statement confirming absence is sufficient"
and "The AI must not require information about concealed flues" is normative —
rewording it silently changes what the firm grades its surveyors on.
``backend/tests/test_note_quality.py`` asserts several of these phrases reach
the prompt intact.

About the property is omitted from the note-entry schema. Every remaining sub-topic
is graded against the practice rubric.

Rooms are no longer part of the schema (see ADR 0009), but the practice's four room
rubrics are kept in :data:`_RETIRED` so its wording survives if rooms return.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.content_based import review_taxonomy
from backend.note_quality.rubric_entries import ENTRIES as _SOURCE

# Live Green/Yellow/Red prose is in rubric_entries.py so this module stays the
# wiring: ungraded set, version, retired rooms, and rubric_for().

# Bumped whenever the practice reissues the document, or whenever entries are
# re-keyed onto a new schema as here, so cached grades can be invalidated and a
# stale grade is never silently trusted.
RUBRIC_VERSION = "practice-2026-08d"

# Sub-topics shown to the surveyor but deliberately not graded, because the source
# document does not cover them. They render neutral and stay out of the tally.
#
# Keep this exhaustive: a code that is neither here nor in :data:`RUBRICS` would be
# silently ungraded, which reads on screen as "no criteria" and is indistinguishable
# from a typo. Tests assert these plus :data:`RUBRICS` cover all note-entry codes.
UNGRADED_CODES: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Rubric:
    """One sub-topic's grading criteria, exactly as the practice wrote it."""

    code: str
    label: str
    text: str
    relevant: tuple[str, ...]


_RELEVANT_HEADING = "Relevant information may include:"


def _relevant_items(text: str) -> tuple[str, ...]:
    """The 'relevant information may include' bullets, for present/missing reporting.

    Parsed out of the verbatim text rather than duplicated beside it, so the list
    the UI shows and the list the model reads can never drift apart.
    """
    _, _, after = text.partition(_RELEVANT_HEADING)
    items: list[str] = []
    for line in after.splitlines():
        stripped = line.strip()
        if stripped.startswith("* "):
            items.append(stripped[2:].strip())
        elif items and stripped:
            break  # prose resumed; the list is over
    return tuple(items)


# ── Section 6: Rooms Described (retired — see _RETIRED below) ─────────────────
_ROOM_DEFAULT = """**GREEN – Sufficient information**

Green if the notes provide sufficient combined information to give a meaningful overall assessment of the room and its condition.

Relevant information may include:

* Ceiling
* Walls
* Floor
* Windows
* Doors
* Joinery
* Finishes
* Dampness
* Cracking
* Movement
* Damage
* Room-specific observations

Not every surface or component needs to be individually described.

However, merely identifying finishes without meaningful condition or inspection observations would not normally be sufficient.

**YELLOW – Limited information**

Yellow if the room is identified and some finishes/components are described, but insufficient meaningful inspection information is available to provide an overall assessment.

Example Yellow:
“Bedroom has plastered walls, carpeted floor and uPVC window.”

**RED – No information**

Red if no meaningful inspection information regarding the room can be identified."""

_ROOM_BATHROOM = """**GREEN – Sufficient information**

Green if the notes provide sufficient information regarding the bathroom as a room and provide a meaningful assessment of its overall condition.

Relevant information may include:

* Overall room condition
* Ceiling
* Walls
* Flooring
* Ventilation
* Moisture/condensation
* Dampness
* Finishes
* Damage
* Room-specific defects

Not every component needs to be individually described.

This section concerns the bathroom as a room and should be assessed separately from **Bathroom and kitchen fittings**, which concerns the sanitary fixtures and fittings.

**YELLOW – Limited information**

Yellow if some room-level information is available but insufficient meaningful information is provided regarding the bathroom's overall condition.

**RED – No information**

Red if no meaningful room-level bathroom information can be identified."""

_ROOM_KITCHEN = """**GREEN – Sufficient information**

Green if the notes provide sufficient information regarding the kitchen and provide a meaningful assessment of its principal fittings, finishes and overall condition.

Relevant information may include:

* Units
* Worktops
* Floor
* Walls
* Ceiling
* Appliances where relevant
* Ventilation
* Moisture
* Damage
* Deterioration
* Significant defects

Not every unit, appliance or finish needs to be individually described.

**YELLOW – Limited information**

Yellow if the kitchen or its principal fittings are identified but insufficient meaningful information regarding condition or relevant inspection findings is provided.

Example Yellow:
“Fitted kitchen with wall and base units and laminate worktops.”

**RED – No information**

Red if no meaningful kitchen information can be identified."""

_ROOM_CONSERVATORY = """**GREEN – Sufficient information**

Green if the notes provide sufficient information regarding the conservatory's general construction/form and provide a meaningful assessment of its visible condition.

Relevant information may include:

* Construction
* Roof
* Glazing
* Walls
* Floor
* Doors/windows
* Movement
* Leakage
* Deterioration
* Significant defects
* Compliance concerns where identified
* Inspection limitations
* Repair requirements

Not every feature needs to be mentioned.

**YELLOW – Limited information**

Yellow if the conservatory is identified or its construction is described but insufficient meaningful information regarding condition or significant observations is provided.

Example Yellow:
“uPVC double-glazed conservatory with polycarbonate roof.”

**RED – No information**

Red if no meaningful information regarding the conservatory can be identified."""


_RETIRED: dict[str, tuple[str, str]] = {
    "_room_default": ("General Room Assessment", _ROOM_DEFAULT),
    "bathroom": ("Bathroom", _ROOM_BATHROOM),
    "kitchen": ("Kitchen", _ROOM_KITCHEN),
    "conservatory": ("Conservatory", _ROOM_CONSERVATORY),
}

RUBRICS: dict[str, Rubric] = {
    code: Rubric(code=code, label=label, text=text, relevant=_relevant_items(text))
    for code, (label, text) in _SOURCE.items()
}


def rubric_for(code: str) -> Rubric | None:
    """The rubric that grades ``code``, or ``None`` when it must not be graded.

    There is no default: a sub-topic with no criteria of its own is not graded
    against a neighbour's.
    """
    slug = (code or "").strip().lower()
    if not slug or slug in UNGRADED_CODES:
        return None
    return RUBRICS.get(slug)


def is_gradable(code: str) -> bool:
    return rubric_for(code) is not None


def rubric_label(code: str) -> str:
    """The heading the model should see: the review label, not the document's."""
    slug = (code or "").strip().lower()
    return review_taxonomy.label_for(slug)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower()).strip("_")


def relevant_item_ids(code: str) -> tuple[str, ...]:
    """Stable slugs for a rubric's checklist items, for present/missing reporting."""
    rubric = rubric_for(code)
    if rubric is None:
        return ()
    return tuple(_slug(item) for item in rubric.relevant)
