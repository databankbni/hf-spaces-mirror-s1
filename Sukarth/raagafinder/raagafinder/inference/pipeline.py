"""Backend-agnostic inference: audio file -> top-3 raga predictions.

Steps: pitch + tonic extraction (essentia on Linux/WSL/Space, rmvpe fallback)
-> a consensus tonic chosen before classification (choose_tonic) -> tonic-
normalized folded cents -> quality gates -> windowed chunk features ->
ensemble probs -> calibrated aggregation. Long recordings are read as
independent sections and merged by corroboration (analyze_segments).

The tonic is settled first rather than treated as a hypothesis the classifier
votes on, because a classifier's confidence on wrongly-normalised features is
arbitrary.
"""

from dataclasses import dataclass, field

import numpy as np

from raagafinder.config import (
    APP_HOP_S,
    APP_WINDOW_S,
    MIN_VOICED_S,
)
from raagafinder.features.gamaka import compute_gamaka_perswara
from raagafinder.features.pcd import compute_pcd
from raagafinder.features.pitch_utils import fold_octave, hz_to_cents, voiced_mask
from raagafinder.features.tdms import compute_tdms
from raagafinder.inference.quality import (
    RELIABILITY_WARNING_PREFIX,
    QualityReport,
    bands_from_artifact,
    check_quality,
    reliability_warning,
)
from raagafinder.models.artifact import ModelArtifact
from raagafinder.pitch.tonic_hist import choose_tonic, tonic_peak_prominence


# Honesty downgrades must survive prob-averaging in the merge paths, so the
# warning text doubles as a sticky marker (checked with `in`).
MISSING_SWARA_WARNING = (
    "The melody avoids note(s) this raga normally uses — it may be "
    "a related raga outside the supported set."
)


@dataclass
class AnalysisResult:
    status: str  # "ok" | "uncertain" | "error"
    failures: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    top3: list = field(default_factory=list)  # [(raga_name, prob), ...]
    probs: np.ndarray | None = None
    classes: list = field(default_factory=list)
    tonic_hz: float = 0.0
    rotation_cents: int = 0
    voiced_s: float = 0.0
    voiced_ratio: float = 0.0
    duration_s: float = 0.0
    pcd: np.ndarray | None = None  # display PCD under the chosen tonic hypothesis
    lstm_input: tuple | None = None  # (f0, hop_s, tonic_hz) for recording-level blend


_lstm_cache: dict = {}


def _lstm_cache_key(artifact):
    """What actually determines the answer: the artifact's name and its class
    list, which are the only two things below that get read.

    This used to be `id(artifact)`, which is a memory ADDRESS and is reused
    the moment the object it belonged to is collected. A caller that loads one
    model, drops it, and loads another can therefore be handed the first
    model's sequence component for the second model's ensemble, with no error
    anywhere -- the same silent-wrong-component failure the class-alignment
    comment below describes, arriving by a different route. It is not
    hypothetical: it surfaced as tests/test_lstm_alignment.py failing in a
    full-suite run and passing alone, because model_v2_3's sequence model
    carries exactly its ensemble's classes and model_v2_4's does not, so the
    swap was visible only as a missing solo class.

    The app never saw it, because app.py loads every artifact once at import
    and holds them for the process lifetime, so no address is ever freed to be
    reused. That is luck rather than design, and it stops being true for
    anything that loads artifacts on demand.
    """
    return (getattr(artifact, "name", None),
            tuple(getattr(artifact, "classes", ()) or ()))


def _lstm_component(artifact):
    """The sequence model paired with this ensemble artifact (by name) as an
    optional ensemble member; None (cached) when absent, unloadable, or
    class-order-mismatched."""
    key = _lstm_cache_key(artifact)
    if key in _lstm_cache:
        return _lstm_cache[key]
    comp = None
    try:
        from raagafinder.config import ARTIFACTS_DIR
        from raagafinder.models.onnx_lstm import load_if_present

        comp = load_if_present(ARTIFACTS_DIR, getattr(artifact, "name", None))
        # Align the two class lists BY NAME. This used to require the ONNX
        # head's first outputs to equal the artifact's list positionally,
        # which silently switched the sequence model off for model_v2_4: its
        # ensemble cleared quota for Dvijāvanti and its LSTM did not, so the
        # lists diverged at index 16 and the whole blend was dropped without a
        # word. align_classes still returns None on a genuine mispairing.
        if comp is not None:
            from raagafinder.models.onnx_lstm import align_classes

            comp.align = align_classes(artifact.classes, comp.classes)
            if comp.align is None:
                comp = None
    except Exception:
        comp = None
    _lstm_cache[key] = comp
    return comp


