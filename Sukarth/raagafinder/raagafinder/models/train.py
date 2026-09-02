"""Baseline: recording-level TDMS + nearest-neighbour over the 480 CMD
recordings, with an ablation grid and three evaluation protocols:

  LOO   leave-one-recording-out (paper-comparable; Gulati 2016 got 87%)
  LOCO  leave-one-concert-out   (nearest ref from a different artist+release)
  LOAO  leave-one-artist-out    (nearest ref from a different artist)

For 1-NN these reduce to masking the pairwise distance matrix, so the whole
grid runs in minutes on CPU. Also freezes work/splits.json (stratified
GroupKFold by concert) for the parametric models.
"""

import itertools
import json

import numpy as np
from sklearn.model_selection import StratifiedGroupKFold
from tqdm import tqdm

from raagafinder.config import NPZ_DIR, WORK_DIR
from raagafinder.features.tdms import compute_tdms

_EPS = 1e-12


def load_index():
    index = json.loads((WORK_DIR / "index.json").read_text(encoding="utf-8"))
    mbids = sorted(index)
    classes = sorted({v["raga"] for v in index.values()})
    labels = np.array([classes.index(index[m]["raga"]) for m in mbids])
    concerts = np.array([index[m]["artist"] + "|" + index[m]["release"] for m in mbids])
    artists = np.array([index[m]["artist"] for m in mbids])
    return index, mbids, classes, labels, concerts, artists


def load_pitch_cache(mbids):
    cache = {}
    prefix_dirs = {
        "saraga_": WORK_DIR / "saraga_npz",
        "private_": WORK_DIR / "private_npz",
        "yt_": WORK_DIR / "newraga_npz",
    }
    for m in tqdm(mbids, desc="load npz"):
        path = NPZ_DIR / f"{m}.npz"
        if not path.exists():
            for prefix, d in prefix_dirs.items():
                if m.startswith(prefix):
                    path = d / f"{m}.npz"
                    break
        with np.load(path) as z:
            folded = np.mod(z["cents"].astype(np.float64), 1200.0)
            cache[m] = (folded, z["voiced"], float(z["hop_s"]))
    return cache


# Saraga spelling variants of ALREADY-COVERED classes (verified against
# work/saraga_index.json 2026-07-23). Merging them is free training data.
# Dhanaśrī and Kalāvati are NOT here: they are distinct ragas, not variant
# spellings (Kalāvati shares Vaḷaji's scale only in its Hindustani sense).
SARAGA_NORM = {
    "Bṛndāvana sāranga": "Brindāvana Sāranga",
    "Cakravākaṁ": "Chakravākaṁ",
    "Dēś": "Desh",
    "Hamsadhvani": "Hamsadhwani",
    "Haṁsānandi": "Hamsanandi",
    "Kathanakutūhalaṁ": "Kadanakutūhalaṁ",
    "Simhēndra madhyamaṁ": "Simhēndramadhyamaṁ",
    "Sārāmati": "Sāramati",
    "Tillāng": "Tilang",
    "Vasanta": "Vasantā",
    "Yamuna kalyāṇi": "Yamunā Kaḷyāṇi",
    # same raga; the corpus spells its sibling "Kēdāragauḷa", so the long
    # e is canonical here. Unmerged, the class sat at 1+2 recordings across
    # two spellings and never reached the 3-recording quota (round 4).
    "Kedāraṁ": "Kēdāraṁ",
    "Śuddadhanyāsi": "Śuddha Dhanyāsi",
    # cut-class spellings normalize too; the quota rule keeps the classes
    # out of the ensemble corpus until they can actually be carried
    "Mānḍu": "Māṇḍ",
    "Śudda sāvēri": "Śuddha Sāvēri",
}


