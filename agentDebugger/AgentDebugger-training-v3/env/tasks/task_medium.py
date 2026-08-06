"""
Task Medium — Red Herring Authentication Bug
==============================================
Three interdependent functions: hash_password, validate_password, authenticate_user.
The error points to authenticate_user but the actual bug is in hash_password.

Bug: hash_password wraps hexdigest() result in str(bytes()), adding b'' prefix.
When passwords are stored via a "direct insert" path that doesn't use hash_password,
the comparison fails because the stored hash is clean but the computed hash has b'' prefix.

Expected: 6 pass, 4 fail
"""

TASK_DESCRIPTION = """A user authentication module with three functions: hash_password, validate_password, 
and authenticate_user. Some tests are failing with errors pointing to authenticate_user returning False 
when it should return True. The module handles password hashing with MD5, password validation by comparing 
hashes, and user authentication against a user database. Debug the module to make all tests pass."""


BUGGY_CODE = '''import hashlib

def hash_password(password: str) -> str:
    """Hash a password using MD5 and return the hex digest string."""
    password_bytes = password.encode('utf-8')
    hash_obj = hashlib.md5(password_bytes)
    hex_digest = hash_obj.hexdigest()
    # BUG: unnecessary bytes conversion corrupts the hash string
    # str(bytes(...)) produces "b'...'" instead of just "..."
    return str(bytes(hex_digest, 'ascii'))

def validate_password(password: str, stored_hash: str) -> bool:
    """Check if password matches the stored hash."""
    computed_hash = hash_password(password)
    return computed_hash == stored_hash

def authenticate_user(username: str, password: str, user_db: dict) -> bool:
    """Authenticate a user against the database.
    
    Args:
        username: The username to authenticate
        password: The password to validate
        user_db: Dict mapping usernames to {\'password_hash\': str, \'active\': bool}
    
    Returns:
        True if user exists, is active, and password matches
    """
    if username not in user_db:
        return False
    user = user_db[username]
    if not user.get(\'active\', False):
        return False
    return validate_password(password, user[\'password_hash\'])
'''

TEST_SUITE = '''import hashlib

# ── Helper: create user_db entries the "correct" way (as a real app would) ──
def _make_hash(password):
    """This is how the registration system stores passwords — using hexdigest directly."""
    return hashlib.md5(password.encode('utf-8')).hexdigest()

def _build_user_db():
    """Build a test user database with properly hashed passwords."""
    return {
        'alice': {'password_hash': _make_hash('password123'), 'active': True},
        'bob': {'password_hash': _make_hash('securepass'), 'active': True},
        'charlie': {'password_hash': _make_hash('charlie_pw'), 'active': False},
        'diana': {'password_hash': _make_hash('d1@n@_pass'), 'active': True},
    }

# ── Tests that PASS (6) — these don't hit the hash mismatch ──────────────────

def test_hash_returns_string():
    result = hash_password("test")
    assert isinstance(result, str), f"hash_password should return str, got {type(result)}"

def test_hash_deterministic():
    h1 = hash_password("same_input")
    h2 = hash_password("same_input")
    assert h1 == h2, "Same input must produce same hash"

def test_hash_different_inputs():
    h1 = hash_password("password1")
    h2 = hash_password("password2")
    assert h1 != h2, "Different inputs should produce different hashes"

def test_unknown_user_rejected():
    db = _build_user_db()
    assert authenticate_user('unknown', 'password123', db) == False

def test_inactive_user_rejected():
    db = _build_user_db()
    assert authenticate_user('charlie', 'charlie_pw', db) == False

def test_wrong_password_rejected():
    db = _build_user_db()
    assert authenticate_user('alice', 'wrong_password', db) == False

# ── Tests that FAIL (4) — these expose the hash mismatch ─────────────────────

def test_alice_correct_password():
    db = _build_user_db()
    result = authenticate_user('alice', 'password123', db)
    assert result == True, f"authenticate_user('alice', 'password123') returned {result}, expected True"

def test_bob_correct_password():
    db = _build_user_db()
    result = authenticate_user('bob', 'securepass', db)
    assert result == True, f"authenticate_user('bob', 'securepass') returned {result}, expected True"

def test_diana_correct_password():
    db = _build_user_db()
    result = authenticate_user('diana', 'd1@n@_pass', db)
    assert result == True, f"authenticate_user('diana', 'd1@n@_pass') returned {result}, expected True"

def test_validate_password_direct():
    stored = _make_hash('mypassword')
    result = validate_password('mypassword', stored)
    assert result == True, f"validate_password with correct password returned {result}, expected True"
'''

