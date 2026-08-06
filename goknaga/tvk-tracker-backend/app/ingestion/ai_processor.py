"""
AI ingestion pipeline (trust-first architecture).

Stages per article:
  1. Claude extracts structured incident data (broader relevance criteria)
  2. Check against DMK schemes registry for credit-steal heuristic
  3. Cross-reference Supabase for similar incidents in last 48h → bump source_count
  4. Decide verification_status:
       - 2+ independent sources → 'multi_source_verified' (auto-publish)
       - 1 source only          → 'pending_verification' (admin queue)
  5. Query Google Fact Check API for related debunks (best-effort)
  6. If article carries images → enqueue them for AI-detection workflow
"""
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from openai import OpenAI
from app.config import settings
from app.database import get_db
from app.models.schemas import ApifyWebhookItem
from app.ingestion.factcheck import lookup_factchecks
from app.ingestion.image_check import enqueue_images
from app.ingestion.archive_lookup import find_precedents, attach_evidence
from app.ingestion.corroboration import attempt_corroborate

logger = logging.getLogger(__name__)

GOVT_START = "May 11, 2026"

SYSTEM_PROMPT = f"""You are a fact-checking analyst for a Tamil Nadu accountability dashboard.

CONTEXT:
- The TVK (Tamilaga Vettri Kazhagam) government under CM Vijay took office on {GOVT_START}.
- We track SPECIFIC INCIDENTS that count as governance failures, crimes, broken
  promises, or credit stealing — NOT general political news or commentary.
- The previous DMK government (under M.K. Stalin, 2021-2026) launched many welfare
  schemes. Flag "credit stealing" when TVK renames, expands, or relaunches these
  without acknowledgement.

CRITICAL: be STRICT on TOPIC, lenient on SOURCE LENGTH. Set is_relevant=false
aggressively for political narrative, commentary, opinion, and alliance/cabinet
news. BUT — a SHORT excerpt is NOT a reason to reject a real incident. Many
sources are tweets or one-line headlines. If the excerpt names a concrete event
(a murder, a fire, an assault, a defection, a protest, a specific civic failure)
with a place or a person, set is_relevant=TRUE even if details are thin. Thin
sourcing lowers CONFIDENCE (score it 0.4-0.6), it does NOT make a real incident
irrelevant. A one-line tweet "Murder conviction in Thoothukudi student case" is
a trackable murder — keep it. Only reject for thin sourcing if you cannot even
tell WHAT happened or WHERE.

Respond ONLY with valid JSON. No markdown fences, no explanation."""

