"""Canonical content taxonomy for the content-based report mode.

A fixed property-surveying topic taxonomy used to classify notes, past reports,
and standard paragraphs by *meaning* rather than by RICS Level 3 structure. This
is the content-mode analogue of :mod:`backend.domain.rics_level3_schema`.

Design:
  - Top-level topics are fixed (Location & Facilities, Outside, Inside, Services,
    Grounds, Rooms Described, Other / General Observations).
  - Element topics carry fixed sub-topics that line up with real RICS leaves, so a
    confidently detected RICS code can be reused as a strong prior.
  - "Rooms Described" carries dynamic room sub-topics discovered from content
    (kitchen, bathroom, named bedrooms, conservatory, ...).
  - Anything unmatched falls to "Other / General Observations" (``other/general``).

``topic_id`` / ``subtopic_id`` are stable STORAGE keys (snake_case). Do not rename
without migrating stored chunk metadata (see ``backend.rag.types.Chunk``).
"""

from __future__ import annotations

import re
from typing import Any

CONTENT_TAXONOMY_VERSION = "v2.0"

# ── Topic id constants ────────────────────────────────────────────────────────
TOPIC_LOCATION_FACILITIES = "location_facilities"
TOPIC_OUTSIDE = "outside"
TOPIC_INSIDE = "inside"
TOPIC_SERVICES = "services"
TOPIC_GROUNDS = "grounds"
TOPIC_ROOMS_DESCRIBED = "rooms_described"
TOPIC_OTHER = "other"

# Catch-all destination for content that matches no topic confidently.
CATCH_ALL_TOPIC = TOPIC_OTHER
CATCH_ALL_SUBTOPIC = "general"

# Topics whose sub-topics are discovered per report (room-by-room), not fixed.
DYNAMIC_SUBTOPIC_TOPICS = frozenset({TOPIC_ROOMS_DESCRIBED})


