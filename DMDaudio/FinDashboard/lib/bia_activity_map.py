"""bia.ge activity labels -> our SubSector, as a *measured* map. Pure: no DB, no UI.

WHAT THIS IS
------------
A bia.ge company page lists ACTIVITY FIELDS (``საქმიანობის სფერო``, e.g.
``სუპერმარკეტები და ჰიპერმარკეტები``, ``საცხობები``) and coarser ACTIVITY
CATEGORIES (``საქმიანობის კატეგორიები``, e.g. ``კვების პროდუქტები``). Those are a
real, independent statement of what a company does, and **1,237 companies that
have a Sector but NO SubSector have them** — GEL 10.3bn of revenue currently
showing no sub-sector at all.

That gap exists by construction: ``scripts/apply_bia_sectors.py`` deliberately
never writes a SubSector, because it works from the NACE-2016 *division* and a
2-digit division cannot support one. bia's own activity labels are far finer than
a division, so they can.

Like ``lib/nace_sector_map.py``, this module hand-authors NO table. It DERIVES the
map every run from companies that already carry a SubSector, measures each
label's purity, and refuses the labels that do not clear a floor.

SCOPED TO THE COMPANY'S KNOWN SECTOR
------------------------------------
Every key is ``(level, Sector, label)``, never ``(level, label)``. Two things fall
out of that, both wanted:

* SubSector names are reused across Sectors — ``Retail - Grocery`` lives under
  both ``FMCG`` and ``Retail`` — so an unscoped map would average two different
  parents together and answer with a sub-sector that cannot hang off this
  company's Sector.
* The pair written is therefore coherent BY CONSTRUCTION. Mismatched
  Sector/SubSector pairs are a known, recurring failure in this codebase (see
  ``scripts/find_stale_subsectors.py``); this map cannot create one.

The corollary is that a company with no Sector is not a candidate. Filling blank
*Sectors* is ``apply_bia_sectors.py``'s job and stays there — see the measurement
under "SECTOR IS NOT THIS MODULE'S JOB" below.

ONE LEVEL: THE ACTIVITY FIELD
-----------------------------
:data:`ACTIVITY_LEVELS` holds ``industry`` alone (1,154 distinct labels). The
level machinery is kept because the "most specific level that clears the floor
wins" shape is the right one if a finer field is ever added — but see the two
rejections below for why neither of bia's other two fields is in it.

A company is seeded only when the labels that clear the floor **AGREE**
(:func:`resolve_company`), the same rule the NACE map uses, and for the same
reason: bia lists labels unordered and unweighted, so there is no "take the
first" path. A filer whose labels point at two different sub-sectors abstains.

FLOOR CALIBRATION (2026-08-26 DB; reference pool = 4,271 companies)
-------------------------------------------------------------------
``LOO`` is leave-one-out accuracy: each pool company is re-predicted with its own
vote removed from every key it contributes to. Yield is over the 1,237
blank-SubSector candidates.

    floor  support  keys>=    LOO    seeded    revenue
     0.75      5       1     81.8%     529    GEL 4.09bn
     0.82      5       1     84.2%     403    GEL 2.81bn
     0.90      5       1     87.6%     271    GEL 1.66bn   <- defaults
     0.95      5       1     90.0%     165    GEL 0.71bn
     0.82      5       2     89.0%     192    GEL 1.21bn
     0.90      5       2     91.9%     103    GEL 0.45bn
     0.82      8       1     84.5%     373    GEL 2.51bn
     0.90      8       1     88.5%     246    GEL 1.44bn
     0.82      8       2     89.7%     175    GEL 1.08bn
     0.90      8       2     92.4%      89    GEL 0.41bn

The defaults take the best accuracy-per-company point on that curve. For a
precision-first run, ``--min-purity 0.82 --min-support 8 --min-keys 2`` gives
89.7% over 175 companies; ``--min-keys 2`` alone is the single biggest precision
lever, because requiring two independent labels to agree is a much stronger
statement than one pure label. Re-measure with
``scripts/seed_subsectors_from_bia.py --calibrate`` before changing any of them.

THE REFERENCE POOL MUST NOT BE CIRCULAR
---------------------------------------
Only layers a HUMAN or a FILED NOTE produced may be measured against
(:data:`TRUSTED_REFERENCE_LAYERS`). This is not caution, it is a measured
correction: scoring the Sector variant of this map against the full classified
population read 90.0%, and the same measurement with the machine-derived layers
(``bia-directory``, ``rms-nace``, ``deterministic``) dropped out read **87.1%**.
The 2.9-point difference was the map being scored against its own cousins.

THE ERROR COMPOUNDS ON A MACHINE-DERIVED SECTOR
-----------------------------------------------
Scoping to the known Sector makes the pair coherent, and coherence is NOT
correctness. Of the 271 companies seeded on the 2026-08-26 run, the Sector being
scoped against was itself machine-derived for most of them:

    Sector provenance of the seeded companies
      bia-directory (bia NACE-2016 division)   198
      rms-nace      (RMS NACE codes)            47
      recent        (filed activity note)       16
      original-web  (analyst research)          10

For those 245, this pass's 87.6% sits on top of that classifier's own ~88-89%, so
the realistic joint accuracy is nearer 78%. The SubSector will be a sensible
child of whatever Sector is recorded — and if the Sector is wrong, a coherent
wrong pair is the outcome. That is a limit of the input, not a bug here, but it is
the reason ``--require-trusted-sector`` exists: it restricts candidates to
companies whose Sector a human or a filed note set, which on the same run seeds
only ~26 companies. Use it when precision matters more than coverage; prefer
fixing the upstream Sector when it does not.

MEASURED AND REJECTED: ``categories``
------------------------------------
bia's ACTIVITY CATEGORIES (``საქმიანობის კატეგორიები``) were in as a coarse last
resort, consulted only when no industry label cleared the floor. Measured, the
level is DEGENERATE: of the 14 category labels that clear the default gate,
**13 (93%) simply reproduce their Sector's most common SubSector**. It is a prior
dressed as evidence — 27 labels cannot say much about a company — and it scored
accordingly:

    level      predicted   LOO
    industry       902    87.6%
    category        35    80.0%

It bought 15 of 286 seeded companies at 7.6 points below the headline, so it is
gone. Anything the industry field cannot answer now abstains, which is the honest
outcome: "no sub-sector" beats "probably whatever this sector usually is".

MEASURED AND REJECTED: ``products``
-----------------------------------
bia also lists PRODUCTS (``პროდუქტები``, 3,495 distinct labels, and 462 companies
carry products but no industries, so it looked like free coverage). Adding it as a
third, most-specific level is worse at every setting measured:

    levels                   floor 0.90 / supp 5 / keys 1
    industry                   87.6%   271 seeded   GEL 1.66bn   <- shipped
    product > industry         85.1%   309 seeded   GEL 1.96bn
    industry > product         85.2%   308 seeded   GEL 1.96bn

Products are item-level, not activity-level — a bakery lists ``ორცხობილა``
(rusks) and so does a supermarket that merely sells them — so they buy ~14% more
companies at a consistent 2.4-point accuracy cost, in either order. Excluded. Do
not re-add without re-running the three-way comparison.
"""
from __future__ import annotations

