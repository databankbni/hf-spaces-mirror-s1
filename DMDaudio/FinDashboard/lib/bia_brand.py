"""bia.ge TRADE NAMES — deciding when a trademark tells you something new.

A Georgian filer's legal name is very often uninformative: ``შპს მემო`` says
nothing, but bia.ge records its trademark as ``უნივერსამი`` — a grocery
supermarket chain. That is exactly the fact an analyst wants on the tearsheet and
it is nowhere in the filing. bia's trademark list is already scraped, verified and
stored (``bia_directory.DetailGz``, see ``lib/bia.py`` for the id-code gate that
makes it trustworthy), so this module is only the *selection* problem:

    of the trademarks bia lists for a company, which ones are a DISTINCT trade
    name — a brand you could not have guessed from the legal name?

No Streamlit, no DB, no network. Pure functions over ``(company_name, detail)``.

WHY A GATE IS NEEDED AT ALL
---------------------------
6,709 of the 6,999 code-verified companies carry at least one trademark, but on
measurement the large majority are the company's own name read back:

    code-verified companies matched to a filer .......... 6,999
      ... carrying at least one trademark ............... 6,709
      ... where EVERY trademark echoes the legal name ... 4,841
      ... with a trade name worth showing ............... 1,391

    trademarks in total ................................. 7,812
      ... passing the novelty gate (reach the echo test)   2,601
      ... surviving all three filters (displayed) ........ 2,040

Showing ``შპს რემმშენი`` that it trades as ``რემმშენი`` is pure noise, and noise
on every tearsheet is worse than no feature. So a trademark has to clear three
filters, each answering a different way the "brand" can be a non-fact.

1. NOVEL-STEM GATE. The trademark must contribute a token the legal name does not
   already have, compared on Georgian STEMS. Georgian declines, so the raw token
   test is fooled by case endings: bia lists ``კნაუფი`` for ``შპს კნაუფ გიპს
   თბილისი`` — nominative ``-ი`` on the same word. Stemming catches it.

2. TRANSLITERATION-ECHO GUARD. ``შპს ISSP Georgia`` → ``აიესესპი ჯორჯია`` is the
   same name in the other script, and no token test can see that because the two
   strings share not one character. Both sides are reduced to a coarse phonetic
   SKELETON (Georgian → Latin, the aspirate/ejective pairs collapsed —
   ``თ``/``ტ``→t, ``ფ``/``პ``→p, ``ქ``/``კ``→k — since transliterators pick
   between them freely) and compared by similarity ratio.

   The threshold is SCRIPT-DEPENDENT, and that split is the measured part.
   Cross-script pairs are overwhelmingly transliterations far down the range,
   while same-script pairs at the same ratio are still real distinct brands.
   Counts are over the 2,601 trademarks that pass the novelty gate — exactly what
   ``scripts/report_bia_trade_names.py --calibrate`` reprints:

       ratio band     cross-script                     same-script
       0.72-1.01        133  ~all echoes (VITA)          229  ~all echoes (+"school")
       0.62-0.72         43  ~all echoes (RMG Gold)      126  mostly echoes
       0.55-0.62         25  still echoes (VTM)          110  REAL (Tbilisi Metro)
       0.00-0.55        224  real + acronym residue    1,711  real

   Hence ``ECHO_RATIO_CROSS_SCRIPT = 0.55`` and ``ECHO_RATIO_SAME_SCRIPT = 0.62``.
   Moving either one moves what shows on the tearsheet — re-measure with
   ``--calibrate`` before touching them.

   The same-script threshold has a KNOWN recall cost, worst on SHORT names where
   difflib's ratio inflates on incidental letter overlap: ``შპს დემასი`` →
   ``იდეალი`` (0.67) and ``სს ლაღიძე`` → ``ლაღიძის წყლები`` (0.63) are genuine
   brands refused as spelling variants. Lowering the threshold to recover them
   admits the extension echoes that dominate the 0.62-0.72 same-script band, so
   they stay refused.

3. INITIALISM GUARD. The residue below the cross-script threshold is the Georgian
   phonetic spelling of a Latin initialism: ``ICC GEORGIA`` → ``აისისი`` (ai-si-si
   = I-C-C), ``Georgian Industrial Asset Management Group`` → ``ჯიაიეიემი``
   (ji-ai-ei-em = G-I-A-M). Similarity can't catch these — the Georgian is three
   times longer than the Latin — so the legal name's initials are expanded into
   their English letter-names *in Georgian spelling* and matched directly.

   This one deliberately costs recall: ``ფრაისუოთერჰაუსკუპერს საქართველო`` →
   ``PwC`` is a genuine trading brand and is refused as an initialism. That is the
   accepted trade — an initialism of your own name is far more often noise than
   news, and a wrong "trades as" line is a claim about a real company.

MEASURED AND REJECTED: IGNORING SHARED WORDS
--------------------------------------------
The echo ratio is inflated when a brand and the legal name end in the same word,
which costs real brands: ``სს საქართველოს ბანკი`` → ``ექსპრეს ბანკი`` (Express
Bank, a genuine BoG brand) scores 0.64 purely on the shared ``ბანკი`` and is
refused. Two fixes for that were built and measured; BOTH were rejected.

* Drop every token the two names share, then compare. Rescues 208 trademarks,
  but only ~40% are real brands — the rest are extension echoes the shared-word
  removal blinds the ratio to (``ინვეტი`` → ``ინვეტ ზოო``, ``აპტოს`` → ``აპტოს
  შოპი``, ``დრიმლენდ ოაზისი`` → ``სასტუმრო დრიმლენდ ოაზისი``) plus a company's
  own parenthesised acronym (``... ოპერატორი`` → ``... ოპერატორი (ესკო)``,
  0.96 → 0.16). Net precision LOSS.
* Drop a shared token only when it is a generic industry descriptor, from a
  curated list (``ბანკი``/``ჯგუფი``/``ჰოსპიტალი``/…). Far narrower — 21
  trademarks — but still roughly half noise (``დისტრიბუცია 2024``; ``შპს GL
  მარკეტი`` → ``ჯიელ მარკეტი``, a transliteration that survives because
  stripping the shared generic word also strips what made the pair comparable),
  for one clearly valuable rescue. Not worth a hand-maintained word list.

So the shared word stays in the comparison and Express Bank stays hidden. If you
revisit this, measure both arms again rather than trusting the shapes above —
they were measured on the 2026-08 scrape.

WHAT THIS MODULE DOES NOT DO
----------------------------
It does not rank, score or pick a single "primary" brand — bia lists trademarks
unordered and a company can genuinely run several (``გელა ჯალიაშვილი`` →
``ტერემოკ`` and ``სუში ვეი``, two restaurant brands). All survivors are returned
in bia's own order. It also never writes: the trade name is DISPLAYED from
``bia_directory`` rather than folded into ``companies.Description``, so refreshing
the bia scrape refreshes the tearsheet and no curated prose is ever overwritten.
"""
from __future__ import annotations