# ── The taxonomy ──────────────────────────────────────────────────────────────
# Sub-topics are chosen by what UK residential survey text actually talks about,
# not by RICS's element numbering (see adr/0007). Each sub-topic carries an
# ``anchor`` descriptor used by the fallback embedding classifier, and optionally
# ``rics`` — the RICS codes that map onto it, used only as an ingest hint.
#
# The mapping is deliberately many-to-one and deliberately incomplete. Codes that
# RICS uses as numbered catch-alls (D9, E9, G3) are left unmapped on purpose, so
# ``section_prior`` falls back to the parent letter and the content decides the
# sub-topic instead of everything piling into an "other" magnet bucket.
CONTENT_TAXONOMY: dict[str, Any] = {
    "version": CONTENT_TAXONOMY_VERSION,
    "topics": [
        {
            "id": TOPIC_LOCATION_FACILITIES,
            "label": "Location & Facilities",
            "order": 1,
            "rated": False,
            "dynamic_subtopics": False,
            "anchor": (
                "The property itself and where it sits: type, age and construction, "
                "setting, neighbourhood, local amenities, transport and environment."
            ),
            "subtopics": [
                {
                    "id": "property_description",
                    "label": "Property description",
                    "rics": ["B"],
                    "anchor": (
                        "Description of the property itself: house flat bungalow "
                        "maisonette, detached semi-detached terraced end-of-terrace, "
                        "approximate age and period built, number of storeys, form of "
                        "construction, brick under tile, accommodation schedule, "
                        "number of bedrooms and reception rooms, tenure freehold "
                        "leasehold, orientation."
                    ),
                },
                {
                    "id": "location",
                    "label": "Location",
                    "anchor": (
                        "Location and setting: address area, urban rural suburban, "
                        "position on road, aspect, nearby buildings, street scene."
                    ),
                },
                {
                    "id": "facilities",
                    "label": "Facilities",
                    "anchor": (
                        "Local facilities and amenities: shops, schools, transport "
                        "links, stations, parking, leisure and community services."
                    ),
                },
                {
                    "id": "local_environment",
                    "label": "Local environment",
                    "anchor": (
                        "Local environment: traffic, noise, air quality, flooding "
                        "history, radon, mining, nearby industry or nuisance."
                    ),
                },
            ],
        },
        {
            "id": TOPIC_OUTSIDE,
            "label": "Outside",
            "order": 2,
            "rated": True,
            "dynamic_subtopics": False,
            "anchor": (
                "Outside the property, external building elements: chimney stacks, "
                "roof coverings, gutters, walls, windows and external doors."
            ),
            "subtopics": [
                {"id": "chimney_stacks", "label": "Chimney stacks", "rics": ["D1"],
                 "anchor": "Chimney stacks, pots, flaunching, flashings, mortar, leaning stack."},
                {"id": "roof_coverings", "label": "Roof coverings", "rics": ["D2"],
                 "anchor": "Roof coverings, slates, tiles, felt, flat roof, ridge, valley, slipped tile, moss."},
                {"id": "rainwater_pipes_gutters", "label": "Rainwater pipes & gutters", "rics": ["D3"],
                 "anchor": "Rainwater pipes and gutters, downpipes, hoppers, overflow, blocked gutter."},
                {"id": "main_walls", "label": "Main walls", "rics": ["D4"],
                 "anchor": "Main external walls, cavity, brick, render, stone, pointing, DPC, cracking."},
                {"id": "windows", "label": "Windows", "rics": ["D5"],
                 "anchor": "External windows, glazing, frames, double glazing, FENSA, rot, misted panes."},
                {"id": "outside_doors", "label": "Outside doors", "rics": ["D6"],
                 "anchor": "Outside doors, patio doors, entrance doors, external door frames, security."},
                # D7 as a *structure* only. A conservatory as a described room lives
                # in Rooms Described; keeping both was a straight duplicate.
                {"id": "porches_extensions", "label": "Porches & extensions", "rics": ["D7"],
                 "anchor": "Porch, canopy, single-storey extension or glazed extension as a structure: "
                           "dwarf wall, polycarbonate or glazed roof, junction with the main wall, lean-to."},
                # Was "other joinery": 1102-char median of real prose in the corpus,
                # so it is a genuine element that was merely named as a leftover.
                {"id": "external_joinery", "label": "External joinery & finishes", "rics": ["D8"],
                 "anchor": "External joinery and finishes: fascias, soffits, bargeboards, cladding, "
                           "weatherboarding, external decoration and paintwork."},
            ],
        },
        {
            "id": TOPIC_INSIDE,
            "label": "Inside",
            "order": 3,
            "rated": True,
            "dynamic_subtopics": False,
            "anchor": (
                "Inside the property, internal building elements: roof structure, "
                "ceilings, walls, floors, fireplaces, fittings and woodwork."
            ),
            "subtopics": [
                {"id": "roof_structure", "label": "Roof structure", "rics": ["E1"],
                 "anchor": "Roof structure inside, trusses, rafters, purlins, loft timbers, roof void."},
                {"id": "ceilings", "label": "Ceilings", "rics": ["E2"],
                 "anchor": "Ceilings, plaster, lath and plaster, artex, cracking, staining, sagging."},
                {"id": "walls_partitions", "label": "Walls & partitions", "rics": ["E3"],
                 "anchor": "Internal walls and partitions, plaster, stud walls, damp patch, cracking."},
                {"id": "floors", "label": "Floors", "rics": ["E4"],
                 "anchor": "Floors, floorboards, suspended timber, solid concrete floor, springy, uneven."},
                {"id": "fireplaces_flues", "label": "Fireplaces & flues", "rics": ["E5"],
                 "anchor": "Fireplaces, chimney breasts, flues, hearth, lintel, open fire, gas fire."},
                # Condition of fitted carcassing as an element. Describing what a
                # room contains belongs to Rooms Described, not here.
                {"id": "built_in_fittings", "label": "Built-in fittings", "rics": ["E6"],
                 "anchor": "Condition of built-in fitted furniture as an element: carcasses, hinges, "
                           "drawer runners, worktop seals, built-in wardrobes, cupboards, shelving."},
                {"id": "woodwork_joinery", "label": "Woodwork & joinery", "rics": ["E7"],
                 "anchor": "Internal woodwork and joinery, staircase, skirting, architrave, internal doors."},
                # Renamed from bathroom_fittings so it stops colliding with the
                # bathroom *room*: this is the sanitaryware's condition.
                {"id": "sanitaryware", "label": "Sanitaryware", "rics": ["E8"],
                 "anchor": "Condition of sanitaryware: WC, cistern, wash basin, bath, shower tray and "
                           "screen, taps, wastes, silicone seals, tiling grout around fittings."},
            ],
        },
        {
            "id": TOPIC_SERVICES,
            "label": "Services",
            "order": 4,
            "rated": True,
            "dynamic_subtopics": False,
            "anchor": (
                "Building services: electricity, gas and oil, water supply, heating, "
                "hot water and drainage installations."
            ),
            "subtopics": [
                {"id": "electricity", "label": "Electricity", "rics": ["F1"],
                 "anchor": "Electricity, wiring, consumer unit, fusebox, circuits, earthing, RCD, EICR."},
                {"id": "gas_oil", "label": "Gas & oil", "rics": ["F2"],
                 "anchor": "Gas and oil supply, gas meter, oil tank, pipework, LPG, Gas Safe."},
                {"id": "water_supply", "label": "Water supply", "rics": ["F3"],
                 "anchor": "Water supply, mains water, stopcock, lead pipe, storage tank, pressure."},
                # F4 + F5 merged: a combi boiler is both, and a surveyor writes one note.
                {"id": "heating_hot_water", "label": "Heating & hot water", "rics": ["F4", "F5"],
                 "anchor": "Heating and hot water: central heating, boiler, combi boiler, radiators, "
                           "controls and thermostat, warm air, heat pump, hot water cylinder, "
                           "immersion heater, flue."},
                {"id": "drainage", "label": "Drainage", "rics": ["F6"],
                 "anchor": "Drainage, foul drain, surface water, manhole, sewer, septic tank, soakaway."},
                {"id": "common_services", "label": "Common services", "rics": ["F7"],
                 "anchor": "Common or shared services, landlord supplies, block heating, communal utilities."},
            ],
        },
        {
            "id": TOPIC_GROUNDS,
            "label": "Grounds",
            "order": 5,
            "rated": True,
            "dynamic_subtopics": False,
            "anchor": (
                "Grounds and outbuildings: garage, permanent outbuildings, sheds, "
                "boundaries, garden, driveways, paths and shared external areas."
            ),
            "subtopics": [
                {"id": "garage", "label": "Garage", "rics": ["G1"],
                 "anchor": "Garage, car port, vehicle storage, up-and-over door, integral garage."},
                {"id": "outbuildings", "label": "Outbuildings", "rics": ["G2"],
                 "anchor": "Permanent outbuildings, shed, workshop, barn, store, greenhouse."},
                # Moved out of Location & Facilities, where it overlapped "garden"
                # with the old other_grounds bucket.
                {"id": "boundaries", "label": "Boundaries", "rics": [],
                 "anchor": "Boundaries: boundary walls, fences, hedges, gates, retaining walls between "
                           "plots, ownership and responsibility for boundaries, party structures."},
                # G3 split into the two things it was actually holding.
                {"id": "garden_landscaping", "label": "Garden & landscaping", "rics": [],
                 "anchor": "Garden and landscaping: lawns, borders and planting, trees and their "
                           "proximity to the building, terracing, shared garden areas for flats."},
                {"id": "drives_paths_patios", "label": "Drives, paths & patios", "rics": [],
                 "anchor": "Driveway, hardstanding, paths, patio, steps, decking, external paving levels "
                           "relative to the damp-proof course."},
            ],
        },
        {
            "id": TOPIC_ROOMS_DESCRIBED,
            "label": "Rooms Described",
            "order": 6,
            "rated": False,
            "dynamic_subtopics": True,
            "anchor": (
                "Room-by-room description of individual rooms: kitchen, bathroom, "
                "bedrooms, living room, dining room, conservatory, hallway and landing."
            ),
            # Seed rooms; the classifier may mint additional slugged room sub-topics.
            "subtopics": [
                {"id": "kitchen", "label": "Kitchen",
                 "anchor": "Kitchen room description, units, worktops, appliances, layout."},
                {"id": "bathroom", "label": "Bathroom",
                 "anchor": "Bathroom room description, suite, tiling, ventilation, layout."},
                {"id": "bedroom", "label": "Bedroom",
                 "anchor": "Bedroom room description, size, aspect, storage, condition."},
                {"id": "living_room", "label": "Living room",
                 "anchor": "Living room, lounge, reception room, sitting room description."},
                {"id": "dining_room", "label": "Dining room",
                 "anchor": "Dining room description, layout, aspect, condition."},
                {"id": "conservatory", "label": "Conservatory",
                 "anchor": "Conservatory room, glazed room, sunroom description."},
                {"id": "hall_landing", "label": "Hall & landing",
                 "anchor": "Entrance hall, hallway, landing, stairwell description."},
                {"id": "wc_cloakroom", "label": "WC / cloakroom",
                 "anchor": "Separate WC, cloakroom, downstairs toilet description."},
                {"id": "utility_room", "label": "Utility room",
                 "anchor": "Utility room, laundry room, boot room description."},
                {"id": "study", "label": "Study / office",
                 "anchor": "Study, home office, box room description."},
            ],
        },
        {
            "id": TOPIC_OTHER,
            "label": "Other / General Observations",
            "order": 7,
            "rated": False,
            "dynamic_subtopics": False,
            "anchor": (
                "General observations that do not fit a specific element topic: "
                "risks, legal matters, energy, inspection summary and general notes."
            ),
            "subtopics": [
                {"id": "inspection_summary", "label": "Inspection & summary", "rics": ["A"],
                 "anchor": "About the inspection, surveyor details, overall opinion and summary of element ratings."},
                # 33 chunks in the corpus are "Limitations on the inspection" blocks,
                # one per parent section per report, and had nowhere to go before.
                {"id": "inspection_limitations", "label": "Inspection limitations", "rics": [],
                 "anchor": "Limitations on the inspection: what could not be inspected and why, no access, "
                           "concealed or covered elements, roof not reachable from ground level, "
                           "floor coverings furniture and stored goods restricting view, "
                           "no lifting of carpets, services not tested."},
                {"id": "legal_regulatory", "label": "Legal & regulatory", "rics": ["H", "H1", "H2", "H3"],
                 "anchor": "Legal and regulatory matters, building regulations, planning, guarantees, tenure, easements."},
                {"id": "risks", "label": "Risks", "rics": ["I", "I1", "I2", "I3", "I4"],
                 "anchor": "Risks to the building, grounds and people: movement, damp, flood, radon, asbestos, fire safety."},
                {"id": "energy", "label": "Energy", "rics": ["J", "J1", "J2", "J3", "J4", "J5"],
                 "anchor": "Energy matters, insulation, heating efficiency, lighting, ventilation, EPC, solar."},
                {"id": "declaration_terms", "label": "Declaration & terms", "rics": ["K", "M"],
                 "anchor": "Surveyor declaration, professional standards, scope of survey, terms of engagement."},
                {"id": CATCH_ALL_SUBTOPIC, "label": "General", "rics": ["L", "N"],
                 "anchor": "General observations and anything that does not fit another topic."},
            ],
        },
    ],
}


