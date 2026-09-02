"""The sub-topic list a surveyor sees and is graded against.

This is the *note-entry* taxonomy: the official Home Survey Level 3 schema, 41
sub-topics across 7 groups. It is deliberately a separate layer from
:mod:`backend.content_based.taxonomy`, which stays the *knowledge-base* taxonomy
that ingested chunks are tagged with.

Why two layers. The schema is authored for the report a client reads, and note
entry plus grading have to match it one for one. The v2 knowledge taxonomy
diverges on purpose — it merges heating with hot water, renames bathroom fittings
to sanitaryware, and collapses the whole of legal / risks / energy into three
buckets — all of which is better for retrieval and worse for matching the schema.
Rather than migrate stored chunk metadata, :data:`REVIEW_TO_V2` bridges review
codes onto the v2 sub-topics that own their chunks. The map is total and
many-to-one, and the reverse direction is deliberately partial.

**Codes are globally unique.** Catch-all chips and the energy Heating chip use
disambiguated labels (Outside Other, Inside Other, Grounds Other, Risks Other,
Energy Heating) so the UI is unambiguous. Every layer below keys off the code
alone — ``SUBTOPIC_LABELS``, ``state.sections[code]``, the ``bullets-${code}``
DOM ids, ``RUBRICS``. Import-time guards below make a future duplicate id a hard
failure rather than a silent overwrite.

**The list is scoped by property type.** :data:`SCHEMAS` says which groups a house
report and a flat report each show, and every read helper takes a
``property_type``. Both currently use all 7 groups, because the practice's house
schema and its flat schema share the same element hierarchy for note entry.
The *About the property* group is omitted from note entry — property-context rows
are not filed or graded here. See ADR 0011.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from backend.content_based import taxonomy
from backend.domain.property_type import PROPERTY_TYPES, try_canonical_property_type

REVIEW_TAXONOMY_VERSION = "r2.3"

# Ordered groups, each with its fixed sub-topics (id + label only). Catch-all
# "Other" chips and the second Heating chip use disambiguated on-screen labels
# (Outside Other, Energy Heating, …) while codes stay globally unique.
REVIEW_GROUPS: tuple[dict[str, Any], ...] = (
    {
        "id": "outside",
        "label": "Outside the property",
        "subtopics": (
            {"id": "chimney_stacks", "label": "Chimney stacks"},
            {"id": "roof_coverings", "label": "Roof coverings"},
            {"id": "rainwater_pipes_gutters", "label": "Rainwater pipes and gutters"},
            {"id": "main_walls", "label": "Main walls"},
            {"id": "windows", "label": "Windows"},
            {
                "id": "outside_doors",
                "label": "Outside doors (including patio doors)",
            },
            {
                "id": "conservatory_porches",
                "label": "Conservatory and porches",
            },
            {
                "id": "other_joinery_finishes",
                "label": "Other joinery and finishes",
            },
            {"id": "outside_other", "label": "Outside Other"},
        ),
    },
    {
        "id": "inside",
        "label": "Inside the property",
        "subtopics": (
            {"id": "roof_structure", "label": "Roof structure"},
            {"id": "ceilings", "label": "Ceilings"},
            {"id": "walls_partitions", "label": "Walls and partitions"},
            {"id": "floors", "label": "Floors"},
            {
                "id": "fireplaces_flues",
                "label": "Fireplaces, chimney breast and flues",
            },
            {
                "id": "built_in_fittings",
                "label": "Built-in fittings (e.g. wardrobes)",
            },
            {
                "id": "woodwork_joinery",
                "label": "Woodwork (e.g. staircase and joinery)",
            },
            {
                "id": "bathroom_kitchen_fittings",
                "label": "Bathroom and kitchen fittings",
            },
            {"id": "inside_other", "label": "Inside Other"},
        ),
    },
    {
        "id": "services",
        "label": "Services",
        "subtopics": (
            {"id": "electricity", "label": "Electricity"},
            {"id": "gas_oil", "label": "Gas/oil"},
            {"id": "water", "label": "Water"},
            {"id": "heating", "label": "Heating"},
            {"id": "water_heating", "label": "Water heating"},
            {"id": "drainage", "label": "Drainage"},
            {"id": "common_services", "label": "Common services"},
            {
                "id": "other_services_features",
                "label": "Other services/features",
            },
        ),
    },
    {
        "id": "grounds",
        "label": "Grounds (including shared areas for flats)",
        "subtopics": (
            {"id": "garage", "label": "Garage"},
            {
                "id": "outbuildings",
                "label": "Permanent outbuildings and other structures",
            },
            {"id": "grounds_other", "label": "Grounds Other"},
        ),
    },
    {
        "id": "legal_advisors",
        "label": "Issues for your legal advisors",
        "subtopics": (
            {"id": "regulation", "label": "Regulation"},
            {"id": "guarantees", "label": "Guarantees"},
            {"id": "other_matters", "label": "Other matters"},
        ),
    },
    {
        "id": "risks",
        "label": "Risks",
        "subtopics": (
            {"id": "risks_building", "label": "Risks to the building"},
            {"id": "risks_grounds", "label": "Risks to the grounds"},
            {"id": "risks_people", "label": "Risks to people"},
            {"id": "risks_other", "label": "Risks Other"},
        ),
    },
    {
        "id": "energy_efficiency",
        "label": "Energy efficiency",
        "subtopics": (
            {"id": "insulation", "label": "Insulation"},
            {"id": "energy_heating", "label": "Energy Heating"},
            {"id": "lighting", "label": "Lighting"},
            {"id": "ventilation", "label": "Ventilation"},
            {"id": "energy_general", "label": "General"},
        ),
    },
)

# v2 sub-topics a review code should retrieve from. Only codes whose v2 identity is
# not recoverable from ``taxonomy.SUBTOPIC_ALIASES`` need an entry here.
#
# v2 merged what this schema splits: the whole of Issues for your legal advisors
# lands on ``legal_regulatory``, all four Risks on ``risks``, and everything under
# Energy efficiency on ``energy``. That is lossy, and deliberately so — it affects
# only which chunks retrieval reads, never which box a note goes in or how it is
# graded. Codes with no v2 concept at all fall to the catch-all rather than being
# forced onto an unrelated element.
_V2_OVERRIDES: dict[str, tuple[str, ...]] = {
    # Outside / Inside
    "outside_other": (taxonomy.CATCH_ALL_SUBTOPIC,),
    "bathroom_kitchen_fittings": ("sanitaryware",),
    "inside_other": (taxonomy.CATCH_ALL_SUBTOPIC,),
    # Services
    "water": ("water_supply",),
    "other_services_features": ("common_services",),
    # Grounds — v2 split the old catch-all G3 in two, and a single "other grounds"
    # note can legitimately be about either half, so query both.
    "grounds_other": ("garden_landscaping", "drives_paths_patios"),
    # Issues for your legal advisors
    "regulation": ("legal_regulatory",),
    "guarantees": ("legal_regulatory",),
    "other_matters": ("legal_regulatory",),
    # Risks
    "risks_building": ("risks",),
    "risks_grounds": ("risks",),
    "risks_people": ("risks",),
    "risks_other": ("risks",),
    # Energy efficiency
    "insulation": ("energy",),
    "energy_heating": ("energy",),
    "lighting": ("energy",),
    "ventilation": ("energy",),
    "energy_general": ("energy",),
}

# Which review code a shared v2 sub-topic maps *back* to. Without this the reverse
# map takes whichever code appears first in display order, which would send every
# energy classification to the wrong chip.
#
# Where the schema has both a descriptive chip and a condition chip for the same
# v2 sub-topic, the condition chip wins: the fallback classifier is reading a site
# observation, and observations belong with the element they describe.
_REVERSE_PREFERENCE: dict[str, str] = {
    "legal_regulatory": "regulation",
    "risks": "risks_building",
    "energy": "energy_general",
    "common_services": "common_services",
    "heating_hot_water": "heating",
    "garden_landscaping": "grounds_other",
}

# v2 sub-topics that must never reverse-map. The catch-all holds content the schema
# has no home for, and filing it under some group's "Other" would put notes
# somewhere the surveyor never agreed to; it is reported as unassigned instead.
_NO_REVERSE: frozenset[str] = frozenset({taxonomy.CATCH_ALL_SUBTOPIC})


def _fixed_rows() -> list[tuple[str, dict[str, Any]]]:
    return [
        (str(group["id"]), dict(sub))
        for group in REVIEW_GROUPS
        for sub in group["subtopics"]
    ]


GROUP_LABELS: dict[str, str] = {
    str(g["id"]): str(g["label"]) for g in REVIEW_GROUPS
}

ORDERED_GROUP_IDS: tuple[str, ...] = tuple(GROUP_LABELS)

SUBTOPIC_LABELS: dict[str, str] = {
    str(sub["id"]): str(sub["label"]) for _gid, sub in _fixed_rows()
}

SUBTOPIC_HINTS: dict[str, str] = {
    # Hints were removed from REVIEW_GROUPS; catalog/UI still expect a string —
    # fall back to the label so chips keep a non-empty helper line.
    str(sub["id"]): str(sub.get("hint") or sub["label"]) for _gid, sub in _fixed_rows()
}

SUBTOPIC_TO_GROUP: dict[str, str] = {
    str(sub["id"]): gid for gid, sub in _fixed_rows()
}

ORDERED_SUBTOPIC_IDS: tuple[str, ...] = tuple(SUBTOPIC_LABELS)

# ── Import-time invariants ────────────────────────────────────────────────────
# Catch-all and Heating chips already use distinct ids; a copy-paste that reuses
# an id would silently overwrite a whole chip — the dicts above are keyed by code
# and would simply lose one. Fail loudly instead.
_duplicate_codes = sorted(
    code
    for code, count in Counter(str(sub["id"]) for _gid, sub in _fixed_rows()).items()
    if count > 1
)
if _duplicate_codes:  # pragma: no cover — import-time invariant
    raise RuntimeError(
        f"Duplicate review sub-topic ids (each chip needs its own): {_duplicate_codes}"
    )

# "Grounds" is both a group and a sub-topic in the schema. Sharing one slug would
# make ``group_for`` ambiguous and break the mint-a-section path in the UI.
_shadowed = sorted(set(ORDERED_SUBTOPIC_IDS) & set(ORDERED_GROUP_IDS))
if _shadowed:  # pragma: no cover — import-time invariant
    raise RuntimeError(
        f"Review sub-topic ids that collide with a group id: {_shadowed}"
    )


# ── Property type ─────────────────────────────────────────────────────────────
# Which groups each property type's schema shows, in display order.
#
# Both are the full 7 today. The element hierarchy belongs to the survey; the
# About the property group is omitted from note entry.
#
# When a type does drop or gain a group, change only its entry here. A *sub-topic*
# level difference (one flat-only chip, say) needs a per-type code filter as well —
# see ADR 0011 for why that is deliberately not built until there is one.
SCHEMAS: dict[str, tuple[str, ...]] = {
    "house": ORDERED_GROUP_IDS,
    "flat": ORDERED_GROUP_IDS,
}

# What an unknown or missing type resolves to. Matches the generate screen's
# default, so a client that never sends one behaves as it did before.
DEFAULT_PROPERTY_TYPE = "house"

_typeless = sorted(set(PROPERTY_TYPES) - set(SCHEMAS))
if _typeless:  # pragma: no cover — import-time invariant
    raise RuntimeError(
        f"Canonical property types with no review schema: {_typeless}"
    )

_stray_groups = sorted(
    {gid for gids in SCHEMAS.values() for gid in gids} - set(ORDERED_GROUP_IDS)
)
if _stray_groups:  # pragma: no cover — import-time invariant
    raise RuntimeError(
        f"Review schema names groups that do not exist: {_stray_groups}"
    )


def resolve_property_type(property_type: str | None = None) -> str:
    """Canonical ``house`` / ``flat``, falling back to the default.

    Deliberately lenient: note entry is not the place to reject a report over a
    missing query parameter, and every type currently shows the same chips.
    """
    return try_canonical_property_type(property_type) or DEFAULT_PROPERTY_TYPE


def groups_for(property_type: str | None = None) -> tuple[str, ...]:
    """Ordered group ids this property type's schema shows."""
    return SCHEMAS[resolve_property_type(property_type)]


