"""Small, interpretable calibration model for retrieval-risk signals.

The model is deliberately independent from runtime routing.  Training produces
a versioned JSON artifact; adopting that artifact in the serving gate requires
a separate evaluation and architecture decision.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Iterable

from .confidence import GateSignals

FEATURE_NAMES = (
    "top1_rerank",
    "top1_missing",
    "top1_top2_margin",
    "margin_missing",
    "bm25_dense_overlap_count",
    "bm25_dense_overlap_jaccard",
    "required_article_coverage",
    "has_required_articles",
    "graph_added_required_article",
    "ambiguous_or_multi_hop",
    "evidence_requirement_coverage",
    "has_evidence_requirements",
)


def extract_gate_features(signals: GateSignals | dict) -> dict[str, float]:
    data = signals.to_dict() if isinstance(signals, GateSignals) else signals
    required = data.get("required_articles") or []
    required_coverage = data.get("required_article_coverage")
    evidence_coverage = data.get("evidence_requirement_coverage")
    return {
        "top1_rerank": float(data.get("top1_rerank") or 0.0),
        "top1_missing": float(data.get("top1_rerank") is None),
        "top1_top2_margin": float(data.get("top1_top2_margin") or 0.0),
        "margin_missing": float(data.get("top1_top2_margin") is None),
        "bm25_dense_overlap_count": float(
            data.get("bm25_dense_overlap_count") or 0
        ),
        "bm25_dense_overlap_jaccard": float(
            data.get("bm25_dense_overlap_jaccard") or 0.0
        ),
        "required_article_coverage": float(
            1.0 if required_coverage is None else required_coverage
        ),
        "has_required_articles": float(bool(required)),
        "graph_added_required_article": float(
            bool(data.get("graph_added_required_article"))
        ),
        "ambiguous_or_multi_hop": float(
            bool(data.get("ambiguous_or_multi_hop"))
        ),
        "evidence_requirement_coverage": float(
            1.0 if evidence_coverage is None else evidence_coverage
        ),
        "has_evidence_requirements": float(evidence_coverage is not None),
    }


def _sigmoid(value: float) -> float:
    if value >= 0:
        exponent = math.exp(-value)
        return 1 / (1 + exponent)
    exponent = math.exp(value)
    return exponent / (1 + exponent)


@dataclass(frozen=True)
class LinearGateModel:
    """Standardized logistic model predicting ``needs_correction`` risk."""

    intercept: float
    coefficients: dict[str, float]
    feature_means: dict[str, float]
    feature_scales: dict[str, float]
    training_count: int
    positive_count: int
    model_version: str
    created_at: str

    def predict_risk(self, features: GateSignals | dict[str, float]) -> float:
        values = (
            extract_gate_features(features)
            if isinstance(features, GateSignals)
            or "top1_missing" not in features
            else features
        )
        score = self.intercept
        for name in FEATURE_NAMES:
            standardized = (
                float(values.get(name, 0.0)) - self.feature_means[name]
            ) / self.feature_scales[name]
            score += self.coefficients[name] * standardized
        return _sigmoid(score)

    def to_dict(self) -> dict:
        return {
            "schema_version": "linear-gate-model-v1",
            **asdict(self),
            "feature_names": list(FEATURE_NAMES),
            "target": "needs_correction",
            "adoption_state": "offline_candidate",
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LinearGateModel":
        return cls(
            intercept=float(data["intercept"]),
            coefficients={
                name: float(data["coefficients"][name]) for name in FEATURE_NAMES
            },
            feature_means={
                name: float(data["feature_means"][name]) for name in FEATURE_NAMES
            },
            feature_scales={
                name: float(data["feature_scales"][name]) for name in FEATURE_NAMES
            },
            training_count=int(data["training_count"]),
            positive_count=int(data["positive_count"]),
            model_version=str(data["model_version"]),
            created_at=str(data["created_at"]),
        )


def train_linear_gate_model(
    rows: Iterable[tuple[dict[str, float], bool]],
    *,
    epochs: int = 2_000,
    learning_rate: float = 0.05,
    l2: float = 0.01,
    model_version: str = "linear-gate-calibration-v1",
) -> LinearGateModel:
    """Fit a deterministic standardized logistic model with batch descent."""
    materialized = list(rows)
    if len(materialized) < 40:
        raise ValueError("at least 40 independently labelled rows are required")
    labels = [int(label) for _, label in materialized]
    if len(set(labels)) < 2:
        raise ValueError("training labels must contain both classes")
    matrix = [
        [float(features.get(name, 0.0)) for name in FEATURE_NAMES]
        for features, _ in materialized
    ]
    count = len(matrix)
    means = {
        name: sum(row[index] for row in matrix) / count
        for index, name in enumerate(FEATURE_NAMES)
    }
    scales: dict[str, float] = {}
    for index, name in enumerate(FEATURE_NAMES):
        variance = sum(
            (row[index] - means[name]) ** 2 for row in matrix
        ) / count
        scales[name] = max(math.sqrt(variance), 1e-6)
    standardized = [
        [
            (row[index] - means[name]) / scales[name]
            for index, name in enumerate(FEATURE_NAMES)
        ]
        for row in matrix
    ]
    weights = [0.0] * len(FEATURE_NAMES)
    prevalence = min(max(sum(labels) / count, 1e-6), 1 - 1e-6)
    intercept = math.log(prevalence / (1 - prevalence))

    for _ in range(epochs):
        predictions = [
            _sigmoid(
                intercept
                + sum(weight * value for weight, value in zip(weights, row))
            )
            for row in standardized
        ]
        errors = [
            prediction - label
            for prediction, label in zip(predictions, labels)
        ]
        intercept -= learning_rate * sum(errors) / count
        for index in range(len(weights)):
            gradient = (
                sum(error * row[index] for error, row in zip(errors, standardized))
                / count
                + l2 * weights[index]
            )
            weights[index] -= learning_rate * gradient

    return LinearGateModel(
        intercept=intercept,
        coefficients=dict(zip(FEATURE_NAMES, weights)),
        feature_means=means,
        feature_scales=scales,
        training_count=count,
        positive_count=sum(labels),
        model_version=model_version,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


def evaluate_gate_model(
    model: LinearGateModel,
    rows: Iterable[tuple[dict[str, float], bool]],
    *,
    threshold: float = 0.5,
) -> dict:
    pairs = [
        (model.predict_risk(features), bool(label)) for features, label in rows
    ]
    if not pairs:
        raise ValueError("evaluation rows are empty")
    tp = sum(score >= threshold and label for score, label in pairs)
    fp = sum(score >= threshold and not label for score, label in pairs)
    fn = sum(score < threshold and label for score, label in pairs)
    tn = sum(score < threshold and not label for score, label in pairs)
    return {
        "count": len(pairs),
        "threshold": threshold,
        "accuracy": (tp + tn) / len(pairs),
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "brier_score": sum(
            (score - int(label)) ** 2 for score, label in pairs
        )
        / len(pairs),
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
    }
