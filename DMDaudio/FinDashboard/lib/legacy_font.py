"""Recover Georgian text from annual-report extracts whose text layer is not
Unicode Georgian ("mojibake").

About 11% of the ``Raw Data/report_text/*.md`` corpus written by
``scripts/extract_report_texts.py`` contains no Georgian codepoints at all, so
``lib.activity_note`` finds no activity statement and the whole sector pipeline
skips those companies silently. This module decides, per report, *which* of the
non-Unicode representations it is looking at, and reverses the ones that are
reversible.

Three representations were identified in the corpus (2026-07-30), and the split
between them is the whole point of this module:

1. ``acadnusx`` — the report was typeset in a pre-Unicode Georgian font of the
   AcadNusx / LitNusx family. Those fonts are ordinary Latin-encoded fonts whose
   glyphs happen to be Georgian, laid out on the Georgian *transliteration*
   keyboard (``a``→ა, ``T``→თ, ``S``→შ, …), so the extracted text is a clean,
   deterministic monoalphabetic substitution — literally readable as
   "finansuri angariSgeba". Fully reversible with :data:`ACADNUSX`.

2. ``shift`` — the font is a subset whose glyph ids are the Georgian codepoints
   minus a constant, so the extractor emits a whole block of some *other* script
   shifted by a fixed offset. Three offsets occur: ``+0x1000`` (Georgian with the
   high byte lost, landing in Latin-1 Supplement), ``+0xE28`` (Spacing Modifier
   Letters, ``ˀʶʹ`` = შპს) and ``+0xA46`` (Arabic). Reversible by adding the
   offset back; the offset is *solved* per file, not hardcoded, so a fourth one
   costs nothing.

3. ``glyph_noise`` — the overwhelming majority, and NOT a cipher. See
   :func:`repeat_ratio` for the measurement that settles it: these files were
   OCR'd from scans by a Latin-alphabet engine, so each Georgian glyph was read
   as whatever Latin/digit/punctuation shape it most resembled — ნ as ``6``, უ as
   ``g``, ა as ``.:``, ფ as ``<z3`` — *inconsistently*, several renderings of the
   same word inside one document (``და`` appears as ``qr``, ``qgr``, ``qrr``,
   ``er``, ``qgt``, ``qg.:``). No character table can invert a non-deterministic
   many-to-one map, and no byte-level recoding can either (a recoding is a
   bijection on characters and therefore preserves the repeat structure that
   these files demonstrably do not have). Recovering them needs the *images*
   re-OCR'd with Georgian — ``scripts/ocr_scanned_reports.py``, not this module.

Acceptance is measured, never assumed: a candidate decode is kept only if it
raises the number of tokens that are real Georgian words (:data:`COMMON_WORDS`,
the 200 most frequent tokens of the clean corpus) and clears
:data:`MIN_WORD_RATE`. On the corpus that gate separates the classes with no
overlap at all — decoded files score 0.41–0.59 against 0.36–0.61 for native
Unicode reports, while ``glyph_noise`` files score 0.000–0.002.

Pure/stdlib-only and fully testable: no DB, no network, no Streamlit. House
style follows :mod:`lib.activity_note` / :mod:`lib.note_quality`.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

__all__ = [
    "ACADNUSX", "ACADNUSX_REVERSE", "BOILERPLATE_CRIBS", "COMMON_WORDS", "KINDS",
    "Recovery", "WordScore",
    "acadnusx_decode", "acadnusx_encode", "classify", "crib_hits", "decode_text",
    "decode_report_markdown", "english_rate", "find_shift", "georgian_ratio",
    "repeat_ratio", "shift_decode", "shift_offsets", "word_score",
]

GEORGIAN_LO, GEORGIAN_HI = 0x10A0, 0x10FF
#: Mkhedruli ა..ჰ — the only letters a modern Georgian filing uses.
_MKHEDRULI_LO, _MKHEDRULI_HI = 0x10D0, 0x10F0

_GEO_CHAR = re.compile(r"[Ⴀ-ჿ]")
_GEO_TOKEN = re.compile(r"[Ⴀ-ჿ]{3,}")
_LAT_TOKEN = re.compile(r"[A-Za-z]{2,}")
_WS = re.compile(r"\s+")


# --------------------------------------------------------------------------- #
# 1. AcadNusx — the Georgian transliteration keyboard layout.
#
# Verified against the corpus rather than taken from a font table: 80 files
# decode under it, and the 33 assignments below are exactly the ones that make
# the universal filing boilerplate appear ("finansuri angariSgeba" →
# ფინანსური ანგარიშგება, "saaRricxvo politika" → სააღრიცხვო პოლიტიკა).
#
# Uppercase aliases (A→ა, B→ბ, …, for the letters whose capital is not already
# taken by თ/ჟ/ღ/შ/ჩ/ძ/ჭ) were TRIED and rejected: they left the median
# known-word rate unchanged (0.965 → 0.962) while mangling the English pages of
# bilingual filings. The capitals in these documents are set in a companion
# *Mtavruli* font that the extractor renders as the same lowercase codes.
# --------------------------------------------------------------------------- #
ACADNUSX: dict[str, str] = {
    "a": "ა", "b": "ბ", "g": "გ", "d": "დ", "e": "ე", "v": "ვ", "z": "ზ",
    "T": "თ", "i": "ი", "k": "კ", "l": "ლ", "m": "მ", "n": "ნ", "o": "ო",
    "p": "პ", "J": "ჟ", "r": "რ", "s": "ს", "t": "ტ", "u": "უ", "f": "ფ",
    "q": "ქ", "R": "ღ", "y": "ყ", "S": "შ", "C": "ჩ", "c": "ც", "Z": "ძ",
    "w": "წ", "W": "ჭ", "x": "ხ", "j": "ჯ", "h": "ჰ",
}
ACADNUSX_REVERSE: dict[str, str] = {v: k for k, v in ACADNUSX.items()}

#: Phrases that appear in essentially every Georgian filing. Used as a cheap
#: sanity check on a candidate decode and as the crib set for the tests; the
#: acceptance decision itself is made by :func:`word_score`, which does not
#: depend on any single phrase being present.
BOILERPLATE_CRIBS: tuple[str, ...] = (
    "საიდენტიფიკაციო კოდი",
    "შეზღუდული პასუხისმგებლობის საზოგადოება",
    "ფინანსური ანგარიშგება",
    "ძირითადი საქმიანობა",
    "ბუღალტრული აღრიცხვის",
    "სააღრიცხვო პოლიტიკა",
    "დამოუკიდებელი აუდიტორის",
)

# The 200 most frequent >=3-letter Georgian tokens in the ~5,950 clean
# Georgian-Unicode reports of the corpus. Deliberately a closed, embedded list:
# the module stays pure, and the resulting score is comparable across runs.
COMMON_WORDS: frozenset[str] = frozenset("""
    ფინანსური წლის სხვა კომპანიის ანგარიშგების ვალდებულებები შპს ფულადი ანგარიშგება არის
    კომპანია რომელიც ძირითადი სულ აქტივები მოგება სავაჭრო რომ აქტივის ფინანსურ ხარჯი
    პერიოდის მიერ საანგარიშგებო როდესაც შემოსავალი საგადასახადო დეკემბერი საპროცენტო
    შენიშვნები ღირებულება რომლებიც ზარალი ხარჯები დეკემბრის ხდება მდგომარეობით კაპიტალი
    მომსახურების აქტივების დასრულებული როგორც შესაბამისად საბალანსო საოპერაციო მიღებული
    მოგების ლარი გაუფასურების ღირებულებით ანგარიშგებაში საკრედიტო აღიარდება მიმდინარე
    საქართველოს დაკავშირებული ღირებულების მისი შემთხვევაში წმინდა ზარალის წარმოადგენს
    სააღრიცხვო შორის ყველა რისკი ლარში მოიცავს დეკემბერს მოთხოვნები ვალდებულებების სრული
    აღიარება განმავლობაში საიჯარო მათი ფასს სახსრები განმარტებითი წლისთვის ვალდებულების
    მნიშვნელოვანი ასევე მიხედვით ვალდებულება ფული არსებული ცვეთა შემოსავლის კაპიტალის
    სესხები საწარმოს ფულის მათ საშუალებები შემდეგ კომპანიას აქვს კონსოლიდირებული
    წარმოდგენილია შესახებ ეკონომიკური საფუძველზე რაც რეალური შეფასება გრძელვადიანი იჯარის
    ზარალში გადახდილი არსებობს საქმიანობის ვალუტაში მდგომარეობის გარდა შეიძლება საკუთარი
    საშუალებების სახსრების ჯგუფის ბოლოს არა მოკლევადიანი სასარგებლო მოსალოდნელი აისახება
    ჯგუფი ვადის რისკის ეკვივალენტები აღირიცხება დაკავშირებულ გადასახადის შედეგად თანხები
    მაშინ აქტივი გადასახადი მარაგები სამართლიანი შესაბამისი არამატერიალური ნაკადების
    სავალუტო პერიოდში დირექტორი საერთაშორისო საქონლის აღნიშნული განაკვეთის ხელმძღვანელობის
    შესაძლებელია ღირებულებას გამოყენების მის თვითღირებულება საერთო ცვლილებები წელი გაცემული
    აღიარების ინფორმაცია შემდგომი შენიშვნა არსებითი უცხოურ ეფექტური საბაზრო საქმიანობიდან
    გამოყენებით საწესდებო ვალუტა თავდაპირველი შეფასების წელს უნდა საწარმო მოგებაში აუდიტის
    რისკების წლისათვის სარგებლის მხოლოდ დაგროვილი ბანკის მომავალი ცვეთის საინვესტიციო
    პოლიტიკა რომლის მარაგების შემდეგი პოლიტიკის ჩვენი მოსალოდნელია სტანდარტების ნაშთი
    ხარჯების საქართველო გაგრძელება
