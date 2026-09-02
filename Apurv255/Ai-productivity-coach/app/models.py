from pydantic import BaseModel, Field
from typing import List, Optional


class Observation(BaseModel):
    current_task: str = "DSA"
    focus_level: float = 0.7
    fatigue: float = 0.0
    distractions: List[str] = []
    time_spent: int = 0
    deadline: int = 60


class Action(BaseModel):
    action: str  # "continue", "take_break", "block_distraction"
    target: Optional[str] = None  # used for block_distraction


class Reward(BaseModel):
    value: float


class TaskScore(BaseModel):
    task: str
    score: float
    grade: str
    avg_focus: float
    total_reward: float
    steps: int


class EpisodeScore(BaseModel):
    scores: List[TaskScore]
    overall: float