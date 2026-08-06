"""
AgentDebuggerEnv — Core Environment
=====================================
Implementation of the core OpenEnv-compliant environment, managing the 
debugging episode lifecycle including task initialization, action 
processing, and reward calculation.
"""

import os
import json
import re
import math
import random
from typing import Dict, Any, Optional, Tuple

from env.models import Observation, Action, Reward, FixAttempt, parse_agent_output, StructuredAgentOutput
from env.sandbox import execute_code
from env.tasks.registry import get_task, list_tasks
from env.graders import get_grader
from server.reward_calculator import DebugRewardCalculator

# Optional W&B — only activates if key is present
try:
    import wandb
    WANDB_AVAILABLE = os.environ.get("WANDB_API_KEY") is not None
except ImportError:
    WANDB_AVAILABLE = False


class DebuggerEnvironment:
    """Core debugging environment implementing the OpenEnv interface."""

    def __init__(self, curriculum_step: int = 0):
        self._task_config: Optional[dict] = None
        self._observation: Optional[Observation] = None
        self._cumulative_reward: float = 0.0
        self._attempts_used: int = 0
        self._best_tests_passed: int = 0
        self._all_hypotheses: list[str] = []
        self._all_attempts: list[dict] = []
        self._queries_used: int = 0
        self._done: bool = True
        self._step_number: int = 0
        self._prev_tests_passed: int = 0

        # Curriculum learning state
        self.curriculum_step: int = curriculum_step
        self.reward_calculator: DebugRewardCalculator = DebugRewardCalculator()
        self.current_episode_trajectory: list[dict] = []
        self.current_bug: Optional[dict] = None
        self.turn_number: int = 0
        self.bugs: list[dict] = self._load_bugs_for_curriculum(curriculum_step)

    def reset(self, task_id: str) -> dict:
        """
        Start a fresh episode. Clears all state.
        Returns the initial Observation as a dict.
        """
        try:
            task_config = get_task(task_id)
        except ValueError as e:
            raise ValueError(str(e))

        self._task_config = task_config
        self._cumulative_reward = 0.0
        self._attempts_used = 0
        self._best_tests_passed = 0
        self._all_hypotheses = []
        self._all_attempts = []
        self._queries_used = 0
        self._done = False
        self._step_number = 0

        # Run buggy code through sandbox to get initial error output
        buggy_code = task_config["buggy_code"]
        test_executable = task_config["test_suite"] + "\n\n" + task_config["test_suite_executable"]
        allow_threading = task_config.get("allow_threading", False)

        initial_output, timed_out, exec_time = execute_code(
            buggy_code, test_executable, allow_threading=allow_threading
        )

        # Parse initial test results
        initial_passed = self._parse_tests_passed(initial_output, task_config["tests_total"])
        self._prev_tests_passed = initial_passed
        self._best_tests_passed = initial_passed

        self._observation = Observation(
            task_id=task_id,
            task_description=task_config["task_description"],
            buggy_code=buggy_code,
            test_suite=task_config["test_suite"],
            initial_error_output=initial_output,
            current_code=buggy_code,
            current_error_output=initial_output,
            tests_passed=initial_passed,
            tests_total=task_config["tests_total"],
            previous_attempts=[],
            attempts_remaining=task_config["max_attempts"],
            max_attempts=task_config["max_attempts"],
            step_number=0,
            max_steps=task_config["max_steps"],
            done=False,
            score_estimate=0.0,
            hint_used=False,
        )

        return self._observation.model_dump()

    def step(self, action: Action) -> Dict[str, Any]:
        """
        Process one action. Returns {observation, reward, done, info}.
        Never crashes — errors go in info["error"].
        """
        # Safety: if episode is already done, return current state
        if self._done:
            return self._make_response(
                step_reward=0.0,
                info={"error": "Episode is already done. Call /reset to start a new episode."},
            )

        # Increment step
        self._step_number += 1

        # Check max_steps exceeded
        if self._step_number > self._task_config["max_steps"]:
            return self._force_truncation()

        action_type = action.action_type

        if action_type == "submit_fix":
            return self._handle_submit_fix(action)
        elif action_type == "query_context":
            return self._handle_query_context(action)
        elif action_type == "give_up":
            return self._handle_give_up(action)
        else:
            return self._make_response(
                step_reward=-0.05,
                info={"error": f"Unknown action_type: '{action_type}'. Use 'submit_fix', 'query_context', or 'give_up'."},
            )

    def state(self) -> dict:
        """Return the full internal environment state as a plain dict."""
        if self._observation is None:
            return {
                "task_id": None,
                "step_number": 0,
                "attempts_used": 0,
                "current_tests_passed": 0,
                "current_tests_total": 0,
                "best_tests_passed": 0,
                "all_hypotheses": [],
                "cumulative_reward": 0.0,
                "done": True,
                "hint_used": False,
            }

        return {
            "task_id": self._observation.task_id,
            "step_number": self._step_number,
            "attempts_used": self._attempts_used,
            "current_tests_passed": self._observation.tests_passed,
            "current_tests_total": self._observation.tests_total,
            "best_tests_passed": self._best_tests_passed,
            "all_hypotheses": list(self._all_hypotheses),
            "cumulative_reward": self._cumulative_reward,
            "done": self._done,
            "hint_used": self._observation.hint_used,
        }

    # ── Curriculum Learning ──────────────────────────────────────────────────

    def _load_bugs_for_curriculum(self, step: int) -> list[dict]:
        """
        Curriculum schedule:
        Steps 0-299:   Tier 1 only (easy — off-by-one, wrong operator)
        Steps 300-599: Tier 1 + Tier 2 (70/30 split)
        Steps 600+:    Tier 1 + Tier 2 + Tier 3 (40/40/20 split)
        """
        def load_tier(tier: int) -> list[dict]:
            path = f"data/bugs_tier{tier}.jsonl"
            if not os.path.exists(path):
                return []
            bugs = []
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        bugs.append(json.loads(line))
            return bugs

        tier1 = load_tier(1)

        if step < 300:
            return tier1
        elif step < 600:
            tier2 = load_tier(2)
            n2 = int(len(tier2) * 0.43)  # ~70/30 split
            return tier1 + tier2[:n2]
        else:
            tier2 = load_tier(2)
            tier3 = load_tier(3)
            return tier1 + tier2 + tier3

    def advance_curriculum(self, step: int):
        """Call from training loop at steps 300 and 600."""
        self.curriculum_step = step
        self.bugs = self._load_bugs_for_curriculum(step)

    def _active_tiers(self) -> list[int]:
        if self.curriculum_step < 300:
            return [1]
        elif self.curriculum_step < 600:
            return [1, 2]
        return [1, 2, 3]

    # ── Curriculum Step / GRPO-Compatible Methods ────────────────────────────

    def reset_curriculum(self) -> dict:
        """
        Start a fresh curriculum episode. Selects a random bug from the
        curriculum-appropriate pool. Returns initial observation dict.
        """
        if not self.bugs:
            raise ValueError("No bugs loaded. Run data/generate_bugs.py first.")

        self.current_bug = random.choice(self.bugs)
        self.current_episode_trajectory = []
        self.turn_number = 0

        return {
            "buggy_code": self.current_bug.get("buggy_code", ""),
            "error_message": self.current_bug.get("initial_error", "Some tests are failing."),
            "test_results": {"passed": 0, "failed": 0, "total": len(self.current_bug.get("test_cases", []))},
            "turn_number": 0,
            "history": [],
        }

    def step_curriculum(self, raw_text: str) -> dict:
        """
        Process one structured agent response in the curriculum setting.
        Returns {observation, reward, done, info}.
        """
        agent_output = parse_agent_output(raw_text)

        # Run fix against test cases if agent proposes one
        test_results = {"passed": 0, "failed": 0, "total": 0, "newly_broken": 0}
        if agent_output.action == "propose_fix" and self.current_bug:
            test_results = self._run_fix_safely(
                proposed_code=agent_output.detail,
                bug=self.current_bug,
            )

        # Compute reward
        reward_breakdown = self.reward_calculator.compute_turn_reward(
            agent_output=agent_output,
            ground_truth={
                "bug_function": self.current_bug.get("bug_location", {}).get("function", "") if self.current_bug else "",
                "bug_line": self.current_bug.get("bug_location", {}).get("line_start", -1) if self.current_bug else -1,
                "bug_type": self.current_bug.get("bug_type", "") if self.current_bug else "",
                "canonical_fix_code": self.current_bug.get("original_code", "") if self.current_bug else "",
            },
            test_results=test_results,
            turn_number=self.turn_number,
        )

        # Record turn in episode trajectory
        self.current_episode_trajectory.append({
            "turn": self.turn_number,
            "agent_output": agent_output,
            "test_results": test_results,
            "reward": reward_breakdown,
        })

        self.turn_number += 1

        # Determine if episode is done
        solved = reward_breakdown.fix_quality >= 0.35
        max_turns_reached = self.turn_number >= self.reward_calculator.MAX_TURNS
        gave_up = agent_output.action == "give_up"
        done = solved or max_turns_reached or gave_up

        # Log to W&B at episode end
        if done and WANDB_AVAILABLE:
            self._log_episode_to_wandb(reward_breakdown, solved)

        return {
            "observation": {
                "buggy_code": self.current_bug.get("buggy_code", "") if self.current_bug else "",
                "error_message": self.current_bug.get("initial_error", "") if self.current_bug else "",
                "test_results": test_results,
                "turn_number": self.turn_number,
                "history": [
                    {
                        "turn": t["turn"],
                        "action": t["agent_output"].action,
                        "reward": t["reward"].total,
                    }
                    for t in self.current_episode_trajectory
                ],
            },
            "reward": reward_breakdown.total,
            "done": done,
            "info": {
                "reward_breakdown": reward_breakdown.__dict__,
                "turn_number": self.turn_number,
                "solved": solved,
                "bug_tier": self.current_bug.get("difficulty", 0) if self.current_bug else 0,
            },
        }

    def _run_fix_safely(self, proposed_code: str, bug: dict) -> dict:
        """Run proposed fix against test cases with timeout. NEVER execute without timeout."""
        import subprocess
        import tempfile
        import sys

        if not proposed_code or not bug.get("test_cases"):
            return {"passed": 0, "failed": 0, "total": 0, "newly_broken": 0}

        test_cases = bug["test_cases"]
        func_name = bug.get("function_name", "")
        passed = 0

        for test in test_cases:
            inp = test["input"]
            expected = test["expected_output"]

            args_str = ", ".join(repr(x) for x in inp)

            script = f"""
{proposed_code}

try:
    result = {func_name}({args_str})
    expected = {repr(expected)}
    print("PASS" if result == expected else f"FAIL: got {{result}}, expected {{expected}}")
except Exception as e:
    print(f"ERROR: {{type(e).__name__}}: {{e}}")
"""
            try:
                with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                    f.write(script)
                    fname = f.name

                result = subprocess.run(
                    [sys.executable, fname],
                    capture_output=True, text=True, timeout=5
                )

                try:
                    os.unlink(fname)
                except Exception:
                    pass

                if "PASS" in result.stdout:
                    passed += 1
            except subprocess.TimeoutExpired:
                pass  # timeout = failed test
            except Exception:
                pass

        failed = len(test_cases) - passed
        return {
            "passed": passed,
            "failed": failed,
            "total": len(test_cases),
            "newly_broken": 0,
        }

    def _log_episode_to_wandb(self, final_reward, solved: bool):
        """Log episode metrics to W&B. Only called if WANDB_AVAILABLE."""
        if not WANDB_AVAILABLE:
            return
        breakdown = self.reward_calculator.get_reward_breakdown_for_logging(
            self.current_episode_trajectory
        )
        episode_reward = self.reward_calculator.compute_episode_reward(
            self.current_episode_trajectory
        )

        wandb.log({
            "episode/reward_total": episode_reward,
            "episode/solved": int(solved),
            "episode/turns_used": self.turn_number,
            "episode/bug_tier": self.current_bug.get("difficulty", 0) if self.current_bug else 0,
            "episode/curriculum_step": self.curriculum_step,
            **breakdown,
        })

    # ── Action Handlers ──────────────────────────────────────────────────────

    def _handle_submit_fix(self, action: Action) -> Dict[str, Any]:
        """Handle submit_fix action."""
        # Check: hypothesis is required
        if not action.hypothesis or not action.hypothesis.strip():
            return self._make_response(
                step_reward=-0.10,
                info={"error": "submit_fix requires a 'hypothesis' field. Fix was NOT executed."},
                count_step=True,
            )

        # Check: attempts remaining
        if self._observation.attempts_remaining <= 0:
            return self._make_response(
                step_reward=-0.15,
                info={"error": "No attempts remaining. Use 'query_context' or 'give_up'."},
                count_step=True,
            )

        # Get submitted code
        fixed_code = action.fixed_code or ""
        hypothesis = action.hypothesis.strip()
        self._all_hypotheses.append(hypothesis)
        self._attempts_used += 1

        # Execute in sandbox
        test_executable = self._task_config["test_suite"] + "\n\n" + self._task_config["test_suite_executable"]
        allow_threading = self._task_config.get("allow_threading", False)
        output, timed_out, exec_time = execute_code(
            fixed_code, test_executable, allow_threading=allow_threading
        )

        # Parse test results
        tests_total = self._task_config["tests_total"]
        tests_passed = self._parse_tests_passed(output, tests_total)

        # Update best
        self._best_tests_passed = max(self._best_tests_passed, tests_passed)

        # Calculate step reward
        step_reward = self._calculate_step_reward(
            tests_passed, tests_total, timed_out, hypothesis
        )

        # Record attempt
        attempt = FixAttempt(
            attempt_number=self._attempts_used,
            code_submitted=fixed_code,
            hypothesis=hypothesis,
            execution_output=output,
            tests_passed=tests_passed,
            tests_total=tests_total,
            execution_time_ms=exec_time,
            timed_out=timed_out,
        )
        self._all_attempts.append(attempt.model_dump())

        # Update observation
        attempts_remaining = self._task_config["max_attempts"] - self._attempts_used
        self._observation = self._observation.model_copy(update={
            "current_code": fixed_code,
            "current_error_output": output,
            "tests_passed": tests_passed,
            "previous_attempts": [FixAttempt(**a) for a in self._all_attempts],
            "attempts_remaining": attempts_remaining,
            "step_number": self._step_number,
            "score_estimate": self._estimate_score(),
        })
        self._prev_tests_passed = tests_passed

        # Check if solved
        all_pass = tests_passed == tests_total
        info = {
            "step_number": self._step_number,
            "attempts_used": self._attempts_used,
            "attempts_remaining": attempts_remaining,
            "tests_passed": tests_passed,
            "tests_total": tests_total,
            "hypothesis_matched_bug": None,
            "query_result": None,
            "error": None,
            "execution_time_ms": exec_time,
            "timed_out": timed_out,
        }

        if all_pass:
            # Episode solved!
            step_reward += 0.50  # Major bonus
            return self._end_episode(step_reward, info)

        # Check if out of attempts
        if attempts_remaining <= 0:
            return self._end_episode(step_reward, info)

        return self._make_response(step_reward=step_reward, info=info, count_step=True)

    def _handle_query_context(self, action: Action) -> Dict[str, Any]:
        """Handle query_context action."""
        valid_query_types = ["function_signature", "related_code", "error_explanation", "test_details", "test_suggestion"]

        if action.query_type not in valid_query_types:
            return self._make_response(
                step_reward=-0.05,
                info={
                    "error": f"Invalid query_type: '{action.query_type}'. Valid: {valid_query_types}",
                    "query_result": None,
                },
                count_step=True,
            )

        # Generate context response
        query_result = self._generate_query_response(action.query_type, action.query_target)

        # First query is free, subsequent cost -0.05
        if self._queries_used == 0:
            step_reward = 0.0
            self._observation = self._observation.model_copy(update={
                "hint_used": True,
                "step_number": self._step_number,
            })
        else:
            step_reward = -0.05

        self._queries_used += 1

        info = {
            "step_number": self._step_number,
            "attempts_used": self._attempts_used,
            "attempts_remaining": self._observation.attempts_remaining,
            "tests_passed": self._observation.tests_passed,
            "tests_total": self._observation.tests_total,
            "hypothesis_matched_bug": None,
            "query_result": query_result,
            "error": None,
            "execution_time_ms": None,
            "timed_out": False,
        }

        return self._make_response(step_reward=step_reward, info=info, count_step=True)

    def _handle_give_up(self, action: Action) -> Dict[str, Any]:
        """Handle give_up action. Ends episode, runs grader."""
        if action.final_diagnosis:
            self._all_hypotheses.append(action.final_diagnosis)

        info = {
            "step_number": self._step_number,
            "attempts_used": self._attempts_used,
            "attempts_remaining": self._observation.attempts_remaining,
            "tests_passed": self._observation.tests_passed,
            "tests_total": self._observation.tests_total,
            "hypothesis_matched_bug": None,
            "query_result": None,
            "error": None,
            "execution_time_ms": None,
            "timed_out": False,
        }
        return self._end_episode(step_reward=0.0, info=info)

    # ── Internal Helpers ─────────────────────────────────────────────────────

    def _calculate_step_reward(
        self, tests_passed: int, tests_total: int, timed_out: bool, hypothesis: str
    ) -> float:
        """Calculate the step-level reward for a fix attempt."""
        reward = 0.0
        prev = self._prev_tests_passed

        if timed_out:
            reward -= 0.10

        if tests_passed > prev:
            # Progress reward
            reward += 0.15 * (tests_passed - prev) / tests_total
        elif tests_passed < prev:
            # Regression penalty
            reward -= 0.10 * (prev - tests_passed) / tests_total
        else:
            # Stagnation
            reward -= 0.05

        return reward

    def _end_episode(self, step_reward: float, info: dict) -> Dict[str, Any]:
        """End the episode, run grader, return final response."""
        self._done = True

        # Run grader
        grader = get_grader(self._task_config["task_id"])
        agent_best_tests_passed = (
            max((a.get("tests_passed", 0) for a in self._all_attempts), default=0)
            if self._all_attempts else 0
        )

        grader_score = grader.score(
            task_config=self._task_config,
            attempts=self._all_attempts,
            best_tests_passed=agent_best_tests_passed,
            tests_total=self._task_config["tests_total"],
            attempts_used=self._attempts_used,
            max_attempts=self._task_config["max_attempts"],
            hypotheses=self._all_hypotheses,
        )

        # Check hypothesis accuracy for info
        ground_truth = self._task_config["ground_truth"]
        keywords = ground_truth["hypothesis_keywords"]
        if self._all_hypotheses:
            any_match = any(
                any(kw.lower() in h.lower() for kw in keywords)
                for h in self._all_hypotheses
            )
            info["hypothesis_matched_bug"] = any_match

        self._observation = self._observation.model_copy(update={
            "done": True,
            "step_number": self._step_number,
            "score_estimate": grader_score,
        })

        return self._make_response(
            step_reward=step_reward,
            info=info,
            grader_score=grader_score,
            force_done=True,
        )

    def _force_truncation(self) -> Dict[str, Any]:
        """Force episode end due to max_steps exceeded."""
        info = {
            "step_number": self._step_number,
            "attempts_used": self._attempts_used,
            "attempts_remaining": self._observation.attempts_remaining,
            "tests_passed": self._observation.tests_passed,
            "tests_total": self._observation.tests_total,
            "hypothesis_matched_bug": None,
            "query_result": None,
            "error": "Max steps exceeded. Episode truncated.",
            "execution_time_ms": None,
            "timed_out": False,
        }
        return self._end_episode(step_reward=-0.20, info=info)

    def _make_response(
        self,
        step_reward: float,
        info: dict,
        grader_score: float = 0.0,
        force_done: bool = False,
        count_step: bool = False,
    ) -> Dict[str, Any]:
        """Build the standard step response dict."""
        self._cumulative_reward += step_reward

        # Update observation step number
        if self._observation:
            self._observation = self._observation.model_copy(update={
                "step_number": self._step_number,
                "done": force_done or self._done,
            })

        # Fill in default info fields
        default_info = {
            "step_number": self._step_number,
            "attempts_used": self._attempts_used,
            "attempts_remaining": self._observation.attempts_remaining if self._observation else 0,
            "tests_passed": self._observation.tests_passed if self._observation else 0,
            "tests_total": self._observation.tests_total if self._observation else 0,
            "hypothesis_matched_bug": None,
            "query_result": None,
            "error": None,
            "execution_time_ms": None,
            "timed_out": False,
        }
        for k, v in default_info.items():
            if k not in info or info[k] is None and v is not None and k not in ("error", "query_result", "hypothesis_matched_bug", "execution_time_ms"):
                pass  # Keep info values
            info.setdefault(k, v)

        reward = Reward(
            step_reward=step_reward,
            cumulative_reward=self._cumulative_reward,
            grader_score=grader_score,
            breakdown={
                "step_reward": step_reward,
                "cumulative_reward": self._cumulative_reward,
            },
        )

        return {
            "observation": self._observation.model_dump() if self._observation else {},
            "reward": reward.model_dump(),
            "done": force_done or self._done,
            "info": info,
        }

    def _estimate_score(self) -> float:
        """Running estimate of what the grader would return right now."""
        if not self._task_config:
            return 0.0
        tests_total = self._task_config["tests_total"]
        if tests_total == 0:
            return 0.0
        return (self._best_tests_passed / tests_total) * 0.60

    def _parse_tests_passed(self, output: str, tests_total: int) -> int:
        """Parse the number of tests passed from sandbox output."""
        # Look for pattern like "7 passed, 1 failed" or "8 passed, 0 failed"
        match = re.search(r'(\d+)\s+passed', output)
        if match:
            return min(int(match.group(1)), tests_total)
        # If no match, assume 0
        return 0

    def _generate_query_response(self, query_type: str, query_target: str = None) -> str:
        """Generate a context response for a query_context action."""
        task = self._task_config
        buggy_code = task["buggy_code"]
        test_suite = task["test_suite"]
        ground_truth = task["ground_truth"]

        if query_type == "function_signature":
            # Extract function signatures from buggy code
            lines = buggy_code.split('\n')
            sigs = [line.strip() for line in lines if line.strip().startswith('def ')]
            if query_target:
                sigs = [s for s in sigs if query_target in s] or sigs
            return "Function signatures:\n" + "\n".join(f"  {s}" for s in sigs)

        elif query_type == "related_code":
            # Return the full buggy code
            return f"Full source code:\n{buggy_code}"

        elif query_type == "error_explanation":
            # Return the current error output with context
            current_error = self._observation.current_error_output if self._observation else ""
            return (
                f"Current error output:\n{current_error}\n\n"
                f"This output shows the result of running the test suite against "
                f"the current version of the code. Failed tests indicate assertions "
                f"that did not hold."
            )

        elif query_type == "test_details":
            # Return specific test details
            if query_target:
                lines = test_suite.split('\n')
                relevant = []
                in_test = False
                for line in lines:
                    if f"def {query_target}" in line or (query_target in line and 'def test_' in line):
                        in_test = True
                    if in_test:
                        relevant.append(line)
                        if line.strip() == '' and len(relevant) > 1:
                            break
                if relevant:
                    return f"Test details for '{query_target}':\n" + "\n".join(relevant)

            return f"Full test suite:\n{test_suite}"
        
        elif query_type == "test_suggestion":
            # Provide a specific hint for the hard task if they ask
            if task["task_id"] == "hard":
                return (
                    "HINT: The sequential tests pass, but have you considered testing with "
                    "concurrent threads? There might be a race condition that only appears "
                    "under load. Try writing a test that uses 'threading' to call methods "
                    "simultaneously."
                )
            elif task["task_id"] == "medium":
                return (
                    "HINT: Don't trust the first error message you see. Trace the data flow "
                    "backwards to see where the invalid input was actually generated."
                )
            else:
                return "HINT: Look closely at the comparison operators and loop boundaries."

        return "No information available for this query."