# NOTE — a pure-numpy phrase/motif ensemble member (note-order bigrams+trigrams;
# see raagafinder/features/phrases.py, raagafinder/models/phrase_ngram.py,
# scripts/fit_dirB_phrases.py) was built and tested as "Direction B". It beats
# the histogram ensemble ALONE (grouped-OOF 0.801 -> 0.831) — note order really
# is the missing signal — but the LSTM already captures note order far better
# (fold-0: ens+LSTM 0.852 vs ens+phrase 0.795), so it added nothing on top of
# the LSTM and could not replace it. Left out of serving; the scripts remain for
# a future corpus/model without an LSTM. See docs/phrase_model_experiment.md.


def _windows(n_frames: int, mask: np.ndarray, hop_s: float):
    """App-time chunk windows: APP_WINDOW_S long, APP_HOP_S apart, keeping
    windows with enough voiced content; always includes the full track."""
    win = int(APP_WINDOW_S / hop_s)
    step = int(APP_HOP_S / hop_s)
    min_voiced_frames = int(0.4 * MIN_VOICED_S / hop_s)
    spans = [(0, n_frames)]
    for start in range(0, max(1, n_frames - win + 1), step):
        end = min(start + win, n_frames)
        if mask[start:end].sum() >= min_voiced_frames:
            spans.append((start, end))
    return spans


