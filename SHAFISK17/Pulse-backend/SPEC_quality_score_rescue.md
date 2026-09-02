# Spec: Quality-Score Rescue — Reduce Wrongful Article Rejections

## Problem Statement

The ingestion pipeline's Category Relevance Gate rejects any article whose title, description,
and URL path contain no keyword matching the target category's compiled regex pattern. This is
intentional — category pages must stay relevant. However, a meaningful fraction of legitimate
tech articles from reputable sources are rejected wrongfully: they are clearly real, substantial
articles but use phrasing or jargon the keyword taxonomy hasn't yet captured.

Readers experience this as thinner category feeds than the raw article volume warrants.
Engineers see it as a high `irrelevant_count` that doesn't map to genuinely off-topic content.
The problem is currently invisible in monitoring because `irrelevant_count` is discarded before
it reaches `IngestionMetrics`.

## Solution

Two changes, independent in scope but deployed together:

**1. Quality-Score Rescue in the Category Relevance Gate.**
When an article fails the regex match, compute its `calculate_quality_score()`. If the score
is ≥ `QUALITY_RESCUE_THRESHOLD` (65), save the article anyway — it carries at least one
substantial quality signal (image, long description, or premium source), making it almost
certainly a real article worth showing. Articles scoring below 65 are still hard-rejected.
Articles that pass the regex are entirely unaffected.

**2. Track `irrelevant_count` in `IngestionMetrics`.**
Wire the `irrelevant_count` value already returned (but discarded) by
`fetch_and_validate_category()` through `news_processor.py` into `IngestionMetrics.record_run()`.
Add `irrelevant_count` as a tracked field and surface it in `get_stats()`. This is the
before/after measurement instrument — without it, we cannot prove the rescue is working.

## User Stories

1. As a reader browsing the AI category page, I want to see more articles from reputable sources
   even if their headlines use non-standard AI terminology, so that the feed feels complete.
2. As a reader on any category page, I want rescued articles to be indistinguishable in quality
   from regex-matched ones, so that relevance doesn't visibly degrade.
3. As an engineer monitoring the pipeline, I want `get_stats()` to show `irrelevant_count`
   per run, so that I can measure how many articles the Category Relevance Gate is rejecting
   before and after the rescue is deployed.
4. As an engineer, I want the Quality-Score Rescue threshold (65) declared as a named constant
   `QUALITY_RESCUE_THRESHOLD`, so that it is auditable and changeable in one place.
5. As an engineer, I want rescued articles to proceed through all downstream pipeline steps
   (Redis dedup, date normalization, image enrichment, Appwrite save) identically to
   gate-passing articles, so that no data-quality difference exists between the two paths.
6. As an engineer, I want articles that fail the regex AND have a quality score below 65 to
   still be rejected, so that the Category Relevance Gate's purpose is preserved.
7. As an engineer, I want the Scalable Bloom Filter and the Redis 48-Hour Dedup Bouncer to be
   completely untouched by this change, so that dedup integrity is guaranteed.
8. As an engineer, I want a test that proves (a) regex-fail + high score → saved, (b) regex-fail
   + low score → rejected, (c) regex-pass → unaffected regardless of score.

## Implementation Decisions

- **`QUALITY_RESCUE_THRESHOLD = 65`** declared as a module-level integer constant in
  `data_validation.py`, immediately above `is_relevant_to_category()`. Named constant, not
  an inline magic number.

- **Rescue logic location**: inside `is_relevant_to_category()`, after the regex search returns
  no match. The function currently returns `False` immediately on no-match. New behavior:
  compute `calculate_quality_score(article_dict)`, compare to threshold, return `True` if
  score ≥ threshold (Rescued Article), `False` otherwise. The function signature is unchanged.

- **Score computation at rescue time**: `calculate_quality_score()` is called only when the
  regex has already failed — it is not called on articles that pass the regex. This is a
  deliberate performance choice (no extra computation on the happy path).

- **`IngestionMetrics.record_run()` signature change** (decision-critical, from analysis):
  ```python
  # Before
  def record_run(self, fetched, saved, duplicates, errors, categories_processed): ...

  # After
  def record_run(self, fetched, saved, duplicates, errors, categories_processed, irrelevant=0): ...
  ```
  `irrelevant` is keyword-only with default 0 so all existing callers compile unchanged.

