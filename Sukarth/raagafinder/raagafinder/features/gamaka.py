"""Gamaka / ornament-dynamics descriptor (pure numpy).

The distribution features the ensemble already ships are time-averaged: the
PCD is a histogram of *where* the pitch sits, and the TDMS is a histogram of
note pairs at a fixed 0.2 s lag. Neither can see *how* the pitch moves inside
that lag -- the speed, oscillation, and slide behaviour that defines gamaka
and, with it, a large part of raga identity (kampita, jaaru, nokku, ...).

This module summarizes the melodic *motion* into a fixed-length descriptor,
computed from exactly the inputs the other features take -- octave-folded
cents, a voicing mask, and the hop -- so it drops straight into the chunk
pipeline and works verbatim in the Space.

Robustness: velocity is derived from the minimal-magnitude frame-to-frame
difference of folded cents. That both (a) makes octave folding transparent to
motion (a true small step near Sa is small regardless of the 1200 wrap) and
(b) turns a single-frame Melodia octave error into one capped spike rather
than a run of garbage. Velocity is clipped to a physical ceiling, and every
scalar is a fraction or a robust percentile, so no single glitch dominates.
"""

import numpy as np

from raagafinder.config import CENTS_PER_OCTAVE

# --- descriptor configuration -------------------------------------------------
# Absolute-velocity histogram: log-spaced edges in cents/second. The first bin
# captures sustained notes / nyas dwelling; the tail captures fast gamaka.
VEL_CAP_CPS = 4000.0            # clip |velocity| to this before binning
VEL_HIST_EDGES = np.concatenate([
    [0.0],
    np.geomspace(30.0, VEL_CAP_CPS, 15),
])                              # -> 15 histogram bins
SUSTAIN_CPS = 60.0              # |v| below this is a "held" frame
DEADBAND_CPS = 90.0            # ignore motion below this when finding runs/turns
MIN_RUN_FRAMES = 3             # minimum voiced run to analyse for turns/slides
MIN_SLIDE_FRAMES = 30          # ~0.13 s: a jaaru slide, not a gamaka half-cycle

GAMAKA_DIM = (len(VEL_HIST_EDGES) - 1) + 10  # 15 + 10 = 25

# Per-swara ornament signature: the descriptor that actually beats the ensemble
# baseline (recording-level pooling of the above is near-useless because it is
# confounded by tempo/artist). Conditioning ornament dynamics on WHICH semitone
# the pitch sits near captures raga-characteristic ornamentation -- an oscillated
# gandhara vs a steady madhyama.
N_SWARA = 12
PERSWARA_DIM = 2 * N_SWARA  # 24: [spread_0..11, mean|vel|_0..11]
# Bump when the per-swara descriptor definition changes; the artifact records
# this in its gamaka meta and predict_chunk refuses a mismatch (a trained
# gamaka_W is only valid for the descriptor it was fit on).
GAMAKA_VERSION = "perswara_v1"


def _voiced_runs(mask: np.ndarray, min_len: int) -> list[tuple[int, int]]:
    """Contiguous [start, end) voiced spans with at least min_len frames."""
    m = np.asarray(mask, dtype=bool)
    if not m.any():
        return []
    edges = np.diff(m.astype(np.int8))
    starts = list(np.flatnonzero(edges == 1) + 1)
    ends = list(np.flatnonzero(edges == -1) + 1)
    if m[0]:
        starts = [0] + starts
    if m[-1]:
        ends = ends + [len(m)]
    return [(s, e) for s, e in zip(starts, ends) if e - s >= min_len]


def _unwrap_run(folded_cents: np.ndarray, hop_s: float):
    """Return (velocity_cps, contour_cents) for one voiced run.

    Both derive from the same minimal-magnitude frame diff, mapped to
    (-600, 600], so octave folding is transparent: a wrap in folded space
    costs nothing and the reconstructed contour is continuous even when a
    phrase legitimately spans more than an octave. A step faster than 600
    cents/frame is nonphysical at the Melodia hop and is already a glitch.
    """
    x = np.asarray(folded_cents, dtype=np.float64)
    d = np.diff(x)
    d -= CENTS_PER_OCTAVE * np.round(d / CENTS_PER_OCTAVE)
    contour = np.concatenate([[0.0], np.cumsum(d)])  # relative, continuous
    v = np.clip(d / hop_s, -VEL_CAP_CPS, VEL_CAP_CPS)
    return v, contour