def analyze(
    audio_path: str,
    artifact: ModelArtifact,
    backend=None,
    tonic_override: float | None = None,
    _pitch: tuple | None = None,
) -> AnalysisResult:
    if backend is None:
        from raagafinder.pitch.base import get_backend

        backend = get_backend()

    f0, hop_s = _pitch if _pitch is not None else backend.extract_pitch(audio_path)
    tonic_vetoed = False
    if tonic_override and tonic_override > 0:
        tonic_hz = float(tonic_override)
    else:
        detected = backend.extract_tonic(audio_path)
        tonic_hz, _mass, tonic_vetoed = choose_tonic([(f0, 1.0)], [detected])
        if tonic_hz <= 0:
            tonic_hz = detected

    mask = voiced_mask(f0)
    cents = hz_to_cents(f0, tonic_hz)
    folded = fold_octave(cents)
    voiced_folded = folded[mask]

    pcd_full = compute_pcd(voiced_folded) if mask.sum() > 10 else None
    prominence = tonic_peak_prominence(f0, tonic_hz) if mask.any() else 0.0
    quality: QualityReport = check_quality(f0, hop_s, pcd_full, prominence,
                                           bands_from_artifact(artifact.meta))
    base = AnalysisResult(
        status="error",
        failures=quality.failures,
        warnings=quality.warnings,
        classes=artifact.classes,
        tonic_hz=tonic_hz,
        voiced_s=quality.voiced_s,
        voiced_ratio=quality.voiced_ratio,
        duration_s=len(f0) * hop_s,
        pcd=pcd_full,
    )
    if not quality.ok:
        return base

    # Chunk features. Tonic is already resolved (choose_tonic), so features are
    # computed once at that tonic -- no classify-time rotation.
    chunk_feats = []
    for s, e in _windows(len(f0), mask, hop_s):
        try:
            pcd = compute_pcd(folded[s:e][mask[s:e]])
            tdms = compute_tdms(folded[s:e], mask[s:e], hop_s)
        except ValueError:
            continue
        gamaka = compute_gamaka_perswara(folded[s:e], mask[s:e], hop_s)
        chunk_feats.append((pcd, tdms, gamaka))
    if not chunk_feats:
        base.failures.append("Could not extract enough melodic content to analyze.")
        return base

    # Tonic hypotheses are resolved BEFORE classification by choose_tonic()
    # (detector consensus + Sa-mass veto). The old scheme — classify under
    # rotated features and compare probabilities — let a wrong tonic win
    # whenever its rotation happened to resemble some other raga.
    thresholds = artifact.meta["thresholds"]
    if tonic_vetoed:
        base.warnings.append(
            "Tonic re-estimated from the note distribution (the detector's "
            "estimate did not look like a Sa)."
        )

    chunk_probs = [artifact.predict_chunk(p, t, g) for p, t, g in chunk_feats]
    probs = artifact.calibrate(artifact.aggregate_uncalibrated(chunk_probs))

    # v3 LSTM blend happens at the RECORDING level in analyze_segments():
    # blending per-section changed which sections corroborate each other and
    # regressed real-audio accuracy (measured 2026-07-22, per-section blend:
    # YouTube 57.1% vs 71.4%). Only what the LSTM needs is stashed here.
    if _lstm_component(artifact) is not None:
        base.lstm_input = (f0, hop_s, tonic_hz)

    order = np.argsort(probs)[::-1]
    base.probs = probs
    base.rotation_cents = 0
    base.top3 = [(artifact.classes[i], float(probs[i])) for i in order[:3]]

    top1, top2 = probs[order[0]], probs[order[1]]
    uncertain = top1 < thresholds["uncertain_top1"] or (
        top1 - top2
    ) < thresholds["uncertain_margin"]

    # Missing-swara honesty check: if the predicted raga's training template
    # has clear mass at a swara the recording never touches, the recording is
    # likely a janya/subset raga OUTSIDE the supported set (e.g. Hamsadhwani
    # classified as Śankarābharaṇaṁ). Downgrade confidence and say why.
    if "pcd_templates" in artifact.arrays and base.pcd is not None:
        template = artifact.arrays["pcd_templates"][order[0]].astype(np.float64)
        n_bins = len(template)
        obs = base.pcd
        swara_bins = n_bins // 12
        half = swara_bins // 2
        missing = []
        for s in range(12):
            idx = (np.arange(-half, half) + s * swara_bins) % n_bins
            t_mass, o_mass = template[idx].sum(), obs[idx].sum()
            # RELATIVE deficit: gamaka glides deposit passing-tone mass in
            # every swara window (measured ~1-5% even for absent swaras), so
            # an absolute floor never fires. Fire when the recording shows
            # under 30% of the mass the template expects there.
            if t_mass >= 0.04 and o_mass < max(0.010, 0.30 * t_mass):
                missing.append(s)
        if missing:
            uncertain = True
            base.warnings.append(MISSING_SWARA_WARNING)

    # NOTE — minor-third tonic errors are a KNOWN OPEN
    # LIMITATION with no scale-level fix. Measured (scripts/debug_hint.py):
    # scoring canonical arohana/avarohana scale sets across all classes is
    # tonic-INVARIANT — at the wrong tonic the folded note set simply matches
    # a different valid raga (graha bheda): one failing recording at the wrong
    # tonic fits Śrī 0.856 vs Kalyāṇi 0.858 at the true tonic. Disambiguating
    # needs phrase-level cues (gamakas, characteristic sancharas), not pitch
    # histograms. Classifier probs at alternate tonics are equally unusable
    # (OOD → confidently wrong). Do not re-attempt an alternative-tonic hint
    # from folded-mass evidence.

    base.status = "uncertain" if uncertain else "ok"
    return base


def _lstm_blend(artifact, results, mix):
    """Recording-level LSTM refinement of a merged distribution (see the
    comment in analyze_segments). Returns mix unchanged when the optional
    component is absent or none of the sections had usable input. In
    class-union mode the returned vector is longer than the artifact's
    class list (LSTM-only classes appended); callers must name classes
    via the component then."""
    lstm = _lstm_component(artifact)
    if lstm is None:
        return mix
    p3s = [
        p for r in results if r.lstm_input is not None
        for p in [lstm.probs(*r.lstm_input)] if p is not None
    ]
    if not p3s:
        return mix
    return lstm.combine(mix, np.mean(p3s, axis=0))


def _blend_names(artifact, probs):
    """Class names for a (possibly class-union) probability vector.

    The unguarded _lstm_component below is safe on an ensemble-only artifact:
    only the LSTM can lengthen the vector past artifact.classes, so with no
    component the early return always fires. Both callers are inside an
    `lstm is not None` branch as well.
    """
    if len(probs) == len(artifact.classes):
        return None  # _rethreshold defaults to artifact.classes
    return _lstm_component(artifact).align.classes


def _rethreshold(result: AnalysisResult, probs: np.ndarray, artifact: ModelArtifact,
                 names=None):
    names = names if names is not None else artifact.classes
    thresholds = artifact.meta["thresholds"]
    order = np.argsort(probs)[::-1]
    result.probs = probs
    result.top3 = [(names[i], float(probs[i])) for i in order[:3]]
    top1, top2 = probs[order[0]], probs[order[1]]
    uncertain = top1 < thresholds["uncertain_top1"] or (
        top1 - top2
    ) < thresholds["uncertain_margin"]
    result.status = "uncertain" if uncertain else "ok"
    return result