- **`get_stats()` addition**: `irrelevant_count` added to `lifetime_totals` dict and as
  `avg_irrelevant_rate_approx` (irrelevant/fetched × 100, where fetched excludes Redis-dedup
  volume — see note below) to the `averages` dict. The per-run `run_data` dict gains an
  `irrelevant_count` field and `irrelevant_rate_approx` (%). The `_approx` suffix communicates
  that the rate is directionally correct for before/after comparison but not an absolute count.

- **Wiring in `news_processor.py`**: the `irrelevant_count` value already present in the
  `result` tuple is currently discarded after line 38. We add a `record_run()` call after the
  save step using `fetched=len(raw_articles)` (not available at that point — see note below).

  > **Note:** `fetch_and_validate_category()` does not return `fetched` count today — it
  > returns `(category, valid_articles, invalid_count, irrelevant_count, relevant_count)`.
  > The closest proxy is `len(valid_articles) + invalid_count + irrelevant_count` — but that
  > misses articles lost to Redis dedup. To avoid complicating the tuple, `record_run()` in
  > `news_processor.py` will use `saved_count` (known) as `saved` and reconstruct a
  > best-effort `fetched_approx` as `len(articles) + invalid_count + irrelevant_count`. This is
  > documented in the metrics output as "approximate fetched".
  > The rate fields are named `irrelevant_rate_approx` / `avg_irrelevant_rate_approx` to
  > communicate this limitation explicitly. The call site in `news_processor.py` carries a
  > one-line comment: `# NOTE: fetched_approx excludes Redis-dedup volume (not returned by
  > # fetch_and_validate_category); rate is directionally correct for before/after comparison, not an absolute count.`

- **No changes to**: `_build_category_regex()`, `redis_dedup.py`, `deduplication.py`,
  `sanitize_article()`, `is_valid_article()`, any provider file, any route file.

## Testing Decisions

Tests verify behavior through the public interface of `is_relevant_to_category()` and
`IngestionMetrics`. No internal state is inspected.

**Seams:**
1. `is_relevant_to_category(article, category)` → return value (`True`/`False`)
2. `IngestionMetrics.get_stats()` after `record_run(…, irrelevant=N)` calls → dict shape

**Test cases:**
1. Regex-fail + quality score ≥ 65 → `is_relevant_to_category()` returns `True` (Rescued).
2. Regex-fail + quality score < 65 → `is_relevant_to_category()` returns `False` (Rejected).
3. Regex-pass + any score → `is_relevant_to_category()` returns `True` (unaffected).
4. `record_run(…, irrelevant=10)` → `get_stats()['lifetime_totals']['irrelevant_count']` == 10.
5. `record_run(…, irrelevant=10)` → latest run in `get_stats()['recent_runs']` has
   `irrelevant_count == 10` and a non-null `irrelevant_rate`.

**Test runner**: pytest (confirm exists in backend; if not, note in ticket).
**Test file**: `tests/test_quality_rescue.py` (new file).
**Prior art**: no existing tests in the backend — bootstrap from scratch if needed.

## Out of Scope

- Changing `_build_category_regex()`, `CATEGORY_KEYWORDS`, or any keyword list.
- Touching `redis_dedup.py`, `deduplication.py`, or any dedup logic.
- Changing `calculate_quality_score()`'s internal formula.
- Any provider file, route file, or frontend code.
- Making `QUALITY_RESCUE_THRESHOLD` configurable via env var (future concern).
- Adding a `rescued_count` as a separate metric field (rescued articles are already
  counted in `saved` — adding a new field is a future enhancement).

## Further Notes

- The "Official Blog Bypass" already in `is_relevant_to_category()` (line 540) is a precedent
  that inline quality/source bypasses belong in this function. The Quality-Score Rescue follows
  the same pattern.
- `ingestion_metrics.record_run()` is currently never called from `news_processor.py` at all
  (BUG-003 comment in `scheduler.py` acknowledges metrics were moved to the worker). The
  missing call is added as part of this ticket.
- Before/after measurement: `GET /admin/ingestion-metrics` or the equivalent endpoint that
  calls `get_ingestion_stats()` will surface `avg_irrelevant_rate` after deployment.
  Before-state: observe `irrelevant_count` in logs (the `🚫 Rejected` prints and the
  `TAG_GATE` log line already emit these numbers).
