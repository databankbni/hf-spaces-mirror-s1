
import pytest
from env.environment import DebuggerEnvironment
from env.models import Action

def test_full_episode_easy():
    env = DebuggerEnvironment()
    
    
    obs = env.reset("easy")
    assert obs["task_id"] == "easy"
    assert obs["done"] is False
    assert obs["tests_passed"] < obs["tests_total"]
    
    
    
    ground_truth_code = """
def binary_search(arr, target):
    left, right = 0, len(arr) - 1
    while left <= right:
        mid = (left + right) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    return -1
"""
    action = Action(
        action_type="submit_fix",
        fixed_code=ground_truth_code,
        hypothesis="Binary search termination condition should be left <= right to include all elements."
    )
    
    result = env.step(action)
    
    
    assert result["done"] is True
    assert result["observation"]["tests_passed"] == result["observation"]["tests_total"]
    assert result["reward"]["grader_score"] > 0.80

def test_query_hint_system():
    env = DebuggerEnvironment()
    env.reset("hard")
    
    action = Action(
        action_type="query_context",
        query_type="test_suggestion"
    )
    
    result = env.step(action)
    assert "concurrent threads" in result["info"]["query_result"]
    assert result["reward"]["step_reward"] == 0.0  

def test_hard_grader_consensus():
    from unittest.mock import patch
    from env.graders.grader_hard import HardGrader
    
    grader = HardGrader()
    
    
    
    with patch("env.graders.grader_hard.execute_code") as mock_exec:
        mock_exec.side_effect = [
            ("CONCURRENT PASS", False, 100),
            ("CONCURRENT FAIL", False, 100),
            ("CONCURRENT PASS", False, 100),
            ("CONCURRENT FAIL", False, 100),
            ("CONCURRENT PASS", False, 100),
        ]
        
        score = grader.score(
            task_config={"task_id": "hard", "ground_truth": {"hypothesis_keywords": ["race"]}},
            attempts=[{"tests_passed": 8, "attempt_number": 1, "code_submitted": "..."}],
            best_tests_passed=8,
            tests_total=8,
            attempts_used=1,
            max_attempts=10,
            hypotheses=["race condition"]
        )
        
        
        
        
        
        
        
        assert score == 0.75
