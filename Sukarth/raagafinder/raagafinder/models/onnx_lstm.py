"""v3 LSTM component: ONNX inference over tokenized pitch sequences.

Mirrors notebooks/kaggle_v3.ipynb exactly: tonic-normalized, octave-folded
cents -> 5-cent pitch-class tokens (0 = unvoiced) on the training corpus's
4.44 ms hop. Inference pitch (Melodia at 2.9 ms in this repo, see
essentia_backend.HOP_SIZE) is nearest-neighbour resampled onto that grid —
skipping this would time-warp every sequence ~1.53x and silently degrade
the model.
"""

import json
from pathlib import Path

import numpy as np

from raagafinder.features.pitch_utils import hz_to_cents, voiced_mask


# An ensemble and its sequence model are trained on the same corpus but not
# always on the same class list: each applies its own minimum-recordings quota,
# so a raga can clear the bar for one and not the other. Below this much
# overlap they are not a deliberate pair (a stale or mismatched checkpoint),
# and blending them would be worse than not blending at all.
MIN_CLASS_OVERLAP = 0.8

# How many windows of a section the sequence model scores before averaging.
#
# Cost is linear in this and accuracy is not. Measured over 329 recordings,
# every third one of the corpus, comparing the shipped model against itself:
#
#     windows   top-1    top-3
#          12   0.8267   0.9301
#           8   0.8359   0.9271
#           6   0.8267   0.9179
#           4   0.7872   0.9119
#
# Flat down to six and falling from four. Eight is a third cheaper than the
# twelve this used to be, with top-1 and top-3 both inside a recording or two
# of it, and it keeps a margin above the point where the curve turns. Six
# would halve the cost but gives up a point of top-3, which the app shows.
#
# Most of those recordings were in the model's training set, which makes the
# absolute numbers optimistic and does NOT undermine the comparison: the
# question is how much the later windows add, and the model is being asked
# about itself at both settings. The one fold it never trained on agrees on
# the shape -- 0.818 at twelve, 0.808 at eight, 0.828 at six, 0.737 at four.
#
# One inconsistency this leaves, stated rather than hidden: the out-of-fold
# matrices the blend weight and the temperature were fitted on were produced
# at twelve windows, so the calibration is very slightly tuned for a
# distribution the app no longer produces. Averaging eight samples instead of
# twelve leaves a marginally less smooth distribution, which a temperature
# absorbs almost entirely. It resolves itself at the next full refit and does
# not justify one on its own.
DEFAULT_WINDOWS = 8


class ClassAlignment:
    """Union class space for two models with overlapping-but-unequal classes.

    Slots 0..len(ens) are the ensemble's own classes in its own order, so an
    ensemble probability vector needs only zero-padding; LSTM-only classes are
    appended after. ``both`` marks the slots BOTH models can express, which is
    the only place a weighted average is meaningful -- see combine().
    """

    def __init__(self, ens_classes, lstm_classes):
        self.classes = list(ens_classes) + [
            c for c in lstm_classes if c not in set(ens_classes)]
        slot = {c: i for i, c in enumerate(self.classes)}
        self.scatter = np.array([slot[c] for c in lstm_classes], dtype=int)
        self.both = np.zeros(len(self.classes), bool)
        self.both[:len(ens_classes)] = True
        lstm_can = np.zeros(len(self.classes), bool)
        lstm_can[self.scatter] = True
        self.both &= lstm_can


def align_classes(ens_classes, lstm_classes) -> ClassAlignment | None:
    """None when the two class lists are too different to be a real pairing."""
    ens = list(ens_classes)
    shared = len(set(ens) & set(lstm_classes))
    if not ens or shared / len(ens) < MIN_CLASS_OVERLAP:
        return None
    return ClassAlignment(ens, lstm_classes)


