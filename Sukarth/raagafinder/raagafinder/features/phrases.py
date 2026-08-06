"""Pure-numpy phrase/motif features: NOTE ORDER, the one lever the distribution
features (PCD, TDMS) structurally cannot pull.

PCD is a note histogram; TDMS a histogram of note pairs at one fixed time
delay. Neither sees a characteristic phrase like N-S-R-G vs N-D-N-S that
separates allied ragas sharing a note set. Here the tonic-normalized,
octave-folded contour is quantized to swaras, collapsed to the melodic
skeleton (notes actually dwelt on; gamaka flicker removed), and turned into a
bag of note BIGRAMS + TRIGRAMS -- the transitions and turns themselves.
Trigrams are strictly beyond TDMS's pairwise surface.

Shared verbatim between training (scripts/fit_dirB_phrases.py,
scripts/build_phrase_component.py) and serving
(raagafinder/models/phrase_ngram.py). No sklearn, no torch.
"""

import numpy as np

H = 0.04            # resample hop (s): uniform grid regardless of source hop
GAP_S = 0.25        # split into phrases at unvoiced gaps longer than this
N_SEMI = 12         # swara quantization (12 semitone bins per octave)


def resample_folded(folded, voiced, hop):
    """Nearest-frame resample of the octave-folded contour onto a uniform
    H-grid, NaN where unvoiced. Removes per-source hop differences."""
    dur = len(folded) * hop
    n = int(dur / H)
    if n < 4:
        return None
    src = np.clip((np.arange(n) * (H / hop)).astype(int), 0, len(folded) - 1)
    val = folded[src].astype(np.float64)
    val[~voiced[src].astype(bool)] = np.nan
    return val


def collapse_stable(q, min_hold):
    """A run shorter than min_hold frames is gamaka flicker / a passing tone,
    not a note the phrase rests on -- drop it. Consecutive duplicates collapse
    so only the melodic skeleton (the note sequence) survives; durations are
    left to PCD."""
    out = []
    if len(q) == 0:
        return out
    cur, run = q[0], 1
    for x in q[1:]:
        if x == cur:
            run += 1
        else:
            if run >= min_hold and (not out or out[-1] != cur):
                out.append(int(cur))
            cur, run = x, 1
    if run >= min_hold and (not out or out[-1] != cur):
        out.append(int(cur))
    return out


def note_phrases(folded, voiced, hop, min_hold):
    """List of melodic-skeleton note sequences, one per breath phrase."""
    val = resample_folded(folded, voiced, hop)
    if val is None:
        return []
    gap_frames = max(1, int(GAP_S / H))
    q = np.mod(np.round(val / (1200.0 / N_SEMI)), N_SEMI)   # NaN stays NaN
    phrases, cur, gap = [], [], 0
    for k in range(len(val)):
        if np.isnan(q[k]):
            gap += 1
            if gap > gap_frames and cur:
                phrases.append(cur)
                cur = []
        else:
            gap = 0
            cur.append(int(q[k]))
    if cur:
        phrases.append(cur)
    out = []
    for p in phrases:
        s = collapse_stable(np.array(p), min_hold)
        if len(s) >= 2:
            out.append(s)
    return out


def vocab():
    """Fixed n-gram column layout over the 12-swara alphabet (no data-derived
    columns -> no feature-selection leakage)."""
    bi = {(a, b): a * N_SEMI + b for a in range(N_SEMI) for b in range(N_SEMI)}
    off = N_SEMI * N_SEMI
    tri = {(a, b, c): off + (a * N_SEMI + b) * N_SEMI + c
           for a in range(N_SEMI) for b in range(N_SEMI) for c in range(N_SEMI)}
    return bi, tri, off + N_SEMI ** 3


BI, TRI, V = vocab()


def bow(phrases):
    """Raw bigram+trigram counts over a list of note sequences."""
    v = np.zeros(V, dtype=np.float64)
    for s in phrases:
        for i in range(len(s) - 1):
            v[BI[(s[i], s[i + 1])]] += 1.0
        for i in range(len(s) - 2):
            v[TRI[(s[i], s[i + 1], s[i + 2])]] += 1.0
    return v


def recording_bow(folded_segments, min_hold):
    """Pooled bigram+trigram counts over all segments of one recording.
    folded_segments: iterable of (folded, voiced, hop)."""
    phrases = []
    for folded, voiced, hop in folded_segments:
        phrases += note_phrases(folded, voiced, hop, min_hold)
    if not phrases:
        return None
    return bow(phrases)


def tfidf_vector(counts, idf):
    """L1 term-frequency * idf, L2-normalized (matches training)."""
    tf = counts / max(counts.sum(), 1.0)
    z = tf * idf
    return z / max(np.linalg.norm(z), 1e-9)
