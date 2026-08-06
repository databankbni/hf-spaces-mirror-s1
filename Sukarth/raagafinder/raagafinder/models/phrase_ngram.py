"""Phrase n-gram ensemble member: pure-numpy note-order classifier.

The distribution features (PCD/TDMS) and the LSTM's fixed-window softmax both
miss, or only weakly capture, longer characteristic phrases. This component
scores a recording by the transitions and turns in its melodic skeleton (note
bigrams + trigrams; see raagafinder.features.phrases), via a logistic
regression exported from scripts/build_phrase_component.py. No onnxruntime, no
sklearn at inference -- just a matrix multiply, so it is free to run in the
Space's CPU budget.

Sidecar: <ensemble_name>.phrase.json
    classes    list[str]          index == column of logreg_W
    logreg_W   (C, V) float32     over the fixed tfidf n-gram vocabulary
    logreg_b   (C,)   float32
    idf        (V,)   float32     fit on the training corpus
    min_hold   int                melodic-skeleton stability threshold
"""

import json
from pathlib import Path

import numpy as np

from raagafinder.features.phrases import V, recording_bow, tfidf_vector
from raagafinder.features.pitch_utils import fold_octave, hz_to_cents, voiced_mask


class PhraseComponent:
    def __init__(self, meta_path: Path):
        m = json.loads(Path(meta_path).read_text(encoding="utf-8"))
        self.classes: list[str] = m["classes"]
        self.W = np.asarray(m["logreg_W"], dtype=np.float64)   # (C, V)
        self.b = np.asarray(m["logreg_b"], dtype=np.float64)   # (C,)
        self.idf = np.asarray(m["idf"], dtype=np.float64)      # (V,)
        self.min_hold = int(m.get("min_hold", 3))
        # recording-level blend params (fit on fold-0 by fit_v4_blend.py);
        # blend_w = 0 => the component is a no-op until fit, so the sidecar is
        # safe to ship before its weight is calibrated.
        self.blend_w: float = float(m.get("blend_w", 0.0))
        self.blend_temp: float = float(m.get("blend_temp", 1.0))
        assert self.W.shape[1] == V and len(self.idf) == V, "phrase vocab mismatch"

    def _probs_from_bow(self, counts):
        z = tfidf_vector(counts, self.idf)
        logits = self.W @ z + self.b
        logits -= logits.max()
        e = np.exp(logits)
        return e / e.sum()

    def probs(self, f0_hz, hop_s, tonic_hz):
        """Class distribution for one recording (single window/segment).
        None if no usable phrase content."""
        mask = voiced_mask(f0_hz)
        folded = np.mod(fold_octave(hz_to_cents(f0_hz, tonic_hz)), 1200.0)
        counts = recording_bow([(folded, mask, hop_s)], self.min_hold)
        return None if counts is None else self._probs_from_bow(counts)

    def probs_multi(self, segments):
        """Pooled distribution over several (f0_hz, hop_s, tonic_hz) segments
        of one recording -- the app path. None if nothing usable."""
        folded_segs = []
        for f0_hz, hop_s, tonic_hz in segments:
            mask = voiced_mask(f0_hz)
            folded = np.mod(fold_octave(hz_to_cents(f0_hz, tonic_hz)), 1200.0)
            folded_segs.append((folded, mask, hop_s))
        counts = recording_bow(folded_segs, self.min_hold)
        return None if counts is None else self._probs_from_bow(counts)


def load_phrase_if_present(artifact_dir: Path,
                           ensemble_name: str | None = None):
    """Load the phrase component paired with an ensemble artifact by name
    (<name>.phrase.json). None when absent."""
    if not ensemble_name:
        return None
    meta = Path(artifact_dir) / f"{ensemble_name}.phrase.json"
    if meta.exists():
        return PhraseComponent(meta)
    return None
