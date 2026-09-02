"""Dynamic literature exemplar retrieval from the operator corpus.

Loads *My literature April 2026.docx* at runtime, segments it into topical
passages and explicit draft->edited demonstration pairs, indexes them with the
same hybrid (BM25 + dense) primitives the RAG store uses, and selects the most
relevant exemplars for a live task (section label + notes).

Two output shapes:

* **Reference exhibits** - topical passages injected as PHRASING-ONLY guidance.
  The corpus is correspondence/clauses describing *other* properties, so hard
  specifics (money, dates, measurements, percentages, URLs, phones) are redacted
  and the prompt fences them as non-factual. This is the design that lets us
  surface authoritative RICS register without reintroducing the foreign-fact
  bleed the deterministic reducers exist to prevent.
* **Few-shot pairs** - genuine draft->edited rewrites mined from the doc (e.g.
  ``Felicity Paragraph:`` -> ``Felicity Edited:``; ``My original ...`` -> ``My
  final version ...``), surfaced as real user/assistant demonstration turns.

The bank is a process singleton keyed by ``(path, mtime, size)``; editing the
``.docx`` refreshes it on the next request. Every failure path degrades to "no
exemplars" so generation never breaks because the corpus is missing or malformed.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

from backend.config import settings
from backend.prompts.prompt_few_shot_examples import FewShotTurn
from backend.rag.lexical_index import BM25Index, reciprocal_rank_fusion, tokenize

logger = logging.getLogger(__name__)

__all__ = [
    "LiteraturePassage",
    "LiteratureSelection",
    "redact_specifics",
    "fetch_exemplars",
    "reset_bank",
]

# Passages shorter than this carry no usable phrasing (labels, list bullets,
# salutations). Longer ones are real professional prose worth surfacing.
_MIN_PASSAGE_CHARS = 80
_MAX_PASSAGE_CHARS = 1200
_MAX_PASSAGES = 6000

# Label lines (short, colon-terminated) become the topic for following prose and
# drive draft->edited pairing.
_LABEL_RE = re.compile(r"^[^.!?]{0,80}:\s*$")
_DRAFT_MARKER = re.compile(r"(?i)\b(original|draft|paragraph|before|version\s*1)\b")
_FINAL_MARKER = re.compile(r"(?i)\b(edited|final|revised|after|amended|version\s*2)\b")

# ── Specifics redaction (the primary fact-bleed guard for exhibits) ──────────
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE_RE = re.compile(r"\b(?:\+?\d[\d ()-]{7,}\d)\b")
_MONEY_RE = re.compile(r"£\s?\d[\d,]*(?:\.\d+)?")
_PERCENT_RE = re.compile(r"\b\d+(?:\.\d+)?\s?%")
_MEASURE_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s?(?:mm|cm|m|metres?|meters?|inch(?:es)?|ft|feet|"
    r"years?|months?|weeks?|days?|storeys?|stories|sq\.?\s?m|m2|kg|litres?|miles?)\b",
    re.IGNORECASE,
)
_MONTHS = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
_DATE_RE = re.compile(
    rf"\b(?:\d{{1,2}}(?:st|nd|rd|th)?\s+)?{_MONTHS}\.?\s+\d{{4}}\b", re.IGNORECASE
)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
# Standalone integers/decimals not already caught (counts, "tranche", indices).
_BARE_NUM_RE = re.compile(r"(?<![\w£%])\d[\d,]*(?:\.\d+)?(?![\w%])")


def redact_specifics(text: str) -> str:
    """Mask other-property specifics while preserving sentence structure.

    Money/dates/measurements/percentages/URLs/phones are the dominant bleed
    vectors from this corpus; replacing them with neutral placeholders keeps the
    authoritative phrasing usable as a style reference without smuggling foreign
    facts past the LLM. Proper nouns are intentionally NOT scrubbed here (no NER)
    - the prompt fence plus the downstream reducers cover residual names.
    """
    if not text:
        return text
    out = _URL_RE.sub("[link]", text)
    out = _EMAIL_RE.sub("[email]", out)
    out = _MONEY_RE.sub("£[amount]", out)
    out = _PERCENT_RE.sub("[percentage]", out)
    out = _DATE_RE.sub("[date]", out)
    out = _MEASURE_RE.sub("[measurement]", out)
    out = _PHONE_RE.sub("[number]", out)
    out = _YEAR_RE.sub("[year]", out)
    out = _BARE_NUM_RE.sub("[number]", out)
    return re.sub(r"[ \t]{2,}", " ", out).strip()


@dataclass(frozen=True)
class LiteraturePassage:
    """One indexable literature passage (injection-ready text plus its origin)."""

    text: str
    topic: str = ""


@dataclass
class LiteratureSelection:
    """Result of a live exemplar lookup for one task."""

    exhibits: list[str] = field(default_factory=list)
    pairs: list[FewShotTurn] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.exhibits and not self.pairs


# ── Segmentation ─────────────────────────────────────────────────────────────


def _is_noise(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if _URL_RE.fullmatch(stripped) or _EMAIL_RE.fullmatch(stripped):
        return True
    # Mostly-digits / phone-only / reference codes.
    alpha = sum(c.isalpha() for c in stripped)
    return alpha < max(8, len(stripped) // 4)


def _segment(blocks: list) -> tuple[list[LiteraturePassage], list[FewShotTurn]]:
    """Split extracted blocks into topical passages and draft->edited pairs.

    ``blocks`` are :class:`backend.ingest.doc_extractor.Block` (text/is_heading).
    A short colon-terminated line (or a heading) is treated as a label that names
    the topic for the prose that follows and anchors draft/edited pairing.
    """
    passages: list[LiteraturePassage] = []
    # (label, marker_kind, passage_text) in document order for pair mining.
    labelled: list[tuple[str, str, str]] = []
    current_label = ""

    for blk in blocks:
        text = (getattr(blk, "text", "") or "").strip()
        if not text:
            continue
        is_heading = bool(getattr(blk, "is_heading", False))
        is_label = is_heading or _LABEL_RE.match(text) is not None

        if is_label:
            current_label = text.rstrip(":").strip()[:80]
            continue
        if _is_noise(text):
            continue

        snippet = text[:_MAX_PASSAGE_CHARS]
        if len(snippet) >= _MIN_PASSAGE_CHARS:
            passages.append(LiteraturePassage(text=snippet, topic=current_label))
            if len(passages) >= _MAX_PASSAGES:
                break

        marker = ""
        if _DRAFT_MARKER.search(current_label):
            marker = "draft"
        elif _FINAL_MARKER.search(current_label):
            marker = "final"
        if marker and len(text) >= 120:
            labelled.append((current_label, marker, snippet))

    return passages, _mine_pairs(labelled)


def _topic_root(label: str) -> str:
    """Strip draft/final markers so 'Felicity Paragraph'/'Felicity Edited' align."""
    root = _DRAFT_MARKER.sub("", label)
    root = _FINAL_MARKER.sub("", root)
    return re.sub(r"[^a-z0-9]+", " ", root.lower()).strip()


def _mine_pairs(labelled: list[tuple[str, str, str]]) -> list[FewShotTurn]:
    """Pair the nearest draft passage with a following final passage on a topic."""
    pairs: list[FewShotTurn] = []
    pending: dict[str, str] = {}  # topic root -> draft text
    for label, marker, text in labelled:
        root = _topic_root(label)
        if marker == "draft":
            pending[root] = text
        elif marker == "final" and root in pending:
            draft = pending.pop(root)
            if draft and text and draft != text:
                user = (
                    "Rewrite the following draft RICS surveyor passage into the "
                    "firm's polished house style. Preserve every fact; improve "
                    "register, structure, and clarity only.\n\nDRAFT:\n" + draft
                )
                pairs.append(FewShotTurn(user=user, assistant=text))
    return pairs


# ── Hybrid index over passages ───────────────────────────────────────────────


class LiteratureExemplarBank:
    """In-process hybrid (BM25 + dense) index over literature passages."""

    def __init__(
        self,
        passages: list[LiteraturePassage],
        pairs: list[FewShotTurn],
        *,
        embedder=None,
    ) -> None:
        import numpy as np

        self._passages = passages
        self._pairs = pairs
        self._bm25 = (
            BM25Index([tokenize(p.text) for p in passages]) if passages else None
        )

        self._matrix = None
        if passages:
            from backend.llm.embeddings import get_embedder

            self._embedder = embedder or get_embedder()
            vecs = self._embedder.embed_documents([p.text for p in passages])
            self._matrix = np.asarray(vecs, dtype="float32")
        else:
            self._embedder = embedder

    def __len__(self) -> int:
        return len(self._passages)

    def select(
        self, query: str, *, k: int, min_score: float
    ) -> list[tuple[LiteraturePassage, float]]:
        if not self._passages or self._matrix is None or k <= 0:
            return []
        import numpy as np

        q_tokens = tokenize(query)
        pool = max(k * 5, 20)
        bm25_ranked = (
            [i for i, _ in self._bm25.top_n(q_tokens, pool)] if self._bm25 else []
        )
        bm25_hits = set(bm25_ranked)

        qvec = np.asarray(self._embedder.embed_query(query), dtype="float32")
        dense = self._matrix @ qvec  # cosine (vectors are normalized)
        dense_ranked = np.argsort(-dense)[:pool].tolist()

        fused = reciprocal_rank_fusion(
            [bm25_ranked, dense_ranked], k=settings.hybrid_rrf_k
        )

        out: list[tuple[LiteraturePassage, float]] = []
        seen_topics: set[str] = set()
        seen_sigs: set[str] = set()
        for idx, _score in fused:
            cos = float(dense[idx])
            # Hybrid gate: keep a candidate if it clears the dense floor OR is a
            # genuine lexical match. A strong BM25 hit must not be vetoed by a
            # weak embedding score — that is the whole point of fusing the arms.
            if cos < min_score and idx not in bm25_hits:
                continue
            passage = self._passages[idx]
            # One exhibit per topic keeps the shortlist diverse, not three
            # near-duplicate clauses from the same cluster.
            topic_key = passage.topic.lower()
            if topic_key and topic_key in seen_topics:
                continue
            # Content signature (lead tokens) drops near-identical bodies that
            # differ only by trailing words — the corpus has many such variants.
            sig = " ".join(tokenize(passage.text)[:12])
            if sig and sig in seen_sigs:
                continue
            seen_topics.add(topic_key)
            seen_sigs.add(sig)
            out.append((passage, cos))
            if len(out) >= k:
                break
        return out

    def pairs(self, limit: int) -> list[FewShotTurn]:
        return self._pairs[: max(0, limit)]


# ── Singleton + live (mtime-keyed) loading ───────────────────────────────────

_bank: LiteratureExemplarBank | None = None
_bank_key: tuple[str, int, int] | None = None
_lock = threading.Lock()


def _resolve_corpus_path() -> Path | None:
    raw = (settings.literature_corpus_filename or "").strip()
    if not raw:
        return None
    cand = Path(raw)
    if cand.is_absolute():
        return cand if cand.is_file() else None
    project_root = Path(__file__).resolve().parents[2]
    for base in (project_root, Path.cwd()):
        p = base / raw
        if p.is_file():
            return p
    return None


def _build_bank(path: Path) -> LiteratureExemplarBank:
    from backend.ingest.doc_extractor import extract_blocks

    blocks = extract_blocks(path)
    passages, pairs = _segment(blocks)
    if settings.literature_redact_specifics:
        passages = [
            LiteraturePassage(text=redact_specifics(p.text), topic=p.topic)
            for p in passages
        ]
    logger.info(
        "Literature corpus indexed: %d passages, %d draft->edited pairs from %s",
        len(passages),
        len(pairs),
        path.name,
    )
    return LiteratureExemplarBank(passages, pairs)


def _get_bank() -> LiteratureExemplarBank | None:
    global _bank, _bank_key
    path = _resolve_corpus_path()
    if path is None:
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    key = (str(path), int(stat.st_mtime), int(stat.st_size))
    if _bank is not None and _bank_key == key:
        return _bank
    with _lock:
        if _bank is not None and _bank_key == key:
            return _bank
        try:
            _bank = _build_bank(path)
            _bank_key = key
        except (
            Exception
        ) as exc:  # noqa: BLE001 - corpus problems must not break generation
            logger.warning(
                "Literature corpus load failed (%s); dynamic exemplars off.", exc
            )
            _bank = None
            _bank_key = key  # cache the failure for this file version
    return _bank


def reset_bank() -> None:
    """Drop the cached bank (tests / forced reload)."""
    global _bank, _bank_key
    with _lock:
        _bank = None
        _bank_key = None


def fetch_exemplars(query: str, *, k: int | None = None) -> LiteratureSelection:
    """Select task-relevant literature exhibits + mined pairs for ``query``.

    Returns an empty selection when the feature is disabled, the corpus is
    unavailable, or nothing clears the relevance floor.
    """
    if not settings.prompt_dynamic_literature_enabled:
        return LiteratureSelection()
    query = (query or "").strip()
    if not query:
        return LiteratureSelection()
    bank = _get_bank()
    if bank is None:
        return LiteratureSelection()

    top_k = settings.literature_exemplar_top_k if k is None else k
    selected = bank.select(
        query, k=top_k, min_score=settings.literature_exemplar_min_score
    )
    exhibits = [p.text for p, _ in selected]
    pairs = bank.pairs(settings.literature_exemplar_pairs_max)
    return LiteratureSelection(exhibits=exhibits, pairs=pairs)
