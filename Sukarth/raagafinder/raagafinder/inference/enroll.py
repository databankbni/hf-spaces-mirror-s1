"""Adding a raga without retraining: prototypes, whitening, abstention.

A class prototype is the mean pooled embedding of a class's recordings,
and the shipped sequence stage already mixes one per trained class into
its answer. The same construction works for a class the encoder was
never trained on: average a handful of recordings, and compare a query
against that mean by cosine. Nothing is retrained and nothing is stored
on disk, which is what makes it usable from inside a session.

Three measured facts shape everything below, and each is quoted where it
is used rather than summarised here.

The metric matters more than the prototype. Cosine in the raw embedding
space treats every direction as equally informative; whitening by the
average within-class scatter discounts the directions along which
recordings of one raga naturally spread. On thirty classes withheld from
every fold's training set, enrolled from five recordings and competing
against all 154 at full strength, that correction moves accuracy from
0.763 to 0.800 (scripts/enroll_abstain_whitened.py, ten folds; the trained
classes score 0.821 and 0.849 under the same two metrics, so the gap an
added raga carries is about five points either way). The
transform is estimated only from classes the encoder trained on and
still improves classes it has never seen, so what it suppresses is a
property of the embedding space rather than of any class list.

Whitening is used HERE ONLY. The 154 trained classes keep the plain
cosine their blend weight and temperature were fitted against; changing
the metric under them would move numbers the app quotes, for a gain
measured at +0.31 points with Wilcoxon p = 0.65 at the shipped mixing
weight (scripts/proto_metric.py). Enrolled scoring is the whitener's
only consumer.

A cosine is not a probability, which is why enrollment did not ship
earlier: every other answer this app gives passes an abstention gate,
and an enrolled raga arrived with no way to say "not sure". The softmax
over cosines at the prototype temperature is that missing signal, and it
is the honest one of the three candidates measured -- it abstains far
more on enrolled ragas than on trained ones and is then almost equally
right on both (scripts/enroll_abstain.py).
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

# The shipped prototype temperature. Not a free parameter here: the gate
# threshold below was fitted at this value, and the two only mean
# anything together.
ENROLL_TAU = 0.05

# Windows per recording when embedding. The serving path averages eight
# (raagafinder/models/onnx_lstm.py), which was chosen as a latency trade
# for classification. Twelve is what every prototype the corpus carries
# was built from, so an enrolled prototype and a trained one have to be
# built the same way or they are not comparable quantities.
ENROLL_WINDOWS = 12

# A window with less than this fraction of voiced frames carries too
# little melody to say anything, and averaging it into a prototype
# pulls the mean toward whatever the padding token means.
MIN_VOICED_FRACTION = 0.25

# Shrinkage on the within-class covariance. 768 dimensions estimated
# from 1275 recordings is not enough for a stable inverse, and the
# unregularised one is measurably worse than doing nothing: prototype
# accuracy out of fold is 0.804 at shrinkage 0, against 0.838 for plain
# cosine and 0.870 at 0.5 (scripts/proto_metric.py, extended past its
# own grid). The curve is single-peaked with an interior maximum at 0.5
# and returns to exactly the cosine value as the transform approaches
# the identity, which is the algebraic check that the construction is
# right.
WCCN_SHRINKAGE = 0.5

# The abstention threshold, on the softmax over cosines at ENROLL_TAU.
# Fitted by scripts/enroll_abstain.py as the largest coverage whose
# accuracy still reaches 90% overall, on 1275 queries against thirty
# withheld classes. At this value the gate keeps 67.7% of answers whose
# true raga was enrolled and is right on 89.4% of those, against 80.6%
# kept and 90.3% right for trained classes -- it answers less often
# where it knows less, so that "confident" carries one meaning across
# both groups.
#
# That fit was measured on the UNWHITENED cosine, before the metric
# correction above existed, and the threshold is carried over unchanged
# rather than refitted -- fitting a second constant for enrolled classes
# is a decision to take deliberately, not a quiet edit. What the
# carry-over does was therefore measured rather than assumed
# (scripts/enroll_abstain_whitened.py, the same 1275 queries with only
# the metric changed): it lets through 69.6% of enrolled answers at
# 92.0% accuracy, and 74.0% of all answers at 94.3%. The fit chose this
# threshold as the largest coverage still reaching 90% overall, so the
# carried-over rule under-promises on the whitened metric rather than
# over-promising -- it answers slightly less often than before and is
# four points more accurate when it does.
ABSTAIN_MIN_SOFTMAX = 0.4161

# Enrollment is capped at both ends. Below three recordings the mean is
# one atypical performance away from being wrong, and the measured curve
# has not been run below three. Above five the app would be asking for a
# collection effort it cannot promise a return on: eight well-chosen
# recordings score 0.803 against five well-chosen ones at 0.788
# (scripts/enroll_selection.py), a point and a half for a 60% larger
# upload.
MIN_ENROLL_RECORDINGS = 3
MAX_ENROLL_RECORDINGS = 5


def unit(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v, axis=-1, keepdims=True) + 1e-9)


def softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max(axis=-1, keepdims=True))
    return e / e.sum(axis=-1, keepdims=True)


@dataclass
class EnrolledRaga:
    """One raga a user added, held for the length of their session."""

    name: str
    prototype: np.ndarray  # unit-norm, UNWHITENED, 768
    n_recordings: int


@dataclass
class EnrollmentAnswer:
    """What the enrolled prototypes say about one query.

    ``winner`` is the closest class over trained and enrolled prototypes
    together, because an enrolled raga has to beat the field rather than
    only its enrolled neighbours -- that is the comparison
    scripts/enroll_abstain.py gated, and gating a narrower one would
    quote its numbers for a different question.
    """

    winner: str
    is_enrolled: bool
    score: float
    kept: bool
    n_enrolled: int


def embed_windows(session, tokens: np.ndarray, seq_len: int,
                  n_windows: int = ENROLL_WINDOWS) -> np.ndarray | None:
    """One unit-norm recording embedding from a token sequence.

    The mean is taken over RAW window vectors and normalised once at the
    end, which is how every prototype in models_artifacts was built
    (scripts/build_prototypes.py). Normalising each window first would
    give a short window the same weight as a long one in a different
    space, and the prototypes would no longer be means of the same
    quantity the query is.

    None when nothing usable came out, which the callers treat as a
    recording that cannot be enrolled rather than as an error.
    """
    starts = np.unique(np.linspace(0, max(0, len(tokens) - seq_len),
                                   n_windows, dtype=int))
    wins = []
    for s in starts:
        x = tokens[s:s + seq_len]
        if len(x) < seq_len:
            x = np.pad(x, (0, seq_len - len(x)))
        if np.mean(x > 0) >= MIN_VOICED_FRACTION:
            wins.append(x)
    if not wins:
        return None
    feed = {"tokens": np.stack(wins).astype(np.int64)}
    emb = session.run(["embedding"], feed)[0]
    return unit(emb.astype(np.float64).mean(0))


def exposes_embedding(lstm) -> bool:
    """Whether this graph can be asked for its pooled context vector.

    A sequence model exported before scripts/add_embedding_output.py ran
    carries only logits, and every enrollment path has to degrade to
    "unavailable" rather than raise on it.
    """
    if lstm is None:
        return False
    return "embedding" in {o.name for o in lstm.sess.get_outputs()}


def recording_embedding(lstm, f0_hz, hop_s, tonic_hz) -> np.ndarray | None:
    """Embed a recording through the sequence model's own tokeniser.

    Routed through ``lstm.tokens`` rather than a local copy so that the
    resampling onto the training hop, the octave folding and the bin
    width are whatever the loaded sidecar says. An enrolled prototype
    built under a different tokenisation than the trained prototypes it
    competes against would be off by a time-warp with nothing to catch
    it.
    """
    if not exposes_embedding(lstm):
        return None
    tokens = lstm.tokens(np.asarray(f0_hz), float(hop_s), float(tonic_hz))
    if len(tokens) < lstm.seq_len // 2:
        return None
    return embed_windows(lstm.sess, tokens, lstm.seq_len)


def embed_sections(lstm, backend, wav_paths) -> np.ndarray | None:
    """One recording embedding from a recording's decoded sections.

    A long upload arrives as several independently decoded sections, and
    they are averaged into a single vector because a prototype is a mean
    over a RECORDING: letting one four-minute upload contribute four
    rows would weight it four times against a three-minute one.

    The tonic is chosen once across all sections, for the reason
    analyze_segments gives -- a recording has one shruti, and a section
    that detects a fourth off normalises its whole melody to the wrong
    Sa. An enrolled prototype built from a mixture of shrutis is worse
    than useless, because it is stable enough to keep being returned.
    """
    from raagafinder.features.pitch_utils import voiced_mask
    from raagafinder.pitch.tonic_hist import choose_tonic

    views, detected = [], []
    for p in wav_paths:
        f0, hop = backend.extract_pitch(p)
        views.append((np.asarray(f0), float(hop)))
        detected.append(backend.extract_tonic(p))
    if not views:
        return None
    tonic, _mass, _vetoed = choose_tonic(
        [(f0, float(voiced_mask(f0).sum() * hop)) for f0, hop in views],
        detected)
    if tonic <= 0:
        tonic = float(detected[0])
    if tonic <= 0:
        return None
    return build_prototype(
        [recording_embedding(lstm, f0, hop, tonic) for f0, hop in views])


def build_prototype(embeddings) -> np.ndarray | None:
    """The mean of a raga's recording embeddings, renormalised."""
    rows = [e for e in embeddings if e is not None]
    if not rows:
        return None
    return unit(np.mean(np.stack(rows).astype(np.float64), axis=0))


