"""
Grader Medium — Scoring with red herring detection.
Same base formula as easy, but with special hypothesis logic:
  - Hypothesis mentioning ONLY "authenticate_user" scores 0.0 for hypothesis_accuracy
  - Must mention "hash_password" AND at least 1 other keyword to get full marks
"""

import math
from typing import List, Dict, Any
from env.graders.base_grader import BaseGrader


class MediumGrader(BaseGrader):

    def _score_hypothesis(self, hypothesis: str, ground_truth: dict) -> float:
        """Score a single hypothesis with red herring detection."""
        h_lower = hypothesis.lower()
        keywords = ground_truth["hypothesis_keywords"]
        red_herring = ground_truth.get("red_herring_keyword", "authenticate_user")

        # Check if only the red herring is mentioned (no correct keywords)
        mentions_red_herring = red_herring.lower() in h_lower
        mentions_hash_password = "hash_password" in h_lower

        # Must mention "hash_password" AND at least 1 other keyword
        other_keywords = [kw for kw in keywords if kw.lower() != "hash_password"]
        mentions_other = any(kw.lower() in h_lower for kw in other_keywords)

        if mentions_hash_password and mentions_other:
            return 1.0  # Full credit
        elif mentions_hash_password:
            return 0.5  # Partial — found right function but no detail
        elif mentions_red_herring and not mentions_hash_password:
            return 0.0  # Red herring was followed
        else:
            return 0.1  # Generic hypothesis

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
        ground_truth = task_config["ground_truth"]

        # 1. Test pass ratio (weight: 0.60)

        if attempts:
            agent_best = max(a.get("tests_passed",0) for a in attempts)
        else:
            agent_best = 0
        test_pass_ratio = (agent_best / tests_total) if tests_total > 0 else 0.0
        test_score = test_pass_ratio * 0.60

        # 2. Efficiency bonus (weight: 0.20)
        efficiency = max(0.0, (max_attempts - attempts_used) / max_attempts) if max_attempts > 0 else 0.0
        efficiency_score = efficiency * 0.20

        # 3. Hypothesis accuracy with red herring detection (weight: 0.15)
        if hypotheses:
            h_scores = [self._score_hypothesis(h, ground_truth) for h in hypotheses]
            hypothesis_ratio = sum(h_scores) / len(h_scores)
        else:
            hypothesis_ratio = 0.0
        hypothesis_score = hypothesis_ratio * 0.15

        # 4. Early solve bonus (weight: 0.05)
        early_threshold = math.ceil(max_attempts / 3)
        all_pass = best_tests_passed == tests_total
        early_solve_score = 0.05 if (all_pass and attempts_used <= early_threshold) else 0.0

        total = test_score + efficiency_score + hypothesis_score + early_solve_score
        return self._clamp(total)
