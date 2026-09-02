# Tickets: Quality-Score Rescue

Reduce wrongful article rejections in Segmento Pulse by adding a Quality-Score Rescue fallback
to the Category Relevance Gate, and wire `irrelevant_count` into `IngestionMetrics` for
before/after measurement. Source spec: `SPEC_quality_score_rescue.md`.

Dependency shape:
  T0 → T1 (parallel with T3)
  T0 → T2 → T3

Work one ticket at a time. Clear context between tickets.

---

## Ticket 0 — pytest harness setup

**What to build:** Confirm pytest is present in the backend environment. If absent, add it
(plus `pytest-asyncio` and `pytest-mock` for async mocking in Ticket 3). Verify the harness
runs clean on a trivial smoke test. This is the shared foundation both Ticket 1 and Ticket 2
depend on before writing their RED tests.

**Blocked by:** None — can start immediately.

- [ ] Check `requirements.txt` and/or `pyproject.toml` for `pytest`, `pytest-asyncio`,
      `pytest-mock`
- [ ] If any are absent, add them (dev/test section if pyproject.toml; separate
      `requirements-dev.txt` or inline if requirements.txt only)
- [ ] Create `tests/` directory if it does not exist
- [ ] Write `tests/test_smoke.py` with one trivially passing test (`assert True`)
- [ ] Run `pytest tests/test_smoke.py -v` — must exit 0 with 1 passed
- [ ] Delete or keep `test_smoke.py` at your discretion — harness is now confirmed

---

## Ticket 1 — `QUALITY_RESCUE_THRESHOLD` constant + rescue path in `is_relevant_to_category()`

**What to build:** When an article fails the category keyword regex, instead of immediately
returning `False`, compute its quality score. If the score is ≥ `QUALITY_RESCUE_THRESHOLD`
(65), return `True` — the article is a Rescued Article and proceeds through the rest of the
pipeline unchanged. Articles that pass the regex are never touched by this path.

**Blocked by:** Ticket 0.

- [ ] Write `tests/test_quality_rescue.py` with failing tests (RED):
      - Regex-fail + quality score ≥ 65 → `is_relevant_to_category()` returns `True`
      - Regex-fail + quality score < 65 → `is_relevant_to_category()` returns `False`
      - Regex-pass + any score → `is_relevant_to_category()` returns `True`
- [ ] Run pytest — confirm all 3 tests FAIL (red state confirmed)
- [ ] Declare `QUALITY_RESCUE_THRESHOLD: int = 65` as a module-level constant in
      `data_validation.py`, immediately above `is_relevant_to_category()`
- [ ] Inside `is_relevant_to_category()`, after `pattern.search(search_text)` returns no
      match: call `calculate_quality_score(article_dict)`, compare to threshold.
      If ≥ threshold → log rescue at INFO level, return `True`.
      If < threshold → fall through to existing rejection log + `return False`.
- [ ] Run pytest — all 3 tests PASS (green)
- [ ] Function signature of `is_relevant_to_category()` is unchanged
- [ ] `_build_category_regex()`, `CATEGORY_KEYWORDS`, `redis_dedup.py`,
      `deduplication.py` are diff-clean (zero changes)

---

## Ticket 2 — `irrelevant_count` tracking in `IngestionMetrics` (with `_approx` naming)

**What to build:** Extend `IngestionMetrics.record_run()` with a new `irrelevant` keyword
argument (default 0, backward-compatible). Track it in per-run data and lifetime totals.
Surface `irrelevant_count` in `lifetime_totals` and `avg_irrelevant_rate_approx` in
`averages` in `get_stats()`. Field names use `_approx` suffix to communicate that the
rate is directionally correct but not an absolute count (Redis-dedup volume is excluded
from the denominator — see Spec).

**Blocked by:** Ticket 0.

