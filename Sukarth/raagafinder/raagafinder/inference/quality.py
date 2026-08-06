"""Inference quality gates: route degraded inputs to honest error states
instead of confident misclassification."""

from dataclasses import dataclass, field

import numpy as np

from raagafinder.config import MIN_VOICED_RATIO, MIN_VOICED_S
from raagafinder.features.pitch_utils import voiced_mask

# Fraction of folded pitch mass within +-35 cents of the claimed tonic pitch
# class. Deliberately conservative: tighten only with evidence from grouped CV.
MIN_TONIC_PROMINENCE = 0.02

# Normalized entropy of the PCD (0 = single spike, 1 = uniform). Measured
# rather than chosen: the 480 CMD recordings span 0.870-0.983 (median 0.941)
# and white-noise tracking measures 0.997, so only near-uniform is
# rejectable. A threshold anywhere near the intuitive 0.85 rejects virtually
# all real music, which is why this sits where it does.
MAX_PCD_NORM_ENTROPY = 0.985

# How accurate the system actually is as a function of how much melody it got.
# Measured on the grouped 10-fold OOF of model_v2_4 (855 recordings) by
# scripts/eval_stratified.py, 2026-07-25, with the CMD recordings EXCLUDED --
# they are long concert pieces and also the easiest source, so including them
# would let the source effect masquerade as a length effect. The trend is
# monotone in the deconfounded numbers too, so length is doing real work:
#
#     voiced audio    n    top-1    top-3
#     under 60 s      9    0.11     0.33
#     60-180 s       91    0.64     0.77
#     180-420 s     190    0.69     0.84
#     420 s and up   85    0.79     0.89
#
# MIN_VOICED_S is 20 s, so without this the app answers with the same
# confidence UI on a 25-second clip it gets right one time in ten. The gate
# stays permissive (top-3 is not zero, and a short clip is still worth a
# guess) but the user is told the real number.
#
# These are the FALLBACK, used only for an artifact that predates
# `by_voiced_s_noncmd`. Prefer `bands_from_artifact`: the numbers below belong
# to one particular model, and the app offers a menu of models. Quoting v2_4's
# accuracy while serving v2_7 is the same failure the About tab already avoids
# by reading its slices out of the artifact.
RELIABILITY_BANDS = (
    (60.0, 0.11, 9, "under a minute"),
    (180.0, 0.64, 91, "1-3 minutes"),
    (420.0, 0.69, 190, "3-7 minutes"),
    (float("inf"), 0.79, 85, "over 7 minutes"),
)

# eval_stratified.py's bucket labels, in order, mapped to the band ceiling in
# seconds and the words shown to a user.
_SLICE_TO_BAND = (
    ("<60s", 60.0, "under a minute"),
    ("60-180s", 180.0, "1-3 minutes"),
    ("180-420s", 420.0, "3-7 minutes"),
    ("420s+", float("inf"), "over 7 minutes"),
)


def bands_from_artifact(artifact: dict | None) -> tuple:
    """Reliability bands for the model actually loaded, or the fallback.

    Reads `stratified.by_voiced_s_noncmd`, which is the CMD-excluded slice.
    The all-sources `by_voiced_s` is deliberately NOT accepted as a substitute:
    CMD is both the longest and the easiest source, so it inflates every band
    and most of all the long ones, and a user upload is not a CMD concert
    recording. A partial slice falls back rather than mixing two models'
    numbers into one table.
    """
    rows = ((artifact or {}).get("stratified") or {}).get("by_voiced_s_noncmd")
    if not rows:
        return RELIABILITY_BANDS
    by_slice = {r["slice"]: r for r in rows}
    if any(name not in by_slice for name, _limit, _words in _SLICE_TO_BAND):
        return RELIABILITY_BANDS
    return tuple(
        (limit, float(by_slice[name]["top1"]), int(by_slice[name]["n"]), words)
        for name, limit, words in _SLICE_TO_BAND
    )
# Below this, say so prominently rather than as a footnote.
LOW_RELIABILITY_ACC = 0.65
# ...but the band that trips that test is also the thinnest one: 0.11 comes
# from nine recordings, 95% CI [0.02, 0.40]. Quoting "11%" to a user implies a
# precision the measurement does not have, so a band this small gets the
# direction of the finding without the decimal point.
MIN_BAND_N = 30