class LstmComponent:
    def __init__(self, onnx_path: Path, meta_path: Path):
        import onnxruntime as ort

        self.sess = ort.InferenceSession(
            str(onnx_path), providers=["CPUExecutionProvider"]
        )
        m = json.loads(Path(meta_path).read_text(encoding="utf-8"))
        # kept whole so provenance fields (trained_on, from_fold_checkpoint,
        # fold_val_top1) stay reachable; scripts/fit_v3_blend.py uses them to
        # refuse a dataset the checkpoint was not trained against
        self.meta: dict = m
        self.classes: list[str] = m["classes"]
        self.seq_len: int = m["seq_len"]
        self.hop_s: float = m["hop_s"]
        self.bin_cents: int = m["bin_cents"]
        self.n_bins = 1200 // self.bin_cents
        # blend params fit out-of-fold over all ten folds (fit_v3_blend.py)
        self.blend_w: float = float(m.get("blend_w_v2", 0.5))
        self.blend_temp: float = float(m.get("blend_temperature", 1.0))
        # single-section recordings blend only when the LSTM's windows agree
        # (scripts/fit_shortclip_blend.py; the within-model analog of
        # section corroboration)
        self.short_agree_min: float = float(m.get("short_agree_min", 0.6))
        # Post-hoc correction for the corpus's long tail: divide by the
        # training frequency raised to tail_tau (scripts/fit_logit_adjust.py).
        # Zero when absent, so a sidecar written before this existed keeps
        # behaving exactly as it did.
        self.tail_tau: float = float(m.get("tail_tau", 0.0))
        self.class_counts: dict = m.get("class_counts", {})
        self._prior: np.ndarray | None = None
        # Class prototypes: the mean pooled embedding of each class's
        # recordings, mixed into this stage's output before the ensemble
        # blend. The head and the prototypes fail on different
        # recordings, so mixing recovers disagreement rather than
        # averaging two correlated opinions; measured out-of-fold at
        # +2.5 points end to end, at a temperature and weight chosen on
        # a different model's surface. Absent from older sidecars, in
        # which case this stage behaves exactly as it did before.
        self.proto: np.ndarray | None = None
        self.proto_tau: float = float(m.get("prototype_tau", 0.05))
        self.proto_w: float = float(m.get("prototype_w", 0.0))
        pf = Path(meta_path).with_suffix("").with_suffix(".protos.npy")
        if self.proto_w > 0 and pf.exists():
            p = np.load(pf).astype(np.float32)
            if p.shape == (len(self.classes), 768):
                self.proto = p
        self._emb_name: str | None = None
        # set by pipeline._lstm_component once the ensemble is known
        self.align: ClassAlignment | None = None

    def tail_prior(self) -> np.ndarray:
        """Training frequency of each union class, in alignment order.

        Built here rather than stored as a vector because the union order is
        decided at load time by align_classes and the sidecar cannot know it.
        A class the sidecar has no count for is floored at one recording,
        which places it at the rare end instead of dividing by zero.
        """
        if self._prior is None:
            c = np.array([max(int(self.class_counts.get(k, 1)), 1)
                          for k in self.align.classes], dtype=np.float64)
            self._prior = c / c.sum()
        return self._prior

    def mix(self, ens_probs: np.ndarray, lstm_probs: np.ndarray, w=None):
        """The union-space blend, before calibration.

        Classes only ONE model carries keep that model's full mass rather than
        being scaled by the blend weight. Down-weighting them instead would
        penalise a raga purely for which model's quota it happened to clear:
        an ensemble-only class could never exceed the fitted w while a shared
        class reaches 1.0, so at any moderate w it could essentially never
        win.

        Separate from combine() so scripts/fit_v3_blend.py can sweep w through
        the exact arithmetic that ships. Fitting a weight under one set of
        alignment semantics and serving it under another is how the positional
        -alignment bug went unnoticed for a release.
        """
        a = self.align
        w = self.blend_w if w is None else w
        e = np.zeros(len(a.classes))
        e[:len(ens_probs)] = ens_probs
        p = np.zeros(len(a.classes))
        p[a.scatter] = lstm_probs
        blend = np.where(a.both, w * e + (1.0 - w) * p, e + p)
        # The tail correction goes here, inside the function the weight is
        # fitted through, so that the temperature and the uncertain thresholds
        # are fitted against the distribution that actually ships. Applying it
        # further downstream would leave both calibrated for a blend the app
        # no longer produces.
        if self.tail_tau:
            blend = blend / self.tail_prior() ** self.tail_tau
        return blend / blend.sum()

    def combine(self, ens_probs: np.ndarray, lstm_probs: np.ndarray):
        """mix(), calibrated — what inference actually returns."""
        from raagafinder.models.calibrate import apply_temperature

        return apply_temperature(self.mix(ens_probs, lstm_probs),
                                 self.blend_temp)

    def tokens(self, f0_hz: np.ndarray, hop_s: float, tonic_hz: float) -> np.ndarray:
        mask = voiced_mask(f0_hz)
        cents = np.zeros(len(f0_hz))
        cents[mask] = hz_to_cents(f0_hz[mask], tonic_hz)
        tok = np.zeros(len(f0_hz), dtype=np.int64)
        folded = np.mod(cents[mask], 1200.0)
        tok[mask] = (np.floor(folded / self.bin_cents).astype(np.int64)
                     % self.n_bins) + 1
        if abs(hop_s - self.hop_s) / self.hop_s > 0.05:
            idx = np.clip(
                (np.arange(int(len(tok) * hop_s / self.hop_s))
                 * self.hop_s / hop_s).astype(int), 0, len(tok) - 1,
            )
            tok = tok[idx]
        return tok

    def probs(self, f0_hz: np.ndarray, hop_s: float, tonic_hz: float,
              max_windows: int = DEFAULT_WINDOWS,
              return_agreement: bool = False):
        """Mean softmax over evenly spaced SEQ_LEN windows with enough voiced
        content. None if nothing usable (too short / mostly unvoiced).
        With return_agreement, returns (probs, fraction of windows whose
        top-1 matches the aggregate top-1)."""
        tok = self.tokens(f0_hz, hop_s, tonic_hz)
        if len(tok) < self.seq_len // 2:
            return None
        starts = np.unique(np.linspace(
            0, max(0, len(tok) - self.seq_len),
            min(max_windows, max(1, len(tok) // self.seq_len * 2)), dtype=int,
        ))
        wins = []
        for s in starts:
            x = tok[s:s + self.seq_len]
            if len(x) < self.seq_len:
                x = np.pad(x, (0, self.seq_len - len(x)))
            if np.mean(x > 0) >= 0.25:
                wins.append(x)
        if not wins:
            return None
        feed = {"tokens": np.stack(wins).astype(np.int64)}
        if self.proto is None:
            logits = self.sess.run(["logits"], feed)[0]
            emb = None
        else:
            # the pooled context vector is an internal node, so ask for it
            # by name once and remember whether this graph exposes it; a
            # model exported before prototypes existed simply will not,
            # and the stage falls back to the head alone
            if self._emb_name is None:
                names = {o.name for o in self.sess.get_outputs()}
                self._emb_name = ("embedding" if "embedding" in names
                                  else "")
            if self._emb_name:
                logits, emb = self.sess.run(["logits", self._emb_name], feed)
            else:
                logits, emb = self.sess.run(["logits"], feed)[0], None
        e = np.exp(logits - logits.max(axis=1, keepdims=True))
        pw = e / e.sum(axis=1, keepdims=True)
        if emb is not None:
            v = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9)
            s = (v @ self.proto.T) / self.proto_tau
            s -= s.max(axis=1, keepdims=True)
            ps = np.exp(s)
            ps /= ps.sum(axis=1, keepdims=True)
            pw = (1.0 - self.proto_w) * pw + self.proto_w * ps
        p = pw.mean(axis=0)
        if return_agreement:
            agree = float(np.mean(pw.argmax(axis=1) == int(p.argmax())))
            return p, agree
        return p


def load_if_present(artifact_dir: Path,
                    ensemble_name: str | None = None) -> LstmComponent | None:
    """Load the LSTM paired with an ensemble artifact.

    Each ensemble carries its own sequence model so the shipped models stay
    independent: ``model_v2_3.onnx`` (71 classes), ``model_v2_4.onnx``
    (90 classes) and ``model_v2_7.onnx`` (104 classes) each pair with the
    ensemble of the same name. The paired sidecar is ``<name>.lstm.json``.
    The legacy ``model_v3.onnx`` name is still honored as a fallback so older
    single-model deployments keep working.
    """
    candidates = []
    if ensemble_name:
        candidates.append((artifact_dir / f"{ensemble_name}.onnx",
                           artifact_dir / f"{ensemble_name}.lstm.json"))
    candidates.append((artifact_dir / "model_v3.onnx",
                       artifact_dir / "model_v3_classes.json"))
    for onnx, meta in candidates:
        if onnx.exists() and meta.exists():
            return LstmComponent(onnx, meta)
    return None