# ── Derived lookups (built once at import) ─────────────────────────────────────
def _topics() -> list[dict[str, Any]]:
    return list(CONTENT_TAXONOMY["topics"])


ORDERED_TOPIC_IDS: tuple[str, ...] = tuple(
    str(t["id"]) for t in sorted(_topics(), key=lambda t: int(t["order"]))
)

TOPIC_LABELS: dict[str, str] = {str(t["id"]): str(t["label"]) for t in _topics()}

RATED_TOPIC_IDS: frozenset[str] = frozenset(
    str(t["id"]) for t in _topics() if t.get("rated")
)

# topic_id -> ordered list of (subtopic_id, label)
_SUBTOPICS: dict[str, list[tuple[str, str]]] = {
    str(t["id"]): [(str(s["id"]), str(s["label"])) for s in t.get("subtopics", [])]
    for t in _topics()
}

# (topic_id, subtopic_id) -> label
SUBTOPIC_LABELS: dict[tuple[str, str], str] = {
    (str(t["id"]), str(s["id"])): str(s["label"])
    for t in _topics()
    for s in t.get("subtopics", [])
}

# subtopic_id -> topic_id (sub-topic ids are unique across topics by construction).
SUBTOPIC_TO_TOPIC: dict[str, str] = {
    str(s["id"]): str(t["id"])
    for t in _topics()
    for s in t.get("subtopics", [])
}

