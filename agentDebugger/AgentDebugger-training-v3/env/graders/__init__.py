# AgentDebuggerEnv - Graders package
from env.graders.grader_easy import EasyGrader
from env.graders.grader_medium import MediumGrader
from env.graders.grader_hard import HardGrader

GRADER_REGISTRY = {
    "easy": EasyGrader(),
    "medium": MediumGrader(),
    "hard": HardGrader(),
}


def get_grader(task_id: str):
    """Get the grader instance for a task_id."""
    if task_id not in GRADER_REGISTRY:
        raise ValueError(f"No grader for task_id: '{task_id}'")
    return GRADER_REGISTRY[task_id]