def within_class_covariance(X: np.ndarray, y: np.ndarray,
                            shrink: float) -> np.ndarray:
    """Average scatter INSIDE classes, shrunk toward a scaled identity.

    Singleton classes contribute nothing: a class with one recording has
    no within-class spread to measure, and counting its zero rows would
    bias the estimate toward zero variance in every direction.
    """
    d = X.shape[1]
    S = np.zeros((d, d))
    n = 0
    for c in np.unique(y):
        V = X[y == c]
        if len(V) < 2:
            continue
        C = V - V.mean(0)
        S += C.T @ C
        n += len(V) - 1
    S /= max(n, 1)
    return (1 - shrink) * S + shrink * np.trace(S) / d * np.eye(d)


def fit_whitener(X: np.ndarray, y: np.ndarray,
                 shrink: float = WCCN_SHRINKAGE) -> np.ndarray:
    """The symmetric WCCN transform for an embedding matrix.

    Symmetric rather than Cholesky because the two differ by a rotation,
    which cosine does not see, and the symmetric form is the one the
    measurement used.
    """
    S = within_class_covariance(np.asarray(X, dtype=np.float64),
                                np.asarray(y), shrink)
    w, V = np.linalg.eigh(S)
    return V @ np.diag(1.0 / np.sqrt(np.maximum(w, 1e-8))) @ V.T


