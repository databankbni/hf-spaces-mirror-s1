"""Map surveyor notes onto a full past-report paragraph — preserve length and structure."""

from __future__ import annotations

import re

from backend.config import settings
from backend.models.schema import TemplateSchema

_PLACEHOLDER_RE = re.compile(r"<text>", re.IGNORECASE)
_UNDERSCORE_BLANK_RE = re.compile(r"_{3,}")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# Specific-claim category detectors for the deterministic fallback merge. A baseline
# sentence carries a "specific, falsifiable claim" about the property when it fixes a
# side/position, a mechanism/type, or a structural relationship. These are the
# categories the past report (a DIFFERENT property) most often asserts and that the
# brief field notes most often leave silent — the documented fabrication-by-retention
# surface. Material is deliberately excluded here (too entangled with legitimate
# note-driven content for safe deterministic dropping); the LLM mapping + grounding
# auditor layers cover material. Patterns are high-precision to avoid false drops.
_POSITION_RE = re.compile(
    r"\b(?:left|right)[-\s]?hand(?:\s+side)?\b"
    r"|\bon\s+the\s+(?:left|right)\b"
    r"|\bto\s+the\s+(?:left|right|front|rear)\b"
    r"|\b(?:front|rear|side)\s+(?:elevation|aspect|slope|extension|garden)\b"
    r"|\b(?:north|south|east|west)(?:[-\s]?(?:east|west))?(?:ern|erly)?\s+"
    r"(?:elevation|aspect|slope|facing|side|gable|corner|boundary)\b",
    re.IGNORECASE,
)
_MECHANISM_RE = re.compile(
    r"\bup[-\s]?and[-\s]?over\b"
    r"|\broller\s+(?:door|shutter)\b"
    r"|\b(?:sliding|sectional|tilt[-\s]?and[-\s]?turn|side[-\s]?hinged)\s+"
    r"(?:door|doors|window|windows|gate)\b"
    r"|\b(?:sash|casement)\s+windows?\b"
    r"|\b(?:combi(?:nation)?|system|back)\s+boiler\b",
    re.IGNORECASE,
)
_RELATIONSHIP_RE = re.compile(
    r"\b(?:semi[-\s]?detached|detached|attached|integral|free[-\s]?standing|"
    r"adjoining|abutting)\b",
    re.IGNORECASE,
)
_SPECIFIC_CLAIM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("position", _POSITION_RE),
    ("mechanism", _MECHANISM_RE),
    ("relationship", _RELATIONSHIP_RE),
)
_STOP = frozenset(
    {
        "about",
        "with",
        "from",
        "this",
        "that",
        "level",
        "section",
        "inside",
        "outside",
        "other",
        "property",
        "report",
        "survey",
        "your",
        "the",
        "and",
        "were",
        "was",
        "has",
        "have",
        "been",
        "noted",
        "inspected",
        "ground",
    }
)


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", text.lower()) if w not in _STOP}


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()]


# ── Field-shorthand normalisation ────────────────────────────────────────────────
# Notes that bypass LLM expansion (the deterministic append/weave safety nets) must
# not ship raw field shorthand like "water is lit". These rules ONLY rephrase — they
# never add or drop a fact — so the zero-loss/zero-invention contract holds. The set
# is deliberately small: a wrong expansion would be a fabrication, worse than terse
# prose, so only unambiguous trade shorthand is included.
_UTILITY_LIT_RE = re.compile(
    r"\b(water|gas|electric(?:ity|s)?|heating|boiler)\s+(?:is|was|are|were)\s+lit\b",
    re.IGNORECASE,
)
_SHORTHAND_ABBREV = {
    "dg": "double glazing",
    "d/g": "double glazing",
    "sg": "single glazing",
    "upvc": "uPVC",
    "pvcu": "uPVC",
    "rwp": "rainwater pipe",
    "svp": "soil vent pipe",
    "approx": "approximately",
}
_SHORTHAND_ABBREV_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _SHORTHAND_ABBREV) + r")\b",
    re.IGNORECASE,
)