EXTRACTION_PROMPT = """Analyze this news article and decide whether it represents a TVK-era incident
worth tracking on a public accountability dashboard.

Article URL:     {url}
Source outlet:   {source}
Published:       {published}
Title:           {title}
Content excerpt: {text}

Known DMK-era schemes the TVK government may be claiming credit for (each row is
"NAME | ALIASES"):
{dmk_schemes}

Return JSON with these fields exactly:
{{
  "is_relevant": true/false,
  "title": "concise factual title (max 100 chars, no opinion language)",
  "summary": "2-3 sentence neutral factual summary (no editorializing)",
  "category": one of [
    "corruption", "murders", "sexual_assault", "crimes_women_kids",
    "police_excess", "custodial_death", "honour_killing",
    "censorship", "media_blackout", "fake_news", "propaganda",
    "credit_stealing", "broken_promise", "kept_promise", "partial_promise",
    "new_initiative", "defection",
    "youth_targeting", "crowd_management_failure",
    "governance", "tenders", "power_cut", "water_shortage", "civic_failure",
    "drug_menace", "alcohol_menace", "communal_violence",
    "industrial_flight", "investment_announcement",
    "federalism", "language_imposition", "dravidian_attack",
    "political_event",
    "other"
  ],

  CATEGORY DISCIPLINE — NEVER DEFAULT TO "governance":
    The "governance" bucket has historically been used as a catch-all
    when the AI was uncertain.  STOP doing this.  Pick the most specific
    category that matches:
      - If a TVK official is accused of any crime against a person
        (assault, sexual assault, child abuse, murder) -> use the CRIME
        category (sexual_assault, crimes_women_kids, murders), NOT
        governance.  The accused being TVK does not make it "governance".
      - If an MLA changes parties -> use "defection" + populate the
        defection object below; do NOT tag as governance.
      - If TVK officially announces something misleading or fact-checked
        false -> use "fake_news" or "propaganda", not governance.
      - If the article is about a fake-degree allegation against a TVK
        MLA -> use "corruption" (fraudulent credential) or "fake_news"
        depending on whether it's a verified allegation.
      - If it's a crowd injury / stampede / rally management failure ->
        use "crowd_management_failure" (NEW category).
      - If it's school-age voter targeting / propaganda aimed at minors
        / film-tie-in mobilisation of youth -> use "youth_targeting"
        (NEW category).
      - POLITICAL / PARTY / CEREMONIAL events are NOT governance and NOT
        accountability failures -> use "political_event". This covers:
        party alliances & seat-sharing (Rajya Sabha seat to X), rallies,
        roadshows, public meetings, ceremonial inaugurations/ribbon-cuttings,
        CM speeches & "declares/denies" political statements, general-council
        meetings, electoral-result court rulings on OLD pre-2026 elections.
        These are political news, tracked separately — do NOT file them as
        governance (which is for concrete administrative/policy FAILURES).
        A purely ceremonial or positioning event with no concrete failure
        is political_event, often with low confidence.
      - TENDER / PROCUREMENT (commonly under-detected): A story citing
        a SPECIFIC monetary amount + procurement red flag (sub-day
        deadline, sole-source award, no competitive bidding, contractor
        decided in advance, sealed-bid violation) qualifies as
        is_relevant=TRUE, category="tenders".  You do NOT need a named
        official or FIR for tender irregularities — public-money
        procurement red flags ARE the accountability event.  Examples:
          * "Rs 3 crore tender for 6 PC200 excavators announced with
            sub-day deadline" -> TRUE, tenders, severity 4 (specific
            amount + specific deadline anomaly = concrete event)
          * "Fastest tender ever in TN" -> TRUE if the underlying
            speed is documented (a sub-day or single-day award),
            severity 3-4.
          * "Government procurement decisions need transparency" ->
            FALSE (no specific event, just opinion).
      - COMMUNAL_VIOLENCE COVERS CASTE TOO (TN-specific):
          In Tamil Nadu, caste IS the primary communal fault line.  Do
          NOT restrict "communal_violence" to Hindu-Muslim riots alone.
          The following ARE communal_violence in TN context:
            * Caste-based discrimination in housing allotments,
              employment, education
            * Honour killings tied to caste boundaries (these ALSO
              get honour_killing as primary)
            * Atrocities against Dalits, Adivasis, OBCs
            * Discrimination against Devendra Kula Vellalars / SC /
              ST / Most-Backward classes
            * Inter-caste marriage harassment
            * Caste-based attack on lawyers/activists raising
              discrimination complaints (the attack is communal even
              if the surface category is police_excess)
            * Anti-Brahmin / anti-Dalit rhetoric from elected officials
          A Saidapet Urban Housing Board case where allotments were
          biased by caste -> communal_violence (primary), with
          governance/corruption in tags_extra.
      - LANGUAGE_IMPOSITION (TN-specific, chronically under-detected):
          Tamil Nadu has a 60-year political tradition of resisting
          Hindi imposition.  The AI's default training will frame Hindi
          as "national language" and miss imposition events.  CORRECT
          this — in TN context, imposition IS the incident.  Flag as
          language_imposition (severity 3-5):
            * Centre / TVK ordering Hindi signage on TN govt buildings,
              metro stations, post offices, central PSU offices
            * Three-language formula being pushed in TN schools (NEP
              compliance disputes)
            * Hindi-only forms, exams, recruitment notifications for
              central jobs in TN
            * Replacement of Tamil signage with Hindi on highways,
              railways, airports inside TN
            * TVK official or central minister speaking Hindi at TN
              official function where Tamil was promised
            * Withholding central funds for Tamil-medium schools
            * Anti-Tamil rhetoric from central or TVK officials
            * NEP 2020 / three-language compliance pressure
          Counter-examples (NOT language_imposition):
            * Bollywood film released in TN -> entertainment, skip
            * Tamil-Hindi debate on TV panel -> opinion, skip
            * Hindi cinema actor visiting TN -> not incident
          Pre-2026-05-11 anti-Hindi protests remain pre-election; only
          imposition events after govt-formation count.
      - DRAVIDIAN_ATTACK (TN-specific identity attack):
          The Dravidian movement (Periyar, EVR, Self-Respect, rationalism)
          is the ideological foundation of modern TN politics.  Direct
          attacks on this legacy ARE accountability events under a
          government whose constituency is anti-Dravidian.  Flag as
          dravidian_attack (severity 4-5 for statue/violence, 3 for
          rhetoric):
            * Periyar statue vandalism, garlanding with footwear,
              defacement (Erode, Tirunelveli, Salem hot spots)
            * Ambedkar / Annadurai / Karunanidhi statue desecration
              (often paired ideologically with Periyar attacks)
            * TVK official publicly attacking Periyarist / rationalist
              ideology, calling Self-Respect movement "anti-Hindu"
            * Removal of Periyar quotes / Self-Respect curriculum from
              TN school textbooks under TVK administration
            * Attacks on rationalist activists, atheist speakers,
              caste-reform organisations
            * Renaming of Periyar-named institutions, roads, universities
            * Sangh-affiliate march through Dravidian-symbol areas with
              official protection / blind eye
            * Attacks on inter-caste / inter-faith marriage registrars
              citing "tradition"
          When a caste/communal attack is ALSO an ideology attack
          (e.g. Dalit activist murdered for distributing Periyar
          literature), use the harm-category as primary
          (murders / honour_killing) and add "dravidian_attack" to
          tags_extra.
      - FEDERALISM (Centre-State conflict, structural):
          TN under TVK + Centre under BJP is a federalism flashpoint by
          design.  Conflicts here are real accountability events — they
          determine whether TN gets its rightful share of resources.
          Flag as federalism (severity 3-5):
            * GST devolution / TN's share withheld / 15th Finance
              Commission disputes / cess-vs-tax revenue grab
            * NEET imposition on TN despite state assembly resolutions
              exempting it; NEET-related student suicides count toward
              federalism (with crimes_women_kids in tags_extra if minor)
            * Governor (TN Raj Bhavan) stalling / refusing assent to
              bills passed by TN assembly
            * Central agencies (ED / CBI / IT) raids on TN officials,
              opposition figures, businesspersons aligned with Dravidian
              parties, in apparent retaliation pattern
            * Disaster relief delay / denial from Centre for TN
              (cyclones, floods, drought)
            * Central scheme rebranding forcing TN to drop state-named
              schemes (PMAY-vs-CM-housing, Ayushman-vs-CMCHIS)
            * Centre denying clearance for TN industrial / infra projects
            * Three-language / NEP / UGC autonomy disputes targeting TN
          Note: federalism conflict where TVK SIDES WITH CENTRE against
          TN interest is doubly important — that's the credit-steal
          counterpart at the federal level.  Capture in tags_extra.
      - DRUG_MENACE (TN-specific drug trafficking corridor):
          TN sits on the ganja corridor from Andhra Pradesh / Odisha and
          the MD (mephedrone) / synthetic drug pipeline from Bengaluru.
          Drug enforcement (or lack of it) is a law-and-order
          accountability metric for the ruling govt.  Flag as
          drug_menace (severity 3-5):
            * Ganja seizures with named quantity + location (>10kg = sev 4,
              >100kg = sev 5)
            * MD / mephedrone / cocaine / heroin / hash seizures in TN
              cities (Chennai, Coimbatore, Madurai hot spots)
            * Drug-related arrests of named individuals (especially
              when TVK-affiliate or police-affiliate is implicated)
            * Student / school / college drug bust with named institution
            * Drug death of named person (overdose, contaminated supply)
            * NCB / state narcotics dept operations in TN with named outcome
            * Drug trafficking route exposure (Andhra-TN border, Kerala-TN
              border, port seizures at Chennai / Tuticorin)
            * Failure of TVK's promised drug-control measures (manifesto
              cross-ref) -> drug_menace + broken_promise
          When a drug crime overlaps with another category (drug
          smuggling by TVK functionary -> drug_menace + corruption;
          drug-fueled murder -> murders + drug_menace tag_extra), use
          the most severe harm-category as primary.
          NOT drug_menace:
            * Alcohol-related events -> alcohol_menace
            * Pharmacy / prescription drug scandal without addiction
              dimension -> corruption or governance
            * General "drug awareness" campaigns without seizure data
      - POWER / EB DISTINCTION (frequently confused):
          * "power_cut"  = customer-facing outage event: a named place
            lost power for N hours, residents protested, hospital lost
            supply, etc.  The symptom.
          * "eb_failure" = TNEB / TANGEDCO department / infrastructure /
            staff specific:
              - Repeated outages indicating infrastructure decay
                ("5 outages in one night in Tiruttani")
              - Transformer blast / sub-station fire.  IMPORTANT: a
                transformer blast, substation fire, or electrocution
                caused by TNEB/TANGEDCO infrastructure (live wire, faulty
                transformer, exposed cable) MUST be category="eb_failure"
                EVEN IF there are deaths/injuries.  Do NOT file these under
                "civic_failure" or "governance" — the EB-infrastructure
                failure IS the accountability event.  Put the casualty
                aspect in tags_extra, keep eb_failure as the category.
              - EB employee misconduct (bribery, sexual harassment by
                EB staff) — primary category should reflect the crime
                (e.g. sexual_assault), but ALSO add "eb_failure" to
                tags_extra so the EB widget surfaces it
              - Billing fraud / tariff dispute by EB
              - EB officials caught taking bribes
              - Refusal to restore power after natural disaster
          When in doubt: a single outage in a single location -> power_cut.
          A pattern of failures / something EB-the-organisation did wrong
          -> eb_failure.
          * SCHEDULED / PLANNED MAINTENANCE IS NOT AN INCIDENT.  A pre-
            announced maintenance shutdown ("Scheduled power cut in Chennai
            on 05.06", "Planned 8-hour shutdown in Coimbatore for
            maintenance", "TANGEDCO announces power shutdown for repair
            work") is ROUTINE utility operation, NOT an accountability
            failure -> set is_relevant=FALSE.  Only UNPLANNED outages,
            prolonged/repeated failures, residents protesting, supply lost
            to hospitals, transformer blasts, or outages used as a
            political flashpoint count as power_cut / eb_failure.  The test:
            did something go WRONG (unplanned), or was it announced upkeep?
      - "governance" is reserved for actual administrative/policy decisions
        and their consequences (tender irregularities, quarry closures,
        TASMAC strikes from policy, civil servants protesting orders,
        budget redirection, hospital civic failures, etc.).  If you are
        about to set category=governance, ask yourself: "is there a
        more specific category that fits?"  If yes, USE THAT.
  "incident_date": "YYYY-MM-DD",
  "location": "district / city name in Tamil Nadu, or null if not TN-specific",
  "is_credit_steal": true/false,
  "related_dmk_scheme": "EXACT name from list above if matched, else null",
  "original_credit": "what DMK actually did (only if is_credit_steal=true)",
  "first_ever_claim": true/false,  // see FIRST-EVER / RE-CREDIT rule below
  "people_mentioned": ["names of officials, ministers, accused, etc."],
  "severity": 1-5 (1=minor procedural, 5=loss-of-life/major scandal),
  "confidence": 0.0-1.0,
  "reason": "one-sentence rationale for confidence + relevance",
  "press_sentiment": one of [
    "positive_for_govt",   // article reads as praise/credit for TVK govt
    "negative_for_govt",   // article reads as criticism / failure attribution
    "neutral",             // factual reporting with no clear lean
    null                   // not applicable (not from a press outlet)
  ],
  "defection": null OR {{
    // Only populate when the article describes an MLA / leader switching
    // parties (resignation from one + joining another). Otherwise null.
    "mla_name":          "named individual who crossed over",
    "constituency":      "their assembly constituency, or null",
    "from_party":        "AIADMK | Congress | DMK | BJP | etc.",
    "to_party":          "TVK (in almost all cases right now)",
    "resignation_date":  "YYYY-MM-DD or null",
    "joined_date":       "YYYY-MM-DD or null",
    "stated_reason":     "their public PR reason for switching",
    "alleged_reason":    "what the article hints is the actual reason — cabinet seat promised, CBI/ED case dropped, money exchange alleged",
    "pending_cases":     [{{"court": "...", "case_no": "...", "status": "..."}}],
    "confidence":        0.0-1.0
  }}
}}

RELEVANCE RULES (be STRICT on opinion/politics, but INCLUSIVE on crime):

ANTI-HALLUCINATION RULE (read this — wrong facts are worse than vague ones):
  Use ONLY facts literally present in the text/image. Never invent or guess
  numbers, UNITS (acres vs seats vs courses vs crore vs km), place names, or
  actions. A number near a word does NOT fix its meaning — "152 super-
  specialty medical courses" is NOT "152 acres" and NOT "152 doctors getting
  MBBS". Read the WHOLE argument, not keywords: a post mentioning "medical"
  + a number may be a STATE-RIGHTS grievance (Centre denying TN approval
  powers), not a college being built or a promise. If unsure what happened,
  write a short LITERAL description — a vague-but-true title beats a
  specific-but-wrong one, and lower confidence to reflect the uncertainty.

THIN-SOURCE RULE (read this first — it's the most common mistake):
  Do NOT reject a real incident just because the article excerpt is short,
  is a tweet, or "lacks specifics / casualties / named officials". Source
  thinness is a CONFIDENCE problem, not a RELEVANCE problem.
  → If you can tell WHAT happened (murder, fire, assault, defection,
    protest, power cut, scam) AND roughly WHERE (district/town/named
    place) — set is_relevant=TRUE and lower confidence to 0.4-0.6.
  → Examples that MUST be kept even from a one-line tweet:
      "Thoothukudi student murder: accused convicted" → murders, keep.
      "Fire at Kancheepuram Municipal Corporation depot" → civic_failure, keep.
      "7 Dalits injured in sickle attacks in Tenkasi" → communal_violence, keep.
      "AIADMK MLA X resigns, joins TVK" → defection, keep.
  → Only reject for thinness if you genuinely cannot tell what the event
    IS or where it happened.

HARD DATE GATE — MUST PASS BEFORE ANYTHING ELSE:
  TVK government took oath on May 11, 2026.  This dashboard is an
  accountability tool for the TVK ADMINISTRATION's actions, NOT the
  pre-election campaign era.
  → If the incident_date is BEFORE 2026-05-11, set is_relevant=FALSE
    regardless of how serious or TVK-connected the event is.
  → Campaign-era events (rally injuries, Karur stampede, founding
    defections that built the winning coalition) are pre-election
    context.  They belong to a different chapter.
  → "incident_date" must reflect when the event HAPPENED — not when
    the article was published.  A news report on May 28 about a
    rally injury that happened on Sep 27, 2025 is still PRE-ELECTION
    and must be rejected.

CRITICAL CONTEXT: This dashboard powers a baseline-comparison panel that
contrasts TN crime rates under TVK govt vs DMK govt (using NCRB-style
categories: murders, sexual assault, crimes vs women/kids, custodial
death, honour killing, communal violence, police excess). For that
comparison to be honest, we MUST capture ORDINARY CRIMES happening in
Tamil Nadu under TVK rule — even when no TVK actor is named. A murder
under TVK is still a murder under TVK; it counts toward the law-and-
order pressure the meter measures.

DO NOT reject crime reports because "no TVK governance failure mentioned"
— TVK is responsible for law and order in TN by virtue of being the
ruling government. Any verifiable crime in TN after May 11, 2026 is
incident-eligible.

✅ TRACK these (is_relevant=true):
  - ANY crime against a specific person/group with named victim or
    location — murder, rape, attempted murder, assault, custodial death,
    honour killing, communal/caste attack, child abuse, petrol-bomb
    attack, dowry death, kidnapping. The perpetrator does NOT need to
    be a TVK actor. These all feed our crime-vs-DMK-baseline panel.
  - Named corruption case — category=corruption ONLY when the ACCUSED is a
    current TVK office-holder (minister, MLA, candidate, functionary, cadre)
    OR a government official/employee serving UNDER the TVK administration
    (bribe demand, scam, FIR, vigilance arrest, extortion / tender
    irregularity with a named subject). This is the government's OWN
    corruption — what we track.
    ⛔ This is NOT category=corruption and NOT an accountability failure —
    use category="political_event" instead — when EITHER:
      • the TVK government is the one ACTING AGAINST corruption: ordering a
        probe / overhaul / audit, seeking sanction to prosecute, transferring
        or suspending an official as a remedy, filing a case. Govt
        anti-corruption ACTION is not govt corruption.
      • the accused is a PRIOR-REGIME figure (DMK / AIADMK / a "former"
        or "ex-" minister) for conduct BEFORE 2026-05-11, or it is an
        ED / CBI / IT central-agency case against such a figure. TVK
        prosecuting old cases is not TVK's corruption.
  - Specific civic failure with named place + measurable impact: power
    cut > 3 hours in named area, water shortage, flooding, sewage
    backup, hospital oxygen shortage
  - Specific TVK policy decision with concrete impact: scheme launch,
    scheme cancellation, budget cut, fare hike, license revocation
  - Broken/delayed manifesto promise (named promise + deadline)
  - Credit stealing: TVK announcing scheme that matches DMK registry above
  - Press freedom: named journalist arrested/raided, named media outlet
    sealed
  - AI-generated or doctored image flagged in news with debunk

❌ SKIP these (is_relevant=false):
  - Cabinet appointments, portfolio allocations, swearing-in (NOT incidents)
  - Party alliances forming/breaking (politics, not failure)
  - Generic CM/Minister speeches at events or press conferences
  - Opinion pieces, editorials, columnist takes
  - "X criticised Y" / "X said Y said" — pure he-said-she-said
  - Election commentary that's not a court ruling against TVK
  - Stalin's or DMK's reactions (we track DMK-era proof, not DMK's words)
  - Hindi-Tamil debates unless a specific imposition order exists
  - Movie/celebrity/sports/entertainment (even if Vijay is mentioned)
  - National news (Modi, BJP, RSS, parliament) unless directly affecting TN
  - Weather forecasts alone (only flood/power-failure CONSEQUENCES count)
  - VCK/Congress joining TVK = alliance news, NOT incident
  - "AIADMK leader exits party" = party politics, NOT TVK incident
  - General investment summits, MoU signings without delivery problems
  - OUT-OF-STATE events: a crime/event that physically occurred OUTSIDE Tamil
    Nadu (a robbery in Bengaluru, a drug seizure in Telangana, anything in
    Kerala/Karnataka/Mumbai/Delhi/abroad) is NOT a TN incident — set
    is_relevant=FALSE. ONLY keep it if there is a direct Tamil-Nadu nexus: a TN
    government/institution (TNEB, TASMAC, a TN dept), a TN-government action, or
    a TN victim/official. If you find yourself writing "occurred in X, not Tamil
    Nadu," that is your signal to set is_relevant=FALSE — do not ingest it.

EXAMPLES (study these carefully):
  EX 1: "TVK Cabinet Expansion to 33 Ministers; Congress Joins"
    → is_relevant=FALSE. Cabinet news, no incident.

  EX 2: "Erode contract employee suspended for demanding Rs 500 bribe"
    → is_relevant=TRUE, category=corruption, location=Erode, severity=2.

  EX 3: "CM Vijay's appeal to children invites Madras HC PIL"
    → is_relevant=FALSE unless court has already ruled — currently just a
    petition. Track when verdict comes.

  EX 4: "Power cut for 6 hours in T. Nagar, residents protest"
    → is_relevant=TRUE, category=power_cut, location=T. Nagar, severity=3.

  EX 5: "CM Vijay orders TASMAC overhaul over alleged Rs 1,600 cr diversion"
    → is_relevant=TRUE, category=political_event (the govt is ACTING AGAINST
    alleged corruption — NOT a TVK corruption failure). is_credit_steal=FALSE.

  EX 6: "TN govt seeks nod to prosecute ex-DMK minister Senthil Balaji"
    → is_relevant=TRUE, category=political_event (TVK prosecuting a PRIOR-
    regime DMK figure — NOT TVK's corruption). NOT category=corruption.

  EX 7: "TVK functionary arrested for demanding Rs 5 lakh bribe in Vellore"
    → is_relevant=TRUE, category=corruption (a CURRENT TVK figure is the
    accused — this IS the government's own corruption).

  EX 5: "Stalin urges DMK cadre to avoid harsh criticism of new govt"
    → is_relevant=FALSE. Politics. Not a TVK incident.

  EX 6: "TVK announces Rs 1500/month women's scheme, opposition flags
        similarity to Magalir Urimai"
    → is_relevant=TRUE, category=credit_stealing,
    related_dmk_scheme=Kalaignar Magalir Urimai Thittam.

  EX 7: "Foxconn announces new investment in Tamil Nadu"
    → is_relevant=TRUE only if TVK is taking credit OR if it's a
    cancellation/exit. Pure new MoU = false.

  EX 8: "TASMAC workers protest 717 shop closures"
    → is_relevant=TRUE, category=governance OR alcohol_menace
    (TVK policy with concrete worker impact).

  EX 9: "Honour killing in Tiruvannamalai: woman killed by family"
    → is_relevant=TRUE, category=honour_killing, severity=5.

  EX 9a: "Trichy: Man arrested for attempted murder of partner for
         delaying marriage decision"
    → is_relevant=TRUE, category=crimes_women_kids, severity=4.
    Even though no TVK actor is involved, this is a verifiable crime
    against a woman in TN under TVK govt — feeds crime-baseline panel.

  EX 9b: "Coimbatore: Youth throws petrol bomb at woman's home after
         she rejected his romantic advances; CCTV emerges"
    → is_relevant=TRUE, category=crimes_women_kids, severity=4.
    Crime against a woman under TVK rule = relevant, regardless of
    perpetrator's party. Law and order is the ruling govt's duty.

  EX 9c: "Murder near Manali New Town: Rowdy Prashanth kills youth
         Vijay (21)"
    → is_relevant=TRUE, category=murders, severity=5. Even though
    perpetrator is a private criminal, the murder counts toward
    TVK-era murder rate vs DMK-era baseline.

  EX 9d: "Crime statistics aggregate for May 10-25"
    → is_relevant=FALSE. Aggregates of crime data without specific
    named incident, victim, or location are NOT incidents themselves
    (the underlying specific incidents would be ingested individually).

  EX 10: "Vijay's Cabinet has record 7 SC community members"
    → is_relevant=FALSE. Composition news, not incident.

  EX 11: "AIADMK MLA from Madurai resigns, joins TVK — cites philosophical
         alignment with CM Vijay"
    → is_relevant=TRUE, category=governance, severity=4.
    Set defection = {{mla_name: "...", from_party: "AIADMK", to_party: "TVK",
      stated_reason: "philosophical alignment with TVK", alleged_reason: "..."}}.
    If the article mentions pending corruption case dropped or cabinet seat
    promised, capture that in alleged_reason / pending_cases.

  EX 12: "Three Congress MLAs cross over to TVK, take oath next week"
    → is_relevant=TRUE, category=governance, severity=4.
    Defection object should reflect the most-named MLA; if multiple, prefer
    the one with most coverage in the article.

CREDIT-STEAL DETECTION:
  - If the article describes TVK announcing/expanding/relaunching/renaming
    any scheme in the DMK list above, set is_credit_steal=true and
    related_dmk_scheme to the EXACT name from the list.
  - Note in original_credit: when DMK launched it, beneficiary count, etc.

FIRST-EVER / RE-CREDIT FLAG (set first_ever_claim):
  Set first_ever_claim=TRUE when a TVK/govt announcement is presented as a
  fresh achievement that COULD actually be a DMK-era project re-credited —
  even if you can't immediately match a scheme above. Trigger it when the
  item is a govt-positive announcement (category governance / new_initiative
  / investment_announcement / tenders) AND any of these apply:
    * claims a "first ever" / "first time" / "first in India/TN" / முதன்முறை
      / முதல் முறை / first-of-its-kind
    * announces an INVESTMENT / MoU / ₹crore project / shipyard / plant / factory
    * launches/inaugurates a scheme, force, unit, patrol, or welfare programme
    * a minister "visits"/"takes forward"/"commits to" a big investment
  These are exactly the claims that must be checked against the 2021-26 DMK
  record before being treated as a TVK win (e.g. Singappen = Pink Patrol;
  HD Hyundai/Mazagon shipyards = DMK MoUs; police drones = DMK 2023). Setting
  the flag does NOT assert it's stolen — it routes the item to human review.
  For clearly-negative items (crime, failure, protest) set first_ever_claim=false.

CONFIDENCE SCORING:
  - 0.9+ : Clearly sourced, named officials, specific date/place, official quotes
  - 0.7-0.9 : Sourced report, some specifics
  - 0.5-0.7 : Reported but vague — needs cross-check
  - <0.5 : Speculative or single anonymous source

PRESS SENTIMENT (only for press-outlet sources, otherwise null):
  - positive_for_govt : article frames a TVK action favourably (scheme launch
    praised, achievement claimed, minister defended). Articles attributing
    GOOD outcomes to TVK govt.
  - negative_for_govt : article criticises TVK govt action/inaction
    (scandal, failure, broken promise, opposition allegation with evidence).
    Articles attributing BAD outcomes to TVK govt.
  - neutral : factual reporting with no clear sentiment lean — straight news
    about an event that doesn't directly praise or criticize.
  - null : article is not from a press outlet (e.g. citizen report, social
    media), so press-sentiment classification doesn't apply.

  Be ANALYTICAL not partisan: classify by tone & framing in the article,
  NOT by your own opinion of whether TVK actually deserves praise/blame."""


