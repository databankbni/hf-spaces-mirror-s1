# -*- coding: ascii -*-
"""
gedcom_parser.py -- Minimal robust GEDCOM 5.5/5.5.1 parser (Layer K1 input).

MemorialWiki-4C, module M1a.
Parses INDI and FAM records into plain Python dicts. No external deps.

Supported per-individual fields : NAME, SEX, BIRT/DATE, DEAT/DATE, FAMC, FAMS
Supported per-family fields     : HUSB, WIFE, CHIL, MARR/DATE

Date handling:
  - "12 MAR 1948", "MAR 1948", "1948" -> {day, month, year}
  - Qualifiers ABT / EST / CAL / BEF / AFT / INT are recorded in 'qual'
    (comparison semantics are decided downstream, conservatively).
  - "BET 1900 AND 1905" -> takes the first date, qual='bet'.
  - Unparseable dates   -> all components None, qual='unparsed',
    raw string preserved in 'raw'.

ASCII-only source file (GBK-safe). Python 3.10, conda env: llmwiki.
"""

import re

MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

QUALIFIERS = ("ABT", "EST", "CAL", "BEF", "AFT", "INT")

LINE_RE = re.compile(r"^\s*(\d+)\s+(@[^@]+@\s+)?(\S+)(?:\s(.*))?$")


def parse_date(raw):
    """Parse a GEDCOM DATE value into a partial-date dict."""
    result = {"year": None, "month": None, "day": None,
              "qual": None, "raw": raw}
    if not raw:
        result["qual"] = "unparsed"
        return result
    s = raw.strip().upper()

    # BET <date1> AND <date2>: keep the earlier bound, flag it.
    m = re.match(r"^BET\.?\s+(.*?)\s+AND\s+.*$", s)
    if m:
        s = m.group(1)
        result["qual"] = "bet"

    for q in QUALIFIERS:
        if s.startswith(q + " ") or s.startswith(q + "."):
            if result["qual"] is None:
                result["qual"] = q.lower()
            s = s[len(q):].lstrip(". ")
            break

    tokens = s.split()
    try:
        if len(tokens) == 3 and tokens[1] in MONTHS:
            result["day"] = int(tokens[0])
            result["month"] = MONTHS[tokens[1]]
            result["year"] = int(tokens[2])
        elif len(tokens) == 2 and tokens[0] in MONTHS:
            result["month"] = MONTHS[tokens[0]]
            result["year"] = int(tokens[1])
        elif len(tokens) == 1:
            result["year"] = int(tokens[0])
        else:
            result["qual"] = "unparsed"
    except (ValueError, KeyError):
        result["year"] = None
        result["month"] = None
        result["day"] = None
        result["qual"] = "unparsed"
    return result


def _new_indi(xref):
    return {"id": xref, "name": None, "sex": None,
            "birth": None, "death": None,
            "famc": [], "fams": []}


def _new_fam(xref):
    return {"id": xref, "husb": None, "wife": None,
            "chil": [], "marr": None}


def parse_gedcom(path):
    """
    Parse a GEDCOM file.

    Returns (individuals, families, issues):
      individuals : dict xref -> indi dict
      families    : dict xref -> fam dict
      issues      : list of parse-level problem strings (C4 raw material)
    """
    individuals = {}
    families = {}
    issues = []

    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        raw_lines = f.readlines()

    current = None          # current top-level record dict
    current_kind = None     # 'INDI' | 'FAM' | None
    context = None          # 'BIRT' | 'DEAT' | 'MARR' | None

    for lineno, raw in enumerate(raw_lines, start=1):
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        m = LINE_RE.match(line)
        if not m:
            issues.append("line %d: unparseable GEDCOM line: %r"
                          % (lineno, line))
            continue
        level = int(m.group(1))
        xref = m.group(2).strip().strip("@") if m.group(2) else None
        tag = m.group(3).strip()
        value = m.group(4).strip() if m.group(4) else ""

        # value may itself be an @XREF@ pointer
        pointer = None
        pm = re.match(r"^@([^@]+)@$", value)
        if pm:
            pointer = pm.group(1)

        if level == 0:
            context = None
            if tag == "INDI" and xref:
                current = _new_indi(xref)
                individuals[xref] = current
                current_kind = "INDI"
            elif tag == "FAM" and xref:
                current = _new_fam(xref)
                families[xref] = current
                current_kind = "FAM"
            else:
                current = None
                current_kind = None
            continue

        if current is None:
            continue

        if level == 1:
            context = None
            if current_kind == "INDI":
                if tag == "NAME" and current["name"] is None:
                    current["name"] = value.replace("/", " ").strip()
                    current["name"] = re.sub(r"\s+", " ", current["name"])
                elif tag == "SEX":
                    v = value[:1].upper()
                    current["sex"] = {"M": "m", "F": "f"}.get(v, "u")
                elif tag == "BIRT":
                    context = "BIRT"
                elif tag == "DEAT":
                    context = "DEAT"
                elif tag == "FAMC" and pointer:
                    current["famc"].append(pointer)
                elif tag == "FAMS" and pointer:
                    current["fams"].append(pointer)
            elif current_kind == "FAM":
                if tag == "HUSB" and pointer:
                    current["husb"] = pointer
                elif tag == "WIFE" and pointer:
                    current["wife"] = pointer
                elif tag == "CHIL" and pointer:
                    current["chil"].append(pointer)
                elif tag == "MARR":
                    context = "MARR"
            continue

        if level == 2 and tag == "DATE" and context:
            d = parse_date(value)
            if context == "BIRT":
                current["birth"] = d
            elif context == "DEAT":
                current["death"] = d
            elif context == "MARR":
                current["marr"] = d

    # referential integrity (C1 at the structural level)
    for fid, fam in families.items():
        for role in ("husb", "wife"):
            pid = fam[role]
            if pid and pid not in individuals:
                issues.append("family %s: %s points to unknown individual %s"
                              % (fid, role.upper(), pid))
        for cid in fam["chil"]:
            if cid not in individuals:
                issues.append("family %s: CHIL points to unknown "
                              "individual %s" % (fid, cid))
    for pid, ind in individuals.items():
        for fid in ind["famc"] + ind["fams"]:
            if fid not in families:
                issues.append("individual %s: reference to unknown "
                              "family %s" % (pid, fid))

    return individuals, families, issues
