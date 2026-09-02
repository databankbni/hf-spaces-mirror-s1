#!/usr/bin/env python3
"""
annotate.py — fill the four metadata fields (topic, subtopic, user_type,
insurance_type) on data/chunks.jsonl.

DETERMINISTIC + AUDITABLE by design. Each field is assigned by a documented
DEFAULT rule (keyed on source_id, or keyword rules on the section heading),
then a small, EXPLICIT override table corrects the individual chunks whose
content diverges from the default. This mirrors the project's ethos: auditable
per-item selection, never "a model guessed."

PROVENANCE NOTE: the taxonomy VOCABULARY and the override tables below were
RECONSTRUCTED from the corpus + the reviewer's five decisions, because the
originally-reviewed proposal was produced in a prior session and is not on disk.
Counts here therefore need not match the proposal's stated "19 user_type
overrides / 3-4 topic overrides / 40 details" — those are the numbers to verify,
not assume. See knowledge/sessions for the reconstruction record.

The five reviewer decisions, encoded:
  1. Beamtin  -> add user_type `civil-servant` (distinct legal regime).
  2. Schuelerin -> COLLAPSE into `student` (pupils fold into students).
  3. Non-statutory -> add insurance_type `non-statutory` for the shared
     privat/familienversichert/uninsured Bundesamt route; KEEP `private` and
     `none` in the vocabulary for future precision even if thin.
  4. Apply the section-level topic overrides (incl. tk_maternity_pay's
     Mutterschutzfrist chunk -> maternity-protection).
  5. Split `special-circumstances` out of the `details` subtopic catch-all.
"""
import json, sys, unicodedata
from pathlib import Path

CHUNKS = Path(__file__).resolve().parent.parent / "data" / "chunks.jsonl"

# ---------------------------------------------------------------------------
# VOCABULARIES (the "taxonomy as proposed", reconstructed)
# ---------------------------------------------------------------------------
TOPIC_VOCAB = [
    "maternity-protection", "maternity-benefits", "parental-benefits",
    "parental-leave", "child-benefits", "prenatal-care", "birth-preparation",
    "postnatal-care", "birth-registration", "family-benefits-overview",
]
SUBTOPIC_VOCAB = [
    "definition", "eligibility", "amount", "duration", "application",
    "protections", "special-circumstances", "care-procedure", "logistics",
    "details",
]
# care/prep/registration topics have a different natural subtopic axis than the
# benefit topics. `care-procedure` and `logistics` are GLOBAL vocab values, but
# their keyword rules fire only within CARE_TOPICS — a topic-gated ROUTING
# signal, not a per-topic vocabulary. Gating prevents cross-topic keyword leakage
# (e.g. "weitere Angebote" appears in both Frühe-Hilfen care content and the
# family-benefits OVERVIEW page; only the former should become care-procedure).
CARE_TOPICS = {"prenatal-care", "postnatal-care", "birth-preparation", "birth-registration"}
USER_TYPE_VOCAB = ["any", "employee", "civil-servant", "student",
                   "self-employed", "unemployed"]
INSURANCE_VOCAB = ["any", "statutory", "non-statutory", "private", "none"]

# ---------------------------------------------------------------------------
# TOPIC — default by source, then explicit per-(source,slug-prefix) overrides
# ---------------------------------------------------------------------------
TOPIC_DEFAULT = {
    "fam_anmeldung_standesamt": "birth-registration",
    "fam_checkliste_nach_geburt": "birth-registration",
    "fam_vaterschaftsanerkennung": "birth-registration",
    "fam_elterngeld": "parental-benefits",
    "fam_elterngeld_antrag": "parental-benefits",
    "fam_elterngeld_faq": "parental-benefits",
    "fam_elternzeit": "parental-leave",
    "fam_kindergeld": "child-benefits",
    "fam_leistungen_ueberblick": "family-benefits-overview",
    "fam_staatliche_leistungen": "family-benefits-overview",
    "fam_mutterschaftsleistungen": "maternity-benefits",
    "fam_mutterschutz": "maternity-protection",
    "gesund_fruehe_hilfen_de": "postnatal-care",
    "gesund_unterstuetzung_de": "postnatal-care",
    "gesund_wochenbett_de": "postnatal-care",
    "gesund_vorsorge_de": "prenatal-care",
    "gesund_vorsorge_en": "prenatal-care",
    "gesund_geburtsvorbereitung_en": "birth-preparation",
    "tk_find_midwife": "birth-preparation",
    "tk_maternity_benefits": "maternity-benefits",
    "tk_maternity_pay": "maternity-benefits",
    "tk_maternity_pay_apply": "maternity-benefits",
}
# (source_id, slug-prefix) -> topic.  slug-prefixes are unique per section.
TOPIC_OVERRIDE = {
    # Decision 4, reviewer-named anchor: the only EN explanation of Mutterschutz,
    # sitting in a benefits-titled page. Must be findable by a protection query.
    ("tk_maternity_pay", "what-is-the-mutterschutzfrist"): "maternity-protection",
    # Benefit/income content living inside the protection page.
    ("fam_mutterschutz", "welche-leistungen-bekomme-ich-wenn-meine-befristete-stelle"): "maternity-benefits",
    # TK "Pregnancy benefits" page: two chunks are midwifery CARE, not income.
    ("tk_maternity_benefits", "on-call-midwifery-service"): "birth-preparation",
    ("tk_maternity_benefits", "postnatal-care"): "postnatal-care",
}