# v1 -> v2 sub-topic renames. Surveyors write note prefixes by hand ("heating: ...")
# and older stored chunks carry the old ids, so a rename must not silently stop
# resolving. Only genuine renames and merges appear here: the dropped magnet buckets
# (other_outside, other_inside, other_grounds) intentionally have no successor, so
# those lines fall through to content classification instead.
SUBTOPIC_ALIASES: dict[str, str] = {
    "heating": "heating_hot_water",
    "water_heating": "heating_hot_water",
    "bathroom_fittings": "sanitaryware",
    "other_joinery_finishes": "external_joinery",
    "grounds_boundaries": "boundaries",
    "conservatory_porches": "porches_extensions",
}

# (topic_id, subtopic_id) -> anchor descriptor text
_SUBTOPIC_ANCHORS: dict[tuple[str, str], str] = {
    (str(t["id"]), str(s["id"])): str(s.get("anchor") or s.get("label") or s["id"])
    for t in _topics()
    for s in t.get("subtopics", [])
}

_TOPIC_ANCHORS: dict[str, str] = {
    str(t["id"]): str(t.get("anchor") or t.get("label") or t["id"]) for t in _topics()
}

# RICS section code (leaf or parent) -> (topic_id, subtopic_id).
SECTION_TO_TOPIC: dict[str, tuple[str, str]] = {}
for _t in _topics():
    for _s in _t.get("subtopics", []):
        for _code in _s.get("rics", []) or []:
            SECTION_TO_TOPIC[str(_code).strip().upper()] = (
                str(_t["id"]),
                str(_s["id"]),
            )

