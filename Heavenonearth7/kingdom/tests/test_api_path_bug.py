"""
Bug Condition Documentation — C4: getPrayerRequests() Wrong API Path

This file documents the frontend JavaScript bug C4 for the backend test suite.
The actual executable test for C4 lives in:

    frontend/src/test/bug-condition-exploration.test.ts
    → describe("C4 — getPrayerRequests API path mismatch (Bug Condition)")

--------------------------------------------------------------------
Bug C4 Summary
--------------------------------------------------------------------

FILE:     frontend/src/services/api.ts
FUNCTION: getPrayerRequests()

BUG:
  The function calls `/prayer-requests` (wrong path):

      export const getPrayerRequests = async (filters = {}) => {
          const queryString = buildQueryString(filters);
          const response = await apiRequest<{ items: PrayerRequest[] }>(
              `/prayer-requests${queryString}`   ← WRONG
          );
          return response.items;
      };

FIX:
  The FastAPI router is mounted at `/prayers`, so the correct call is:

      `/prayers${queryString}`   ← CORRECT

IMPACT:
  Any component or feature that calls getPrayerRequests() will receive a
  404 response from the backend. The admin PrayerRequests page currently
  calls `apiRequest` directly with `/prayers`, so this latent bug has not
  yet caused visible breakage — but it will when any code consumes this
  helper function.

EXPECTED COUNTEREXAMPLE (on unfixed code):
  fetch("…/prayer-requests") → FastAPI returns HTTP 404
  Expected: fetch("…/prayers") → HTTP 200 with { items: [...] }

Validates: Requirement 1.4 (bug condition), will validate 2.4 after fix.
"""

import pytest


@pytest.mark.skip(reason=(
    "C4 is a frontend JavaScript bug — see "
    "frontend/src/test/bug-condition-exploration.test.ts for the runnable test. "
    "This file documents the bug in the backend test suite for traceability."
))
def test_get_prayer_requests_calls_correct_path():
    """
    Documented here for traceability only.

    The runnable test for C4 is:
      frontend/src/test/bug-condition-exploration.test.ts
      → "C4 — getPrayerRequests API path mismatch (Bug Condition)"
      → "should fail: getPrayerRequests calls /prayer-requests instead of /prayers"

    Bug: getPrayerRequests() in api.ts calls /prayer-requests (404).
    Fix: change to /prayers (matches FastAPI router mount point).
    """
    pass