import difflib
import re
from functools import lru_cache

from lib.bia import normalize_company_name

# --- Tuning constants (see the module docstring's measured bands) ------------

#: A trademark this similar to the legal name, written in the OTHER script, is a
#: transliteration of it rather than a distinct brand.
ECHO_RATIO_CROSS_SCRIPT = 0.55

#: The same test within one script, where real brands persist much higher.
ECHO_RATIO_SAME_SCRIPT = 0.62

#: Tokens shorter than this are ignored when testing novelty — Georgian
#: one/two-letter fragments ("2019", "ჯი") carry no brand information.
MIN_TOKEN_LEN = 3

_GEORGIAN_RE = re.compile(r"[Ⴀ-ჿ]")
_LATIN_RE = re.compile(r"[A-Za-z]")

# Georgian letter → its plain Latin value. Deliberately LOSSY: the aspirated and
# ejective pairs collapse onto one Latin letter because transliterators choose
# between them inconsistently (თბილისი is "Tbilisi", ტურკო is "Turko" — both t).
_GE_TO_LATIN = {
    "ა": "a", "ბ": "b", "გ": "g", "დ": "d", "ე": "e", "ვ": "v", "ზ": "z",
    "თ": "t", "ი": "i", "კ": "k", "ლ": "l", "მ": "m", "ნ": "n", "ო": "o",
    "პ": "p", "ჟ": "j", "რ": "r", "ს": "s", "ტ": "t", "უ": "u", "ფ": "p",
    "ქ": "k", "ღ": "g", "ყ": "k", "შ": "s", "ჩ": "c", "ც": "c", "ძ": "d",
    "წ": "c", "ჭ": "c", "ხ": "k", "ჯ": "j", "ჰ": "h",
}

