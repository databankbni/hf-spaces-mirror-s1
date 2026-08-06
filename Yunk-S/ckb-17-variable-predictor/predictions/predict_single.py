"""
Single-person inference for the frozen CKB 17-variable model package.

The package has two separate layers:

1. The cluster label is produced by the frozen CKB nearest-centroid model.
   Its SHAP files explain a multiclass random-forest surrogate trained to
   reproduce deployed C1/C2/C3 labels; they do not change the cluster label.
2. Each incident outcome is predicted by the selected first-stage classifier.
   The outcome SHAP files explain the corresponding second-stage regression
   surrogate for that classifier's probability score.  The classifier's
   probability and the surrogate score are therefore reported separately.

The command-line entry point is intentionally small, but the same file can
be imported as a library:

    from predict_single import predict_one

    result = predict_one({
        "sex": 1, "age": 55, "edu_level": 2,
        "marital_status": 1, "work": 1, "retire": 0,
        "hh_size": 3, "smoking": 0, "alcohol": 1,
        "height_cm": 165, "weight_kg": 65, "waist_cm": 82,
        "sbp_mmhg": 125, "dbp_mmhg": 78, "bp_drugs": 0,
        "self_health": 2, "chronic_pain": 0,
    })

The outcome high-risk flag is defined as probability >= the frozen full-CKB
Youden threshold recorded in manifest.json.  No missing-value imputation,
re-standardisation, feature selection, or cohort-specific refitting is done.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import warnings
from pathlib import Path
from typing import Any, Mapping

import joblib
import numpy as np
import pandas as pd
import shap


PACKAGE_ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = PACKAGE_ROOT / "manifest.json"


def _json_default(value: Any) -> Any:
    """Convert common NumPy/path values into JSON-safe values."""
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


class CKBSingleSamplePredictor:
    """Load the packaged models and make one complete-case prediction."""

    def __init__(self, package_root: str | Path | None = None) -> None:
        self.package_root = Path(package_root or PACKAGE_ROOT).resolve()
        self.manifest = _read_json(self.package_root / "manifest.json")
        self.features = list(self.manifest["features"])
        self.feature_labels = dict(self.manifest.get("feature_labels", {}))
        self.outcome_meta = dict(self.manifest["outcomes"])

        cluster_dir = self.package_root / "cluster"
        with np.load(cluster_dir / "frozen_model.npz", allow_pickle=True) as data:
            self.cluster_centers = np.asarray(data["centers"], dtype=np.float64)
            self.cluster_mu = np.asarray(data["mu"], dtype=np.float64)
            self.cluster_sigma = np.asarray(data["sigma"], dtype=np.float64)
            self.cluster_log_applied = np.asarray(data["log_applied"], dtype=bool)
            frozen_features = [str(x) for x in data["features"].tolist()]
            self.cluster_k = int(np.asarray(data["K"]).ravel()[0])

        if frozen_features != self.features:
            raise ValueError(
                "The frozen cluster feature order does not match manifest.json: "
                f"{frozen_features} != {self.features}"
            )
        if self.cluster_centers.shape != (self.cluster_k, len(self.features)):
            raise ValueError("Unexpected frozen cluster-centre shape")

        self.cluster_thresholds = _read_json(cluster_dir / "ood_thresholds.json")
        calibration_path = cluster_dir / "calibration_model.npz"
        self.cluster_calibration = None
        if calibration_path.exists():
            with np.load(calibration_path, allow_pickle=True) as data:
                self.cluster_calibration = {
                    "coef": np.asarray(data["coef"], dtype=np.float64),
                    "intercept": np.asarray(data["intercept"], dtype=np.float64),
                    "d_std": float(np.asarray(data["d_std"]).ravel()[0]),
                }

        self._cluster_shap_model = None
        self._cluster_shap_explainer = None
        self._outcome_cache: dict[str, dict[str, Any]] = {}

    def _validate_input(self, values: Mapping[str, Any]) -> tuple[pd.DataFrame, list[str]]:
        if not isinstance(values, Mapping):
            raise TypeError("Input must be a mapping with the 17 required feature names")

        missing = [feature for feature in self.features if feature not in values]
        if missing:
            raise ValueError(f"Missing required input variables: {missing}")

        ignored = sorted(set(values) - set(self.features))
        frame = pd.DataFrame([{feature: values[feature] for feature in self.features}])
        for feature in self.features:
            frame[feature] = pd.to_numeric(frame[feature], errors="coerce")
        if frame.isna().any(axis=None):
            bad = frame.columns[frame.isna().any()].tolist()
            raise ValueError(f"All 17 variables must be finite numeric values; invalid: {bad}")
        array = frame.to_numpy(dtype=np.float64)
        if not np.isfinite(array).all():
            raise ValueError("All 17 variables must be finite numeric values")

        log_features = [
            feature for feature, use_log in zip(self.features, self.cluster_log_applied)
            if use_log
        ]
        negative_log = [feature for feature in log_features if float(frame.iloc[0][feature]) < 0]
        if negative_log:
            raise ValueError(
                "The following variables are log1p-transformed by the frozen cluster "
                f"model and cannot be negative: {negative_log}"
            )
        return frame, ignored

    def _cluster_preprocess(self, frame: pd.DataFrame) -> np.ndarray:
        raw = frame[self.features].to_numpy(dtype=np.float64, copy=True)
        for index, use_log in enumerate(self.cluster_log_applied):
            if use_log:
                # This is the locked external-assignment rule from the CKB
                # validation code. Input validation above prevents negatives.
                raw[:, index] = np.log1p(np.maximum(raw[:, index], 0.0))
        denominator = np.where(self.cluster_sigma > 1e-8, self.cluster_sigma, 1.0)
        return (raw - self.cluster_mu) / denominator

    def _cluster_confidence(self, distances: np.ndarray) -> np.ndarray:
        calibration = self.cluster_calibration
        if calibration is None:
            return np.full(distances.shape[0], np.nan, dtype=np.float64)
        centered = distances - distances.min(axis=1, keepdims=True)
        centered = np.clip(centered / (calibration["d_std"] + 1e-8), -10, 10)
        logits = centered @ calibration["coef"].T + calibration["intercept"]
        logits -= logits.max(axis=1, keepdims=True)
        probabilities = np.exp(logits)
        probabilities /= probabilities.sum(axis=1, keepdims=True)
        return probabilities.max(axis=1)

    def _predict_cluster(self, frame: pd.DataFrame) -> dict[str, Any]:
        z = self._cluster_preprocess(frame)
        distances = np.linalg.norm(
            z[:, None, :] - self.cluster_centers[None, :, :], axis=2
        )
        nearest = distances.argmin(axis=1).astype(int)
        ordered = np.sort(distances, axis=1)
        d1 = ordered[:, 0]
        d2 = ordered[:, 1]
        margin = np.where(d2 > 0, (d2 - d1) / d2, 1.0)
        confidence = self._cluster_confidence(distances)

        index = int(nearest[0])
        nearest_distance = float(d1[0])
        second_distance = float(d2[0])
        nearest_margin = float(margin[0])
        nearest_confidence = _safe_float(confidence[0])

        ood = int(nearest_distance > float(self.cluster_thresholds["p99_9_overall"]))
        per_cluster = self.cluster_thresholds.get("p99_5_per_cluster", {})
        uncertain = int(
            nearest_distance > float(per_cluster.get(str(index), np.inf))
            or nearest_margin < float(self.cluster_thresholds["margin_p5"])
        )
        confidence_p10 = self.cluster_thresholds.get("confidence_p10")
        low_conf = int(
            (confidence_p10 is not None and nearest_confidence is not None
             and nearest_confidence < float(confidence_p10))
            or nearest_margin < float(self.cluster_thresholds["margin_p5"])
        )

        if ood:
            status = "unclassified_ood"
        elif uncertain:
            status = "uncertain"
        else:
            status = "assigned"
        label = f"C{index + 1}"

        result = {
            # provisional_cluster_label is always available; cluster_label is
            # only definitive when the frozen protocol calls it assigned.
            "provisional_cluster_label": label,
            "cluster_label": label if status == "assigned" else None,
            "cluster_index": index,
            "classification_status": status,
            "distance_nearest": nearest_distance,
            "distance_second": second_distance,
            "margin": nearest_margin,
            "calibrated_confidence": nearest_confidence,
            "ood_flag": bool(ood),
            "uncertain_flag": bool(uncertain),
            "low_confidence_flag": bool(low_conf),
        }

        self._ensure_cluster_shap()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            surrogate_probability = self._cluster_shap_model.predict_proba(
                frame.to_numpy(dtype=np.float64)
            )[0]
        result["shap_surrogate_cluster_probability"] = {
            f"C{int(class_index) + 1}": float(probability)
            for class_index, probability in zip(
                self._cluster_shap_model.classes_, surrogate_probability
            )
        }
        return result

    def _ensure_cluster_shap(self) -> None:
        if self._cluster_shap_model is not None:
            return
        cluster_dir = self.package_root / "cluster"
        self._cluster_shap_model = joblib.load(
            cluster_dir / "cluster_shap_surrogate_random_forest.joblib"
        )
        self._cluster_shap_explainer = shap.TreeExplainer(self._cluster_shap_model)

    @staticmethod
    def _normalise_cluster_shap_values(
        values: Any, n_classes: int, n_features: int
    ) -> np.ndarray:
        """Return an array with shape (class, sample, feature)."""
        if isinstance(values, list):
            arrays = [np.asarray(item, dtype=np.float64) for item in values]
            return np.stack(arrays, axis=0)
        array = np.asarray(values, dtype=np.float64)
        if array.ndim == 2:
            return array[None, :, :]
        if array.ndim != 3:
            raise ValueError(f"Unexpected multiclass SHAP shape: {array.shape}")
        if array.shape[0] == 1 and array.shape[1] == n_features:
            return np.transpose(array, (2, 0, 1))
        if array.shape[0] == n_classes and array.shape[2] == n_features:
            return array
        if array.shape[0] == n_classes and array.shape[1] == n_features:
            return array
        raise ValueError(f"Could not normalise multiclass SHAP shape: {array.shape}")

    def _cluster_force_plots(
        self, frame: pd.DataFrame, output_dir: Path
    ) -> dict[str, str]:
        self._ensure_cluster_shap()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            raw_values = self._cluster_shap_explainer.shap_values(
                frame.to_numpy(dtype=np.float64)
            )
        n_classes = len(self._cluster_shap_model.classes_)
        values = self._normalise_cluster_shap_values(
            raw_values, n_classes=n_classes, n_features=len(self.features)
        )
        expected = np.asarray(self._cluster_shap_explainer.expected_value, dtype=float).reshape(-1)
        plot_paths: dict[str, str] = {}
        feature_values = frame.iloc[0].to_numpy(dtype=np.float64)
        for class_position, class_index in enumerate(self._cluster_shap_model.classes_):
            class_label = f"C{int(class_index) + 1}"
            path = output_dir / f"single_sample_cluster_{class_label}_force.html"
            force = shap.force_plot(
                float(expected[class_position]),
                values[class_position, 0, :],
                feature_values,
                feature_names=[self.feature_labels.get(f, f) for f in self.features],
                matplotlib=False,
            )
            shap.save_html(str(path), force)
            plot_paths[class_label] = str(path)
        return plot_paths

    def _load_outcome_bundle(self, outcome: str) -> dict[str, Any]:
        if outcome in self._outcome_cache:
            return self._outcome_cache[outcome]
        meta = self.outcome_meta[outcome]
        outcome_dir = self.package_root / "outcomes" / outcome
        bundle = {
            "classifier": joblib.load(outcome_dir / meta["classifier_file"]),
            "shap_surrogate": joblib.load(outcome_dir / meta["shap_surrogate_file"]),
        }
        self._outcome_cache[outcome] = bundle
        return bundle

    def _outcome_force_plot(
        self,
        outcome: str,
        frame: pd.DataFrame,
        bundle: dict[str, Any],
        output_dir: Path,
    ) -> tuple[str, float]:
        # The bundled explanation pickles were created on a different Python
        # runtime. In particular, PermutationExplainer serialises a Numba
        # dispatcher whose bytecode is not portable between Python versions.
        # Rebuild the explainer in the active runtime from the frozen surrogate
        # and its stored background sample instead of invoking that dispatcher.
        # The prediction-only API still never pays this cost.
        if "shap_explainer" not in bundle:
            meta = self.outcome_meta[outcome]
            outcome_dir = self.package_root / "outcomes" / outcome
            surrogate = bundle["shap_surrogate"]
            if hasattr(surrogate, "estimators_"):
                # Tree SHAP is deterministic for the frozen RandomForest
                # surrogates and avoids another cross-version pickle edge case.
                bundle["shap_explainer"] = shap.TreeExplainer(surrogate)
            else:
                stored_explainer = joblib.load(
                    outcome_dir / meta["shap_explainer_file"]
                )
                background = getattr(
                    getattr(stored_explainer, "masker", None), "data", None
                )
                if background is None:
                    raise RuntimeError(
                        f"Missing SHAP background sample for outcome {outcome}."
                    )
                bundle["shap_explainer"] = shap.PermutationExplainer(
                    surrogate.predict,
                    np.asarray(background, dtype=np.float64),
                )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            explanation = bundle["shap_explainer"](
                frame.to_numpy(dtype=np.float64)
            )
        values = np.asarray(explanation.values, dtype=np.float64)
        if values.ndim == 3:
            # The outcome SHAP artifacts are univariate. This branch makes a
            # malformed or future artifact fail loudly rather than silently
            # choosing an arbitrary class.
            if values.shape[-1] != 1:
                raise ValueError(f"Unexpected SHAP output shape for {outcome}: {values.shape}")
            values = values[:, :, 0]
        base_values = np.asarray(explanation.base_values, dtype=np.float64).reshape(-1)
        if values.shape != (1, len(self.features)) or base_values.size < 1:
            raise ValueError(
                f"Unexpected SHAP explanation shape for {outcome}: "
                f"values={values.shape}, base={base_values.shape}"
            )
        surrogate_score = float(bundle["shap_surrogate"].predict(frame)[0])
        path = output_dir / f"single_sample_{outcome}_force.html"
        force = shap.force_plot(
            float(base_values[0]),
            values[0],
            frame.iloc[0].to_numpy(dtype=np.float64),
            feature_names=[self.feature_labels.get(f, f) for f in self.features],
            matplotlib=False,
        )
        shap.save_html(str(path), force)
        return str(path), surrogate_score

    def predict_one(
        self,
        values: Mapping[str, Any],
        output_dir: str | Path | None = None,
        make_force_plots: bool = True,
        sample_id: str | None = None,
    ) -> dict[str, Any]:
        """Predict the cluster and all 13 outcomes for one complete case.

        Parameters
        ----------
        values:
            Mapping containing the 17 required variables. Extra keys are
            ignored and reported in ``input.ignored_fields``.
        output_dir:
            Directory for JSON and HTML force plots. If omitted, a timestamped
            folder is created under ``1-output/model/predictions``.
        make_force_plots:
            Save one HTML force plot for each cluster class and outcome when
            true. Setting false only skips plots; prediction probabilities and
            labels are unchanged.
        sample_id:
            Optional identifier written to the result JSON. It is never used
            as a model feature.
        """
        frame, ignored = self._validate_input(values)
        if output_dir is None:
            stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.package_root / "predictions" / stamp
        else:
            output_path = Path(output_dir).expanduser().resolve()
        output_path.mkdir(parents=True, exist_ok=True)
        force_dir = output_path / "force_plots"
        if make_force_plots:
            force_dir.mkdir(parents=True, exist_ok=True)

        result: dict[str, Any] = {
            "package_version": self.manifest.get("package_version"),
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "sample_id": sample_id,
            "input": {
                "features": {
                    feature: float(frame.iloc[0][feature]) for feature in self.features
                },
                "ignored_fields": ignored,
            },
            "cluster": self._predict_cluster(frame),
            "outcomes": {},
            "force_plots": {},
            "notes": [
                "The definitive cluster is the frozen nearest-centroid assignment.",
                "Cluster SHAP explains a multiclass RF surrogate of deployed cluster labels.",
                "Outcome SHAP explains a regression surrogate of the selected classifier probability.",
                "High risk is probability >= the frozen full-CKB Youden threshold.",
            ],
        }

        if make_force_plots:
            result["force_plots"]["cluster"] = self._cluster_force_plots(frame, force_dir)

        X = frame.to_numpy(dtype=np.float64)
        for outcome, meta in self.outcome_meta.items():
            bundle = self._load_outcome_bundle(outcome)
            classifier = bundle["classifier"]
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                probabilities = np.asarray(classifier.predict_proba(X), dtype=np.float64)
            classes = np.asarray(getattr(classifier, "classes_", [0, 1]))
            positive = np.where(classes == 1)[0]
            if positive.size != 1:
                raise ValueError(f"Outcome {outcome} does not have a unique positive class")
            probability = float(probabilities[0, int(positive[0])])
            threshold = float(meta["youden_threshold"])
            risk = "high_risk" if probability >= threshold else "low_risk"

            row: dict[str, Any] = {
                "outcome": meta.get("display_name", outcome),
                "model": meta["model"],
                "probability": probability,
                "youden_threshold": threshold,
                "risk_class": risk,
                "threshold_rule": "high_risk if probability >= Youden threshold",
                "shap_explanation_target": "selected_classifier_probability_surrogate",
            }
            if make_force_plots:
                path, surrogate_score = self._outcome_force_plot(
                    outcome, frame, bundle, force_dir
                )
                row["shap_surrogate_score"] = surrogate_score
                result["force_plots"][outcome] = path
            else:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    row["shap_surrogate_score"] = float(
                        bundle["shap_surrogate"].predict(frame)[0]
                    )
            result["outcomes"][outcome] = row

        result_path = output_path / "single_sample_prediction.json"
        result["result_json"] = str(result_path)
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8",
        )
        return result


def predict_one(
    values: Mapping[str, Any],
    package_dir: str | Path | None = None,
    output_dir: str | Path | None = None,
    make_force_plots: bool = True,
    sample_id: str | None = None,
) -> dict[str, Any]:
    """Convenience wrapper around :class:`CKBSingleSamplePredictor`."""
    predictor = CKBSingleSamplePredictor(package_dir)
    return predictor.predict_one(
        values,
        output_dir=output_dir,
        make_force_plots=make_force_plots,
        sample_id=sample_id,
    )


def _load_input_json(path: Path) -> tuple[dict[str, Any], str | None]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Input JSON must contain an object")
    sample_id = data.get("sample_id")
    if isinstance(data.get("features"), dict):
        data = data["features"]
    return data, str(sample_id) if sample_id is not None else None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run CKB frozen cluster and 13-outcome single-sample inference."
    )
    parser.add_argument(
        "--input-json", required=True, type=Path,
        help="JSON object containing the 17 variables; example_input.json is provided.",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=None,
        help="Output folder; default is a timestamped folder under predictions/.",
    )
    parser.add_argument(
        "--sample-id", default=None,
        help="Optional identifier; it is written to output but not used for prediction.",
    )
    parser.add_argument(
        "--no-force-plots", action="store_true",
        help="Skip HTML force plots while retaining predictions and SHAP surrogate scores.",
    )
    args = parser.parse_args()
    values, input_sample_id = _load_input_json(args.input_json)
    sample_id = args.sample_id if args.sample_id is not None else input_sample_id
    result = predict_one(
        values,
        output_dir=args.output_dir,
        make_force_plots=not args.no_force_plots,
        sample_id=sample_id,
    )
    print(json.dumps({
        "result_json": result["result_json"],
        "cluster": result["cluster"],
        "outcomes": result["outcomes"],
        "force_plots": result["force_plots"],
    }, ensure_ascii=False, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
