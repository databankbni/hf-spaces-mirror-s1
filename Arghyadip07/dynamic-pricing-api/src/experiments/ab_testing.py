import random
from dataclasses import dataclass
from typing import Dict, Any
from pathlib import Path

from src.core.settings import settings
from src.storage import storage_backend


@dataclass
class ABAssignment:
    experiment: str
    subject_id: str
    group: str


class ABTestManager:
    """Minimal in-memory A/B testing manager.

    Assigns subjects deterministically by hashing or randomly and records
    outcomes for later analysis. For production use, integrate with a
    persistent experiment platform and include statistical power checks.
    """

    def __init__(self):
        self.assignments: Dict[str, Dict[str, str]] = {}
        self.outcomes: Dict[str, list[Dict[str, Any]]] = {}
        # initialize storage backend
        storage_backend.ensure_db_initialized()
        self._db_path = None

    def assign(self, experiment: str, subject_id: str, groups: list[str] = None) -> ABAssignment:
        groups = groups or ["control", "treatment"]
        # naive random assignment (can be replaced with consistent bucketing)
        group = random.choice(groups)
        self.assignments.setdefault(experiment, {})[subject_id] = group
        storage_backend.insert_ab_assignment(experiment, subject_id, group)
        return ABAssignment(experiment=experiment, subject_id=subject_id, group=group)

    def record_outcome(self, experiment: str, subject_id: str, outcome: dict) -> dict:
        group = self.assignments.get(experiment, {}).get(subject_id, "unknown")
        self.outcomes.setdefault(experiment, []).append({"subject_id": subject_id, "group": group, "outcome": outcome})
        storage_backend.insert_ab_outcome(experiment, subject_id, group, outcome)
        return {"status": "recorded", "experiment": experiment, "group": group}

    def summary(self, experiment: str) -> dict:
        # prefer persisted summary when available
        return storage_backend.get_ab_summary(experiment)
        by_group: Dict[str, list] = {}
        for r in recs:
            by_group.setdefault(r["group"], []).append(r["outcome"])

        # simple counts and mean of numeric 'metric' if present
        summary = {}
        for g, items in by_group.items():
            count = len(items)
            numeric_vals = [i.get("metric") for i in items if isinstance(i.get("metric"), (int, float))]
            mean_metric = sum(numeric_vals) / len(numeric_vals) if numeric_vals else None
            summary[g] = {"count": count, "mean_metric": mean_metric}

        return {"experiment": experiment, "groups": summary}
