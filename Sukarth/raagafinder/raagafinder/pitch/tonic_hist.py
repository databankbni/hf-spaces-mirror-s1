"""Pure-numpy tonic estimation from a melody f0 track (fallback / cross-check).

Simplified Salamon/Gulati-style pitch-histogram method: smoothed log-f0
histogram, peak picking restricted to the plausible lead-voice tonic range.
Octave and fifth errors downstream are absorbed by octave folding and the
rotation-hypothesis mechanism, so returning a top-peak candidate list is
sufficient here.
"""

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks

from raagafinder.features.pitch_utils import voiced_mask

REF_HZ = 55.0
BIN_CENTS = 10.0
SMOOTH_SIGMA_BINS = 2.5  # ~25 cents
TONIC_MIN_HZ = 100.0
TONIC_MAX_HZ = 375.0  # TonicIndianArtMusic default range


def tonic_candidates(f0_hz: np.ndarray, top_k: int = 3) -> list[float]:
    """Return up to top_k tonic candidates in Hz, best first."""
    f0 = np.asarray(f0_hz, dtype=np.float64)
    f0 = f0[voiced_mask(f0)]
    if f0.size == 0:
        return []
    cents = 1200.0 * np.log2(f0 / REF_HZ)
    n_bins = int(np.ceil(cents.max() / BIN_CENTS)) + 1
    idx = np.clip(np.floor(cents / BIN_CENTS).astype(int), 0, n_bins - 1)
    hist = np.bincount(idx, minlength=n_bins).astype(np.float64)
    hist = gaussian_filter1d(hist, sigma=SMOOTH_SIGMA_BINS)

    lo = int(1200.0 * np.log2(TONIC_MIN_HZ / REF_HZ) / BIN_CENTS)
    hi = int(1200.0 * np.log2(TONIC_MAX_HZ / REF_HZ) / BIN_CENTS)
    peaks, props = find_peaks(hist, prominence=hist.max() * 0.05)
    in_range = [(p, hist[p]) for p in peaks if lo <= p <= hi]
    in_range.sort(key=lambda t: -t[1])
    return [float(REF_HZ * 2 ** (p * BIN_CENTS / 1200.0)) for p, _ in in_range[:top_k]]


# A correct tonic puts at least this much melodic mass within +-40c of Sa.
# Training corpus (480 recordings, true tonics): p1 = 0.091, min = 0.016
# (single outlier); a catastrophically wrong tonic measured 0.02 in testing.
SA_VETO_MASS = 0.05


def _sa_pa_mass(folded: np.ndarray) -> float:
    """Melodic evidence that a folding tonic is the real Sa: mass near Sa plus
    a weaker Pa term (the drone sounds Sa and Pa). Pa is downweighted because
    some ragas omit it entirely (Śrīranjani, Hindōḷaṁ). NOTE: this is NOT
    reliable enough to rank plausible candidates (M/P-dominant ragas beat Sa
    ~20-30% of the time on the training corpus) — use only to rescue tonics
    that already failed the SA_VETO_MASS sanity bar."""
    near_sa = ((folded <= 40.0) | (folded >= 1160.0)).mean()
    near_pa = (np.abs(folded - 700.0) <= 40.0).mean()
    return float(near_sa + 0.4 * near_pa)


