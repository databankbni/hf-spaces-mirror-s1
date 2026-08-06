
import pytest
from env.environment import DebuggerEnvironment
from env.models import Action


@pytest.fixture
def env():
    return DebuggerEnvironment()




def test_reset_easy_returns_observation(env):
    obs = env.reset("easy")
    assert obs["task_id"] == "easy"
    assert obs["done"] is False
    assert obs["tests_total"] == 8
    assert obs["attempts_remaining"] == 5
    assert obs["max_attempts"] == 5
    assert obs["step_number"] == 0
    assert obs["buggy_code"] != ""
    assert obs["test_suite"] != ""
    assert obs["initial_error_output"] != ""
    assert obs["previous_attempts"] == []


def test_reset_medium_returns_observation(env):
    obs = env.reset("medium")
    assert obs["task_id"] == "medium"
    assert obs["tests_total"] == 10
    assert obs["max_attempts"] == 7


def test_reset_hard_returns_observation(env):
    obs = env.reset("hard")
    assert obs["task_id"] == "hard"
    assert obs["tests_total"] == 8
    assert obs["max_attempts"] == 10


def test_reset_invalid_task_raises(env):
    with pytest.raises(ValueError, match="Unknown task_id"):
        env.reset("nonexistent")


def test_reset_clears_previous_state(env):
    env.reset("easy")
    
    action = Action(
        action_type="submit_fix",
        fixed_code="def binary_search(arr, target): return -1",
        hypothesis="test hypothesis",
    )
    env.step(action)

    
    obs = env.reset("easy")
    assert obs["step_number"] == 0
    assert obs["previous_attempts"] == []
    assert obs["attempts_remaining"] == 5




def test_step_submit_fix_without_hypothesis(env):
    env.reset("easy")
    action = Action(action_type="submit_fix", fixed_code="def binary_search(arr, target): return -1")
    result = env.step(action)
    assert result["reward"]["step_reward"] == -0.10
    assert result["info"]["error"] is not None
    assert "hypothesis" in result["info"]["error"].lower()


def test_step_submit_fix_with_valid_code(env):
    env.reset("easy")
    action = Action(
        action_type="submit_fix",
        fixed_code="def binary_search(arr, target): return -1",
        hypothesis="Testing a fix",
    )
    result = env.step(action)
    assert "observation" in result
    assert "reward" in result
    assert "done" in result
    assert "info" in result
    assert result["observation"]["step_number"] == 1


def test_step_submit_fix_solves_easy(env):
    env.reset("easy")
    fixed_code = '''def binary_search(arr: list, target: int) -> int:
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
'''
    action = Action(
        action_type="submit_fix",
        fixed_code=fixed_code,
        hypothesis="Off by one: should be left <= right",
    )
    result = env.step(action)
    assert result["observation"]["tests_passed"] == 8, result["observation"]["current_error_output"]
    assert result["done"] is True
    assert result["reward"]["grader_score"] > 0.0


def test_step_query_context_first_free(env):
    env.reset("easy")
    action = Action(
        action_type="query_context",
        query_type="error_explanation",
        query_target="binary_search",
    )
    result = env.step(action)
    assert result["reward"]["step_reward"] == 0.0
    assert result["info"]["query_result"] is not None


def test_step_query_context_second_costs(env):
    env.reset("easy")
    action = Action(
        action_type="query_context",
        query_type="error_explanation",
    )
    env.step(action)  
    result = env.step(action)  
    assert result["reward"]["step_reward"] == -0.05


def test_step_give_up(env):
    env.reset("easy")
    action = Action(
        action_type="give_up",
        final_diagnosis="I cannot find the bug",
    )
    result = env.step(action)
    assert result["done"] is True
    assert result["reward"]["grader_score"] >= 0.0


def test_step_after_done(env):
    env.reset("easy")
    action = Action(action_type="give_up", final_diagnosis="done")
    env.step(action)
    result = env.step(Action(action_type="give_up"))
    assert result["info"]["error"] is not None
    assert "already done" in result["info"]["error"].lower()


def test_step_invalid_action_type(env):
    env.reset("easy")
    action = Action(action_type="invalid_action")
    result = env.step(action)
    assert result["info"]["error"] is not None


def test_step_invalid_query_type(env):
    env.reset("easy")
    action = Action(action_type="query_context", query_type="invalid_query")
    result = env.step(action)
    assert result["reward"]["step_reward"] == -0.05
    assert result["info"]["error"] is not None




def test_state_before_reset(env):
    state = env.state()
    assert state["done"] is True
    assert state["task_id"] is None


def test_state_after_reset(env):
    env.reset("easy")
    state = env.state()
    assert state["task_id"] == "easy"
    assert state["done"] is False
    assert state["attempts_used"] == 0


def test_state_after_step(env):
    env.reset("easy")
    action = Action(
        action_type="submit_fix",
        fixed_code="def binary_search(arr, target): return -1",
        hypothesis="Testing",
    )
    env.step(action)
    state = env.state()
    assert state["attempts_used"] == 1
    assert state["step_number"] == 1
    assert len(state["all_hypotheses"]) == 1




def test_attempts_exhausted(env):
    env.reset("easy")
    for i in range(5):
        action = Action(
            action_type="submit_fix",
            fixed_code=f"def binary_search(arr, target): return {i}",
            hypothesis=f"Attempt {i + 1}",
        )
        result = env.step(action)

    
    assert result["done"] is True or result["observation"]["attempts_remaining"] == 0

    
    if not result["done"]:
        action = Action(
            action_type="submit_fix",
            fixed_code="def binary_search(arr, target): return -1",
            hypothesis="Extra attempt",
        )
        result = env.step(action)
        assert result["info"]["error"] is not None