def _normalize_shorthand(text: str) -> str:
    """Rephrase unambiguous surveyor shorthand into report-grade prose (no fact change)."""
    s = (text or "").strip()
    if not s:
        return s
    s = _UTILITY_LIT_RE.sub(lambda m: f"the {m.group(1).lower()} supply was on", s)
    s = _SHORTHAND_ABBREV_RE.sub(lambda m: _SHORTHAND_ABBREV[m.group(1).lower()], s)
    return s


def _observation_prose(observations: list[str]) -> str:
    parts = [
        _normalize_shorthand(o).rstrip(".") for o in observations if o and o.strip()
    ]
    parts = [p for p in parts if p]
    if not parts:
        return ""
    text = "; ".join(parts)
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text


def _drop_unconfirmed_specific_sentences(
    sentences: list[str], notes_text: str
) -> list[str]:
    """Remove baseline sentences asserting an unconfirmed specific from another property.

    A sentence is dropped only when it fixes a side/position, mechanism/type, or
    structural relationship in a category the notes do not also exhibit. Generic
    methodology/principle sentences (no category match) and sentences whose category
    is corroborated by the notes are kept. The surveyor's actual notes are never lost:
    they are still woven/inserted by the caller after this pass.
    """
    note_categories = {
        name for name, pat in _SPECIFIC_CLAIM_PATTERNS if pat.search(notes_text)
    }
    kept: list[str] = []
    for sent in sentences:
        matched = {name for name, pat in _SPECIFIC_CLAIM_PATTERNS if pat.search(sent)}
        if matched - note_categories:
            continue
        kept.append(sent)
    return kept


def _weave_into_sentence(sentence: str, observations: list[str]) -> str:
    obs = _observation_prose(observations)
    if not obs:
        return sentence
    core = obs.rstrip(".")
    if core.lower() in sentence.lower():
        return sentence
    base = sentence.rstrip()
    if base.endswith("."):
        return f"{base[:-1]}; {core}."
    return f"{base}; {core}."


def merge_observations_into_paragraph(
    paragraph: str,
    observations: list[str],
    schema: TemplateSchema,
) -> str:
    """Return the full reference paragraph with notes mapped in (no bullets, no truncation).

    Sentences or topics not covered by the surveyor notes are left unchanged from the
    reference so the user can complete them manually after generation.
    """
    base = (paragraph or "").strip()
    if not base:
        return "\n".join(o for o in observations if o.strip())
    if not observations:
        return base

    obs = [o.strip() for o in observations if o and o.strip()]
    obs_text = "; ".join(obs)

    for marker in schema.placeholders.free_text_markers:
        if marker and marker in base:
            return base.replace(marker, obs_text).strip()

    if _PLACEHOLDER_RE.search(base):
        return _PLACEHOLDER_RE.sub(obs_text, base, count=1).strip()

    if _UNDERSCORE_BLANK_RE.search(base):
        return _UNDERSCORE_BLANK_RE.sub(obs_text, base, count=1).strip()

    sentences = _split_sentences(base)
    if not sentences:
        obs_sent = _observation_prose(obs)
        return f"{base} {obs_sent}." if obs_sent and not base.endswith(".") else base

    # Excise the other property's unconfirmed specifics (side/mechanism/relationship)
    # before weaving. If that empties the paragraph, fall back to the notes themselves.
    sentences = _drop_unconfirmed_specific_sentences(sentences, obs_text)
    if not sentences:
        obs_sent = _observation_prose(obs)
        return f"{obs_sent}." if obs_sent else ""

    obs_tokens = _tokens(obs_text)
    best_i = -1
    best_score = 0
    for i, sent in enumerate(sentences):
        overlap = len(obs_tokens & _tokens(sent))
        if overlap > best_score:
            best_score = overlap
            best_i = i

    if best_i >= 0 and best_score > 0:
        sentences[best_i] = _weave_into_sentence(sentences[best_i], obs)
    elif obs_sent := _observation_prose(obs):
        # Notes do not overlap any reference sentence — add without altering the rest.
        insert_at = min(1, len(sentences))
        sentences.insert(insert_at, f"{obs_sent}.")

    return " ".join(sentences)


