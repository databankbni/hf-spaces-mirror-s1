"""Deterministic keyword router for messy surveyor notes → RICS L3 product section ids.

Uses ordered regex patterns (most specific first). Explicit section prefixes and
high-confidence domain keywords are resolved in ``backend.domain.notes.routing``
before these general patterns run. Parent-storage groups (A/B/C/K/L/M/N) route
to the parent letter; D–I/J keep real leaf codes.
"""

from __future__ import annotations

import re

from backend.domain.notes.routing import (
    UNASSIGNED,
    classify_high_confidence_keywords,
    parse_element_label_prefix,
    parse_explicit_section_prefix,
)
from backend.domain.rics_level3_schema import valid_leaf_section_ids

# (section_id, compiled regex) — first match wins.
_ROUTE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Hazards before generic ceiling mentions.
    ("I3", re.compile(r"asbestos|chrysotile|aib\b|suspected.*artex", re.I)),
    # ── A: About the inspection (parent-level unit) ───────────────────────────
    (
        "A",
        re.compile(
            r"surveyor|rics\s*member|qualification|company\s*name|indemnity|"
            r"date\s*of\s*inspection|inspection\s*date|survey\s*date|date\s*of\s*survey|"
            r"related\s*party|conflict\s*of\s*interest|third\s*party\s*disclos|"
            r"\bweather\b(?!\s*(?:bar|board))|conditions\s*on\s*site|dry\s*day|wet\s*day|overcast|"
            r"occupied|vacant|furnished|unfurnished|tenant|property\s*status",
            re.I,
        ),
    ),
    # ── B: Overall opinion (parent-level unit) ────────────────────────────────
    (
        "B",
        re.compile(
            r"summary\s*of\s*condition|condition\s*rat|category\s*[123]|rating\s*summary|"
            r"overall\s*opinion|general\s*condition|key\s*findings|"
            r"further\s*invest|specialist\s*report|additional\s*survey",
            re.I,
        ),
    ),
    # ── C: About the property (parent-level unit) ─────────────────────────────
    (
        "C",
        re.compile(
            r"\bsemi.?det|\bdet(ached)?\b|terraced|bungalow|maisonette|(?<!laid\s)\bflat\b(?!\s*roof)|"
            r"type\s*and\s*construct|timber\s*frame|"
            r"year\s*built|approximate\s*year|circa\s*19|circa\s*20|built\s*in\s*19|built\s*in\s*20|"
            r"accommodation|bedroom|reception\s*room|storey|room\s*matrix|floor\s*area|sq\.?\s*m\b|"
            r"\bepc\b|energy\s*effici|sap\s*rating|double\s*glazing|"
            r"location|facilities|flood\s*zone|radon|mining|contamination|flight\s*path|noise\s*nuisance",
            re.I,
        ),
    ),
    # ── G: Grounds (before D roof so "garage roof" stays G1, not D2) ─────────
    ("G1", re.compile(r"\bgarage\b|car\s*port", re.I)),
    (
        "G2",
        re.compile(r"outbuilding|shed\b|workshop|barn\b|permanent\s*outbuild", re.I),
    ),
    (
        "G3",
        re.compile(
            r"boundary|fence\b|hedge|retaining\s*wall|garden\b|driveway|grounds|timber\s*fenc",
            re.I,
        ),
    ),
    # ── D: Outside the property ───────────────────────────────────────────────
    (
        "D1",
        re.compile(
            r"chimney\s*stack|chimney\s*pot|flaunch|\bchimney\b|stack.*brick|tv\s*aerial|aerial.*lean",
            re.I,
        ),
    ),
    (
        "D2",
        re.compile(
            r"roof\s*cover|slate|slates|tile\s*roof|clay\s*tile|felt\s*roof|flat\s*roof|"
            r"hip\s*roof|ridge\s*tile|roof\s*light|dormer\s*roof|slipp|moss.*roof|"
            r"\bverges?\b|roof[^.\n]*re-?point|re-?point[^.\n]*roof|ridge[^.\n]*re-?point",
            re.I,
        ),
    ),
    (
        "D3",
        re.compile(
            r"rainwater|gutter|gutters|downpipe|down\s*pipe|gullies|rwp\b|hopper|"
            r"gutter\s*block|gutter\s*leak|fittings.*brittle",
            re.I,
        ),
    ),
    (
        "D4",
        re.compile(
            r"main\s*wall|external\s*wall|brick\s*wall|cavity\s*wall|render|pointing|"
            r"repoint|dpc\b|parapet|erosion|step\s*crack|cracking|fixing\s*bar|wall\s*tie|cavity\s*wall\s*tie",
            re.I,
        ),
    ),
    (
        "D5",
        re.compile(
            r"\bwindows?\b|glazing|fensa|upvc\s*window|sash\s*window|bay\s*window|double\s*glaz",
            re.I,
        ),
    ),
    (
        "D6",
        re.compile(
            r"external\s*door|outside\s*door|patio\s*door|entrance\s*door|front\s*door",
            re.I,
        ),
    ),
    ("D7", re.compile(r"conservatory|porch\b", re.I)),
    (
        "D8",
        re.compile(r"fascia\b|soffit\b|bargeboard|external\s*joinery|cladding", re.I),
    ),
    ("D9", re.compile(r"balcony|external\s*stair|other\s*outside", re.I)),
    # ── E: Inside the property ────────────────────────────────────────────────
    (
        "E1",
        re.compile(
            r"roof\s*struct|truss|purlin|collar\s*tie|cut\s*rafter|trussed\s*rafter|rafter.*loft|purlin.*loft|loft\s*hatch|astragal|wasteness|building\s*regulation.*support|support.*building\s*regulation",
            re.I,
        ),
    ),
    ("E2", re.compile(r"ceil|ceiling|artex|lath.*plaster", re.I)),
    (
        "E3",
        re.compile(
            r"internal\s*wall|partition|plaster.*wall|stud\s*wall|rising\s*damp|penetrat.*damp",
            re.I,
        ),
    ),
    (
        "E4",
        re.compile(
            r"floor\s*board|suspended\s*floor|solid\s*floor|sub.?floor|springy\s*floor",
            re.I,
        ),
    ),
    (
        "E5",
        re.compile(r"fireplace|chimney\s*breast|hearth|open\s*fire|flue\s*liner", re.I),
    ),
    (
        "E6",
        re.compile(
            r"built.?in\s*fit|fitted\s*kitchen|built.?in\s*wardrobe|kitchen\s*unit|\bkitchen\b",
            re.I,
        ),
    ),
    (
        "E7",
        re.compile(
            r"skirting|architrave|staircase|internal\s*door|woodwork|joinery", re.I
        ),
    ),
    (
        "E8",
        re.compile(
            r"bathroom|sanitary|shower|wc\b|basin|ventilation\s*fan|extract\s*fan|\bfan\b",
            re.I,
        ),
    ),
    # ── F: Services (before E9 — service type beats cellar/basement location) ───
    (
        "F1",
        re.compile(
            r"electric|consumer\s*unit|fuse\s*board|wiring|earthing|rcd\b|eicr|verdigris",
            re.I,
        ),
    ),
    (
        "F2",
        re.compile(r"\bgas\b|oil\s*tank|lpg|gas\s*meter|gas\s*pipe|gas\s*safe", re.I),
    ),
    ("F3", re.compile(r"water\s*supply|stopcock|mains\s*water|lead\s*pipe", re.I)),
    (
        "F4",
        re.compile(
            r"boiler|central\s*heat|radiator|heating\s*system|vaillant|worcester", re.I
        ),
    ),
    ("F5", re.compile(r"hot\s*water|water\s*heat|cylinder|combi|immersion", re.I)),
    (
        "F6",
        re.compile(
            r"drain|sewer|manhole|soil\s*pipe|soil\s*and\s*vent|vent\s*stack|soil\s*stack|\bsvp\b|septic|gully",
            re.I,
        ),
    ),
    (
        "F7",
        re.compile(
            r"common\s*service|shared\s*util|landlord\s*suppl|alarm|burglar|security|sensor",
            re.I,
        ),
    ),
    ("E9", re.compile(r"cellar|basement|other\s*inside", re.I)),
    # ── H: Legal ──────────────────────────────────────────────────────────────
    (
        "H1",
        re.compile(
            r"building\s*reg|planning\s*permiss|listed\s*build|conservation\s*area|regulation|"
            r"(?:load.?bearing|supporting)\s*walls?[^.\n]*remov|remov[^.\n]*(?:load.?bearing|supporting)\s*walls?|"
            r"structural\s*alteration|converted\s*to\s*flat|flat.*convert",
            re.I,
        ),
    ),
    ("H2", re.compile(r"guarantee|warranty|nhbc|fensa\s*certif", re.I)),
    (
        "H3",
        re.compile(r"tenure|leasehold|freehold|easement|covenant|legal\s*advis", re.I),
    ),
    # ── I: Risks ──────────────────────────────────────────────────────────────
    # condensation/mould carry NO I-signal: they are element symptoms (windows D5,
    # bathroom E8, ceilings E2) and must inherit the block's element context. A
    # context-free mention falls to UNASSIGNED → RAG topical reroute, never blindly I1.
    (
        "I1",
        re.compile(
            r"rising\s*damp|penetrat.*damp|subsiden|structural\s*movement|woodworm|dry\s*rot|wet\s*rot|timber\s*decay",
            re.I,
        ),
    ),
    (
        "I2",
        re.compile(
            r"flood\s*risk|radon|mining|knotweed|tree\s*root|shrinkable\s*clay|risk.*ground",
            re.I,
        ),
    ),
    (
        "I3",
        re.compile(
            r"asbestos|chrysotile|aib\b|fire\s*safety|safety\s*glass|lead\s*pipe|trip\s*hazard|balustrade",
            re.I,
        ),
    ),
    (
        "I4",
        re.compile(
            r"contamination|unexploded|invasive\s*species|other\s*risk|other\s*hazard",
            re.I,
        ),
    ),
    # ── J: Energy matters ─────────────────────────────────────────────────────
    (
        "J1",
        re.compile(
            r"loft\s*insul|roof\s*void\s*insul|cavity\s*insul|wall\s*insul|insulation",
            re.I,
        ),
    ),
    (
        "J2",
        re.compile(
            r"boiler\s*effici|heating\s*effici|heat\s*pump|zone\s*control", re.I
        ),
    ),
    ("J3", re.compile(r"lighting|led\b|low\s*energy\s*light", re.I)),
    ("J4", re.compile(r"ventilation|trickle\s*vent|extract\s*fan", re.I)),
    ("J5", re.compile(r"energy\s*matter|renewable|solar\s*panel|epc\s*improv", re.I)),
    # ── K / L / M / N (parent-level units) ─────────────────────────────────────
    (
        "K",
        re.compile(
            r"surveyor\s*declar|signature|rics\s*number|professional\s*stand", re.I
        ),
    ),
    (
        "L",
        re.compile(
            r"what\s*to\s*do|obtain\s*quot|next\s*step|recommended\s*action", re.I
        ),
    ),
    (
        "M",
        re.compile(
            r"terms\s*of\s*engage|scope\s*of\s*survey|service\s*description|complaints",
            re.I,
        ),
    ),
    (
        "N",
        re.compile(
            r"typical\s*house\s*diagram|diagram\s*reference|elevation\s*sketch", re.I
        ),
    ),
]


