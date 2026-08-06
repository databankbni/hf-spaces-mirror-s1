"""Map a free-text sub-sector phrase onto the curated vocabulary, deterministically.

Stage 3b of the sector pipeline normally asks a model to fold the classifier's
free-text sub-sectors into the DB's curated buckets
(``group_subsectors_llm.py --map-to-db``). This module does the easy fraction of
that job with no model at all, so the mapping is not blocked on having budget and
so the model only ever has to look at the genuinely hard phrases.

It is deliberately a HIGH-PRECISION, LOW-COVERAGE matcher. The asymmetry comes
from what the two kinds of error cost downstream: a phrase left unmapped is
withheld by the writer and the company simply keeps its existing SubSector (no
harm), while a phrase mapped to the wrong bucket writes a wrong value into
production and is invisible afterwards. So the threshold is set where precision is
near-total and most phrases are refused.

CALIBRATION. ``apply_sector_overrides`` already contains 672 analyst-authored
``phrase -> bucket`` pairs across its two canon layers, which is real ground truth
for exactly this task. Scoring each phrase against every bucket in its own sector
and taking the top pick:

    threshold   accepted   precision   coverage
        (none)       672       69.3%      100.0%
         0.30        510       84.1%       75.9%
         0.50        434       87.8%       64.6%
         0.60        289       95.2%       43.0%
        *0.70        178       99.4%       26.5%

:data:`MIN_SCORE` is 0.70 — one error in 178. Lowering it to 0.60 would buy 16
points of coverage for a 20x worse error rate, which is the wrong trade when the
alternative to a match is a harmless no-op.

Caveat worth keeping in mind: that ground truth is pairs an analyst WROTE as
corresponding, so it is a friendlier population than the unmapped tail. Treat the
precision figure as an upper bound, which is another reason to keep the threshold
high.

Pure/stdlib-only: no DB, no network, no Streamlit, no model.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping

__all__ = ["MIN_SCORE", "normalize", "score", "best_bucket", "map_phrases"]

#: Accept a match at or above this token-set F1. See the calibration table above.
MIN_SCORE = 0.70

#: Words that carry no discriminating signal in a sub-sector name. Dropping them
#: is what lets 'pharma wholesale' reach 'Pharma Distribution' — but note they are
#: dropped from BOTH sides, so a bucket whose whole name is a stopword ('Other',
#: 'Services') normalises to nothing and can never match. That is intended: those
#: are parking buckets, not homes.
STOPWORDS = frozenset({
    "and", "of", "the", "for", "in", "to", "a",
    "services", "service", "other", "general", "unspecified", "misc",
    "various", "related", "activities", "activity",
})


def normalize(text: str) -> list[str]:
    """Comparable tokens for a phrase or a bucket name.

    Case, punctuation and ``&``/``and`` are levelled, and the ``Retail - Apparel``
    prefix style collapses to plain tokens so it can meet ``clothing apparel``.
    The plural trim is crude on purpose — a stemmer would be another dependency
    for a handful of ``-s`` endings, and it is length-guarded so short words
    ('gas', 'glass') survive intact.
    """
    s = unicodedata.normalize("NFKC", str(text)).casefold()
    s = s.replace("&", " and ")
    # Keep Georgian as well as ASCII: some phrases arrive untranslated.
    s = re.sub(r"[^a-z0-9Ⴀ-ჿ]+", " ", s)
    out: list[str] = []
    for tok in s.split():
        if tok in STOPWORDS:
            continue
        if len(tok) > 4 and tok.endswith("s") and not tok.endswith("ss"):
            tok = tok[:-1]
        out.append(tok)
    return out


def score(phrase: str, bucket: str) -> float:
    """Token-set F1 between a phrase and a candidate bucket, 0.0-1.0.

    F1 rather than plain overlap or containment so that BOTH directions cost
    something: 'retail' alone should not score 1.0 against 'Retail - Consumer
    Electronics', and a six-word phrase should not win on one shared token.
    """
    a, b = set(normalize(phrase)), set(normalize(bucket))
    if not a or not b:
        return 0.0
    shared = len(a & b)
    if not shared:
        return 0.0
    return 2 * shared / (len(a) + len(b))


def best_bucket(phrase: str, buckets: Iterable[str],
                min_score: float = MIN_SCORE) -> tuple[str | None, float]:
    """The best-scoring bucket for ``phrase``, or ``(None, score)`` if none clears
    ``min_score``.

    A TIE IS A REFUSAL. Two buckets scoring equally means the phrase does not
    discriminate between them, and picking either by iteration order would be
    arbitrary — exactly the silent-wrong-value case this module exists to avoid.
    """
    ranked = sorted(((score(phrase, b), b) for b in buckets),
                    key=lambda sb: (-sb[0], sb[1]))
    if not ranked:
        return None, 0.0
    top_score, top_bucket = ranked[0]
    if top_score < min_score:
        return None, top_score
    if len(ranked) > 1 and ranked[1][0] == top_score:
        return None, top_score
    return top_bucket, top_score


def map_phrases(phrases: Iterable[str], buckets: Iterable[str],
                min_score: float = MIN_SCORE,
                ) -> tuple[dict[str, str], dict[str, float]]:
    """Map what can be mapped confidently; report the rest with its best score.

    Returns ``(mapped, refused)`` where ``refused`` maps each unmapped phrase to
    the score it fell short at — so a later model pass can be pointed at the near
    misses first, and so a threshold change can be argued from data.
    """
    bucket_list = list(buckets)
    mapped: dict[str, str] = {}
    refused: dict[str, float] = {}
    for phrase in phrases:
        bucket, sc = best_bucket(phrase, bucket_list, min_score)
        if bucket is None:
            refused[phrase] = sc
        else:
            mapped[phrase] = bucket
    return mapped, refused


def map_by_sector(
    phrases_by_sector: Mapping[str, Iterable[str]],
    buckets_by_sector: Mapping[str, Iterable[str]],
    min_score: float = MIN_SCORE,
) -> tuple[dict[str, dict], dict[str, dict[str, float]]]:
    """Per-sector convenience wrapper.

    Emits the ``{sector: {"groups": [...], "map": {...}}}`` shape
    ``apply_sector_from_reports.py --subsector-groups`` already consumes, so the
    deterministic pass is a drop-in for the model-produced file.
    """
    groups: dict[str, dict] = {}
    refused: dict[str, dict[str, float]] = {}
    for sector, phrases in phrases_by_sector.items():
        mapped, miss = map_phrases(phrases, buckets_by_sector.get(sector, ()),
                                   min_score)
        if mapped:
            groups[sector] = {"groups": sorted(set(mapped.values())), "map": mapped}
        if miss:
            refused[sector] = miss
    return groups, refused
