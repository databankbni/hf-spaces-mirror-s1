"""Stream C — stylometric / structural features.

These capture *how* text is structured (sentence-length rhythm, lexical diversity, function-word use,
repetition) rather than *which exact tokens* appear. They are comparatively robust to paraphrasing,
which rewrites surface tokens but tends to preserve an author's structural fingerprint — and, unlike
raw perplexity, they don't collapse non-native human text onto AI text. Pure-Python, no heavy deps.
"""
from __future__ import annotations
import math
import re
import numpy as np

# Small closed-class function-word list (paraphrase-stable; AI vs human differ in their distribution).
_FUNCTION_WORDS = {
    "the", "a", "an", "and", "or", "but", "if", "while", "of", "at", "by", "for", "with", "about",
    "against", "between", "into", "through", "during", "before", "after", "above", "below", "to",
    "from", "up", "down", "in", "out", "on", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "all", "any", "both", "each", "few", "more", "most", "other", "some",
    "such", "no", "nor", "not", "only", "own", "same", "so", "than", "too", "very", "can", "will",
    "just", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does",
    "did", "this", "that", "these", "those", "i", "you", "he", "she", "it", "we", "they", "them",
    "his", "her", "its", "their", "as", "because", "however", "therefore", "thus", "moreover",
}

_WORD_RE = re.compile(r"[A-Za-z']+")
_SENT_RE = re.compile(r"[.!?]+")

FEATURE_NAMES = [
    "log_n_words", "mean_sent_len", "std_sent_len", "type_token_ratio", "hapax_ratio",
    "mean_word_len", "std_word_len", "punct_density", "comma_per_word", "function_word_ratio",
    "bigram_repetition", "uppercase_ratio", "digit_ratio", "stopword_gap_std",
]
N_FEATURES = len(FEATURE_NAMES)


def stylometric_features(text: str) -> np.ndarray:
    """Return a fixed-length (N_FEATURES,) float vector of stylometric features."""
    if not text or not text.strip():
        return np.zeros(N_FEATURES, dtype=float)

    words = _WORD_RE.findall(text.lower())
    n_words = len(words)
    if n_words == 0:
        return np.zeros(N_FEATURES, dtype=float)

    sents = [s for s in _SENT_RE.split(text) if s.strip()]
    n_sents = max(len(sents), 1)
    sent_lens = [len(_WORD_RE.findall(s)) for s in sents] or [n_words]

    uniq = set(words)
    counts: dict[str, int] = {}
    for w in words:
        counts[w] = counts.get(w, 0) + 1
    hapax = sum(1 for c in counts.values() if c == 1)

    word_lens = [len(w) for w in words]
    chars = len(text)
    n_punct = sum(text.count(c) for c in ",.;:!?\"'()-")
    n_commas = text.count(",")
    n_func = sum(1 for w in words if w in _FUNCTION_WORDS)
    bigrams = list(zip(words[:-1], words[1:]))
    bigram_rep = 1.0 - (len(set(bigrams)) / len(bigrams)) if bigrams else 0.0
    letters = sum(1 for ch in text if ch.isalpha())
    uppers = sum(1 for ch in text if ch.isupper())
    digits = sum(1 for ch in text if ch.isdigit())

    # rhythm of function words: gaps (in tokens) between successive function words
    func_pos = [i for i, w in enumerate(words) if w in _FUNCTION_WORDS]
    gaps = np.diff(func_pos) if len(func_pos) > 1 else np.array([0.0])

    feats = [
        math.log1p(n_words),
        float(np.mean(sent_lens)),
        float(np.std(sent_lens)),
        len(uniq) / n_words,
        hapax / max(len(uniq), 1),
        float(np.mean(word_lens)),
        float(np.std(word_lens)),
        n_punct / max(chars, 1),
        n_commas / n_words,
        n_func / n_words,
        bigram_rep,
        uppers / max(letters, 1),
        digits / max(chars, 1),
        float(np.std(gaps)),
    ]
    return np.array(feats, dtype=float)


def stylometric_matrix(texts: list[str]) -> np.ndarray:
    """(len(texts), N_FEATURES) feature matrix."""
    return np.vstack([stylometric_features(t) for t in texts]) if texts \
        else np.zeros((0, N_FEATURES))


if __name__ == "__main__":  # smoke test
    ai = "The implementation leverages a robust framework. The system processes data efficiently. " \
         "The results demonstrate significant improvements across all evaluated metrics."
    hu = "I dunno, it kinda worked? We tried a bunch of stuff and, honestly, some of it broke — " \
         "but the demo went fine in the end, somehow."
    for name, t in [("AI-ish", ai), ("human-ish", hu)]:
        v = stylometric_features(t)
        print(name, dict(zip(FEATURE_NAMES, np.round(v, 3))))
    assert stylometric_features("").shape == (N_FEATURES,)
    assert stylometric_matrix([ai, hu]).shape == (2, N_FEATURES)
    print("stylometric self-test passed")
