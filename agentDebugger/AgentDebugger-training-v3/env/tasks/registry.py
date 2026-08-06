"""
Task Registry — Maps task_id strings to task configurations.
"""

from env.tasks.task_easy import TASK_CONFIG as EASY_CONFIG
from env.tasks.task_medium import TASK_CONFIG as MEDIUM_CONFIG
from env.tasks.task_hard import TASK_CONFIG as HARD_CONFIG

TASK_REGISTRY = {
    "easy": EASY_CONFIG,
    "medium": MEDIUM_CONFIG,
    "hard": HARD_CONFIG,
}


def get_task(task_id: str) -> dict:
    """Get a task config by task_id. Raises ValueError if not found."""
    if task_id not in TASK_REGISTRY:
        raise ValueError(
            f"Unknown task_id: '{task_id}'. Available: {list(TASK_REGISTRY.keys())}"
        )
    return TASK_REGISTRY[task_id]


def list_tasks() -> list[str]:
    """Return list of available task IDs."""
    return list(TASK_REGISTRY.keys())
