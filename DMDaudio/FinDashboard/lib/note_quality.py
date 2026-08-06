"""Is this activity-note slice actually a statement of what the business does?

:mod:`lib.activity_note` answers "where in the report is the activity note" and
is tuned for *recall* — it fires on any of ~20 anchors and picks the best window.
This module answers the narrower question the LLM stage actually needs: **is the
text we sliced worth classifying from?** It runs on an already-emitted note (from
``activity_snippets.jsonl`` or a fresh slice) and returns a reason code, so a
dry-run CSV can show why a company was skipped instead of silently dropping it.

Why it is a separate gate and not a tightening of the slicer: the slicer's
anchors are load-bearing for the 2,539 companies already classified from them,
and its rejection rules operate on a *candidate window* before the sentence is
chosen. These eight failures all survive the current slicer (verified 2026-07-28
against the extracted corpus) because the anchor genuinely fires — the words
"principal activity" really are in the sentence — but the sentence is about
something else:

    company                        slice says                        reason
    Bank of Georgia   204378869    climate-transition analysis        esg
    TBC Bank          204854595    "Scope 1 (combustion of fuel)"     esg
    Liberty Bank      203828304    "NOT related to the bank's         risk
                                    principal activity … flood,
                                    fire, earthquake"
    Credo Bank        205232238    "principal risks are described     crossref
                                    in the Business Review"
    ქართული სპირტი    415099967    the IAS 40 investment-property     accounting_policy
                                   definition
    Tbilisi Electr.   406312690    "principal place of business is:   address
                                    Otar Chkheidze 10, 0186"
    Atlas             404569944    "…because the group's principal    truncated
                                    activity is." (no object)
    Tbilisi Energy    205129617    "the subject of activity is c."    truncated
                                   (split on the abbreviation ქ.)

The last one is a slicer bug worth fixing separately — ``_SENT_SPLIT`` treats the
Georgian abbreviation ``ქ.`` ("city") as a sentence end — but rejecting the slice
is the right outcome either way: better to leave the company for a human than to
classify it from a sentence that names no activity.

The accept condition is deliberately positive rather than "not rejected": the
note must either **assert an activity** ("the company's principal activity is X")
with enough text after the copula to be that X, or name a **business object** — a
thing the company trades, makes, or provides.

The assertion test is primary and the object vocabulary is the fallback, which is
the opposite of the first cut of this module. Measured on the 4,686 sliced notes,
an object-vocabulary-first gate rejected 30.8% of them, and sampling the
high-confidence classifications it would have thrown away showed why: Georgian
builds activity nouns freely (``დამზადება`` manufacture, ``გაყიდვა`` sale,
``მოპოვება`` extraction, ``სამუშაოების შესრულება`` performance of works,
``საგანმანათლებლო`` educational), so any hand-listed noun set will keep missing
real ones. "There is a principal-activity claim, and there is text after it"
generalises; a vocabulary does not.

Pure/stdlib-only: no DB, no network, no Streamlit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["NoteVerdict", "REJECT_REASONS", "assess_note", "is_usable"]

#: Minimum letters in the note. Below this there is nothing to classify from.
#: Kept low deliberately: a terse but complete statement is legitimate ("The
#: Company operates hotels." is 24 letters), and the truncated-claim case is
#: already covered by :data:`MIN_ASSERTION_TAIL` and ``_TRUNCATED_TAIL`` rather
#: than by overall length. On the measured corpus this floor accounts for only 72
#: of 857 rejections, so raising it buys little and costs real notes.
MIN_LETTERS = 22

#: Above this digit-to-letter ratio the slice is a table row, not prose. Slightly
#: looser than the slicer's 0.28 because a legitimate note often carries a store
#: count, a founding year and a registration number (Nikora's names 634 shops).
MAX_DIGIT_RATIO = 0.40

#: Letters that must follow a principal-activity claim for the claim to have an
#: object. "…principal activity is construction activity." leaves 20.
MIN_ASSERTION_TAIL = 15

REJECT_REASONS: tuple[str, ...] = (
    "too_short", "toc", "table", "esg", "risk", "crossref",
    "accounting_policy", "address", "boilerplate", "truncated",
    "no_activity_statement",
)

# --- reject classes, most specific first ---------------------------------

# Sustainability reporting. Georgian filings increasingly carry a TCFD/ESG
# section that quotes "principal activities" verbatim while discussing emissions.
_ESG = re.compile(
    r"კლიმატ\w*|გამონაბოლქვ\w*|ნახშირბად\w*|მდგრადობ\w*|სათბურის\s+გაზ"
    r"|\bscope\s*[123]\b|emission|greenhouse|climate|sustainab|\bTCFD\b|\bESG\b"
    r"|carbon\s+(?:footprint|neutral)|decarbonis",
    re.IGNORECASE,
)

# Operational-risk prose, and the specific trap of a sentence that NEGATES the
# link to the principal activity ("events not related to the bank's principal
# activity: flood, fire, earthquake").
_RISK = re.compile(
    r"არ\s+არის\s+დაკავშირებული|not\s+(?:directly\s+)?(?:related|connected)\s+to"
    r"|წყალდიდობა|ხანძარ\w*|მიწისძვრ\w*|flood|earthquake"
    r"|რისკ\w*\s*(?:ებ)?ი?\s+(?:მართვ|შეფასებ|იდენტიფიცირ)|risk\s+(?:management|appetite|exposure)"
    r"|ძირითადი\s+რისკ|principal\s+risk|operational\s+risk",
    re.IGNORECASE,
)

# "…is described in detail in the Business Review" — names the note's location,
# never its content.
_CROSSREF = re.compile(
    r"აღწერილი\w*\s+არის|არის\s+აღწერილ|დეტალურად\s+არის|იხილეთ|იხ\.\s*\d"
    r"|described\s+in\s+(?:detail\s+)?(?:the\s+)?\w+|set\s+out\s+in|refer\s+to\s+note"
    r"|see\s+note\s*\d",
    re.IGNORECASE,
)

# IFRS recognition/measurement prose. The IAS 40 investment-property definition
# is the worst offender because it literally contains "principal activities,
# administrative purposes or rental".
_ACCOUNTING_POLICY = re.compile(
    r"აღრიცხულია|აღიარებ\w*|თვითღირებულებ\w*|გაუფასურებ\w*|ცვეთ\w*|ამორტიზაცი\w*"
    r"|სამართლიან\w*\s+ღირებულებ|საბალანსო\s+ღირებულებ"
    # Receivables/payables definitions quote "arising from the entity's principal
    # activity", so they pass the assertion test and must be caught here.
    r"|დებიტორულ\w*|კრედიტორულ\w*|დავალიანებ\w*|მისაღები\s+თანხ"
    r"|\bIAS\s*\d|\bIFRS\s*\d|ფასს\s*\d"
    r"|(?:is|are)\s+(?:initially\s+)?(?:measured|recognis|recogniz|carried)"
    r"|carrying\s+amount|fair\s+value\s+(?:less|through)|impairment\s+loss"
    r"|(?:trade\s+)?receivable|payable|depreciat|amortis|amortiz",
    re.IGNORECASE,
)

# Standard prose that mentions "activity" while saying nothing about the business.
# Mirrors ``lib.activity_note._ACTIVITY_BOILERPLATE`` — kept here as well because
# the shipped ``activity_snippets.jsonl`` was built before those rules landed, so
# the cache still contains slices the current slicer would refuse to emit.
_BOILERPLATE = re.compile(
    r"ფუნქციონირებად\w*|საქმიანობა\s+გაგრძელდება|going\s+concern"
    r"|სოციალური\s+პასუხისმგებლობ|corporate\s+social\s+responsib"
    r"|მარეგულირებელ\w*|regulated\s+by|regulator\b"
    r"|აუდიტორ\w*|audit(?:or|ing)\b"
    r"|ანგარიშგებ\w*\s+მომზადებ|basis\s+of\s+preparation",
    re.IGNORECASE,
)

# "principal place of business is: <street> <number>, <postcode>, <city>" — the
# `en:principal-place` / `ka:activity-field` anchors both land on addresses.
_ADDRESS = re.compile(
    r"(?:მისამართ\w*|ადგილია|ადგილმდებარეობ\w*|registered\s+(?:office|address)"
    r"|place\s+of\s+business)\s*(?:არის|is)?\s*[:\-–]",
    re.IGNORECASE,
)
_ADDRESSY_TAIL = re.compile(r"\d{1,4}\s*[,;]|\b\d{4}\b\s*[,;]|ქ\.\s*\w|\bстр\b", re.IGNORECASE)

# "the principal PLACE of activity is Georgia" — the same words as an activity
# claim, but it names a geography. No colon follows, so ``_ADDRESS`` misses it.
_PLACE_OF_ACTIVITY = re.compile(
    r"საქმიანობის\s+ძირითადი\s+ადგილ|ძირითადი\s+საქმიანობის\s+ადგილ"
    r"|principal\s+place\s+of\s+(?:business|activit)"
    # 2026-08-05: the LOCATION-COUNT form. "კომპანია ძირითად საქმიანობას
    # ანხორციელებს ერთ ლოკაციაზე — საქართველო, წყალტუბო, რუსთაველის ქ." says
    # where the business happens and never what it is, but it satisfies every
    # other test — it has the anchor, a predicate and a place. Two of these
    # reached live tearsheets (წყალტუბო პლაზა 421269512, აისბერგი-9 445384682)
    # before it was caught. Note the misspelt ანხორციელებს: same hand-typing as
    # the ძირითადი transposition, so the ა is optional here too.
    r"|საქმიანობას?\s+ა?ნ?ხორციელებს\s+\S*\s*ლოკაცია",
    re.IGNORECASE,
)

# ``ძირითადი საქმიანობა ხორციელდება საქართველოს ტერიტორიაზე`` — the same trap in
# VERB form, and it cannot be a pre-accept reject class like the nouns above.
# The nouns REPLACE the activity claim, so a note containing them is the wrong
# text whatever else it says. This one only means the object slot was filled by a
# geography, and a legitimate note can name its activity and then add where it
# operates ("we mill wheat …; the activity is carried out in Georgia") — a blanket
# rule rejected that too. So it is applied to the assertion's TAIL only: refused
# when "is carried out" is what follows the claim, accepted when a real object
# does and this merely trails it. All 26 corpus hits are the former.
_CARRIED_OUT_TAIL = re.compile(r"^\s*ხორციელდება", re.IGNORECASE)

# A credit-risk CONCENTRATION disclosure lists the dimensions exposure is grouped
# BY — "by counterparty, by geographic location and by sector of activity" — so
# the activity noun arrives in the purposive case ``-სთვის`` and names nothing the
# filer does. It survived every other class: the fragment carries no IFRS
# recognition verb, no risk-management verb, and no negated-activity phrase, and
# ``სფერო\w*`` in _ACTIVITY_ASSERTION happily absorbs the case ending, so the
# comma-separated remainder cleared MIN_ASSERTION_TAIL and the note was accepted.
# Three filers (202431412, 404473164, 404480897) carry a byte-identical 148-char
# instance of it; an adjudicating reader found them and had to return Unknown.
# Deliberately a narrow literal, not a concentration-risk vocabulary: this
# module's history is that broad object vocabularies over-reject (see the 30.8%
# note above), so this is scoped to the measured phrase.
_CONCENTRATION = re.compile(r"საქმიანობის\s+სფეროსთვის", re.IGNORECASE)

# Table-of-contents dot leaders.
_TOC = re.compile(r"\.{4,}|…{2,}")

# A sentence that ends immediately after the copula/activity verb, i.e. the
# object was cut off ("the group's principal activity is.").
_TRUNCATED_TAIL = re.compile(
    r"(?:წარმოადგენს|საგანია|სახეა|არის|მოიცავს|ეწევა|ახორციელებს"
    r"|is|are|includes?|comprises?)\s*[.:;]?\s*$",
    re.IGNORECASE,
)

# --- the accept condition ------------------------------------------------

# A claim about what the business principally does. The group captures everything
# after the copula, which is where the activity itself has to be — see
# MIN_ASSERTION_TAIL. `\w*` absorbs Georgian case endings.
_ACTIVITY_ASSERTION = re.compile(
    r"(?:"
    r"(?:ძირითად\w*|მთავარ\w*|ძირითადი\s+ბიზნეს)\s+(?:ბიზნეს\s+)?საქმიანობ\w*"
    r"|საქმიანობის\s+(?:ძირითადი\s+)?(?:საგან\w*|სფერო\w*|მიმართულებ\w*|სახე\w*)"
    r"|ძირითადი\s+საქმიანობა"
    r"|(?:principal|main|primary|core)\s+(?:business\s+)?activit\w*"
    r"|nature\s+of\s+(?:the\s+)?business"
    r")"
    # optional copula / colon, then the object
    r"\s*(?:არის|არიან|აა|ა|წარმოადგენს|მოიცავს|იყო|is|are|comprises?|includes?)?"
    r"\s*[:\-–]?\s*(?P<tail>.*)",
    re.IGNORECASE | re.DOTALL,
)

# Fallback for notes that describe the business without the formal claim
# ("the company engages in transport activity", "operates 634 shops and produces
# food products"). Stems chosen so prefixed verb forms hit too — `წარმოებ`
# matches `აწარმოებს` ("produces"), `მშენებლ` matches `სამშენებლო`.
_BUSINESS_OBJECT = re.compile(
    r"ვაჭრობ\w*|წარმოებ\w*|დამზადებ\w*|გაყიდვ\w*|შეძენ\w*|მომსახურებ\w*"
    r"|იმპორტ\w*|ექსპორტ\w*|მშენებლ\w*|სამუშაო\w*|რემონტ\w*|მონტაჟ\w*"
    r"|ტრანსპორტ\w*|გადაზიდვ\w*|საბანკო|დაზღვევ\w*|იჯარ\w*|გაქირავებ\w*"
    r"|რეალიზაცი\w*|მიწოდებ\w*|დისტრიბუცი\w*|მაღაზი\w*|რესტორან\w*|სასტუმრო\w*"
    r"|აფთიაქ\w*|კლინიკ\w*|საავადმყოფო|მეურნეობ\w*|მოშენებ\w*|მოყვან\w*"
    r"|მოპოვებ\w*|გადამუშავებ\w*|თევზ\w*|ელექტროენერგი\w*|აირის|გაზ(?:ის|ს)\b"
    r"|ნავთობ\w*|ბენზინ\w*|დიზელ\w*|საწვავ\w*|მადნეულ\w*|ლითონ\w*|ავტომანქან\w*"
    r"|პროგრამულ\w*|ტელეკომუნიკაცი\w*|განათლ\w*|საგანმანათ\w*|ლიზინგ\w*|სესხ\w*"
    r"|retail|wholesale|manufactur|production|services?\b|import|export"
    r"|construction|transport|logistics|banking|insurance|leasing|distribut"
    r"|trading|development|generation|supply|hospitality|pharmac|clinic"
    r"|agricultur|mining|telecom|software",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NoteVerdict:
    """Whether a note is classifiable, and why not when it isn't."""

    usable: bool
    #: One of :data:`REJECT_REASONS`, or ``""`` when usable.
    reason: str
    #: Short human-readable detail for the dry-run CSV.
    detail: str = ""

    def __bool__(self) -> bool:  # pragma: no cover - convenience
        return self.usable


