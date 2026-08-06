"""Pure-numpy model artifact: no pickles, no sklearn at inference time.

Bundle = <name>.npz (arrays) + <name>.json (config/thresholds/metrics).

npz keys (all optional except classes-related ones in json):
    tdms_refs        (N, D)  float16  L1-normalized flattened TDMS references
    tdms_ref_labels  (N,)    int16
    logreg_W         (C, F)  float32  weights over feature vector
    logreg_b         (C,)    float32
    pca_mean         (D,)    float32  PCA over flattened TDMS (optional)
    pca_components   (K, D)  float32
    pcd_templates    (C, B)  float32  mean training PCD per class (for UI)
    gamaka_W         (C, 24) float32  per-swara ornament weights (optional)
    gamaka_b         (C,)    float32

json keys:
    classes            list[str]  index == integer label
    feature_config_hash str       must match config.feature_config_hash()
    knn                {k, distance, temperature, weight}
    logreg             {weight, feature: "pcd" | "pcd+pca_tdms"}
    gamaka             {weight, feature, dim, version}  (optional)
    calibration        {temperature}
    thresholds         {uncertain_top1, uncertain_margin, rotation_margin}
    metrics            free-form training metrics for display
"""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from raagafinder.config import feature_config_hash
from raagafinder.models.aggregate import aggregate_chunks
from raagafinder.models.calibrate import apply_temperature
from raagafinder.models.knn_tdms import knn_probs


@dataclass
class ModelArtifact:
    arrays: dict
    meta: dict
    name: str = ""  # base filename (e.g. "model_v2_4"); pairs the LSTM sidecar

    @classmethod
    def load(cls, base_path: str | Path) -> "ModelArtifact":
        base = Path(base_path)
        npz_path = base.with_suffix(".npz")
        json_path = base.with_suffix(".json")
        meta = json.loads(json_path.read_text(encoding="utf-8"))
        expected = feature_config_hash()
        got = meta.get("feature_config_hash")
        if got != expected:
            raise RuntimeError(
                f"Model artifact feature config hash {got} != code {expected}. "
                "Retrain/re-export the artifact or check out matching code."
            )
        with np.load(npz_path) as z:
            arrays = {k: z[k] for k in z.files}
        return cls(arrays=arrays, meta=meta, name=base.stem)

    def save(self, base_path: str | Path) -> None:
        base = Path(base_path)
        base.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(base.with_suffix(".npz"), **self.arrays)
        base.with_suffix(".json").write_text(
            json.dumps(self.meta, indent=2), encoding="utf-8"
        )

    @property
    def classes(self) -> list[str]:
        return self.meta["classes"]

    # -- component predictors ------------------------------------------------

    def _logreg_features(self, pcd: np.ndarray, tdms_flat: np.ndarray) -> np.ndarray:
        kind = self.meta["logreg"]["feature"]
        if kind == "pcd":
            return pcd
        if kind == "pcd+pca_tdms":
            proj = (tdms_flat - self.arrays["pca_mean"]) @ self.arrays["pca_components"].T
            return np.concatenate([pcd, proj])
        raise ValueError(f"unknown logreg feature spec: {kind}")

    def _logreg_probs(self, feats: np.ndarray) -> np.ndarray:
        z = self.arrays["logreg_W"] @ feats + self.arrays["logreg_b"]
        z -= z.max()
        e = np.exp(z)
        return e / e.sum()

    def _softmax_logits(self, W: np.ndarray, b: np.ndarray, feat: np.ndarray) -> np.ndarray:
        z = W @ feat + b
        z -= z.max()
        e = np.exp(z)
        return e / e.sum()

    def predict_chunk(
        self, pcd: np.ndarray, tdms: np.ndarray, gamaka: np.ndarray | None = None
    ) -> np.ndarray:
        """Uncalibrated ensemble probabilities for one chunk's features.

        gamaka is the per-swara ornament descriptor (raagafinder.features.
        gamaka.compute_gamaka_perswara). When the artifact carries a gamaka
        member, callers should pass it; if omitted the member is skipped (the
        ensemble degrades to kNN+logreg) so older callers keep working.
        """
        n_classes = len(self.classes)
        parts, weights = [], []
        if "tdms_refs" in self.arrays and self.meta.get("knn"):
            knn_cfg = self.meta["knn"]
            p = knn_probs(
                tdms.ravel(),
                self.arrays["tdms_refs"].astype(np.float64),
                self.arrays["tdms_ref_labels"].astype(np.int64),
                n_classes,
                k=knn_cfg["k"],
                distance=knn_cfg["distance"],
                temperature=knn_cfg["temperature"],
            )
            parts.append(p)
            weights.append(knn_cfg["weight"])
        if "logreg_W" in self.arrays and self.meta.get("logreg"):
            p = self._logreg_probs(self._logreg_features(pcd, tdms.ravel()))
            parts.append(p)
            weights.append(self.meta["logreg"]["weight"])
        if (
            gamaka is not None
            and "gamaka_W" in self.arrays
            and self.meta.get("gamaka")
        ):
            from raagafinder.features.gamaka import GAMAKA_VERSION

            stored = self.meta["gamaka"].get("version", GAMAKA_VERSION)
            if stored != GAMAKA_VERSION:
                raise RuntimeError(
                    f"gamaka descriptor version {stored} in artifact != code "
                    f"{GAMAKA_VERSION}; re-export the artifact."
                )
            p = self._softmax_logits(
                self.arrays["gamaka_W"].astype(np.float64),
                self.arrays["gamaka_b"].astype(np.float64),
                np.asarray(gamaka, dtype=np.float64),
            )
            parts.append(p)
            weights.append(self.meta["gamaka"]["weight"])
        if not parts:
            raise RuntimeError("artifact has no usable model components")
        mix = sum(w * p for w, p in zip(weights, parts)) / sum(weights)
        return mix / mix.sum()

    def aggregate_uncalibrated(self, chunk_probs: list[np.ndarray]) -> np.ndarray:
        """Aggregate chunk probs WITHOUT calibration (used for hypothesis
        comparison — temperature sharpening breaks margin rules)."""
        return aggregate_chunks(np.stack(chunk_probs))

    def calibrate(self, probs: np.ndarray) -> np.ndarray:
        return apply_temperature(probs, self.meta["calibration"]["temperature"])

    def predict_recording(self, chunk_probs: list[np.ndarray]) -> np.ndarray:
        """Aggregate chunk probs and apply calibration -> final distribution."""
        return self.calibrate(self.aggregate_uncalibrated(chunk_probs))

    def knn_best_distance(self, tdms_flat: np.ndarray) -> float:
        """Smallest Bhattacharyya distance from a TDMS surface to any
        reference (evidence for tonic-hypothesis selection).

        The distance is ``-log(bc)`` and ``bc`` is a similarity, so the
        nearest reference is the one with the LARGEST ``log(bc)``. Taking
        ``.min()`` of the log first, then negating, returns the farthest
        reference instead -- the unary minus binds after the reduction.
        """
        refs = np.clip(self.arrays["tdms_refs"].astype(np.float64), 0, None)
        bc = np.sqrt(np.clip(tdms_flat, 0, None)) @ np.sqrt(refs).T
        return float(-np.log(np.clip(bc, 1e-12, None)).max())