# Latin digraphs that stand for one Georgian letter, folded so "shota" and
# "შოთა"→"sota" meet in the middle.
_DIGRAPHS = (("ch", "c"), ("sh", "s"), ("kh", "k"), ("ts", "c"),
             ("zh", "j"), ("gh", "g"))

# Georgian case endings, longest first. Only stripped when a real stem remains.
_CASE_ENDINGS = ("ისა", "ის", "ში", "ს", "ი")

# How each Latin letter's ENGLISH NAME is spelled in Georgian. This is what an
# initialism looks like once bia records it: G-C-C becomes "ჯისისი".
_LETTER_NAMES_KA = {
    "a": "ეი", "b": "ბი", "c": "სი", "d": "დი", "e": "ი", "f": "ეფ",
    "g": "ჯი", "h": "ეიჩ", "i": "აი", "j": "ჯეი", "k": "ქეი", "l": "ელ",
    "m": "ემ", "n": "ენ", "o": "ო", "p": "პი", "q": "ქიუ", "r": "არ",
    "s": "ეს", "t": "თი", "u": "იუ", "v": "ვი", "w": "დაბლიუ", "x": "იქს",
    "y": "ვაი", "z": "ზეტ",
}

# Words that are never part of a brand's identity for initialism purposes.
_INITIALISM_STOPWORDS = {
    "ltd", "llc", "jsc", "inc", "plc", "co", "company", "group", "holding",
    "georgia", "georgian", "international", "and", "the", "of",
}


# --- Script + skeleton ------------------------------------------------------

def scripts_of(text) -> tuple[bool, bool]:
    """``(has_georgian, has_latin)`` for a string."""
    s = str(text or "")
    return bool(_GEORGIAN_RE.search(s)), bool(_LATIN_RE.search(s))


def is_cross_script(name, trademark) -> bool:
    """True when one side is written in Latin and the other purely in Georgian.

    Such a pair CANNOT be compared token-wise — it shares no characters even when
    the two strings are the same name — so it gets the stricter echo threshold.
    """
    n_ge, n_lat = scripts_of(name)
    t_ge, t_lat = scripts_of(trademark)
    return (n_lat and t_ge and not t_lat) or (t_lat and n_ge and not n_lat)


def skeleton(text) -> str:
    """A coarse phonetic skeleton: script-independent, lossy, comparable.

    Georgian is transliterated, Latin digraphs are folded onto the same single
    letters, everything non-alphanumeric is dropped, look-alike Latin letters are
    unified (w→v, y→i, q→k) and runs of a repeated letter collapse. What survives
    is close enough that a name and its transliteration score high while two
    genuinely different brands score low.
    """
    s = normalize_company_name(text)
    s = "".join(_GE_TO_LATIN.get(ch, ch) for ch in s).lower()
    for digraph, single in _DIGRAPHS:
        s = s.replace(digraph, single)
    s = re.sub(r"[^a-z0-9]", "", s)
    s = s.translate(str.maketrans("wyq", "vik"))
    return re.sub(r"(.)\1+", r"\1", s)


def skeleton_similarity(name, trademark) -> float:
    """Similarity of two names' skeletons, 0.0-1.0."""
    a, b = skeleton(name), skeleton(trademark)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


# --- Stems + novelty --------------------------------------------------------

def stem(token: str) -> str:
    """A Georgian token with one case ending peeled off, if one can be.

    Guarded by length: ``ის`` is not stripped off ``ბის`` down to a two-letter
    fragment, and a token that is only an ending is left alone.
    """
    for ending in _CASE_ENDINGS:
        if token.endswith(ending) and len(token) - len(ending) >= MIN_TOKEN_LEN:
            return token[: -len(ending)]
    return token


def stems_of(text) -> set[str]:
    """The set of stemmed, information-carrying tokens in a name."""
    return {
        stem(tok)
        for tok in normalize_company_name(text).split()
        if len(tok) >= MIN_TOKEN_LEN
    }