# ── Notes-bounded baseline reduction (verbatim/passthrough paths only) ────────
# Applied where the surveyor's notes did NOT map onto the retrieved past-report
# section, so the system must NOT reproduce that other property's section as-is.
# A sentence is kept only when it carries no specific, falsifiable claim about the
# property/inspection, OR the notes corroborate that specific value. This is value-
# level (not topic-level) corroboration: a baseline "concrete tiles" sentence is
# dropped when the notes say "slate", even though both mention "tiles". Generic
# surveying principles, recommendations and regulatory boilerplate (no specific
# claim) are retained — matching the style-plus-safe policy.
#
# Deliberately separate from `_drop_unconfirmed_specific_sentences` (which is pinned
# to the weave path and intentionally ignores material): this reducer is only used
# on the no-mappable passthrough, where aggressive dropping cannot discard mapped
# note content because none was mapped.

_PAGE_FURNITURE_RE = re.compile(r"^\s*(?:page\s+)?\d{1,4}\.?\s*$", re.IGNORECASE)
_TRAILING_PAGE_NO_RE = re.compile(r"\s+\d{1,4}\.?\s*$")

# Material asserted as the element's fabric. Bare material nouns appear in generic
# prose and homographs ("lead to") cause false positives, so a material only counts
# when it sits in an assertion construction (copula/"of …"/"<material> covering").
_MATERIALS = (
    "slate",
    "slates",
    "concrete",
    "bitumen",
    "bituminised",
    "lead",
    "zinc",
    "copper",
    "upvc",
    "pvcu",
    "timber",
    "brickwork",
    "brick",
    "blockwork",
    "masonry",
    "render",
    "polycarbonate",
    "grp",
    "fibreglass",
    "asphalt",
    "clay",
    "terracotta",
    "aluminium",
    "softwood",
    "hardwood",
    "stone",
    "pebbledash",
    "stucco",
    "shingle",
    "thatch",
    "felt",
)
_MAT_ALT = "|".join(re.escape(m) for m in _MATERIALS)
# Bare material detector — retained for optional callers / tests; fabric assertions are
# no longer used to drop scaffold sentences (prompt handles foreign materials).
_MATERIAL_RE = re.compile(r"\b(" + _MAT_ALT + r")\b", re.IGNORECASE)
_DIRECTION_RE = re.compile(
    r"\b(left|right|front|rear|north|south|east|west)\b", re.IGNORECASE
)
_MEASUREMENT_RE = re.compile(
    r"\b\d+(?:\.\d+)?[-\s]*(?:mm|cm|metre|metres|meter|meters|per\s+cent|degrees?)\b"
    r"|\b\d+(?:\.\d+)?\s*%"
    r"|\b\d+(?:\.\d+)?\s*m\b",
    re.IGNORECASE,
)
_COUNT_RE = re.compile(
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
    r"(?:ridge|hip|valley|vent)?\s*tiles?\b"
    r"|\b(?:a\s+)?(?:single|number\s+of)\s+(?:tiles?|cracks?)\b",
    re.IGNORECASE,
)
# Observed first-person/state findings about THIS property (vs general principles).
_DEFECT_STATE_RE = re.compile(
    r"\b(?:has|have|had|is|are|was|were)\s+(?:been\s+)?"
    r"(?:slipped|lifted|cracked|broken|missing|present|absent|deteriorat\w+|"
    r"perished|displaced|spalled|bowed|defective|installed|noted|observed)\b"
    r"|\bwe\s+(?:were\s+able\s+to|took|noted|observed|inspected)\b"
    r"|\b(?:photographs?|videos?|binoculars?|camera|drone)\b"
    r"|\bextendable\s+pole\b"
    r"|\bthere\s+(?:were|was|are|is)\b[^.?!]*\b(?:present|installed|fitted|provided|absent)\b"
    r"|\bno\b[^.?!]*\b(?:present|installed|fitted|provided)\b",
    re.IGNORECASE,
)

_SPECIFIC_CATEGORY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("mechanism", _MECHANISM_RE),
    ("relationship", _RELATIONSHIP_RE),
    ("count", _COUNT_RE),
    ("defect_state", _DEFECT_STATE_RE),
)

