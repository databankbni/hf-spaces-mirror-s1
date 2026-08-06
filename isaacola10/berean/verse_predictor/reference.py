"""Parse a spoken/typed Bible reference like "John 3:16" or "first cor 13 4".

Turns free text into (book_index, chapter, verse|None). book_index is the
1-based canonical position (Genesis=1 ... Revelation=66), so it maps cleanly
onto whatever book names a translation uses (English, Spanish, ...).
"""
import re

# (canonical index, display name, [abbreviations]) in KJV/Protestant order.
_BOOKS = [
    (1, "Genesis", ["gen", "ge", "gn"]),
    (2, "Exodus", ["exod", "exo", "ex"]),
    (3, "Leviticus", ["lev", "lv"]),
    (4, "Numbers", ["num", "nu", "nm", "nb"]),
    (5, "Deuteronomy", ["deut", "deu", "dt"]),
    (6, "Joshua", ["josh", "jos", "jsh"]),
    (7, "Judges", ["judg", "jdg", "jg"]),
    (8, "Ruth", ["rth", "ru"]),
    (9, "Samuel", ["sam", "sa"], 1),
    (10, "Samuel", ["sam", "sa"], 2),
    (11, "Kings", ["kings", "kgs", "ki"], 1),
    (12, "Kings", ["kings", "kgs", "ki"], 2),
    (13, "Chronicles", ["chron", "chr", "ch"], 1),
    (14, "Chronicles", ["chron", "chr", "ch"], 2),
    (15, "Ezra", ["ezr"]),
    (16, "Nehemiah", ["neh"]),
    (17, "Esther", ["esth", "est"]),
    (18, "Job", ["jb"]),
    (19, "Psalms", ["psalm", "psa", "ps", "psm", "pslm"]),
    (20, "Proverbs", ["prov", "prv", "pr"]),
    (21, "Ecclesiastes", ["eccl", "ecc", "qoh"]),
    (22, "Song of Solomon", ["song", "song of songs", "sos", "canticles"]),
    (23, "Isaiah", ["isa"]),
    (24, "Jeremiah", ["jer", "je"]),
    (25, "Lamentations", ["lam", "la"]),
    (26, "Ezekiel", ["ezek", "eze", "ezk"]),
    (27, "Daniel", ["dan", "da", "dn"]),
    (28, "Hosea", ["hos", "ho"]),
    (29, "Joel", ["joe", "jl"]),
    (30, "Amos", ["amos", "amo"]),
    (31, "Obadiah", ["obad", "ob"]),
    (32, "Jonah", ["jon", "jnh"]),
    (33, "Micah", ["mic", "mc"]),
    (34, "Nahum", ["nah", "na"]),
    (35, "Habakkuk", ["hab", "hb"]),
    (36, "Zephaniah", ["zeph", "zep", "zp"]),
    (37, "Haggai", ["hag", "hg"]),
    (38, "Zechariah", ["zech", "zec", "zc"]),
    (39, "Malachi", ["mal", "ml"]),
    (40, "Matthew", ["matt", "mat", "mt"]),
    (41, "Mark", ["mrk", "mk", "mr"]),
    (42, "Luke", ["luk", "lk"]),
    (43, "John", ["jhn", "joh", "jn"]),
    (44, "Acts", ["act", "ac"]),
    (45, "Romans", ["rom", "ro", "rm"]),
    (46, "Corinthians", ["cor"], 1),
    (47, "Corinthians", ["cor"], 2),
    (48, "Galatians", ["gal", "ga"]),
    (49, "Ephesians", ["eph", "ephes"]),
    (50, "Philippians", ["phil", "php", "pp"]),
    (51, "Colossians", ["col", "co"]),
    (52, "Thessalonians", ["thess", "thes", "th"], 1),
    (53, "Thessalonians", ["thess", "thes", "th"], 2),
    (54, "Timothy", ["tim"], 1),
    (55, "Timothy", ["tim"], 2),
    (56, "Titus", ["tit"]),
    (57, "Philemon", ["philem", "phm", "pm"]),
    (58, "Hebrews", ["heb"]),
    (59, "James", ["jas", "jm"]),
    (60, "Peter", ["pet", "pe"], 1),
    (61, "Peter", ["pet", "pe"], 2),
    (62, "John", ["jhn", "joh", "jn"], 1),
    (63, "John", ["jhn", "joh", "jn"], 2),
    (64, "John", ["jhn", "joh", "jn"], 3),
    (65, "Jude", ["jud", "jd"]),
    (66, "Revelation", ["rev", "re", "apocalypse"]),
]

# Word forms for the leading number of numbered books (1/2/3 ...).
_NUM_PREFIXES = {
    1: ["1", "1st", "first", "i", "one"],
    2: ["2", "2nd", "second", "ii", "two"],
    3: ["3", "3rd", "third", "iii", "three"],
}

_WORD_NUM = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", s.lower())).strip()


def _build_aliases():
    """alias string -> canonical book index. Longest aliases match first."""
    aliases: dict[str, int] = {}

    def add(text: str, idx: int):
        key = _norm(text)
        if key and (key not in aliases):
            aliases[key] = idx

    for entry in _BOOKS:
        idx, name, abbrevs = entry[0], entry[1], entry[2]
        num = entry[3] if len(entry) > 3 else None
        names = [name] + abbrevs
        if num:
            for prefix in _NUM_PREFIXES[num]:
                for n in names:
                    add(f"{prefix} {n}", idx)
                    add(f"{prefix}{n}", idx)
        else:
            for n in names:
                add(n, idx)
    return aliases


