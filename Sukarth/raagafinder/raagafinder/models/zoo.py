"""Chunked training, model zoo, grouped CV, calibration, artifact export.

Protocol:
- Training items = multi-scale voiced-time chunks ({30,60,120,240}s, ~16 per
  recording) with pitch-track augmentation (voiced dropout, gap insertion,
  tonic jitter) on half of them, plus the full recording.
- Test items mimic the app: 45 s windows w/ 15 s hop + full track, chunk probs
  aggregated (mean) to a recording-level distribution.
- CV folds = frozen stratified GroupKFold by concert (work/splits.json).
- Models: kNN over recording-level TDMS refs (k/T grid, Bhattacharyya), multinomial
  logistic regression on PCD, per-swara gamaka logreg. Ensemble = weighted mix
  of those three, chosen on OOF; temperature calibration on OOF; thresholds fit
  on OOF. LightGBM runs on one fold as a CONTROL and never ships (see below).
- Rotation recovery: synthetic fifth-shifts of a recording sample must be
  recovered by the pipeline's hypothesis rule. Measured in-sample, against the
  full-data model and reference set -- the production condition (see the NOTE
  at the rotation test).
- Export: pure-numpy artifact (npz + json).
"""

import json
from contextlib import contextmanager
from time import perf_counter

import numpy as np
from tqdm import tqdm

from raagafinder.config import (
    ARTIFACTS_DIR,
    CHUNK_VOICED_LENGTHS_S,
    CHUNKS_PER_RECORDING,
    PCD_BINS,
    ROTATION_ACCEPT_MARGIN,
    TONIC_ROTATIONS_CENTS,
    UNCERTAIN_MARGIN,
    UNCERTAIN_TOP1,
    WORK_DIR,
    feature_config_hash,
)
from raagafinder.features.gamaka import (
    GAMAKA_VERSION,
    PERSWARA_DIM,
    compute_gamaka_perswara,
)
from raagafinder.features.pcd import compute_pcd
from raagafinder.features.pitch_utils import sample_voiced_windows
from raagafinder.features.rotations import rotate_pcd, rotate_tdms
from raagafinder.features.tdms import compute_tdms
from raagafinder.models.aggregate import aggregate_chunks
from raagafinder.models.calibrate import apply_temperature, fit_temperature
from raagafinder.models.train import load_index, load_pitch_cache

RNG = np.random.default_rng(42)
_EPS = 1e-12

APP_WIN_S, APP_HOP_WIN_S = 45.0, 15.0

# PCD vectors sum to 1 over 240 bins (values ~1e-4..4e-2). sklearn >=1.9's
# LogisticRegression collapses at that feature scale (measured 4% vs 74%
# accuracy) — train on PCD*PCD_BINS and fold the scale into the exported
# weights so the artifact still consumes raw PCDs unchanged.
PCD_FEAT_SCALE = float(PCD_BINS)


def _full_proba(clf, X, n_classes):
    """predict_proba padded to all n_classes columns. A grouped fold can hold
    out every concert of a sparse class, leaving it out of the fold's training
    set; without padding the probability vector would be short and misaligned."""
    p = clf.predict_proba(X)
    if p.shape[1] == n_classes:
        return p
    full = np.zeros((len(X), n_classes))
    full[:, clf.classes_] = p
    return full


# -- chunk generation --------------------------------------------------------


def augment(folded, mask, hop_s, rng):
    """Pitch-track-level augmentation simulating app-time degradation."""
    folded = folded.copy()
    mask = mask.copy()
    # voiced-frame dropout
    drop_p = rng.uniform(0.1, 0.4)
    voiced_idx = np.flatnonzero(mask)
    drop = rng.random(len(voiced_idx)) < drop_p
    mask[voiced_idx[drop]] = False
    # 1-3 contiguous gaps of 2-10 s
    for _ in range(rng.integers(1, 4)):
        gap = int(rng.uniform(2.0, 10.0) / hop_s)
        if gap < len(mask):
            s = rng.integers(0, len(mask) - gap)
            mask[s : s + gap] = False
    # tonic jitter +-25 cents
    folded = np.mod(folded + rng.uniform(-25, 25), 1200.0)
    return folded, mask


