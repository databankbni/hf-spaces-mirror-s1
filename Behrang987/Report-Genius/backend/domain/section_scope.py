"""Product-scope rules for RICS L3 sections.

Real L3 reports carry leaf subsection codes (``D1``…``J5``) for parents D–J,
plus a parent-intro mapping unit (``D``…``J``) for the preamble before the first
leaf. Parents A, B, C, K, L, M and N are single parent-level product units
(no A1/C1/… UI or DOCX keys). Surveyor notes drive D–J parent intros and all
D–J leaves; A/B/C/K/L/M/N stay scaffold / manual.
"""

from __future__ import annotations

import re

# Parents whose leaf subsections receive surveyor messy notes (note → prose mapping).
NOTES_PARENT_IDS = frozenset({"D", "E", "F", "G", "H", "I", "J"})

# Parents stored/retrieved at LEAF level (real leaf codes exist in live PDFs).
# Each also has a parent-intro mapping unit (``D``…``J``) that accepts notes.
LEAF_STORAGE_PARENT_IDS = NOTES_PARENT_IDS
PARENT_INTRO_SECTION_IDS = LEAF_STORAGE_PARENT_IDS

# Parents stored/retrieved at PARENT level (no leaf codes in live reports).
PARENT_STORAGE_PARENT_IDS = frozenset({"A", "B", "C", "K", "L", "M", "N"})

# Official RICS form prose headings that appear under parent C instead of
# numeric leaf codes. All of them map to parent ``C`` at ingest.
C_PROSE_HEADINGS: tuple[str, ...] = (
    "Type of property",
    "Approximate year of construction",
    "Approximate year of extension",
    "Approximate year of conversion",
    "Information relevant to flats and maisonettes",
    "Construction",
    "Accommodation",
    "Means of escape",
    "Energy",
    "Energy efficiency",
    "Mains services",
    "Central heating",
    "Other services or energy sources",
    "Grounds",
    "Location",
    "Facilities",
    "Local environment",
)

# Canonical parent titles (lowercased, punctuation-folded) -> letter.
# Prefer distinctive titles only — short labels like "Grounds" / "Services" /
# "Risks" also appear as C-form prose headings and must not trigger a parent cut.
PARENT_TITLE_TO_LETTER: dict[str, str] = {
    "about the inspection": "A",
    # Literal heading text as printed in the RICS L3 form.
    "overall opinion and summary of the condition ratings": "B",  # rics-literal-ok
    # LlamaParse emits B as ``Section B icon`` + ``# Overall opinion`` (no
    # ``B <title>`` banner), so the bare section titles must also resolve to B or
    # B is swallowed into A. These are B-only headings in the RICS L3 form.
    "overall opinion": "B",
    "overall opinion of property": "B",
    "about the property": "C",
    "outside the property": "D",
    "inside the property": "E",
    "services": "F",
    "grounds": "G",
    "grounds (including shared areas for flats)": "G",
    "issues for your legal advisers": "H",
    "issues for your legal advisors": "H",
    "risks": "I",
    "energy matters": "J",
    "surveyor's declaration": "K",
    "surveyors declaration": "K",
    "what to do now": "L",
    "description of the rics home survey - level 3 service and terms of engagement": "M",
    "description of the rics home survey level 3 service and terms of engagement": "M",
    "typical house diagram": "N",
}


def fold_parent_title(title: str) -> str:
    """Lowercase + strip punctuation so curly apostrophes still match."""
    cleaned = (title or "").strip().lower()
    cleaned = cleaned.replace("\u2019", "'").replace("\u2018", "'")
    cleaned = re.sub(r"[^a-z0-9\s\-()]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def parent_letter_for_title(title: str) -> str | None:
    """Return parent letter for a known RICS parent title, else None."""
    folded = fold_parent_title(title)
    if not folded:
        return None
    if folded in PARENT_TITLE_TO_LETTER:
        return PARENT_TITLE_TO_LETTER[folded]
    # Prefix match only when the input is at least as long as the key (truncated
    # long titles). Never map short C-prose labels like "Energy" -> J.
    for key, letter in PARENT_TITLE_TO_LETTER.items():
        if len(key) >= 12 and len(folded) >= len(key) and folded.startswith(key):
            return letter
    return None


def parent_letter(section_id: str) -> str:
    """Uppercase parent group letter for a leaf or parent section id."""
    return (section_id or "").strip()[:1].upper()


def section_accepts_notes(section_id: str) -> bool:
    """True when surveyor messy notes drive generation for this mapping unit.

    D–J leaves and the D–J parent-intro units (``D``, ``E``, … ``J``) accept
    notes. A/B/C/K/L/M/N stay scaffold-only / manual.
    """
    sid = (section_id or "").strip().upper()
    if sid in PARENT_INTRO_SECTION_IDS:
        return True
    return parent_letter(sid) in NOTES_PARENT_IDS


def is_parent_level_storage(section_id: str) -> bool:
    """True when this section's parent group is stored as one parent-level body."""
    return parent_letter(section_id) in PARENT_STORAGE_PARENT_IDS


def storage_section_id(section_id: str) -> str:
    """Canonical STORAGE / product id for a schema or legacy layout-hook id.

    Leaf ids under D–I/J keep their leaf code; anything under A/B/C/K/L/M/N
    collapses to the parent letter (legacy artificial leaves like ``C1`` map to
    ``C``).
    """
    sid = (section_id or "").strip().upper()
    if not sid:
        return ""
    if is_parent_level_storage(sid):
        return parent_letter(sid)
    return sid


# User-facing notes-input guidance lives in backend/prompts/notes_guidance.py
# (prompt text is exempt from the RICS-hardcode hygiene rule).