def _classify_general_keywords(text: str) -> tuple[str, float]:
    """Priority-3 general keyword patterns."""
    line = (text or "").strip()
    if len(line) < 3:
        return UNASSIGNED, 0.0

    valid = valid_leaf_section_ids()
    for section_id, pattern in _ROUTE_PATTERNS:
        if pattern.search(line):
            sid = section_id.upper()
            if sid in valid:
                return sid, 1.0
    return UNASSIGNED, 0.0


# Routing tiers, strongest → weakest. "explicit"/"label"/"high" are STRONG signals
# (a surveyor code, an element label, or curated high-confidence vocabulary) and may
# establish or override the running section of a note block. "general" is a WEAK
# fallback keyword that must not override an already-established block context.
TIER_EXPLICIT = "explicit"
TIER_LABEL = "label"
TIER_HIGH = "high"
TIER_GENERAL = "general"
TIER_NONE = "none"
STRONG_TIERS = frozenset({TIER_EXPLICIT, TIER_LABEL, TIER_HIGH})


def classify_note_cascade_with_tier(text: str) -> tuple[str, str, str]:
    """Run the routing cascade and report *which* tier resolved the note.

    Returns ``(section_id, tier, observation_text)`` where ``tier`` is one of
    :data:`TIER_EXPLICIT`, :data:`TIER_LABEL`, :data:`TIER_HIGH`,
    :data:`TIER_GENERAL`, or :data:`TIER_NONE`. The tier lets the block-level
    parser decide whether a match is strong enough to override an inherited
    section, without re-running the cascade.
    """
    line = (text or "").strip()
    if len(line) < 3:
        return UNASSIGNED, TIER_NONE, line

    explicit = parse_explicit_section_prefix(line)
    if explicit:
        section_id, body = explicit
        return section_id, TIER_EXPLICIT, body

    labelled = parse_element_label_prefix(line)
    if labelled:
        section_id, full_line = labelled
        return section_id, TIER_LABEL, full_line

    section_id, _ = classify_high_confidence_keywords(line)
    if section_id != UNASSIGNED:
        return section_id, TIER_HIGH, line

    section_id, _ = _classify_general_keywords(line)
    if section_id != UNASSIGNED:
        return section_id, TIER_GENERAL, line
    return UNASSIGNED, TIER_NONE, line


def classify_note_cascade(text: str) -> tuple[str, float, str]:
    """Run P1 code prefix → P1b element label → P2 keywords → P3 general keywords.

    Back-compat wrapper over :func:`classify_note_cascade_with_tier`; any resolved
    tier scores 1.0 and ``UNASSIGNED`` scores 0.0 (unchanged contract).
    """
    section_id, tier, body = classify_note_cascade_with_tier(text)
    score = 0.0 if tier == TIER_NONE else 1.0
    return section_id, score, body


def classify_note_by_keywords(text: str) -> tuple[str, float]:
    """Return ``(section_id | UNASSIGNED, confidence)`` for one note line."""
    section_id, score, _ = classify_note_cascade(text)
    return section_id, score