# ---------------------------------------------------------------------------
# USER_TYPE — default by source, then explicit persona overrides
# ---------------------------------------------------------------------------
# Persona SCOPE of the assistant is "employed, publicly insured" (decision 2):
# employment-linked sources default to `employee`; everything else to `any`
# (applies regardless of employment status -> no persona filter).
USER_TYPE_DEFAULT_EMPLOYEE = {
    "fam_mutterschutz", "fam_mutterschaftsleistungen", "fam_elternzeit",
    "tk_maternity_pay", "tk_maternity_pay_apply",
}
# (source_id, slug-prefix) -> user_type. Multi-chunk sections share a slug, so
# one entry can cover several chunks (noted in the count report).
USER_TYPE_OVERRIDE = {
    # civil-servant (decision 1)
    ("fam_mutterschutz", "welche-regelungen-fuer-den-mutterschutz-gelten-fuer-beamtinn"): "civil-servant",
    # student  (Studentin + Schuelerin[collapsed, decision 2] + Auszubildende)
    ("fam_mutterschutz", "gibt-es-mutterschutz-fuer-studentinnen"): "student",
    ("fam_mutterschutz", "gibt-es-mutterschutz-fuer-schuelerinnen"): "student",
    ("fam_mutterschutz", "gibt-es-mutterschutz-in-der-ausbildung"): "student",
    ("fam_mutterschaftsleistungen", "bekomme-ich-als-geringfuegig-beschaeftigte-studentin"): "student",
    ("fam_mutterschaftsleistungen", "welche-leistungen-kann-ich-als-schuelerin-auszubildende"): "student",
    # self-employed  (5-chunk "wenn ich selbststaendig bin" section)
    ("fam_mutterschaftsleistungen", "welche-mutterschaftsleistungen-kann-ich-bekommen-wenn-ich-se"): "self-employed",
    # unemployed / benefit-recipient
    ("fam_mutterschaftsleistungen", "kann-ich-mutterschaftsgeld-bekommen-wenn-ich-arbeitslosengel"): "unemployed",
    ("fam_mutterschaftsleistungen", "kann-ich-mutterschaftsgeld-bekommen-wenn-ich-buergergeld"): "unemployed",
    ("fam_mutterschaftsleistungen", "bekomme-ich-mutterschaftsgeld-wenn-ich-arbeitslos-und-nicht"): "unemployed",
}

# ---------------------------------------------------------------------------
# INSURANCE_TYPE — default `any`, then explicit overrides (decision 3)
# ---------------------------------------------------------------------------
INSURANCE_OVERRIDE = {
    # statutory (gesetzliche Krankenkasse route)
    ("fam_mutterschaftsleistungen", "wie-kann-ich-mutterschaftsgeld-der-gesetzlichen-krankenkasse"): "statutory",
    ("fam_mutterschaftsleistungen", "wie-hoch-ist-das-mutterschaftsgeld-der-gesetzlichen-krankenk"): "statutory",
    ("fam_mutterschaftsleistungen", "wie-lange-kann-ich-das-mutterschaftsgeld-der-gesetzlichen-kr"): "statutory",
    ("fam_mutterschaftsleistungen", "wie-kann-ich-das-mutterschaftsgeld-der-gesetzlichen-krankenk"): "statutory",
    ("fam_mutterschaftsleistungen", "bin-ich-in-der-krankenversicherung-weiterhin-versichert"): "statutory",
    # non-statutory (decision 3): privat + familienversichert + uninsured share
    # ONE administrative route (Bundesamt fuer Soziale Sicherung). Collapsing
    # into `private` would silently drop family-insured women.
    ("fam_mutterschaftsleistungen", "wo-kann-ich-mutterschaftsgeld-beantragen-wenn-ich-nicht-gese"): "non-statutory",
    ("fam_mutterschaftsleistungen", "kann-ich-mutterschaftsgeld-des-bundesamtes-fuer-soziale-sich"): "non-statutory",
    ("fam_mutterschaftsleistungen", "wie-hoch-ist-das-mutterschaftsgeld-des-bundesamtes-fuer-sozi"): "non-statutory",
    ("fam_mutterschaftsleistungen", "wie-kann-ich-das-mutterschaftsgeld-des-bundesamtes-fuer-sozi"): "non-statutory",
    # private (privately-insured EMPLOYEE); kept in vocab per decision 3
    ("fam_mutterschaftsleistungen", "welche-leistungen-kann-ich-bekommen-wenn-ich-in-einem-bescha"): "private",
    # none (uninsured); kept in vocab per decision 3
    ("fam_mutterschaftsleistungen", "bekomme-ich-mutterschaftsgeld-wenn-ich-arbeitslos-und-nicht"): "none",
}