# Parent RICS letter -> (topic_id, subtopic_id-or-empty). Element parents leave the
# sub-topic empty (decided by content); descriptive parents carry a default.
PARENT_TO_TOPIC: dict[str, tuple[str, str]] = {
    "A": (TOPIC_OTHER, "inspection_summary"),
    # B is "about the property" — its own description, not the inspection blurb.
    "B": (TOPIC_LOCATION_FACILITIES, "property_description"),
    "C": (TOPIC_LOCATION_FACILITIES, ""),
    "D": (TOPIC_OUTSIDE, ""),
    "E": (TOPIC_INSIDE, ""),
    "F": (TOPIC_SERVICES, ""),
    "G": (TOPIC_GROUNDS, ""),
    "H": (TOPIC_OTHER, "legal_regulatory"),
    "I": (TOPIC_OTHER, "risks"),
    "J": (TOPIC_OTHER, "energy"),
    "K": (TOPIC_OTHER, "declaration_terms"),
    "L": (TOPIC_OTHER, CATCH_ALL_SUBTOPIC),
    "M": (TOPIC_OTHER, "declaration_terms"),
    "N": (TOPIC_OTHER, CATCH_ALL_SUBTOPIC),
}

# Room lexicon used to detect room-by-room descriptions for the Rooms Described
# topic. Maps a normalized seed room id to trigger words/phrases.
ROOM_LEXICON: dict[str, tuple[str, ...]] = {
    "kitchen": ("kitchen", "kitchen/diner", "kitchen diner"),
    "bathroom": ("bathroom", "family bathroom", "en-suite", "en suite", "ensuite", "shower room"),
    "bedroom": ("bedroom", "master bedroom", "double bedroom", "single bedroom", "box room"),
    "living_room": ("living room", "lounge", "sitting room", "reception room", "front room", "drawing room"),
    "dining_room": ("dining room", "dining area"),
    "conservatory": ("conservatory", "sunroom", "sun room", "garden room"),
    "hall_landing": ("hallway", "hall", "entrance hall", "landing", "stairwell"),
    "wc_cloakroom": ("cloakroom", "wc", "w.c.", "downstairs toilet", "separate toilet"),
    "utility_room": ("utility room", "utility", "laundry room", "boot room"),
    "study": ("study", "home office", "office"),
}

