"""Generate STATIC_L3_SECTIONS for frontend/index.html."""

from __future__ import annotations

from backend.domain.rics_level3_schema import CANONICAL_SCHEMA
from backend.domain.section_scope import (
    PARENT_INTRO_SECTION_IDS,
    PARENT_STORAGE_PARENT_IDS,
)

HINTS = {
    "A": "surveyor · RICS · inspection date · weather · occupancy · related party",
    "B": "condition ratings summary · overall opinion · further investigations",
    "C": "property type · construction · year built · accommodation · EPC · location",
    "D": "external inspection · ground level · binoculars · access limitations",
    "D1": "chimney stacks · pots · flaunching · flashings · lean · condition rating",
    "D2": "roof covering · slate · tile · felt · slipped tiles · moss · condition rating",
    "D3": "gutters · downpipes · rainwater · hopper · leakage · condition rating",
    "D4": "main walls · cavity · render · DPC · cracking · condition rating",
    "D5": "windows · glazing · FENSA · frames · condition rating",
    "D6": "outside doors · patio doors · entrance door · condition rating",
    "D7": "conservatory · porch · glazing · condition rating",
    "D8": "fascias · soffits · external joinery · condition rating",
    "D9": "other outside elements · balconies · external stairs",
    "E": "internal inspection · access · furniture · floor coverings not lifted",
    "E1": "roof structure · trusses · rafters · purlins · loft access · condition rating",
    "E2": "ceilings · plaster · artex · cracking · condition rating",
    "E3": "walls · partitions · damp · cracking · condition rating",
    "E4": "floors · suspended · solid · springy · condition rating",
    "E5": "fireplaces · chimney breasts · flues · hearth · condition rating",
    "E6": "built-in kitchen · fitted wardrobes · cupboards · condition rating",
    "E7": "staircase · skirting · architrave · internal doors · condition rating",
    "E8": "bathroom fittings · sanitaryware · shower · WC · condition rating",
    "E9": "cellar · basement · other inside · condition rating",
    "F": "services inspection · meters · not tested · visual check",
    "F1": "electricity · consumer unit · wiring · EICR · condition rating",
    "F2": "gas · oil · meter · pipework · Gas Safe · condition rating",
    "F3": "water supply · stopcock · lead pipes · condition rating",
    "F4": "heating · boiler · radiators · controls · condition rating",
    "F5": "water heating · cylinder · combi · immersion · condition rating",
    "F6": "drainage · manholes · sewers · condition rating",
    "F7": "common services · shared utilities · flats only",
    "G": "grounds inspection · garden · boundaries · shared areas",
    "G1": "garage · car port · door · condition rating",
    "G2": "outbuildings · shed · workshop · condition rating",
    "G3": "boundaries · garden · driveway · shared areas · condition rating",
    "H": "legal introduction · solicitor enquiries · not a legal report",
    "H1": "regulations · planning · listed building · conservation area",
    "H2": "guarantees · NHBC · FENSA · warranties",
    "H3": "tenure · lease · easements · other legal matters",
    "I": "risks introduction · further investigation · summary of risks",
    "I1": "structural movement · dampness · timber defects · building risks",
    "I2": "flood · radon · mining · knotweed · ground risks",
    "I3": "asbestos · fire safety · safety glass · people risks",
    "I4": "other risks · contamination · hazards",
    "J": "energy introduction · EPC · insulation overview",
    "J1": "insulation · loft · cavity · floor insulation",
    "J2": "heating efficiency · boiler · heat pump",
    "J3": "lighting · LED · natural light",
    "J4": "ventilation · trickle vents · extract fans",
    "J5": "general energy · solar · EPC improvements",
    "K": "surveyor declaration · signature · RICS · qualifications",
    "L": "quotations · next steps · recommended actions",
    "M": "terms of engagement · scope · fee · complaints",
    "N": "typical house diagram · illustration reference",
}

lines = ["const STATIC_L3_SECTIONS = ["]
for parent in CANONICAL_SCHEMA["sections"]:
    gid = str(parent["id"])
    if gid.upper() in PARENT_STORAGE_PARENT_IDS:
        title = str(parent["label"]).replace("'", "\\'")
        hint = HINTS.get(gid, title)
        lines.append(
            f"  {{ code:'{gid}', group:'{gid}', title:'{title}', hint:'{hint}' }},"
        )
        continue
    if gid.upper() in PARENT_INTRO_SECTION_IDS:
        title = str(parent["label"]).replace("'", "\\'")
        hint = HINTS.get(gid, title)
        lines.append(
            f"  {{ code:'{gid}', group:'{gid}', title:'{title}', hint:'{hint}' }},"
        )
    for sub in parent.get("subsections") or []:
        code = str(sub["id"])
        title = str(sub["label"]).replace("'", "\\'")
        hint = HINTS.get(code, title)
        lines.append(
            f"  {{ code:'{code}', group:'{gid}', title:'{title}', hint:'{hint}' }},"
        )
lines.append("];")
print("\n".join(lines))
