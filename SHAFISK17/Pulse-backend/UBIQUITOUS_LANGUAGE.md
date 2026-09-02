# Segmento Pulse Backend — Ubiquitous Language

This file defines the canonical shared vocabulary for the SegmentoPulse backend codebase.
**This is separate from the frontend's `UBIQUITOUS_LANGUAGE.md`.** Do not merge the two.
All engineers, agents, and reviewers use these exact terms in code, comments, specs, tickets,
and commit messages.

---

## Ingestion Pipeline

| Term | Definition | Aliases to avoid |
|------|-----------|-----------------|
| **Category Relevance Gate** | +
The validation step inside `fetch_and_validate_category()` that calls `is_relevant_to_category()`. An article that fails this gate is counted as an **Irrelevant Rejection** and discarded before the Redis dedup check. Distinct from the Basic Validation Gate (title/URL/date checks) and the Redis 48-Hour Dedup Bouncer. | Keyword filter, category check, regex filter |
| **Irrelevant Rejection** | An article discarded at the Category Relevance Gate because no keyword in its title, description, or URL path matched the compiled regex pattern for the target category. Tracked by `IngestionMetrics` as `irrelevant_count`. | Keyword rejection, regex miss, category drop |
| **Quality-Score Rescue** | The fallback path inside `is_relevant_to_category()` that saves an article which fails the Category Relevance Gate, provided its `calculate_quality_score()` output is ≥ `QUALITY_RESCUE_THRESHOLD` (65). An article rescued this way is counted as a **Rescued Article**, not an Irrelevant Rejection. The rescue path does not touch and is entirely independent from the Redis 48-Hour Dedup Bouncer and the Scalable Bloom Filter. | Score bypass, quality fallback, score override |
| **Rescued Article** | An article that failed the Category Relevance Gate regex match but was saved anyway because its quality score was ≥ 65. It is treated identically to a gate-passing article for all downstream pipeline steps (dedup, date normalization, image enrichment, Appwrite save). | Bypassed article, fallback article |
| **QUALITY_RESCUE_THRESHOLD** | The integer constant (value: **65**) used by the Quality-Score Rescue path. Represents base score (50) plus at least one substantial quality signal: image present (+20), description > 100 chars (+15), or premium source (+15), assuming no long-title penalty (–10). This value is declared as a module-level constant in `data_validation.py` and must not be changed without updating this glossary. | Rescue score, bypass score, quality cutoff |
| **Basic Validation Gate** | The `is_valid_article()` check that runs before the Category Relevance Gate. Rejects articles missing a title, URL, or parseable publication date within the rolling IST window. Tracked as `invalid_count`. | Basic check, structural validation |
| **Redis 48-Hour Dedup Bouncer** | The `is_url_seen_or_mark()` call that runs after the Category Relevance Gate. Uses a Redis SET NX with a 172,800-second TTL to prevent re-saving URLs already ingested in the last 48 hours. Completely separate from both the Category Relevance Gate and the Scalable Bloom Filter. | Redis dedup, URL dedup |
| **Scalable Bloom Filter** | The `URLFilter` in `deduplication.py`, a disk-persisted probabilistic data structure for long-horizon URL tracking. Separate service, not called in `fetch_and_validate_category()`. Must not be confused with the Redis 48-Hour Dedup Bouncer. | Bloom filter dedup, URL filter |
| **Ingestion Metrics** | The `IngestionMetrics` singleton that records per-run statistics: `fetched`, `saved`, `duplicates`, `errors`, and (after this task) `irrelevant_count`. Exposed via `get_stats()`. Rate fields for irrelevant rejections are named `irrelevant_rate_approx` and `avg_irrelevant_rate_approx` — the `_approx` suffix signals that the denominator (`fetched`) excludes the Redis-dedup volume, which is not returned by `fetch_and_validate_category()`. The rates are directionally correct for before/after comparison of the Quality-Score Rescue, not absolute counts. The primary measurement instrument for this feature. | Ingestion stats, pipeline metrics |

---

## Top Git Repositories

| Term | Definition | Aliases to avoid |
|------|-----------|-----------------|
| **Top Git Repositories** | The distinct data vertical and Appwrite collection for storing top open-source projects ingested via the GitHub Search API. Completely separate from the primary Articles collection. Routed correctly by `get_collection_id()`. | GitHub Repos, Top Repos, Git category |
| **Upsert Engagement Preservation** | The backend database logic inside `GithubReposAggregator.run()` that distinguishes between new repositories (creates) and existing ones (updates), ensuring engagement metrics (likes, dislikes, views) are strictly preserved across sync cycles. | Repo update, sync merge |