# ── Theme tags (orthogonal to topics) ─────────────────────────────────────────
# A chunk belongs to exactly one topic/sub-topic but may carry several theme tags.
#
# These are the themes a per-element structure shatters worst. Measured over the
# ingested corpus: damp appeared in 27 different RICS codes, ventilation in 24,
# movement in 21, consents in 19. Modelling them as topics would make every
# "damp patch on the bedroom wall" note ambiguous between the damp topic and the
# wall element, so they run as a second, independent dimension instead. Retrieval
# can then answer "all damp evidence" across every element. See adr/0007.
CONTENT_THEME_TAGS: dict[str, str] = {
    "damp": (
        "Damp and moisture: rising or penetrating damp, damp meter readings, "
        "condensation, mould growth, water staining, leaks."
    ),
    "movement": (
        "Structural movement: cracking, subsidence, settlement, heave, bulging or "
        "leaning walls, distortion, lintel failure."
    ),
    "ventilation": (
        "Ventilation: air bricks, sub-floor and roof-void ventilation, extractor "
        "fans, trickle vents, blocked or absent ventilation."
    ),
    "timber_decay": (
        "Timber decay and infestation: wet rot, dry rot, fungal decay, woodworm "
        "and other beetle attack."
    ),
    "consents": (
        "Consents and paperwork: building regulations approval, planning "
        "permission, completion or compliance certificates, FENSA, Gas Safe, "
        "guarantees and warranties."
    ),
    "energy": (
        "Energy efficiency: insulation, thermal performance, draughts, glazing "
        "performance, EPC rating, solar."
    ),
    "safety": (
        "Health and safety: fire safety and means of escape, smoke and carbon "
        "monoxide alarms, safety glazing, trip hazards, electrical safety."
    ),
    "asbestos": (
        "Asbestos and other deleterious materials suspected or identified."
    ),
    "not_inspected": (
        "Something could not be inspected or tested: no access, concealed, "
        "covered by finishes or stored goods, services not tested."
    ),
}


# ── Public helpers ──────────────────────────────────────────────────────────
def ordered_topics() -> list[tuple[str, str]]:
    """Return ``(topic_id, topic_label)`` in canonical display order."""
    return [(tid, TOPIC_LABELS[tid]) for tid in ORDERED_TOPIC_IDS]


def valid_topic_ids() -> frozenset[str]:
    return frozenset(ORDERED_TOPIC_IDS)


def valid_subtopic_ids(topic_id: str) -> frozenset[str]:
    return frozenset(sid for sid, _ in _SUBTOPICS.get(topic_id, []))


def subtopics_for_topic(topic_id: str) -> list[tuple[str, str]]:
    """Ordered ``(subtopic_id, label)`` for a topic (seed rooms for Rooms Described)."""
    return list(_SUBTOPICS.get(topic_id, []))


def is_topic(topic_id: str) -> bool:
    return (topic_id or "") in TOPIC_LABELS


def is_rated_topic(topic_id: str) -> bool:
    return (topic_id or "") in RATED_TOPIC_IDS


def has_dynamic_subtopics(topic_id: str) -> bool:
    return (topic_id or "") in DYNAMIC_SUBTOPIC_TOPICS


def topic_label(topic_id: str) -> str:
    return TOPIC_LABELS.get(topic_id, topic_id)


def subtopic_label(topic_id: str, subtopic_id: str) -> str:
    if (topic_id, subtopic_id) in SUBTOPIC_LABELS:
        return SUBTOPIC_LABELS[(topic_id, subtopic_id)]
    # Dynamic room sub-topics are minted as slugs — humanize them.
    return _humanize_slug(subtopic_id) if subtopic_id else topic_label(topic_id)


def resolve_subtopic_id(subtopic_id: str) -> str:
    """Canonicalise a sub-topic id, translating pre-v2 names. '' when unknown."""
    sid = (subtopic_id or "").strip().lower()
    if sid in SUBTOPIC_TO_TOPIC:
        return sid
    return SUBTOPIC_ALIASES.get(sid, "")


