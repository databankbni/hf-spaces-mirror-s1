"""Statement-of-changes-in-equity data model (reportal RMS ``Equity ALL
<year>.xlsx`` bulk files) — pure, no Streamlit/DB.

Source: the per-year ``Equity_ALL_<id>.xlsx`` bulk file from
``rms.reportal.ge`` (request-gated, same portal as ``lib/auditors.py``'s
``Auditors`` files). A full statement of changes in equity as an
``EquityRow x EquityColumn`` long-format matrix. Measured against the real
FY2024 file (``Equity_ALL_271.xlsx``, 602,391 rows × 14 cols):

``ReportCode, IdCode, Name, ReportType, EquityRow, EquityColumn, Value,
Thousands, Cat, ReportYear, FVYear, NACE_CODE, NACE_NAME, NACE_MAIN``.

**One file covers several FVYears.** The FY2024 file's ``FVYear`` column is
2022 (89,370 rows), 2023 (273,591 rows) and 2024 (239,430 rows) — a filer's
statement shows the current year's movements plus one or two comparative
years, and RMS flattens all of them into one long table tagged ``ReportYear``
2024 throughout (the year the *file* was produced), with the real per-row
year living in ``FVYear``. Always key off ``FVYear``, never ``ReportYear``.

This module does the **narrow extraction the survey recommends** (see
``docs/reviews/2026-08-05-reportal-rms-untapped-datasets.md``, §A3): three
figures per ``(IdCode, FVYear, ReportType)``, all read off the
``EquityColumn == 'სულ საკუთარი კაპიტალი'`` ("Total equity") column —

* ``dividends_declared`` — the ``EquityRow == 'დივიდენდის გამოცხადება'``
  ("Dividends declared") row. Sign is preserved as filed: a normal
  distribution reduces equity and is filed as **negative**; a consumer
  wanting a headline "amount declared" should take ``abs()``.
* ``error_correction`` — the ``EquityRow == 'გამოვლენილი შეცდომების
  შესწორების ეფექტი'`` ("Effect of correction of identified errors") row,
  signed. **Measured: every non-zero instance in the FY2024 file (163 raw
  rows across 150 distinct (IdCode, ReportType, FVYear) keys, 130 companies)
  is tagged ``FVYear == 2022``** — the earliest comparative year the file
  presents. That is not a parsing bug: IAS 8 retroactive restatement adjusts
  the opening balance of the *earliest* period shown, so the correction
  always lands on whichever FVYear happens to anchor that. A future file
  spanning different years will show it on ITS earliest year, not
  necessarily "2022" specifically. **This row is also genuinely
  double-rendered per key** (see :func:`_place`'s docstring) — an earlier
  version of this parser let the second, usually-zero occurrence silently
  clobber 111 of those 150 keys' real value, undercounting non-zero
  corrections by ~74% (39 survived vs the true 150). Fixed; regression-tested
  in ``tests/test_rms_datasets.py``.
* ``closing_total_equity`` — the row literally named "balance at the end of
  the reporting period" for THIS row's own year (``EquityRow`` matches
  ``ნაშთი საანგარიშგებო პერიოდის ბოლო თარიღისთვის - <FVYear>``, normalised
  for whitespace — the 2022-year label ships with a doubled space after
  ``ნაშთი`` in the real file; :func:`closing_year` collapses it before
  matching). Deliberately excludes the parallel "ADJUSTED" balance labels
  (``დაკორექტირებული ნაშთი ...`` — an adjusted closing exists only for the
  file's earliest year, 2022 in the FY2024 file; there is no adjusted variant
  for the later years, so picking the adjusted row for one year and the plain
  row for the others would be an inconsistent, not-uniformly-available rule).
  This is a scope decision, not an oversight — revisit if a use case needs
  the restated figure specifically.

**The ``Thousands`` scale finding — DIFFERENT from ``lib/auditors.py``.**
That module's docstring says ``Thousands`` is presentation metadata only,
never a scale factor, because ``Auditors``' ``Income``/``Assets`` are always
absolute GEL. This file is NOT the same: cross-checking 5,617 real closing
"Total equity" cells (FY2022-2024) against the corresponding
``metrics_panel.TotalEquity`` (itself already absolute GEL and already
unit-mistag-corrected) gives, by the row's own ``Thousands`` flag —

======================  =========  ======================  =================
``Thousands`` value      n          ratio (panel / raw)      reading
======================  =========  ======================  =================
``NULL``                 3,414      median 1.0 (89.5% ~1)    already absolute GEL
``'.ლარი'``                 142      median 1.0 (85.9% ~1)    already absolute GEL
``'.000 ლარი'``           1,378      median 1000 (88.2% ~1000) **multiply Value by 1000**
======================  =========  ======================  =================

So for THIS file, ``Thousands == '.000 ლარი'`` genuinely means "presented in
thousand GEL" and the raw ``Value`` must be scaled up; the other two values
mean the cell is already absolute GEL. (Verified with a large filer:
``202177205`` შპს თეგეტა მოტორსი, FY2023 group filing, ``Thousands='.000
ლარი'``, closing Total-equity cell = 224,877 -> ×1000 = 224,877,000, which is
exactly ``metrics_panel.TotalEquity`` for that company-year.) The ~10-15% of
cells that don't land near their flag's expected ratio are not a rule
violation — mostly individual-vs-consolidated basis differences against
`metrics_panel`'s picked filing, plus a handful of companies with their own
independent, pre-existing unit-mistag issue in the *source* filing (one such
company, ``204875082`` შპს აკა, is a name already flagged in
``docs/reviews/2026-08-05-reportal-rms-untapped-datasets.md``'s auditors
cross-check — its OWN filed figures were mistagged regardless of what this
file's ``Thousands`` column says about them).

**A calibrated, more rigorous sibling already exists.** ``Raw Data/equity/``
+ ``scripts/build_equity_movements.py`` ingest what looks like the same
underlying export family (its file ``equity_2024_id271.xlsx`` shares the RMS
file id 271 with this module's ``Equity_ALL_271.xlsx``) into a full per-cell
``equity_movements`` table, with a per-filing calibration factor tied back to
``financial_data.BS_TotalEquity`` rather than trusting the ``Thousands`` flag
directly — a stronger approach precisely because a filer's own ``Thousands``
tagging can be wrong (see the ``204875082`` case above). That table already
feeds a ``v_dividends`` view. **This module and its table are independent of
that pipeline by design** (different, narrower scope — see
``scripts/build_rms_datasets.py``'s ``--report`` mode, which cross-checks
this module's dividend totals against ``v_dividends`` but never writes to
``equity_movements`` or ``v_dividends``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from lib.auditors import clean_text, to_int, to_number

# --------------------------------------------------------------------------
# Header schema
# --------------------------------------------------------------------------

#: Canonical field names, as spelled in the FY2024 file.
COLUMNS = (
    "ReportCode", "IdCode", "Name", "ReportType", "EquityRow", "EquityColumn",
    "Value", "Thousands", "Cat", "ReportYear", "FVYear", "NACE_CODE",
    "NACE_NAME", "NACE_MAIN",
)

#: Without ``IdCode``/``FVYear`` a row can't be keyed; without ``ReportType``
#: there's no consolidation basis to key it on either. Without ``EquityRow``/
#: ``EquityColumn`` a row can't even be given a semantic meaning — unlike
#: ``lib.auditors``'s optional columns (e.g. a missing ``AuditOpinion`` still
#: leaves useful firm/fee data), a file missing either of these two would
#: yield literally nothing extractable, so failing loud here beats silently
#: returning zero rows.
REQUIRED_COLUMNS = ("IdCode", "FVYear", "ReportType", "EquityRow", "EquityColumn")

#: Older headers -> canonical name. Empty for now (only the FY2024 file
#: inspected) — same seam as ``lib/rms_nace.py``, kept for whichever future
#: year's file respells a column first.
COLUMN_ALIASES: dict[str, str] = {}


def resolve_header(names) -> list[str | None]:
    """Map a sheet's raw header cells to canonical names (``None`` = drop).

    Mirrors ``lib.auditors.resolve_header``.
    """
    raw = [(" ".join(str(c).split()) if c is not None else None) for c in names]
    present = {c for c in raw if c in COLUMNS}
    out: list[str | None] = []
    for cell in raw:
        if cell is None:
            out.append(None)
        elif cell in COLUMNS:
            out.append(cell)
        else:
            target = COLUMN_ALIASES.get(cell)
            out.append(target if (target and target not in present) else None)
    return out


# --------------------------------------------------------------------------
# Fixed vocabulary — measured against the real FY2024 file
# --------------------------------------------------------------------------

#: The "dividends declared" movement row.
EQUITY_ROW_DIVIDENDS = "დივიდენდის გამოცხადება"

#: The "effect of correction of identified errors" restatement row.
EQUITY_ROW_ERROR_CORRECTION = "გამოვლენილი შეცდომების შესწორების ეფექტი"

#: The "Total equity" column — every extracted figure reads off this column.
EQUITY_COLUMN_TOTAL = "სულ საკუთარი კაპიტალი"

#: Plain (non-adjusted) closing-balance row, year captured in group 1.
#: Deliberately does NOT match the "დაკორექტირებული ..." (adjusted) variant —
#: see module docstring.
_CLOSING_BALANCE_RE = re.compile(
    r"^ნაშთი საანგარიშგებო პერიოდის ბოლო თარიღისთვის - (\d{4})$"
)

#: ``ReportType`` (Georgian) -> ``is_consolidated``. Mirrors the individual
#: vs consolidated split ``lib/auditors.py`` keys on.
REPORT_TYPE_MAP: dict[str, bool] = {
    "ინდივიდუალური": False,
    "კონსოლიდირებული": True,
}

#: ``Thousands`` flag -> scale multiplier applied to ``Value``. See the
#: module docstring's cross-check table. Anything not in this map (a future
#: year's file using a new spelling) defaults to ``1.0`` in
#: :func:`scale_factor` — silent, so callers wanting to catch a genuinely new
#: spelling should use :func:`unexpected_thousands_flags` on the raw rows.
THOUSANDS_SCALE: dict[str | None, float] = {
    None: 1.0,
    ".ლარი": 1.0,
    ".000 ლარი": 1000.0,
}


def scale_factor(raw_thousands: object) -> float:
    """Scale multiplier for a row's raw ``Thousands`` flag. See module docstring."""
    return THOUSANDS_SCALE.get(clean_text(raw_thousands), 1.0)


