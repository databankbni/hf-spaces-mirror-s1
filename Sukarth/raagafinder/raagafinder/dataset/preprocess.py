"""Stream-parse every Carnatic recording from the zip into work/npz/.

Each work/npz/<mbid>.npz stores:
    cents   float32  unfolded cents relative to tonicFine (NaN where unvoiced)
    voiced  bool     voicing mask
    hop_s   float64  scalar
    tonic_hz float64 scalar
plus work/index.json with per-recording metadata (raga, artist, release,
voiced stats, tonic sanity) for the training harness.

Tonic sanity check: the folded pitch histogram must have a peak within +-35
cents of 0 (Sa). Failures are flagged, not silently trained on.
"""

import json

import numpy as np
from tqdm import tqdm

from raagafinder.config import NPZ_DIR, WORK_DIR
from raagafinder.dataset.loader import RagaDatasetLoader
from raagafinder.features.pcd import compute_pcd
from raagafinder.features.pitch_utils import fold_octave, hz_to_cents, voiced_mask


def tonic_sanity(folded: np.ndarray) -> tuple[bool, float]:
    """(ok, offset_cents_of_max_peak_near_sa). Peak within +-35c of 0?"""
    pcd = compute_pcd(folded, n_bins=240, sigma_bins=2.4)
    # local max in the +-35 cent neighborhood of Sa (bins are 5 cents)
    neigh = np.r_[pcd[-7:], pcd[:8]]  # -35..+35 cents inclusive
    peak_local = neigh.max()
    ok = peak_local >= 0.6 * pcd.max() and peak_local > 1.5 / len(pcd)
    offset = (int(np.argmax(neigh)) - 7) * 5.0
    return bool(ok), float(offset)


def run() -> dict:
    NPZ_DIR.mkdir(parents=True, exist_ok=True)
    loader = RagaDatasetLoader()
    index = {}
    for rec in tqdm(loader.recordings, desc="preprocess"):
        f0, hop = loader.read_pitch(rec)
        tonic = loader.read_tonic(rec)
        cents = hz_to_cents(f0, tonic)
        mask = voiced_mask(f0)
        folded = fold_octave(cents[mask])
        ok, sa_offset = tonic_sanity(folded)
        np.savez_compressed(
            NPZ_DIR / f"{rec.mbid}.npz",
            cents=cents.astype(np.float32),
            voiced=mask,
            hop_s=np.float64(hop),
            tonic_hz=np.float64(tonic),
        )
        index[rec.mbid] = dict(
            raga=rec.raga_name,
            raga_id=rec.raga_id,
            artist=rec.artist,
            release=rec.release,
            track=rec.track,
            hop_s=hop,
            tonic_hz=tonic,
            n_frames=int(len(f0)),
            voiced_s=float(mask.sum() * hop),
            voiced_ratio=float(mask.mean()),
            tonic_ok=ok,
            sa_peak_offset_cents=sa_offset,
        )
    (WORK_DIR / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return index


if __name__ == "__main__":
    idx = run()
    n = len(idx)
    bad = [m for m, v in idx.items() if not v["tonic_ok"]]
    total_voiced_h = sum(v["voiced_s"] for v in idx.values()) / 3600
    print(f"recordings: {n}, voiced hours: {total_voiced_h:.1f}")
    print(f"tonic sanity failures: {len(bad)}")
    for m in bad[:10]:
        v = idx[m]
        print("  ", v["raga"], v["artist"], v["track"], "offset:", v["sa_peak_offset_cents"])