def analyze_segments(
    paths,
    artifact: ModelArtifact,
    analyze_one=None,
    backend=None,
) -> AnalysisResult:
    """Analyze sampled sections of a long recording INDEPENDENTLY and merge.

    A recording has ONE shruti, so a consensus tonic is chosen across all
    sections first (per-section tonic estimates are the dominant real-world
    failure: one section detecting a fourth/fifth off produced confident
    wrong answers). Then each section is analyzed under that tonic and merged:
    an answer is adopted only when sections corroborate it.

    analyze_one(path, tonic_override=..., _pitch=...) must accept the consensus
    tonic and, when the pre-pass backend matches its own, a precomputed pitch
    track. Default is the robust (Melodia + RMVPE-fallback) path.
    """
    share_pitch = analyze_one is None
    if analyze_one is None:
        analyze_one = lambda p, **kw: analyze_robust(p, artifact, **kw)  # noqa: E731
    else:
        share_pitch = backend is not None  # caller extracted with same backend
    if backend is None:
        from raagafinder.pitch import essentia_backend

        try:
            essentia_backend.assert_available()
            backend = essentia_backend
        except ImportError:
            from raagafinder.pitch.base import get_backend

            backend = get_backend()

    if len(paths) == 1:
        # Short (single-section) recordings blend ONLY when the LSTM's own
        # windows agree on the answer — the within-model analog of section
        # corroboration. Ungated blending measured 0 wins / -1 holdout
        # top-3 (2026-07-23); with the agreement gate at 0.6, every
        # LSTM-wrong holdout item is gated off while fold-0 crops still
        # gain +2.6 top-1 (scripts/fit_shortclip_blend.py, n=76).
        r = analyze_one(paths[0])
        lstm = _lstm_component(artifact)
        if lstm is not None and r.probs is not None and r.lstm_input is not None:
            res = lstm.probs(*r.lstm_input, return_agreement=True)
            if res is not None:
                p3, agree = res
                if agree >= lstm.short_agree_min:
                    blended = lstm.combine(r.probs, p3)
                    swara_forced = any(
                        MISSING_SWARA_WARNING in w for w in r.warnings)
                    r = _rethreshold(r, blended, artifact,
                                     _blend_names(artifact, blended))
                    if swara_forced:
                        r.status = "uncertain"
        return r

    views, dets = [], []
    for p in paths:
        f0, hop = backend.extract_pitch(p)
        views.append((f0, float(voiced_mask(f0).sum() * hop), hop))
        dets.append(backend.extract_tonic(p))
    consensus, _mass, vetoed = choose_tonic(
        [(f0, w) for f0, w, _ in views], dets
    )
    results = []
    for p, (f0, _w, hop) in zip(paths, views):
        kw = dict(tonic_override=consensus if consensus > 0 else None)
        if share_pitch:
            kw["_pitch"] = (f0, hop)
        results.append(analyze_one(p, **kw))
    if vetoed:
        for r in results:
            r.warnings.append(
                "Tonic re-estimated from the note distribution (the detector's "
                "estimate did not look like a Sa)."
            )
    valid = [r for r in results if r.probs is not None]
    if not valid:
        return max(results, key=lambda r: r.voiced_s)

    def top1(r):
        return r.top3[0][0] if r.top3 else None

    ok = [r for r in valid if r.status == "ok"]
    agree = []
    if ok:
        names = [top1(r) for r in ok]
        best = max(set(names), key=names.count)
        agree = [r for r in ok if top1(r) == best]

    forced_uncertain = False
    if len(agree) >= 2:
        chosen, note = agree, (
            f"{len(agree)} of {len(results)} analyzed sections agree."
        )
    elif len(ok) == 1 and any(
        top1(ok[0]) in [n for n, _ in r.top3]
        for r in valid
        if r is not ok[0]
    ):
        # one confident section, corroborated by another section's top-3 lean
        chosen, note = [ok[0]], "One section was clearest; others lean the same way."
    else:
        # no corroborated confident answer — a lone confident section is the
        # exact signature of a contaminated sample (intro speech, a different
        # item on the same upload), so never let it through as "ok"
        chosen, note = valid, (
            "Sections of this recording disagreed — combined cautiously."
        )
        forced_uncertain = True
    primary = max(chosen, key=lambda r: float(r.probs.max()))
    mix = np.mean([r.probs for r in chosen], axis=0)

    # v3 LSTM blend — RECORDING level, after section corroboration (blending
    # per-section changed which sections agreed and regressed real audio;
    # measured 2026-07-22). Section choice above is pure-ensemble; the LSTM
    # only refines the final merged distribution. Weight/temperature fit on a
    # complete ten-fold out-of-fold run (scripts/fit_v3_blend.py --oof).
    mix = _lstm_blend(artifact, chosen, mix)

    merged = _rethreshold(primary, mix, artifact, _blend_names(artifact, mix))
    if forced_uncertain or any(
        MISSING_SWARA_WARNING in w for r in chosen for w in r.warnings
    ):
        merged.status = "uncertain"
    merged.voiced_s = float(sum(r.voiced_s for r in valid))
    merged.duration_s = float(sum(r.duration_s for r in results))
    # The short-clip warning is per-section and the sections' voiced seconds
    # add up here, so drop whatever the sections said and re-derive it from the
    # merged total. Otherwise one short section makes a ten-minute analysis
    # claim it only saw forty seconds.
    merged.warnings = sorted({
        w for r in chosen for w in r.warnings
        if not w.startswith(RELIABILITY_WARNING_PREFIX)
    }) + [note]
    warn = reliability_warning(merged.voiced_s,
                               bands_from_artifact(artifact.meta))
    if warn:
        merged.warnings.append(warn)
    return merged


