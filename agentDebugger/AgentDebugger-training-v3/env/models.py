"""
AgentDebuggerEnv — Pydantic Data Models
========================================
Pydantic v2 data models for structured interaction between the agent 
and the environment, ensuring strict type safety and schema compliance.
"""

import re
from pydantic import BaseModel
from typing import List, Dict, Optional, Literal


class FixAttempt(BaseModel):
    attempt_number: int           # 1-indexed attempt number this episode
    code_submitted: str           # The full code the agent submitted for this attempt
    hypothesis: str               # Agent's stated hypothesis about the bug before this attempt
    execution_output: str         # Full stdout + stderr from running the test suite
    tests_passed: int             # Number of tests that passed after this fix
    tests_total: int              # Total number of tests in the suite
    execution_time_ms: int        # How long the sandbox took to run (milliseconds)
    timed_out: bool               # Whether this attempt hit the 10-second sandbox timeout


class Observation(BaseModel):
    # Task context — fixed for the episode
    task_id: str                  # "easy" | "medium" | "hard"
    task_description: str         # Plain English description of what the code is supposed to do
    buggy_code: str               # The original broken code (shown once at reset, always available)
    test_suite: str               # The full test suite code
    initial_error_output: str     # Output of running the test suite against the buggy code at reset()

    # Dynamic state — changes each step
    current_code: str             # The most recent version of the code
    current_error_output: str     # Output of running tests against current_code
    tests_passed: int             # Tests passing on current_code
    tests_total: int              # Total tests in suite
    previous_attempts: List[FixAttempt]  # Full history of all fix attempts this episode

    # Budget tracking
    attempts_remaining: int       # How many more fix submissions are allowed
    max_attempts: int             # Total attempt budget for this task

    # Step tracking
    step_number: int              # Current step number (increments on every action)
    max_steps: int                # Total step budget (includes both fix and query actions)
    done: bool                    # Whether the episode has ended

    # Scoring signal (shown to agent for learning)
    score_estimate: float         # Running estimate of current grader score (0.0–1.0)
    hint_used: bool               # Whether the agent has used their one hint this episode


class Action(BaseModel):
    action_type: str              # "submit_fix" | "query_context" | "give_up"

    # ── submit_fix ──
    fixed_code: Optional[str] = None
    hypothesis: Optional[str] = None

    # ── query_context ──
    query_type: Optional[str] = None
    query_target: Optional[str] = None

    # ── give_up ──
    final_diagnosis: Optional[str] = None


class Reward(BaseModel):
    step_reward: float            # Reward for THIS step only. Range: -1.0 to +1.0
    cumulative_reward: float      # Sum of all step_rewards this episode
    grader_score: float           # 0.0 during episode. Set ONLY on terminal step (done=True).
    breakdown: Dict[str, float]   # Itemized components


# ── STRUCTURED AGENT OUTPUT ────────────────────────────────────────────────

VALID_ACTIONS = {"inspect_lines", "run_tests", "propose_fix", "request_context", "give_up"}


class StructuredAgentOutput(BaseModel):
    observation: str
    hypothesis: str
    confidence: Literal["low", "medium", "high"]
    action: str
    detail: str
    valid: bool
    raw_text: str


def parse_agent_output(raw_text: str) -> StructuredAgentOutput:
    """
    Parse agent's structured response. Robust to minor formatting variations.
    Sets valid=False if any required field is missing or action is not in VALID_ACTIONS.

    Expected format:
        OBSERVATION: [text]
        HYPOTHESIS: [text]
        CONFIDENCE: [low|medium|high]
        ACTION: [inspect_lines|run_tests|propose_fix|request_context|give_up]
        DETAIL: [text]
    """
    def extract_field(text: str, field: str) -> Optional[str]:
        pattern = rf"(?i){field}\s*:\s*(.*?)(?=\n(?:OBSERVATION|HYPOTHESIS|CONFIDENCE|ACTION|DETAIL)\s*:|$)"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return None

    observation = extract_field(raw_text, "OBSERVATION") or ""
    hypothesis = extract_field(raw_text, "HYPOTHESIS") or ""
    confidence_raw = (extract_field(raw_text, "CONFIDENCE") or "").lower().strip()
    action_raw = (extract_field(raw_text, "ACTION") or "").lower().strip()
    detail = extract_field(raw_text, "DETAIL") or ""

    confidence = confidence_raw if confidence_raw in {"low", "medium", "high"} else "low"
    action = action_raw if action_raw in VALID_ACTIONS else "invalid"

    valid = all([
        len(observation) > 5,
        len(hypothesis) > 10,
        confidence in {"low", "medium", "high"},
        action in VALID_ACTIONS,
        len(detail) > 0,
    ])

    return StructuredAgentOutput(
        observation=observation,
        hypothesis=hypothesis,
        confidence=confidence,
        action=action,
        detail=detail,
        valid=valid,
        raw_text=raw_text,
    )