def topic_for_subtopic(subtopic_id: str) -> str:
    """Return the owning topic id for a (static) sub-topic id, else ''.

    Accepts pre-v2 sub-topic names via :data:`SUBTOPIC_ALIASES`.
    """
    return SUBTOPIC_TO_TOPIC.get(resolve_subtopic_id(subtopic_id), "")


def topic_order(topic_id: str) -> int:
    try:
        return ORDERED_TOPIC_IDS.index(topic_id)
    except ValueError:
        return len(ORDERED_TOPIC_IDS)


def catch_all() -> tuple[str, str]:
    """The ``(topic_id, subtopic_id)`` for unclassifiable content."""
    return (CATCH_ALL_TOPIC, CATCH_ALL_SUBTOPIC)


# Trigger phrases per theme, matched on word boundaries. Deliberately deterministic
# and offline: most chunks resolve their topic from an exact RICS leaf code and never
# reach the LLM, so without this they would carry no themes at all. Kept to terms a
# UK surveyor uses when actually reporting the theme, not every loose synonym.
THEME_LEXICON: dict[str, tuple[str, ...]] = {
    "damp": (
        "damp", "dampness", "damp-proof", "damp proof", "dpc", "moisture", "moisture meter",
        "condensation", "mould", "mold", "mildew", "penetrating damp", "rising damp",
        "water staining", "water stain", "tide mark", "leak", "leaking", "leaks",
    ),
    "movement": (
        "crack", "cracks", "cracked", "cracking", "subsidence", "settlement", "heave",
        "bulging", "bulge", "leaning", "distortion", "distorted", "structural movement",
        "lintel", "deflection", "out of plumb",
    ),
    "ventilation": (
        "ventilation", "ventilated", "unventilated", "air brick", "air bricks", "airbrick",
        "airbricks", "extractor fan", "extract fan", "extractor", "trickle vent",
        "trickle vents", "cross ventilation", "through ventilation",
    ),
    "timber_decay": (
        "wet rot", "dry rot", "rot", "rotten", "rotting", "fungal", "fungus",
        "woodworm", "beetle", "infestation", "timber decay", "decayed",
    ),
    "consents": (
        "building regulation", "building regulations", "building regs", "planning permission",
        "planning consent", "completion certificate", "fensa", "gas safe", "guarantee",
        "guarantees", "warranty", "indemnity", "listed building", "conservation area",
    ),
    "energy": (
        "insulation", "insulated", "uninsulated", "thermal", "draught", "draughts",
        "draughty", "epc", "energy performance", "u-value", "solar", "heat loss",
    ),
    "safety": (
        "smoke alarm", "smoke detector", "carbon monoxide", "co alarm", "safety glass",
        "safety glazing", "toughened glass", "means of escape", "fire door",
        "fire safety", "trip hazard", "handrail", "balustrade", "electrical safety",
    ),
    "asbestos": ("asbestos", "asbestos-containing", "acm"),
    # Phrases only. Bare words like "limitations" or "restricted" appear in every
    # report's standard preamble and tagged ~55% of the corpus on their own.
    "not_inspected": (
        "not inspected", "could not be inspected", "unable to inspect",
        "were not inspected", "was not inspected", "not accessible", "no access",
        "not tested", "were not tested", "concealed", "not exposed", "not lifted",
        "did not inspect", "prevented inspection", "restricted our inspection",
        "limited our inspection",
    ),
}

_THEME_PATTERNS: dict[str, re.Pattern[str]] = {
    tag: re.compile(
        r"\b(?:" + "|".join(re.escape(p) for p in sorted(phrases, key=len, reverse=True)) + r")\b"
    )
    for tag, phrases in THEME_LEXICON.items()
}


def theme_tags_for_text(text: str) -> list[str]:
    """Themes whose trigger phrases appear in ``text``, in vocabulary order.

    Lexical and deterministic, so it works offline and for chunks that bypassed
    the LLM. Union this with any model-reported tags rather than replacing them.
    """
    low = (text or "").lower()
    if not low:
        return []
    return [tag for tag in CONTENT_THEME_TAGS if _THEME_PATTERNS[tag].search(low)]


