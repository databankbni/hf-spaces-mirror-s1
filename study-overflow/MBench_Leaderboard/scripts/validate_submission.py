import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from constants import METRIC_COLUMNS


ALLOWED_MODEL_TYPES = {"text-conditioned", "action-conditioned"}
REQUIRED_KEYS = ["model_name", "model_link", "model_type", "total_m_score"]
SUMMARY_SCORE_FIELDS = [
    "total_m_score",
    "entity_score",
    "environment_score",
    "causal_score",
]


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")


def _is_present(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def validate_submission_json(data: dict) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "Submission JSON must be an object."

    normalized = {_normalize_key(str(key)): value for key, value in data.items()}

    for key in REQUIRED_KEYS:
        if key not in normalized or not _is_present(normalized[key]):
            return False, f"Missing required field: {key}"

    model_type = str(normalized["model_type"]).strip()
    if model_type not in ALLOWED_MODEL_TYPES:
        return (
            False,
            "model_type must be either text-conditioned or action-conditioned.",
        )

    score_fields = set(SUMMARY_SCORE_FIELDS)
    score_fields.update(_normalize_key(column) for column in METRIC_COLUMNS)

    for key, value in normalized.items():
        if key in score_fields and _is_present(value):
            try:
                score = float(value)
            except (TypeError, ValueError):
                return False, f"Score field {key} must be convertible to float."
            if not 0 <= score <= 100:
                return False, f"Score field {key} must be between 0 and 100."

    return True, "Submission JSON is valid."