def unexpected_thousands_flags(rows: list[dict]) -> set[str]:
    """Distinct ``Thousands`` values in ``rows`` outside the known set.

    Pure read-only diagnostic — callers (the builder script) can print a
    warning if this is non-empty, since :func:`scale_factor` silently treats
    an unrecognised flag as "no scaling", which is the wrong answer for
    anything that turns out to mean "thousands" the way ``'.000 ლარი'`` does.
    """
    known = set(THOUSANDS_SCALE) - {None}
    seen: set[str] = set()
    for r in rows:
        v = clean_text(r.get("Thousands"))
        if v is not None and v not in known:
            seen.add(v)
    return seen


def closing_year(equity_row: object) -> int | None:
    """Year suffix if ``equity_row`` is a plain (non-adjusted) closing-balance
    label, else ``None``."""
    s = clean_text(equity_row)
    if s is None:
        return None
    m = _CLOSING_BALANCE_RE.match(s)
    return int(m.group(1)) if m else None


@dataclass(frozen=True)
class EquityRecord:
    """Narrow per-``(IdCode, FVYear, ReportType)`` extraction — the fields
    ``scripts/build_rms_datasets.py`` writes to ``rms_equity``."""

    id_code: str
    fv_year: int
    is_consolidated: bool
    dividends_declared: float | None
    error_correction: float | None
    closing_total_equity: float | None