def valid_theme_tags() -> frozenset[str]:
    """The fixed theme-tag vocabulary (see :data:`CONTENT_THEME_TAGS`)."""
    return frozenset(CONTENT_THEME_TAGS)


def normalize_theme_tags(raw: object) -> list[str]:
    """Keep only known tags, de-duplicated and in canonical vocabulary order.

    Tolerant of whatever a model or an older stored row hands over (a list, a
    comma-separated string, or junk), because tags are advisory metadata and must
    never break ingest or retrieval.
    """
    if isinstance(raw, str):
        items = raw.split(",")
    elif isinstance(raw, (list, tuple, set, frozenset)):
        items = list(raw)
    else:
        return []
    seen = {str(t).strip().lower().replace("-", "_") for t in items if str(t).strip()}
    return [tag for tag in CONTENT_THEME_TAGS if tag in seen]


def iter_anchor_units() -> list[tuple[str, str, str]]:
    """All ``(topic_id, subtopic_id, anchor_text)`` rows for embedding classification."""
    rows: list[tuple[str, str, str]] = []
    for tid in ORDERED_TOPIC_IDS:
        for sid, _label in _SUBTOPICS.get(tid, []):
            rows.append((tid, sid, _SUBTOPIC_ANCHORS[(tid, sid)]))
    return rows


def build_topic_anchor_text(topic_id: str, subtopic_id: str = "") -> str:
    """Descriptive anchor string for embedding-based topic classification."""
    tid = (topic_id or "").strip()
    sid = (subtopic_id or "").strip()
    if sid and (tid, sid) in _SUBTOPIC_ANCHORS:
        return f"{TOPIC_LABELS.get(tid, tid)}: {SUBTOPIC_LABELS[(tid, sid)]}. {_SUBTOPIC_ANCHORS[(tid, sid)]}"
    if tid in _TOPIC_ANCHORS:
        return f"{TOPIC_LABELS.get(tid, tid)}. {_TOPIC_ANCHORS[tid]}"
    raise KeyError(f"Unknown topic/sub-topic: {topic_id!r}/{subtopic_id!r}")


def section_prior(section_id_hint: str) -> tuple[str, str, str] | None:
    """Map a RICS section id to ``(topic_id, subtopic_id, strength)``.

    ``strength`` is ``"leaf"`` when the code pins an exact sub-topic (e.g. ``D2``),
    or ``"parent"`` when it only pins the topic (e.g. ``C`` / ``D``). Returns
    ``None`` for empty or unknown ids.
    """
    sid = (section_id_hint or "").strip().upper()
    if not sid:
        return None
    if sid in SECTION_TO_TOPIC:
        topic_id, subtopic_id = SECTION_TO_TOPIC[sid]
        strength = "leaf" if len(sid) > 1 else "parent"
        return (topic_id, subtopic_id, strength)
    letter = sid[0]
    if letter in PARENT_TO_TOPIC:
        topic_id, subtopic_id = PARENT_TO_TOPIC[letter]
        return (topic_id, subtopic_id, "parent")
    return None


def base_room_for(text: str) -> str:
    """Return the seed room id whose trigger phrase appears in ``text``, else ''.

    Keeps room sub-topics within the stable seed set (kitchen, bathroom, bedroom,
    ...) so classification, note routing, and the section catalog stay aligned.
    """
    low = (text or "").lower()
    for room_id, triggers in ROOM_LEXICON.items():
        for trig in triggers:
            if re.search(r"\b" + re.escape(trig) + r"\b", low):
                return room_id
    return ""


def normalize_room_subtopic_id(raw: str) -> str:
    """Slugify a free-form room name into a stable sub-topic id.

    e.g. "Front First Floor Bedroom" -> "front_first_floor_bedroom".
    """
    slug = re.sub(r"[^a-z0-9]+", "_", (raw or "").strip().lower()).strip("_")
    return slug or "room"


def _humanize_slug(slug: str) -> str:
    return (slug or "").replace("_", " ").strip().capitalize()
