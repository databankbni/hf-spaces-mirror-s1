"""Which evidence set a company's ``Sector``, and what a re-read may overwrite.

``companies.Sector`` was filled by four different passes with very different
evidential strength, and nothing in the schema records which one won. The only
surviving trace is ``companies.DescriptionSources`` plus membership of the
analyst-curated ``apply_sector_overrides.OVERRIDES`` map. This module turns that
into an explicit *layer*, and each layer into a *write policy* saying what a
fresh read of the company's own filed activity note is allowed to change.

Measured on the 2026-07-28 DB (9,138 companies; revenue = latest filed year):

    layer            cos     revenue   evidence that set the Sector
    manual           306    ₾27.05bn   analyst OVERRIDES map, keyed by IdCode
    recent         2,539    ₾40.73bn   the company's own filed activity note
    original-web   1,098    ₾59.45bn   1–2 web pages (384 of them a SINGLE url)
    original-xlsx    320     ₾3.11bn   GCAP "Sectors and enrichment.xlsx" import
    deterministic  1,227     ₾6.67bn   a SUBSTRING OF THE COMPANY NAME, conf 0.70
    unclassified   3,648    ₾19.48bn   nothing

The policy encodes one rule (user decision, 2026-07-28): **a usable filed
activity note replaces whatever tag is there; no usable note keeps it.** The only
exemption is the analyst layer.

That makes the layer irrelevant to *whether* a Sector may be replaced — every
non-manual layer may be. What the layer still decides is the **confidence floor**,
and that turns on one thing: whether there is an incumbent classification to
displace. Filling a blank is cheap; overwriting somebody's answer should cost more.

  * ``manual``            — untouchable. Nothing is written, ever.
  * no incumbent          — a blank Sector, or one parked in ``'Other'``. Written at
                            any confidence, because there is nothing to lose.
  * every other layer     — Sector and SubSector written at confidence >= 0.75.

``--protect-original`` restores the older, more conservative treatment of the two
web-research layers (SubSector only, and only when the note agrees on the Sector)
for anyone who wants to stage the change.

Why the exemptions and the floor are where they are:

  * ``manual``        — excluding it *up front* is the only thing that actually
                       leaves it alone. Relying on ``apply_sector_overrides.py`` to
                       re-assert the Sector on the next rebuild does not protect
                       SubSector at all, because most OVERRIDES entries pass
                       ``SubSector=None`` — so an LLM sub-sector written onto a
                       curated company survives indefinitely.
  * ``deterministic`` — the clearest case for the rule. These 1,227 sectors are a
                       substring of the company name ('ტრანს' → Logistics,
                       'აგრო' → Agriculture, 'ავტო' → Auto) scored at a flat 0.70,
                       and 652 have their own filed note sitting unread. The old
                       writer put them in a "sub-sector only" bucket whose
                       sector-agreement check *dropped* every case in which the
                       note disagreed with the keyword — preserving exactly the
                       guesses most likely to be wrong.
  * ``original-*``    — 384 of these 1,418 companies rest on a SINGLE web url, for
                       ₾62.56bn of revenue. Thin evidence, and a filed note beats
                       it. The safety here is not the layer, it is
                       :mod:`lib.note_quality`: the measured snippet quality for
                       this layer is the worst of any (19% gate rejection, and the
                       largest slices are ESG paragraphs and risk-note
                       cross-references), so the gate is what stops a bad note
                       from displacing a correct web-researched Sector.
  * ``recent``        — writable for consistency, but a near no-op in practice: the
                       stored Sector came from the same note via the same model, so
                       a re-read lands on "sector already correct". It stops being a
                       no-op only when the note itself improves — a better slice or
                       an OCR pass — which is exactly when a rewrite is wanted.
  * ``rms-nace`` /
    ``bia-directory``  — the two statistical NACE maps. Both fill blanks only, so
                       neither ever displaced anything, and both are ~85-89% right
                       by measurement — a filed note beats them at the standard
                       0.75 floor, which is why they need no special case here.
  * ``unclassified``  — everything is writable, at any confidence.

Orthogonal to all of that: ``'Other'`` is a parking space, not a classification.
A non-manual company sitting in ``'Other'`` is treated as unclassified for
Sector-write purposes regardless of which layer put it there (364 companies,
₾15.4bn — the single largest "sector" in the book).

Rejected: "clear the SubSector when the Sector moves" (measured 2026-08-10)
-------------------------------------------------------------------------
The known cost of the never-clobber rule is that an EARLIER pass's LLM-written
SubSector is not curated but is non-empty, so it counts as curated and survives a
later pass rewriting the Sector. The company then holds two halves describing two
businesses — the defect behind 68749bd, c588f2e and the 34-company block dated
2026-08-10 in ``scripts/apply_sector_overrides.py``. The obvious repair is to treat
a SubSector as stale by construction once the Sector under it changes, and clear or
re-derive it. Measured against the 34 adjudicated companies, DON'T:

    shape                                        cos   what the rule would do
    Sector right, SubSector stale                 21   correct — clears the bad half
    SubSector right, Sector wrong                  6   DESTROYS the only good half
    both halves wrong                              7   no better than today

It is not merely 6 losses against 21 wins, because of what happens to those 6. The
re-derived SubSector comes from the same pass that got the Sector wrong, so the
result is a pair that AGREES — ``Real Estate / property leasing`` for a dental
clinic (405084723), ``Oil & Gas / gas station operations`` for a landlord that
leases petrol stations out (404989241), ``Marketing / booking platform support`` for
Booking.com's support arm (405079800), ``Real Estate / recreational facility
rental`` for a campsite (405262086). Each is still wrong, and each becomes
undetectable: the sweep that finds these companies looks for a SubSector whose
dominant home is a different Sector, and a coherent pair matches nothing. The
incoherence is the only reason 34 misclassifications were findable at all.

So the mismatch is a symptom worth KEEPING as an assertion failure. The standing
detector is ``scripts/find_stale_subsectors.py``; the analyst layer is where
adjudicated answers get pinned. What would genuinely help is narrower: record which
pass wrote the SubSector, so "stale" can be decided from provenance rather than
inferred from vocabulary. Nothing in the schema does that today — the whole reason
this module has to reconstruct layers from ``DescriptionSources`` in the first place.

Pure/stdlib-only: no DB, no network, no Streamlit. Callers read the four inputs
themselves and pass them in (see ``scripts/apply_sector_from_reports.py``).
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

__all__ = [
    "MANUAL", "RECENT", "ORIGINAL_WEB", "ORIGINAL_XLSX", "RMS_NACE", "BIA",
    "DETERMINISTIC", "UNCLASSIFIED", "LAYERS",
    "PLACEHOLDER_SECTORS", "WritePolicy",
    "OVERWRITE_MIN_CONFIDENCE",
    "is_placeholder_sector", "layer_of", "manual_idcodes", "write_policy",
]

MANUAL = "manual"
RECENT = "recent"
ORIGINAL_WEB = "original-web"
ORIGINAL_XLSX = "original-xlsx"
#: Sector derived from the company's NACE-2016 division on its code-verified
#: bia.ge directory page (``bia_directory``), via a purity-gated division ->
#: sector map. Ranked below the web-research layers because it is a statistical
#: map rather than a read of this company: measured against the note-derived
#: layer, the gated map is ~85% right, so roughly one in seven is wrong. It is
#: its own layer precisely so that error rate stays measurable and the whole
#: layer stays retractable, the way the name-keyword layer had to be.
BIA = "bia-directory"
#: Sector seeded from the NACE Rev.2 codes the company declared in its OWN filing
#: (the ``nace_codes`` table, from the reportal RMS ``NACE <year>.xlsx`` bulk
#: file), via the purity-gated map in :mod:`lib.nace_sector_map`. Ranked above
#: :data:`BIA` on two measured differences — the codes are the filer's own
#: declaration rather than a third-party directory page, and the map is derived
#: from a larger reference pool (4,178 vs 2,776 companies) at a higher floor —
#: but it is still a statistical map, ~89% right leave-one-out, so roughly one in
#: nine is wrong. Its own layer for the same reason as ``bia-directory``: the
#: error rate stays measurable and the whole layer stays retractable.
RMS_NACE = "rms-nace"
DETERMINISTIC = "deterministic"
UNCLASSIFIED = "unclassified"

#: Display order — strongest evidence first, then weakest, then none.
LAYERS: tuple[str, ...] = (
    MANUAL, RECENT, ORIGINAL_WEB, ORIGINAL_XLSX, RMS_NACE, BIA, DETERMINISTIC,
    UNCLASSIFIED,
)

#: Sector values that are a parking space rather than a classification. Matched
#: case-insensitively after stripping. Keep in sync with the same list in
#: ``scripts/apply_sector_from_reports.py``'s target query.
PLACEHOLDER_SECTORS: frozenset[str] = frozenset({"other", "unknown", "n/a", "-"})

# Provenance markers written into DescriptionSources by each pass. The recent
# pass writes "sector: <model> via FY<year> annual-report activity note [date]";
# the GCAP import writes the workbook filename. Substring tests, because the
# column is a JSON array whose other entries are unrelated source urls.
_MARKER_ACTIVITY_NOTE = "activity note"
_MARKER_GCAP_XLSX = "Sectors and enrichment"
#: ``scripts/apply_bia_sectors.py`` writes
#: "sector: NACE-2016 division NN via bia.ge directory [date]". Tested BEFORE the
#: bare-url fallback, since the row also carries the bia.ge company URL and would
#: otherwise be indistinguishable from the web-research layer.
_MARKER_BIA = "bia.ge directory"
#: ``scripts/seed_sectors_from_nace.py`` writes
#: "sector: NACE Rev.2 <level> <code> via reportal RMS [date]".
#:
#: Tested FIRST — ahead of the activity-note marker — and that ordering is
#: measured, not stylistic. 108 of the 1,791 blank-Sector NACE candidates already
#: carry an activity-note marker from a note read that wrote a Description but no
#: Sector (the note was unusable, or the model abstained). Those rows read as
#: ``unclassified`` today only because rule 2 below short-circuits on the blank
#: Sector; the moment the seeder fills it, a note-marker-first order would file
#: them under ``recent`` — which is the pool ``lib.nace_sector_map`` measures
#: purity against, so the next run would be scoring the map partly against its own
#: output. Keeping this test first keeps that circularity out.
#:
#: The cost of the choice, stated plainly: if a later note read replaces an
#: RMS-seeded Sector, both markers are present and this still reports
#: ``rms-nace``. Retract with ``seed_sectors_from_nace.py --restore`` (which
#: strips the marker) rather than relying on precedence to age out.
_MARKER_RMS_NACE = "via reportal RMS"

#: ``scripts/seed_subsectors_from_bia.py`` writes
#: "subsector: bia.ge industry <label> [date]" — and is NOT tested here on
#: purpose. It only ever writes ``SubSector``, never ``Sector``, so it does not
#: define a Sector provenance layer and must not shadow one. The wording is
#: chosen so it contains none of the substrings above: not "bia.ge directory"
#: (the Sector-from-NACE layer), not "activity note", not "via reportal RMS".
#: A company seeded by it therefore keeps reporting whichever layer set its
#: Sector, which is the layer that decides what a later note read may overwrite.
_MARKER_BIA_SUBSECTOR_NOT_A_LAYER = "subsector: bia.ge industry "


def is_placeholder_sector(sector: str | None) -> bool:
    """True when ``sector`` is blank or a parking-space value (``'Other'``)."""
    if sector is None:
        return True
    s = sector.strip()
    return not s or s.casefold() in PLACEHOLDER_SECTORS


def manual_idcodes(overrides: Mapping[str, object] | Iterable[str]) -> frozenset[str]:
    """Normalise ``apply_sector_overrides.OVERRIDES`` (or any id iterable) to a set.

    Kept here so every consumer agrees on what "manual" means, while the
    dependency still points the right way: the *script* imports its own
    ``OVERRIDES`` and passes it in, rather than ``lib/`` importing ``scripts/``.
    """
    keys = overrides.keys() if isinstance(overrides, Mapping) else overrides
    return frozenset(str(k).strip() for k in keys if str(k).strip())


def layer_of(
    sector: str | None,
    sources: str | None,
    *,
    is_manual: bool,
) -> str:
    """Return which pass set this company's ``Sector``.

    ``sources`` is the raw ``companies.DescriptionSources`` cell (a JSON array
    string, or NULL). Precedence is deliberate and not merely a fallthrough:

      1. ``is_manual`` wins over everything, because ``apply_sector_overrides.py``
         runs LAST in ``rebuild_db.py`` and therefore has the final say on the
         stored value — 42 of the 306 manual companies also carry a recent-pass
         marker and 137 carry web-research urls, and in every one of those cases
         the analyst's bucket is what is actually in the column.
      2. A blank Sector is ``unclassified`` even when the row has sources: 39
         companies have an enrichment Description but no Sector.
      3. NULL sources means the deterministic classifier, which writes Sector
         without touching Description. Cross-checked: 1,213 of those 1,227 appear
         in ``docs/reviews/2026-06-18-sector-classifier-proposal.csv``.
      4. Among the marker tests, the RMS-NACE marker is checked before the
         activity-note one — see ``_MARKER_RMS_NACE`` for the measurement that
         decides it (108 rows carry a note marker but no Sector, and letting them
         land in ``recent`` would feed the NACE map back into its own reference
         pool).

    Note ``'Other'`` is NOT its own layer — it is a state that any layer can
    leave a company in. Use :func:`is_placeholder_sector` for that.
    """
    if is_manual:
        return MANUAL
    if sector is None or not sector.strip():
        return UNCLASSIFIED
    if sources is None or not str(sources).strip():
        return DETERMINISTIC
    src = str(sources)
    if _MARKER_RMS_NACE in src:
        return RMS_NACE
    if _MARKER_ACTIVITY_NOTE in src:
        return RECENT
    if _MARKER_GCAP_XLSX in src:
        return ORIGINAL_XLSX
    if _MARKER_BIA in src:
        return BIA
    return ORIGINAL_WEB


@dataclass(frozen=True)
class WritePolicy:
    """What a fresh activity-note read may change for one company.

    ``min_confidence`` is a FLOOR THE LAYER RAISES, never lowers: the caller's
    global ``--min-confidence`` still applies, and the effective threshold is the
    max of the two.
    """

    write_sector: bool
    write_subsector: bool
    #: Only fill SubSector when the note's sector matches the stored one. Without
    #: this, a sub-sector guess from a different taxonomy branch gets written
    #: under the wrong parent.
    require_sector_agreement: bool
    min_confidence: float
    reason: str

    @property
    def writes_nothing(self) -> bool:
        return not (self.write_sector or self.write_subsector)


# Confidence floor for REPLACING an existing classification (as opposed to filling
# a blank, which has no floor). Anchored on the deterministic pass, which scored
# every name-keyword rule at a flat 0.70: a note that only matches that is not an
# improvement, so require it to beat the incumbent with room to spare.
OVERWRITE_MIN_CONFIDENCE = 0.75

#: Deprecated alias kept so external callers and older commands keep working.
DETERMINISTIC_OVERWRITE_MIN_CONFIDENCE = OVERWRITE_MIN_CONFIDENCE

_NOTHING = WritePolicy(False, False, False, 1.0, "manual: analyst-curated, left alone")


def write_policy(
    layer: str,
    sector: str | None,
    *,
    protect_original: bool = False,
) -> WritePolicy:
    """What a usable filed note may change for a company in ``layer``.

    The rule: a usable note replaces the tag; no usable note keeps it. Whether the
    note is usable is :func:`lib.note_quality.assess_note`'s job, not this
    function's — this only says what a note that HAS passed the gate is permitted
    to do. So the caller must run the gate; a policy allowing a Sector write is not
    on its own a licence to write one.

    ``protect_original`` restores the older conservative handling of the two
    web-research layers (SubSector only, and only on sector agreement), for staging
    the change rather than taking it in one step.
    """
    if layer not in LAYERS:
        raise ValueError(f"unknown provenance layer: {layer!r}")
    if layer == MANUAL:
        return _NOTHING

    # No incumbent classification to displace: a blank Sector, or one parked in
    # 'Other'. Write at any confidence — there is nothing to lose.
    if layer == UNCLASSIFIED or is_placeholder_sector(sector):
        return WritePolicy(
            write_sector=True,
            write_subsector=True,
            require_sector_agreement=False,
            min_confidence=0.0,
            reason=("unclassified: no sector to protect" if layer == UNCLASSIFIED
                    else f"{layer}: parked in a placeholder sector, not a classification"),
        )

    if protect_original and layer in (ORIGINAL_WEB, ORIGINAL_XLSX):
        return WritePolicy(
            write_sector=False,
            write_subsector=True,
            require_sector_agreement=True,
            min_confidence=0.0,
            reason=f"{layer}: --protect-original set, sub-sector only",
        )

    # Displacing a real incumbent costs more confidence than filling a blank.
    return WritePolicy(
        write_sector=True,
        write_subsector=True,
        require_sector_agreement=False,
        min_confidence=OVERWRITE_MIN_CONFIDENCE,
        reason=f"{layer}: usable filed note replaces the incumbent tag",
    )


def source_urls(sources: str | None) -> list[str]:
    """The http(s) entries in a ``DescriptionSources`` cell, for reporting.

    Tolerates the column's real-world shapes: a JSON array, a bare string, or
    malformed JSON (a few rows carry a mojibake'd filename).
    """
    if not sources or not str(sources).strip():
        return []
    try:
        parsed = json.loads(sources)
    except (json.JSONDecodeError, TypeError):
        parsed = [str(sources)]
    if not isinstance(parsed, list):
        parsed = [str(parsed)]
    return [str(x) for x in parsed if str(x).startswith(("http://", "https://"))]
