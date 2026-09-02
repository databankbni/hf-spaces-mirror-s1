"""Patch frontend/index.html with official 54-leaf STATIC_L3_SECTIONS."""

from __future__ import annotations

from pathlib import Path

from backend.domain.rics_level3_schema import CANONICAL_SCHEMA

HINTS = {
    "A1": "surveyor name · RICS number · qualifications · company · contact",
    "A2": "inspection date · time on site",
    "A3": "related party · conflict of interest",
    "A4": "weather · dry · wet · overcast",
    "A5": "occupied · vacant · furnished · access limitations",
    "B1": "condition ratings summary · Cat 1 · Cat 2 · Cat 3",
    "B2": "overall opinion · key findings",
    "B3": "further investigations · specialist reports",
    "C1": "property type · construction · detached · cavity · timber frame",
    "C2": "year built · approximate age · period",
    "C3": "accommodation · bedrooms · bathrooms · storeys · room matrix",
    "C4": "EPC · energy efficiency · double glazing",
    "C5": "location · facilities · flood · radon · noise",
    "D1": "chimney stacks · pots · flaunching · flashings · lean · condition rating",
    "D2": "roof covering · slate · tile · felt · slipped tiles · moss · condition rating",
    "D3": "gutters · downpipes · rainwater · hopper · leakage · condition rating",
    "D4": "main walls · cavity · render · DPC · cracking · condition rating",
    "D5": "windows · glazing · FENSA · frames · condition rating",
    "D6": "outside doors · patio doors · entrance door · condition rating",
    "D7": "conservatory · porch · glazing · condition rating",
    "D8": "fascias · soffits · external joinery · condition rating",
    "D9": "other outside elements · balconies · external stairs",
    "E1": "roof structure · trusses · rafters · purlins · loft access · condition rating",
    "E2": "ceilings · plaster · artex · cracking · condition rating",
    "E3": "walls · partitions · damp · cracking · condition rating",
    "E4": "floors · suspended · solid · springy · condition rating",
    "E5": "fireplaces · chimney breasts · flues · hearth · condition rating",
    "E6": "built-in kitchen · fitted wardrobes · cupboards · condition rating",
    "E7": "staircase · skirting · architrave · internal doors · condition rating",
    "E8": "bathroom fittings · sanitaryware · shower · WC · condition rating",
    "E9": "cellar · basement · other inside · condition rating",
    "F1": "electricity · consumer unit · wiring · EICR · condition rating",
    "F2": "gas · oil · meter · pipework · Gas Safe · condition rating",
    "F3": "water supply · stopcock · lead pipes · condition rating",
    "F4": "heating · boiler · radiators · controls · condition rating",
    "F5": "water heating · cylinder · combi · immersion · condition rating",
    "F6": "drainage · manholes · sewers · condition rating",
    "F7": "common services · shared utilities · flats only",
    "G1": "garage · car port · door · condition rating",
    "G2": "outbuildings · shed · workshop · condition rating",
    "G3": "boundaries · garden · driveway · shared areas · condition rating",
    "H1": "regulations · planning · listed building · conservation area",
    "H2": "guarantees · NHBC · FENSA · warranties",
    "H3": "tenure · lease · easements · other legal matters",
    "I1": "structural movement · dampness · timber defects · building risks",
    "I2": "flood · radon · mining · knotweed · ground risks",
    "I3": "asbestos · fire safety · safety glass · people risks",
    "I4": "other risks · contamination · hazards",
    "J1": "insulation · loft · cavity · floor insulation",
    "J2": "heating efficiency · boiler · heat pump",
    "J3": "lighting · LED · natural light",
    "J4": "ventilation · trickle vents · extract fans",
    "J5": "general energy · solar · EPC improvements",
    "K1": "surveyor declaration · signature · RICS · qualifications",
    "L1": "quotations · next steps · recommended actions",
    "M1": "terms of engagement · scope · fee · complaints",
    "N1": "typical house diagram · illustration reference",
}

