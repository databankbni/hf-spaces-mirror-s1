"""
Task Hard — Concurrency Race Condition
========================================
Implementation of a thread-safe counter with a classic race condition. 
The read-modify-write cycle is non-atomic, leading to inconsistent 
states under heavy concurrent load.

Task Configuration:
- Type: Concurrency / Race Condition
- Requirements: Proper synchronization and atomicity
- Execution: Sandbox threading support enabled
"""

TASK_DESCRIPTION = """A thread-safe connection counter used in a web server to track active connections.
The ConnectionCounter class uses threading locks for thread safety, but some users report that under 
heavy concurrent load, the counter occasionally shows incorrect values. All existing unit tests pass.
Your job is to identify the concurrency bug, design a test that surfaces it, and fix the implementation.

IMPORTANT: All 8 existing tests pass. The bug only manifests under concurrent access with multiple threads.
You need to think about what could go wrong when multiple threads call increment() simultaneously."""

BUGGY_CODE = '''import threading

class ConnectionCounter:
    """Thread-safe connection counter for a web server."""
    
    def __init__(self):
        self.count = 0
        self._lock = threading.Lock()
    
    def increment(self):
        with self._lock:
            current = self.count      # read
        # LOCK RELEASED HERE — race window
        new_val = current + 1         # modify  
        with self._lock:
            self.count = new_val      # write
    
    def decrement(self):
        with self._lock:
            current = self.count
        # LOCK RELEASED HERE — race window
        new_val = current - 1
        with self._lock:
            self.count = new_val
    
    def get_count(self) -> int:
        with self._lock:
            return self.count
    
    def reset(self):
        with self._lock:
            self.count = 0
'''

TEST_SUITE = '''import threading

def test_initial_count_zero():
    counter = ConnectionCounter()
    assert counter.get_count() == 0

def test_single_increment():
    counter = ConnectionCounter()
    counter.increment()
    assert counter.get_count() == 1

def test_single_decrement():
    counter = ConnectionCounter()
    counter.increment()
    counter.decrement()
    assert counter.get_count() == 0

def test_multiple_increments():
    counter = ConnectionCounter()
    for _ in range(10):
        counter.increment()
    assert counter.get_count() == 10

def test_multiple_decrements():
    counter = ConnectionCounter()
    for _ in range(10):
        counter.increment()
    for _ in range(5):
        counter.decrement()
    assert counter.get_count() == 5

def test_increment_then_decrement():
    counter = ConnectionCounter()
    counter.increment()
    counter.increment()
    counter.increment()
    counter.decrement()
    assert counter.get_count() == 2

def test_get_count_returns_int():
    counter = ConnectionCounter()
    counter.increment()
    result = counter.get_count()
    assert isinstance(result, int), f"get_count should return int, got {type(result)}"

def test_reset_works():
    counter = ConnectionCounter()
    for _ in range(5):
        counter.increment()
    counter.reset()
    assert counter.get_count() == 0
'''

TEST_SUITE_EXECUTABLE = '''
import threading

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
        _failures.append(f"ERROR {name}: {type(e).__name__}: {e}")

_run_test("test_initial_count_zero", lambda: test_initial_count_zero())
_run_test("test_single_increment", lambda: test_single_increment())
_run_test("test_single_decrement", lambda: test_single_decrement())
_run_test("test_multiple_increments", lambda: test_multiple_increments())
_run_test("test_multiple_decrements", lambda: test_multiple_decrements())
_run_test("test_increment_then_decrement", lambda: test_increment_then_decrement())
_run_test("test_get_count_returns_int", lambda: test_get_count_returns_int())
_run_test("test_reset_works", lambda: test_reset_works())

for f in _failures:
    print(f)
print(f"{_tests_passed} passed, {_tests_total - _tests_passed} failed")
'''

GROUND_TRUTH = {
    "bug_location": "increment AND decrement",
    "bug_type": "race_condition",
    "hypothesis_keywords": [
        "race condition", "atomic", "lock", "read-modify-write",
        "interleaving", "not thread-safe", "release the lock"
    ],
    "keyword_match_mode": "any",
    "fixed_code": '''import threading

class ConnectionCounter:
    """Thread-safe connection counter for a web server."""
    
    def __init__(self):
        self.count = 0
        self._lock = threading.Lock()
    
    def increment(self):
        with self._lock:
            self.count += 1
    
    def decrement(self):
        with self._lock:
            self.count -= 1
    
    def get_count(self) -> int:
        with self._lock:
            return self.count
    
    def reset(self):
        with self._lock:
            self.count = 0
''',
}

TASK_CONFIG = {
    "task_id": "hard",
    "task_description": TASK_DESCRIPTION,
    "buggy_code": BUGGY_CODE,
    "test_suite": TEST_SUITE,
    "test_suite_executable": TEST_SUITE_EXECUTABLE,
    "ground_truth": GROUND_TRUTH,
    "max_attempts": 10,
    "max_steps": 25,
    "tests_total": 8,
    "allow_threading": True,
}