TEST_SUITE_EXECUTABLE = '''
import hashlib

# ── Helper ──
def _make_hash(password):
    return hashlib.md5(password.encode('utf-8')).hexdigest()

def _build_user_db():
    return {
        'alice': {'password_hash': _make_hash('password123'), 'active': True},
        'bob': {'password_hash': _make_hash('securepass'), 'active': True},
        'charlie': {'password_hash': _make_hash('charlie_pw'), 'active': False},
        'diana': {'password_hash': _make_hash('d1@n@_pass'), 'active': True},
    }

_tests_passed = 0
_tests_total = 10
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

# 6 passing tests
_run_test("test_hash_returns_string", lambda: test_hash_returns_string())
_run_test("test_hash_deterministic", lambda: test_hash_deterministic())
_run_test("test_hash_different_inputs", lambda: test_hash_different_inputs())
_run_test("test_unknown_user_rejected", lambda: test_unknown_user_rejected())
_run_test("test_inactive_user_rejected", lambda: test_inactive_user_rejected())
_run_test("test_wrong_password_rejected", lambda: test_wrong_password_rejected())

# 4 failing tests
_run_test("test_alice_correct_password", lambda: test_alice_correct_password())
_run_test("test_bob_correct_password", lambda: test_bob_correct_password())
_run_test("test_diana_correct_password", lambda: test_diana_correct_password())
_run_test("test_validate_password_direct", lambda: test_validate_password_direct())

for f in _failures:
    print(f)
print(f"{_tests_passed} passed, {_tests_total - _tests_passed} failed")
'''

GROUND_TRUTH = {
    "bug_location": "hash_password",
    "bug_type": "bytes_str_conversion",
    "hypothesis_keywords": ["hash_password", "bytes", "str(", "hexdigest", "encoding", "b'"],
    "keyword_match_mode": "hash_password_plus_one",  # must mention "hash_password" AND at least 1 other
    "red_herring_keyword": "authenticate_user",  # hypothesis mentioning ONLY this scores 0.0
    "fixed_code": '''import hashlib

def hash_password(password: str) -> str:
    """Hash a password using MD5 and return the hex digest string."""
    password_bytes = password.encode('utf-8')
    hash_obj = hashlib.md5(password_bytes)
    return hash_obj.hexdigest()

def validate_password(password: str, stored_hash: str) -> bool:
    """Check if password matches the stored hash."""
    computed_hash = hash_password(password)
    return computed_hash == stored_hash

def authenticate_user(username: str, password: str, user_db: dict) -> bool:
    """Authenticate a user against the database."""
    if username not in user_db:
        return False
    user = user_db[username]
    if not user.get('active', False):
        return False
    return validate_password(password, user['password_hash'])
''',
}

TASK_CONFIG = {
    "task_id": "medium",
    "task_description": TASK_DESCRIPTION,
    "buggy_code": BUGGY_CODE,
    "test_suite": TEST_SUITE,
    "test_suite_executable": TEST_SUITE_EXECUTABLE,
    "ground_truth": GROUND_TRUTH,
    "max_attempts": 7,
    "max_steps": 15,
    "tests_total": 10,
    "allow_threading": False,
}
