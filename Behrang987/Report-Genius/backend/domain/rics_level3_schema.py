"""Canonical RICS Home Survey Level 3 structural guard.

Official 14 parent sections (A–N). Product mapping units:
  - Parent-level bodies for A/B/C/K/L/M/N (no artificial A1/C1/… leaves)
  - Real leaf codes for D–I and J (as in live PDFs)

Artificial leaf ids under A/B/C/K/L/M/N must never be used as ingest,
retrieval, UI, or DOCX keys (see :mod:`backend.domain.section_scope`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.domain.section_scope import (
    PARENT_INTRO_SECTION_IDS,
    PARENT_STORAGE_PARENT_IDS,
)
from backend.models.schema import (
    RatingSystem,
    RatingValue,
    SectionDefinition,
    TemplateSchema,
)

CANONICAL_SCHEMA_VERSION = "v4.2"
# 7 parent-level units (A/B/C/K/L/M/N) + 7 D–J parent intros + 40 real leaves.
CANONICAL_SECTION_COUNT = 54
CANONICAL_LEAF_COUNT = CANONICAL_SECTION_COUNT  # backward-compat alias
CANONICAL_REAL_LEAF_COUNT = 40
PARENT_SECTION_COUNT = 14

# Fallback rating-system label used when a discovered template exposes rating
# legends/values but no explicit rating-system name. This is the bare default
# and is intentionally distinct from the canonical schema's fully-qualified
# ``name`` ("RICS Condition Rating", see below) — do not collapse the two.
DEFAULT_RATING_SYSTEM_NAME = "Condition Rating"

CANONICAL_SCHEMA: dict[str, Any] = {
    "version": CANONICAL_SCHEMA_VERSION,
    "rating_system": {"detected": True, "type": "RICS_3_TIER"},
    "sections": [
        {
            "id": "A",
            "label": "About the inspection",
            "order": 1,
            "has_rating_field": False,
            "subsections": [],
        },
        {
            "id": "B",
            "label": "Overall opinion and summary of the condition ratings",
            "order": 2,
            "has_rating_field": False,
            "subsections": [],
        },
        {
            "id": "C",
            "label": "About the property",
            "order": 3,
            "has_rating_field": False,
            "subsections": [],
        },
        {
            "id": "D",
            "label": "Outside the property",
            "order": 4,
            "has_rating_field": True,
            "subsections": [
                {"id": "D1", "label": "Chimney stacks"},
                {"id": "D2", "label": "Roof coverings"},
                {"id": "D3", "label": "Rainwater pipes and gutters"},
                {"id": "D4", "label": "Main walls"},
                {"id": "D5", "label": "Windows"},
                {"id": "D6", "label": "Outside doors (including patio doors)"},
                {"id": "D7", "label": "Conservatory and porches"},
                {"id": "D8", "label": "Other joinery and finishes"},
                {"id": "D9", "label": "Other"},
            ],
        },
        {
            "id": "E",
            "label": "Inside the property",
            "order": 5,
            "has_rating_field": True,
            "subsections": [
                {"id": "E1", "label": "Roof structure"},
                {"id": "E2", "label": "Ceilings"},
                {"id": "E3", "label": "Walls and partitions"},
                {"id": "E4", "label": "Floors"},
                {"id": "E5", "label": "Fireplaces, chimney breasts and flues"},
                {"id": "E6", "label": "Built-in fittings"},
                {"id": "E7", "label": "Woodwork"},
                {"id": "E8", "label": "Bathroom fittings"},
                {"id": "E9", "label": "Other"},
            ],
        },
        {
            "id": "F",
            "label": "Services",
            "order": 6,
            "has_rating_field": True,
            "subsections": [
                {"id": "F1", "label": "Electricity"},
                {"id": "F2", "label": "Gas and Oil"},
                {"id": "F3", "label": "Water"},
                {"id": "F4", "label": "Heating"},
                {"id": "F5", "label": "Water heating"},
                {"id": "F6", "label": "Drainage"},
                {"id": "F7", "label": "Common services"},
            ],
        },
        {
            "id": "G",
            "label": "Grounds (including shared areas for flats)",
            "order": 7,
            "has_rating_field": True,
            "subsections": [
                {"id": "G1", "label": "Garage"},
                {"id": "G2", "label": "Permanent outbuildings"},
                {"id": "G3", "label": "Other"},
            ],
        },
        {
            "id": "H",
            "label": "Issues for your legal advisers",
            "order": 8,
            "has_rating_field": False,
            "subsections": [
                {"id": "H1", "label": "Regulation"},
                {"id": "H2", "label": "Guarantees"},
                {"id": "H3", "label": "Other matters"},
            ],
        },
        {
            "id": "I",
            "label": "Risks",
            "order": 9,
            "has_rating_field": False,
            "subsections": [
                {"id": "I1", "label": "Risks to the building"},
                {"id": "I2", "label": "Risks to the grounds"},
                {"id": "I3", "label": "Risks to people"},
                {"id": "I4", "label": "Other risks or hazards"},
            ],
        },
        {
            "id": "J",
            "label": "Energy matters",
            "order": 10,
            "has_rating_field": False,
            "subsections": [
                {"id": "J1", "label": "Insulation"},
                {"id": "J2", "label": "Heating"},
                {"id": "J3", "label": "Lighting"},
                {"id": "J4", "label": "Ventilation"},
                {"id": "J5", "label": "General"},
            ],
        },
        {
            "id": "K",
            "label": "Surveyor's declaration",
            "order": 11,
            "has_rating_field": False,
            "subsections": [],
        },
        {
            "id": "L",
            "label": "What to do now",
            "order": 12,
            "has_rating_field": False,
            "subsections": [],
        },
        {
            "id": "M",
            "label": "Description of the RICS Home Survey - Level 3 service and terms of engagement",
            "order": 13,
            "has_rating_field": False,
            "subsections": [],
        },
        {
            "id": "N",
            "label": "Typical house diagram",
            "order": 14,
            "has_rating_field": False,
            "subsections": [],
        },
    ],
}


def _subsection_rows(parent: dict[str, Any]) -> list[dict[str, str]]:
    return list(parent.get("subsections") or [])


def valid_leaf_section_ids() -> frozenset[str]:
    """All product mapping-unit ids (A/B/C/K/L/M/N, D–J parent intros, D–I/J leaves)."""
    out: set[str] = set()
    for parent in CANONICAL_SCHEMA["sections"]:
        pid = str(parent["id"]).upper()
        if pid in PARENT_STORAGE_PARENT_IDS:
            out.add(pid)
            continue
        subs = _subsection_rows(parent)
        if subs:
            if pid in PARENT_INTRO_SECTION_IDS:
                out.add(pid)
            out.update(str(s["id"]).upper() for s in subs)
        else:
            out.add(pid)
    return frozenset(out)


def valid_parent_section_ids() -> frozenset[str]:
    return frozenset(str(p["id"]).upper() for p in CANONICAL_SCHEMA["sections"])


def is_valid_leaf_section_id(section_id: str) -> bool:
    return (section_id or "").strip().upper() in valid_leaf_section_ids()


def is_canonical_schema(schema: TemplateSchema | None) -> bool:
    if schema is None:
        return False
    meta = schema.additional_metadata or {}
    if not meta.get("canonical_rics_l3"):
        return False
    if len(ordered_parent_sections(schema)) != PARENT_SECTION_COUNT:
        return False
    if len(schema.sections) != CANONICAL_SECTION_COUNT:
        return False
    return frozenset(s.id.upper() for s in schema.sections) == valid_leaf_section_ids()


def build_canonical_template_schema(
    *,
    source_filename: str = "RICS_L3_CANONICAL",
    tenant_id: str = "",
) -> TemplateSchema:
    """Materialise CANONICAL_SCHEMA into a :class:`TemplateSchema`."""
    sections: list[SectionDefinition] = []
    order = 0
    for parent in CANONICAL_SCHEMA["sections"]:
        pid = str(parent["id"])
        has_rating = bool(parent.get("has_rating_field"))
        # Parent-storage groups are one mapping unit each — never emit A1/C1/…
        if pid.upper() in PARENT_STORAGE_PARENT_IDS:
            title = str(parent["label"])
            sections.append(
                SectionDefinition(
                    id=pid,
                    title=title,
                    order=order,
                    level=1,
                    parent_id=None,
                    has_rating_field=has_rating,
                    keywords=_default_keywords(pid, title),
                )
            )
            order += 1
            continue
        subs = _subsection_rows(parent)
        if subs:
            if pid.upper() in PARENT_INTRO_SECTION_IDS:
                title = str(parent["label"])
                sections.append(
                    SectionDefinition(
                        id=pid,
                        title=title,
                        order=order,
                        level=1,
                        parent_id=None,
                        has_rating_field=False,
                        keywords=_default_keywords(pid, title),
                    )
                )
                order += 1
            for sub in subs:
                sid = str(sub["id"])
                title = str(sub["label"])
                sections.append(
                    SectionDefinition(
                        id=sid,
                        title=title,
                        order=order,
                        level=2,
                        parent_id=pid,
                        has_rating_field=has_rating,
                        keywords=_default_keywords(sid, title),
                    )
                )
                order += 1
        else:
            title = str(parent["label"])
            sections.append(
                SectionDefinition(
                    id=pid,
                    title=title,
                    order=order,
                    level=1,
                    parent_id=None,
                    has_rating_field=has_rating,
                    keywords=_default_keywords(pid, title),
                )
            )
            order += 1

    rating = CANONICAL_SCHEMA.get("rating_system") or {}
    rating_system = RatingSystem(
        detected=bool(rating.get("detected")),
        name="RICS Condition Rating",
        type=str(rating.get("type") or "RICS_3_TIER"),
        values=[
            RatingValue(value="1", label="No repair currently needed"),
            RatingValue(value="2", label="Defects that need repairing or replacing"),
            RatingValue(
                value="3", label="Defects that are serious and/or need urgent attention"
            ),
            RatingValue(value="NI", label="Not inspected"),
        ],
        format_template="Condition Rating [VALUE]",
    )

    return TemplateSchema(
        tenant_id=tenant_id,
        version=2,
        source_filename=source_filename,
        extracted_at=datetime.now(UTC).isoformat(),
        section_hierarchy="two-level",
        rating_system=rating_system,
        sections=sections,
        additional_metadata={
            "canonical_rics_l3": True,
            "schema_version_label": str(
                CANONICAL_SCHEMA.get("version", CANONICAL_SCHEMA_VERSION)
            ),
            "parent_section_count": PARENT_SECTION_COUNT,
            "leaf_section_count": CANONICAL_SECTION_COUNT,
            "real_leaf_section_count": CANONICAL_REAL_LEAF_COUNT,
            "parent_sections": [
                {"id": p["id"], "label": p["label"], "order": p["order"]}
                for p in CANONICAL_SCHEMA["sections"]
            ],
        },
    )


_EXTRA_KEYWORDS: dict[str, list[str]] = {
    "A": ["surveyor", "rics", "qualification", "company", "weather", "inspection", "occupied", "vacant"],
    "B": ["condition", "rating", "summary", "category", "overall", "opinion", "investigation"],
    "C": ["detached", "semi", "construction", "type", "year", "built", "accommodation", "epc", "location"],
    "D": ["outside", "external", "inspection", "ground", "binoculars", "access"],
    "E": ["inside", "internal", "inspection", "limitations", "access"],
    "F": ["services", "inspection", "meters", "not", "tested"],
    "G": ["grounds", "garden", "boundaries", "inspection"],
    "H": ["legal", "adviser", "solicitor", "enquiries"],
    "I": ["risks", "summary", "further", "investigation"],
    "J": ["energy", "epc", "insulation", "efficiency"],
    "D1": ["chimney", "stack", "flue", "pot"],    "D2": [
        "slate",
        "slates",
        "tile",
        "tiles",
        "covering",
        "coverings",
        "felt",
        "slipped",
    ],
    "D3": ["gutter", "gutters", "downpipe", "rainwater"],
    "D4": ["wall", "walls", "brick", "render", "cavity"],
    "D5": ["window", "windows", "glazing", "fensa"],
    "D6": ["door", "doors", "patio", "entrance"],
    "E1": ["truss", "rafter", "purlin", "roof", "structure", "loft"],
    "E2": ["ceiling", "ceilings", "plaster", "artex"],
    "E4": ["floor", "floors", "board", "boards"],
    "E5": ["fireplace", "flue", "chimney", "breast"],
    "E6": ["kitchen", "fitted", "built-in", "wardrobe"],
    "E7": ["staircase", "skirting", "architrave", "woodwork"],
    "E8": ["bathroom", "sanitary", "shower", "wc"],
    "F1": ["electric", "electricity", "wiring", "consumer"],
    "F2": ["gas", "oil", "lpg"],
    "F4": ["heating", "boiler", "radiator"],
    "F5": ["hot", "water", "cylinder", "combi"],
    "F6": ["drainage", "drain", "sewer"],
    "I3": ["asbestos", "chrysotile", "artex", "fire"],
    "J1": ["insulation", "loft", "cavity", "glasswool"],
}

# High-contrast anchor descriptors for product mapping units.
LEAF_ANCHOR_DESCRIPTORS: dict[str, str] = {
    "A": (
        "About the inspection: surveyor details, RICS membership, qualifications, "
        "company, indemnity, inspection date, related party disclosure, weather, "
        "property status occupied vacant furnished."
    ),
    "B": (
        "Overall opinion and summary of condition ratings, category 1 2 3, "
        "key findings, further investigations, specialist reports."
    ),
    "C": (
        "About the property: type and construction, year built, accommodation, "
        "energy efficiency EPC, location facilities flood radon."
    ),
    "D": (
        "Outside the property introduction: external inspection method, ground "
        "level, binoculars, access limitations, weather affecting the outside."
    ),
    "E": (
        "Inside the property introduction: internal inspection method, access "
        "limitations, furniture, floor coverings not lifted."
    ),
    "F": (
        "Services introduction: services not tested, meters, specialist "
        "inspection recommended, visual check only."
    ),
    "G": (
        "Grounds introduction: gardens, boundaries, inspection of grounds "
        "and shared areas."
    ),
    "H": (
        "Issues for your legal advisers introduction: matters for the "
        "solicitor, legal enquiries, not a legal report."
    ),
    "I": (
        "Risks introduction: summary of risks identified elsewhere in the "
        "report, further investigation."
    ),
    "J": (
        "Energy matters introduction: energy efficiency overview, EPC, "
        "insulation and services efficiency."
    ),
    "D1": (
        "Chimney stacks, chimney pots, flaunching, flashings, mortar, crown, "
        "cracking, leaning, TV aerial, brick stack."
    ),
    "D2": (
        "Roof coverings outside, slate, slates, clay tiles, concrete tiles, felt, "
        "flat roof, ridge tiles, valley, slipped tile, moss, lead flashing."
    ),
    "D3": "Rainwater pipes and gutters, downpipes, hopper, overflow, blocked gutter, cast iron, UPVC.",
    "D4": "Main walls external, cavity wall, brick, render, stone, pointing, DPC, cracking, erosion.",
    "D5": "Windows external, glazing, frames, double glazing, FENSA, rot, condensation between panes.",
    "D6": "Outside doors, patio doors, entrance door, external door frames, security, glazing.",
    "D7": "Conservatory and porches, glazed extension, polycarbonate, dwarf wall.",
    "D8": "Other joinery and finishes external, fascias, soffits, bargeboards, cladding.",
    "D9": "Other outside elements, balcony, external stairs, paths, decking.",
    "E1": (
        "Roof structure inside, trusses, rafters, purlins, collar ties, loft timbers, "
        "cut roof, trussed rafters, roof void structure."
    ),
    "E2": "Ceilings, plaster, lath and plaster, artex, cracking, staining, sagging.",
    "E3": "Walls and partitions internal, plaster, stud walls, damp patch, cracking.",
    "E4": "Floors, floorboards, suspended timber, solid floor, concrete, springy, uneven.",
    "E5": "Fireplaces, chimney breasts, flues, hearth, lintel, open fire, gas fire.",
    "E6": "Built-in fittings, fitted kitchen units, built-in wardrobes, cupboards, not appliances.",
    "E7": "Woodwork, staircase, joinery, skirting, architrave, internal doors.",
    "E8": "Bathroom fittings, sanitaryware, WC, basin, bath, shower, silicone.",
    "E9": "Other inside elements, cellar, basement, internal garage, loft conversion.",
    "F1": "Electricity, wiring, consumer unit, fusebox, circuits, earthing, RCD, EICR.",
    "F2": "Gas and oil, gas meter, oil tank, pipework, LPG, Gas Safe.",
    "F3": "Water supply, mains water, stopcock, lead pipe, storage tank.",
    "F4": "Heating, central heating, boiler, radiators, controls, warm air.",
    "F5": "Water heating, hot water cylinder, immersion heater, combi boiler hot water.",
    "F6": "Drainage, foul drain, surface water, manhole, sewer, septic tank.",
    "F7": "Common services, shared utilities, landlord supplies, block heating.",
    "G1": "Garage, car port, vehicle storage, up-and-over door.",
    "G2": "Permanent outbuildings, shed, workshop, barn, store.",
    "G3": "Other grounds, garden, boundaries, fences, driveway, retaining wall, shared areas flats.",
    "H1": "Regulation, building regulations, planning permission, listed building, conservation area.",
    "H2": "Guarantees, warranties, NHBC, FENSA, damp proof guarantee.",
    "H3": "Other legal matters, tenure, lease, easements, rights of way, covenants.",
    "I1": "Risks to the building, structural movement, subsidence, dampness, timber defects, rot.",
    "I2": "Risks to the grounds, flood, radon, mining, trees, shrinkable clay, knotweed.",
    "I3": "Risks to people, asbestos, fire safety, safety glass, lead pipes, trip hazards.",
    "I4": "Other risks or hazards, contamination, unexploded ordnance, invasive species.",
    "J1": "Insulation, loft insulation, cavity wall insulation, floor insulation, draught proofing.",
    "J2": "Heating energy efficiency, boiler efficiency, controls, zoning, heat pump.",
    "J3": "Lighting, low energy lighting, LED, natural light.",
    "J4": "Ventilation, trickle vents, extract fans, whole house ventilation.",
    "J5": "General energy matters, EPC improvements, renewable energy, solar panels.",
    "K": "Surveyor declaration, signature, RICS number, professional standards, indemnity.",
    "L": "What to do now, obtain quotations, further steps, recommended actions.",
    "M": "Terms of engagement, scope of survey, fee, liability, complaints, service description.",
    "N": "Typical house diagram, illustration, elevation sketch, roof plan reference.",
}


def iter_canonical_leaf_sections() -> list[tuple[str, str, str, str]]:
    """Return ordered ``(section_id, parent_label, section_label, descriptor)`` rows."""
    rows: list[tuple[str, str, str, str]] = []
    for parent in CANONICAL_SCHEMA["sections"]:
        pid = str(parent["id"])
        plabel = str(parent["label"])
        if pid.upper() in PARENT_STORAGE_PARENT_IDS:
            sid = pid.upper()
            desc = LEAF_ANCHOR_DESCRIPTORS.get(sid, plabel)
            rows.append((sid, plabel, plabel, desc))
            continue
        subs = _subsection_rows(parent)
        if subs:
            if pid.upper() in PARENT_INTRO_SECTION_IDS:
                desc = LEAF_ANCHOR_DESCRIPTORS.get(pid.upper(), plabel)
                rows.append((pid.upper(), plabel, plabel, desc))
            for sub in subs:
                sid = str(sub["id"]).upper()
                leaf = str(sub["label"])
                desc = LEAF_ANCHOR_DESCRIPTORS.get(sid, leaf)
                rows.append((sid, plabel, leaf, desc))
        else:
            sid = pid.upper()
            desc = LEAF_ANCHOR_DESCRIPTORS.get(sid, plabel)
            rows.append((sid, plabel, plabel, desc))
    return rows


def build_section_anchor_text(section_id: str) -> str:
    """Descriptive anchor string for embedding-based note classification."""
    sid = (section_id or "").strip().upper()
    for leaf_id, parent_label, leaf_label, descriptor in iter_canonical_leaf_sections():
        if leaf_id == sid:
            return f"Section {leaf_id}. {parent_label}: {leaf_label}. {descriptor}"
    raise KeyError(f"Unknown canonical leaf section: {section_id!r}")


def _default_keywords(section_id: str, title: str) -> list[str]:
    import re

    words = re.findall(r"[a-z]{4,}", title.lower())
    stop = {
        "with",
        "from",
        "that",
        "this",
        "your",
        "other",
        "about",
        "the",
        "and",
        "for",
    }
    kws = [w for w in words if w not in stop][:6]
    kws.extend(_EXTRA_KEYWORDS.get(section_id.upper(), []))
    kws.insert(0, section_id.lower())
    return list(dict.fromkeys(kws))


def ordered_parent_sections(schema: TemplateSchema) -> list[SectionDefinition]:
    """Return exactly 14 parent section stubs in canonical order."""
    meta_parents = (schema.additional_metadata or {}).get("parent_sections") or []
    if meta_parents:
        return [
            SectionDefinition(
                id=str(p["id"]),
                title=str(p.get("label") or p.get("title") or p["id"]),
                order=int(p.get("order", idx)) - 1,
                level=1,
            )
            for idx, p in enumerate(meta_parents, start=1)
        ]
    parents: dict[str, SectionDefinition] = {}
    for sec in schema.sections:
        if sec.parent_id:
            parents.setdefault(
                sec.parent_id,
                SectionDefinition(
                    id=sec.parent_id, title=sec.parent_id, order=sec.order, level=1
                ),
            )
        else:
            parents[sec.id] = sec
    return sorted(parents.values(), key=lambda s: s.order)[:PARENT_SECTION_COUNT]


def mapping_units_for_parent(
    schema: TemplateSchema, parent_id: str
) -> list[SectionDefinition]:
    """Mapping units under a parent: intro unit (D–J) then leaves, or the parent itself."""
    pid = parent_id.strip().upper()
    children = [
        s for s in schema.ordered_sections() if (s.parent_id or "").upper() == pid
    ]
    parent = schema.get_section(pid)
    if children:
        if parent is not None and not parent.parent_id:
            return [parent, *children]
        return children
    return [parent] if parent else []