def analyze_robust(
    audio_path: str,
    artifact: ModelArtifact,
    max_fallback_duration_s: float = 420.0,
    tonic_override: float | None = None,
    _pitch: tuple | None = None,
) -> AnalysisResult:
    """Two-tracker analysis: fast MELODIA first; if the result is not a
    confident 'ok' (typical for film songs / dense mixes where MELODIA hops
    between instruments), retry with the vocal-specific RMVPE tracker and
    combine. Falls back gracefully when either backend is unavailable."""
    from raagafinder.pitch import essentia_backend, rmvpe_backend

    try:
        essentia_backend.assert_available()
        primary = analyze(
            audio_path, artifact, backend=essentia_backend,
            tonic_override=tonic_override, _pitch=_pitch,
        )
    except ImportError:
        return analyze(
            audio_path, artifact, backend=rmvpe_backend,
            tonic_override=tonic_override,
        )
    if primary.status == "ok":
        return primary
    try:
        rmvpe_backend.assert_available()
    except ImportError:
        return primary
    if primary.duration_s > max_fallback_duration_s:
        return primary

    # Hybrid secondary: RMVPE's vocal-specific pitch + essentia's drone-aware
    # tonic. RMVPE's own histogram tonic is wrong on ~half of real concerts
    # (most-sung note != Sa), which wrecks everything downstream.
    from types import SimpleNamespace

    hybrid = SimpleNamespace(
        extract_pitch=rmvpe_backend.extract_pitch,
        extract_tonic=essentia_backend.extract_tonic,
    )
    secondary = analyze(
        audio_path, artifact, backend=hybrid, tonic_override=tonic_override
    )
    if primary.probs is None or secondary.probs is None:
        best = secondary if secondary.status != "error" else primary
        if best is secondary:
            best.warnings.append(
                "Used vocal-focused analysis (better for film/studio songs)."
            )
        return best

    # Two INDEPENDENT trackers agreeing is evidence; the secondary must never
    # override alone (measured: wholesale adoption flipped correct-leaning
    # results to the secondary's confident-wrong answer on concert audio).
    mix = (primary.probs + secondary.probs) / 2.0
    agree = bool(
        primary.top3 and secondary.top3
        and primary.top3[0][0] == secondary.top3[0][0]
    )
    combined = secondary if secondary.probs.max() >= primary.probs.max() else primary
    combined = _rethreshold(combined, mix, artifact)
    if not (secondary.status == "ok" and agree):
        combined.status = "uncertain"
    if any(
        MISSING_SWARA_WARNING in w
        for r in (primary, secondary)
        for w in r.warnings
    ):
        combined.status = "uncertain"  # honesty downgrade survives averaging
    combined.warnings.append("Combined two melody-tracking methods.")
    return combined