def load_index_v2(min_new_class_recs: int = 3, min_voiced_s: float = 30.0):
    """Combined corpus: CMD 480 + Saraga 1.5 Carnatic (work/saraga_npz).

    Existing classes gain Saraga recordings as extra data; ragas outside the
    v1 set become NEW classes when they have >= min_new_class_recs recordings
    (recordings, not concerts — no per-concert dedup is applied here).
    Returns the same tuple shape as load_index().
    """
    index, mbids, classes, labels, concerts, artists = load_index()
    index = dict(index)  # do not mutate the cached copy
    saraga = json.loads(
        (WORK_DIR / "saraga_index.json").read_text(encoding="utf-8")
    )
    from collections import Counter

    new_counts = Counter(
        SARAGA_NORM.get(v["raga"], v["raga"]) for v in saraga.values()
        if not v["in_model_v1"] and v["voiced_s"] >= min_voiced_s
    )
    new_classes = sorted(
        r for r, c in new_counts.items() if c >= min_new_class_recs
    )
    keep = set(classes) | set(new_classes)
    for rec_id, v in saraga.items():
        raga = SARAGA_NORM.get(v["raga"], v["raga"])
        if raga not in keep or v["voiced_s"] < min_voiced_s:
            continue
        index[rec_id] = dict(
            raga=raga, raga_id="", artist=v["concert"],
            release=v["concert"], track=v["track"],
        )
    mbids = sorted(index)
    classes = sorted({v["raga"] for v in index.values()})
    labels = np.array([classes.index(index[m]["raga"]) for m in mbids])
    concerts = np.array(
        [index[m]["artist"] + "|" + index[m]["release"] for m in mbids]
    )
    artists = np.array([index[m]["artist"] for m in mbids])
    print(f"combined corpus: {len(mbids)} recordings, {len(classes)} classes "
          f"(new: {', '.join(new_classes) or 'none'})")
    return index, mbids, classes, labels, concerts, artists


def load_index_v3(min_new_class_recs: int = 3, min_voiced_s: float = 30.0):
    """v2 corpus + the private solo-voice TRAIN split (the holdout split NEVER
    trains) + YouTube new-raga recordings whose labels were checked by ear
    against the composition (work/newraga_index.json keep=true).

    Groups: each private recording is its own concert group (per song);
    each YouTube video likewise. New classes (beyond v2's) must reach
    min_new_class_recs recordings across the added sources.
    """
    index, mbids, classes, labels, concerts, artists = load_index_v2(
        min_new_class_recs, min_voiced_s
    )
    index = dict(index)
    extra = {}
    priv = json.loads(
        (WORK_DIR / "private_index.json").read_text(encoding="utf-8")
    )
    for rec_id, v in priv.items():
        if v["split"] != "train":
            continue  # holdout is the permanent solo-voice benchmark
        extra[rec_id] = dict(
            raga=v["raga"], raga_id="", artist="private_solo_voice",
            release=rec_id, track=v["key"],
        )
    yt = json.loads(
        (WORK_DIR / "newraga_index.json").read_text(encoding="utf-8")
    )
    for rec_id, v in yt.items():
        if v.get("keep"):
            extra[rec_id] = dict(
                raga=v["raga"], raga_id="", artist="youtube",
                release=rec_id, track=rec_id,
            )
    # Saraga recordings that load_index_v2 dropped (variant spellings of
    # later classes, and tail ragas under the Saraga-only quota) pool with
    # private/YouTube recordings here, so a class can assemble cross-source
    # (e.g. 2 Saraga + 1 verified YouTube).
    saraga = json.loads(
        (WORK_DIR / "saraga_index.json").read_text(encoding="utf-8")
    )
    for rec_id, v in saraga.items():
        raga = SARAGA_NORM.get(v["raga"], v["raga"])
        if rec_id in index or rec_id in extra or v["voiced_s"] < min_voiced_s:
            continue
        extra[rec_id] = dict(
            raga=raga, raga_id="", artist=v["concert"],
            release=v["concert"], track=v["track"],
        )
    from collections import Counter

    new_counts = Counter(
        v["raga"] for v in extra.values() if v["raga"] not in classes
    )
    ok_new = sorted(r for r, c in new_counts.items() if c >= min_new_class_recs)
    dropped = sorted(set(new_counts) - set(ok_new))
    for rec_id, v in extra.items():
        if v["raga"] in classes or v["raga"] in ok_new:
            index[rec_id] = v
    mbids = sorted(index)
    classes = sorted({v["raga"] for v in index.values()})
    labels = np.array([classes.index(index[m]["raga"]) for m in mbids])
    concerts = np.array(
        [index[m]["artist"] + "|" + index[m]["release"] for m in mbids]
    )
    artists = np.array([index[m]["artist"] for m in mbids])
    print(f"v3 corpus: {len(mbids)} recordings, {len(classes)} classes "
          f"(added: {', '.join(ok_new) or 'none'}"
          + (f"; under quota: {', '.join(dropped)}" if dropped else "") + ")")
    return index, mbids, classes, labels, concerts, artists


