"""
Task Easy — Binary Search Off-By-One Bug
==========================================
Single function, one clear bug. The termination condition uses `<` instead of `<=`,
causing the function to miss the target when it's the last element.

Expected: 7 pass, 1 fail (test_finds_last_element)
"""

TASK_DESCRIPTION = """A utility module for a data processing pipeline contains a binary search function.
The function searches for a target value in a sorted list and returns its index, or -1 if not found.
One of the tests is failing — the function is not returning the correct result in all cases.
Your job is to identify the bug, form a hypothesis about the root cause, and fix it."""

BUGGY_CODE = '''def binary_search(arr: list, target: int) -> int:
    """Return the index of target in sorted arr, or -1 if not found."""
    left, right = 0, len(arr) - 1
    while left < right:          # BUG: should be left <= right
        mid = (left + right) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    return -1
'''

TEST_SUITE = '''def test_finds_first_element():
    assert binary_search([1, 3, 5, 7, 9], 1) == 0

def test_finds_middle_element():
    assert binary_search([1, 3, 5, 7, 9], 5) == 2

def test_finds_last_element():
    assert binary_search([1, 3, 5, 7, 9], 9) == 4

def test_returns_minus_one_for_missing():
    assert binary_search([1, 3, 5, 7, 9], 4) == -1

def test_single_element_found():
    assert binary_search([42], 42) == 0

def test_single_element_not_found():
    assert binary_search([42], 7) == -1

def test_empty_list():
    assert binary_search([], 5) == -1

def test_finds_second_to_last():
    assert binary_search([2, 4, 6, 8, 10], 8) == 3
'''

# The test suite formatted for sandbox execution (no pytest, direct assertions)
TEST_SUITE_EXECUTABLE = '''
_tests_passed = 0
_tests_total = 8
_failures = []

def _run_test(name, fn):
    global _tests_passed
    try:
        fn()
        _tests_passed += 1
    except AssertionError as e:
        _failures.append(f"FAILED {name}: {e}")
    except Exception as e:
        _failures.append(f"ERROR {name}: {e}")

_run_test("test_finds_first_element", lambda: test_finds_first_element())
_run_test("test_finds_middle_element", lambda: test_finds_middle_element())
_run_test("test_finds_last_element", lambda: test_finds_last_element())
_run_test("test_returns_minus_one_for_missing", lambda: test_returns_minus_one_for_missing())
_run_test("test_single_element_found", lambda: test_single_element_found())
_run_test("test_single_element_not_found", lambda: test_single_element_not_found())
_run_test("test_empty_list", lambda: test_empty_list())
_run_test("test_finds_second_to_last", lambda: test_finds_second_to_last())

for f in _failures:
    print(f)
print(f"{_tests_passed} passed, {_tests_total - _tests_passed} failed")
'''

GROUND_TRUTH = {
    "bug_location": "binary_search",
    "bug_type": "off_by_one",
    "hypothesis_keywords": ["left <= right", "termination", "last element", "off by one", "<="],
    "keyword_match_mode": "any",  # match if ANY keyword appears
    "fixed_code": '''def binary_search(arr: list, target: int) -> int:
    """Return the index of target in sorted arr, or -1 if not found."""
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
''',
}

TASK_CONFIG = {
    "task_id": "easy",
    "task_description": TASK_DESCRIPTION,
    "buggy_code": BUGGY_CODE,
    "test_suite": TEST_SUITE,
    "test_suite_executable": TEST_SUITE_EXECUTABLE,
    "ground_truth": GROUND_TRUTH,
    "max_attempts": 5,
    "max_steps": 8,
    "tests_total": 8,
    "allow_threading": False,
}
