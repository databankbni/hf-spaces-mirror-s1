# ClimaFlora Search v0.10 — Runtime architecture decision

## Status

Release candidate **0.10.0 — GO_CLEAR**.

The production scientific method remains `climaflora-score-0.6.0` and the catalog schema remains `2.0.0`. Search v0.10 changes execution architecture only; it does not change the scientific meaning of compatibility scores.

## Production catalog used for validation

All full-catalog gates use the verified ClimaFlora v2.0 catalog:

- taxa: **420,532**;
- climate-envelope rows: **2,009,625**;
- climate-envelope taxa: **401,925**;
- canonical reference counts preserved:
  - TREE: **42,528**;
  - HERB: **155,841**;
  - PALM: **2,846**;
  - TREE + FOOD_HUMAN: **1,907**.

No `TOP N`, alphabetical pre-limit or scientific candidate truncation is permitted.

## Final scientific parity

The vector engine reproduces the exhaustive SQLite reference semantics over the complete catalog.

Validated gates:

- full ranking differences: **0 / 420,532**;
- climate status parity: **exact**;
- soil status parity: **exact**;
- `UNKNOWN` parity: **exact**;
- combined ranking parity: **exact**;
- presentation/facet counts: **exact**;
- sort-key rounding: **none**.

The initial one-ULP climate discrepancy found during the architecture spike was traced to SQLite compensated `SUM(REAL)` behavior. Search v0.10 uses a vectorized Kahan-Babuska-Neumaier accumulation so the runtime reproduces the historical float64 semantics without rounding sort keys.

## Final architecture

A request now follows this model when the vector runtime is enabled:

1. acquire `ClimateProfile` and `SoilProfile` concurrently;
2. derive scientific signatures from the resolved scoring inputs;
3. load/reuse the immutable search runtime sidecar and global ordinal mapping;
4. build/reuse a global `ClimateScoreVector`;
5. build/reuse a global `SoilScoreVector`;
6. build/reuse a global combined `RankingVector`;
7. apply `life_form`, canonical function, climate-status and soil-status masks to the already-scored population;
8. paginate;
9. hydrate and explain only visible taxa.

This preserves the public funnel semantics while removing presentation filters and pagination from scientific computation.

## Runtime sidecar

The immutable catalog sidecar provides:

- stable `taxon_id -> ordinal` mapping;
- five-variable climate arrays;
- life-form masks;
- canonical function bit masks;
- catalog/runtime integrity metadata.

When vector search is enabled, the service prewarms the sidecar, climate matrix and navigation matrix at application startup. This moves the expensive static projection work out of the first user search.

## Cache architecture

Search v0.10 caches scientific vectors rather than UI views.

Independent cache identities exist for:

- climate scientific signature;
- soil scientific signature;
- combined ranking signature.

Presentation filters (`life_form`, functions, statuses), offset and limit are deliberately absent from scientific cache keys.

The current production cache is:

- process-local RAM LRU;
- byte bounded;
- default production budget: **192 MiB**;
- protected by per-key single-flight to avoid duplicate concurrent computations;
- invalidated naturally by runtime/catalog identity and independent cache-format versioning.

The immutable sidecar is persistent across process restarts. Dynamic score vectors are intentionally not persisted in v0.10 because measured recomputation is already well below the target; disk/Redis persistence would add complexity without demonstrated production benefit. This decision can be revisited from telemetry without changing `METHOD_VERSION`.

## Performance validation

Full-catalog measurements on the CI runner after runtime prewarm:

- climate + soil + combined scoring/sort: approximately **1.54 s**;
- first complete scientific environment through the vector cache service: approximately **1.75 s**;
- TREE navigation: approximately **0.158 s**;
- TREE + FOOD_HUMAN: approximately **0.166 s**;
- climate GREEN filter: approximately **0.148 s**;
- page 2: approximately **0.165 s**;
- worst measured navigation mask during parity validation: approximately **0.228 s**.

The three cached scientific layers for the reference environment consume approximately **29.4 MiB**, well below the 192 MiB budget.

The previous exhaustive SQLite reference remains available as a fallback and as a regression oracle.

## Failure behavior

Production activation keeps the historical engine as an automatic fallback:

- `CLIMAFLORA_SEARCH_VECTOR_ENABLED=true`;
- `CLIMAFLORA_SEARCH_VECTOR_FALLBACK_ENABLED=true`;
- `CLIMAFLORA_SEARCH_VECTOR_CACHE_MB=192`.

If the vector runtime fails internally, the request falls back to the exhaustive SQLite path and exposes the fallback in runtime diagnostics/warnings. SoilGrids failure behavior is unchanged: climate-only ranking remains valid and soil compatibility becomes unavailable/UNKNOWN as previously specified.

## Observability

The search response exposes runtime diagnostics including:

- runtime/cache format versions;
- engine used (`vector-v0.10` or SQLite fallback);
- profile acquisition wall time;
- scientific signatures;
- scientific/cache stage timings;
- cache-hit state for climate, soil and combined ranking when the vector path is active.

These diagnostics are execution metadata only and do not alter recommendation scores.

## Versioning rule

Execution formats remain independent from scientific semantics:

- `APP_VERSION = 0.10.0`;
- `METHOD_VERSION = climaflora-score-0.6.0`;
- `CATALOG_SCHEMA_VERSION = 2.0.0`;
- `SEARCH_RUNTIME_FORMAT_VERSION = search-runtime-1`;
- `SEARCH_CACHE_FORMAT_VERSION = search-cache-1`.

A runtime/cache implementation change must not increment `METHOD_VERSION` unless the scientific meaning of a score changes.

## Release gates

Before merge/deployment, the release candidate must keep all of the following green:

- complete unit/regression suite and lint;
- robustness workflow;
- exhaustive historical benchmark;
- full climate vector parity gate;
- full soil/combined/ranking/navigation parity gate;
- vector runtime/cache benchmark;
- fallback behavior tests.

After deployment to Hugging Face, production validation must confirm:

1. `/api/v1/health` reports app version `0.10.0`;
2. `/api/v1/recommendations/search` reports `search_runtime.engine = vector-v0.10`;
3. canonical TREE and TREE+FOOD counts remain exact;
4. repeated requests show scientific cache reuse;
5. no automatic SQLite fallback occurs during nominal requests.

Only after these checks is Search v0.10 considered production-closed.