def adds_new_word(name, trademark) -> bool:
    """True when the trademark contributes a stem the legal name lacks."""
    return bool(stems_of(trademark) - stems_of(name))


# --- Initialism -------------------------------------------------------------

def _initial_letters(name) -> str:
    """The Latin initials of a name's meaningful words, e.g. 'ICC GEORGIA'→'ic'.

    Words in ``_INITIALISM_STOPWORDS`` are skipped: they are shared by hundreds of
    companies and including them would make almost nothing match.
    """
    words = [w for w in re.split(r"[^A-Za-z]+", str(name or "")) if w]
    letters = []
    for word in words:
        low = word.lower()
        if low in _INITIALISM_STOPWORDS:
            continue
        if word.isupper() and len(word) > 1:
            # Already an acronym in the legal name ("ICC") — every letter counts.
            letters.extend(low)
        else:
            letters.append(low[0])
    return "".join(letters)


def is_initialism_echo(name, trademark) -> bool:
    """True when the trademark spells the legal name's initials out in Georgian.

    ``Georgian Concrete Club`` → ``ჯისისი`` is G-C-C read aloud. The name's
    initials are expanded into their Georgian letter-name spellings and the two
    skeletons compared; a near-exact match means the "brand" is the company's own
    acronym, which is not news.
    """
    initials = _initial_letters(name)
    if len(initials) < 2:
        return False
    t_ge, t_lat = scripts_of(trademark)
    if not t_ge or t_lat:
        # Only the Georgian-spelled-out form is detectable this way.
        return False
    spelled = "".join(_LETTER_NAMES_KA.get(ch, ch) for ch in initials)
    return skeleton_similarity(spelled, trademark) >= 0.85


# --- The decision -----------------------------------------------------------

def is_distinct_trade_name(name, trademark) -> bool:
    """True when this trademark is a brand you could not read off the legal name.

    All three filters must pass: it adds a word, it is not the same name in the
    other script (or spelled differently in this one), and it is not the legal
    name's own initialism.
    """
    tm = re.sub(r"\s+", " ", str(trademark or "")).strip()
    if not tm or not str(name or "").strip():
        return False
    if not adds_new_word(name, tm):
        return False
    limit = (ECHO_RATIO_CROSS_SCRIPT if is_cross_script(name, tm)
             else ECHO_RATIO_SAME_SCRIPT)
    if skeleton_similarity(name, tm) >= limit:
        return False
    return not is_initialism_echo(name, tm)


def trade_names(name, detail: dict | None) -> list[str]:
    """The distinct trade names bia records for a company, in bia's own order.

    ``detail`` is a ``lib.bia.parse_company_page`` dict (what
    ``lib.data_loader.get_bia_directory`` returns). Duplicates and whitespace
    variants are collapsed; an empty list means bia adds no brand information.
    """
    if not detail:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in detail.get("trademarks") or []:
        tm = re.sub(r"\s+", " ", str(raw or "")).strip()
        if not tm:
            continue
        key = normalize_company_name(tm)
        if key in seen:
            continue
        if is_distinct_trade_name(name, tm):
            seen.add(key)
            out.append(tm)
    return out


# --- Search ----------------------------------------------------------------
#
# Trade names are the ONLY handle many companies have in English: the legal name
# is Georgian, the curated blurb may not exist, but "Carrefour" is a word people
# type. Matching has to bridge the scripts, because bia stores the brand as
# Georgian PHONETICS of an English word (``კარფური``, ``მაკდონალდსი``,
# ``აჭარაბეთი``) and no substring test can see through that.
#
# ``search_key`` is a LOOSER fold than ``skeleton``, and deliberately a separate
# function: ``skeleton`` feeds the calibrated echo thresholds above, so widening
# it to help search would silently move which brands display. Extra folds here
# are the ones transliterators actually disagree on — ``ფ`` is written both "p"
# and "f" (ფული=puli, but კარფური=Carrefour), and Latin c/k/q collapse.

_SEARCH_DIGRAPHS = (("ch", "c"), ("sh", "s"), ("kh", "k"), ("ts", "c"),
                    ("zh", "j"), ("gh", "g"), ("ph", "p"), ("ck", "k"),
                    ("qu", "k"), ("dj", "j"), ("x", "ks"))