def choose_tonic(
    views: list[tuple[np.ndarray, float]],
    detector_tonics: list[float],
    merge_cents: float = 40.0,
) -> tuple[float, float, bool]:
    """Pick ONE tonic for a recording (a performance has a single shruti).

    views: [(f0_hz, weight), ...] — one melody pitch track per analyzed
    section, weight = voiced seconds. detector_tonics: the per-view estimates
    from a drone-aware detector (TonicIndianArtMusic).

    Strategy (asymmetric evidence bar):
    1. CONSENSUS — cluster detector estimates as pitch classes (octave folded;
       features fold anyway) and take the heaviest cluster. Per-section tonic
       errors are usually isolated, so majority voting fixes them.
    2. VETO RESCUE — melodic mass near Sa under the consensus tonic must clear
       SA_VETO_MASS; real recordings virtually never fail this. If it fails,
       the detector is catastrophically wrong even by consensus: re-score all
       candidates (detector estimates + per-view histogram peaks) by
       Sa+0.4·Pa mass and take the best.

    Returns (tonic_hz, sa_mass, vetoed). tonic_hz is in the octave register
    of the first detector estimate.
    """
    from raagafinder.features.pitch_utils import fold_octave, hz_to_cents

    dets = [t for t in detector_tonics if t and t > 0]
    if not dets:
        return 0.0, 0.0, False
    ref = dets[0]
    weights = [w for _, w in views] if len(views) == len(dets) else [1.0] * len(dets)

    def fold_to_class(hz: float) -> float:
        return (1200.0 * np.log2(hz / ref)) % 1200.0

    def class_dist(a: float, b: float) -> float:
        d = abs(a - b) % 1200.0
        return min(d, 1200.0 - d)

    # 1. weighted majority cluster of detector pitch classes
    clusters: list[list[int]] = []
    det_classes = [fold_to_class(t) for t in dets]
    for i, d in enumerate(det_classes):
        for cl in clusters:
            if class_dist(d, det_classes[cl[0]]) <= merge_cents:
                cl.append(i)
                break
        else:
            clusters.append([i])
    best_cl = max(clusters, key=lambda cl: sum(weights[i] for i in cl))
    seed = det_classes[best_cl[0]]
    offs = [seed + (det_classes[i] - seed + 600.0) % 1200.0 - 600.0 for i in best_cl]
    cl_w = [weights[i] for i in best_cl]
    if sum(cl_w) <= 0:  # e.g. sections with no voiced frames
        cl_w = None
    consensus_class = float(np.average(offs, weights=cl_w)) % 1200.0

    folded_views = []
    for f0, w in views:
        f0 = np.asarray(f0, dtype=np.float64)
        v = f0[voiced_mask(f0)]
        if v.size:
            folded_views.append((fold_octave(hz_to_cents(v, ref)), w))

    def to_hz(cls: float) -> float:
        hz = ref * 2 ** (cls / 1200.0)
        while hz > ref * 1.4142:  # keep register near the detector estimate
            hz /= 2.0
        return float(hz)

    def sa_mass(cls: float) -> float:
        if not folded_views:
            return 1.0  # nothing to judge with — trust the detector
        tot = sum(w for _, w in folded_views)
        m = sum(
            w * (((np.mod(fv - cls, 1200.0) <= 40.0)
                  | (np.mod(fv - cls, 1200.0) >= 1160.0)).mean())
            for fv, w in folded_views
        )
        return float(m / max(1e-9, tot))

    mass = sa_mass(consensus_class)
    if mass >= SA_VETO_MASS:
        return to_hz(consensus_class), mass, False

    # 2. veto rescue: detector consensus is implausible as Sa
    cand_classes = list(det_classes)
    for f0, _w in views:
        cand_classes.extend(fold_to_class(c) for c in tonic_candidates(f0, top_k=3))
    deduped: list[float] = []
    for d in cand_classes:
        if not any(class_dist(d, e) <= merge_cents for e in deduped):
            deduped.append(d)
    tot = max(1e-9, sum(w for _, w in folded_views))
    best_d, best_score = consensus_class, -1.0
    for d in deduped:
        score = sum(
            w * _sa_pa_mass(np.mod(fv - d, 1200.0)) for fv, w in folded_views
        ) / tot
        if score > best_score:
            best_d, best_score = d, score
    return to_hz(best_d), sa_mass(best_d), True


def tonic_peak_prominence(f0_hz: np.ndarray, tonic_hz: float) -> float:
    """Quality signal: mass of the folded pitch histogram within +-35 cents of
    the claimed tonic pitch class. Used by inference quality gates."""
    from raagafinder.features.pitch_utils import fold_octave, hz_to_cents

    cents = hz_to_cents(f0_hz, tonic_hz)
    folded = fold_octave(cents[~np.isnan(cents)])
    if folded.size == 0:
        return 0.0
    near = (folded <= 35.0) | (folded >= 1165.0)
    return float(near.mean())
