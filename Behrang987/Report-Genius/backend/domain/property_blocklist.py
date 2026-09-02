"""Property-type terminology helpers (retrieval no longer drops on these).

Historically this module rejected past-report paragraphs whose flat/house
terminology clashed with the current survey's property type. That caused
empty retrievals (and single-source baselines when two reports were uploaded).
Foreign terminology is now left for anti-bleed reduction + the grounding
auditor; every uploaded source that holds the subsection is kept.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# category -> terms that are INCOMPATIBLE with that category (lower-case).
# Retained for diagnostics / future tooling; not applied at retrieval time.
PROPERTY_TYPE_BLOCKLIST: dict[str, list[str]] = {
    # A house must not contain flat/apartment-only terminology.
    "house": [
        "communal",
        "common area",
        "common parts",
        "managing agent",
        "management company",
        "flat entrance",
        "leaseholder",
        "leasehold",
        "service charge",
        "peep",
        "personal emergency evacuation",
        "stay put",
        "simultaneous evacuation",
        "communal stair",
        "block of flats",
        "apartment block",
        "shared entrance",
    ],
    # Mid-terraced houses additionally cannot have detached/front-drive features.
    "terraced": [
        "front driveway",
        "front drive",
        "retaining wall to front",
        "retaining walls to the front",
        "integral garage",
        "detached garage",
    ],
    # A flat must not claim standalone-house features.
    "flat": [
        "integral garage",
        "own front driveway",
        "rear garden boundary fence",
    ],
}


def categories_for(property_context: dict | None) -> set[str]:
    """Resolve a property_context into applicable blocklist categories."""
    if not property_context:
        return set()
    ptype = str(property_context.get("property_type") or "").lower()
    if not ptype:
        return set()
    cats: set[str] = set()
    if any(w in ptype for w in ("flat", "apartment", "maisonette")):
        cats.add("flat")
        return cats  # a flat is never also a house
    if any(w in ptype for w in ("terrace", "townhouse", "town house")):
        cats.update({"house", "terraced"})
    if any(
        w in ptype
        for w in ("semi", "detached", "bungalow", "cottage", "house", "dwelling")
    ):
        cats.add("house")
    return cats


def is_paragraph_compatible(paragraph: str, property_context: dict | None) -> bool:
    """Always ``True`` — retrieval no longer rejects on property terminology."""
    _ = (paragraph, property_context)
    return True


# Spec-named private alias.
_is_paragraph_compatible = is_paragraph_compatible


def filter_hits_by_property(hits: list, property_context: dict | None) -> list:
    """Pass-through: never drop retrieved hits on property-type terminology.

    Past-report sections must reach the mapping prompt for every uploaded
    source that holds the subsection. Foreign flat/house wording is handled
    downstream (anti-bleed + auditor), not by deleting the baseline.
    """
    _ = property_context
    return hits