_VOWELS = set("aeiou")

#: Minimum fuzzy similarity for a trade name to answer a query. Measured on 20
#: real brand/English-query pairs: 0.72 accepts 18 (Carrefour→კარფური 0.80,
#: Adjarabet→აჭარაბეთი 0.82, McDonalds→მაკდონალდსი 0.90) and the two it misses
#: are pure vowel divergences that :func:`consonants` recovers.
SEARCH_MIN_RATIO = 0.72

#: A consonant skeleton shorter than this matches far too much to be evidence.
SEARCH_MIN_CONSONANTS = 3


@lru_cache(maxsize=8192)
def search_key(text) -> str:
    """A looser phonetic key than :func:`skeleton`, for matching user queries."""
    t = "".join(_GE_TO_LATIN.get(ch, ch) for ch in str(text or "")).lower()
    for digraph, single in _SEARCH_DIGRAPHS:
        t = t.replace(digraph, single)
    t = re.sub(r"[^a-z0-9]", "", t)
    t = t.translate(str.maketrans("wyqcf", "vikkp"))
    return re.sub(r"(.)\1+", r"\1", t)


@lru_cache(maxsize=8192)
@lru_cache(maxsize=8192)
def fold_nominative(key: str) -> str:
    """Drop a trailing Georgian nominative -i from a search key.

    bia writes the same brand both ways: Foodmart's is stored as ``სპარი``
    (SPAR + the nominative ending) and a franchisee's as bare ``სპარ``. Left
    unfolded these key differently, so the bare form scored an exact match and
    the declined one only a prefix match — ranking a tiny franchisee above the
    operator that actually runs the chain.
    """
    if len(key) >= 4 and key.endswith("i"):
        return key[:-1]
    return key


def consonants(text) -> str:
    """The consonant skeleton of a search key — vowels carry the least signal.

    ``Gulf`` and ``გალფი`` differ on their vowel (u vs a) and score only 0.67 by
    similarity, but both reduce to ``glp``. Transliterated brands diverge on
    vowels far more often than on consonants.
    """
    return "".join(ch for ch in search_key(text) if ch not in _VOWELS)


@lru_cache(maxsize=8192)
def _key_words(trade_name) -> tuple[str, ...]:
    """Search keys of a brand's individual words, blanks dropped.

    A tuple, not a list: the result is memoized and handing callers a shared
    mutable list invites action at a distance.
    """
    return tuple(k for k in (search_key(w)
                     for w in re.split(r"[\s\-/,]+", str(trade_name or ""))) if k)


def _ratio_at_least(a: str, b: str, floor: float) -> float:
    """``SequenceMatcher`` ratio, skipped when it cannot reach ``floor``.

    ``ratio()`` is the expensive part of search — it would run on every one of
    the ~2,040 indexed brands for each query. difflib ships two exact UPPER
    bounds for exactly this, so a brand whose bound is already below the floor is
    dropped without the real computation and the surviving scores are unchanged.
    Returns the bound (not the true ratio) when it short-circuits; callers only
    ever compare against the floor.
    """
    matcher = difflib.SequenceMatcher(None, a, b)
    if matcher.real_quick_ratio() < floor:
        return 0.0
    if matcher.quick_ratio() < floor:
        return 0.0
    return matcher.ratio()