def _v2_targets(code: str) -> tuple[tuple[str, str], ...]:
    """The ``(topic_id, subtopic_id)`` pairs in the v2 taxonomy for a review code."""
    override = _V2_OVERRIDES.get(code)
    ids = override if override else (taxonomy.resolve_subtopic_id(code),)
    return tuple(
        (taxonomy.topic_for_subtopic(sid), sid) for sid in ids if sid
    )


# review code -> every v2 (topic_id, subtopic_id) that may hold its content.
REVIEW_TO_V2: dict[str, tuple[tuple[str, str], ...]] = {
    code: _v2_targets(code) for code in ORDERED_SUBTOPIC_IDS
}

_unbridged = sorted(code for code, targets in REVIEW_TO_V2.items() if not targets)
if _unbridged:  # pragma: no cover — import-time invariant
    raise RuntimeError(
        "Review sub-topics with no v2 home (add a taxonomy alias or a "
        f"_V2_OVERRIDES entry): {_unbridged}"
    )

# The reverse direction, used only to place fallback classifier output on the
# review panel. It is partial on purpose: v2 carries sub-topics the schema has no
# chip for, and the catch-all is excluded outright, so those come back "" and are
# surfaced as unassigned instead of being filed somewhere unagreed.
V2_TO_REVIEW: dict[str, str] = {
    sub: code
    for sub, code in _REVERSE_PREFERENCE.items()
    if sub not in _NO_REVERSE and code in SUBTOPIC_LABELS
}
for _code in ORDERED_SUBTOPIC_IDS:
    for _topic, _sub in REVIEW_TO_V2[_code]:
        if _sub not in _NO_REVERSE:
            V2_TO_REVIEW.setdefault(_sub, _code)