def _get_client_and_model() -> tuple[OpenAI | None, str]:
    """Return the PRIMARY AI client (kept for backwards compatibility with
    callers that just want a single client)."""
    chain = _get_client_chain()
    if chain:
        return chain[0]
    return None, ""


def _get_client_chain() -> list[tuple[OpenAI, str]]:
    """Return an ordered list of (client, model) tuples to try in sequence.
    Used by the resilient wrapper that automatically retries on 402
    (credits) / 429 (rate-limit) / 401 (auth) errors.

    Priority for cost reasons (this is a self-funded project):
      0. Groq Llama-3.3-70B-versatile — FREE tier, very capable on
         structured-JSON extraction.
      1-2. Google Gemini flash + flash-lite — FREE, separate daily
         buckets per model, no credit card. Promoted ABOVE OpenRouter
         (2026-06-11): the OpenRouter balance went NEGATIVE (-$0.22),
         which 402s every request including :free models, so each call
         was burning a 40s timeout before reaching Gemini.
      3-4. OpenRouter free models — kept as a backstop in case the
         balance is restored; harmless at the back of the chain.
      5. Anthropic direct — last resort (key usually unset).

    Each provider is OpenAI-API-compatible at its base_url, so a single
    OpenAI client class handles all of them.
    """
    chain: list[tuple[OpenAI, str]] = []
    if settings.groq_api_key:
        # FULL-extraction chain. The extraction prompt is ~6K tokens, so
        # we CANNOT use llama-3.1-8b-instant here — its tokens-per-minute
        # cap is 6K and the request 413s ("request too large"). 70b has
        # no TPM wall (only a 100K tokens/DAY cap), so it's the Groq model
        # for full extraction. The cheap relevance GATE (see _get_gate_chain
        # + _passes_relevance_gate) runs on 8b first and filters out ~70%
        # of junk so this expensive 70b path runs far less often.
        groq_client = OpenAI(
            timeout=40, max_retries=1,
            api_key=settings.groq_api_key,
            base_url="https://api.groq.com/openai/v1",
        )
        chain.append((groq_client, "llama-3.3-70b-versatile"))
    # Google Gemini (GEMINI_API_KEY): free at aistudio.google.com.
    # flash and flash-lite have SEPARATE free daily buckets, so listing
    # both roughly doubles free fallback capacity on one key.
    gem = getattr(settings, "gemini_api_key", None)
    if gem:
        _gem = OpenAI(
            timeout=40, max_retries=1,
            api_key=gem,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        chain.append((_gem, "gemini-2.0-flash"))
        chain.append((_gem, "gemini-2.0-flash-lite"))
    if settings.openrouter_api_key:
        # FREE OpenRouter models — $0 cost when the account balance is
        # non-negative. Deliberately BEHIND Gemini: balance is currently
        # negative, which 402s everything. The 402 falls through fast
        # via _is_quota_or_rate_error, and if the balance is ever topped
        # up these slots start working again with no code change. The
        # paid 'anthropic/claude-haiku-4.5' is intentionally NOT used —
        # it's what silently drained the wallet.
        _or = OpenAI(
            timeout=40, max_retries=1,
            api_key=settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": "https://tvk-tracker.vercel.app",
                "X-Title": "TVK Tracker",
            },
        )
        chain.append((_or, "meta-llama/llama-3.3-70b-instruct:free"))
        chain.append((_or, "qwen/qwen3-next-80b-a3b-instruct:free"))
    if settings.anthropic_api_key:
        chain.append((OpenAI(
            timeout=40, max_retries=1,
            api_key=settings.anthropic_api_key,
            base_url="https://api.anthropic.com/v1",
        ), "claude-haiku-4-5"))
    return chain


