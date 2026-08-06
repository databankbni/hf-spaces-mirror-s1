"""Convert the openbible.info cross-reference TSV into a compact lookup.

Output: data/crossrefs.json — { "<book_no>:<ch>:<v>": ["<book_no>:<ch>:<v>", ...] }
keeping the top-voted references per verse. The API resolves each target key
to its ref + text from the index at request time, so we store keys only.

Source (download first): https://a.openbible.info/data/cross-references.zip
Data: openbible.info cross references, CC-BY.
"""
import json
import re
from collections import defaultdict
from pathlib import Path

SRC = Path("/tmp/cross_references.txt")
# Outside data/ so it isn't shadowed by a mounted data volume in Docker.
OUT = Path(__file__).parent / "crossrefs.json"
TOP_N = 8

# OSIS book codes in canonical order (Genesis=1 ... Revelation=66).
OSIS = [
    "Gen", "Exod", "Lev", "Num", "Deut", "Josh", "Judg", "Ruth", "1Sam",
    "2Sam", "1Kgs", "2Kgs", "1Chr", "2Chr", "Ezra", "Neh", "Esth", "Job",
    "Ps", "Prov", "Eccl", "Song", "Isa", "Jer", "Lam", "Ezek", "Dan", "Hos",
    "Joel", "Amos", "Obad", "Jonah", "Mic", "Nah", "Hab", "Zeph", "Hag",
    "Zech", "Mal", "Matt", "Mark", "Luke", "John", "Acts", "Rom", "1Cor",
    "2Cor", "Gal", "Eph", "Phil", "Col", "1Thess", "2Thess", "1Tim", "2Tim",
    "Titus", "Phlm", "Heb", "Jas", "1Pet", "2Pet", "1John", "2John", "3John",
    "Jude", "Rev",
]
OSIS_NO = {code: i + 1 for i, code in enumerate(OSIS)}
_REF = re.compile(r"^([1-3]?[A-Za-z]+)\.(\d+)\.(\d+)")


def to_key(osis_ref: str) -> str | None:
    # Range targets ("Gen.1.1-Gen.1.5") -> take the start verse.
    m = _REF.match(osis_ref.split("-")[0])
    if not m:
        return None
    book, ch, v = m.group(1), m.group(2), m.group(3)
    no = OSIS_NO.get(book)
    return f"{no}:{ch}:{v}" if no else None


def build():
    if not SRC.exists():
        raise SystemExit(
            "Missing /tmp/cross_references.txt — download + unzip "
            "https://a.openbible.info/data/cross-references.zip first."
        )
    scored: dict[str, list] = defaultdict(list)
    with open(SRC, encoding="utf-8") as f:
        next(f)  # header
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            src, dst, votes = parts[0], parts[1], parts[2]
            try:
                votes = int(votes)
            except ValueError:
                continue
            if votes <= 0:
                continue
            sk, dk = to_key(src), to_key(dst)
            if sk and dk and sk != dk:
                scored[sk].append((votes, dk))

    out: dict[str, list[str]] = {}
    for key, items in scored.items():
        items.sort(reverse=True)
        seen, refs = set(), []
        for _, dk in items:
            if dk not in seen:
                seen.add(dk)
                refs.append(dk)
            if len(refs) >= TOP_N:
                break
        out[key] = refs

    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print(f"Wrote {len(out)} verses with cross-references -> {OUT.name} "
          f"({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    build()