def _place(slot: dict, field: str, value: float) -> None:
    """Write ``value`` into ``slot[field]``, but never let an incoming ``0.0``
    overwrite an already-recorded nonzero value for the same field.

    **Why this exists — a measured bug, not a defensive nicety.** The
    ``EQUITY_ROW_ERROR_CORRECTION`` row is genuinely rendered TWICE per
    ``(IdCode, ReportType, FVYear)`` in the real FY2024 file — 1,759 of 1,761
    such keys carry it on exactly two rows (the SoCE template shows the
    earliest year's restatement reconciliation once feeding the "adjusted
    closing" balance and once again feeding the following year's "adjusted
    opening" balance, both tagged with the same FVYear in this flattened
    export). The second occurrence is, for every measured company that has a
    genuine correction, a zero placeholder. Naive last-row-wins (the
    original implementation) let that placeholder overwrite the real
    figure — of 150 keys with a nonzero correction on at least one of their
    two rows, 111 got silently zeroed. Dividends and closing-balance rows are
    NOT templated this way (>99.8% of their keys carry exactly one row), but
    the same guard is applied uniformly since it costs nothing on a
    single-row key and protects the handful of dividends/closing keys
    (measured: 2 and 1 respectively) that turned out to be duplicated too.

    A key with two GENUINELY DIFFERENT nonzero values (39 of the 150 above)
    still resolves to whichever is seen LAST — there is no evidence either
    reading is more authoritative when both are nonzero, so this preserves
    the pre-fix behaviour for that specific, rarer case.
    """
    if value == 0.0 and slot.get(field, 0.0) != 0.0:
        return
    slot[field] = value


