"""
Grader Hard — Concurrent stress test scoring.

Weights:
  0.40 — agent's submitted fix passes the original 8 sequential tests
  0.30 — agent's submitted fix passes a 1000-thread concurrent stress test
  0.20 — hypothesis accuracy (agent correctly identified race condition)
  0.10 — efficiency bonus (solved within 5 attempts)

Security: ALL code execution goes through execute_code() sandbox.
          Never uses raw exec() or eval() on agent-submitted code.

Score floor fix: original_test_score uses only agent-submitted attempts,
                 NOT the initial buggy code. An agent that submits nothing
                 scores 0.0, not 0.40.
"""

from typing import List, Dict, Any
from env.graders.base_grader import BaseGrader
from env.sandbox import execute_code


# The concurrent stress test — written as a string and run through the sandbox.
# 1000 threads all calling increment() simultaneously.
# A correct fix must result in count == 1000 every single time.
_CONCURRENT_STRESS_TEST = """
import threading

counter = ConnectionCounter()
num_threads = 1000

threads = [threading.Thread(target=counter.increment) for _ in range(num_threads)]
for t in threads:
    t.start()
for t in threads:
    t.join()

result = counter.get_count()
assert result == num_threads, f"CONCURRENT FAIL: expected {num_threads}, got {result}"
print(f"CONCURRENT PASS: {result} == {num_threads}")
"""

class HardGrader(BaseGrader):

    def _run_concurrent_stress_test(self, code: str) -> bool:
        """
        Run the concurrent stress test against agent-submitted code.
        Routes through execute_code() sandbox — never uses raw exec().
        Returns True only if the counter reaches exactly 1000 after 
        1000 concurrent increments.
        """
        output, timed_out, _ = execute_code(
            code, 
            _CONCURRENT_STRESS_TEST,
            allow_threading=True,
        )
        if timed_out:
            return False
        return "CONCURRENT PASS" in output and "CONCURRENT FAIL" not in output

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

        # ── 1. Sequential test score (weight: 0.40) ──────────────────────────
        # IMPORTANT: Only count agent-submitted attempts, NOT the initial buggy
        # code. The buggy code passes all 8 sequential tests — if we used 
        # best_tests_passed from environment state, every agent would score 
        # 0.40 for free without fixing anything. We recalculate from attempts.
        if attempts:
            agent_best_sequential = max(
                a.get("tests_passed", 0) for a in attempts
            )
        else:
            agent_best_sequential = 0  # No attempts submitted → 0.0

        sequential_ratio = agent_best_sequential / tests_total if tests_total > 0 else 0.0
        sequential_score = sequential_ratio * 0.40

        # ── 2. Concurrent stress test (weight: 0.30) ──────────────────────────
        # Use the best attempt by sequential test count (ties broken by recency).
        # Run the stress test 5 times — must pass 4/5 for full credit,
        # at least 2/5 for partial credit. This handles non-determinism robustly.
        concurrent_score = 0.0
        if attempts:
            best_attempt = max(
                attempts,
                key=lambda a: (a.get("tests_passed", 0), a.get("attempt_number", 0))
            )
            best_code = best_attempt.get("code_submitted", "").strip()

            if best_code:
                passes = sum(
                    1 for _ in range(5)
                    if self._run_concurrent_stress_test(best_code)
                )
                if passes >= 4:
                    concurrent_score = 0.30       # Robustly fixed
                elif passes >= 2:
                    concurrent_score = 0.15       # Partially fixed / Flaky
        
        # ── 3. Hypothesis accuracy (weight: 0.20) ─────────────────────────────
        if hypotheses:
            matches = sum(
                1 for h in hypotheses
                if self._check_hypothesis_keywords(h, keywords, "any")
            )
            hypothesis_ratio = matches / len(hypotheses)
        else:
            hypothesis_ratio = 0.0
        hypothesis_score = hypothesis_ratio * 0.20

        # ── 4. Efficiency bonus (weight: 0.10) ────────────────────────────────
        # Only awarded if the agent actually fixed the concurrent bug too,
        # not just for submitting fewer attempts on a wrong fix.
        efficiency_score = 0.10 if (concurrent_score == 0.30 and attempts_used <= 5) else 0.0

        total = sequential_score + concurrent_score + hypothesis_score + efficiency_score
        return self._clamp(total)