def make_train_chunks(cache, mbids, labels):
    """Returns (pcd_X, tdms_X, gamaka_X, y, rec_idx) for all training chunks."""
    pcds, tdmss, gamakas, ys, recs = [], [], [], [], []
    per_len = max(1, CHUNKS_PER_RECORDING // len(CHUNK_VOICED_LENGTHS_S))
    for ri, m in enumerate(tqdm(mbids, desc="train chunks")):
        folded, mask, hop = cache[m]
        variants = [(folded, mask)]
        for length in CHUNK_VOICED_LENGTHS_S:
            for s, e in sample_voiced_windows(mask, hop, length, per_len, RNG):
                fw, mw = folded[s:e], mask[s:e]
                if RNG.random() < 0.5:
                    fw, mw = augment(fw, mw, hop, RNG)
                variants.append((fw, mw))
        for fw, mw in variants:
            try:
                pcds.append(compute_pcd(fw[mw]).astype(np.float32))
                tdmss.append(compute_tdms(fw, mw, hop).astype(np.float32).ravel())
            except ValueError:
                continue
            gamakas.append(compute_gamaka_perswara(fw, mw, hop).astype(np.float32))
            ys.append(labels[ri])
            recs.append(ri)
    return (np.stack(pcds), np.stack(tdmss), np.stack(gamakas),
            np.array(ys), np.array(recs))


def make_test_chunks(cache, mbid):
    """App-parity test chunks: 45 s windows w/ 15 s hop + full track.
    Each chunk is (pcd, tdms_flat, gamaka)."""
    folded, mask, hop = cache[mbid]
    win, step = int(APP_WIN_S / hop), int(APP_HOP_WIN_S / hop)
    spans = [(0, len(folded))]
    for s in range(0, max(1, len(folded) - win + 1), step):
        e = min(s + win, len(folded))
        if mask[s:e].sum() * hop >= 8.0:
            spans.append((s, e))
    out = []
    for s, e in spans:
        try:
            pcd = compute_pcd(folded[s:e][mask[s:e]]).astype(np.float32)
            tdms = compute_tdms(folded[s:e], mask[s:e], hop).astype(np.float32).ravel()
        except ValueError:
            continue
        gamaka = compute_gamaka_perswara(folded[s:e], mask[s:e], hop).astype(np.float32)
        out.append((pcd, tdms, gamaka))
    return out


# -- kNN over recording-level references --------------------------------------


def chunk_bhatt_D(Q, refs_sqrt):
    """Bhattacharyya distance matrix D (n_chunks, n_refs). This matmul is the
    dominant CV cost, and it depends on NEITHER k nor T -- so compute it once
    per recording and reuse it across the whole (k, T) grid (see run())."""
    bc = np.sqrt(np.clip(Q, 0, None)) @ refs_sqrt.T
    return -np.log(np.clip(bc, _EPS, None))


def knn_from_D(D, ref_labels, n_classes, k, T):
    """Soft kNN class probs per chunk from a precomputed distance matrix D."""
    part = np.argpartition(D, min(k, D.shape[1] - 1), axis=1)[:, :k]
    rows = np.arange(D.shape[0])[:, None]
    dk = D[rows, part]
    w = np.exp(-(dk - dk.min(axis=1, keepdims=True)) / T)
    probs = np.zeros((D.shape[0], n_classes))
    for i in range(D.shape[0]):
        np.add.at(probs[i], ref_labels[part[i]], w[i])
    return probs / probs.sum(axis=1, keepdims=True)


def knn_chunk_probs(Q, refs_sqrt, ref_labels, n_classes, k, T):
    """Vectorized Bhattacharyya kNN for all query chunks at once.
    Q (n,D) surfaces; refs_sqrt (R,D) precomputed sqrt refs. Thin wrapper kept
    for callers that classify at a single (k, T)."""
    return knn_from_D(chunk_bhatt_D(Q, refs_sqrt), ref_labels, n_classes, k, T)


# -- main --------------------------------------------------------------------


def run(index_fn=load_index, splits_name="splits.json", out_name="model_v1",
        rotation_test=True, fast=False):
    from raagafinder.models.train import make_splits

    index, mbids, classes, labels, concerts, artists = index_fn()
    n_classes = len(classes)
    if not (WORK_DIR / splits_name).exists():
        make_splits(mbids, labels, concerts, artists, out_name=splits_name)
    splits = json.loads((WORK_DIR / splits_name).read_text(encoding="utf-8"))

    # make_splits refuses the fresh-YouTube probe recordings a fold so that
    # no model trains on them. The corpus loader still returns them, so they
    # arrive here fold-less and must be dropped -- and only they may be: any
    # other fold-less recording is a stale splits file, which silently
    # shrinking the corpus would hide.
    from raagafinder.models.youtube_probe import YOUTUBE_PROBE

    unassigned = [m for m in mbids if m not in splits["concert_fold"]]
    stray = [m for m in unassigned if m not in set(YOUTUBE_PROBE)]
    assert not stray, (
        f"{len(stray)} non-probe recordings missing from {splits_name}, "
        f"e.g. {stray[:3]} -- the splits file predates the corpus")
    if unassigned:
        drop = set(unassigned)
        keep = [i for i, m in enumerate(mbids) if m not in drop]
        mbids = [mbids[i] for i in keep]
        labels = np.asarray(labels)[keep]
        concerts = [concerts[i] for i in keep]
        artists = [artists[i] for i in keep]
        print(f"holding {len(drop)} probe recordings out of training")

    folds = np.array([splits["concert_fold"][m] for m in mbids])
    cache = load_pitch_cache(mbids)

    # Recording-level reference surfaces + PCDs (for kNN refs and UI templates)
    rec_tdms = np.stack([
        compute_tdms(*cache[m]).astype(np.float32).ravel() for m in tqdm(mbids, desc="rec tdms")
    ])
    rec_pcd = np.stack([
        compute_pcd(cache[m][0][cache[m][1]]).astype(np.float32) for m in mbids
    ])

    pcd_X, tdms_X, gamaka_X, y, rec_idx = make_train_chunks(cache, mbids, labels)
    print(f"train chunks: {len(y)}")

    test_chunks = {m: make_test_chunks(cache, m) for m in tqdm(mbids, desc="test chunks")}

    # ---------------- grouped CV ----------------
    from sklearn.linear_model import LogisticRegression
    if not fast:
        import lightgbm as lgb  # non-shipping control; the numpy trio always exports

    knn_grid = [(k, T) for k in (1, 5, 10, 20) for T in (0.05, 0.1, 0.25)]
    param_models = ["logreg"] if fast else ["logreg", "lgbm"]
    oof = {name: np.zeros((len(mbids), n_classes)) for name in
           param_models + ["gamaka"] + [f"knn_k{k}_T{T}" for k, T in knn_grid]}

    # LightGBM is a CONTROL, not a component. Nothing downstream reads
    # oof["lgbm"]: the exported ensemble is kNN + PCD-logreg + gamaka, all
    # pure numpy, and lgbm exists only to print whether a gradient-boosted
    # baseline would have beaten the logreg. It was nevertheless being trained
    # on every fold, and multiclass boosting builds n_estimators x n_classes
    # trees -- 400 x 88 = 35,200 per fold at the current class count, ten times
    # over. So the run's dominant cost scaled with the number of ragas while
    # its value stayed at one printed line, and the retrain cycle ran to twenty
    # hours at this corpus size.
    #
    # One fold is enough for a control. The comparison below is made on that
    # fold's recordings for BOTH models, so it stays like-for-like; it is a
    # smaller sample than before and is reported as such.
    lgbm_fold = sorted(set(folds))[0]

    # This loop is the run's wall clock, and until now the only thing it
    # reported was a tqdm bar -- so "the fit is slow" could never be turned into
    # "this stage is slow" without guessing. Guessing gets it wrong: a fold can
    # take four times its neighbour for scheduling reasons that have nothing to
    # do with the model. Attribute the seconds instead.
    spent = {}

    @contextmanager
    def timed(key):
        t0 = perf_counter()
        yield
        spent[key] = spent.get(key, 0.0) + perf_counter() - t0

    for f in tqdm(sorted(set(folds)), desc="folds"):
        tr_rec = np.flatnonzero(folds != f)
        te_rec = np.flatnonzero(folds == f)
        tr_chunk = np.isin(rec_idx, tr_rec)

        with timed("fit logreg"):
            lr = LogisticRegression(C=1.0, max_iter=2000)
            lr.fit(pcd_X[tr_chunk] * PCD_FEAT_SCALE, y[tr_chunk])
        with timed("fit gamaka"):
            # per-swara gamaka: z-score on TRAIN stats only, balanced logreg
            gmu = gamaka_X[tr_chunk].mean(0)
            gsd = gamaka_X[tr_chunk].std(0) + 1e-9
            glr = LogisticRegression(C=1.0, max_iter=3000,
                                     class_weight="balanced")
            glr.fit((gamaka_X[tr_chunk] - gmu) / gsd, y[tr_chunk])
        if not fast and f == lgbm_fold:
            with timed("fit lgbm (control, 1 fold)"):
                gbm = lgb.LGBMClassifier(
                    n_estimators=400, learning_rate=0.06, num_leaves=31,
                    feature_fraction=0.7, verbosity=-1, n_jobs=-1,
                )
                gbm.fit(pcd_X[tr_chunk] * PCD_FEAT_SCALE, y[tr_chunk])

        refs_sqrt = np.sqrt(np.clip(rec_tdms[tr_rec].astype(np.float64), 0, None))
        ref_lab = labels[tr_rec]

        for ri in te_rec:
            chunks = test_chunks[mbids[ri]]
            if not chunks:
                continue
            P = np.stack([c[0] for c in chunks]).astype(np.float64) * PCD_FEAT_SCALE
            S = np.stack([c[1] for c in chunks]).astype(np.float64)
            G = (np.stack([c[2] for c in chunks]).astype(np.float64) - gmu) / gsd
            with timed("predict logreg+gamaka"):
                oof["logreg"][ri] = aggregate_chunks(lr.predict_proba(P))
                oof["gamaka"][ri] = aggregate_chunks(_full_proba(glr, G, n_classes))
            if not fast and f == lgbm_fold:
                with timed("predict lgbm"):
                    oof["lgbm"][ri] = aggregate_chunks(gbm.predict_proba(P))
            with timed("knn distances"):
                # once per recording, reused over the whole k/T grid
                D = chunk_bhatt_D(S, refs_sqrt)
            with timed("knn grid"):
                for k, T in knn_grid:
                    cp = knn_from_D(D, ref_lab, n_classes, k, T)
                    oof[f"knn_k{k}_T{T}"][ri] = aggregate_chunks(cp)

    total = sum(spent.values())
    print(f"cv loop {total / 60:.0f} min:")
    for key, secs in sorted(spent.items(), key=lambda kv: -kv[1]):
        print(f"  {secs / 60:7.1f} min  {100 * secs / max(total, 1e-9):4.0f}%  {key}")

    # ---------------- model selection ----------------
    def top1(P):
        return float((P.argmax(1) == labels).mean())

    def topk(P, k=3):
        return float(np.mean([labels[i] in np.argsort(P[i])[::-1][:k] for i in range(len(labels))]))

    # lgbm is deliberately excluded here: it only has predictions for one fold,
    # so scoring it against every label would read the untouched zero rows as
    # wrong answers and report a control that never ran as one that lost badly.
    scores = {name: (top1(P), topk(P)) for name, P in oof.items()
              if name != "lgbm"}
    for name, (t1, t3) in sorted(scores.items(), key=lambda kv: -kv[1][0]):
        print(f"  {name:>16}: top1 {t1:.3f}  top3 {t3:.3f}")

    best_knn = max((n for n in oof if n.startswith("knn")), key=lambda n: scores[n][0])
    lgbm_control = None
    if not fast:
        sub = folds == lgbm_fold
        gb1 = float((oof["lgbm"][sub].argmax(1) == labels[sub]).mean())
        lr1 = float((oof["logreg"][sub].argmax(1) == labels[sub]).mean())
        lgbm_control = dict(fold=int(lgbm_fold), n=int(sub.sum()),
                            lgbm_top1=gb1, logreg_top1=lr1)
        print(f"  control (fold {lgbm_fold}, n={int(sub.sum())}): lgbm "
              f"{gb1:.3f} vs logreg {lr1:.3f}")
        if gb1 > lr1:
            print(f"note: lgbm beat logreg on that fold (not pure-numpy "
                  f"shippable, so logreg is still what ships). One fold at "
                  f"this corpus size resolves about one recording per point — "
                  f"treat a small gap as no gap.")

    # Ensemble weight search over the exportable pure-numpy trio: kNN (best
    # k,T) + PCD-logreg + per-swara gamaka. Grid the (knn, logreg, gamaka)
    # simplex; gamaka adds the ornament-dynamics axis the other two are blind
    # to. All three ship as numpy, so the winning mix is exported verbatim.
    comps = (oof[best_knn], oof["logreg"], oof["gamaka"])
    w_knn, w_logreg, w_gamaka, best_ens_t1 = 1.0, 0.0, 0.0, 0.0
    grid = np.linspace(0, 1, 21)
    for a in grid:
        for b in grid:
            if a + b > 1.0 + 1e-9:
                continue
            c = max(0.0, 1.0 - a - b)
            t1 = top1(a * comps[0] + b * comps[1] + c * comps[2])
            if t1 > best_ens_t1 + 1e-12:
                best_ens_t1 = t1
                w_knn, w_logreg, w_gamaka = float(a), float(b), float(c)
    print(f"best knn: {best_knn}; ensemble weights knn={w_knn:.2f} "
          f"logreg={w_logreg:.2f} gamaka={w_gamaka:.2f} -> top1 {best_ens_t1:.3f}")

    ens_oof = w_knn * comps[0] + w_logreg * comps[1] + w_gamaka * comps[2]
    ens_oof /= ens_oof.sum(1, keepdims=True)
    best_ens_t1 = top1(ens_oof)
    print(f"exported ensemble: top1 {best_ens_t1:.3f} top3 {topk(ens_oof):.3f}")

    # The number just printed is the MAXIMUM over the simplex grid above,
    # read off the same out-of-fold predictions it is reported on. This
    # project measures exactly that bias in other people's methods and
    # prices it at 6.5 points for a 2700-cell grid and 1.25 for a 36-cell
    # one, so quoting its own selected maximum without the honest
    # counterpart would be the same error it documents.
    #
    # The nested version chooses the weights on nine folds and applies
    # them once to the tenth, so no fold contributes to the choice of the
    # weights that score it. It is stored beside the selected figure
    # rather than replacing it: both are informative, and the gap between
    # them is the quantity of interest.
    nested_hits, nested_choices = [], []
    for f in sorted(set(folds.tolist())):
        te = folds == f
        tr = ~te
        best_in, best_w = -1.0, (1.0, 0.0, 0.0)
        for a in grid:
            for b in grid:
                if a + b > 1.0 + 1e-9:
                    continue
                c = max(0.0, 1.0 - a - b)
                mix = (a * comps[0][tr] + b * comps[1][tr]
                       + c * comps[2][tr])
                t = float((mix.argmax(1) == labels[tr]).mean())
                if t > best_in + 1e-12:
                    best_in, best_w = t, (float(a), float(b), float(c))
        a, b, c = best_w
        mix_te = a * comps[0][te] + b * comps[1][te] + c * comps[2][te]
        nested_hits.append(mix_te.argmax(1) == labels[te])
        nested_choices.append(best_w)
    nested_t1 = float(np.concatenate(nested_hits).mean())
    print(f"nested ensemble (weights chosen off-fold): top1 {nested_t1:.3f}"
          f"  selection advantage {100 * (best_ens_t1 - nested_t1):+.2f} pts")

    # ---------------- calibration + thresholds ----------------
    temp = fit_temperature(ens_oof, labels)
    cal = apply_temperature(ens_oof, temp)
    srt = np.sort(cal, axis=1)
    top1_p, top2_p = srt[:, -1], srt[:, -2]
    correct = cal.argmax(1) == labels

    # pick uncertain_top1 so that accuracy among covered predictions >= 0.90
    thr_grid = np.linspace(0.1, 0.8, 71)
    chosen_thr = UNCERTAIN_TOP1
    for thr in thr_grid:
        covered = top1_p >= thr
        if covered.mean() < 0.3:
            break
        if correct[covered].mean() >= 0.90:
            chosen_thr = float(thr)
            break
    covered = top1_p >= chosen_thr
    print(f"temperature {temp:.3f}; uncertain_top1 {chosen_thr:.2f} "
          f"-> coverage {covered.mean():.2%}, covered acc {correct[covered].mean():.3f}")

    # ---------------- rotation recovery test ----------------
    # Legacy diagnostic (rotation_test=False for v3). It compares only the
    # kNN+logreg pair under rotation; gamaka is omitted here since the live
    # pipeline resolves tonic up front (choose_tonic) rather than rotating at
    # classify time. export_w = kNN's share of the 2-way renormalization.
    export_w = w_knn / (w_knn + w_logreg + 1e-12)

    # Simulate a tonic detected a fifth out by rotating test chunks -700
    # cents; the hypothesis rule then has to pick offset +700, which is the
    # rotation that undoes it. Run on a sample of recordings, not all of them.
    def predict_with_offset(chunks, refs_sqrt, ref_lab, lr, off):
        P = np.stack(
            [rotate_pcd(c[0].astype(np.float64), off) for c in chunks]
        ) * PCD_FEAT_SCALE
        S = np.stack([rotate_tdms(c[1].reshape(120, 120).astype(np.float64), off).ravel() for c in chunks])
        k, T = [int(best_knn.split("_")[1][1:]), float(best_knn.split("_T")[1])]
        kp = knn_chunk_probs(S, refs_sqrt, ref_lab, n_classes, k, T)
        pp = lr.predict_proba(P)
        mix = export_w * aggregate_chunks(kp) + (1 - export_w) * aggregate_chunks(pp)
        return apply_temperature(mix / mix.sum(), temp)

    lr_full = LogisticRegression(C=1.0, max_iter=2000).fit(
        pcd_X * PCD_FEAT_SCALE, y
    )
    # per-swara gamaka logreg on ALL data. Fold the z-score (mean/std) into the
    # exported weights so predict_chunk consumes the raw descriptor exactly like
    # the PCD member: W' = W/std, b' = b - W @ (mean/std). Identical logits.
    g_mu = gamaka_X.mean(0)
    g_sd = gamaka_X.std(0) + 1e-9
    glr_full = LogisticRegression(C=1.0, max_iter=3000, class_weight="balanced").fit(
        (gamaka_X - g_mu) / g_sd, y
    )
    gamaka_W = (glr_full.coef_ / g_sd).astype(np.float32)
    gamaka_b = (glr_full.intercept_ - glr_full.coef_ @ (g_mu / g_sd)).astype(np.float32)
    refs_sqrt_all = np.sqrt(np.clip(rec_tdms.astype(np.float64), 0, None))
    rot_recovery = -1.0
    if rotation_test:
        # Legacy diagnostic: the pipeline now resolves tonic BEFORE
        # classification (choose_tonic), so this measures the old in-model
        # rotation rule only. Kept for comparability of v1 numbers.
        sample = RNG.choice(len(mbids), size=60, replace=False)
        recovered = 0
        for ri in tqdm(sample, desc="rotation test"):
            chunks = test_chunks[mbids[ri]]
            if not chunks:
                continue
            # rotate -700 cents, as if the tonic had been detected a fifth out
            corrupted = [(rotate_pcd(c[0].astype(np.float64), -700),
                          rotate_tdms(c[1].reshape(120, 120).astype(np.float64), -700).ravel())
                         for c in chunks]
            per_off = {off: predict_with_offset(corrupted, refs_sqrt_all, labels, lr_full, off)
                       for off in TONIC_ROTATIONS_CENTS}
            chosen = 0
            for off in TONIC_ROTATIONS_CENTS[1:]:
                if per_off[off].max() > per_off[chosen].max() and \
                   per_off[off].max() >= per_off[0].max() + ROTATION_ACCEPT_MARGIN:
                    chosen = off
            if per_off[chosen].argmax() == labels[ri]:
                recovered += 1
        rot_recovery = recovered / len(sample)
        print(f"rotation recovery (fifth-shift, n={len(sample)}): {rot_recovery:.2%}")

    # NOTE: refs for the rotation test and final artifact include the item's
    # own recording (production condition: refs are the full training set).

    # ---------------- export artifact ----------------
    k, T = int(best_knn.split("_")[1][1:]), float(best_knn.split("_T")[1])
    pcd_templates = np.stack([rec_pcd[labels == c].mean(0) for c in range(n_classes)])
    arrays = dict(
        tdms_refs=rec_tdms.astype(np.float16),
        tdms_ref_labels=labels.astype(np.int16),
        # fold the training-time feature scale into W: identical logits on
        # the raw PCDs the artifact consumes
        logreg_W=(lr_full.coef_ * PCD_FEAT_SCALE).astype(np.float32),
        logreg_b=lr_full.intercept_.astype(np.float32),
        pcd_templates=pcd_templates.astype(np.float32),
        # per-swara gamaka member (z-score folded into W/b, see above)
        gamaka_W=gamaka_W,
        gamaka_b=gamaka_b,
    )
    meta = dict(
        classes=classes,
        feature_config_hash=feature_config_hash(),
        knn=dict(k=k, distance="bhattacharyya", temperature=T, weight=float(w_knn)),
        logreg=dict(weight=float(w_logreg), feature="pcd"),
        gamaka=dict(weight=float(w_gamaka), feature="perswara",
                    dim=int(PERSWARA_DIM), version=GAMAKA_VERSION),
        selection_note=(
            f"3-way pure-numpy ensemble: {best_knn} + PCD-logreg + per-swara "
            f"gamaka, weights knn={w_knn:.2f} logreg={w_logreg:.2f} "
            f"gamaka={w_gamaka:.2f} (OOF top1 {best_ens_t1:.3f})"
        ),
        calibration=dict(temperature=float(temp)),
        thresholds=dict(
            uncertain_top1=float(chosen_thr),
            uncertain_margin=UNCERTAIN_MARGIN,
            rotation_margin=ROTATION_ACCEPT_MARGIN,
        ),
        metrics=dict(
            n_recordings=len(mbids),
            n_classes=n_classes,
            oof_scores={n: dict(top1=s[0], top3=s[1]) for n, s in scores.items()},
            # kept out of oof_scores because it is measured on one fold, not
            # out-of-fold across the corpus, and the two must not be read off
            # the same table
            lgbm_control=lgbm_control,
            ensemble=dict(top1=best_ens_t1, top3=topk(ens_oof)),
            # The selected maximum above, and the same quantity with the
            # weights chosen off-fold. Reporting only the first would be
            # the practice this project prices in other people's methods.
            ensemble_nested=dict(
                top1=nested_t1,
                selection_advantage=float(best_ens_t1 - nested_t1),
                note="weights fitted on nine folds, applied once to the "
                     "tenth; `ensemble.top1` is the maximum over the same "
                     "grid read off the folds it is reported on"),
            coverage=float(covered.mean()),
            covered_accuracy=float(correct[covered].mean()),
            rotation_recovery=float(rot_recovery),
            protocol="StratifiedGroupKFold(10) grouped by concert; "
                     "recording-level scores via app-parity 45s-window aggregation",
        ),
    )
    from raagafinder.models.artifact import ModelArtifact

    art = ModelArtifact(arrays=arrays, meta=meta)
    art.save(ARTIFACTS_DIR / out_name)
    np.save(WORK_DIR / f"oof_ensemble_{out_name}.npy", ens_oof)
    # The OOF array's row order is this run's mbid order and nothing else.
    # Consumers used to recover it by iterating the splits file's keys, which
    # worked only by luck: make_splits happened to write keys in index order,
    # so the two agreed and the assumption went unchecked for four models.
    # extend_splits appends new recordings in group order, so for model_v2_6
    # they diverge at row 569 -- every downstream row after that would have
    # been a different recording's probabilities, and the resulting per-slice
    # accuracies would have looked plausible.
    #
    # Written to work/ rather than into the artifact json: the artifact is
    # published, and these identifiers are not.
    (WORK_DIR / f"oof_mbids_{out_name}.json").write_text(
        json.dumps(list(mbids)), encoding="utf-8")
    print("artifact saved:", ARTIFACTS_DIR / out_name)
    return meta


if __name__ == "__main__":
    import sys

    if "--v3" in sys.argv:
        from raagafinder.models.train import load_index_v3

        name = "model_v2_2"
        if "--out" in sys.argv:
            name = sys.argv[sys.argv.index("--out") + 1]
        run(
            index_fn=load_index_v3,
            splits_name=f"splits_{name}.json",
            out_name=name,
            rotation_test=False,
            fast="--fast" in sys.argv,
        )
    elif "--v2" in sys.argv:
        from raagafinder.models.train import load_index_v2

        min_recs = 3
        if "--min-new-class-recs" in sys.argv:
            min_recs = int(sys.argv[sys.argv.index("--min-new-class-recs") + 1])
        name = f"model_v2" if min_recs >= 3 else "model_v2beta"
        run(
            index_fn=lambda: load_index_v2(min_new_class_recs=min_recs),
            splits_name=f"splits_{name}.json",
            out_name=name,
            rotation_test=False,
        )
    else:
        run()
