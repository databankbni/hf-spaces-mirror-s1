"""Tokenization and BM25 scoring for hybrid retrieval."""

from __future__ import annotations

import math
import re
from collections import Counter

TOKEN_RE = re.compile(r"[\w\u0600-\u06FF]+", re.UNICODE)
STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "with", "is", "are",
    "this", "that", "be", "as", "by", "from", "at", "it", "its", "was", "were", "will",
    "can", "if", "not", "no", "yes", "into", "than", "then", "also", "such", "using",
}


def tokenize(text: str) -> list[str]:
    tokens = [t.lower() for t in TOKEN_RE.findall(text or "")]
    return [t for t in tokens if len(t) > 1 and t not in STOPWORDS]


class BM25Index:
    """Okapi BM25 over a tokenized corpus."""

    def __init__(self, documents: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.corpus = documents
        self.n = len(documents)
        self.doc_len = [len(d) for d in documents]
        self.avgdl = (sum(self.doc_len) / self.n) if self.n else 0.0
        df: Counter[str] = Counter()
        for doc in documents:
            df.update(set(doc))
        self.idf = {
            term: math.log(1.0 + (self.n - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }
        self.doc_tf = [Counter(doc) for doc in documents]

    def scores(self, query_tokens: list[str]) -> list[float]:
        out: list[float] = []
        for i, tf in enumerate(self.doc_tf):
            score = 0.0
            dl = self.doc_len[i] or 1
            norm = self.k1 * (1.0 - self.b + self.b * dl / max(self.avgdl, 1.0))
            for term in query_tokens:
                if term not in tf:
                    continue
                freq = tf[term]
                idf = self.idf.get(term, 0.0)
                score += idf * (freq * (self.k1 + 1.0)) / (freq + norm)
            out.append(score)
        return out
