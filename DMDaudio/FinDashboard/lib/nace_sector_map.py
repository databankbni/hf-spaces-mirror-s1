"""NACE Rev.2 code -> our Sector, as a *measured* map. Pure: no DB, no Streamlit.

WHAT THIS IS
------------
``nace_codes`` (built by ``scripts/build_rms_datasets.py`` from the reportal **RMS**
``NACE <year>.xlsx`` bulk file) holds every NACE Rev.2 activity code a company
declared in its own filing. That is a real, independent signal about what the
company does — and 1,791 companies with no curated ``Sector`` have one.

It is NOT a read of the company, though. Two taxonomies are in play and they
disagree by construction: ours is THEME-first (Pharma, Oil & Gas and FMCG each
contain wholesalers), NACE is CHANNEL-first (46 = wholesale of anything, 47 =
retail of anything). So this module writes no hand-authored table. It *derives*
the map every run from the companies that already have a Sector, measures each
code's purity, and refuses the codes that do not clear a floor — the same method
``scripts/apply_bia_sectors.py`` used for the bia.ge NACE-2016 fill, whose gated
map measured 88.9% right.

THE FOUR TRAPS THIS MODULE EXISTS TO ABSORB
-------------------------------------------
1. **Codes are not flagged primary vs secondary, and the first-listed code is not
   the main activity.** ``200075113`` (a winery) lists ``91020`` *museum
   activities* first — see ``lib/rms_nace.py`` and the survey doc §A4. So there is
   no "take the first code" path here. Every code is one equal-weight fact, each
   one is resolved independently, and a company is seeded only when the codes that
   clear the floor AGREE (:func:`resolve_company`). Under that rule the winery
   resolves correctly: ``91020`` museum and ``46341`` alcohol-wholesale both
   abstain (impure), ``11020`` wine-production carries it to Alcoholic Beverages.
2. **A leading zero was already lost at source.** The RMS file stores the code
   column as an Excel *number*, so division-0x codes arrive 4 characters wide.
   Every 4-wide code measured in the FY2024 file resolves to a real division
   01/07/08/09 activity name (``1111`` = growing of wheat, ``8121`` = quarrying of
   sand and gravel, ``1500`` = mixed farming), never to the 4-digit class it would
   otherwise denote — so :func:`normalize_nace_code` re-pads it. That pad is the
   inverse of a known source loss, not a guess.
3. **Coarse keys average away the distinction our taxonomy turns on.** Hence the
   hierarchy in :data:`NACE_LEVELS`: the most specific level that clears the floor
   wins, and the division is only a last resort. Reversing that order silently
   loses every company the sub-class could have separated.
4. **A company must not be counted twice in its own purity denominator.** A filer
   with both ``46341`` and ``46719`` carries division ``46`` once, not twice, so
   ``support`` reads as "how many already-classified companies carry this key" and
   the leave-one-out subtraction in :func:`resolve_code` is exactly one company.

CIRCULARITY — the one thing a caller must get right
---------------------------------------------------
The reference pool must exclude any layer that was ITSELF derived from NACE codes.
``lib.sector_provenance.BIA`` is exactly that (a NACE-2016 division map over
bia.ge pages, 590 companies in the classified population): measuring purity
against it would be scoring this map against a cousin of itself. Callers pass the
pool in; :data:`CIRCULAR_REFERENCE_LAYERS` names the layers they must drop.

FLOOR CALIBRATION (measured on the 2026-08-05 DB, min_support=8)
----------------------------------------------------------------
Reference pool: 4,178 classified companies with a NACE code (recent 3,081 + manual
448 + original-web 394 + original-xlsx 255). ``LOO`` = leave-one-out accuracy on
that pool; ``cross-check`` = the same measurement with map AND pool rebuilt from
the note-derived (``recent``) layer alone, which is the pool the bia fill used.
Yield is over the 1,791 blank-Sector candidates:

    floor   keys    LOO    cross-check   seeded   revenue
    >=0.70   299   83.5%      84.3%         817   GEL 4.97bn
    >=0.75   252   86.8%      86.0%         630   GEL 3.78bn
    >=0.78   216   87.3%      86.1%         559   GEL 3.43bn
    >=0.80   205   88.9%      85.1%         514   GEL 3.17bn
    >=0.82   186   89.1%      86.9%         450   GEL 2.81bn   <- default
    >=0.85   155   88.8%      88.7%         361   GEL 2.31bn
    >=0.88   117   91.5%      90.6%         274   GEL 1.78bn
    >=0.90   103   92.0%      90.9%         213   GEL 1.37bn

0.82 is the default because it is the LOWEST floor whose measured accuracy reaches
the shipped bia layer's 88.9% on *both* pools. 0.80 looks equal on the primary pool
(88.9%) but is the table's widest disagreement between the two measurements —
3.8pp, and the cross-check falls to 85.1% there — which is precisely the signal
that the extra 64 companies it buys are the doubtful ones. Above 0.82 accuracy sits
on an 89±0.5% plateau through 0.85 (which costs 89 companies for no measurable
gain); the next genuine step is 0.88 at 91.5%, and it costs 39% of the yield. That
trade is a reviewer's call, one flag wide: ``--min-purity 0.88``.

``min_support`` is insensitive by comparison — 5/8/12/20 give 89.0/89.1/89.1/88.3%
— so it stays at the precedent's 8.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

__all__ = [
    "NACE_LEVELS", "LEVEL_NAMES", "CIRCULAR_REFERENCE_LAYERS",
    "DEFAULT_MIN_PURITY", "DEFAULT_MIN_SUPPORT",
    "SKIP_NO_USABLE_CODE", "SKIP_NO_CODE_CLEARS_FLOOR", "SKIP_CODES_DISAGREE",
    "CodeVerdict", "PurityTable",
    "normalize_nace_code", "code_keys", "build_purity_table",
    "resolve_code", "resolve_company", "kept_keys", "refused_keys",
    "loo_accuracy",
]

#: ``(level name, key width)``, MOST SPECIFIC FIRST. The order is the design, not
#: a detail — see trap 3 in the module docstring. Widths are positions of the
#: normalised 5-character code: NACE Rev.2 division (2) / group (3) / class (4),
#: plus the Georgian national 5th digit (sub-class).
NACE_LEVELS: tuple[tuple[str, int], ...] = (
    ("subclass", 5),
    ("class", 4),
    ("group", 3),
    ("division", 2),
)

LEVEL_NAMES: tuple[str, ...] = tuple(name for name, _ in NACE_LEVELS)

#: Provenance layers a caller must NOT put in the reference pool, because they
#: were themselves derived from NACE codes. Kept as bare strings so this module
#: stays free of the (also pure, but unrelated) provenance module.
CIRCULAR_REFERENCE_LAYERS: frozenset[str] = frozenset({"bia-directory"})

DEFAULT_MIN_PURITY = 0.82
DEFAULT_MIN_SUPPORT = 8

SKIP_NO_USABLE_CODE = "no usable NACE code"
SKIP_NO_CODE_CLEARS_FLOOR = "no code clears the floor"
SKIP_CODES_DISAGREE = "codes disagree"

#: ``{level name: {key: Counter[sector]}}``, each company counted at most once per
#: key (trap 4).
PurityTable = dict[str, dict[str, Counter]]


@dataclass(frozen=True)
class CodeVerdict:
    """What one NACE code resolves to, and on what evidence."""

    code: str
    level: str
    key: str
    sector: str
    purity: float
    support: int

    @property
    def label(self) -> str:
        return f"{self.level} {self.key}"


def normalize_nace_code(raw: object) -> str | None:
    """A NACE code as a 5-character digit string, or ``None`` if unusable.

    Absorbs trap 2: a 4-character code lost a leading zero in the source Excel
    file and is re-padded. Anything that is not 4 or 5 digits after stripping is
    refused rather than guessed at — a 2- or 3-digit cell is ambiguous between a
    truncated code and a bare division, and no such cell exists in the measured
    file.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, float):
        if raw != int(raw):
            return None
        raw = int(raw)
    if isinstance(raw, int):
        s = str(raw)
    else:
        s = "".join(str(raw).split())
    if not s or s.upper() == "NULL" or not s.isdigit():
        return None
    if len(s) == 4:
        return "0" + s
    return s if len(s) == 5 else None