import collections
from typing import Iterable, Mapping

#: bia detail field behind each level, most specific first. Order is load-bearing
#: when there is more than one; today there is one, and the reason the coarse
#: level was removed is in the docstring ("MEASURED AND REJECTED: categories").
ACTIVITY_LEVELS: tuple[tuple[str, str], ...] = (
    ("industry", "industries"),
)

LEVEL_NAMES: tuple[str, ...] = tuple(name for name, _ in ACTIVITY_LEVELS)

#: Sector-provenance layers a human or a filed activity note produced. Anything
#: else in the classified population came out of a classifier and would make the
#: purity measurement circular — see the module docstring.
TRUSTED_REFERENCE_LAYERS: frozenset[str] = frozenset({
    "manual", "recent", "original-web", "original-xlsx",
})

DEFAULT_MIN_PURITY = 0.90
DEFAULT_MIN_SUPPORT = 5
#: How many independent labels must clear the floor and agree. 1 is the measured
#: default; 2 trades roughly a third of the yield for ~4 accuracy points.
DEFAULT_MIN_KEYS = 1

SKIP_NO_SECTOR = "no Sector to scope against"
SKIP_NO_USABLE_LABEL = "no usable bia activity label"
SKIP_NO_LABEL_CLEARS_FLOOR = "no label clears the floor"
SKIP_LABELS_DISAGREE = "labels disagree"

#: ``(level, sector, label) -> {subsector: companies}``
PurityTable = dict[tuple[str, str, str], collections.Counter]


def activity_labels(detail: Mapping | None, level: str) -> tuple[str, ...]:
    """The de-duplicated, whitespace-normalised bia labels for one level.

    De-duplication matters for the denominator: a company that lists the same
    label twice must count ONCE, or ``support`` stops meaning "how many
    already-classified companies carry this label" and the leave-one-out
    subtraction is no longer exactly one company.
    """
    if not detail:
        return ()
    field = dict(ACTIVITY_LEVELS).get(level)
    if not field:
        return ()
    seen: set[str] = set()
    out: list[str] = []
    for raw in detail.get(field) or []:
        label = " ".join(str(raw or "").split())
        if label and label not in seen:
            seen.add(label)
            out.append(label)
    return tuple(out)


def has_usable_labels(detail: Mapping | None) -> bool:
    """True when bia gives this company at least one activity label."""
    return any(activity_labels(detail, level) for level in LEVEL_NAMES)