def compute_gamaka(
    folded_cents: np.ndarray,
    mask: np.ndarray,
    hop_s: float,
) -> np.ndarray:
    """Ornament-dynamics descriptor, shape (GAMAKA_DIM,), float64.

    Layout: [15-bin |velocity| histogram (sums to 1)] followed by 10 scalars:
      sustain_frac, oscillation_rate_hz, osc_depth_med, osc_depth_p90,
      slide_mean_len_s, slide_max_len_s, slide_mean_slope_cps,
      accel_p50, accel_p90, voiced_frac.
    Silent / too-short input returns a zero vector (the caller weights it out).
    """
    m = np.asarray(mask, dtype=bool)
    out = np.zeros(GAMAKA_DIM, dtype=np.float64)
    n_hist = len(VEL_HIST_EDGES) - 1
    if m.sum() < MIN_RUN_FRAMES + 1:
        return out
    out[n_hist + 9] = float(m.mean())  # voiced_frac always meaningful

    runs = _voiced_runs(m, MIN_RUN_FRAMES + 1)
    if not runs:
        return out

    vels, turns, run_secs = [], 0, 0.0
    osc_depths, slide_lens, slide_slopes, accels = [], [], [], []
    for s, e in runs:
        v, c = _unwrap_run(folded_cents[s:e], hop_s)  # v: len-1, c: len (continuous)
        vels.append(v)
        run_secs += (e - s - 1) * hop_s
        accels.append(np.abs(np.diff(v)) / hop_s)  # cents/s^2 magnitude

        # direction turns: sign changes of velocity above the deadband
        sig = np.where(v > DEADBAND_CPS, 1, np.where(v < -DEADBAND_CPS, -1, 0))
        nz = sig[sig != 0]
        if nz.size >= 2:
            turns += int(np.count_nonzero(np.diff(nz) != 0))

        # local extrema of the (continuous) contour -> swing depths (kampita)
        dc = np.diff(c)
        turn_pts = np.flatnonzero(np.sign(dc[:-1]) * np.sign(dc[1:]) < 0) + 1
        if turn_pts.size >= 2:
            osc_depths.extend(np.abs(np.diff(c[turn_pts])).tolist())

        # monotonic slides (jaaru): sustained same-sign runs, long enough to be
        # a glide rather than one half-cycle of an oscillation
        run_dir, run_start = 0, 0
        for i in range(len(sig) + 1):
            d = sig[i] if i < len(sig) else 0
            if d != run_dir:
                if run_dir != 0 and (i - run_start) >= MIN_SLIDE_FRAMES:
                    seg = v[run_start:i]
                    slide_lens.append(len(seg) * hop_s)
                    slide_slopes.append(float(np.mean(np.abs(seg))))
                run_dir, run_start = d, i

    allv = np.abs(np.concatenate(vels)) if vels else np.zeros(1)
    hist, _ = np.histogram(np.clip(allv, 0, VEL_CAP_CPS), bins=VEL_HIST_EDGES)
    total = hist.sum()
    if total > 0:
        out[:n_hist] = hist / total

    out[n_hist + 0] = float((allv < SUSTAIN_CPS).mean())
    out[n_hist + 1] = turns / run_secs if run_secs > 0 else 0.0
    if osc_depths:
        out[n_hist + 2] = float(np.median(osc_depths))
        out[n_hist + 3] = float(np.percentile(osc_depths, 90))
    if slide_lens:
        out[n_hist + 4] = float(np.mean(slide_lens))
        out[n_hist + 5] = float(np.max(slide_lens))
        out[n_hist + 6] = float(np.mean(slide_slopes))
    if accels:
        aa = np.concatenate(accels)
        out[n_hist + 7] = float(np.percentile(aa, 50))
        out[n_hist + 8] = float(np.percentile(aa, 90))
    return out


def compute_gamaka_perswara(
    folded_cents: np.ndarray,
    mask: np.ndarray,
    hop_s: float,
) -> np.ndarray:
    """Per-swara ornament signature, shape (PERSWARA_DIM,), float64.

    For each of the 12 semitone swaras: the pitch spread around it (std of the
    cents deviation from its center -> gamaka width) and the mean |velocity|
    while the pitch is near it (ornament intensity). The velocity half carries
    the discriminative, genuinely-new signal; the spread half mostly refines
    the scale info the ensemble already has.

    Tonic-relative: the swara indexing assumes the given tonic. Under a
    tonic-hypothesis rotation, transform with rotate_gamaka(). Zero vector when
    there is too little voiced data (the caller weights it out).
    """
    m = np.asarray(mask, dtype=bool)
    out = np.zeros(PERSWARA_DIM, dtype=np.float64)
    if m.sum() < MIN_RUN_FRAMES + 1:
        return out
    x = np.asarray(folded_cents, dtype=np.float64)
    d = np.diff(x)
    d -= CENTS_PER_OCTAVE * np.round(d / CENTS_PER_OCTAVE)  # fold-transparent
    v = np.clip(np.abs(d / hop_s), 0, VEL_CAP_CPS)          # len n-1
    pair = m[:-1] & m[1:]
    sw = np.zeros(len(x), dtype=np.int64)
    sw[m] = np.round(x[m] / 100.0).astype(np.int64) % N_SWARA  # only where voiced
    dev = x - 100.0 * np.round(x / 100.0)                   # (-50, 50] from center
    for s in range(N_SWARA):
        near = m & (sw == s)
        if near.sum() >= 3:
            out[s] = float(np.std(dev[near]))
        pnear = pair & (sw[:-1] == s)
        if pnear.sum() >= 3:
            out[N_SWARA + s] = float(v[pnear].mean())
    return out


def rotate_gamaka(feat: np.ndarray, offset_cents: float) -> np.ndarray:
    """Per-swara gamaka feature AS IF the tonic were offset_cents higher.

    Matches the rotate_pcd/rotate_tdms convention: a tonic offset_cents higher
    shifts folded cents DOWN by offset_cents, so each 12-swara half rolls by
    -offset_cents/100 semitones. offset_cents must be a multiple of 100.
    """
    shift = offset_cents / 100.0
    rounded = round(shift)
    if abs(shift - rounded) > 1e-9:
        raise ValueError(f"offset {offset_cents} cents is not a whole semitone")
    k = int(rounded)
    a = np.roll(feat[:N_SWARA], -k)
    b = np.roll(feat[N_SWARA:], -k)
    return np.concatenate([a, b])