ROUTES_JS = """function routeLinesToSections(lines) {
  const routes = [
    { code:'A1', rx:/surveyor|rics\\s*member|qualification|company\\s*name|indemnity/i },
    { code:'A2', rx:/date\\s*of\\s*inspection|inspection\\s*date|survey\\s*date/i },
    { code:'A3', rx:/related\\s*party|conflict\\s*of\\s*interest/i },
    { code:'A4', rx:/weather|conditions\\s*on\\s*site|dry\\s*day|wet\\s*day/i },
    { code:'A5', rx:/occupied|vacant|furnished|property\\s*status/i },
    { code:'B1', rx:/summary\\s*of\\s*condition|condition\\s*rat|category\\s*[123]/i },
    { code:'B2', rx:/overall\\s*opinion|general\\s*condition|key\\s*findings/i },
    { code:'B3', rx:/further\\s*invest|specialist\\s*report/i },
    { code:'C1', rx:/\\bsemi.?det|\\bdet(ached)?\\b|terraced|bungalow|maisonette|type\\s*and\\s*construct|timber\\s*frame|cavity\\s*wall/i },
    { code:'C2', rx:/year\\s*built|approximate\\s*year|circa\\s*19|circa\\s*20|built\\s*in\\s*19/i },
    { code:'C3', rx:/accommodation|bedroom|reception\\s*room|storey|room\\s*matrix|sq\\.?\\s*m\\b/i },
    { code:'C4', rx:/\\bepc\\b|energy\\s*effici|sap\\s*rating/i },
    { code:'C5', rx:/location|facilities|flood\\s*zone|radon|mining|contamination/i },
    { code:'D1', rx:/chimney\\s*stack|chimney\\s*pot|flaunch|\\bchimney\\b|stack.*brick|tv\\s*aerial/i },
    { code:'D2', rx:/roof\\s*cover|slate|slates|tile\\s*roof|felt\\s*roof|flat\\s*roof|hip\\s*roof|ridge\\s*tile|slipp|moss.*roof/i },
    { code:'D3', rx:/rainwater|gutter|gutters|downpipe|down\\s*pipe|gullies|rwp\\b|hopper|fittings.*brittle/i },
    { code:'D4', rx:/main\\s*wall|external\\s*wall|brick\\s*wall|cavity\\s*wall|render|pointing|dpc\\b|parapet/i },
    { code:'D5', rx:/window|glazing|fensa|upvc\\s*window|sash\\s*window|bay\\s*window/i },
    { code:'D6', rx:/external\\s*door|outside\\s*door|patio\\s*door|entrance\\s*door|front\\s*door/i },
    { code:'D7', rx:/conservatory|porch\\b/i },
    { code:'D8', rx:/fascia\\b|soffit\\b|bargeboard|external\\s*joinery|cladding/i },
    { code:'D9', rx:/balcony|external\\s*stair|other\\s*outside/i },
    { code:'E1', rx:/roof\\s*struct|truss|purlin|collar\\s*tie|cut\\s*rafter|trussed\\s*rafter|rafter.*loft|loft\\s*hatch/i },
    { code:'E2', rx:/ceil|ceiling|artex|lath.*plaster/i },
    { code:'E3', rx:/internal\\s*wall|partition|plaster.*wall|stud\\s*wall|rising\\s*damp|penetrat.*damp/i },
    { code:'E4', rx:/floor\\s*board|suspended\\s*floor|solid\\s*floor|sub.?floor|springy\\s*floor/i },
    { code:'E5', rx:/fireplace|chimney\\s*breast|hearth|open\\s*fire|flue\\s*liner/i },
    { code:'E6', rx:/built.?in\\s*fit|fitted\\s*kitchen|built.?in\\s*wardrobe|kitchen\\s*unit/i },
    { code:'E7', rx:/skirting|architrave|staircase|internal\\s*door|woodwork|joinery/i },
    { code:'E8', rx:/bathroom|sanitary|shower|wc\\b|basin/i },
    { code:'E9', rx:/cellar|basement|other\\s*inside/i },
    { code:'F1', rx:/electric|consumer\\s*unit|fuse\\s*board|wiring|earthing|rcd\\b|eicr/i },
    { code:'F2', rx:/\\bgas\\b|oil\\s*tank|lpg|gas\\s*meter|gas\\s*pipe|gas\\s*safe/i },
    { code:'F3', rx:/water\\s*supply|stopcock|mains\\s*water|lead\\s*pipe/i },
    { code:'F4', rx:/boiler|central\\s*heat|radiator|heating\\s*system|vaillant|worcester/i },
    { code:'F5', rx:/hot\\s*water|water\\s*heat|cylinder|combi|immersion/i },
    { code:'F6', rx:/drain|sewer|manhole|soil\\s*pipe|septic|gully/i },
    { code:'F7', rx:/common\\s*service|shared\\s*util/i },
    { code:'G1', rx:/\\bgarage\\b|car\\s*port/i },
    { code:'G2', rx:/outbuilding|shed\\b|workshop|permanent\\s*outbuild/i },
    { code:'G3', rx:/boundary|fence\\b|hedge|retaining\\s*wall|garden\\b|driveway|grounds/i },
    { code:'H1', rx:/building\\s*reg|planning\\s*permiss|listed\\s*build|conservation\\s*area|regulation/i },
    { code:'H2', rx:/guarantee|warranty|nhbc|fensa\\s*certif/i },
    { code:'H3', rx:/tenure|leasehold|freehold|easement|covenant|legal\\s*advis/i },
    { code:'I1', rx:/rising\\s*damp|penetrat.*damp|condensation|mould|subsiden|structural\\s*movement|woodworm|dry\\s*rot|wet\\s*rot|timber\\s*decay/i },
    { code:'I2', rx:/flood\\s*risk|radon|mining|knotweed|tree\\s*root|shrinkable\\s*clay|risk.*ground/i },
    { code:'I3', rx:/asbestos|chrysotile|aib\\b|fire\\s*safety|safety\\s*glass|lead\\s*pipe|trip\\s*hazard|balustrade/i },
    { code:'I4', rx:/contamination|unexploded|invasive\\s*species|other\\s*risk|other\\s*hazard/i },
    { code:'J1', rx:/loft\\s*insul|roof\\s*void\\s*insul|cavity\\s*insul|insulation/i },
    { code:'J2', rx:/boiler\\s*effici|heating\\s*effici|heat\\s*pump|zone\\s*control/i },
    { code:'J3', rx:/lighting|led\\b|low\\s*energy\\s*light/i },
    { code:'J4', rx:/ventilation|trickle\\s*vent|extract\\s*fan/i },
    { code:'J5', rx:/energy\\s*matter|renewable|solar\\s*panel|epc\\s*improv/i },
    { code:'K1', rx:/surveyor\\s*declar|signature|rics\\s*number/i },
    { code:'L1', rx:/what\\s*to\\s*do|obtain\\s*quot|next\\s*step/i },
    { code:'M1', rx:/terms\\s*of\\s*engage|scope\\s*of\\s*survey|service\\s*description/i },
    { code:'N1', rx:/typical\\s*house\\s*diagram|diagram\\s*reference/i },
  ];"""