def match_score(query, trade_name, floor: float = 0.0) -> float:
    """How well a query answers a trade name, 0.0-1.0.

    Scored in explicit TIERS rather than one similarity number, because a raw
    "either string contains the other" rule ranks the wrong company first:

    * it is symmetric, so the short brand ``კარე`` ("kare") is contained in the
      query "Carrefour" ("karepour") and scored a perfect match, beating the
      actual ``კარფური``;
    * it ignores word boundaries, so "spar" matches inside
      ``ბათუმის პარკინგი`` ("batumi**spar**kingi") — an accident, not a brand.

    So an exact or PREFIX match on a brand word ranks above an interior
    substring, and the reverse direction (the query containing the brand) only
    counts when the brand is most of the query — otherwise every two-syllable
    brand answers every long query.

    ``floor`` is a performance hint: with it set, a fuzzy score that cannot reach
    it may be reported as 0.0 instead of its true (still-below-floor) value. The
    tiered scores above the floor are always exact.
    """
    kq, kb = search_key(query), search_key(trade_name)
    if not kq or not kb:
        return 0.0
    words = _key_words(trade_name)
    fq = fold_nominative(kq)
    if kq == kb or kq in words:
        return 1.0
    if fq == fold_nominative(kb) or any(fq == fold_nominative(w) for w in words):
        return 1.0
    if kb.startswith(kq) or any(w.startswith(kq) for w in words):
        return 0.95
    cq = consonants(query)
    if len(cq) >= SEARCH_MIN_CONSONANTS and (
            cq == consonants(trade_name)
            or any(cq == "".join(c for c in w if c not in _VOWELS) for w in words)):
        return 0.92
    # Interior substring: real ("იბის სტაილს" for a query matching mid-word) but
    # accident-prone, so it sits below every boundary-respecting tier and needs a
    # query long enough not to hit by chance.
    if len(kq) >= 4 and kq in kb:
        return 0.88
    # Query CONTAINS the brand — only meaningful when the brand accounts for most
    # of the query, else "kare" answers "carrefour".
    best = 0.90 if (kb in kq and len(kb) >= 0.7 * len(kq)) else 0.0
    if best < 1.0:
        best = max(best, _ratio_at_least(kq, kb, floor))
        for w in words:
            best = max(best, _ratio_at_least(kq, w, floor))
    return best


def build_trade_name_index(rows) -> dict[str, list[str]]:
    """``{IdCode: [trade name, ...]}`` from ``(idcode, company_name, detail)``.

    Only companies with at least one distinct trade name appear. Pure, so the
    caller owns the DB pass (see ``lib.cache.trade_name_index``).
    """
    index: dict[str, list[str]] = {}
    for idcode, name, detail in rows:
        names = trade_names(name, detail)
        if names:
            index[str(idcode)] = names
    return index


def search_trade_names(index: dict[str, list[str]], query,
                       limit: int = 5, exclude=(),
                       min_score: float = SEARCH_MIN_RATIO
                       ) -> list[tuple[str, str, float]]:
    """``[(IdCode, matched trade name, score)]`` for a query, best match first.

    The score is returned because ranking cannot be finished here: this module
    knows nothing about company size, and two companies whose brands match a
    query EQUALLY well should be ordered by revenue, which only the caller can
    see. Callers that do not care can ignore the third element.

    Single-character queries return nothing — one letter matches most brands and
    would bury the exact company-name hits the caller ranks above these.
    ``exclude`` drops IdCodes already surfaced by a stronger pass.

    ``min_score`` raises the bar above :data:`SEARCH_MIN_RATIO`. A ranked top-5
    palette can afford the fuzzy tail — the user reads the list and picks — but a
    FILTER that asserts "these companies match" cannot: at the default floor,
    "SPAR" pulls in ``შპალერი`` and ``სუპერი სათამაშო`` alongside the real
    thing. Pass ``0.9`` to keep only the exact / prefix / consonant tiers.
    """
    q = str(query or "").strip()
    if len(q) < 2 or not search_key(q):
        return []
    skip = {str(x) for x in exclude}
    scored: list[tuple[float, str, str]] = []
    for idcode, names in index.items():
        if idcode in skip:
            continue
        best_score, best_name = 0.0, ""
        for name in names:
            score = match_score(q, name, floor=min_score)
            if score > best_score:
                best_score, best_name = score, name
        if best_score >= min_score:
            scored.append((best_score, idcode, best_name))
    # Score desc, then IdCode for a stable order between equal scores.
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [(idcode, name, score) for score, idcode, name in scored[:limit]]


def trade_name_label(names: list[str]) -> str:
    """Human phrasing for a trade-name list: ``Trades as X`` / ``X, Y and Z``.

    Empty list gives an empty string, so callers can render unconditionally.
    """
    clean = [n for n in names if n]
    if not clean:
        return ""
    if len(clean) == 1:
        joined = clean[0]
    else:
        joined = ", ".join(clean[:-1]) + " and " + clean[-1]
    return f"Trades as {joined}"
