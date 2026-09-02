"""PII scrubbing for the v2 backend — single-pass, domain-aware redaction.

The previous single-pass scrubber suffered from *entity bleed*: a broad spaCy
NER pass (PERSON/GPE/LOC/FAC/ORG) plus greedy reference regexes redacted ordinary
survey vocabulary — materials (``timber``, ``lead``, ``uPVC``), directions
(``left``, ``rear``), regulatory names (``FENSA``, ``Building Regulations``) —
destroying the technical context the downstream RAG LLM depends on.

Architecture — **one candidate pass**:

* **Regex (always on):** deterministic UK-focused patterns for postcodes,
  addresses, emails, phones, URLs, money, dates, and reference / UPRN /
  Land-Registry / NINO identifiers (all ``\\b``-anchored).
* **spaCy NER (optional):** PERSON only — catches uncapitalized names the regex
  misses. Entities whose surface text is RICS survey vocabulary
  (:data:`PROPTECH_SAFE_WHITELIST`) are skipped at source so ``slate``, ``lead
  flashing``, ``FENSA``, etc. are never PII candidates.

Policy unchanged: REFERENCE-tier uploads are scrubbed at ingest; surveyor field
notes are parsed verbatim; generated output is gated/redacted before DOCX export.

Referential integrity: pass one :class:`ScrubSession` through every chunk of a
single file-processing run so each unique sensitive value maps to one stable
token (``[REDACTED_NAME_1]``) everywhere, while distinct values stay distinct.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from backend.config import settings
from backend.domain.rics_level3_schema import DEFAULT_RATING_SYSTEM_NAME

logger = logging.getLogger(__name__)


class PiiDetectedError(RuntimeError):
    """Raised by :func:`assert_no_pii` when disallowed PII is present."""


# ── Survey vocabulary (NER exclusion list) ─────────────────────────────────
# RICS/proptech terms that spaCy PERSON sometimes mis-tags. These are excluded
# at the NER layer so they never become redaction candidates. Real PII (postcodes,
# emails, titled names, street addresses) is unaffected — it is caught by regex.

_SPATIAL_TERMS = frozenset(
    {
        "front",
        "rear",
        "left",
        "right",
        "elevation",
        "side",
        "landing",
        "bedroom",
        "kitchen",
        "loft",
        "ground floor",
        "upper level",
        "apex",
        "perimeter",
    }
)

_MATERIAL_TERMS = frozenset(
    {
        "timber",
        "brickwork",
        "solid brick",
        "lath",
        "plaster",
        "plasterboard",
        "cement",
        "mortar",
        "lead",
        "copper",
        "upvc",
        "plastic",
        "cast iron",
        "slate",
        "tile",
        "felt",
        "bitumen",
        "velux",
        "concrete",
    }
)

# The RICS rating label is not inlined here: it is derived from the canonical
# DEFAULT_RATING_SYSTEM_NAME so the engine core holds no RICS literal (see
# RICS_CONSTANT_INVENTORY.md 2.1). The effective set is unchanged: base ∪ {rating}.
_BASE_STATUS_TERMS = frozenset(
    {
        "defect",
        "satisfactory",
        "serviceable",
        "deflection",
        "distortion",
        "cracking",
        "spalled",
        "damp",
        "moisture",
        "insulation",
    }
)

_STATUS_TERMS = _BASE_STATUS_TERMS | frozenset({DEFAULT_RATING_SYSTEM_NAME.lower()})

_COMPLIANCE_TERMS = frozenset(
    {
        "building regulations",
        "local authority",
        "fensa",
        "gas safe",
        "rics",
        "home survey",
        "level 3",
        "environment agency",
        "council tax band",
    }
)

# Supplementary structural vocabulary that NER models routinely mis-tag as
# ORG/FAC/PERSON. Kept separate from the spec-mandated sets above for clarity.
_EXTRA_STRUCTURAL_TERMS = frozenset(
    {
        "render",
        "flashing",
        "gutter",
        "guttering",
        "downpipe",
        "fascia",
        "soffit",
        "casement",
        "purlin",
        "joist",
        "rafter",
        "ridge",
        "valley",
        "verge",
        "eaves",
        "hip",
        "gable",
        "parapet",
        "lintel",
        "cavity",
        "chimney",
        "stack",
        "flaunching",
        "pointing",
        "rendering",
        "screed",
        "joinery",
        "dpc",
        "vent",
        "airbrick",
        "elecsa",
        "niceic",
        "hetas",
        "epc",
        "uprn",
    }
)

PROPTECH_SAFE_WHITELIST: frozenset[str] = (
    _SPATIAL_TERMS
    | _MATERIAL_TERMS
    | _STATUS_TERMS
    | _COMPLIANCE_TERMS
    | _EXTRA_STRUCTURAL_TERMS
)

# Individual tokens drawn from every whitelist phrase, so multi-word spans built
# entirely from safe tokens ("front elevation", "left landing", "ground floor
# void") are also intercepted even when the exact phrase is not enumerated.
_WHITELIST_TOKENS: frozenset[str] = frozenset(
    tok
    for entry in PROPTECH_SAFE_WHITELIST
    for tok in re.split(r"[^a-z0-9]+", entry)
    if tok
)

_WS_RE = re.compile(r"\s+")
_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+")


def _normalize_candidate(text: str) -> str:
    """Lower-case, trim, and collapse internal whitespace for lookup."""
    return _WS_RE.sub(" ", (text or "").strip().lower())


def _is_survey_vocabulary(text: str) -> bool:
    """True when surface text is RICS survey jargon, not PII."""
    return _whitelist_reason(text) is not None


def _whitelist_reason(text: str) -> str | None:
    """Return why ``text`` is survey-safe vocabulary, or ``None`` if not whitelisted."""
    norm = _normalize_candidate(text)
    if not norm:
        return None
    if norm in PROPTECH_SAFE_WHITELIST:
        return "exact_phrase"
    stripped = norm.strip(" .,:;!?\"'()[]{}-/")
    if stripped and stripped != norm and stripped in PROPTECH_SAFE_WHITELIST:
        return "stripped_punctuation"
    tokens = [t for t in _TOKEN_SPLIT_RE.split(stripped or norm) if t]
    if tokens and all(t in _WHITELIST_TOKENS for t in tokens):
        return "safe_token_composition"
    return None


def export_whitelist_catalog() -> dict:
    """Machine-readable export of every survey term excluded from NER redaction."""
    return {
        "description": (
            "RICS / proptech vocabulary excluded from spaCy PERSON redaction. "
            "Regex detectors (postcode, email, phone, address, etc.) are unaffected."
        ),
        "categories": {
            "spatial": sorted(_SPATIAL_TERMS),
            "materials": sorted(_MATERIAL_TERMS),
            "status": sorted(_STATUS_TERMS),
            "compliance": sorted(_COMPLIANCE_TERMS),
            "structural": sorted(_EXTRA_STRUCTURAL_TERMS),
        },
        "all_phrases": sorted(PROPTECH_SAFE_WHITELIST),
        "all_tokens": sorted(_WHITELIST_TOKENS),
        "phrase_count": len(PROPTECH_SAFE_WHITELIST),
        "token_count": len(_WHITELIST_TOKENS),
    }


# ── Pass 1a: regex detectors (rigid, high-confidence identifiers) ─────────────
# Each entry: (pii_type, compiled_regex, placeholder). All boundary-anchored so
# they never swallow adjacent words or formatting.
_POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_PHONE_RE = re.compile(
    r"\b(?:\+44\s?|0)(?:\d[\s-]?){9,12}\b|\b\d{3,4}[\s-]\d{3,4}[\s-]\d{3,4}\b"
)
_ADDRESS_RE = re.compile(
    # House number (optional letter suffix, e.g. 12A) + 1–7 name words + a street
    # type. The street-type list is deliberately limited to clearly-thoroughfare
    # words: tokens that double as survey vocabulary after a number (House, Park,
    # Hill, Green, View, Mount) are intentionally excluded to avoid over-redaction.
    r"\b(\d{1,4}[A-Za-z]?\s+[A-Za-z][A-Za-z'\-]*(?:\s+[A-Za-z][A-Za-z'\-]*){0,6}\s+"
    r"(?:Road|Rd|Street|St|Avenue|Ave|Lane|Ln|Drive|Dr|Crescent|Cres|Close|Cl|"
    r"Place|Pl|Way|Gardens|Gdns|Court|Ct|Terrace|Terr|Mews|Row|Square|Sq|Grove|"
    r"Walk|Parade|Pde|Boulevard|Blvd|Croft|Quay|Wharf|Broadway|Circus|Vale|Rise))\b",
    re.IGNORECASE,
)
# "PO Box 4521" / "P.O. Box 4521" — postal box identifiers.
_PO_BOX_RE = re.compile(r"\bP\.?\s?O\.?\s?Box\s+\d+\b", re.IGNORECASE)
# Titled personal names ("Mr John Smith", "Dr. Patel"). A deterministic backstop
# for the spaCy PERSON pass: the title is matched case-insensitively, but the
# name token(s) must be Capitalised, so ordinary lower-case prose is never hit.
_PERSON_TITLE_RE = re.compile(
    r"\b(?i:Mr|Mrs|Ms|Miss|Mx|Dr|Prof|Professor|Sir|Dame|Lord|Lady)\.?\s+"
    r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\b"
)
_MONEY_RE = re.compile(
    r"(£\s*\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\s*(?:gbp|pounds)\b)",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s+"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{2,4})\b",
    re.IGNORECASE,
)
_WRITTEN_DATE_RE = re.compile(
    r"\b\d{1,2}(?:st|nd|rd|th)?\s+"
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{4}\b",
    re.IGNORECASE,
)
# UK National Insurance number: two prefix letters, six digits, one suffix letter.
_NINO_RE = re.compile(
    r"\b[A-CEGHJ-PR-TW-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b", re.IGNORECASE
)
# Land Registry title number: 1–3 district letters + 5–6 digits (e.g. SGL123456).
_TITLE_NUMBER_RE = re.compile(r"\b[A-Z]{1,3}\d{5,6}\b")
# Dotted/slashed reference codes (e.g. NCS-100147, 22/AB/ELECSA). A real code is
# UPPER-CASE alphanumeric with a separator AND contains at least one digit. The
# digit + upper-case requirement is deliberate: without it (and with IGNORECASE)
# this pattern matched ordinary hyphenated British survey vocabulary
# ("well-maintained", "south-facing", "single-storey", "load-bearing"), shredding
# legitimate report prose. Reference identifiers are not lower-case words.
_REF_ID_RE = re.compile(r"\b(?=[A-Z0-9\-/]*\d)[A-Z0-9]+(?:[\-/][A-Z0-9]+)+\b")
# UPRN / long account or certificate numbers.
_LONG_NUMBER_RE = re.compile(r"\b\d{6,}\b")
_US_ZIP_RE = re.compile(r"\b\d{5}(?:-\d{4})?\b")

# Ordered so longer / higher-confidence matches resolve first.
_REGEX_DETECTORS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("EMAIL", _EMAIL_RE, "[REDACTED_EMAIL]"),
    ("URL", _URL_RE, "[REDACTED_URL]"),
    ("PERSON", _PERSON_TITLE_RE, "[REDACTED_NAME]"),
    ("PHONE", _PHONE_RE, "[REDACTED_PHONE]"),
    ("ADDRESS", _ADDRESS_RE, "[REDACTED_ADDRESS]"),
    ("ADDRESS", _PO_BOX_RE, "[REDACTED_ADDRESS]"),
    ("POSTCODE", _POSTCODE_RE, "[REDACTED_POSTCODE]"),
    ("POSTCODE", _US_ZIP_RE, "[REDACTED_POSTCODE]"),
    ("MONEY", _MONEY_RE, "[REDACTED_AMOUNT]"),
    ("DATE", _WRITTEN_DATE_RE, "[REDACTED_DATE]"),
    ("DATE", _DATE_RE, "[REDACTED_DATE]"),
    ("REFERENCE", _NINO_RE, "[REDACTED_REF]"),
    ("REFERENCE", _REF_ID_RE, "[REDACTED_REF]"),
    ("REFERENCE", _TITLE_NUMBER_RE, "[REDACTED_REF]"),
    ("REFERENCE", _LONG_NUMBER_RE, "[REDACTED_REF]"),
)

# Detectors that, if present, mean text MUST NOT pass an assert_no_pii gate.
# The gate targets PROPERTY-IDENTIFYING data: a real address/postcode in a master
# paragraph means it is a completed report, not boilerplate. A firm's own
# phone/email and generic money/date/reference values are legitimate template
# content (still scrubbed from references/notes, but they do not fail the gate).
_HARD_PII_TYPES = frozenset({"ADDRESS", "POSTCODE"})

# After scrubbing a past-report (REFERENCE) chunk, none of these may remain
# stored or returned to the mapping LLM — prevents cross-property data leakage.
# Place/org NER labels are deliberately excluded: the regex layer owns the
# property-identifying patterns (address/postcode), and statistical place/org
# tags are the primary source of entity bleed. REFERENCE covers NINO, Land
# Registry title numbers, file refs, and UPRN-style long numeric IDs.
_REFERENCE_LEAK_TYPES = frozenset(
    {
        "EMAIL",
        "PHONE",
        "ADDRESS",
        "POSTCODE",
        "URL",
        "PERSON",
        "REFERENCE",
    }
)

_REGEX_PII_TYPES = frozenset(pii_type for pii_type, _, _ in _REGEX_DETECTORS)

# ── Pass 1b: spaCy NER, restricted to human context only ──────────────────────
_SPACY_PII_LABELS = frozenset({"PERSON"})
_SPACY_PLACEHOLDERS = {"PERSON": "[REDACTED_NAME]"}


@dataclass
class Span:
    start: int
    end: int
    pii_type: str
    placeholder: str


@dataclass
class ScrubResult:
    text: str
    audit: dict[str, int] = field(default_factory=dict)
    whitelisted: list[dict[str, str]] = field(default_factory=list)
    redactions: list[dict] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(self.audit.values())


@dataclass
class ScrubSession:
    """Run-scoped value→token map giving referential integrity within one file.

    Pass a single session through every chunk of a document so the same name,
    address or reference is masked to the *same* token everywhere, while
    distinct values stay distinguishable (``[REDACTED_NAME_1]`` vs ``_2``).
    Tokens stay regex-safe so subsequent scrub/detect passes never re-flag them.
    """

    _tokens: dict[tuple[str, str], str] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=dict)

    def token_for(self, pii_type: str, value: str, base_placeholder: str) -> str:
        key = (pii_type, _normalize_candidate(value))
        existing = self._tokens.get(key)
        if existing is not None:
            return existing
        n = self._counters.get(pii_type, 0) + 1
        self._counters[pii_type] = n
        token = (
            f"{base_placeholder[:-1]}_{n}]"
            if base_placeholder.endswith("]")
            else f"{base_placeholder}_{n}"
        )
        self._tokens[key] = token
        return token


_nlp = None
_nlp_loaded = False


def _get_nlp():
    """Lazily load the spaCy pipeline. Returns ``None`` if unavailable."""
    global _nlp, _nlp_loaded
    if _nlp_loaded:
        return _nlp
    _nlp_loaded = True
    if not settings.pii_use_spacy:
        return None
    try:
        import spacy
    except ImportError:
        logger.warning("spaCy not installed; PII scrubber using regex layer only.")
        return None

    # Try the configured model, then progressively smaller English pipelines.
    # Robust across deploys: trf (best NER) → md → sm (always-installed floor).
    # Duplicates are removed so the configured model is never retried.
    _seen: set[str] = set()
    candidates = [
        m
        for m in (
            settings.spacy_model,
            "en_core_web_sm",
            "en_core_web_md",
            "en_core_web_trf",
        )
        if m and not (m in _seen or _seen.add(m))
    ]

    for model_name in candidates:
        try:
            _nlp = spacy.load(model_name)
            logger.info("PII scrubber loaded spaCy model %s", model_name)
            return _nlp
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "spaCy model %s unavailable (%s); trying next fallback.",
                model_name,
                exc,
            )
    logger.warning(
        "No spaCy model available (tried %s); PII scrubber using regex layer only.",
        ", ".join(candidates),
    )
    _nlp = None
    return _nlp


def reset_nlp_cache() -> None:
    """Reset the cached spaCy pipeline (tests / config reloads)."""
    global _nlp, _nlp_loaded
    _nlp = None
    _nlp_loaded = False


def _regex_spans(text: str) -> list[Span]:
    spans: list[Span] = []
    for pii_type, rx, placeholder in _REGEX_DETECTORS:
        for m in rx.finditer(text):
            spans.append(Span(m.start(), m.end(), pii_type, placeholder))
    return spans


def _record_whitelist(
    out: list[dict[str, str]],
    *,
    surface: str,
    reason: str,
    ner_label: str = "",
) -> None:
    out.append(
        {
            "surface": surface,
            "reason": reason,
            "ner_label": ner_label,
            "action": "kept",
        }
    )


def _spacy_spans(
    text: str, *, whitelisted: list[dict[str, str]] | None = None
) -> list[Span]:
    nlp = _get_nlp()
    if nlp is None:
        return []
    try:
        doc = nlp(text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("spaCy NER failed (%s); skipping NER pass.", exc)
        return []
    spans: list[Span] = []
    for ent in doc.ents:
        if ent.label_ not in _SPACY_PII_LABELS:
            continue
        surface = text[ent.start_char : ent.end_char]
        reason = _whitelist_reason(surface)
        if reason is not None:
            if whitelisted is not None:
                _record_whitelist(
                    whitelisted,
                    surface=surface,
                    reason=reason,
                    ner_label=ent.label_,
                )
            continue
        spans.append(
            Span(
                ent.start_char,
                ent.end_char,
                ent.label_,
                _SPACY_PLACEHOLDERS.get(ent.label_, "[REDACTED]"),
            )
        )
    return spans


def _resolve_overlaps(spans: list[Span]) -> list[Span]:
    """Keep non-overlapping spans, preferring earlier start then longer length."""
    ordered = sorted(spans, key=lambda s: (s.start, -(s.end - s.start)))
    chosen: list[Span] = []
    last_end = -1
    for s in ordered:
        if s.start >= last_end:
            chosen.append(s)
            last_end = s.end
    return chosen


def _candidate_spans(
    text: str,
    *,
    whitelisted: list[dict[str, str]] | None = None,
) -> list[Span]:
    """Regex + NER (survey vocabulary excluded at NER) → overlap resolution."""
    raw = text or ""
    if not raw.strip():
        return []
    return _resolve_overlaps(
        _regex_spans(raw) + _spacy_spans(raw, whitelisted=whitelisted)
    )


def _placeholder_for(span: Span, value: str, session: ScrubSession | None) -> str:
    if session is None:
        return span.placeholder
    return session.token_for(span.pii_type, value, span.placeholder)


def scrub(text: str, *, session: ScrubSession | None = None) -> ScrubResult:
    """Scrub free text, returning cleaned text plus a type→count audit map.

    Pass a :class:`ScrubSession` to keep value→token mapping stable across calls
    (referential integrity within a single file-processing run).

    ``whitelisted`` / ``redactions`` on the result list every NER span kept by the
    survey vocabulary and every span replaced (regex or NER), for structured audit.
    """
    if not settings.pii_scrubbing_enabled:
        # Whole PII layer disabled via PII_SCRUBBING_ENABLED=false. Return the text
        # verbatim (no redaction, no whitespace normalisation) so the un-redacted
        # content flows through for an effectiveness review.
        return ScrubResult(text=text or "", audit={})
    raw = text or ""
    if not raw.strip():
        return ScrubResult(text="", audit={})

    whitelisted: list[dict[str, str]] = []
    redactions: list[dict] = []
    spans = _candidate_spans(raw, whitelisted=whitelisted)
    audit: dict[str, int] = {}
    cleaned = raw
    ctx = 48
    for s in sorted(spans, key=lambda s: s.start, reverse=True):
        surface = raw[s.start : s.end]
        placeholder = _placeholder_for(s, surface, session)
        cleaned = cleaned[: s.start] + placeholder + cleaned[s.end :]
        audit[s.pii_type] = audit.get(s.pii_type, 0) + 1
        source = "regex" if s.pii_type in _REGEX_PII_TYPES else "ner"
        redactions.append(
            {
                "surface": surface,
                "type": s.pii_type,
                "placeholder": placeholder,
                "source": source,
                "action": "redacted",
                # Char offsets in the ORIGINAL (pre-redaction) text of this pass,
                # so an auditor can locate exactly where the value sat.
                "char_start": s.start,
                "char_end": s.end,
                "context_before": raw[max(0, s.start - ctx) : s.start],
                "context_after": raw[s.end : s.end + ctx],
            }
        )

    # Present redactions in reading order (spans were applied back-to-front).
    redactions.sort(key=lambda r: r["char_start"])

    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    if audit:
        logger.info("PII scrub redacted %d spans: %s", sum(audit.values()), audit)
    return ScrubResult(
        text=cleaned,
        audit=audit,
        whitelisted=whitelisted,
        redactions=redactions,
    )


def _merge_audit(*audits: dict[str, int]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for a in audits:
        for k, v in a.items():
            merged[k] = merged.get(k, 0) + v
    return merged


def _merge_records(*groups: list[dict]) -> list[dict]:
    out: list[dict] = []
    for group in groups:
        out.extend(group)
    return out


@dataclass
class ReferenceScrubOutcome:
    """Result of scrubbing a REFERENCE chunk, including audit detail when dropped."""

    result: ScrubResult | None
    dropped: bool = False
    residual_leaks: dict[str, int] = field(default_factory=dict)
    whitelisted: list[dict[str, str]] = field(default_factory=list)
    redactions: list[dict] = field(default_factory=list)
    audit: dict[str, int] = field(default_factory=dict)
    # Scrubbed text even when the chunk is dropped, so the audit can show what the
    # redacted content looked like before rejection.
    cleaned_text: str = ""


def scrub_reference_for_ingest(
    text: str, *, session: ScrubSession | None = None
) -> ReferenceScrubOutcome:
    """Scrub a past-report chunk for REFERENCE tier storage.

    Runs two scrub passes, then drops the chunk if property-identifying PII would
    still leak into another report's generation context. Returns
    :class:`ReferenceScrubOutcome` with whitelist/redaction detail even when
    ``result`` is ``None`` (chunk unsafe to index).
    """
    raw = text or ""
    if not raw.strip():
        return ReferenceScrubOutcome(result=None, dropped=True)

    first = scrub(raw, session=session)
    second = scrub(first.text, session=session)
    for r in first.redactions:
        r["pass"] = 1
    for r in second.redactions:
        r["pass"] = 2
    cleaned = second.text
    audit = _merge_audit(first.audit, second.audit)
    whitelisted = _merge_records(first.whitelisted, second.whitelisted)
    redactions = _merge_records(first.redactions, second.redactions)

    residual = detect_pii(cleaned)
    leaks = {k: v for k, v in residual.items() if k in _REFERENCE_LEAK_TYPES}
    if leaks:
        logger.warning(
            "REFERENCE chunk unsafe after scrub (dropping): %s",
            ", ".join(f"{k}={v}" for k, v in sorted(leaks.items())),
        )
        return ReferenceScrubOutcome(
            result=None,
            dropped=True,
            residual_leaks=leaks,
            whitelisted=whitelisted,
            redactions=redactions,
            audit=audit,
            cleaned_text=cleaned,
        )

    return ReferenceScrubOutcome(
        result=ScrubResult(
            text=cleaned,
            audit=audit,
            whitelisted=whitelisted,
            redactions=redactions,
        ),
        dropped=False,
        whitelisted=whitelisted,
        redactions=redactions,
        audit=audit,
        cleaned_text=cleaned,
    )


def scrub_rag_chunk(text: str, *, session: ScrubSession | None = None) -> str:
    """Scrub a REFERENCE RAG chunk; returns empty string if chunk must be dropped."""
    outcome = scrub_reference_for_ingest(text, session=session)
    return outcome.result.text if outcome.result else ""


def sanitize_for_generation_context(text: str) -> str:
    """Last-line scrub on any paragraph about to enter the mapping LLM."""
    cleaned = scrub(text or "").text
    residual = detect_pii(cleaned)
    leaks = {k: v for k, v in residual.items() if k in _REFERENCE_LEAK_TYPES}
    if leaks:
        logger.warning(
            "Sanitizing paragraph before generation (residual PII: %s)",
            leaks,
        )
        cleaned = scrub(cleaned).text
    return cleaned


def detect_pii(text: str) -> dict[str, int]:
    """Return a type→count map of detected PII spans."""
    if not settings.pii_scrubbing_enabled:
        # Disabled: report nothing detected so sanitisation, residual-leak drops,
        # and every assert_no_pii gate become no-ops.
        return {}
    audit: dict[str, int] = {}
    for s in _candidate_spans(text or ""):
        audit[s.pii_type] = audit.get(s.pii_type, 0) + 1
    return audit


def assert_no_pii(text: str, *, context: str = "document") -> None:
    """Raise :class:`PiiDetectedError` if high-confidence PII is present.

    Used as a hard gate on the operator master template (which must be
    property-agnostic boilerplate) and on final report output before DOCX export.
    """
    if not settings.pii_scrubbing_enabled:
        # Disabled: skip the hard gate entirely (no DOCX / master-template block).
        return
    audit = detect_pii(text)
    hard = {k: v for k, v in audit.items() if k in _HARD_PII_TYPES}
    if hard:
        raise PiiDetectedError(
            f"PII detected in {context}: "
            + ", ".join(f"{k}={v}" for k, v in sorted(hard.items()))
        )