def _get_gate_chain() -> list[tuple[OpenAI, str]]:
    """Provider chain for the CHEAP relevance gate (~300-token prompt).

    Order is deliberately different from the full-extraction chain:
      0. Groq llama-3.1-8b-instant — TINY prompt fits its 6K TPM, and it
         has a 500K tokens/DAY bucket (5x the 70b). Gate calls are cheap
         and plentiful here — exactly what a high-volume pre-filter needs.
      1. Groq llama-3.3-70b-versatile — backup if 8b errors.
      2. Gemini flash-lite — free last resort, separate daily bucket.

    The gate's whole purpose is to AVOID burning the expensive chain on
    obvious junk, so it must run on the highest-capacity cheapest model.
    (2026-06-11: the old slot-2 was PAID OpenRouter Haiku — removed. With
    the OpenRouter balance negative it 402'd anyway, and if topped up it
    would silently resume draining the wallet on every gate call.)
    """
    chain: list[tuple[OpenAI, str]] = []
    if settings.groq_api_key:
        groq_client = OpenAI(
            timeout=40, max_retries=1,
            api_key=settings.groq_api_key,
            base_url="https://api.groq.com/openai/v1",
        )
        chain.append((groq_client, "llama-3.1-8b-instant"))
        chain.append((groq_client, "llama-3.3-70b-versatile"))
    gem = getattr(settings, "gemini_api_key", None)
    if gem:
        chain.append((OpenAI(
            timeout=40, max_retries=1,
            api_key=gem,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        ), "gemini-2.0-flash-lite"))
    return chain


