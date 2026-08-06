
import pytest
from env.graders import get_grader
from env.tasks.registry import get_task




def _make_dummy_attempts(n=2, tests_passed=3, tests_total=8):
    return [
        {
            "attempt_number": i + 1,
            "code_submitted": "def dummy(): pass",
            "hypothesis": "The bug is in the loop condition",
            "execution_output": f"{tests_passed} passed, {tests_total - tests_passed} failed",
            "tests_passed": tests_passed,
            "tests_total": tests_total,
            "execution_time_ms": 100,
            "timed_out": False,
        }
        for i in range(n)
    ]


def test_easy_grader_deterministic():
    grader = get_grader("easy")
    task = get_task("easy")
    attempts = _make_dummy_attempts(2, tests_passed=7, tests_total=8)
    hypotheses = ["The off by one error in the loop condition"]

    score1 = grader.score(task, attempts, 7, 8, 2, 5, hypotheses)
    score2 = grader.score(task, attempts, 7, 8, 2, 5, hypotheses)
    assert score1 == score2, f"Easy grader not deterministic: {score1} != {score2}"


def test_medium_grader_deterministic():
    grader = get_grader("medium")
    task = get_task("medium")
    attempts = _make_dummy_attempts(3, tests_passed=6, tests_total=10)
    hypotheses = ["Bug is in hash_password bytes conversion"]

    score1 = grader.score(task, attempts, 6, 10, 3, 7, hypotheses)
    score2 = grader.score(task, attempts, 6, 10, 3, 7, hypotheses)
    assert score1 == score2, f"Medium grader not deterministic: {score1} != {score2}"


def test_hard_grader_deterministic():
    grader = get_grader("hard")
    task = get_task("hard")
    
    attempts = _make_dummy_attempts(2, tests_passed=8, tests_total=8)
    hypotheses = ["race condition in increment"]

    score1 = grader.score(task, attempts, 8, 8, 2, 10, hypotheses)
    score2 = grader.score(task, attempts, 8, 8, 2, 10, hypotheses)
    assert score1 == score2, f"Hard grader not deterministic: {score1} != {score2}"




@pytest.mark.parametrize("task_id", ["easy", "medium", "hard"])
def test_grader_range_with_zero_attempts(task_id):
    grader = get_grader(task_id)
    task = get_task(task_id)
    score = grader.score(task, [], 0, task["tests_total"], 0, task["max_attempts"], [])
    assert 0.0 <= score <= 1.0, f"{task_id} grader out of range: {score}"


@pytest.mark.parametrize("task_id", ["easy", "medium", "hard"])
def test_grader_range_with_perfect_score(task_id):
    grader = get_grader(task_id)
    task = get_task(task_id)
    tests_total = task["tests_total"]
    attempts = _make_dummy_attempts(1, tests_passed=tests_total, tests_total=tests_total)
    hypotheses = ["off by one", "hash_password bytes", "race condition atomic lock"]

    score = grader.score(task, attempts, tests_total, tests_total, 1, task["max_attempts"], hypotheses)
    assert 0.0 <= score <= 1.0, f"{task_id} grader out of range: {score}"


@pytest.mark.parametrize("task_id", ["easy", "medium", "hard"])
def test_grader_range_with_all_failures(task_id):
    grader = get_grader(task_id)
    task = get_task(task_id)
    tests_total = task["tests_total"]
    attempts = _make_dummy_attempts(task["max_attempts"], tests_passed=0, tests_total=tests_total)

    score = grader.score(task, attempts, 0, tests_total, task["max_attempts"], task["max_attempts"], [])
    assert 0.0 <= score <= 1.0, f"{task_id} grader out of range: {score}"




def test_easy_dummy_agent_low_score():
    grader = get_grader("easy")
    task = get_task("easy")
    attempts = [
        {
            "attempt_number": i + 1,
            "code_submitted": "pass",
            "hypothesis": "I don't know",
            "execution_output": "0 passed, 8 failed",
            "tests_passed": 0,
            "tests_total": 8,
            "execution_time_ms": 50,
            "timed_out": False,
        }
        for i in range(5)
    ]
    score = grader.score(task, attempts, 0, 8, 5, 5, ["I don't know"] * 5)
    assert score < 0.15, f"Dummy agent scored too high on easy: {score}"


def test_easy_perfect_agent_high_score():
    grader = get_grader("easy")
    task = get_task("easy")
    attempts = [
        {
            "attempt_number": 1,
            "code_submitted": task["ground_truth"]["fixed_code"],
            "hypothesis": "The off by one error: should be left <= right",
            "execution_output": "8 passed, 0 failed",
            "tests_passed": 8,
            "tests_total": 8,
            "execution_time_ms": 50,
            "timed_out": False,
        }
    ]
    score = grader.score(task, attempts, 8, 8, 1, 5, ["The off by one error: should be left <= right"])
    assert score > 0.85, f"Perfect agent scored too low on easy: {score}"


def test_medium_red_herring_low_score():
    grader = get_grader("medium")
    task = get_task("medium")
    attempts = _make_dummy_attempts(3, tests_passed=6, tests_total=10)
    hypotheses = [
        "The bug is in authenticate_user, it's not checking credentials correctly",
        "authenticate_user should handle the case differently",
        "Fix authenticate_user to return True for valid users",
    ]
    score = grader.score(task, attempts, 6, 10, 3, 7, hypotheses)
    
    assert score < 0.60, f"Red herring agent scored too high on medium: {score}"