# Value-anchored categories still stripped on the note-mapped path. Material,
# position, measurement and construction-form stripping were removed — those
# claims are left to the prompt / auditor so past-report voice is not hollowed out.
_VALUE_ANCHORED_CATEGORIES = frozenset(
    {
        "mechanism",
        "relationship",
    }
)

# Generic survey methodology / limitation prose. These sentences frequently trip
# ``_DEFECT_STATE_RE`` (they mention "inspected", "binoculars", "from the roof
# void") yet carry no property-specific finding — they are stylistic baseline
# scaffolding and must never be stripped as an uncorroborated foreign observation.
_METHODOLOGY_RE = re.compile(
    r"\b(?:inspect\w*|binoculars?|camera|drone|extendable\s+pole|ground\s+level|"
    r"roof\s+void|where\s+(?:accessible|possible)|limited\s+to|visual(?:ly)?|"
    r"not\s+(?:possible|practical|able)|we\s+were\s+able\s+to)\b",
    re.IGNORECASE,
)


def _is_page_furniture(sentence: str) -> bool:
    return bool(_PAGE_FURNITURE_RE.match(sentence.strip()))


def _strip_trailing_page_number(sentence: str) -> str:
    """Drop a stray PDF page number stuck to the end of a sentence (… Rating 2. 27)."""
    s = sentence.rstrip()
    # Only strip a trailing bare number that follows a sentence terminator, so real
    # counts inside prose ("replace 3 tiles") are never touched.
    m = re.search(r"([.!?])\s+\d{1,4}\.?$", s)
    if m:
        return s[: m.start() + 1].rstrip()
    return sentence


def _sentence_specifics(sentence: str) -> set[str]:
    """Categories of specific, falsifiable claim asserted by a baseline sentence."""
    return {name for name, pat in _SPECIFIC_CATEGORY_PATTERNS if pat.search(sentence)}


def _notes_corroborate(sentence: str, cats: set[str], notes_text: str) -> bool:
    """True when the notes support the specific values the sentence asserts.

    Value-level, per category. A sentence is only retained when every specific
    category it triggers is echoed by the notes — so a foreign mechanism /
    relationship the surveyor never recorded is dropped even if the topic words
    overlap. Material, position, measurement and construction-form are not
    stripped here anymore.
    """
    notes_lower = notes_text.lower()
    notes_tokens = _tokens(notes_text)

    for cat, pat in (("mechanism", _MECHANISM_RE), ("relationship", _RELATIONSHIP_RE)):
        if cat in cats:
            phrases = {m.group(0).lower() for m in pat.finditer(sentence)}
            if phrases and not any(p in notes_lower for p in phrases):
                return False
    if cats & {"count", "defect_state"}:
        # No safe value anchor — keep only with strong topical overlap with notes.
        strong = {t for t in (_tokens(sentence) & notes_tokens) if len(t) >= 5}
        if len(strong) < 2:
            return False
    return True


def bound_baseline_to_notes(baseline: str, observations: list[str]) -> str:
    """Reduce a past-report baseline to what the notes actually support.

    Generic prose (no specific claim) is kept; specific claims are kept only when the
    notes corroborate the asserted value; page furniture is always stripped. Used on
    the no-mappable passthrough so the report never reproduces another property's
    section verbatim. Returns ``""`` when nothing safe remains (caller then authors
    from the surveyor's own notes instead).
    """
    base = (baseline or "").strip()
    if not base:
        return ""
    notes_text = "; ".join(o.strip() for o in (observations or []) if o and o.strip())
    kept: list[str] = []
    for raw in _split_sentences(base):
        sent = _strip_trailing_page_number(raw).strip()
        if not sent or _is_page_furniture(sent):
            continue
        cats = _sentence_specifics(sent)
        if not cats or _notes_corroborate(sent, cats, notes_text):
            kept.append(sent)
    return " ".join(kept).strip()