def code_keys(code: str) -> tuple[tuple[str, str], ...]:
    """``[(level, key), ...]`` for one normalised code, most specific first."""
    return tuple((name, code[:width]) for name, width in NACE_LEVELS)


def build_purity_table(
    reference: Iterable[tuple[str, str, Iterable[str]]],
) -> PurityTable:
    """Count already-classified companies per ``(level, key) -> sector``.

    ``reference`` yields ``(id_code, sector, codes)`` for companies that already
    carry a real (non-placeholder) Sector, with the circular layers already
    dropped by the caller (:data:`CIRCULAR_REFERENCE_LAYERS`). Codes may be raw —
    they are normalised here — and a company contributes **once** per key however
    many of its codes land on it.
    """
    table: PurityTable = {name: defaultdict(Counter) for name in LEVEL_NAMES}
    for _idc, sector, codes in reference:
        sector = (sector or "").strip()
        if not sector:
            continue
        seen: set[tuple[str, str]] = set()
        for raw in codes:
            norm = normalize_nace_code(raw)
            if not norm:
                continue
            seen.update(code_keys(norm))
        for level, key in seen:
            table[level][key][sector] += 1
    return {name: dict(d) for name, d in table.items()}


def _modal(counter: Mapping[str, int], exclude_sector: str | None) -> tuple[str, int, int] | None:
    """``(sector, hits, support)`` for the modal sector, one company optionally
    removed (leave-one-out). Ties break on the sector name so a run is
    deterministic."""
    counts = Counter(counter)
    if exclude_sector:
        counts[exclude_sector] -= 1
        if counts[exclude_sector] <= 0:
            del counts[exclude_sector]
    support = sum(counts.values())
    if not support:
        return None
    sector, hits = min(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return sector, hits, support


def resolve_code(
    table: PurityTable,
    code: str,
    *,
    min_purity: float = DEFAULT_MIN_PURITY,
    min_support: int = DEFAULT_MIN_SUPPORT,
    exclude_sector: str | None = None,
) -> CodeVerdict | None:
    """The most specific level of ``code`` that clears the floor, or ``None``.

    ``exclude_sector`` removes one company holding that sector from every counter
    before judging — the leave-one-out used both to keep a reference company out
    of its own accuracy measurement and to satisfy "the company being seeded is
    never in its own denominator". Passing it for a company that is not in the
    reference pool is harmless but wrong, so callers pass it only for reference
    companies.

    A level that is present but too thin (``support < min_support``) does not stop
    the walk — it falls through to the next, coarser level. That is deliberate:
    the alternative (abstaining outright) throws away the division evidence for
    every rare sub-class.
    """
    norm = normalize_nace_code(code)
    if not norm:
        return None
    for level, key in code_keys(norm):
        counter = table.get(level, {}).get(key)
        if not counter:
            continue
        modal = _modal(counter, exclude_sector)
        if modal is None:
            continue
        sector, hits, support = modal
        if support < min_support:
            continue
        purity = hits / support
        if purity >= min_purity:
            return CodeVerdict(norm, level, key, sector, purity, support)
    return None


def resolve_company(
    table: PurityTable,
    codes: Iterable[str],
    *,
    min_purity: float = DEFAULT_MIN_PURITY,
    min_support: int = DEFAULT_MIN_SUPPORT,
    exclude_sector: str | None = None,
) -> tuple[CodeVerdict | None, str | None, list[CodeVerdict]]:
    """``(verdict, skip_reason, all_verdicts)`` for one company's whole code list.

    Every code is resolved independently and the company is seeded only if the
    codes that clear the floor AGREE on a sector — that unanimity rule is what
    defuses the winery (trap 1), and it is measurably better than taking the
    most-specific code and moving on: 89.1% vs 88.4% leave-one-out at the default
    floor, over the 66 companies it abstains on instead of guessing. Codes that
    abstain do not veto; only a *conflicting* verdict does.

    The returned verdict is the most specific/purest of the agreeing ones, so the
    provenance marker names the code that actually carried the decision.
    """
    normed = [n for n in (normalize_nace_code(c) for c in codes) if n]
    if not normed:
        return None, SKIP_NO_USABLE_CODE, []
    verdicts = [
        v for v in (
            resolve_code(table, c, min_purity=min_purity, min_support=min_support,
                         exclude_sector=exclude_sector)
            for c in sorted(set(normed))
        ) if v is not None
    ]
    if not verdicts:
        return None, SKIP_NO_CODE_CLEARS_FLOOR, []
    if len({v.sector for v in verdicts}) > 1:
        return None, SKIP_CODES_DISAGREE, verdicts
    best = min(verdicts, key=lambda v: (LEVEL_NAMES.index(v.level), -v.purity, -v.support))
    return best, None, verdicts


def _walk(table: PurityTable, min_support: int):
    for level in LEVEL_NAMES:
        for key, counter in table.get(level, {}).items():
            modal = _modal(counter, None)
            if modal is None:
                continue
            sector, hits, support = modal
            if support >= min_support:
                yield level, key, sector, hits / support, support


def kept_keys(table: PurityTable, *, min_purity: float = DEFAULT_MIN_PURITY,
              min_support: int = DEFAULT_MIN_SUPPORT) -> list[tuple[str, str, str, float, int]]:
    """``[(level, key, sector, purity, support)]`` for keys that clear the floor,
    strongest support first — the per-code purity table the dry run prints."""
    rows = [r for r in _walk(table, min_support) if r[3] >= min_purity]
    return sorted(rows, key=lambda r: (-r[4], r[0], r[1]))


def refused_keys(table: PurityTable, *, min_purity: float = DEFAULT_MIN_PURITY,
                 min_support: int = DEFAULT_MIN_SUPPORT) -> list[tuple[str, str, str, float, int]]:
    """The mirror image of :func:`kept_keys`. The big refusals are the informative
    part of the report: 46 wholesale and 47 retail are the largest keys in the
    data and a theme-first taxonomy cannot use either."""
    rows = [r for r in _walk(table, min_support) if r[3] < min_purity]
    return sorted(rows, key=lambda r: (-r[4], r[0], r[1]))


def loo_accuracy(
    table: PurityTable,
    reference: Iterable[tuple[str, str, Iterable[str]]],
    *,
    min_purity: float = DEFAULT_MIN_PURITY,
    min_support: int = DEFAULT_MIN_SUPPORT,
) -> tuple[int, int, Counter]:
    """``(decided, correct, skip_reasons)`` over the reference pool, leave-one-out.

    Each reference company is resolved against a table with its own contribution
    removed, so this is an honest out-of-sample estimate of what the seeding pass
    will get right — stricter than the in-sample weighted purity the bia fill
    quoted. It still assumes the unclassified population behaves like the
    classified one, which is an assumption, not a measurement.
    """
    decided = correct = 0
    skips: Counter = Counter()
    for _idc, sector, codes in reference:
        sector = (sector or "").strip()
        if not sector:
            continue
        verdict, reason, _all = resolve_company(
            table, codes, min_purity=min_purity, min_support=min_support,
            exclude_sector=sector)
        if verdict is None:
            skips[reason] += 1
            continue
        decided += 1
        correct += int(verdict.sector == sector)
    return decided, correct, skips
