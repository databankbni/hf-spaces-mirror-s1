"""
Base Grader — Abstract base class for all graders.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any


class BaseGrader(ABC):
    """Abstract base grader. All graders must implement score()."""

    @abstractmethod
    def score(
        self,
        task_config: dict,
        attempts: List[Dict[str, Any]],
        best_tests_passed: int,
        tests_total: int,
        attempts_used: int,
        max_attempts: int,
        hypotheses: List[str],
    ) -> float:
        """
        Score an episode. Must return a float in [0.0, 1.0].
        Must be deterministic: same inputs → same output.
        
        Args:
            task_config: The full task config dict
            attempts: List of attempt dicts with code_submitted, hypothesis, tests_passed, etc.
            best_tests_passed: Best test pass count across all attempts
            tests_total: Total tests in the suite
            attempts_used: Number of fix attempts used
            max_attempts: Maximum allowed attempts
            hypotheses: All hypotheses submitted
        
        Returns:
            float in [0.0, 1.0]
        """
        pass

    def _check_hypothesis_keywords(
        self, hypothesis: str, keywords: List[str], mode: str = "any"
    ) -> bool:
        """Check if a hypothesis matches any/all of the ground truth keywords."""
        hypothesis_lower = hypothesis.lower()
        if mode == "any":
            return any(kw.lower() in hypothesis_lower for kw in keywords)
        elif mode == "all":
            return all(kw.lower() in hypothesis_lower for kw in keywords)
        return False

    def _clamp(self, value: float) -> float:
        """Clamp a value to (0.0, 1.0)."""
        return max(0.01, min(0.99, value))