# Polarity pairs: when notes match ``note_pat`` the baseline must not retain
# ``baseline_pat`` (direct contradictions from another property's report).
_CONTRADICTION_RULES: tuple[tuple[re.Pattern[str], re.Pattern[str]], ...] = (
    (
        re.compile(
            r"not\s+functional|non[-\s]?functional|wasn['']t\s+working|not\s+working|"
            r"was\s+not\s+functional",
            re.I,
        ),
        re.compile(
            r"\bfunctional\b|operating\s+normally|found\s+to\s+be\s+operating",
            re.I,
        ),
    ),
    (
        re.compile(r"condensation|missing\s+item", re.I),
        re.compile(
            r"no\s+visible\s+signs\s+of\s+condensation|no\s+signs\s+of\s+condensation",
            re.I,
        ),
    ),
    (
        re.compile(
            r"supply\s+of\s+hot\s+water|hot\s+water\s+supply|hot\s+water\b", re.I
        ),
        re.compile(
            r"hot\s+water\s+was\s+not\s+available|no\s+hot\s+water|"
            r"full\s+functionality\s+could\s+not\s+be\s+verified",
            re.I,
        ),
    ),
    (
        re.compile(
            r"modern\s+electric|consumer\s+unit|\belectricity\b|electric\s+supply|"
            r"electric\s+meter",
            re.I,
        ),
        re.compile(
            r"no\s+supply\s+of\s+electricity|not\s+allowed\s+to\s+turn\s+the\s+electricity|"
            r"tape\s+on\s+some\s+of\s+the\s+electrical",
            re.I,
        ),
    ),
    (
        re.compile(
            r"water\s+is\s+lit|mains\s+water|water\s+supply|super.*water|\bwater\b.*\bon\b",
            re.I,
        ),
        re.compile(
            r"no\s+supply\s+of\s+water|shut\s+off|drained\s+down|"
            r"not\s+allowed\s+to\s+turn\s+the\s+water",
            re.I,
        ),
    ),
    # Cracking / structural movement polarity. The affirmative note phrases below
    # ("step cracking", "wall tie failure") never appear in a negation in practice,
    # so this rule fires only when the notes genuinely report movement and the
    # foreign baseline denies it.
    (
        re.compile(
            r"(?:step|stepped|diagonal|vertical|horizontal)\s+crack"
            r"|crack(?:s|ing|ed)?\s+(?:was|were|is|are|been|noted|observed|present|evident|visible)"
            r"|(?:cavity\s+)?wall\s+tie\s+failure|structural\s+movement",
            re.I,
        ),
        re.compile(
            r"no\s+(?:visible\s+|significant\s+|obvious\s+|further\s+)?(?:signs?|evidence|indication)\s+"
            r"of\s+(?:any\s+)?(?:cracking|cracks|structural\s+movement|movement|subsidence|"
            r"settlement|distortion)"
            r"|no\s+cracks?\b|free\s+from\s+(?:cracking|movement|distortion)"
            r"|(?:walls?|elevations?|structure)\s+(?:appeared?|were|was)\s+"
            r"(?:structurally\s+)?(?:sound|stable|plumb)",
            re.I,
        ),
    ),
    # Reverse polarity: notes explicitly DENY cracking/movement → drop a foreign
    # baseline that asserts it. Note pattern requires the negation token so it cannot
    # collide with the affirmative rule above.
    (
        re.compile(
            r"no\s+(?:visible\s+|significant\s+)?(?:signs?|evidence)?\s*of?\s*"
            r"(?:cracking|cracks|structural\s+movement|movement|subsidence|settlement)"
            r"|no\s+crack(?:s|ing)?\b",
            re.I,
        ),
        re.compile(
            r"(?:step|stepped|diagonal|vertical)\s+crack"
            r"|cracking\s+(?:was\s+)?(?:noted|observed|present|evident|visible)"
            r"|structural\s+movement\s+(?:was\s+)?(?:noted|observed|evident|present)"
            r"|evidence\s+of\s+(?:subsidence|settlement|structural\s+movement)",
            re.I,
        ),
    ),
)