GROUP_LABELS = """const STATIC_L3_GROUP_LABELS = {
  A:'A — About the inspection',
  B:'B — Overall opinion and summary of ratings',
  C:'C — About the property',
  D:'D — Outside the property',
  E:'E — Inside the property',
  F:'F — Services',
  G:'G — Grounds (including shared areas for flats)',
  H:'H — Issues for your legal advisers',
  I:'I — Risks',
  J:'J — Energy matters',
  K:"K — Surveyor's declaration",
  L:'L — What to do now',
  M:'M — Description of the RICS Home Survey - Level 3 service and terms of engagement',
  N:'N — Typical house diagram',
};"""


def _sections_block() -> str:
    lines = ["const STATIC_L3_SECTIONS = ["]
    for parent in CANONICAL_SCHEMA["sections"]:
        gid = str(parent["id"])
        for sub in parent.get("subsections") or []:
            code = str(sub["id"])
            title = str(sub["label"]).replace("'", "\\'")
            hint = HINTS.get(code, title)
            lines.append(
                f"  {{ code:'{code}', group:'{gid}', title:'{title}', hint:'{hint}' }},"
            )
    lines.append("];")
    return "\n".join(lines)


def main() -> None:
    path = Path(__file__).resolve().parents[2] / "frontend" / "index.html"
    text = path.read_text(encoding="utf-8")

    start = text.index("const STATIC_L3_SECTIONS = [")
    end = text.index("];", start) + 2
    text = text[:start] + _sections_block() + text[end:]

    gl_start = text.index("const STATIC_L3_GROUP_LABELS = {")
    gl_end = text.index("};", gl_start) + 2
    text = text[:gl_start] + GROUP_LABELS + text[gl_end:]

    fn_start = text.index("function routeLinesToSections(lines) {")
    fn_end = text.index("  const routeCodes = ", fn_start)
    text = text[:fn_start] + ROUTES_JS.strip() + "\n\n" + text[fn_end:]

    # Fix comment above routeLinesToSections
    text = text.replace(
        " * Codes match backend schema (D1=chimney, D4=rainwater, E1=loft insulation, …).",
        " * Codes match official RICS L3 matrix (D2=roof coverings, E1=roof structure, …).",
    )

    path.write_text(text, encoding="utf-8")
    print(f"Patched {path}")


if __name__ == "__main__":
    main()