def from_v2(topic_id: str, subtopic_id: str) -> str:
    """Review code for a v2 classification, or '' when the schema has no home for it.

    Rooms are not part of the schema, so a room classification returns "" and the
    note is reported as unassigned rather than filed under an element the surveyor
    did not choose.
    """
    if (topic_id or "").strip().lower() == taxonomy.TOPIC_ROOMS_DESCRIBED:
        return ""
    return V2_TO_REVIEW.get((subtopic_id or "").strip().lower(), "")


# ── Public helpers ────────────────────────────────────────────────────────────
def ordered_groups(property_type: str | None = None) -> list[tuple[str, str]]:
    """``(group_id, label)`` in display order, for this property type."""
    return [(gid, GROUP_LABELS[gid]) for gid in groups_for(property_type)]


def group_labels_for(property_type: str | None = None) -> dict[str, str]:
    """Group id to label for this property type, so the payload has no dead groups."""
    return {gid: GROUP_LABELS[gid] for gid in groups_for(property_type)}


def subtopics_for_group(
    group_id: str,
    property_type: str | None = None,
) -> list[tuple[str, str]]:
    """Ordered ``(code, label)`` for a group, empty when the type omits it."""
    if group_id not in groups_for(property_type):
        return []
    return [
        (str(sub["id"]), str(sub["label"]))
        for group in REVIEW_GROUPS
        if str(group["id"]) == group_id
        for sub in group["subtopics"]
    ]