# Cheap pre-filter prompt. ~300 tokens. Kills obvious non-incidents
# (cabinet news, opinion, national politics, pre-May-11 events) BEFORE
# they reach the 6K-token full-extraction prompt. Biased toward
# relevant=true on uncertainty so it never silently drops a real incident.
GATE_SYSTEM_PROMPT = (
    "You are a fast, strict binary classifier for a Tamil Nadu TVK-government "
    "accountability tracker. You output ONLY compact JSON, nothing else."
)

GATE_PROMPT = """TVK govt took office 2026-05-11. Article published: {published}.

TITLE: {title}
TEXT: {text_head}

Output ONLY this JSON: {{"relevant": true}} or {{"relevant": false}}

relevant=TRUE if this is a SPECIFIC Tamil Nadu event dated ON OR AFTER 2026-05-11:
- a crime with a named victim/place (murder, assault, rape, theft, kidnap, honour killing, caste/communal attack, child abuse, petrol-bomb)
- a named corruption case / scam / bribe / tender irregularity
- a civic failure at a named place (power cut, water shortage, flood, sewage, hospital failure)
- a TVK policy decision with concrete impact (scheme launch/cancel, fare hike, closure, license action)
- a broken or delayed government promise
- a politician defecting TO TVK
- an attack on a named journalist or media outlet
- TVK claiming credit for a DMK-era scheme

relevant=FALSE for: cabinet/portfolio/swearing-in news, party alliances forming,
generic speeches/press conferences, opinion/editorial/columns, "X criticised Y"
he-said-she-said, election commentary, DMK/Stalin reactions, movies/sports/celebrity,
national news (Modi/BJP/RSS/parliament) not specific to TN, weather forecasts alone,
crime-statistic AGGREGATES (no single named incident), and ANY event before 2026-05-11.

When genuinely unsure, answer {{"relevant": true}} — a fuller check runs next."""