def _letters_digits(text: str) -> tuple[int, int]:
    return (sum(ch.isalpha() for ch in text), sum(ch.isdigit() for ch in text))


def assess_note(note: str | None) -> NoteVerdict:
    """Classify ``note`` as usable, or reject it with a reason code.

    Runs on the FULL note text — judging a truncated prefix inverts several
    calls (Nikora's slice opens with a shop count and only names food production
    ~90 characters in, so a 60-char preview reads as a metrics fragment).
    """
    if not note or not note.strip():
        return NoteVerdict(False, "too_short", "empty")
    text = " ".join(note.split())
    letters, digits = _letters_digits(text)
    # Dot leaders are decisive whatever the length — a short TOC fragment is a TOC,
    # not merely a short note, and the distinction matters when triaging reasons.
    if _TOC.search(text):
        return NoteVerdict(False, "toc", "dot leaders — matched the table of contents")
    if letters < MIN_LETTERS:
        return NoteVerdict(False, "too_short", f"{letters} letters")
    ratio = digits / max(letters, 1)
    if ratio > MAX_DIGIT_RATIO:
        return NoteVerdict(False, "table", f"digit ratio {ratio:.2f}")

    if _ESG.search(text):
        return NoteVerdict(False, "esg", "sustainability/emissions section")
    if _RISK.search(text):
        return NoteVerdict(False, "risk", "risk-note prose or a negated activity link")
    if _CROSSREF.search(text):
        return NoteVerdict(False, "crossref", "points at another section instead of describing")
    if _ACCOUNTING_POLICY.search(text):
        return NoteVerdict(False, "accounting_policy", "IFRS recognition/measurement prose")
    if _CONCENTRATION.search(text):
        return NoteVerdict(False, "risk",
                           "credit-risk concentration dimension, not an activity")
    if _PLACE_OF_ACTIVITY.search(text):
        return NoteVerdict(False, "address", "principal PLACE of activity — a geography")
    if _ADDRESS.search(text) and _ADDRESSY_TAIL.search(text):
        return NoteVerdict(False, "address", "registered address, not an activity")
    if _BOILERPLATE.search(text):
        return NoteVerdict(False, "boilerplate", "going-concern/CSR/regulator/audit prose")
    if _TRUNCATED_TAIL.search(text):
        return NoteVerdict(False, "truncated", "sentence cut off before naming the activity")

    # Primary accept: an explicit principal-activity claim WITH an object after it.
    m = _ACTIVITY_ASSERTION.search(text)
    if m:
        tail = m.group("tail")
        tail_letters = sum(ch.isalpha() for ch in tail)
        # The claim is present and long enough, but its object is "is carried out
        # <somewhere>" — a geography standing where the activity should be.
        if _CARRIED_OUT_TAIL.match(tail):
            return NoteVerdict(False, "address",
                               "activity claim answered with a geography, not an activity")
        if tail_letters >= MIN_ASSERTION_TAIL:
            return NoteVerdict(True, "", f"activity claim + {tail_letters} letters of object")
        # A claim with nothing after it is the Atlas/Tbilisi-Energy shape.
        return NoteVerdict(False, "truncated",
                           f"activity claim with only {tail_letters} letters after it")

    # Fallback accept: no formal claim, but it names something the business does.
    if _BUSINESS_OBJECT.search(text):
        return NoteVerdict(True, "", f"business object named, {letters} letters")

    return NoteVerdict(False, "no_activity_statement",
                       "no principal-activity claim and no business object")


def is_usable(note: str | None) -> bool:
    """Convenience predicate for callers that don't need the reason."""
    return assess_note(note).usable