# ---------------------------------------------------------------------------
# SUBTOPIC — keyword rules on the folded section heading, ordered by priority.
# special-circumstances is checked FIRST (decision 5): the "standard rule does
# not apply" cases are exactly where precision matters most.
# ---------------------------------------------------------------------------
def fold(s: str) -> str:
    s = s.lower().replace("ä", "a").replace("ö", "o").replace("ü", "u").replace("ß", "ss")
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))

SPECIAL = ["zwilling", "mehrling", "totgeburt", "fehlgeburt", "fehl- und tot",
           "behinderung", "fruehfoerder", "fruehchen", "fruehgeburt",
           "zu frueh geboren", "befristet", "probezeit", "gekuendigt",
           "wieder schwanger", "freiwillig weitergearbeitet"]
APPLICATION = ["beantrag", "wie kann ich den antrag", "wo kann ich",
               "nachweise", "antrag stellen", "apply", "step by step",
               "step-by-step", "elterngeld-bescheinigung"]
AMOUNT = ["wie hoch", "wie viel", "wieviel", "how much", "berechne", "berechnung",
          "hoehe", "-netto", "netto berechnet", "welches einkommen",
          "auf welchen zeitraum", "geschwisterbonus", "partnerschaftsbonus"]
DURATION = ["wie lange", "how long", "wie lange besteht", "dauer der",
            "wann finden", "wann und wie muss"]
ELIGIBILITY = ["kann ich elterngeld bekommen", "kann ich mutterschaftsgeld bekommen",
               "bekomme ich mutterschaftsgeld", "welche frauen werden geschuetzt",
               "gibt es mutterschutz", "kann ich elterngeld und",
               "welche mutterschaftsleistungen kann ich bekommen",
               "welche leistungen kann ich", "wer ", "voraussetzung", "anspruch",
               "kann ich auch dann mutterschaftsgeld", "gibt es besondere leistungen",
               "stehen mir waehrend"]
PROTECTIONS = ["beschaeftigungsverbot", "kuendigungsschutz", "freistell",
               "urlaubsanspruch", "auf meine rente", "arbeitgeber ueber meine",
               "bewerbungsgespraech", "muss mein arbeitgeber", "wie lange muss mich mein arbeitgeber"]
DEFINITION = ["was ist ", "was sind ", "what is ", "what are ", "unterschied zwischen",
              "was macht eine", "was ist das"]
# --- care-topic-only axes (decision: option (a)) ---
# logistics = where to go / who to contact / what to bring / deadlines
LOGISTICS = ["wo teile ich", "geburtsurkunde", "anmeldung ihres kindes", "standesamt",
             "how do i find a midwife", "wo finde ich eine hebamme",
             "wo finde ich beratung", "where will i have the baby",
             "who will be with me", "hospital bag", "needs to be packed",
             "needs to be sorted", "was muss nach der geburt erledigt",
             "wann kann ich eine vaterschaft", "checklisten", "quick access"]
# care-procedure = what an appointment / class / service involves (fallback for
# care topics, so no exhaustive keyword list needed — it catches the remainder)
def subtopic_for(heading: str, is_root: bool, topic: str) -> str:
    h = fold(heading)
    if any(k in h for k in SPECIAL):        return "special-circumstances"
    if any(k in h for k in APPLICATION):    return "application"
    if any(k in h for k in AMOUNT):         return "amount"
    if any(k in h for k in DURATION):       return "duration"
    if any(k in h for k in PROTECTIONS):    return "protections"
    if any(k in h for k in ELIGIBILITY):    return "eligibility"
    if any(k in h for k in DEFINITION) or is_root: return "definition"
    if topic in CARE_TOPICS:
        if any(k in h for k in LOGISTICS):  return "logistics"
        return "care-procedure"
    return "details"

# ---------------------------------------------------------------------------
def match_override(table, source_id, slug):
    for (sid, prefix), val in table.items():
        if sid == source_id and slug.startswith(prefix):
            return val
    return None