# A band also warns when a longer clip would do materially better, even if the
# band's own accuracy clears the floor above. Without this the rule is purely
# absolute, and an absolute rule breaks as soon as the model's overall level
# moves: model_v2_7's 3-7 minute band sits at 0.66 against 0.74 for its longest
# clips, so a floor of 0.67 would fire on it while a floor of 0.60 would stay
# silent about an 8-point loss the user could simply avoid. The advice the
# warning gives is "use a longer excerpt", so the condition that should trigger
# it is "a longer excerpt would help".
RELIABILITY_GAP = 0.10
# Below this the top answer is wrong more often than not and the warning says
# so in words rather than leaving the user to read the percentage.
USUALLY_WRONG_ACC = 0.50


def _band(voiced_s: float, bands: tuple = RELIABILITY_BANDS
          ) -> tuple[float, float, int, str]:
    for band in bands:
        if voiced_s < band[0]:
            return band
    return bands[-1]


def reliability_for(voiced_s: float,
                    bands: tuple = RELIABILITY_BANDS) -> tuple[float, str]:
    """Measured top-1 accuracy for this much melody, and a plain-words band."""
    _limit, acc, _n, label = _band(voiced_s, bands)
    return acc, label


# Analyses of separate sections are merged downstream and their voiced seconds
# add up, so this warning has to be recomputed from the merged total rather
# than inherited from whichever section happened to be short. The prefix is
# what lets the merge find and drop the stale ones, so it has to lead every
# shape the message can take -- which is why it is about length in general
# rather than shortness in particular.
RELIABILITY_WARNING_PREFIX = "Clip length:"


def reliability_warning(voiced_s: float,
                        bands: tuple = RELIABILITY_BANDS) -> str | None:
    _limit, acc, n, label = _band(voiced_s, bands)
    best = max(b[1] for b in bands)
    if acc >= LOW_RELIABILITY_ACC and best - acc < RELIABILITY_GAP:
        return None
    rate = (
        f"the top answer is right about {acc:.0%} of the time"
        if n >= MIN_BAND_N else
        f"the top answer was right in {acc:.0%} of the {n} such recordings "
        f"in the test set"
    )
    if acc < best:
        rate += f", against {best:.0%} on the longest clips"
    if acc < USUALLY_WRONG_ACC:
        rate += ", so it is usually wrong"
    return (
        f"{RELIABILITY_WARNING_PREFIX} {voiced_s:.0f} s of melody ({label}). "
        f"At this length {rate} — treat it as a hint, and use a longer "
        f"excerpt if you can."
    )


@dataclass
class QualityReport:
    voiced_s: float = 0.0
    voiced_ratio: float = 0.0
    tonic_prominence: float = 0.0
    pcd_norm_entropy: float = 1.0
    reliability: float = 0.0
    reliability_band: str = ""
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def pcd_normalized_entropy(pcd: np.ndarray) -> float:
    p = np.clip(np.asarray(pcd, dtype=np.float64), 1e-12, None)
    p = p / p.sum()
    return float(-(p * np.log(p)).sum() / np.log(len(p)))


def check_quality(
    f0_hz: np.ndarray,
    hop_s: float,
    pcd: np.ndarray | None,
    tonic_prominence: float,
    bands: tuple = RELIABILITY_BANDS,
) -> QualityReport:
    mask = voiced_mask(f0_hz)
    rep = QualityReport(
        voiced_s=float(mask.sum() * hop_s),
        voiced_ratio=float(mask.mean()) if len(mask) else 0.0,
        tonic_prominence=tonic_prominence,
    )
    if rep.voiced_s < MIN_VOICED_S:
        rep.failures.append(
            f"Need at least ~{MIN_VOICED_S:.0f} s of melody; found {rep.voiced_s:.0f} s."
        )
    if rep.voiced_ratio < MIN_VOICED_RATIO:
        rep.failures.append(
            "Couldn't track a dominant melody (speech, percussion-only, or very noisy audio?)."
        )
    if pcd is not None:
        rep.pcd_norm_entropy = pcd_normalized_entropy(pcd)
        if rep.pcd_norm_entropy > MAX_PCD_NORM_ENTROPY:
            rep.failures.append(
                "No clear tonal structure found — this may not be a melodic recording."
            )
    if tonic_prominence < MIN_TONIC_PROMINENCE:
        rep.warnings.append(
            "Tonic estimate looks unreliable — results may be less accurate."
        )
    rep.reliability, rep.reliability_band = reliability_for(rep.voiced_s, bands)
    if rep.ok:
        warn = reliability_warning(rep.voiced_s, bands)
        if warn:
            rep.warnings.append(warn)
    return rep
