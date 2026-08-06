"""
Grader Easy — Standard scoring formula for the binary search task.
Formula: 0.60 test_pass_ratio + 0.20 efficiency + 0.15 hypothesis + 0.05 early_solve
"""

import math
from typing import List, Dict, Any
from env.graders.base_grader import BaseGrader


class EasyGrader(BaseGrader):

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
        keywords = ground_truth["hypothesis_keywords"]

        # 1. Test pass ratio (weight: 0.60)
        test_pass_ratio = (best_tests_passed / tests_total) if tests_total > 0 else 0.0
        test_score = test_pass_ratio * 0.60

        # 2. Efficiency bonus (weight: 0.20)
        efficiency = max(0.0, (max_attempts - attempts_used) / max_attempts) if max_attempts > 0 else 0.0
        efficiency_score = efficiency * 0.20

        # 3. Hypothesis accuracy (weight: 0.15)
        if hypotheses:
            matches = sum(
                1 for h in hypotheses
                if self._check_hypothesis_keywords(h, keywords, "any")
            )
            hypothesis_ratio = matches / len(hypotheses)
        else:
            hypothesis_ratio = 0.0
        hypothesis_score = hypothesis_ratio * 0.15

        # 4. Early solve bonus (weight: 0.05)
        early_threshold = math.ceil(max_attempts / 3)
        all_pass = best_tests_passed == tests_total
        early_solve_score = 0.05 if (all_pass and attempts_used <= early_threshold) else 0.0

        total = test_score + efficiency_score + hypothesis_score + early_solve_score
        return self._clamp(total)