def _passes_relevance_gate(item) -> tuple[bool, str]:
    """Cheap pre-filter. Returns (should_proceed, reason).

    should_proceed=True  -> route to the expensive full extraction
    should_proceed=False -> skip; obvious junk, save the tokens

    FAIL-OPEN by design: any AI error, missing provider, or unparseable
    response returns True so a gate hiccup never drops a real incident.
    The only thing that returns False is the model clearly saying
    relevant=false on a tiny, cheap call.
    """
    chain = _get_gate_chain()
    if not chain:
        return True, "no_gate_provider"
    prompt = GATE_PROMPT.format(
        published=getattr(item, "published_at", None) or "?",
        title=(getattr(item, "title", "") or "")[:200],
        text_head=(getattr(item, "text", "") or "")[:1500],
    )
    messages = [
        {"role": "system", "content": GATE_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    last_err = None
    for client, model in chain:
        try:
            resp = client.chat.completions.create(
                model=model, max_tokens=20, messages=messages,
            )
            raw = (resp.choices[0].message.content or "").strip()
            low = raw.lower()
            # Explicit false → skip. Everything else → proceed (fail-open).
            if '"relevant": false' in low or '"relevant":false' in low or \
               "'relevant': false" in low:
                return False, "gate_rejected"
            return True, "gate_passed"
        except Exception as e:
            last_err = e
            if _is_quota_or_rate_error(e):
                continue  # try next provider in the gate chain
            continue
    # Whole gate chain failed → fail-open, let full extraction decide
    logger.warning("Relevance gate chain failed (%s); failing open", last_err)
    return True, "gate_error_failopen"


def _is_quota_or_rate_error(exc: Exception) -> bool:
    """Recognise OpenAI/OpenRouter errors that indicate we should try the
    next provider in the chain (insufficient credits, rate limited, etc.)."""
    s = str(exc).lower()
    if "402" in s or "insufficient" in s or "credit" in s or "quota" in s:
        return True
    if "429" in s or "rate limit" in s or "rate_limit" in s:
        return True
    if "401" in s or "unauthor" in s or "invalid_api_key" in s:
        return True
    return False


def llm_call_with_fallback(messages: list[dict], *, max_tokens: int = 1024) -> str | None:
    """Call the LLM chain with automatic provider failover.

    Tries each (client, model) in order. On 402/429/401 from one
    provider, logs and falls through to the next. Returns the raw
    string response from the first provider that succeeds, or None
    if every provider failed.

    Non-quota errors (network, parse, etc.) on the LAST provider raise.
    """
    chain = _get_client_chain()
    if not chain:
        logger.warning("No AI provider configured")
        return None

    last_err: Exception | None = None
    for i, (client, model) in enumerate(chain):
        try:
            resp = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=messages,
            )
            return resp.choices[0].message.content
        except Exception as e:
            last_err = e
            is_last = i == len(chain) - 1
            if _is_quota_or_rate_error(e) and not is_last:
                logger.warning("Provider %d (%s) hit quota/rate (%s); falling through to next",
                               i, model, type(e).__name__)
                continue
            if is_last:
                # Last provider failed too — bubble up the original error
                logger.error("All %d providers failed; last error on %s: %s",
                             len(chain), model, e)
                return None
            # Non-quota error on non-last provider — also try the next one
            # rather than fail loudly (a transient network blip shouldn't
            # block everything if we have a fallback available).
            logger.warning("Provider %d (%s) errored (%s); trying next",
                           i, model, type(e).__name__)
            continue
    if last_err:
        logger.error("Provider chain exhausted: %s", last_err)
    return None


def _load_dmk_schemes_for_prompt(db) -> str:
    try:
        res = db.table("dmk_schemes").select("name, aliases").execute()
        rows = res.data or []
    except Exception:
        return "(scheme registry unavailable)"
    lines = []
    for r in rows:
        aliases = ", ".join(r.get("aliases") or [])
        lines.append(f"  - {r['name']} | aliases: {aliases}")
    return "\n".join(lines) if lines else "(registry empty)"


def _event_signature(extracted: dict) -> str:
    """Normalized key for fuzzy dedup. Two articles with the same
    category + location + incident_date are presumed to be the same event."""
    cat = (extracted.get("category") or "other").lower()
    loc = re.sub(r"[^a-z0-9]+", "", (extracted.get("location") or "").lower())[:30]
    d = extracted.get("incident_date") or date.today().isoformat()
    return f"{cat}:{loc}:{d}"


# Stopwords stripped before title-similarity so common filler doesn't inflate
# the overlap score. Includes place/party words that appear in most titles.
_TITLE_STOP = {
    "the", "a", "an", "of", "in", "on", "at", "to", "and", "or", "for", "with",
    "is", "was", "are", "were", "after", "over", "near", "by", "from", "into",
    "tamil", "nadu", "tn", "tvk", "case", "video", "watch", "news", "update",
    "justnow", "breaking", "report", "alleged", "allegedly",
}


# Categories whose titles are generic/location-only ("Power Cut in Chennai")
# and recur for genuinely different events — excluded from fuzzy title-merge
# (they still dedup via the exact category+location+date signature).
_GENERIC_TITLE_CATS = {"power_cut", "eb_failure", "civic_failure", "water_shortage"}

# Deterministic safety net for the rule the LLM applies unreliably on bare
# headlines: a pre-announced TANGEDCO maintenance shutdown is ROUTINE utility
# ops, not an accountability failure. The prompt already says so, but "Power Cut
# in Chennai" excerpts still slip through, so we re-check post-extraction.
_MAINT_SIG = re.compile(
    r"schedul|planned|pre-?announced|announce[ds]?\b|maintenance|"
    r"routine|upkeep|shutdown for|repair work|will be implemented|"
    r"to take place|check (?:the )?list|charge (?:your )?phones",
    re.I,
)
# If ANY of these appear, something went WRONG (unplanned) -> keep as an incident.
_GRIEVANCE_SIG = re.compile(
    r"protest|rally|rallies|besieg|sieg|detain|confront|anger|abuse|outrage|"
    r"unannounced|unplanned|dies|died|death|elderly|oxygen|ventilat|unconscious|"
    r"hospital|crisis|dangerous|sabotage|vip|unrespons|frequent|repeated|"
    r"continued|overnight|night-?time|wartime|complaint|helpline|alleg|"
    r"acknowledg|raise[sd]? question|infrastructure|fluctuat",
    re.I,
)


def _is_routine_power_maintenance(category: str, title: str, summary: str) -> bool:
    """True only for a routine, pre-announced power-maintenance notice with no
    grievance/failure element — these do NOT belong in the power-cut section."""
    if category not in {"power_cut", "eb_failure"}:
        return False
    blob = f"{title or ''} {summary or ''}"
    return bool(_MAINT_SIG.search(blob)) and not _GRIEVANCE_SIG.search(blob)


# Out-of-state guard. The LLM sometimes ingests another state's crime news
# (a Bengaluru robbery, a Telangana drug seizure) into this TN tracker — even
# writing "the incident occurred in Karnataka, not Tamil Nadu" and approving it
# anyway. High-precision deterministic catch, post-extraction.
_OUT_ADMISSION = re.compile(r"(?:not|outside(?:\s+of)?)\s+tamil\s*nadu", re.I)
_NON_TN_LOC = re.compile(
    r"\b(bengaluru|bangalore|karnataka|telangana|hyderabad|kerala|kochi|kozhikode|"
    r"thiruvananthapuram|trivandrum|mumbai|maharashtra|pune|new delhi|delhi|noida|"
    r"gurugram|gurgaon|kolkata|west bengal|gujarat|ahmedabad|surat|uttar pradesh|"
    r"lucknow|bihar|patna|rajasthan|jaipur|punjab|himachal|madhya pradesh|odisha|"
    r"assam|jharkhand|chhattisgarh|goa|saudi|dubai|abu dhabi|qatar|kuwait)\b",
    re.I,
)
# A Tamil-Nadu nexus (govt/institution/district) — its presence overrides the
# location check (e.g. "hard disks stolen from TNEB HQ, arrested in Bengaluru").
_TN_HOOK = re.compile(
    r"\b(tamil\s*nadu|tamilnadu|tvk|vijay|dmk|stalin|udhayanidhi|annamalai|tneb|"
    r"tangedco|tasmac|cmda|cmrl|chennai|madurai|coimbatore|trichy|tiruchirap|salem|"
    r"tirunelveli|thoothukudi|tuticorin|erode|vellore|tiruppur|thanjavur|dindigul|"
    r"kanchi|kancheepuram|tiruvannamalai|cuddalore|nagapattinam|krishnagiri|"
    r"dharmapuri|namakkal|karur|theni|sivaganga|ramanathapuram|virudhunagar|tenkasi|"
    r"villupuram|ranipet|kallakurichi|ariyalur|perambalur|pudukottai|mayiladuthurai|"
    r"tirupathur|chengalpattu|tiruvallur|nilgiri|ooty|hosur|avadi|ambattur|tambaram)\b",
    re.I,
)


def _is_out_of_state(location: str, title: str, summary: str) -> bool:
    """True when the event clearly occurred outside Tamil Nadu with no TN nexus."""
    blob = f"{location or ''} {title or ''} {summary or ''}".lower()
    if _OUT_ADMISSION.search(blob):          # the model's own "not Tamil Nadu" confession
        return True
    if _TN_HOOK.search(blob):                # any TN govt/institution/district -> keep
        return False
    if location and _NON_TN_LOC.search(location.lower()):  # location pins it out of state
        return True
    return False


def _title_tokens(s: str) -> set[str]:
    """Tokenise a headline for similarity. Keeps Latin + Tamil word chars so
    Tamil-script duplicates can match too."""
    return {
        w for w in re.findall(r"[a-z0-9஀-௿]+", (s or "").lower())
        if len(w) > 2 and w not in _TITLE_STOP
    }


def _title_jaccard(a: str, b: str) -> float:
    """Token Jaccard similarity of two headlines (0..1)."""
    ta, tb = _title_tokens(a), _title_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _find_fuzzy_duplicate(db, extracted: dict, cutoff_iso: str):
    """Catch the same event when the exact signature missed it because the
    LOCATION was written differently (e.g. 'Gummidipoondi' vs 'Thiruvallur'
    vs blank for one Tiruvallur event → 3 incidents).

    Looks at incidents of the SAME category within ±1 day, then merges ONLY
    when the headlines are genuinely similar — so two *different* crimes in the
    same district on the same day are never wrongly merged (over-merging would
    HIDE a real incident, which is worse than a duplicate). The title check is
    the guard; same-district just relaxes the threshold slightly.
    """
    cat = extracted.get("category")
    title = extracted.get("title") or ""
    idate = (extracted.get("incident_date") or "")[:10]
    if not (cat and title and idate):
        return None
    # Infrastructure categories have generic, location-only titles ("Power Cut
    # in Chennai") that legitimately recur for DIFFERENT events — title
    # similarity can't tell two distinct outages apart, so fuzzy-merging them
    # would HIDE real incidents. They still dedup via the exact category+
    # location+date signature; we just don't fuzzy-match them.
    if cat in _GENERIC_TITLE_CATS:
        return None
    district = None
    try:
        from app.ingestion.district_mapper import map_location_to_district
        district = map_location_to_district(extracted.get("location"))
    except Exception:
        district = None
    try:
        d = date.fromisoformat(idate)
    except Exception:
        return None
    lo, hi = (d - timedelta(days=1)).isoformat(), (d + timedelta(days=1)).isoformat()
    try:
        cands = (db.table("incidents")
                 .select("id, title, district, source_urls, source_count, "
                         "verification_status, ai_confidence")
                 .eq("category", cat)
                 .neq("status", "rejected")  # don't revive merged duplicates
                 .gte("incident_date", lo).lte("incident_date", hi)
                 .gte("created_at", cutoff_iso)
                 .limit(60).execute().data or [])
    except Exception:
        return None
    best, best_score = None, 0.0
    for c in cands:
        sim = _title_jaccard(title, c.get("title") or "")
        same_dist = bool(district) and (c.get("district") == district)
        # Same district → 0.45 is enough; different/blank district → demand 0.65.
        threshold = 0.45 if same_dist else 0.65
        if sim >= threshold and sim > best_score:
            best, best_score = c, sim
    return best


def _strip_code_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.strip()
    return s


def _record_audit(db, incident_id: str, action: str, **fields) -> None:
    try:
        db.table("incident_audit").insert({
            "incident_id": incident_id,
            "action": action,
            "actor": fields.pop("actor", "ai"),
            **fields,
        }).execute()
    except Exception as e:
        logger.warning("Failed to write audit log: %s", e)


def analyze_only(*, url: str, source: str, title: str, text: str) -> dict:
    """Run the Claude extractor against an article WITHOUT writing anything
    to the database. Used by the admin quick-add form so the human can edit
    the AI's output before publishing.

    Raises RuntimeError if no AI provider is configured.
    Returns the raw `extracted` dict from the model.
    """
    if not _get_client_chain():
        raise RuntimeError("No AI provider configured (set OPENROUTER_API_KEY or ANTHROPIC_API_KEY)")

    db = get_db()
    schemes_block = _load_dmk_schemes_for_prompt(db)
    prompt = EXTRACTION_PROMPT.format(
        url=url,
        source=source or "unknown",
        published=date.today().isoformat(),
        title=title,
        text=(text or "")[:8000],
        dmk_schemes=schemes_block,
        today=date.today().isoformat(),
    )

    raw_response = llm_call_with_fallback(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=1024,
    )
    if raw_response is None:
        raise RuntimeError("All AI providers failed (check OpenRouter credits + Anthropic key)")
    raw = _strip_code_fences(raw_response)
    extracted = json.loads(raw)

    # Best-effort: also attach fact-check matches so admin sees them in the form
    try:
        fc = lookup_factchecks(extracted.get("title") or title,
                                (extracted.get("people_mentioned") or [])[:3])
        if fc:
            extracted["related_factchecks"] = fc
    except Exception:
        pass

    return extracted


async def process_article(item: ApifyWebhookItem) -> None:
    if not _get_client_chain():
        logger.warning("No AI provider configured — skipping %s", item.url)
        return

    db = get_db()

    # ---- 0. Dedup by URL ----
    existing = db.table("sources").select("id").eq("url", item.url).execute()
    if existing.data:
        logger.debug("Already processed: %s", item.url)
        return

    # ---- 0.5. CHEAP RELEVANCE GATE ----
    # Most ingested items (cabinet news, opinion, national politics, etc.)
    # are NOT trackable incidents. Running the 6K-token full-extraction
    # prompt on all of them exhausts the free-tier daily token budget in
    # ~12 articles. This ~300-token gate (on the cheap 8B model with a
    # 500K/day bucket) filters the obvious junk first. Fail-open: on any
    # gate error it returns True and the full extractor still runs.
    proceed, gate_reason = _passes_relevance_gate(item)
    if not proceed:
        logger.debug("Gate rejected (%s): %s", gate_reason, item.url)
        return

    # ---- 1. Claude extraction ----
    schemes_block = _load_dmk_schemes_for_prompt(db)
    prompt = EXTRACTION_PROMPT.format(
        url=item.url,
        source=item.source or "unknown",
        published=item.published_at or "?",
        title=item.title,
        text=(item.text or "")[:8000],
        dmk_schemes=schemes_block,
        today=date.today().isoformat(),
    )

    try:
        raw_response = llm_call_with_fallback(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1024,
        )
        if raw_response is None:
            logger.error("All AI providers failed for %s — skipping", item.url)
            return
        raw = _strip_code_fences(raw_response)
        extracted = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("AI returned invalid JSON for %s: %s", item.url, e)
        return
    except Exception as e:
        logger.error("Claude call failed for %s: %s", item.url, e)
        return

    if not extracted.get("is_relevant"):
        logger.debug("Not relevant: %s", item.url)
        return

    # ---- 2. Record source ----
    # Outlet detection: if the URL host matches a known press outlet, use
    # that as the outlet name (Hindu, ToI, etc.) regardless of which RSS
    # feed it came from. This is important for Google News aggregator
    # entries where item.source='gnews_tvk_govt' but the actual URL is
    # thehindu.com/... — we want it counted as "the_hindu" for the 2+
    # distinct outlets verification gate.
    from app.ingestion.corroboration import _identify_outlet, PRESS_TIERS
    detected_outlet, detected_tier = _identify_outlet(item.url, item.source or "")
    if detected_tier in PRESS_TIERS:
        outlet = detected_outlet
        tier = detected_tier
    else:
        outlet = item.source or "unknown"
        tier = getattr(item, "tier", None) or "established_press"
    image_urls = getattr(item, "image_urls", None) or []
    db.table("sources").insert({
        "url": item.url,
        "outlet": outlet,
        "title": item.title,
        "credibility_tier": tier,
    }).execute()

    # ---- 3. Multi-source verification gate ----
    # Signature = category:location:incident_date. Two articles about the same
    # event (e.g. a Reddit post and a Hindu article) get the same signature.
    #
    # Window extended from 48h → 30 DAYS so that an old single-source
    # pending_verification incident (e.g. a Reddit post from 2 weeks ago)
    # gets AUTO-PROMOTED to multi_source_verified when a press source today
    # reports the same event. This is the "truth-first" cross-reference loop.
    signature = _event_signature(extracted)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    similar = (
        db.table("incidents")
        .select("id, source_urls, source_count, verification_status, ai_confidence")
        .eq("event_signature", signature)
        # Never match a retracted/merged duplicate — otherwise a new source for
        # the event resurrects the row we deliberately folded into the keeper
        # (the Gummidipoondi 3yo case had 10 such revivals). Excluded rows fall
        # through to the fuzzy matcher, which routes the source to the keeper.
        .neq("status", "rejected")
        .gte("created_at", cutoff)
        .execute()
    )

    confidence = extracted.get("confidence", 0.5)

    # Exact-signature match first; if none, try the fuzzy fallback that catches
    # the same event written with a different location string (the Gummidipoondi
    # / Thiruvallur / blank → 3 incidents bug). The title guard inside keeps
    # distinct same-district events apart.
    target = similar.data[0] if similar.data else \
        _find_fuzzy_duplicate(db, extracted, cutoff)

    if target:
        # Found an existing incident matching this event → add this source
        new_sources = list(set((target.get("source_urls") or []) + [item.url]))
        new_count = len(new_sources)

        # Cross-source verification: distinct outlets are stronger than dup-outlet
        distinct_outlets = (
            db.table("sources")
            .select("outlet", count="exact")
            .in_("url", new_sources)
            .execute()
        )
        outlet_count = distinct_outlets.count or new_count

        # Determine the right status:
        #   2+ distinct outlets       -> multi_source_verified
        #   1 outlet but it's press   -> press_verified (NEW: single press
        #                                source is credible on its own —
        #                                Hindu / SunNews / Vikatan etc. are
        #                                real journalism, not Reddit posts)
        #   only social_media         -> pending_verification (still needs
        #                                press to publish)
        from app.ingestion.corroboration import PRESS_TIERS as _PRESS_TIERS_SET
        _is_reddit_xref = ("reddit.com" in (item.url or "").lower()) or ("reddit" in (outlet or "").lower())
        is_press_source = (tier in _PRESS_TIERS_SET) and not _is_reddit_xref
        if outlet_count >= 2:
            new_status = "multi_source_verified"
        elif is_press_source:
            new_status = "press_verified"
        else:
            new_status = "pending_verification"

        publish_visible = new_status in ("multi_source_verified", "press_verified")

        db.table("incidents").update({
            "source_urls": new_sources,
            "source_count": new_count,
            "verification_status": new_status,
            "status": "approved" if publish_visible else "pending_review",
            # Keep highest confidence
            "ai_confidence": max(target.get("ai_confidence") or 0, confidence),
        }).eq("id", target["id"]).execute()

        _record_audit(
            db, target["id"], "source_added",
            from_value=str(target.get("source_count") or 1),
            to_value=str(new_count),
            metadata={"new_source": item.url, "verification_status": new_status},
        )
        logger.info("Cross-reference: %s now at %d sources [%s]", signature, new_count, new_status)
        return

    # ---- 4. First sighting of this event — decide auto-publish vs queue ----
    # New status hierarchy:
    #   multi_source_verified  — 2+ press outlets agree (only set later)
    #   press_verified         — 1 press-tier source (NEW)
    #   pending_verification   — social_media / unknown, awaits press
    # Reddit posts had historical mis-tagging as 'online_native'; explicitly
    # disqualify any URL on reddit.com from press_verified.
    from app.ingestion.corroboration import PRESS_TIERS as _PRESS_TIERS_SET
    HIGH_TIER = {"primary", "established_press"}
    _is_reddit = ("reddit.com" in (item.url or "").lower()) or ("reddit" in (outlet or "").lower())
    is_press_source = (tier in _PRESS_TIERS_SET) and not _is_reddit

    if is_press_source and confidence >= 0.6:
        # Press outlet at decent confidence -> publish as press_verified.
        # Future cross-ref from a 2nd outlet upgrades to multi_source_verified.
        verification_status = "press_verified"
        publish_status = "approved"
    elif tier in HIGH_TIER and confidence >= 0.7:
        # Edge case: established press but lower confidence in extraction
        verification_status = "press_verified"
        publish_status = "approved"
    else:
        # Social_media / citizen / low-confidence -> waits for press
        verification_status = "pending_verification"
        publish_status = "pending_review"  # held back from public view

    # ROUTINE-MAINTENANCE GUARD: a pre-announced TANGEDCO scheduled/maintenance
    # shutdown is utility upkeep, not a power-supply failure or grievance. The
    # prompt says so, but bare "Power Cut in <place>" headlines still slip past
    # the LLM — so reject deterministically here. Grievance markers (protest,
    # unplanned, death, hospital, repeated/continued cuts) exempt it.
    if _is_routine_power_maintenance(
        extracted.get("category") or "", extracted.get("title") or "", extracted.get("summary") or ""
    ):
        publish_status = "rejected"
        verification_status = "rejected"

    # OUT-OF-STATE GUARD: don't ingest another state's crime news into the TN
    # tracker. The LLM occasionally does this even after noting "occurred in
    # Karnataka, not Tamil Nadu" — reject deterministically (a TN govt/institution/
    # district nexus exempts it, e.g. a TNEB matter with an arrest in Bengaluru).
    if _is_out_of_state(
        extracted.get("location") or "", extracted.get("title") or "", extracted.get("summary") or ""
    ):
        publish_status = "rejected"
        verification_status = "rejected"

    # DMK-LINEAGE GUARD: a TVK "first-ever" / investment / scheme-launch claim
    # must be checked against the 2021-26 DMK record before it's published as a
    # clean win — these are exactly the Singappen / HD Hyundai / police-drone
    # re-credits. Hold them for human review (queued under pending_review) and
    # mark WHY. Items the AI already flagged as credit_steal keep normal
    # handling (they're correctly captured).
    if extracted.get("first_ever_claim") and not extracted.get("is_credit_steal") \
       and (extracted.get("category") or "") in {
           "governance", "new_initiative", "investment_announcement", "tenders"}:
        publish_status = "pending_review"
        _s = extracted.get("summary") or ""
        if not _s.startswith("⚑"):
            extracted["summary"] = ("⚑ DMK-LINEAGE CHECK — verify against the "
                                    "2021-26 DMK record before treating as a TVK win. " + _s)

    # Only persist press_sentiment for INDEPENDENT press tiers — exclude
    # govt_announcement (CMO/DIPR are partisan by definition), citizen
    # reports, and social_media leads. The speaker must be a neutral
    # observer for tone classification to be meaningful.
    from app.ingestion.corroboration import INDEPENDENT_PRESS_TIERS
    raw_sentiment = extracted.get("press_sentiment")
    valid_sentiments = {"positive_for_govt", "negative_for_govt", "neutral"}
    press_sentiment = (
        raw_sentiment if (tier in INDEPENDENT_PRESS_TIERS and raw_sentiment in valid_sentiments)
        else None
    )

    # District resolution: dictionary lookup first (free, fast); AI fallback
    # only if the dictionary can't find a match.  The result powers the
    # District Mood page without changing anything else about ingestion.
    try:
        from app.ingestion.district_mapper import map_location_to_district
        resolved_district = map_location_to_district(extracted.get("location"))
    except Exception:
        resolved_district = None

    # Clamp the incident date: never let an event be dated in the FUTURE
    # (the LLM occasionally mis-parses a scheduled/post-dated article).
    _idate = extracted.get("incident_date") or date.today().isoformat()
    if str(_idate)[:10] > date.today().isoformat():
        _idate = date.today().isoformat()

    incident_payload = {
        "title": extracted["title"],
        "summary": extracted["summary"],
        "category": extracted["category"],
        "incident_date": _idate,
        "location": extracted.get("location"),
        "district": resolved_district,
        "source_urls": [item.url],
        "source_count": 1,
        "is_credit_steal": extracted.get("is_credit_steal", False),
        "original_credit": extracted.get("original_credit"),
        "related_dmk_scheme": extracted.get("related_dmk_scheme"),
        "severity": extracted.get("severity", 1),
        "ai_confidence": confidence,
        "member_ids": [],
        "status": publish_status,
        "verification_status": verification_status,
        "event_signature": signature,
        "image_urls": image_urls,
        "ai_raw": extracted,
        "press_sentiment": press_sentiment,
    }

    inserted = db.table("incidents").insert(incident_payload).execute()
    if not inserted.data:
        logger.error("Insert failed for %s", item.url)
        return
    incident_id = inserted.data[0]["id"]

    _record_audit(
        db, incident_id, "created",
        to_value=verification_status,
        metadata={"category": extracted["category"], "confidence": confidence},
    )

    # ---- 5. Best-effort: fact-check lookup (async, non-blocking on failure) ----
    try:
        factchecks = lookup_factchecks(extracted["title"], (extracted.get("people_mentioned") or [])[:3])
        if factchecks:
            db.table("incidents").update({"related_factchecks": factchecks}).eq("id", incident_id).execute()
            logger.info("Attached %d factchecks to %s", len(factchecks), incident_id)
    except Exception as e:
        logger.warning("Factcheck lookup failed for %s: %s", incident_id, e)

    # ---- 6. Best-effort: image suspicion check ----
    if image_urls:
        try:
            enqueue_images(db, incident_id, image_urls)
        except Exception as e:
            logger.warning("Image check failed for %s: %s", incident_id, e)

    # ---- 7. DMK archive cross-reference (only for credit-steal candidates) ----
    if extracted.get("is_credit_steal") or extracted.get("related_dmk_scheme"):
        try:
            precedents = find_precedents(
                incident_title=extracted["title"],
                incident_summary=extracted["summary"],
                related_scheme=extracted.get("related_dmk_scheme"),
                limit=5,
            )
            attached = attach_evidence(incident_id, precedents)
            if attached:
                logger.info(
                    "Cross-ref: attached %d DMK archive precedents to %s",
                    attached, incident_id,
                )
        except Exception as e:
            logger.warning("Archive cross-ref failed for %s: %s", incident_id, e)

    logger.info(
        "Saved [%s] conf=%.2f sig=%s: %s",
        verification_status, confidence, signature, extracted["title"],
    )

    # ---- 7a. PROMISE COMPARATOR (govt-tier announcements + press) -------
    # Fires on:
    #   (a) tier=govt_announcement (CMO/DIPR posts) — the original case
    #   (b) tier in PRESS_TIERS when the extractor flagged the article as
    #       related to a scheme / promise / implementation (signals:
    #       category in {broken_promise, partial_promise, kept_promise,
    #       new_initiative, governance, credit_stealing} OR title/summary
    #       mentions specific scheme keywords)
    # This catches "Sun News says TVK loan waiver is inadequate" without
    # needing CMO to tweet first.
    from app.ingestion.corroboration import PRESS_TIERS as _PT_FOR_CMP
    _scheme_words = ("scheme", "manifesto", "promise", "waiver", "padai",
                     "thittam", "thogai", "magalir", "singappen",
                     "loan", "subsidy", "free", "assistance", "rupees")
    _comparator_should_fire = (
        tier == "govt_announcement"
        or (
            tier in _PT_FOR_CMP and (
                extracted.get("category") in {
                    "broken_promise", "partial_promise", "kept_promise",
                    "new_initiative", "credit_stealing"
                }
                or any(w in (extracted.get("title", "") + " " + extracted.get("summary", "")).lower()
                       for w in _scheme_words)
            )
        )
    )
    if _comparator_should_fire:
        try:
            from app.ingestion.promise_comparator import compare_to_manifesto
            verdict = compare_to_manifesto(
                title=extracted["title"],
                summary=extracted["summary"],
                category=extracted["category"],
                location=extracted.get("location"),
                date=extracted.get("incident_date") or date.today().isoformat(),
                announcement_url=item.url,
            )
            if verdict:
                v = verdict.get("verdict")
                # Map verdict to a clean incident category that downstream
                # filters / dashboard cards can rely on.
                cat_for_verdict = {
                    "fulfilled":   "kept_promise",
                    "partial":     "partial_promise",
                    "broken":      "broken_promise",
                    "new":         "new_initiative",
                    "irrelevant":  None,    # don't overwrite extractor's category
                }.get(v)
                update_fields = {}
                if cat_for_verdict:
                    update_fields["category"] = cat_for_verdict
                # Store the full verdict on the incident for the UI to render
                merged_raw = dict(extracted)
                merged_raw["promise_verdict"] = verdict
                update_fields["ai_raw"] = merged_raw
                db.table("incidents").update(update_fields).eq("id", incident_id).execute()
                logger.info(
                    "Promise comparator: incident %s -> category=%s, matched_promise=%s, verdict=%s",
                    incident_id, cat_for_verdict, verdict.get("best_match_promise_id"), v,
                )
        except Exception as e:
            # Never let comparator failure break the ingestion path
            logger.warning("Promise comparator failed for %s: %s", item.url, e)

    # ---- 7b. Defection record (horse-trading tracker) -----------------
    # When the article describes an MLA / leader switching parties, also
    # persist a defection row so the /horse-trading page + meter can
    # consume it. We never block on this — failure logs only.
    defection_payload = extracted.get("defection")
    if isinstance(defection_payload, dict) and defection_payload.get("mla_name"):
        try:
            mla_name = (defection_payload.get("mla_name") or "").strip()
            from_party = (defection_payload.get("from_party") or "").strip()
            # Dedup: same person + same from/to party = same defection
            existing = (
                db.table("defections")
                .select("id")
                .eq("mla_name", mla_name)
                .eq("from_party", from_party)
                .limit(1)
                .execute()
            )
            if not (existing.data or []):
                drec = {
                    "mla_name":         mla_name,
                    "constituency":     defection_payload.get("constituency"),
                    "from_party":       from_party or "AIADMK",
                    "to_party":         defection_payload.get("to_party") or "TVK",
                    "resignation_date": defection_payload.get("resignation_date"),
                    "joined_date":      defection_payload.get("joined_date"),
                    "stated_reason":    defection_payload.get("stated_reason"),
                    "alleged_reason":   defection_payload.get("alleged_reason"),
                    "pending_cases":    defection_payload.get("pending_cases") or [],
                    "evidence_urls":    [item.url],
                    "severity":         extracted.get("severity", 3),
                    "ai_confidence":    float(defection_payload.get("confidence") or confidence),
                    # Mirror the incident's verification gate: tier+confidence
                    # high enough → publish as 'pending' (visible w/ badge),
                    # else hold as 'pending' anyway (still visible) but UI
                    # will show "single source" warning.
                    "status":           "pending",
                    "ai_raw":           defection_payload,
                }
                db.table("defections").insert(drec).execute()
                logger.info("Horse-trading: recorded defection of %s (%s → %s)",
                            mla_name, drec["from_party"], drec["to_party"])
            else:
                # Already on file — append this URL as additional evidence
                drow_id = existing.data[0]["id"]
                drow_res = db.table("defections").select("evidence_urls").eq("id", drow_id).single().execute()
                cur_urls = (drow_res.data or {}).get("evidence_urls") or []
                if item.url not in cur_urls:
                    db.table("defections").update({
                        "evidence_urls": list(set(cur_urls + [item.url])),
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }).eq("id", drow_id).execute()
                    logger.info("Horse-trading: added URL to existing defection %s", mla_name)
        except Exception as e:
            logger.warning("Defection persistence failed for %s: %s", item.url, e)

    # ---- 8. IMMEDIATE corroboration attempt (no waiting for nightly sweep) ----
    # As soon as we save a pending incident, search Google News for press
    # coverage. If 2+ press outlets are already reporting the same event,
    # the incident graduates to multi_source_verified before the user even
    # refreshes the dashboard. This is what makes the dashboard 'live truth'
    # instead of 'truth at 9 AM tomorrow'.
    if verification_status == "pending_verification":
        try:
            # Re-fetch the row so attempt_corroborate has the canonical source_urls
            fresh = (
                db.table("incidents")
                .select("id, title, summary, location, incident_date, source_urls, verification_status")
                .eq("id", incident_id)
                .single()
                .execute()
            )
            if fresh.data:
                outcome = attempt_corroborate(fresh.data)
                if outcome.get("promoted"):
                    logger.info(
                        "Live-corroborated [%s] via %s",
                        incident_id, ",".join(outcome.get("matched_outlets") or [])
                    )
        except Exception as e:
            # Never let corroboration failure break the ingestion path
            logger.warning("Live corroboration failed for %s: %s", incident_id, e)