def load_oof_order(model_name):
    """The recording order of a model's saved out-of-fold probability rows.

    Row i of `oof_ensemble_<model>.npy` is whatever recording was i-th in the
    mbid list of the run that produced it. zoo.run writes that list beside the
    array; anything reading those rows must use it.

    The old way was to iterate the splits file's keys, which agreed with the
    index order only because make_splits wrote them in index order. It stopped
    agreeing the moment folds were extended rather than regenerated, and the
    failure is silent: misindexed rows still produce a confusion matrix.

    Returns None for models fit before the order was recorded, so callers can
    fall back deliberately rather than by accident.
    """
    p = WORK_DIR / f"oof_mbids_{model_name}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def make_splits(mbids, labels, concerts, artists, n_splits=10, seed=42,
                out_name="splits.json", absorb_probe=False):
    """Frozen fold assignments for the parametric models.

    The fresh-YouTube probe recordings are refused a fold unless
    ``absorb_probe`` says otherwise. extend_splits.py has guarded against
    absorbing them since the probe existed, but a from-scratch resplit ran
    through this function and took all 67 silently -- that is how they
    reached the v28 corpus. The guard belongs at the point where fold
    assignment happens, not only in one of the two scripts that trigger it.
    """
    from raagafinder.models.youtube_probe import YOUTUBE_PROBE

    if not absorb_probe:
        probe = set(YOUTUBE_PROBE)
        held = [m for m in mbids if m in probe]
        if held:
            keep = [i for i, m in enumerate(mbids) if m not in probe]
            mbids = [mbids[i] for i in keep]
            labels = np.asarray(labels)[keep]
            concerts = [concerts[i] for i in keep]
            artists = [artists[i] for i in keep]
            print(f"make_splits: refusing a fold to {len(held)} fresh-"
                  f"YouTube probe recording(s); pass absorb_probe=True to "
                  f"end the source-gap measurement deliberately")
    out = {"seed": seed, "n_splits": n_splits}
    sgkf = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    concert_folds = np.full(len(mbids), -1)
    for f, (_, test) in enumerate(sgkf.split(np.zeros(len(mbids)), labels, concerts)):
        concert_folds[test] = f
    out["concert_fold"] = {m: int(f) for m, f in zip(mbids, concert_folds)}
    try:
        artist_folds = np.full(len(mbids), -1)
        for f, (_, test) in enumerate(
            sgkf.split(np.zeros(len(mbids)), labels, artists)
        ):
            artist_folds[test] = f
        out["artist_fold"] = {m: int(f) for m, f in zip(mbids, artist_folds)}
    except ValueError as exc:
        out["artist_fold_error"] = str(exc)
    (WORK_DIR / out_name).write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


# -- pairwise distances ------------------------------------------------------


def pairwise_bhattacharyya(P):
    S = np.sqrt(np.clip(P, 0, None))
    return -np.log(np.clip(S @ S.T, _EPS, None))