# Whole-scenario bleed from other properties — drop when notes are silent on the topic.
# (scenario_pat matches a BASELINE sentence; note_guard is searched in the NOTES — the
# sentence is dropped only when the notes never raise the topic, so a genuinely-noted
# fact is always preserved.)
_FOREIGN_SCENARIO_PATTERNS: tuple[tuple[re.Pattern[str], re.Pattern[str]], ...] = (
    (
        re.compile(r"repossess", re.I),
        re.compile(r"repossess|bank\s+owned|lender", re.I),
    ),
    (
        re.compile(
            r"reservoir|environment\s+agency.*flood|flooding\s+from\s+reservoirs", re.I
        ),
        re.compile(r"reservoir|flood\s+risk|environment\s+agency", re.I),
    ),
    # Heritage status carried from another property's report.
    (
        re.compile(
            r"listed\s+building|grade\s+(?:i{1,3}|[12])\s+listed|"
            r"\bconservation\s+area\b|article\s+4\s+direction",
            re.I,
        ),
        re.compile(r"listed\b|conservation\s+area|heritage|article\s+4", re.I),
    ),
    # Structural-alteration claims (chimney breast / load-bearing wall removal,
    # conversion to flats). Kept whenever the notes actually mention an alteration.
    (
        re.compile(
            r"chimney\s+breasts?[^.?!]*\bremov"
            r"|load[-\s]?bearing\s+wall[^.?!]*\bremov"
            r"|(?:has|have|had|been)\s+converted\s+(?:in)?to\s+"
            r"(?:flats?|apartments?|maisonettes?|bedsits?)"
            r"|structural\s+alterations?\s+(?:have|has|had|were|was)"
            r"|wall[^.?!]*\b(?:has|had|have|been)\s+removed",
            re.I,
        ),
        re.compile(
            r"remov|convert|conversion|\bflats?\b|maisonette|apartment|bedsit|"
            r"alteration|chimney\s+breast|load[-\s]?bearing|knock(?:ed)?\s+through|"
            r"open(?:ed)?\s+up",
            re.I,
        ),
    ),
)

_COVERAGE_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")
_COVERAGE_STOP = frozenset(
    {"the", "and", "with", "was", "were", "are", "has", "have", "not"}
)


def _content_tokens(text: str) -> set[str]:
    return {
        t
        for t in _COVERAGE_TOKEN_RE.findall((text or "").lower())
        if t not in _COVERAGE_STOP
    }


def note_covered_in_text(note: str, text: str, *, min_ratio: float = 0.55) -> bool:
    """True when enough of the note's content tokens appear in the prose."""
    note_norm = (note or "").strip().lower()
    if not note_norm:
        return True
    if note_norm in (text or "").lower():
        return True
    want = _content_tokens(note_norm)
    if not want:
        return True
    have = _content_tokens(text or "")
    return len(want & have) / len(want) >= min_ratio


def find_uncovered_notes(
    notes: list[str], report_text: str, *, min_ratio: float = 0.55
) -> list[str]:
    """Zero-loss backstop: notes whose substance is absent from the WHOLE report.

    Run once after the full report is assembled. Any messy-note fact not reflected
    anywhere — because it was misrouted, dropped by a reducer, or lost by the LLM —
    is returned here (shorthand-normalised, de-duplicated) so the caller can surface
    it in the Unassigned Observations appendix instead of silently dropping it.
    Coverage is tested against both the raw and the normalised note so a fact already
    rendered in its expanded form ("water is lit" → "water supply was on") is not
    re-flagged.
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in notes:
        norm = _normalize_shorthand(raw)
        key = re.sub(r"\s+", " ", norm.lower()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        if note_covered_in_text(raw, report_text, min_ratio=min_ratio):
            continue
        if note_covered_in_text(norm, report_text, min_ratio=min_ratio):
            continue
        out.append(norm)
    return out


def strip_note_contradictions(baseline: str, observations: list[str]) -> str:
    """Drop baseline sentences that directly contradict the surveyor's notes."""
    base = (baseline or "").strip()
    if not base:
        return ""
    notes_text = "; ".join(o.strip() for o in (observations or []) if o and o.strip())
    if not notes_text:
        return base
    kept: list[str] = []
    for raw in _split_sentences(base):
        sent = _strip_trailing_page_number(raw).strip()
        if not sent or _is_page_furniture(sent):
            continue
        drop = False
        for note_pat, baseline_pat in _CONTRADICTION_RULES:
            if note_pat.search(notes_text) and baseline_pat.search(sent):
                drop = True
                break
        if not drop:
            for scenario_pat, note_guard in _FOREIGN_SCENARIO_PATTERNS:
                if scenario_pat.search(sent) and not note_guard.search(notes_text):
                    drop = True
                    break
        if not drop:
            kept.append(sent)
    return " ".join(kept).strip()