def parse_rows(rows: list[dict]) -> list[EquityRecord]:
    """Parse raw Equity-ALL workbook rows (dicts keyed by :data:`COLUMNS`)
    into one :class:`EquityRecord` per ``(IdCode, FVYear, ReportType)``.

    Only ``EquityColumn == EQUITY_COLUMN_TOTAL`` rows are read; every other
    column is out of scope for this narrow extraction. A row's ``Value`` is
    parsed tolerantly (the real file mixes numeric and string-typed cells for
    the same column) and scaled per :func:`scale_factor` before being placed
    into whichever of the three tracked fields its ``EquityRow`` matches, via
    :func:`_place` (a zero never overwrites an already-recorded nonzero — see
    its docstring for the measured duplicate-row bug this guards against).

    ``None`` in a returned field means "no such row was present in the
    source" (e.g. a filing missing the dividends row entirely); ``0.0`` means
    "every row seen for this field explicitly reported zero" — neither is
    interchangeable with the other. A row whose ``ReportType`` isn't one of
    the two known Georgian labels is skipped outright: without knowing the
    consolidation basis there is no valid primary key to file it under.
    """
    order: list[tuple[str, int, bool]] = []
    acc: dict[tuple[str, int, bool], dict[str, float]] = {}

    for r in rows:
        id_code = clean_text(r.get("IdCode"))
        if not id_code:
            continue
        fv_year = to_int(r.get("FVYear"))
        if fv_year is None:
            continue
        is_consolidated = REPORT_TYPE_MAP.get(clean_text(r.get("ReportType")))
        if is_consolidated is None:
            continue
        if clean_text(r.get("EquityColumn")) != EQUITY_COLUMN_TOTAL:
            continue
        value = to_number(r.get("Value"))
        if value is None:
            continue
        value *= scale_factor(r.get("Thousands"))

        key = (id_code, fv_year, is_consolidated)
        if key not in acc:
            acc[key] = {}
            order.append(key)
        slot = acc[key]

        equity_row = clean_text(r.get("EquityRow"))
        if equity_row == EQUITY_ROW_DIVIDENDS:
            _place(slot, "dividends_declared", value)
        elif equity_row == EQUITY_ROW_ERROR_CORRECTION:
            _place(slot, "error_correction", value)
        elif closing_year(equity_row) == fv_year:
            _place(slot, "closing_total_equity", value)

    return [
        EquityRecord(
            id_code=k[0],
            fv_year=k[1],
            is_consolidated=k[2],
            dividends_declared=acc[k].get("dividends_declared"),
            error_correction=acc[k].get("error_correction"),
            closing_total_equity=acc[k].get("closing_total_equity"),
        )
        for k in order
    ]