def pairwise_symkl(P):
    Pc = np.clip(P, _EPS, None)
    L = np.log(Pc)
    A = (Pc * L).sum(1)
    return A[:, None] + A[None, :] - Pc @ L.T - L @ Pc.T


def pairwise_euclidean(P):
    sq = (P * P).sum(1)
    d2 = np.clip(sq[:, None] + sq[None, :] - 2 * (P @ P.T), 0, None)
    return np.sqrt(d2)


PAIRWISE = {
    "bhattacharyya": pairwise_bhattacharyya,
    "symmetric_kl": pairwise_symkl,
    "euclidean": pairwise_euclidean,
}


# -- evaluation --------------------------------------------------------------


def evaluate_nn(D, labels, forbid_same):
    """1-NN top-1 and class-rank top-3 with a boolean 'forbidden neighbour'
    matrix (True = may not be used as reference for this query)."""
    D = D.copy()
    D[forbid_same] = np.inf
    nn = D.argmin(1)
    top1 = float((labels[nn] == labels).mean())

    n_classes = labels.max() + 1
    top3_hits = 0
    for i in range(len(labels)):
        class_min = np.full(n_classes, np.inf)
        np.minimum.at(class_min, labels, D[i])
        top3 = np.argsort(class_min)[:3]
        top3_hits += labels[i] in top3
    return top1, top3_hits / len(labels)


def run_baseline(grid=None):
    index, mbids, classes, labels, concerts, artists = load_index()
    make_splits(mbids, labels, concerts, artists)
    cache = load_pitch_cache(mbids)

    same_rec = np.eye(len(mbids), dtype=bool)
    same_concert = concerts[:, None] == concerts[None, :]
    same_artist = artists[:, None] == artists[None, :]

    grid = grid or dict(
        tau=[0.2, 0.3, 0.5], alpha=[0.5, 0.75], sigma=[1.0, 2.0],
        distance=["bhattacharyya", "symmetric_kl", "euclidean"],
    )
    results = []
    combos = list(itertools.product(grid["tau"], grid["alpha"], grid["sigma"]))
    for tau, alpha, sigma in tqdm(combos, desc="ablation"):
        P = np.stack([
            compute_tdms(f, m, hop, tau_s=tau, alpha=alpha, sigma_bins=sigma).ravel()
            for f, m, hop in (cache[mb] for mb in mbids)
        ])
        for dist in grid["distance"]:
            D = PAIRWISE[dist](P)
            row = dict(tau=tau, alpha=alpha, sigma=sigma, distance=dist)
            row["loo_top1"], row["loo_top3"] = evaluate_nn(D, labels, same_rec)
            row["loco_top1"], row["loco_top3"] = evaluate_nn(D, labels, same_concert)
            row["loao_top1"], row["loao_top3"] = evaluate_nn(D, labels, same_artist)
            results.append(row)

    results.sort(key=lambda r: -r["loco_top1"])
    (WORK_DIR / "baseline_results.json").write_text(
        json.dumps(dict(classes=classes, results=results), indent=1), encoding="utf-8"
    )
    return results


if __name__ == "__main__":
    res = run_baseline()
    print(f"{'tau':>4} {'alpha':>5} {'sig':>4} {'distance':>14} | "
          f"{'LOO t1':>6} {'t3':>5} | {'LOCO t1':>7} {'t3':>5} | {'LOAO t1':>7} {'t3':>5}")
    for r in res[:12]:
        print(f"{r['tau']:>4} {r['alpha']:>5} {r['sigma']:>4} {r['distance']:>14} | "
              f"{r['loo_top1']:.3f}  {r['loo_top3']:.3f} | {r['loco_top1']:.3f}   "
              f"{r['loco_top3']:.3f} | {r['loao_top1']:.3f}   {r['loao_top3']:.3f}")