def strip_uncorroborated_observations(baseline: str, observations: list[str]) -> str:
    """Drop property-specific baseline observations with no topical support in notes.

    Targets ``defect_state`` sentences from another property (e.g. "no supply of
    electricity", "fan was functional") while keeping generic methodology prose.
    """
    base = (baseline or "").strip()
    if not base:
        return ""
    notes_text = "; ".join(o.strip() for o in (observations or []) if o and o.strip())
    notes_tokens = _tokens(notes_text)
    kept: list[str] = []
    for raw in _split_sentences(base):
        sent = _strip_trailing_page_number(raw).strip()
        if not sent or _is_page_furniture(sent):
            continue
        cats = _sentence_specifics(sent)
        if "defect_state" in cats and not _METHODOLOGY_RE.search(sent):
            strong = {t for t in (_tokens(sent) & notes_tokens) if len(t) >= 4}
            if len(strong) < 2:
                continue
        kept.append(sent)
    return " ".join(kept).strip()


def prepare_baseline_for_mapping(baseline: str, observations: list[str]) -> str:
    """Chain deterministic reducers before LLM mapping on the note-mapped path."""
    reduced = strip_foreign_property_facts(baseline, observations)
    reduced = strip_note_contradictions(reduced, observations)
    return strip_uncorroborated_observations(reduced, observations)


def append_missing_observations(text: str, observations: list[str]) -> str:
    """Append routed notes whose substance is absent from mapped prose."""
    base = (text or "").strip()
    missing = [
        o.strip()
        for o in (observations or [])
        if o.strip() and not note_covered_in_text(o, base)
    ]
    if not missing:
        return base
    addon = _observation_prose(missing)
    if not addon:
        return base
    if base.endswith("."):
        return f"{base} {addon}."
    return f"{base}. {addon}."


def strip_foreign_property_facts(baseline: str, observations: list[str]) -> str:
    """Drop value-anchored foreign specifics the notes do not corroborate.

    Currently limited to mechanism / relationship claims. Material, position,
    measurement and construction-form are not stripped here (left to the prompt).
    Methodology and defect/count sentences are also deferred on the mapped path.
    """
    base = (baseline or "").strip()
    if not base:
        return ""
    notes_text = "; ".join(o.strip() for o in (observations or []) if o and o.strip())
    kept: list[str] = []
    for raw in _split_sentences(base):
        sent = _strip_trailing_page_number(raw).strip()
        if not sent or _is_page_furniture(sent):
            continue
        cats = _sentence_specifics(sent) & _VALUE_ANCHORED_CATEGORIES
        if not cats or _notes_corroborate(sent, cats, notes_text):
            kept.append(sent)
    return " ".join(kept).strip()


def compress_to_budget(text: str, note_terms: set[str], max_chars: int) -> str:
    """Extractively compress ``text`` to ``max_chars`` by note relevance.

    Deterministic and extractive (no LLM, no paraphrase, no new claims): split into
    sentences, score each by content-token overlap with the notes, then greedily
    admit the highest-scoring sentences that still fit the budget. Selected
    sentences are emitted in their original document order so the kept prose stays
    coherent. This replaces the positional tail-cut (which drops whatever happens to
    fall after the budget, regardless of relevance) with a relevance-aware keep.
    """
    text = (text or "").strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    sentences = _split_sentences(text)
    if len(sentences) <= 1:
        return text[:max_chars].strip()
    ranked = sorted(
        range(len(sentences)),
        key=lambda i: (
            len(_content_tokens(sentences[i]) & note_terms),
            -len(sentences[i]),
        ),
        reverse=True,
    )
    chosen: set[int] = set()
    used = 0
    for i in ranked:
        cost = len(sentences[i]) + 1  # +1 for the joining space
        if used + cost > max_chars:
            continue
        chosen.add(i)
        used += cost
    if not chosen:  # always keep at least the single most relevant sentence
        chosen.add(ranked[0])
    return " ".join(sentences[i] for i in sorted(chosen)).strip()