def whitener_path(artifacts_dir: Path, model_name: str) -> Path:
    return Path(artifacts_dir) / f"{model_name}.whitener.npy"


def load_whitener(artifacts_dir: Path, model_name: str) -> np.ndarray | None:
    """The whitener for a model, or None when it was never built.

    Shape is checked rather than trusted, for the same reason the
    prototype loader checks its own: a transform of the wrong width
    would silently score every enrolled raga in a space that has nothing
    to do with the embeddings.
    """
    p = whitener_path(artifacts_dir, model_name)
    if not p.exists():
        return None
    W = np.load(p).astype(np.float64)
    if W.ndim != 2 or W.shape[0] != W.shape[1]:
        return None
    return W


def score_query(query: np.ndarray, trained_protos: np.ndarray,
                trained_classes, enrolled, whitener=None,
                tau: float = ENROLL_TAU,
                threshold: float = ABSTAIN_MIN_SOFTMAX
                ) -> EnrollmentAnswer | None:
    """Compare one recording against trained and enrolled prototypes.

    Both sides are transformed by the same whitener and renormalised, so
    the comparison stays a cosine in the corrected space. The gate is
    the exact rule scripts/enroll_abstain.py fitted: softmax over the
    similarities at ``tau``, read at the winning class, kept when it
    reaches ``threshold``.

    None when there is nothing enrolled, so the caller can skip the
    whole branch without special-casing an empty answer.
    """
    if not enrolled:
        return None
    M = np.vstack([np.asarray(trained_protos, dtype=np.float64)]
                  + [e.prototype[None, :] for e in enrolled])
    q = np.asarray(query, dtype=np.float64)
    if whitener is not None:
        M, q = M @ whitener, q @ whitener
    sims = unit(M) @ unit(q)
    soft = softmax(sims / tau)
    top = int(sims.argmax())
    names = list(trained_classes) + [e.name for e in enrolled]
    return EnrollmentAnswer(
        winner=names[top],
        is_enrolled=top >= len(trained_classes),
        score=float(soft[top]),
        kept=bool(soft[top] >= threshold),
        n_enrolled=len(enrolled),
    )
