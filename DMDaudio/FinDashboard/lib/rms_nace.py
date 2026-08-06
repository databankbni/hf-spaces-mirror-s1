"""NACE activity-code data model (reportal RMS ``NACE <year>.xlsx`` bulk files) —
pure, no Streamlit/DB.

Source: the per-year ``NACE_<id>.xlsx`` bulk file from ``rms.reportal.ge``
(request-gated, same portal as ``lib/auditors.py``'s ``Auditors`` files). Long
format, one row per ``(company, NACE Rev.2 code)`` pair. Measured against the
real FY2024 file (``NACE_272.xlsx``, 105,827 rows × 10 cols):

* ``ReportCode, IdCode, OrgName, LegalForm, NACE_CODE, NACE_NAME, ReportYear,
  Cat, Status, NACE_MAIN`` — confirmed header order, no drift observed yet
  (only one year inspected so far; :func:`resolve_header` exists for the same
  reason ``lib/auditors.py`` needed it — header spelling drifted across the
  Auditors files' years, so treat this as a when-not-if for NACE too).

Two source quirks this module exists to absorb, both measured on the FY2024
file:

* **93,945 of 105,826 non-blank rows have no ``IdCode``.** Category IV is
  anonymised at source in this year's file — no IdCode, no OrgName, code and
  name columns hold the literal string ``"NULL"``. These rows can never be
  attributed to a company and are dropped. (Category IV anonymisation is
  itself per-year, not universal — the FY2022 ``Auditors`` file identifies
  Category IV fully. Don't assume this file's behaviour generalises without
  checking a given year's numbers.)
* **819 of the remaining 11,881 IdCode-bearing rows have no ``NACE_CODE``**
  (literal ``"NULL"``). These are a company's *consolidated* ("... ჯგუფი")
  filing declaration — Georgian filers list NACE codes once, on the
  individual-basis row, and the parallel group-basis row for the same company
  carries no code list of its own. ``Cat`` on these rows is always one of
  ``{I ჯგუფი, II ჯგუფი, III ჯგუფი, IV ჯგუფი}`` (n=807) plus a handful of
  genuinely blank individual-basis rows (n=12). Dropped for the same reason as
  the no-IdCode rows: a NULL code can't be a primary-key column.

``NACE_CODE`` is a NACE Rev.2 code, 4 or 5 digits (measured range 1111–99000).
In the real file every non-NULL code is stored as an Excel **number**
(``openpyxl`` returns a Python ``int``), so any leading zero a code might
carry was already lost by the source tool before this module ever sees the
cell — :func:`normalize_code` cannot reconstruct a width it was never given.
If a future year's file stores the column as text instead (plausible, given
the header-drift precedent), a leading zero present in that text IS
preserved — :func:`normalize_code` only strips whitespace and never re-pads.

**Ordering caveat (do not build a "primary sector" flag from this table):**
codes are not flagged primary vs secondary, and the first-listed code is not
reliably the company's main activity. Example measured in the survey doc
(``docs/reviews/2026-08-05-reportal-rms-untapped-datasets.md``, §A4):
``200075113`` (a winery) lists ``91020`` *museum activities* first, ahead of
its actual wine-production and retail codes. Treat every row as one
equal-weight fact about the company, never as a ranked list.
"""
from __future__ import annotations

from dataclasses import dataclass

from lib.auditors import clean_text, to_int

# --------------------------------------------------------------------------
# Header schema
# --------------------------------------------------------------------------

#: Canonical field names, as spelled in the FY2024 file.
COLUMNS = (
    "ReportCode", "IdCode", "OrgName", "LegalForm", "NACE_CODE", "NACE_NAME",
    "ReportYear", "Cat", "Status", "NACE_MAIN",
)

#: Without these a row cannot be keyed at all. ``NACE_CODE`` is deliberately
#: NOT required at the file level — plenty of real rows lack it per-row (see
#: module docstring), and that is a per-row skip, not a whole-file error.
REQUIRED_COLUMNS = ("ReportYear", "IdCode")

#: Older headers -> canonical name. Empty for now (only FY2024 inspected), but
#: kept as a seam — ``lib/auditors.py``'s ``Auditors`` files taught us header
#: spelling drifts across RMS bulk-file years, so a future NACE year landing
#: with a respelled column should extend this map rather than a new module.
COLUMN_ALIASES: dict[str, str] = {}


def resolve_header(names) -> list[str | None]:
    """Map a sheet's raw header cells to canonical names (``None`` = drop).

    Mirrors ``lib.auditors.resolve_header``: a canonical name already present
    wins over an alias pointing at it, so a file carrying both spellings keeps
    the canonical column.
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
# Field normalisation
# --------------------------------------------------------------------------
def normalize_code(raw: object) -> str | None:
    """Normalise a ``NACE_CODE`` cell to a string, preserving any leading
    zero the source already carries.

    The real file stores every genuine code as an Excel number (Python
    ``int``/``float``), so there is no leading zero to preserve there — this
    just renders it back to a plain digit string. A future year storing the
    column as text is handled without stripping a leading zero that text may
    carry (unlike ``int()``, which would).
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return str(raw)
    if isinstance(raw, float):
        if raw != int(raw):
            return None  # not a whole number — not a real NACE code
        return str(int(raw))
    s = " ".join(str(raw).split())
    if not s or s.upper() == "NULL":
        return None
    return s


@dataclass(frozen=True)
class NaceRow:
    """One ``(company, NACE code)`` fact for a given filing year."""

    id_code: str
    nace_code: str
    nace_name: str | None
    nace_main: str | None
    report_year: int
    category: str | None


def parse_rows(rows: list[dict]) -> list[NaceRow]:
    """Parse raw NACE workbook rows (dicts keyed by :data:`COLUMNS`) into
    :class:`NaceRow` records, one per unique ``(IdCode, NACE_CODE,
    ReportYear)``.

    Skipped, in order:

    * rows with no ``IdCode`` — Category IV anonymised at source (93,945 of
      105,826 rows in the FY2024 file).
    * rows with no ``NACE_CODE`` — the company's *consolidated*-basis
      declaration, which carries no code list of its own (819 rows in the
      FY2024 file; see module docstring).
    * rows with no parseable ``ReportYear``.

    A duplicate key (observed once in the FY2024 file: one company listing
    the same code twice) resolves last-row-wins; insertion order of the first
    occurrence is preserved for the rest, so a run's output is deterministic.
    """
    order: list[tuple[str, str, int]] = []
    by_key: dict[tuple[str, str, int], NaceRow] = {}

    for r in rows:
        id_code = clean_text(r.get("IdCode"))
        if not id_code:
            continue
        code = normalize_code(r.get("NACE_CODE"))
        if not code:
            continue
        report_year = to_int(r.get("ReportYear"))
        if report_year is None:
            continue

        key = (id_code, code, report_year)
        if key not in by_key:
            order.append(key)
        by_key[key] = NaceRow(
            id_code=id_code,
            nace_code=code,
            nace_name=clean_text(r.get("NACE_NAME")),
            nace_main=clean_text(r.get("NACE_MAIN")),
            report_year=report_year,
            category=clean_text(r.get("Cat")),
        )

    return [by_key[k] for k in order]