def reorder_sentences_edges_in(sentences: list[str], note_terms: set[str]) -> list[str]:
    """Re-order sentences "edges-in": most note-relevant at the head and tail.

    Mitigates the long-context "lost in the middle" effect — models attend most to
    the start and end of their context. Sentences are scored by content-token
    overlap with the notes, sorted descending, then placed alternately at the
    outermost free positions (0, n-1, 1, n-2, ...), so the least relevant land in
    the middle. Stable on ties (original index breaks ties) and a no-op for fewer
    than three sentences or when there is nothing to score against.
    """
    if len(sentences) < 3 or not note_terms:
        return sentences
    ranked = sorted(
        range(len(sentences)),
        key=lambda i: (len(_content_tokens(sentences[i]) & note_terms), -i),
        reverse=True,
    )
    ordered = [sentences[i] for i in ranked]  # most relevant first
    n = len(ordered)
    positions: list[int] = []
    lo, hi = 0, n - 1
    to_front = True
    while lo <= hi:
        if to_front:
            positions.append(lo)
            lo += 1
        else:
            positions.append(hi)
            hi -= 1
        to_front = not to_front
    result: list[str | None] = [None] * n
    for item, pos in zip(ordered, positions, strict=False):
        result[pos] = item
    return [s for s in result if s is not None]


def combine_reference_blocks(
    primary: str,
    extras: list[str] | None = None,
    *,
    note_terms: set[str] | None = None,
    multi_source: bool = False,
) -> str:
    """Merge reference chunks into the fullest paragraph without duplicating sentences.

    Document order is preserved by default — critical for a single coherent section,
    whose chunks arrive in paragraph order. When ``settings.context_reorder_enabled``
    is set AND the caller marks this a genuine ``multi_source`` merge (blocks that do
    NOT form one ordered section) with ``note_terms`` to score against, the merged
    sentences are re-ordered edges-in (lost-in-the-middle mitigation). The sole
    current caller assembles one ordered section and does not opt in, so default
    behaviour is unchanged.
    """
    sentences = _split_sentences(primary)
    seen = {s.lower() for s in sentences}
    for ref in extras or []:
        for sent in _split_sentences(ref):
            key = sent.lower()
            if key not in seen:
                sentences.append(sent)
                seen.add(key)
    if settings.context_reorder_enabled and multi_source and note_terms:
        sentences = reorder_sentences_edges_in(sentences, note_terms)
    return " ".join(sentences)


def reference_body_preserved(
    output: str, reference: str, *, min_ratio: float = 0.5
) -> bool:
    """True when most reference sentences are still reflected in the output."""
    ref_sents = _split_sentences(reference)
    if not ref_sents:
        return bool(output.strip())
    out_tokens = _tokens(output)
    kept = 0
    for sent in ref_sents:
        sent_tokens = _tokens(sent)
        if not sent_tokens:
            continue
        overlap = len(sent_tokens & out_tokens)
        if overlap >= max(2, len(sent_tokens) * min_ratio):
            kept += 1
    return kept >= max(1, int(len(ref_sents) * min_ratio))


def apply_notes_to_paragraph(
    paragraph: str,
    observations: list[str],
    schema: TemplateSchema,
) -> str:
    """Legacy MASTER merge: full paragraph + bullet append when no placeholder."""
    base = (paragraph or "").strip()
    if not base:
        return "\n".join(o for o in observations if o.strip())

    obs = [o.strip() for o in observations if o and o.strip()]
    if not obs:
        return base

    merged = merge_observations_into_paragraph(base, obs, schema)
    if merged != base:
        return merged

    bullets = "\n".join(f"• {o}" for o in obs)
    return f"{merged}\n\n{bullets}".strip()
