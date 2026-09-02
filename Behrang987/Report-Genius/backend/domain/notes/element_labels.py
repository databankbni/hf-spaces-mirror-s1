"""RICS L3 element-label prefixes used by surveyors in field notes (``Main roof:``, …)."""

from __future__ import annotations

from typing import Final

# (section_id, label regex) — matched only at line start before the first colon.
# More specific / longer labels must appear before shorter overlapping ones.
ELEMENT_LABEL_ROUTES: Final[list[tuple[str, str]]] = [
    # ── A / B / C (parent-level units) ────────────────────────────────────────
    ("A", r"weather(?:\s*conditions)?|(?:property\s*)?status|(?:occupied|vacant|unoccupied)|about\s*the\s*inspection"),
    ("B", r"overall\s*opinion|summary\s*of\s*condition(?:\s*ratings?)?|condition\s*ratings?"),
    ("C", r"type\s*(?:and\s*)?construction|property\s*type|(?:approximate\s*)?year\s*of\s*construction|year\s*built|accommodation|energy\s*effici(?:ency|ent)|(?:\bepc\b)|location(?:\s*and\s*facilities)?|facilities|amenities"),
    # ── G before D (garage/outbuildings before roof/walls) ───────────────────
    ("G1", r"garage"),
    ("G2", r"(?:permanent\s*)?outbuildings?|outbuilding"),
    ("G3", r"grounds|garden|driveway|boundaries|boundary"),
    # ── D outside fabric ─────────────────────────────────────────────────────
    ("D1", r"chimney\s*stacks?|chimneys?"),
    ("D2", r"main\s*roof|roof\s*coverings?|roof\s*cover"),
    ("D3", r"rainwater\s*(?:fittings|goods|pipes?(?:\s*and\s*gutters)?)|rainwater"),
    ("D4", r"(?:external|main)\s*walls?"),
    ("D5", r"windows?"),
    ("D6", r"(?:outside|external)\s*doors?(?:\s*\([^)]*\))?|patio\s*doors?"),
    ("D7", r"conservatory(?:\s*and\s*porches?)?|porches?"),
    ("D8", r"(?:other\s*)?(?:joinery|fascias?|soffits?)"),
    ("D9", r"other(?:\s*outside)?"),
    # ── E inside fabric ──────────────────────────────────────────────────────
    ("E1", r"roof\s*structure|loft(?:\s*conversion)?"),
    ("E2", r"ceilings?"),
    ("E3", r"walls?\s*and\s*partitions?|internal\s*walls?|partitions?"),
    ("E4", r"floors?"),
    (
        "E5",
        r"fireplaces?(?:\s*,?\s*chimney\s*breasts?(?:\s*and\s*flues?)?)?|chimney\s*breasts?",
    ),
    ("E6", r"built.?in\s*fit(?:tings)?"),
    ("E7", r"woodwork|staircase"),
    ("E8", r"bathroom\s*fit(?:tings)?|sanitary(?:\s*ware)?"),
    ("E9", r"other(?:\s*inside)?|cellar|basement"),
    # ── F services ───────────────────────────────────────────────────────────
    ("F1", r"electricity|electrics?"),
    ("F2", r"gas(?:\s*and\s*oil)?|oil(?:\s*tank)?"),
    ("F3", r"water(?:\s*supply)?"),
    ("F4", r"heating|central\s*heating"),
    ("F5", r"water\s*heating|hot\s*water"),
    ("F6", r"drainage|drains?|sewers?"),
    ("F7", r"common\s*services?"),
    # ── H / I / J ────────────────────────────────────────────────────────────
    ("H1", r"regulation|planning"),
    ("H2", r"guarantees?|warranties?"),
    ("H3", r"tenure|legal(?:\s*matters)?|other\s*matters"),
    ("I1", r"risks?\s*to\s*(?:the\s*)?building|building\s*risks?"),
    ("I2", r"risks?\s*to\s*(?:the\s*)?grounds|ground\s*risks?"),
    ("I3", r"risks?\s*to\s*(?:people|persons)|asbestos"),
    ("I4", r"other\s*risks?(?:\s*or\s*hazards?)?"),
    ("J1", r"insulation"),
    ("J2", r"heating\s*effici(?:ency|ent)"),
    ("J3", r"lighting"),
    ("J4", r"ventilation"),
    ("J5", r"general|energy\s*matters"),
]