- [ ] In `tests/test_quality_rescue.py`, add a new test class/block with failing tests (RED):
      - `record_run(…, irrelevant=10)` → `get_stats()['lifetime_totals']['irrelevant_count'] == 10`
      - Same call → latest entry in `recent_runs` has `irrelevant_count == 10` and a
        non-null `irrelevant_rate_approx`
- [ ] Run pytest — confirm new tests FAIL (red)
- [ ] Add `irrelevant: int = 0` keyword parameter to `record_run()` (after `categories_processed`)
- [ ] Add to per-run `run_data` dict:
      - `'irrelevant_count': irrelevant`
      - `'irrelevant_rate_approx': round(irrelevant / fetched * 100, 2) if fetched > 0 else 0`
- [ ] Add `self.total_irrelevant: int = 0` to `__init__`; increment with `+= irrelevant` in `record_run()`
- [ ] Add `'irrelevant_count': self.total_irrelevant` to `lifetime_totals` in `get_stats()`
- [ ] Add `'avg_irrelevant_rate_approx': round(avg_irrelevant_rate, 2)` to `averages` in
      `get_stats()` (computed as average of per-run `irrelevant_rate_approx` values)
- [ ] Run pytest — all tests PASS (green)
- [ ] All existing callers of `record_run()` compile unchanged (no positional-arg breakage)

---

## Ticket 3 — Wire `irrelevant_count` through `news_processor.py` into `record_run()`

**What to build:** The `irrelevant_count` value already present in the tuple returned by
`fetch_and_validate_category()` is currently discarded in `news_processor.py`. Wire it into
a `record_run()` call (currently missing entirely from `news_processor.py`). This closes the
measurement gap so monitoring reflects real rejection numbers.

**Blocked by:** Ticket 2 only.
(Ticket 1 and Ticket 3 can run in parallel — this ticket does not exercise the rescue path.)

- [ ] Write failing test (RED) in `tests/test_quality_rescue.py`:
      assert that after `process_category()` runs with a mocked aggregator (controlled
      valid/invalid/irrelevant counts), `get_ingestion_metrics().get_stats()`
      `['lifetime_totals']['irrelevant_count']` increments correctly.
      Use `pytest-asyncio` + `unittest.mock.AsyncMock` for async mocking.
- [ ] Run pytest — confirm new test FAILS (red)
- [ ] In `news_processor.py`, after `saved_count` is known (after the Appwrite save step),
      import `get_ingestion_metrics` from `app.services.ingestion_metrics` and add:
      ```python
      # NOTE: fetched excludes Redis-dedup volume (not returned by
      # fetch_and_validate_category); rate is directionally correct for
      # before/after comparison, not an absolute count.
      get_ingestion_metrics().record_run(
          fetched=len(articles) + invalid_count + irrelevant_count,
          saved=saved_count,
          duplicates=duplicate_count,
          errors=error_count,
          categories_processed=1,
          irrelevant=irrelevant_count,
      )
      ```
- [ ] Verify all six variables are in scope at the call site:
      `articles` (from result tuple), `invalid_count` (from result tuple),
      `irrelevant_count` (from result tuple), `saved_count` / `duplicate_count` /
      `error_count` (from `appwrite_db.save_articles()` return)
- [ ] Run pytest — all tests PASS (green)
- [ ] `redis_dedup.py` and `deduplication.py` diff-clean

---

## Final verification checklist (run after all tickets complete)

- [ ] `pytest tests/test_quality_rescue.py -v` — all tests green
- [ ] `git diff -- app/utils/redis_dedup.py app/services/deduplication.py` — empty (untouched)
- [ ] Observe logs on next ingestion run: `🚫 Rejected` count lower for articles with image /
      long description / premium source
- [ ] Monitoring endpoint that calls `get_ingestion_stats()` returns `irrelevant_count` in
      `lifetime_totals` and `avg_irrelevant_rate_approx` in `averages`
- [ ] All pre-existing tests (if any) still pass