def build_purity_table(rows: Iterable[tuple[str, str, Mapping]]) -> PurityTable:
    """Count SubSectors per ``(level, Sector, label)`` over the reference pool.

    ``rows`` is ``(sector, subsector, bia_detail)`` for companies that already
    carry BOTH, drawn only from :data:`TRUSTED_REFERENCE_LAYERS` (the caller owns
    that filter — this module never touches a DB).
    """
    table: PurityTable = collections.defaultdict(collections.Counter)
    for sector, subsector, detail in rows:
        sector = (sector or "").strip()
        subsector = (subsector or "").strip()
        if not sector or not subsector:
            continue
        for level in LEVEL_NAMES:
            for label in activity_labels(detail, level):
                table[(level, sector, label)][subsector] += 1
    return dict(table)


def resolve_label(
    table: PurityTable,
    level: str,
    sector: str,
    label: str,
    *,
    min_purity: float = DEFAULT_MIN_PURITY,
    min_support: int = DEFAULT_MIN_SUPPORT,
    exclude_subsector: str | None = None,
) -> tuple[str, float, int] | None:
    """``(subsector, purity, support)`` for one label, or None if it abstains.

    ``exclude_subsector`` removes ONE company's vote — the leave-one-out
    subtraction. It is a single decrement, not a whole class, because a company
    contributes exactly one vote to each label it carries.
    """
    counter = table.get((level, sector, label))
    if not counter:
        return None
    counts = collections.Counter(counter)
    if exclude_subsector is not None and counts.get(exclude_subsector):
        counts[exclude_subsector] -= 1
        if counts[exclude_subsector] <= 0:
            del counts[exclude_subsector]
    support = sum(counts.values())
    if support < min_support:
        return None
    subsector, hits = counts.most_common(1)[0]
    purity = hits / support
    if purity < min_purity:
        return None
    return subsector, purity, support


def resolve_company(
    table: PurityTable,
    sector: str,
    detail: Mapping | None,
    *,
    min_purity: float = DEFAULT_MIN_PURITY,
    min_support: int = DEFAULT_MIN_SUPPORT,
    min_keys: int = DEFAULT_MIN_KEYS,
    exclude_subsector: str | None = None,
) -> tuple[str | None, str, tuple[str, ...]]:
    """``(subsector | None, reason, labels_that_voted)`` for one company.

    The most specific level that produces any vote decides; a coarser level is
    consulted only when the finer one was silent. Within a level the qualifying
    labels must AGREE — bia lists them unordered and unweighted, so there is no
    principled way to pick between two that disagree.
    """
    sector = (sector or "").strip()
    if not sector:
        return None, SKIP_NO_SECTOR, ()
    if not has_usable_labels(detail):
        return None, SKIP_NO_USABLE_LABEL, ()
    for level in LEVEL_NAMES:
        votes: list[tuple[str, str]] = []
        for label in activity_labels(detail, level):
            hit = resolve_label(
                table, level, sector, label,
                min_purity=min_purity, min_support=min_support,
                exclude_subsector=exclude_subsector,
            )
            if hit:
                votes.append((hit[0], label))
        if not votes:
            continue
        chosen = {sub for sub, _ in votes}
        if len(chosen) > 1:
            return None, SKIP_LABELS_DISAGREE, tuple(lbl for _, lbl in votes)
        if len(votes) < min_keys:
            return None, SKIP_NO_LABEL_CLEARS_FLOOR, tuple(lbl for _, lbl in votes)
        return votes[0][0], level, tuple(lbl for _, lbl in votes)
    return None, SKIP_NO_LABEL_CLEARS_FLOOR, ()


def kept_labels(
    table: PurityTable,
    *,
    min_purity: float = DEFAULT_MIN_PURITY,
    min_support: int = DEFAULT_MIN_SUPPORT,
) -> list[tuple[str, str, str, str, float, int]]:
    """Every label that clears the floor: ``(level, sector, label, sub, purity, n)``.

    This IS the map — inspect it rather than trusting the defaults.
    """
    out = []
    for (level, sector, label), counter in table.items():
        support = sum(counter.values())
        if support < min_support:
            continue
        subsector, hits = counter.most_common(1)[0]
        purity = hits / support
        if purity >= min_purity:
            out.append((level, sector, label, subsector, purity, support))
    out.sort(key=lambda r: (-r[5], -r[4], r[0], r[1], r[2]))
    return out


def loo_accuracy(
    table: PurityTable,
    pool: Iterable[tuple[str, str, Mapping]],
    *,
    min_purity: float = DEFAULT_MIN_PURITY,
    min_support: int = DEFAULT_MIN_SUPPORT,
    min_keys: int = DEFAULT_MIN_KEYS,
) -> tuple[int, int, int]:
    """``(correct, wrong, abstained)`` over the reference pool, leave-one-out."""
    correct = wrong = abstained = 0
    for sector, subsector, detail in pool:
        predicted, _reason, _labels = resolve_company(
            table, sector, detail,
            min_purity=min_purity, min_support=min_support, min_keys=min_keys,
            exclude_subsector=subsector,
        )
        if predicted is None:
            abstained += 1
        elif predicted == subsector:
            correct += 1
        else:
            wrong += 1
    return correct, wrong, abstained