_ALIASES = _build_aliases()
# Match longest alias first so "1 john" beats "john".
_ALIAS_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(a) for a in sorted(_ALIASES, key=len, reverse=True)) + r")\b"
)


def _words_to_int(text: str) -> int | None:
    parts = text.split()
    if not parts:
        return None
    total = 0
    current = 0
    for p in parts:
        if p.isdigit():
            current += int(p)
        elif p in _WORD_NUM:
            v = _WORD_NUM[p]
            if v == 100:
                current = max(1, current) * 100
            else:
                current += v
        else:
            return None
    return total + current


def _first_int(text: str) -> int | None:
    """First integer in a phrase — digit form takes precedence over words."""
    if not text:
        return None
    m = re.search(r"\d+", text)
    if m:
        return int(m.group(0))
    return _words_to_int(text.strip())


def parse_reference(query: str) -> tuple[int, int, int | None] | None:
    """Return (book_index, chapter, verse|None) or None if not a reference.

    Handles digits and spelled-out numbers, "chapter"/"verse" markers, and
    the ASR-friendly forms like "Matthew chapter five verse two" or
    "John three sixteen"."""
    norm = _norm(query)
    # Consider every alias hit and pick the last one whose remainder yields a
    # valid chapter — later hits are usually the real reference (e.g. in
    # "as it is written in psalm 23", the "psalm" hit is the real book).
    hits = list(_ALIAS_PATTERN.finditer(norm))
    if not hits:
        return None
    best: tuple[int, int, int | None] | None = None
    for m in hits:
        cand = _parse_after_alias(norm, m)
        if cand is not None:
            best = cand
    return best


def _parse_after_alias(norm: str, m) -> tuple[int, int, int | None] | None:
    idx = _ALIASES[m.group(1)]
    rest = norm[m.end():].strip()
    if not rest:
        return None  # bare book name — no chapter info, not a full reference

    # Try to split on explicit chapter/verse markers first: this is what makes
    # "chapter five verse two" work (five -> 5, two -> 2).
    ch_part, vs_part = rest, ""
    marker = re.search(r"\b(verse|verses|vs|v)\b", rest)
    if marker:
        ch_part = rest[:marker.start()].strip()
        vs_part = rest[marker.end():].strip()
    ch_part = re.sub(r"\bchapter\b", " ", ch_part).strip()
    ch_part = re.sub(r"\s+", " ", ch_part)

    # Numeric colon/dot form (highest priority — most explicit): "3:16", "3.16".
    m_colon = re.search(r"(\d+)\s*[:.]\s*(\d+)", rest)
    if m_colon:
        return (idx, int(m_colon.group(1)), int(m_colon.group(2)))

    chapter = _first_int(ch_part)
    if chapter is None:
        # No chapter after the book name at all.
        nums = re.findall(r"\d+", rest)
        if nums:
            chapter = int(nums[0])
            verse = int(nums[1]) if len(nums) > 1 else None
            return (idx, chapter, verse)
        n = _words_to_int(rest)
        return (idx, n, None) if n is not None else None

    verse: int | None = None
    if vs_part:
        verse = _first_int(vs_part)
    else:
        # No explicit "verse" word — if two consecutive numbers appear, treat
        # the second as the verse ("john 3 16" -> John 3:16).
        nums = re.findall(r"\d+", rest)
        if len(nums) >= 2:
            verse = int(nums[1])
        else:
            # "John three sixteen": try splitting spelled-out words into a
            # (chapter, verse) pair. Skip when the whole thing is naturally a
            # single chapter ("psalm twenty three" -> Psalm 23), which we
            # detect by "no word > ten in the tail" (i.e. "twenty three" is
            # a compound number, not chapter-then-verse).
            words = ch_part.split()
            if len(words) >= 3 or (
                len(words) == 2 and _WORD_NUM.get(words[0], 0) <= 12
                and _WORD_NUM.get(words[1], 0) <= 30
                and words[0] not in ("twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
            ):
                for i in range(1, len(words)):
                    left = _words_to_int(" ".join(words[:i]))
                    right = _words_to_int(" ".join(words[i:]))
                    if left is not None and right is not None and left >= 1 and right >= 1:
                        chapter, verse = left, right
                        break
    return (idx, chapter, verse)


def format_reference(book_no: int, chapter: int, verse: int | None,
                     style: str = "colon") -> str:
    """Render (book_no, chapter, verse) as 'Matthew 5:2' (colon) or
    'Matthew 5v2' (v-style). Both are common ways to write scripture refs."""
    name = None
    for entry in _BOOKS:
        if entry[0] == book_no:
            name = entry[1]
            num = entry[3] if len(entry) > 3 else None
            if num:
                name = ("I " if num == 1 else "II " if num == 2 else "III ") + name
            break
    if name is None:
        return ""
    if verse is None:
        return f"{name} {chapter}"
    sep = "v" if style == "v" else ":"
    return f"{name} {chapter}{sep}{verse}"


if __name__ == "__main__":
    for q in [
        "John 3:16", "first corinthians 13", "psalm 23", "jn 3 16",
        "second timothy 3 verse 16", "the lord is my shepherd", "revelation 22 21",
    ]:
        print(f"{q!r:40} -> {parse_reference(q)}")
