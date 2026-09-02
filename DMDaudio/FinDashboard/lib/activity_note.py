"""Slice the 'principal activities / nature of operations' note from an
extracted annual-report markdown file.

Stage 1 of the offline sector-identification pipeline. ``companies.Sector`` is
empty for ~6,200 of ~9,100 filers, and the residual is dominated by companies
whose *name* carries no sector signal (the easy name-keyword wins were already
harvested). What those reports DO carry — reliably, near the front — is a short
statement of what the company actually does:

    EN:  "The principal activities of the Company are ..."
         "The Group is primarily engaged in ..."
    KA:  "კომპანიის ძირითადი საქმიანობა ..."
         "ძირითადი საოპერაციო საქმიანობა არის ..."

This module locates that statement with a small set of high-precision anchors
and returns a compact (~1–2k char) bilingual snippet. Downstream, Stage 2
(``classify_sectors.py --snippets``) runs the deterministic keyword rules
against the snippet (which beats the company name), and only the residual is
ever sent to an LLM (Stage 3). Doing the slice here means the LLM sees ~1.5k
chars, not the ~120k-char full report — the whole token-efficiency argument.

Pure/stdlib-only and fully testable: no DB, no network, no Streamlit. The input
is the markdown written by ``scripts/extract_report_texts.py``
(``render_markdown``): an ``# … annual report`` title, a ``- key: value``
provenance block, then ``## Page N`` sections separated by ``---``.

The key precision hazard is that some anchor *words* recur in accounting-policy
boilerplate — "nature of estimation process", "whether it is a principal or an
agent", "nature of the Georgian taxation system". The anchors below are written
narrowly (e.g. ``nature of`` only when followed by company/group/business/…) so
those never fire. See ``tests/test_activity_note.py`` for the guarded cases.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Reuse the business-object vocabulary from the usability gate rather than
# maintaining a second copy — they answer the same question ('does this text
# name something the company does?') and must not drift apart.
from lib.note_quality import (  # noqa: E402
    _ACCOUNTING_POLICY,
    _BUSINESS_OBJECT,
    _CONCENTRATION,
    _PLACE_OF_ACTIVITY,
)

# --------------------------------------------------------------------------- #
# Anchors — narrow, high-precision phrases that introduce an activity statement.
# Each carries a language tag ('ka'/'en') so we can prefer one clean window per
# language (reports are usually bilingual and the Georgian note is often the
# richest). Ordered by precision; order only affects tie-breaking within a
# language, since window selection is primarily by document position.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _Anchor:
    pattern: str
    lang: str
    label: str
    tier: int  # 0 = strong (unambiguous activity header), 1 = weak (sole-signal fallback)


# Tier 0 anchors are phrases that essentially only occur as an activity
# statement. Tier 1 anchors ("business activities", bare "operating activity",
# "engaged in") ALSO appear in auditor's-report / accounting-policy boilerplate,
# so they are used only when no strong anchor fired for that language — this
# stops the earliest weak hit from beating a later strong one (e.g. Tegeta's
# audit-report "business activities" vs the real "principal activities" note).
_ANCHORS: tuple[_Anchor, ...] = (
    # ---- Georgian (case-less script; \w* absorbs inflected endings) ----
    _Anchor(r"ძირითად\w*\s+საქმიანობ\w*", "ka", "ka:principal-activity", 0),
    _Anchor(r"საქმიანობის\s+ძირითად\w*", "ka", "ka:activity-principal", 0),
    _Anchor(r"ძირითად\w*\s+საოპერაციო\s+საქმიანობ\w*", "ka", "ka:principal-operating-activity", 0),
    _Anchor(r"საქმიანობის\s+სახე\w*", "ka", "ka:activity-type", 0),
    _Anchor(r"საქმიანობის\s+საგან\w*", "ka", "ka:activity-subject", 0),
    _Anchor(r"საქმიანობის\s+სფერო\w*", "ka", "ka:activity-field", 0),
    # 2026-08-05. Added after measuring the 483 reports that carry perfectly
    # readable Georgian and still produced no note — they are ~47% of everything
    # blocking the unclassified backlog (the other ~49% is scan mojibake that
    # needs re-OCR). Each of these three was counted over that population before
    # being added, and the set was A/B'd over all 6,726 extracted reports.
    #
    # Misspelt ძირითადი. Not a rare accident: 95 of the 483 have it. The filings
    # are typed by hand and the -ითა- cluster gets transposed (ძირიათადი) or
    # doubled. შპს დონა 2005 (445409059) states its business plainly — "…
    # არახანგრძლივი შენახვის საკონდიტრო ნაწარმის წარმოება და რეალიზაცია" — and
    # was lost to exactly one swapped pair of letters. Kept tight: the character
    # class only admits the letters already in the word, so it cannot wander onto
    # an unrelated stem.
    _Anchor(r"ძირ[ითას]{2,5}ად\w*\s+საქმიანობ\w*", "ka", "ka:principal-activity-typo", 0),
    # The predicate WITHOUT the ძირითადი prefix — "კომპანიის საქმიანობას
    # წარმოადგენს …". 93 of the 483. Strong on its own: წარმოადგენს is the
    # copula that introduces the statement, so this is an activity claim by
    # construction rather than a bare mention of the noun.
    # NO `რომლის` exclusion here, and that was tried and REVERTED on 2026-08-05.
    # The reasoning looked sound — "…, რომლის საქმიანობას წარმოადგენს …" can be a
    # relative clause about a different entity just named — and it did fix one
    # case (ბევრილი ჯგუფი, where the antecedent was an industry association). But
    # the construction is far more often SELF-referential: "შპს „ჯითი თაუერი“
    # წარმოადგენს დეველოპერულ კომპანიას, რომლის საქმიანობას წარმოადგენს უძრავი
    # ქონების მშენებლობა" — "…is a development company WHOSE activity is real
    # estate construction". Excluding it lost several good notes to fix one, so
    # the filer check in `_names_a_foreign_entity` handles the real cases instead.
    _Anchor(r"საქმიანობა[სს]?\s+წარმოადგენს", "ka", "ka:activity-is", 0),
    # The registry formula "ეკონომიკური საქმიანობის სახე/სფერო", 61 of the 483.
    # TIER 1, deliberately. At tier 0 it caused 26 regressions in the A/B because
    # the phrase is also how filings introduce a revenue note ("ეკონომიკური
    # საქმიანობიდან მიღებული შემოსავლები შედგება:"), a charter clause list, and
    # accounting-policy prose — and a tier-0 hit outranks better candidates
    # elsewhere in the document. As a sole-signal fallback it keeps the coverage
    # and stops outbidding the real anchors.
    # `(?!იდან)` because the ABLATIVE — "ეკონომიკური საქმიანობიდან მიღებული
    # შემოსავლები შედგება:" ("income received FROM economic activity consists
    # of:") — is a revenue-note heading, never a statement of activity. It was 3
    # of the 13 regressions on its own.
    _Anchor(r"ეკონომიკური\s+საქმიანობ(?!იდან)\w*", "ka", "ka:economic-activity", 1),
    _Anchor(r"საოპერაციო\s+საქმიანობ\w*", "ka", "ka:operating-activity", 1),
    _Anchor(r"კომპანიის\s+საქმიანობ\w*", "ka", "ka:company-activity", 1),
    # ---- English ----
    _Anchor(r"principal activit(?:y|ies)", "en", "en:principal-activities", 0),
    _Anchor(r"main activit(?:y|ies)", "en", "en:main-activities", 0),
    _Anchor(r"core business", "en", "en:core-business", 0),
    _Anchor(r"main line of business", "en", "en:main-line-of-business", 0),
    _Anchor(r"principal place of business", "en", "en:principal-place", 0),
    # "nature of" ONLY when it introduces the entity's business (never
    # "nature of estimation", "nature of its promise", …).
    _Anchor(r"nature of (?:the )?(?:company|group|entity|business|operations|its operations)",
            "en", "en:nature-of-business", 0),
    _Anchor(r"(?:company|group|entity)['’’]s (?:principal|main|core) (?:activit|business|operat)",
            "en", "en:entitys-principal", 0),
    _Anchor(r"(?:is|are|was|were) (?:primarily |mainly |principally )?engaged in",
            "en", "en:engaged-in", 1),
    _Anchor(r"the (?:company|group) (?:is |was )?(?:principally |mainly |primarily )?(?:involved|operating) in",
            "en", "en:involved-in", 1),
    _Anchor(r"business activit(?:y|ies)", "en", "en:business-activities", 1),
)

_COMPILED: tuple[tuple[re.Pattern[str], str, str, int], ...] = tuple(
    (re.compile(a.pattern, re.IGNORECASE), a.lang, a.label, a.tier) for a in _ANCHORS
)

# Markdown scaffolding lines emitted by extract_report_texts.render_markdown.
_META_LINE = re.compile(r"^- (?:IdCode|FVYear|Source|Pages|Extractor|Chars|ExtractedAt):",
                        re.IGNORECASE)
_PAGE_HEADER = re.compile(r"^## Page \d+\s*$")
_TITLE = re.compile(r"^# .+ annual report \(extracted text\)\s*$", re.IGNORECASE)
#: The filer's name out of the extractor scaffold: "# <name> — FY2024 annual report".
_TITLE_NAME = re.compile(r"^#\s*(.+?)\s+[-—–]\s*FY\d{4}\s+annual report", re.MULTILINE)
_WS = re.compile(r"\s+")


# --------------------------------------------------------------------------- #
# Sentence boundaries. A bare `[.!?]` split is wrong for these filings and the
# damage is visible on the tearsheet: შპს პეის ჯორჯია (204413759) states its
# business as "…, პორტის სახით ოპერირება, გემების აგენტირება და ა. შ.." and the
# note came out ending "…გემების აგენტირება და ა." — cut inside "და ა. შ."
# ("etc."). The same naive split also breaks inside a cross-reference number
# ("შენიშვნაში 2.3.") and after an initial ("ბნ. ირაკლი").
#
# Georgian is caseless, so the usual "next word is capitalised" disambiguation is
# unavailable. These three rules cover what actually occurs in the corpus.
# --------------------------------------------------------------------------- #

#: Multi-letter abbreviations whose trailing period is never a full stop.
_ABBREV_WORDS = frozenset({
    "გვ", "მაგ", "იხ", "სხვ", "ათ", "მლნ", "მლრდ", "დაახლ", "ბნ", "ქნ",
    "no", "nr", "etc", "inc", "ltd", "llc", "jsc", "mr", "mrs", "ms", "dr",
    "vs", "approx", "fig", "art",
})
#: The word a period is attached to (letters first, so "4." is not a "token").
_TOKEN_BEFORE_DOT = re.compile(r"([^\W\d_][\w\-]*)\.$")
#: A following single letter that itself carries a period — i.e. we are in the
#: middle of a chained initialism ("ა. შ.", "ე. წ."), not at a sentence end.
_INITIAL_CHAIN = re.compile(r"^\s*[^\W\d_]\.")


def _ends_sentence(text: str, i: int) -> bool:
    """True when ``text[i]`` (a terminator character) really ends a sentence.

    Only "." is ambiguous; "!" / "?" / "।" always terminate. Three rejections:

    * a dot binding two digits — ``2.3``, ``№4.5`` — is punctuation inside a
      token (this alone truncated windows at every note cross-reference);
    * a single-letter token followed by another dotted single letter — the
      INTERNAL dot of "ა. შ." / "ე. წ.". The dot that *completes* the initialism
      is deliberately still a terminator, because "და ა.შ." ("etc.") almost
      always closes the sentence it appears in;
    * a known multi-letter abbreviation ("ბნ.", "გვ.", "მლნ.", "etc.").
    """
    if text[i] != ".":
        return True
    nxt = text[i + 1: i + 5]
    if nxt[:1].isdigit():
        return False
    m = _TOKEN_BEFORE_DOT.search(text[max(0, i - 14): i + 1])
    if not m:
        return True
    tok = m.group(1)
    if len(tok) == 1 and _INITIAL_CHAIN.match(nxt):
        return False
    return tok.lower() not in _ABBREV_WORDS


#: How far back :func:`_extract_window` looks for the clause boundary to open on.
#: Same 180 that :func:`_anchor_sentence`'s span was swept to; see the rationale
#: in ``_extract_window``.
_HEAD_SEARCH = 180

#: Candidate inter-sentence gaps: whitespace after a terminator, or a blank line.
#: Every "." candidate is then re-tested by :func:`_ends_sentence`.
_BREAK_CANDIDATE = re.compile(r"(?<=[.!?।])\s+|\n[ \t]*\n")


def _sentence_breaks(text: str) -> list[tuple[int, int]]:
    """(start, end) of every real inter-sentence gap in ``text``."""
    out: list[tuple[int, int]] = []
    for m in _BREAK_CANDIDATE.finditer(text):
        i = m.start() - 1
        if i >= 0 and text[i] in ".!?।" and not _ends_sentence(text, i):
            continue
        out.append((m.start(), m.end()))
    return out


def _split_sentences(text: str) -> list[str]:
    """Abbreviation-aware sentence split."""
    parts: list[str] = []
    prev = 0
    for start, end in _sentence_breaks(text):
        parts.append(text[prev:start])
        prev = end
    parts.append(text[prev:])
    return parts


@dataclass(frozen=True)
class ActivityNote:
    """Result of slicing one report. ``text`` is None when no anchor fired.

    ``text`` is the single best activity SENTENCE — deliberately narrow, because
    the deterministic keyword pass substring-matches and every extra word is
    another chance to match the wrong rule. ``context`` is the whole note region
    that sentence came from, which is what an LLM should read instead: a
    consolidated filer's Note 1 continues into a per-subsidiary roll-call, and a
    single sentence gives no way to tell "the Group sells X" from "the Group owns
    a subsidiary that sells X". Only the surrounding note answers that.
    """
    text: str | None
    anchors: tuple[str, ...]        # labels that fired, doc order
    langs: tuple[str, ...]          # distinct languages of the chosen windows
    chars: int
    context: str | None = None      # the full note region `text` was chosen from

    @property
    def found(self) -> bool:
        return bool(self.text)


def strip_scaffold(md_text: str) -> str:
    """Return the report body with the extractor's markdown scaffolding removed.

    Drops the H1 title, the ``- key: value`` provenance block, the ``## Page N``
    headers, and the ``---`` page separators — leaving just the page text. Kept
    public so callers can reuse the same clean body (e.g. for an LLM prompt).
    """
    out: list[str] = []
    for line in md_text.splitlines():
        s = line.strip()
        if s == "---" or _PAGE_HEADER.match(s) or _META_LINE.match(s) or _TITLE.match(s):
            continue
        out.append(line)
    return "\n".join(out)


def _iter_hits(body: str) -> list[tuple[int, str, str, int]]:
    """(position, lang, label, tier) for every anchor match, sorted by position."""
    hits: list[tuple[int, str, str, int]] = []
    for rx, lang, label, tier in _COMPILED:
        for m in rx.finditer(body):
            hits.append((m.start(), lang, label, tier))
    hits.sort(key=lambda t: t[0])
    return hits


def _extract_window(body: str, pos: int, before: int, after: int) -> tuple[int, int, str]:
    """The activity CLAUSE around ``pos``, snapped tight to sentence boundaries.

    Returns (start, end, text). The window is deliberately tight: it captures the
    activity statement itself and stops at the next sentence end, NOT a fixed
    ~760-char block. The accounting-policy / basis-of-preparation boilerplate that
    follows an activity note is where free-text false-positive keywords live (a
    bank-account mention → 'ბანკი', credit terms → 'საკრედიტო', 'ferro' substrings),
    so sweeping it in wrecks deterministic precision. Keep it out.
    """
    # Start: snapped to the previous sentence/line start so we open on a clause
    # boundary (usually "კომპანიის …" / "The …").
    #
    # The search radius is _HEAD_SEARCH, NOT ``before``, and the two are different
    # numbers on purpose. Looking only ``before`` (40) characters back means that
    # whenever the clause opens further away than that, no boundary is found and
    # the window silently starts 40 characters before the anchor — mid-word, mid
    # clause. That is how "კომპანიის და მისი შვილობილი კომპანიის (ერთად ჯგუფი)
    # ძირითად საქმიანობას წარმოადგენს …" reached the tearsheet as "მისი შვილობილი
    # კომპანიის …" (204413759): the sentence start was 52 characters back, 12
    # past the horizon. The lead-in is 52 characters in that filing and routinely
    # longer, so the radius is set to the same 180 that `_anchor_sentence` was
    # swept to. rfind semantics keep this conservative — a nearer boundary still
    # wins, so a wider radius only ever helps a window that had none.
    #
    # With no boundary anywhere in radius, open AT the anchor rather than at an
    # arbitrary offset: dropping a few words of lead-in is a smaller error than
    # emitting a fragment that starts with a dangling pronoun.
    lo0 = max(0, pos - _HEAD_SEARCH)
    seg = body[lo0:pos]
    cut = -1
    for m in re.finditer(r"\n|\.(?=\s)|।|:", seg):
        if m.group() == "." and not _ends_sentence(seg, m.start()):
            continue
        cut = m.start() + 1
    lo = lo0 + cut if cut != -1 else pos
    # End: the first sentence terminator after the anchor. If that terminator is
    # right on the anchor (the anchor is a bare header like "ძირითადი საქმიანობა."),
    # extend to the next one so the real statement isn't cut to nothing.
    tail = body[pos: pos + after]
    # A single "\n" is a PDF line-wrap MID-sentence, NOT a clause boundary —
    # breaking on it truncated e.g. "retail sale of watches and jewellery in
    # specialised stores" down to "retail sale", discarding the product detail
    # that actually determines the sector. Only sentence-ending punctuation or a
    # blank-line paragraph break ends the activity clause; line-wraps are later
    # collapsed to spaces by _WS.
    ends = [m.end() for m in re.finditer(r"[.।!?]|\n[ \t]*\n", tail)
            if _ends_sentence(tail, m.start())]
    if ends:
        take = ends[0]
        if take < 25 and len(ends) > 1:
            take = ends[1]
        hi = pos + take
    else:
        hi = pos + after
    text = _WS.sub(" ", body[lo:hi]).strip()
    return lo, hi, text


# --------------------------------------------------------------------------- #
# Note 1 — "General information". Georgian annual reports open the notes with a
# corporate-information note that states the registration, the owners and, in one
# sentence, what the company does. Anchoring the SEARCH REGION to that note is far
# more precise than scanning the whole ~120k-char report, because the competing
# matches — cash-flow statement headings, ESG sections, risk-management policy,
# subsidiary tables — all live outside it. Whole-document search is kept only as a
# fallback for reports that do not use the standard note layout.
# --------------------------------------------------------------------------- #
_NOTE1_START = re.compile(
    r"(?:შენიშვნა\s*[№#]?\s*1\b|შენიშვნა\s*1\s*[-–—.:]"
    r"|ზოგადი\s+ინფორმაცია|ზოგადი\s+ცნობები|საერთო\s+ინფორმაცია"
    r"|ინფორმაცია\s+(?:საწარმოს|კომპანიის)\s+შესახებ"
    r"|საწარმოს\s+შესახებ\s+ინფორმაცია"
    # NOT here, and it was measured: "ჯგუფი და მისი საქმიანობა" / "The Group and
    # its operations" is the other standard Note-1 heading, and adding it routes
    # 478 more reports onto the (better) sentence-selection path. It still loses.
    # A/B over all 6,726 extracted reports, scored on how many yield a note that
    # passes the DESCRIPTION gate (assess_note + predicate + business object):
    #     baseline                          3815
    #     + marker, region opens ON it      3801   (+24 / -38)
    #     + marker, region opens AFTER it   3814   (+24 / -25)
    # The first variant fails because these headings carry no trailing
    # punctuation, so the heading glues onto the first real sentence and the
    # blob outscores the activity statement ("კომპანია და მისი საქმიანობა შპს
    # კორიდა … დაარსდა 2006 წელს …" beat ბიზნესის უმთავრეს საქმიანობას …).
    # Opening after the heading fixes that and still nets -1. Neither earns the
    # change; revisit only with a sentence-splitter that treats a short unpunctuated
    # line as a heading break.
    r"|\bnote\s*1\b|general\s+information|corporate\s+information"
    r"|organisation\s+and\s+(?:its\s+)?principal\s+activit"
    r"|organization\s+and\s+(?:its\s+)?principal\s+activit)",
    re.IGNORECASE,
)
# The next note ends the region. "Basis of preparation" is the near-universal
# Note 2 in both languages.
_NOTE1_END = re.compile(
    r"(?:შენიშვნა\s*[№#]?\s*2\b|მომზადების\s+საფუძვლ|წარდგენის\s+საფუძვლ"
    r"|სააღრიცხვო\s+პოლიტიკ"
    r"|\bnote\s*2\b|basis\s+of\s+preparation|material\s+accounting\s+polic"
    r"|summary\s+of\s+significant\s+accounting\s+polic)",
    re.IGNORECASE,
)
# Cap so a missing end-marker can't swallow the statements, and only look for the
# note near the FRONT (a later "general information" belongs to a subsidiary).
_NOTE1_MAX_LEN = 9000
# Generous: in a report that opens with a long management review (TBC's runs to
# ~1.5M chars) the notes start well past the midpoint. Precision comes from the
# rejection rules below, not from a tight horizon.
_NOTE1_SEARCH_FRACTION = 0.85
# Dot leaders ("ზოგადი ინფორმაცია ......... 13") mean we matched the TABLE OF
# CONTENTS, whose entry names the note but contains none of its text.
_TOC_LEADER = re.compile(r"\.{4,}|…{2,}")
# "(იხ. შენიშვნა 1(b))" / "see Note 1" are cross-references, not the note itself.
_XREF_BEFORE = re.compile(r"(?:იხ\.?|see|refer(?:\s+to)?|per)\s*\(?\s*$", re.IGNORECASE)


def first_note_region(body: str) -> tuple[int, int] | None:
    """(start, end) of the general-information note, or None if not identifiable.

    Walks every start-marker match and returns the first that survives three
    rejections, each of which was a real mis-hit on the 2026-07-28 batch:
      * table-of-contents entries (Nikora, Nova) — dot leaders after the marker;
      * cross-references (Atlas: "შენიშვნა 1(b))") — a "see/იხ." lead-in, or a
        marker that is not at the start of a line;
      * degenerate regions shorter than a sentence.
    """
    if not body:
        return None
    horizon = max(4000, int(len(body) * _NOTE1_SEARCH_FRACTION))
    for m in _NOTE1_START.finditer(body, 0, horizon):
        start = m.start()
        lead = body[max(0, start - 24):start]
        if _XREF_BEFORE.search(lead):
            continue
        # Must open a line/heading — mid-sentence hits are prose references.
        if lead.strip() and not lead.rstrip().endswith((".", ":", ";", "|")) and "\n" not in lead:
            continue
        if _TOC_LEADER.search(body[m.end():m.end() + 160]):
            continue
        end_m = _NOTE1_END.search(body, m.end())
        end = end_m.start() if end_m else len(body)
        end = min(end, start + _NOTE1_MAX_LEN)
        if end - start < 200:
            continue
        return start, end
    return None


# --------------------------------------------------------------------------- #
# Window quality — an anchor can fire inside a TABLE or a STATEMENT HEADING as
# easily as inside prose, and taking the earliest hit then loses the real note.
# Measured on the 2026-07-28 batch, this cost us the largest filers in the book:
#   * JTI Caucasus / UGT  -> "ფულადი სახსრები საოპერაციო საქმიანობიდან"
#                            (the CASH-FLOW statement heading)
#   * Atlas (GEL 706M)    -> "ძირითადი საქმიანობა საკუთრების წილი 31 დეკემბერი"
#                            (a shareholding TABLE header)
#   * Nikora (GEL 1.45bn) -> "საქმიანობის სფერო სს ნიკორა ტრეიდი 96."
#   * SOCAR Georgia Gas   -> a subsidiary table of "100% 100% საქართველო" rows
#   * TBC Bank            -> an ESG / Scope-1 emissions paragraph
# So score every candidate window for prose-likeness and take the best one,
# rather than the first.
# --------------------------------------------------------------------------- #

# Headings that introduce a FINANCIAL STATEMENT, not a description of the
# business. An anchor matching inside one of these is never the activity note.
_STATEMENT_CONTEXT = re.compile(
    r"ფულად[ია]\s+სახსრებ|ფულადი\s+ნაკადებ|საოპერაციო\s+საქმიანობიდან"
    r"|cash\s+(?:flows?|and\s+cash\s+equivalents)\s+from"
    r"|ძირითადი\s+ფინანსური\s+მაჩვენებლ"      # "main financial indicators"
    r"|statement\s+of\s+cash\s+flows",
    re.IGNORECASE,
)

# Verbs/phrases that actually assert what the business DOES.
_ACTIVITY_VERB = re.compile(
    r"წარმოადგენს|მოიცავს|ეწევა|ახორციელებს|ეკუთვნის|არის\b"
    r"|is\s+(?:the\s+)?(?:principal|main|primary)|engaged\s+in|consists?\s+of"
    r"|includes?\b|operates?\b|provides?\b|involved\s+in",
    re.IGNORECASE,
)


def _window_quality(text: str) -> float:
    """Prose-likeness of a candidate window; higher is better, <= 0 is unusable.

    Cheap, explainable signals only — this runs over every anchor hit:
      * a financial-statement heading in view is disqualifying;
      * digit-heavy text is a table (percentages, years, amounts);
      * an activity verb is strong positive evidence;
      * very short windows are truncated headers.
    """
    if not text:
        return -1.0
    if _STATEMENT_CONTEXT.search(text):
        return -1.0
    letters = sum(ch.isalpha() for ch in text)
    digits = sum(ch.isdigit() for ch in text)
    if letters < 25:
        return -1.0
    # Tables carry far more digits per letter than prose does.
    digit_ratio = digits / max(letters, 1)
    if digit_ratio > 0.28:
        return -1.0
    score = 1.0 - digit_ratio * 2.0
    if _ACTIVITY_VERB.search(text):
        score += 1.5
    # Long-enough clauses are more likely to name a product or service.
    score += min(len(text), 300) / 600.0
    # A window that is almost all percent signs / ownership rows.
    if text.count("%") >= 3:
        score -= 1.5
    return score


# Words that mark a sentence as being ABOUT the business activity, used to pick
# the right sentence once we are already inside the general-information note.
_ACTIVITY_TOPIC = re.compile(
    r"საქმიანობა|საქმიანობის|მოღვაწეობ|ოპერირებს"
    r"|principal\s+activit|main\s+activit|business\s+activit|nature\s+of\s+(?:the\s+)?business"
    r"|engaged\s+in|operates?\b",
    re.IGNORECASE,
)
# A sentence that says "PRINCIPAL activity" is the note; one that merely contains
# the word "activity" may be boilerplate. Rank the former far above the latter.
_ACTIVITY_TOPIC_STRONG = re.compile(
    r"(?:ძირითად\w*|მთავარ\w*|ძირითადი\s+ბიზნეს)\s+(?:ბიზნეს\s+)?საქმიანობ"
    r"|საქმიანობის\s+(?:ძირითადი\s+)?(?:საგანი|სფერო|მიმართულება)"
    r"|principal\s+(?:business\s+)?activit|main\s+(?:business\s+)?activit"
    r"|primary\s+activit|principally\s+engaged",
    re.IGNORECASE,
)
# "Activity" also appears in standard boilerplate that says nothing about what the
# business does. Each of these cost a real company a correct note on the
# 2026-07-28 batch: going-concern (Nikora, Tbilisi Electricity), CSR (Tbilisi
# Energy), the tariff regulator (Telasi), audit scope, and staff relocation (EPAM).
_ACTIVITY_BOILERPLATE = re.compile(
    r"ფუნქციონირებად\w*\s+საწარმო|going\s+concern"
    r"|სოციალური\s+პასუხისმგებლობ|corporate\s+social\s+responsib"
    r"|არეგულირებ\w*|მარეგულირებელ\w*|regulated\s+by|regulator"
    r"|აუდიტ\w*|audit(?:or|ing)?\b"
    r"|რისკ\w*\s+მართვ|risk\s+management"
    r"|ანგარიშგებ\w*\s+მომზადებ|basis\s+of\s+preparation"
    r"|თანამშრომლების\s+გადაადგილებ",
    re.IGNORECASE,
)

# NOT a reject class: the Georgian oblique forms ``საქმიანობისთვის`` (for the
# activity) / ``საქმიანობის შედეგად`` (as a result of the activity) look like a
# clean signature for accounting prose — they are what makes the IAS 16 fixed-asset
# sentence and the IFRS 15 receivables sentence outscore the real note — but
# rejecting on them was MEASURED and rejected (2026-07-31, A/B over the 6,726-report
# corpus): it bought 2 extra fixes and 3 improved swaps at the cost of 3 misfires on
# legitimate sentences, because Georgian uses the same form for ordinary modification
# — Expo Georgia's ``კომპანია იჯარით გასცემს საოპერაციო საქმიანობისთვის აუთვისებელ
# შენობებს`` ("leases out buildings unused FOR operating activity") is a real
# activity statement. The accounting-policy vocabulary below already catches both
# attested boilerplate sentences on their own, with zero regressions.


#: An entity name quoted inside a sentence. Georgian filings wrap the name in
#: „…“ (or plain quotes) right after the legal form.
_QUOTED_NAME = re.compile(r"[„“\"]([^„“\"]{3,60})[“\"]")
#: Common nouns that appear in quotes but name nobody.
_QUOTED_GENERIC = frozenset({
    "კომპანია", "კომპანიის", "ჯგუფი", "ჯგუფის", "ჰოლდინგი", "საზოგადოება",
    "company", "group", "the company", "the group",
})


def _norm_entity(name: str) -> frozenset[str]:
    """Token set of an entity name, stripped of legal form and case endings."""
    s = re.sub(r"^(?:შპს|სს|სპს|ააიპ|ი/მ|jsc|llc|ltd)\s*", "", (name or "").strip(),
               flags=re.IGNORECASE)
    s = re.sub(r"[„“\"'.,()\-–—]", " ", s).lower()
    toks = [t for t in s.split() if t not in {"და", "and", "the", "of"}]
    return frozenset(re.sub(r"(?:ისა|ის|ში|ზე|თან|ად|ს|მ|ი)$", "", t) for t in toks if t)


def _names_a_foreign_entity(sentence: str, filer: frozenset[str]) -> bool:
    """True when the sentence's subject is a NAMED entity other than the filer.

    This is what separates "the Company's principal activity is running a retail
    store network" from "OOO X **Delivery**'s principal activity is organising
    delivery from the Company's shops" — both sit inside the same Note 1 of the
    same consolidated report, both are verbatim, both say "principal activity".
    """
    if not filer:
        return False
    for raw in _QUOTED_NAME.findall(sentence):
        if raw.strip().lower() in _QUOTED_GENERIC:
            continue
        toks = _norm_entity(raw)
        if not toks:
            continue
        shared = len(toks & filer) / max(len(filer), 1)
        # Shares the filer's name but adds a qualifier => a subsidiary
        # ("…დელივერი"). Shares nothing => an unrelated entity.
        if shared >= 0.6 and len(toks - filer) >= 1 and len(toks) > len(filer):
            return True
        if shared < 0.6:
            return True
    return False


def _anchor_sentence(body: str, pos: int, span: int = 180) -> str:
    """The single sentence containing the anchor at ``pos``.

    Expands to the nearest sentence boundary either side, so the reject classes can
    be applied at the scope they are calibrated for even on the anchor-window path.

    ``span`` bounds how far to look for those boundaries, and matters because plenty
    of Georgian filings carry no sentence punctuation at all — there the search runs
    to the bound and returns a blob, so a wider span pulls in unrelated accounting
    vocabulary and rejects a good note. Swept over the whole corpus (2026-07-31):

        span   fixed   lost
         180     182      3     <- best on both axes
         260     181      4
         340     178      4
         500     178      4
         700     178      4

    Monotone, so 180 is not a knife-edge fit; it is the flat end of the curve.
    """
    lo = max(0, pos - span)
    seg = body[lo:pos + span]
    off = pos - lo
    breaks = _sentence_breaks(seg)
    start = 0
    for b_start, b_end in breaks:
        if b_end <= off:
            start = b_end
    end = next((b_start for b_start, _ in breaks if b_start >= off), len(seg))
    return _WS.sub(" ", seg[start:end]).strip()


#: A sentence that explicitly disclaims being the principal activity. Filings say
#: "დამატებით (არაძირითად) ეკონომიკურ საქმიანობას წარმოადგენს ნებისმიერი სხვა
#: საქმიანობა, რომელიც არ არის აკრძალული" — its ADDITIONAL, non-principal
#: activity is anything not prohibited by law. Content-free, and self-labelled as
#: the wrong thing. Caught 2 of the 13 regressions in the 2026-08-05 A/B.
_NON_PRINCIPAL = re.compile(r"არაძირითად")


def _is_policy_sentence(sentence: str) -> bool:
    """True when a sentence is recognition/measurement prose, a place, a risk
    dimension, or an explicit NON-principal activity, rather than a statement of
    what the business does."""
    if not sentence:
        return False
    return bool(_ACCOUNTING_POLICY.search(sentence)
                or _PLACE_OF_ACTIVITY.search(sentence)
                or _CONCENTRATION.search(sentence)
                or _NON_PRINCIPAL.search(sentence))


def _best_sentence_in_region(region_text: str,
                             filer: frozenset[str] = frozenset()) -> str | None:
    """Best activity sentence inside Note 1, or None.

    Once the region is known to be the general-information note, sentence-level
    selection beats anchor windows: an anchor can still land on a subsidiary
    table INSIDE the note (Nikora's "საქმიანობის სფერო სს ნიკორა ტრეიდი 96.")
    and win on position, whereas scoring whole sentences lets the real statement
    — which is longer, verb-bearing and digit-light — come top.

    ``filer`` is the reporting entity's own name. Without it, a CONSOLIDATED
    filing hands this function several equally-verbatim "principal activity"
    sentences — one per group member — and prose quality picks whichever is
    longest. That is how ორი ნაბიჯი (204571668), a 529-store grocery chain, came
    out as Logistics & Transport: its delivery subsidiary's note on page 13 is a
    longer sentence than the filer's own on page 11. Naming a foreign entity is
    therefore a HARD demotion, ranked ahead of both other signals.
    """
    best: tuple[tuple[int, int, int, float], str] | None = None
    for raw in _split_sentences(region_text):
        s = _WS.sub(" ", raw).strip()
        if len(s) < 40 or not _ACTIVITY_TOPIC.search(s):
            continue
        # Boilerplate that merely contains the word "activity" — going concern,
        # CSR, the tariff regulator, audit scope — describes no business.
        if _ACTIVITY_BOILERPLATE.search(s):
            continue
        # Sentence-level reuse of lib.note_quality's reject classes. Applied HERE,
        # per candidate sentence, and deliberately NOT to the emitted note as a
        # whole: measured on the corpus, gating the whole note (slice + its
        # surrounding context) flips 2,224 currently-good notes to FAIL, because
        # any accounting boilerplate anywhere in the window trips the pattern.
        # One sentence at a time is the scope these patterns are calibrated for,
        # and it lets the scorer fall through to the NEXT-best sentence — usually
        # the real activity statement — instead of emitting the policy prose.
        if _is_policy_sentence(s):
            continue
        q = _window_quality(s)
        if q <= 0:
            continue
        # Rank on (NAMES A BUSINESS, about-the-filer, says-PRINCIPAL-activity,
        # prose quality).
        #
        # Informativeness has to come FIRST, above the filer check. Ranking the
        # filer check first — the obvious reading of "prefer the company's own
        # sentence" — measurably made things worse: it demoted every sentence
        # naming another entity unconditionally, so wherever the only
        # filer-subject alternative was vacuous, vacuous won. რითეილ ინვესთმენთს
        # lost "the Group's activity is retail trade under the Magniti brand" for
        # "the company was founded on 27 December 2017"; ტაბიძის 4 lost "owns and
        # operates the hotel Ibis Styles Tbilisi" for "the Group operates in
        # accordance with Georgian legislation".
        #
        # A company describes itself through relationships and brands all the
        # time — "we lease our assets to our 100% subsidiary", "we operate under
        # the Magniti brand". Naming another entity is not disqualifying; naming
        # NO BUSINESS is. So an informative sentence about a group member beats a
        # contentless one about the filer, and the entity question is left to
        # scripts/verify_sector_changes.py, which can flag it for a human.
        key = (1 if _BUSINESS_OBJECT.search(s) else 0,
               0 if _names_a_foreign_entity(s, filer) else 1,
               1 if _ACTIVITY_TOPIC_STRONG.search(s) else 0,
               q)
        if best is None or key > best[0]:
            best = (key, s)
    return best[1] if best else None


def _raw_span(body: str, pos: int, before: int, after: int) -> str:
    """A plain character span around ``pos``, snapped only to word boundaries.

    Deliberately NOT :func:`_extract_window`, which stops at the first sentence
    terminator so the deterministic keyword pass never sees the accounting-policy
    boilerplate that follows an activity note. That tightness is right for
    substring matching and wrong for a reader: the sentence a filer uses to say
    what it does is frequently the SECOND one ("The company was registered on …
    Its principal activity is …"), and a consolidated filer's activity is only
    decidable from the sentences around it.
    """
    lo = max(0, pos - before)
    hi = min(len(body), pos + after)
    span = body[lo:hi]
    if lo > 0:
        span = span.partition(" ")[2]          # drop a half-word at the front
    return _WS.sub(" ", span).strip()


def _clip(text: str, limit: int) -> str:
    """Whitespace-collapse and cap on a word boundary."""
    t = _WS.sub(" ", text).strip()
    return t if len(t) <= limit else t[:limit].rsplit(" ", 1)[0].rstrip() + " …"


def slice_activity_note(
    md_text: str,
    max_chars: int = 1000,
    window_before: int = 40,
    window_after: int = 400,
    context_chars: int = 2600,
) -> ActivityNote:
    """Slice the principal-activities note from extractor markdown.

    Strategy: strip scaffolding, find all anchor hits, then take the EARLIEST
    hit for each language (up to two windows — one KA, one EN — since reports
    are typically bilingual), in document order, deduping overlaps. The result
    is whitespace-collapsed and capped at ``max_chars`` on a word boundary.

    Returns an :class:`ActivityNote`; ``.found`` is False (``.text`` None) when
    no anchor fires — the caller records that as "note not found" (distinct from
    a scanned PDF that produced no text at all).
    """
    # Read the filer's own name off the scaffold BEFORE stripping it, so sentence
    # selection can tell the reporting entity's activity from a group member's.
    _m = _TITLE_NAME.search(md_text)
    filer = _norm_entity(_m.group(1)) if _m else frozenset()

    body = strip_scaffold(md_text)
    hits = _iter_hits(body)
    if not hits:
        return ActivityNote(None, (), (), 0)

    # Per language: among the hits at the STRONGEST tier present (a strong anchor
    # beats a weak one), take the BEST-SCORING window rather than the earliest —
    # otherwise a table header or a cash-flow heading near the front of the report
    # wins over the real note further down. Document position is only the
    # tie-breaker now. Up to two windows (one KA, one EN), reports being bilingual.
    # Prefer hits inside Note 1 ("General information"). A hit there is trusted on
    # position alone and is NOT held to the prose-quality bar — that bar exists to
    # fend off the cash-flow headings and ESG paragraphs that live OUTSIDE the note.
    # NB: "everything in Note 1 is about the company itself" was the original
    # assumption here and it is FALSE for a consolidated filing, whose Note 1
    # continues into a per-subsidiary roll-call, each entry with its own verbatim
    # "principal activity" sentence. Hence the filer check in the sentence ranking.
    region = first_note_region(body)
    if region:
        # Sentence-level pick first — see _best_sentence_in_region for why this
        # beats anchor windows once we know we are inside the note.
        region_text = body[region[0]:region[1]]
        sent = _best_sentence_in_region(region_text, filer)
        if sent:
            if len(sent) > max_chars:
                sent = sent[:max_chars].rsplit(" ", 1)[0].rstrip() + " …"
            lang = "ka" if re.search(r"[Ⴀ-ჿ]", sent) else "en"
            return ActivityNote(sent, (f"{lang}:note1-sentence",), (lang,), len(sent),
                                _clip(region_text, context_chars))
    in_region = [h for h in hits if region and region[0] <= h[0] < region[1]]
    if in_region:
        hits, require_quality = in_region, False
    else:
        require_quality = True

    best_tier: dict[str, int] = {}
    for pos, lang, label, tier in hits:
        best_tier[lang] = min(best_tier.get(lang, tier), tier)

    scored: dict[str, tuple[float, int, str]] = {}
    for pos, lang, label, tier in hits:
        if tier != best_tier[lang]:
            continue
        # Same reject classes the sentence path applies, but scoped to the anchor's
        # OWN sentence rather than the window: a 400-char window routinely runs on
        # into neighbouring accounting prose, and testing the whole thing would
        # throw away good notes (the measured failure mode of gating a wide span).
        #
        # This path is reached when first_note_region() finds no Note 1 — which is
        # exactly the situation of the four companies the audit caught (სიმი
        # 416332953, ტოტი 400024497, სანტრეიდი 406049903, მესხეთი 208142419): with
        # no region there is no sentence scoring, so the raw window won and every
        # one of them was handed the IAS 16 fixed-asset sentence
        # ("ძირითადი საშუალებები … გამოიყენება ძირითადი საქმიანობისთვის …
        # აღრიცხულია …") as its activity note, at classifier confidence >= 0.90.
        if _is_policy_sentence(_anchor_sentence(body, pos)):
            continue
        quality = _window_quality(_extract_window(body, pos, window_before, window_after)[2])
        # Earlier is better only between windows of equal quality.
        key = (quality, -pos)
        if lang not in scored or key > (scored[lang][0], -scored[lang][1]):
            scored[lang] = (quality, pos, label)

    # Outside Note 1, drop languages whose best candidate is still junk (every hit
    # was a table or a statement heading) rather than emitting a note we know is
    # wrong — "no note" is an honest answer the classifier already handles.
    usable = scored if not require_quality else {
        lang: v for lang, v in scored.items() if v[0] > 0
    }
    if not usable:
        return ActivityNote(None, (), (), 0)
    chosen = sorted(((pos, label) for _q, pos, label in usable.values()),
                    key=lambda t: t[0])  # doc order

    windows: list[tuple[int, int, str]] = []
    used_labels: list[str] = []
    used_langs: list[str] = []
    for pos, label in chosen:
        w = _extract_window(body, pos, window_before, window_after)
        # Skip a window that overlaps one already taken.
        if any(not (w[1] <= a or w[0] >= b) for a, b, _ in windows):
            continue
        windows.append(w)
        used_labels.append(label)
        lang = label.split(":", 1)[0]
        if lang not in used_langs:
            used_langs.append(lang)

    windows.sort(key=lambda t: t[0])  # document order
    snippet = " … ".join(w[2] for w in windows if w[2]).strip()
    if len(snippet) < 30:
        return ActivityNote(None, (), (), 0)
    full = " … ".join(w[2] for w in windows if w[2]).strip()
    if len(snippet) > max_chars:
        snippet = snippet[:max_chars].rsplit(" ", 1)[0].rstrip() + " …"
    # Context here is a RAW span around the same anchor positions, not a re-cut of
    # the windows: _extract_window snaps to the first sentence terminator by design
    # (sweeping in the accounting boilerplate that follows wrecks the deterministic
    # keyword pass), so asking it for more text returns the same clause. A reader
    # that can weigh a whole paragraph wants the opposite trade.
    wide = " … ".join(
        _raw_span(body, pos, 600, 1600) for pos, _label in chosen
    ).strip()
    return ActivityNote(snippet, tuple(used_labels), tuple(used_langs), len(snippet),
                        _clip(wide or full, context_chars))


__all__ = ["ActivityNote", "slice_activity_note", "strip_scaffold"]