def is_fixed_subtopic(code: str, property_type: str | None = None) -> bool:
    """True when this code is a chip on this property type's schema.

    Stage A validates against this, so a code from a group the type does not show
    cannot earn a chip — the same closed-list guarantee, narrowed to the report in
    front of the surveyor.
    """
    slug = (code or "").strip().lower()
    if slug not in SUBTOPIC_LABELS:
        return False
    return SUBTOPIC_TO_GROUP[slug] in groups_for(property_type)


def group_for(code: str) -> str:
    return SUBTOPIC_TO_GROUP.get((code or "").strip().lower(), "")


def label_for(code: str) -> str:
    slug = (code or "").strip().lower()
    return SUBTOPIC_LABELS.get(slug, "")


def hint_for(code: str) -> str:
    return SUBTOPIC_HINTS.get((code or "").strip().lower(), "")


def sort_key(code: str) -> tuple[int, int]:
    """Order a code by group then position, so panels and exports agree."""
    slug = (code or "").strip().lower()
    group = group_for(slug)
    gidx = ORDERED_GROUP_IDS.index(group) if group in ORDERED_GROUP_IDS else len(
        ORDERED_GROUP_IDS
    )
    try:
        return (gidx, ORDERED_SUBTOPIC_IDS.index(slug))
    except ValueError:
        return (gidx, len(ORDERED_SUBTOPIC_IDS))


def to_v2(code: str) -> tuple[str, str]:
    """Primary v2 ``(topic_id, subtopic_id)`` for a review code, for bucketing."""
    targets = REVIEW_TO_V2.get((code or "").strip().lower())
    return targets[0] if targets else taxonomy.catch_all()


def to_v2_all(code: str) -> tuple[tuple[str, str], ...]:
    """Every v2 ``(topic_id, subtopic_id)`` a review code may need to retrieve from."""
    slug = (code or "").strip().lower()
    targets = REVIEW_TO_V2.get(slug)
    if targets:
        return targets
    return (to_v2(slug),) if slug else ()


def v2_subtopic_ids(codes: list[str] | set[str] | tuple[str, ...]) -> set[str]:
    """Flatten review codes to the v2 sub-topic ids that back them."""
    out: set[str] = set()
    for code in codes:
        for _topic_id, sub_id in to_v2_all(code):
            if sub_id:
                out.add(sub_id)
    return out


def catalog_sections(property_type: str | None = None) -> list[dict[str, str]]:
    """The catalog rows for this property type, in display order."""
    allowed = set(groups_for(property_type))
    return [
        {
            "code": str(sub["id"]),
            "group": gid,
            "title": str(sub["label"]),
            "hint": str(sub.get("hint") or sub["label"]),
        }
        for gid, sub in _fixed_rows()
        if gid in allowed
    ]
