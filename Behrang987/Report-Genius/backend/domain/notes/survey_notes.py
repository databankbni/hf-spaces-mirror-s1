"""Structured extraction of surveyor field notes (Fix 3).

Converts a raw notes string into a :class:`SurveyNotes` object: property
identity, section-mapped findings, cost estimates and special-risk flags. This
is an *additive* layer — it does not replace the existing note→section routing
in :mod:`backend.domain.notes.parser`; it enriches the pipeline with a
``property_context`` (consumed by the property-type retrieval guard) and makes
raw findings available for notes-first fallbacks.

Pure functions only — no LLM, no network, no embeddings.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_WORD_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

_BOILER_BRANDS = (
    "viessmann",
    "worcester",
    "vaillant",
    "baxi",
    "ideal",
    "glow-worm",
    "glow worm",
    "potterton",
    "alpha",
    "ferroli",
    "intergas",
    "vokera",
)

_TREE_SPECIES = (
    "london plane",
    "plane",
    "oak",
    "willow",
    "cypress",
    "leylandii",
    "ash",
    "beech",
    "birch",
    "sycamore",
    "horse chestnut",
    "poplar",
    "lime",
    "magnolia",
    "conifer",
    "eucalyptus",
)

_PROPERTY_TYPE_HINTS = (
    "mid-terraced",
    "end-terraced",
    "end of terrace",
    "end-of-terrace",
    "terraced",
    "semi-detached",
    "detached",
    "townhouse",
    "town house",
    "maisonette",
    "apartment",
    "flat",
    "bungalow",
    "cottage",
)

_ERA_HINTS = (
    "victorian",
    "edwardian",
    "georgian",
    "interwar",
    "inter-war",
    "post-war",
    "modern",
    "new build",
    "1930s",
    "1960s",
)


@dataclass
class SurveyNotes:
    # Property identity
    property_type: str = ""  # "mid-terraced Victorian townhouse"
    construction_year: int | None = None
    storeys: int | None = None
    tenure: str = ""
    is_conservation_area: bool = False
    flood_zone: str = ""
    epc_band: str = ""
    epc_score: int | None = None

    # Section-mapped findings (keyed by RICS section code)
    section_findings: dict[str, list[str]] = field(default_factory=dict)

    # Cost estimates
    cost_estimates: dict[str, tuple[int, int]] = field(default_factory=dict)
    cost_total_essential: tuple[int, int] = (0, 0)
    cost_total_with_insulation: tuple[int, int] = (0, 0)

    # Special flags
    has_asbestos: bool = False
    asbestos_location: str = ""
    has_structural_crack: bool = False
    crack_description: str = ""
    tree_species: str = ""
    tree_distance_m: float = 0.0


# ── Field regexes (module level) ─────────────────────────────────────────────
_RE_YEAR = re.compile(r"\b(1[6-9]\d{2}|20[0-2]\d)\b")
_RE_BUILT_YEAR = re.compile(
    r"(?:built|constructed|circa|c\.?|dating from|erected)\s*(?:in\s*)?(1[6-9]\d{2}|20[0-2]\d)",
    re.IGNORECASE,
)
_RE_STOREYS_DIGIT = re.compile(
    r"\b(\d{1,2})\s*[-\s]?(?:storey|story|stories|storeys|floors?)\b", re.IGNORECASE
)
_RE_STOREYS_WORD = re.compile(
    r"\b(" + "|".join(_WORD_NUMBERS) + r")[-\s]?(?:storey|story|stories|storeys)\b",
    re.IGNORECASE,
)
_RE_FREEHOLD = re.compile(
    r"\b(share of freehold|freehold|leasehold|commonhold)\b", re.IGNORECASE
)
_RE_CONSERVATION = re.compile(r"conservation area", re.IGNORECASE)
_RE_CONSERVATION_NEG = re.compile(
    r"(?:not|isn't|is not|outside)[^.\n]{0,40}conservation area", re.IGNORECASE
)
_RE_FLOOD_ZONE = re.compile(r"flood\s*zone\s*([0-9a-z]+)", re.IGNORECASE)
_RE_EPC_BAND = re.compile(r"\bEPC\b[^.\n]{0,30}?\b([A-G])\b", re.IGNORECASE)
_RE_EPC_SCORE = re.compile(r"\bEPC\b[^.\n]{0,40}?\b(\d{1,3})\b", re.IGNORECASE)
_RE_RADIATORS = re.compile(r"\b(\d{1,3})\s*radiators?\b", re.IGNORECASE)
_RE_CYLINDER = re.compile(r"\b(\d{2,4})\s*(?:l|litre|liter|ltr)\b", re.IGNORECASE)
_RE_CRACK_MM = re.compile(r"(\d+(?:\.\d+)?)\s*mm", re.IGNORECASE)
_RE_DISTANCE_M = re.compile(r"(\d+(?:\.\d+)?)\s*m(?:etre|eter)?s?\b", re.IGNORECASE)
_RE_COST_RANGE = re.compile(
    r"£\s?([\d,]+)\s*(k)?\s*(?:[-–—]|to)\s*£?\s?([\d,]+)\s*(k)?",
    re.IGNORECASE,
)


def _money_to_int(value: str, has_k: bool) -> int:
    n = int(value.replace(",", "").strip() or "0")
    return n * 1000 if has_k else n


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if p and p.strip()]


def _first(pattern: re.Pattern[str], text: str) -> str | None:
    m = pattern.search(text)
    return m.group(1) if m else None


def _extract_property_type(text: str) -> str:
    lowered = text.lower()
    type_hit = next((h for h in _PROPERTY_TYPE_HINTS if h in lowered), "")
    era_hit = next((h for h in _ERA_HINTS if h in lowered), "")
    pieces = [p for p in (era_hit, type_hit) if p]
    return " ".join(pieces).strip()


def _extract_costs(
    text: str,
) -> tuple[dict[str, tuple[int, int]], tuple[int, int], tuple[int, int]]:
    estimates: dict[str, tuple[int, int]] = {}
    total_essential = (0, 0)
    total_insulation = (0, 0)
    for sentence in _split_sentences(text):
        m = _RE_COST_RANGE.search(sentence)
        if not m:
            continue
        low = _money_to_int(m.group(1), bool(m.group(2)))
        high = _money_to_int(m.group(3), bool(m.group(4)))
        rng = (min(low, high), max(low, high))
        low_sentence = sentence.lower()
        if "total" in low_sentence and (
            "insulation" in low_sentence or "with" in low_sentence
        ):
            total_insulation = rng
            continue
        if "total" in low_sentence:
            total_essential = rng
            continue
        # Key the estimate by a nearby subject noun (first content word before '£').
        prefix = sentence[: m.start()]
        words = re.findall(r"[A-Za-z]{4,}", prefix.lower())
        key = words[-1] if words else f"item_{len(estimates) + 1}"
        estimates[key] = rng
    return estimates, total_essential, total_insulation


def _extract_flags(notes: SurveyNotes, text: str) -> None:
    for sentence in _split_sentences(text):
        low = sentence.lower()
        if "asbestos" in low and not notes.has_asbestos:
            notes.has_asbestos = True
            notes.asbestos_location = sentence
        if "crack" in low and not notes.has_structural_crack:
            mm = _RE_CRACK_MM.search(sentence)
            if mm or any(
                w in low for w in ("structural", "diagonal", "stepped", "subsidence")
            ):
                notes.has_structural_crack = True
                notes.crack_description = sentence
        if not notes.tree_species:
            species = next((s for s in _TREE_SPECIES if s in low), "")
            if species and ("tree" in low or "m " in low or "metre" in low):
                notes.tree_species = species
                dist = _RE_DISTANCE_M.search(sentence)
                if dist:
                    try:
                        notes.tree_distance_m = float(dist.group(1))
                    except ValueError:
                        pass


def _map_section_findings(text: str) -> dict[str, list[str]]:
    """Route each note line to a section code via the existing cascade classifier."""
    from backend.domain.notes.keyword_router import classify_note_cascade
    from backend.domain.notes.parser import UNASSIGNED, _iter_note_lines

    findings: dict[str, list[str]] = {}
    for line in _iter_note_lines(text):
        section_id, _score, obs = classify_note_cascade(line)
        if section_id == UNASSIGNED:
            continue
        findings.setdefault(section_id.upper(), []).append((obs or line).strip())
    return findings


def parse_notes(raw_notes: str) -> SurveyNotes:
    """Extract a structured :class:`SurveyNotes` object from raw field-note text."""
    notes = SurveyNotes()
    text = (raw_notes or "").replace("\r\n", "\n")
    if not text.strip():
        return notes

    notes.property_type = _extract_property_type(text)

    year = _first(_RE_BUILT_YEAR, text) or _first(_RE_YEAR, text)
    if year:
        notes.construction_year = int(year)

    storey_digit = _first(_RE_STOREYS_DIGIT, text)
    if storey_digit:
        notes.storeys = int(storey_digit)
    else:
        storey_word = _first(_RE_STOREYS_WORD, text)
        if storey_word:
            notes.storeys = _WORD_NUMBERS.get(storey_word.lower())

    tenure = _first(_RE_FREEHOLD, text)
    if tenure:
        notes.tenure = tenure.lower()

    notes.is_conservation_area = bool(
        _RE_CONSERVATION.search(text) and not _RE_CONSERVATION_NEG.search(text)
    )

    flood = _first(_RE_FLOOD_ZONE, text)
    if flood:
        notes.flood_zone = f"Zone {flood.upper()}"

    band = _first(_RE_EPC_BAND, text)
    if band:
        notes.epc_band = band.upper()
    score = _first(_RE_EPC_SCORE, text)
    if score:
        notes.epc_score = int(score)

    (
        notes.cost_estimates,
        notes.cost_total_essential,
        notes.cost_total_with_insulation,
    ) = _extract_costs(text)
    _extract_flags(notes, text)
    notes.section_findings = _map_section_findings(text)
    return notes


def build_property_context(
    notes: SurveyNotes,
    *,
    property_type: str = "",
    tenure: str = "",
) -> dict:
    """Merge parsed notes with explicit session values into a retrieval context.

    Explicit (UI/session) ``property_type``/``tenure`` take precedence over the
    values inferred from the notes.
    """
    return {
        "property_type": (property_type or notes.property_type or "").strip(),
        "tenure": (tenure or notes.tenure or "").strip(),
        "construction_year": notes.construction_year,
        "storeys": notes.storeys,
        "is_conservation_area": notes.is_conservation_area,
        "flood_zone": notes.flood_zone,
        "epc_band": notes.epc_band,
        "has_asbestos": notes.has_asbestos,
        "has_structural_crack": notes.has_structural_crack,
    }