def annotate(rows):
    audit = {"topic": [], "user_type": [], "insurance": []}
    for r in rows:
        sid, slug = r["source_id"], r["section_slug"]
        heading = r["heading_path"][-1] if r["heading_path"] else ""
        is_root = (len(r["heading_path"]) <= 2)  # [authority, page-title]

        # topic
        topic = TOPIC_DEFAULT[sid]
        ov = match_override(TOPIC_OVERRIDE, sid, slug)
        if ov:
            audit["topic"].append((sid, slug, topic, ov))
            topic = ov
        r["topic"] = topic

        # user_type
        ut = "employee" if sid in USER_TYPE_DEFAULT_EMPLOYEE else "any"
        ov = match_override(USER_TYPE_OVERRIDE, sid, slug)
        if ov:
            audit["user_type"].append((sid, slug, ut, ov))
            ut = ov
        r["user_type"] = ut

        # insurance_type
        ins = "any"
        ov = match_override(INSURANCE_OVERRIDE, sid, slug)
        if ov:
            audit["insurance"].append((sid, slug, ins, ov))
            ins = ov
        r["insurance_type"] = ins

        # subtopic (needs topic for care-topic gating)
        r["subtopic"] = subtopic_for(heading, is_root, topic)
    return audit

def main():
    rows = [json.loads(l) for l in CHUNKS.open(encoding="utf-8")]
    audit = annotate(rows)
    if "--write" in sys.argv:
        with CHUNKS.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"WROTE {len(rows)} chunks -> {CHUNKS}")

    import collections
    N = len(rows)
    print(f"\n{'='*70}\nFILLED COUNTS PER VALUE  (N={N} chunks)\n{'='*70}")
    for field, vocab in [("topic", TOPIC_VOCAB), ("subtopic", SUBTOPIC_VOCAB),
                         ("user_type", USER_TYPE_VOCAB), ("insurance_type", INSURANCE_VOCAB)]:
        cnt = collections.Counter(r[field] for r in rows)
        print(f"\n-- {field} --")
        for v in sorted(cnt, key=lambda k: -cnt[k]):
            pct = 100*cnt[v]/N
            flag = "  <<< >40%" if pct > 40 else ("  <<< <3" if cnt[v] < 3 else "")
            invocab = "" if v in vocab else "  (NOT IN VOCAB!)"
            print(f"   {cnt[v]:>3} ({pct:4.1f}%)  {v}{flag}{invocab}")
        unused = [v for v in vocab if v not in cnt]
        if unused: print(f"   [unused vocab values: {unused}]")

    print(f"\n{'='*70}\nFLAGS\n{'='*70}")
    for field in ["topic", "subtopic", "user_type", "insurance_type"]:
        cnt = collections.Counter(r[field] for r in rows)
        for v in cnt:
            if cnt[v] < 3:
                print(f"   <3 : {field}={v}  ({cnt[v]})")
    for field in ["topic", "subtopic", "user_type", "insurance_type"]:
        cnt = collections.Counter(r[field] for r in rows)
        for v in cnt:
            if 100*cnt[v]/N > 40:
                print(f"   >40%: {field}={v}  ({cnt[v]}, {100*cnt[v]/N:.1f}%)")

    print(f"\n{'='*70}\nUSER_TYPE OVERRIDES (chunk-level; default shown -> override)\n{'='*70}")
    seen=set()
    for sid, slug, default, ov in audit["user_type"]:
        if (sid,slug) in seen: continue
        seen.add((sid,slug))
        k = sum(1 for r in rows if r["source_id"]==sid and r["section_slug"]==slug)
        print(f"   [{k}x] {ov:<13} (was {default})  {sid} :: {slug}")
    print(f"   --> {len(seen)} sections, {len(audit['user_type'])} chunks overridden")

    print(f"\n{'='*70}\nTOPIC OVERRIDES\n{'='*70}")
    for sid, slug, default, ov in audit["topic"]:
        print(f"   {ov:<20} (was {default})  {sid} :: {slug}")

    print(f"\n{'='*70}\nINSURANCE_TYPE OVERRIDES\n{'='*70}")
    for sid, slug, default, ov in audit["insurance"]:
        print(f"   {ov:<14} (was {default})  {sid} :: {slug}")

    print(f"\n{'='*70}\nDETAILS-SUBTOPIC AUDIT (decision 5 asked: is it <=~25 after split?)\n{'='*70}")
    det = [r for r in rows if r["subtopic"]=="details"]
    print(f"   details count = {len(det)}")
    for r in det:
        print(f"     {r['source_id']} :: {r['heading_path'][-1][:70]}")

if __name__ == "__main__":
    main()