""".split())

# English function/finance words, for leaving the English pages of a bilingual
# filing alone. A short list is enough — the question is only "is this line
# English prose", never "how good is the English".
_ENGLISH_WORDS: frozenset[str] = frozenset("""
    the of and to in for as at is are be was were on with from by not or an it its
    this that these those any all such other has have had will would may
    financial statements statement december january year ended company auditor
    report reports notes note income cash flow flows assets liabilities equity
    total revenue profit loss tax taxes independent management accounting policies
    thousands amounts value fair current period balance sheet audit opinion
""".split())

#: A decode must reach this share of recognisable Georgian words to be accepted.
#: Native Unicode reports score 0.36–0.61 and OCR noise 0.000–0.002, so the exact
#: value is not delicate; it sits an order of magnitude clear of the noise.
MIN_WORD_RATE = 0.20
#: Below this many Georgian tokens the rate is not a measurement. A report with
#: less text than this has nothing to classify a sector from either.
MIN_TOKENS = 40
#: A candidate scheme must raise the recognised-word COUNT by this factor. Using
#: the count rather than the rate is what makes a partly-legacy filing work:
#: decoding a Latin section adds Georgian tokens without touching the Georgian
#: ones already there, so the rate can move either way but the count only rises
#: when the decode is real.
MIN_HIT_GAIN = 1.25
#: Absolute floor on the recognised-word count, so a handful of accidental hits
#: in a short file cannot satisfy :data:`MIN_HIT_GAIN` on its own.
MIN_HITS = 12
#: A line needs this share of English function words to be left undecoded.
ENGLISH_LINE_RATE = 0.30

KINDS: tuple[str, ...] = ("unicode", "recovered", "english", "glyph_noise", "no_text")


@dataclass(frozen=True)
class WordScore:
    """How much of ``text`` reads as real Georgian."""

    rate: float          # hits / tokens, 0.0 when there are no tokens
    hits: int            # tokens found in COMMON_WORDS
    tokens: int          # Georgian tokens of >= 3 letters

    @property
    def measurable(self) -> bool:
        return self.tokens >= MIN_TOKENS


@dataclass(frozen=True)
class Recovery:
    """Result of trying to recover one report.

    ``text`` is always usable output: the decoded text when ``kind`` is
    ``"recovered"``, and the input unchanged otherwise — so a caller can pipe
    every report through :func:`decode_report_markdown` unconditionally.
    """

    kind: str
    text: str
    #: Scheme names applied, in order ("acadnusx", "shift+0xE28", …).
    schemes: tuple[str, ...] = ()
    score: WordScore = field(default_factory=lambda: WordScore(0.0, 0, 0))
    cribs: int = 0

    @property
    def recovered(self) -> bool:
        return self.kind == "recovered"


# --------------------------------------------------------------------------- #
# Measurements
# --------------------------------------------------------------------------- #
def georgian_ratio(text: str) -> float:
    """Share of the alphabetic characters that are Georgian codepoints."""
    alpha = sum(1 for ch in text if ch.isalpha())
    if not alpha:
        return 0.0
    return len(_GEO_CHAR.findall(text)) / alpha


def word_score(text: str) -> WordScore:
    """Score ``text`` on the share of its Georgian tokens that are real words."""
    toks = _GEO_TOKEN.findall(text)
    if not toks:
        return WordScore(0.0, 0, 0)
    hits = sum(1 for t in toks if t in COMMON_WORDS)
    return WordScore(hits / len(toks), hits, len(toks))


def crib_hits(text: str) -> int:
    """How many of :data:`BOILERPLATE_CRIBS` appear in ``text``."""
    return sum(1 for c in BOILERPLATE_CRIBS if c in text)


def english_rate(text: str) -> float:
    """Share of the Latin tokens that are English function/finance words."""
    toks = _LAT_TOKEN.findall(text.lower())
    if not toks:
        return 0.0
    return sum(1 for t in toks if t in _ENGLISH_WORDS) / len(toks)


def repeat_ratio(text: str, n: int = 5, minimum: int = 150) -> float | None:
    """Type/token ratio over character ``n``-grams; ``None`` when too short.

    This is the measurement that decides whether a file is *worth* attacking,
    and it works because of one invariant: a character-level cipher — a font
    encoding, a codepage, a byte recoding, any bijection on characters — maps
    equal substrings to equal substrings, so it leaves this ratio EXACTLY as it
    is in the plaintext. Measured over a fixed-length prefix of the corpus:

        native Georgian Unicode reports   median 0.365   (0.223 – 0.585)
        AcadNusx reports (a real cipher)  median 0.363   (0.215 – 0.834)
        the 'mojibake' residue            median 0.866   (0.807 – 0.945)

    The residue's plaintext is Georgian financial boilerplate, which repeats
    heavily; a ratio of 0.87 means those repeats are gone. They cannot be
    restored by any table, which is why :func:`decode_text` reports those files
    as ``glyph_noise`` instead of guessing. Holds per-page too (0.67–0.94), so
    it is not an artefact of several font subsets in one document.
    """
    s = _WS.sub(" ", text)
    grams = [s[i:i + n] for i in range(len(s) - n) if " " not in s[i:i + n]]
    if len(grams) < minimum:
        return None
    return len(Counter(grams)) / len(grams)


# --------------------------------------------------------------------------- #
# Scheme 1 — AcadNusx
# --------------------------------------------------------------------------- #
def acadnusx_decode(text: str) -> str:
    """Map AcadNusx-family Latin codes to Georgian; other characters pass."""
    return "".join(ACADNUSX.get(ch, ch) for ch in text)


def acadnusx_encode(text: str) -> str:
    """Inverse of :func:`acadnusx_decode`, for round-trip tests."""
    return "".join(ACADNUSX_REVERSE.get(ch, ch) for ch in text)


# --------------------------------------------------------------------------- #
# Scheme 2 — a constant offset between the Georgian block and some other block
# --------------------------------------------------------------------------- #
#: Georgian letters frequent enough that the most frequent cipher characters are
#: almost certainly among them; used to propose offsets. Ordered by corpus
#: frequency (ა 14.4%, ი 12.3%, ე 9.2%, ს 7.5%, რ 5.9%, …).
_FREQUENT_GEORGIAN = "აიესრბოლნმდვუგთ"


def shift_offsets(text: str, top_chars: int = 14, limit: int = 40) -> list[int]:
    """Candidate offsets ``k`` such that ``chr(ord(c) + k)`` is Georgian.

    Proposed rather than brute-forced: pair each of the most frequent
    non-Georgian letters with each frequent Georgian letter and weight the
    implied offset by the character's count. The true offset is proposed by
    every letter of the block at once, so it dominates.
    """
    counts = Counter(ch for ch in text
                     if ch.isalpha() and not (GEORGIAN_LO <= ord(ch) <= GEORGIAN_HI))
    votes: Counter[int] = Counter()
    for ch, n in counts.most_common(top_chars):
        for g in _FREQUENT_GEORGIAN:
            k = ord(g) - ord(ch)
            if k:
                votes[k] += n
    return [k for k, _ in votes.most_common(limit)]


def shift_decode(text: str, k: int) -> str:
    """Add ``k`` to every character that thereby lands on a Georgian letter."""
    out = []
    for ch in text:
        o = ord(ch) + k
        if _MKHEDRULI_LO <= o <= _MKHEDRULI_HI and not (GEORGIAN_LO <= ord(ch) <= GEORGIAN_HI):
            out.append(chr(o))
        else:
            out.append(ch)
    return "".join(out)


def find_shift(text: str) -> int | None:
    """The offset that best improves ``text``, or None if none does."""
    base = word_score(text)
    best: tuple[int, int] | None = None
    for k in shift_offsets(text):
        s = word_score(shift_decode(text, k))
        if s.hits >= max(MIN_HITS, int(base.hits * MIN_HIT_GAIN)) and (
                best is None or s.hits > best[1]):
            best = (k, s.hits)
    return best[0] if best else None


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #
#: A whole report runs to ~120k characters and there are ~25 candidate schemes to
#: try per pass, so ranking them on the full text costs a corpus pass of tens of
#: billions of character operations. Rank on a sample instead and apply the winner
#: to everything. The sample is STRIDED, not a prefix: in a partly-legacy filing
#: the legacy section is often the notes at the back.
_SAMPLE_CHARS = 24000
_SAMPLE_SLICES = 6


def _sample(text: str) -> str:
    if len(text) <= _SAMPLE_CHARS:
        return text
    step = len(text) // _SAMPLE_SLICES
    width = _SAMPLE_CHARS // _SAMPLE_SLICES
    return "".join(text[i * step: i * step + width] for i in range(_SAMPLE_SLICES))


def _scheme_name(k: int) -> str:
    return f"shift+0x{k:X}" if k > 0 else f"shift-0x{-k:X}"


def _apply(text: str, name: str) -> str:
    if name == "acadnusx":
        return acadnusx_decode(text)
    sign = -1 if name.startswith("shift-") else 1
    return shift_decode(text, sign * int(name.split("0x", 1)[1], 16))


def _candidate_names(sample: str, used: frozenset[str]) -> list[str]:
    out: list[str] = []
    if "acadnusx" not in used and any(ch in ACADNUSX for ch in sample):
        out.append("acadnusx")
    out += [n for n in map(_scheme_name, shift_offsets(sample)) if n not in used]
    return out


def decode_text(text: str, max_passes: int = 3) -> Recovery:
    """Recover Georgian from ``text``, or say why it cannot be recovered.

    Applies schemes greedily: whichever candidate raises the recognised-word
    count most is kept, then the search repeats on the result. More than one
    pass is needed in practice because a single filing can mix an AcadNusx body
    with a shifted heading block.
    """
    cur, best = text, word_score(text)
    schemes: list[str] = []
    for _ in range(max_passes):
        sample = _sample(cur)
        base_hits = word_score(sample).hits
        winner: tuple[str, int] | None = None
        for name in _candidate_names(sample, frozenset(schemes)):
            hits = word_score(_apply(sample, name)).hits
            if hits < max(MIN_HITS, int(base_hits * MIN_HIT_GAIN)):
                continue
            if winner is None or hits > winner[1]:
                winner = (name, hits)
        if winner is None:
            break
        cand = _apply(cur, winner[0])
        s = word_score(cand)
        # The sample only ranks; the full text decides. A scheme that wins on the
        # sample but does not improve the whole document is not applied.
        if s.hits < max(MIN_HITS, int(best.hits * MIN_HIT_GAIN)):
            break
        schemes.append(winner[0])
        cur, best = cand, s

    if schemes and best.measurable and best.rate >= MIN_WORD_RATE:
        return Recovery("recovered", cur, tuple(schemes), best, crib_hits(cur))

    # Nothing was recovered — say what the input actually is.
    base = word_score(text)
    if base.measurable and base.rate >= MIN_WORD_RATE:
        return Recovery("unicode", text, (), base, crib_hits(text))
    if sum(1 for ch in text if ch.isalpha()) < 200:
        return Recovery("no_text", text, (), base, 0)
    if english_rate(text) >= 0.18:
        return Recovery("english", text, (), base, 0)
    return Recovery("glyph_noise", text, (), base, 0)


def classify(text: str) -> str:
    """One of :data:`KINDS`. Convenience wrapper over :func:`decode_text`."""
    return decode_text(text).kind


# --------------------------------------------------------------------------- #
# Report markdown
# --------------------------------------------------------------------------- #
# The extractor's scaffolding must survive verbatim: lib.activity_note strips it
# with regexes that match English keys and an "annual report" title, and it reads
# the FILER'S OWN NAME off that title to tell the reporting entity's activity
# from a group member's. Decoding those lines would both defeat strip_scaffold
# (leaving provenance junk inside the note region) and destroy the filer name.
_SCAFFOLD_LINE = re.compile(
    r"^\s*(?:#|---\s*$|- (?:IdCode|FVYear|Source|Pages|Extractor|Chars|ExtractedAt):)",
    re.IGNORECASE,
)


def _decodable_lines(md_text: str) -> tuple[list[str], list[bool]]:
    lines = md_text.splitlines()
    flags = []
    for ln in lines:
        if _SCAFFOLD_LINE.match(ln) or not ln.strip():
            flags.append(False)
        else:
            # An English page of a bilingual filing: AcadNusx would turn real
            # English words into Georgian gibberish, which costs nothing in
            # recognised words but destroys the slicer's English anchors.
            flags.append(english_rate(ln) < ENGLISH_LINE_RATE)
    return lines, flags


def decode_report_markdown(md_text: str, max_passes: int = 3) -> Recovery:
    """Recover an ``<idcode>_<year>.md`` extract, preserving its scaffolding.

    The scheme is chosen on the decodable body alone (so English pages and the
    provenance block cannot vote), then applied to exactly the lines that voted.
    ``Recovery.text`` is markdown of the same shape, ready for
    :func:`lib.activity_note.slice_activity_note`.
    """
    lines, flags = _decodable_lines(md_text)
    body = "\n".join(ln for ln, ok in zip(lines, flags) if ok)
    verdict = decode_text(body, max_passes=max_passes)
    if not verdict.recovered:
        kind = verdict.kind
        # The English test has to run on the WHOLE report: the body handed to
        # decode_text has had its English lines removed by construction, so an
        # all-English filing arrives here as an empty body and would otherwise be
        # filed as noise. That distinction matters — an English-language filing is
        # not damaged, it simply has no Georgian note, and the slicer's English
        # anchors already handle it.
        if kind in ("glyph_noise", "no_text") and english_rate(md_text) >= 0.18:
            kind = "english"
        return Recovery(kind, md_text, (), verdict.score, verdict.cribs)

    out = list(lines)
    for i, (ln, ok) in enumerate(zip(lines, flags)):
        if not ok:
            continue
        cur = ln
        for name in verdict.schemes:
            cur = _apply(cur, name)
        out[i] = cur
    text = "\n".join(out)
    return Recovery("recovered", text, verdict.schemes, word_score(text), crib_hits(text))
