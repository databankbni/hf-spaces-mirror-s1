"""Canonical Priority-2 (high-confidence) keyword lexicon for RICS L3 note routing.

Order is significant: first match wins. Hazards and grounds (G) precede building
fabric (D/E/F). Insulation phrases are disambiguated before generic fallbacks.
"""

from __future__ import annotations

import re
from typing import Final

# (section_id, regex pattern) — evaluated top-to-bottom; synced to frontend highConfidence[].
HIGH_CONFIDENCE_LEXICON: Final[list[tuple[str, str]]] = [
    # ── I: Risks (before element keywords that share vocabulary) ─────────────
    ("I3", r"asbestos|chrysotile|aib\b|suspected.*artex"),
    (
        "I1",
        # condensation/mould deliberately NOT high-confidence here: they are symptoms
        # observed ON an element (windows D5, bathroom E8, ceilings E2) and must inherit
        # the block's element context rather than be force-routed to "risks to the
        # building". They remain a WEAK general-keyword fallback (notes_keyword_router)
        # for genuinely context-free lines.
        r"woodworm|dry\s*rot|wet\s*rot|structural\s*movement|dampness|"
        r"rising\s*damp|penetrat.*damp|subsiden|timber\s*decay",
    ),
    ("I2", r"japanese\s*knotweed|knotweed|invasive\s*species|flood\s*risk|tree\s*root"),
    ("I4", r"contamination|unexploded|other\s*hazard|other\s*risk"),
    # ── A / B / C: parent-level units ─────────────────────────────────────────
    (
        "A",
        r"surveyor\s*name|rics\s*member|surveyor.*qualif|company\s*name|indemnity|\bsurveyor\b|"
        r"date\s*of\s*inspection|inspection\s*date|survey\s*date|date\s*of\s*survey|"
        r"disclosure|related\s*party|conflict\s*of\s*interest|third\s*party\s*disclos|"
        r"\bweather\b(?!\s*(?:bar|board))|\braining\b|dry\s*day|wet\s*day|conditions\s*on\s*site|overcast|"
        r"unoccupied|vacant|occupied|furnished|unfurnished|property\s*status|tenant",
    ),
    (
        "B",
        r"condition\s*rating\s*3|category\s*3|summary\s*of\s*condition|condition\s*rat|"
        r"urgent\s*repair|overall\s*opinion|general\s*condition|key\s*findings|"
        r"further\s*investigation|further\s*invest|specialist\s*report|additional\s*survey",
    ),
    (
        "C",
        r"detached|semi.?det|\bdet(ached)?\b|terraced|bungalow|maisonette|"
        r"timber\s*frame\s*(?:property|construction|build)|type\s*and\s*construct|"
        r"built\s*around|extended|year\s*built|approximate\s*year|circa\s*19|circa\s*20|built\s*in\s*19|"
        r"accommodation|bedroom|reception\s*room|storey|room\s*matrix|floor\s*area|sq\.?\s*m\b|"
        r"\bepc\b|mains\s*gas|mains\s*electric|energy\s*effici|sap\s*rating|"
        r"amenities|location|facilities|flood\s*zone|radon|mining|noise\s*nuisance",
    ),
    # ── G: Grounds — always before D/E/F fabric ─────────────────────────────
    ("G1", r"\bgarage\b|car\s*port"),
    ("G2", r"outbuilding|permanent\s*outbuild|\bshed\b|workshop|\bbarn\b"),
    # "leaning"/"brick wall" removed: a leaning or brick WALL is the external wall (D4),
    # and a leaning TV aerial is D1 — neither is grounds. Boundary/retaining/garden
    # walls remain here via their explicit phrases.
    (
        "G3",
        r"driveway|boundary\s*wall|fencing|\bfence\b|patio(?!\s*door)|\bgarden\b|boundary|hedge|retaining\s*wall|timber\s*fenc",
    ),
    # ── Insulation disambiguation (specific compound phrases first) ──────────
    ("J1", r"cavity\s*insul"),
    ("E1", r"roof\s*insul|roof\s*void\s*insul"),
    ("J1", r"loft\s*insul"),
    # ── E5 fireplaces before external chimneys (chimney breast ≠ chimney stack) ─
    (
        "E5",
        r"chimney\s*breast|hearth|woodburner|wood\s*burner|flue\s*liner|fireplace|open\s*fire",
    ),
    # ── D: Outside the property ──────────────────────────────────────────────
    (
        "D1",
        r"chimney\s*stack|chimney\s*pot|flaunch|flaunching|chimney\s*flashing|"
        r"repoint.*chimney|chimney.*repoint|\bchimney\b|tv\s*aerial|stack.*brick",
    ),
    (
        "D2",
        r"main\s*roof|valley\s*gutter|slates|slipped\s*slate|slipped\s*tile|clay\s*tiles|"
        r"pitched\s*roof|flat\s*roof|felt\s*roof|roof\s*cover|battens|tile\s*roof|ridge\s*tile|"
        r"\bverges?\b|roof[^.\n]*re-?point|re-?point[^.\n]*roof|ridge[^.\n]*re-?point",
    ),
    (
        "D3",
        r"rainwater\s*fittings?|rainwater\s*goods|(?<!valley\s)gutters|downpipe|down\s*pipe|"
        r"gullies|rwp\b|hopper|\brainwater\b",
    ),
    (
        "D4",
        # Bare "pointing"/"repoint" deliberately excluded here: chimneys (D1) and
        # roofs (D2) are repointed too, so an unqualified repointing mention is
        # ambiguous. It stays a Priority-3 (general) D4 fallback, which lets the
        # block-level parser inherit the established element instead of hijacking
        # generic "repairs and repointing" boilerplate to the walls.
        r"external\s*walls?|main\s*walls?|cavity\s*wall|brickwork|brick\s*walls?|rendering|render\b|"
        r"wall\s*re-?point|re-?point.*wall|step\s*crack|wall.*crack|crack.*wall|lintel|dpc\b|parapet|erosion|"
        r"fixing\s*bar|wall\s*tie|cavity\s*wall\s*tie",
    ),
    (
        "D5",
        r"glazing|double\s*glaz|upvc\s*window|timber\s*frame\s*(?:window|casement|doors?)|casement|"
        r"\bwindows?\b|window\s*sill|\bsill\b|fensa|sash\s*window|bay\s*window",
    ),
    (
        "D6",
        r"patio\s*door|front\s*door|rear\s*door|threshold|bifold|external\s*door|"
        r"outside\s*door|entrance\s*door|back\s*door|french\s*door",
    ),
    ("D7", r"conservatory|porch\b"),
    ("D8", r"fascia\b|soffit\b|bargeboard|external\s*joinery|cladding"),
    ("D9", r"balcony|external\s*stair|other\s*outside"),
    # ── E: Inside the property ───────────────────────────────────────────────
    (
        "E1",
        r"loft\s*conversion|rafters|purlins|purlin|truss|collar\s*tie|cut\s*rafter|"
        r"loft\s*hatch|roof\s*struct|trussed\s*rafter|astragal|wasteness|"
        r"building\s*regulation.*support|support.*building\s*regulation",
    ),
    (
        "E2",
        r"plasterboard\s*ceil|lath\s*and\s*plaster|ceiling\s*crack|ceilings?\b|artex|lath.*plaster",
    ),
    ("E3", r"stud\s*wall|internal\s*partition|internal\s*wall|plastering|partition"),
    (
        "E4",
        r"suspended\s*timber|solid\s*concrete\s*floor|floorboards|floor\s*tiles|"
        r"suspended\s*floor|solid\s*floor|sub.?floor|springy\s*floor",
    ),
    (
        "E6",
        r"built.?in\s*fit|fitted\s*kitchen|built.?in\s*wardrobe|kitchen\s*unit|\bkitchen\b",
    ),
    ("E7", r"skirting|architrave|staircase|internal\s*door|woodwork|joinery"),
    (
        "E8",
        r"bathroom|bathtub|\bbath\b|\btoilet\b|sanitary|shower|wc\b|basin|sanitary\s*ware|ventilation\s*fan|extract\s*fan|\bfan\b",
    ),
    # ── F: Services (before E9 cellar/basement — location must not beat service type) ─
    (
        "F1",
        r"consumer\s*unit|fuse\s*board|wiring|\bsockets?\b|electric\s*meter|eicr|earthing|rcd\b|\belectric|verdigris",
    ),
    (
        "F2",
        r"gas\s*meter|gas\s*supply|\blpg\b|gas\s*pipe|gas\s*safe|\bgas\b|oil\s*tank",
    ),
    ("F3", r"water\s*supply|stopcock|mains\s*water|lead\s*pipe"),
    (
        "F4",
        r"boiler|central\s*heat|radiators|radiator|heating\s*system|vaillant|worcester",
    ),
    ("F5", r"cylinder|immersion\s*heater|immersion|hot\s*water|combi|water\s*heat"),
    (
        "F6",
        r"manhole|inspection\s*chamber|foul\s*drain|soil\s*pipe|soil\s*and\s*vent|vent\s*stack|soil\s*stack|\bsvp\b|sewer|septic|\bdrainage\b|\bdrain\b",
    ),
    (
        "F7",
        r"common\s*service|shared\s*util|landlord\s*suppl|alarm|burglar|security\s*system|sensor",
    ),
    ("E9", r"cellar|basement|other\s*inside"),
    # ── H: Legal ─────────────────────────────────────────────────────────────
    (
        "H1",
        r"building\s*reg|planning\s*permiss|listed\s*build|conservation\s*area|regulation|"
        r"(?:load.?bearing|supporting)\s*walls?[^.\n]*remov|remov[^.\n]*(?:load.?bearing|supporting)\s*walls?|"
        r"structural\s*alteration|converted\s*to\s*flat|flat.*convert",
    ),
    ("H2", r"guarantee|warranty|nhbc|fensa\s*certif"),
    ("H3", r"tenure|leasehold|freehold|easement|covenant|legal\s*advis"),
    # ── J: Energy matters (general insulation fallback last) ─────────────────
    ("J3", r"low\s*energy\s*light|\bled\b|lighting"),
    ("J4", r"ventilation|trickle\s*vent|extract\s*fan"),
    ("J2", r"boiler\s*effici|heating\s*effici|heat\s*pump|zone\s*control"),
    ("J5", r"solar\s*panel|renewable|energy\s*matter|epc\s*improv"),
    ("J1", r"\binsulation\b|wall\s*insul"),
    # ── K / L / M / N (parent-level units) ────────────────────────────────────
    ("K", r"surveyor\s*declar|signature|rics\s*number|professional\s*stand"),
    ("L", r"what\s*to\s*do|obtain\s*quot|next\s*step|recommended\s*action"),
    ("M", r"terms\s*of\s*engage|scope\s*of\s*survey|service\s*description|complaints"),
    ("N", r"typical\s*house\s*diagram|diagram\s*reference|elevation\s*sketch"),
]


def compile_high_confidence_patterns() -> list[tuple[str, re.Pattern[str]]]:
    """Compile lexicon entries into regex patterns."""
    return [
        (section_id, re.compile(pattern, re.IGNORECASE))
        for section_id, pattern in HIGH_CONFIDENCE_LEXICON
    ]
