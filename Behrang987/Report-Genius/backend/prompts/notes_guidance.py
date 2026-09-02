"""User-facing guidance for the messy-notes input (surfaced via the API/UI).

Notes drive generation for D–J leaves and the D–J parent-intro units.
A/B/C and K/L/M/N stay scaffold / manual (see :mod:`backend.domain.section_scope`).
"""

from __future__ import annotations

NOTES_INPUT_GUIDANCE = """\
Notes are used for D–J element subsections (including energy J1–J5) and for
the parent introductions D–J (Outside, Inside, Services, Grounds, Legal,
Risks, Energy). Sections A/B/C/K/L/M/N are not note-driven — leave them
blank for manual fill or past-report/SP scaffold.

For parent D–J boxes, record group-level inspection method and limitations
(e.g. inspected from ground level, rear not accessible) — not chimney/roof
findings (those belong in D1/D2).

For best results in D–J leaves:
* One observation per line.
* State condition ratings explicitly (e.g. "CR2" or "Condition Rating 2").
* Write "NI" for elements that were not inspected.
* Spell out uncommon abbreviations at least once; common surveying shorthand
  (dpc, rwp, uPVC, w/c) is understood.
* Keep each line about one element only — do not mix roof and gutter findings
  on one line.
"""
