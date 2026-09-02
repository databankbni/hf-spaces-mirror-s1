# ClimaFlora — Project memory

Last updated: 2026-08-20

## Architecture

- ClimaFlora is a standalone web application, independent from WordPress.
- Public frontend: OVH under `https://shugoan.com/climaflora/`.
- Scientific/backend engine: Hugging Face Space `gyamotab/climaflora-engine`.
- GitHub repository and source of truth: `GuilhemBato/climaflora-engine`.
- Production runtime/package: `0.9.32`.
- Scientific scoring method: `climaflora-score-0.6.0`.
- Production scientific catalog: v1.8 (`climaflora_global_plants_v1_8.sqlite`).
- `CATALOG_SCHEMA_VERSION = 1.8.0`.
- Retained rollback catalogs on OVH: v1.7, v1.6 and v1.2. They must not be deleted during normal deployments.

## Production deployment

### GitHub -> Hugging Face

Workflow: `.github/workflows/deploy-huggingface.yml`.
A non-`.github` push to `main` deploys the repository to Space `gyamotab/climaflora-engine` and synchronizes production catalog variables.

Current production variables point to catalog v1.8 with exact expected hashes:

- SQLite SHA-256: `d9632aea3d9d37195884d7d3beffc48147f5e51b1c3490606d6d0fae3be51722`
- zstd SHA-256: `5ad8726fdb22af9f325d3b724a7d32ccf92077a38c6fb245e612d0bb95fe5e07`
- expected catalog version: `1.8.0`
- required v1.8 tables include `plant_vernacular_name`, `plant_image_asset`, `plant_use`, `plant_use_reference`, `plant_trait_evidence` in addition to the scientific climate/soil tables.

### GitHub -> OVH

Workflow: `.github/workflows/deploy-ovh.yml`.
Only frontend assets are deployed non-destructively so `data/`, scientific catalogs and plant media remain preserved.

Catalog promotion uses dedicated reversible workflows and exact public hash verification before runtime activation.

## Scientific catalog history relevant to production

### v1.6 — soil context baseline

- Geographic-prior taxa: 401,523.
- Geographic priors use `confidence='PRIOR'` and `scoring_enabled=0` for every row.
- SQLite SHA-256: `aea9ce8577d93ff7e4350f0f8f7c36a067df3014d60a7e751ce23d046202ebdb`.
- zstd SHA-256: `752ede1549132a0a2df9a531448737a238268e327507f716ebec0939be73bc96`.
- v1.6 remains retained as a rollback target.

### v1.7 — vernacular names and media — READY, PROMOTED, RETAINED

- Promotion status: `uploaded_verified`.
- Source build run: `32281989340`.
- Catalog version: `1.7.0`.
- SQLite SHA-256: `be5554f8d095427e63583f1bbc72927a7f681480bb45d0329c17946f4f9ea27e`.
- zstd SHA-256: `df88b1dc8ef2e5eda2b6ced135319eb720944ee43ef984835ceba99c325e05ed`.
- media archive SHA-256: `36a36cd828880a17ee8ebb3389a4ccaec7c003fe44e295c184ef7f4d94d81270`.
- 478 local thumbnails were materialized from reusable licensed GBIF media; 5 materialization failures were retained as failures rather than silently substituted.
- Image records retain source, original URL, license, author and attribution URL.
- NC/ND/unknown licenses are rejected for local materialization.
- `image_identification_evidence=false`: images are illustrative only and never evidence for identification, adaptation or scoring.
- Taxonomic linkage is exact/deterministic only; no fuzzy fallback.
- v1.7 remains retained as the immediate rollback target.

## Priority 5 — COMPLETE

Priority 5 addressed user-visible information gaps while preserving scientific provenance and score semantics.

### v1.8 — functions/usages and life-form enrichment — READY, PROMOTED, PRODUCTION

Build candidate:

- successful build run: `32297916832`
- source commit: `ffa6c937c184d1d2863fcb8fe970b01f619404d1`
- base catalog: v1.7
- catalog version: `1.8.0`
- plants retained: 420,532
- SQLite SHA-256: `d9632aea3d9d37195884d7d3beffc48147f5e51b1c3490606d6d0fae3be51722`
- zstd SHA-256: `5ad8726fdb22af9f325d3b724a7d32ccf92077a38c6fb245e612d0bb95fe5e07`

Functions/usages from WCUPS 2020, Royal Botanic Gardens Kew, CC BY 4.0:

- `plant_use` rows: 74,648
- taxa with WCUPS uses: 39,884
- reference/provenance rows: 167,860
- exact IPNI-LSID taxon matches: 39,828 taxa
- exact scientific-name matches: 60 taxa
- coarse function labels added: 109
- taxa with function labels after enrichment: 35,041

Life-form enrichment from the auditable global growth-form dataset:

- life-form taxa before: 325,029
- life-form taxa after: 326,169
- taxa added: 1,140
- new life-form evidence rows: 1,140

Scientific safeguards:

- taxonomy policy: exact deterministic WCVP linkage only; no fuzzy matching
- no invented traits or usages
- source/provenance rows retained for enrichment evidence
- `images_identification_evidence=false`
- `soil_geographic_prior` scoring-enabled rows: 0
- media attribution/license semantics from v1.7 are preserved

### v1.8 OVH promotion

- promotion status: `uploaded_verified`
- public catalog object verified byte-for-byte before activation
- rollback objects retained: v1.7, v1.6, v1.2
- current public zstd SHA-256: `5ad8726fdb22af9f325d3b724a7d32ccf92077a38c6fb245e612d0bb95fe5e07`

### v1.8 production verification

Final production verification recorded at `2026-08-19T23:08:37.590611+00:00`:

- status: `ready`
- app version: `0.9.32`
- catalog filename: `climaflora_global_plants_v1_8.sqlite`
- catalog version/schema: `1.8.0`
- `scientific_ready=true`
- master bootstrap phase: `ready`
- master ready: `true`
- geographic-prior scoring safety: `true`
- minimum verified function/use coverage: >=39,000 taxa
- minimum verified new life-form evidence: >=1,000 rows
- rollback catalogs retained: v1.7, v1.6, v1.2

Priority 5 is therefore closed. The next major workstream is frontend/UX exploitation of the new v1.7/v1.8 data: names, thumbnails, functions/usages, life-form, filters, plant detail views, comparison and future account/project/monetization layers.

## Runtime/scoring safeguards that remain invariant

- Climate and soil scores remain independent and explainable.
- Combined navigation score uses climate + soil only when both axes are sufficiently known.
- Climate RED cannot be rescued by soil.
- Climate UNKNOWN cannot be promoted above known-compatible climate solely because of soil.
- Regulatory veto remains a separate final constraint.
- EIVE indicators and native-range geographic priors remain context only and are excluded from numerical ranking.
- Every `soil_geographic_prior` row must remain `scoring_enabled=0`.
- Unknown remains UNKNOWN; missing evidence must not be converted into invented tolerance.
- Non-finite numeric inputs are treated as unavailable/UNKNOWN.
- Taxonomy remains exact/deterministic for enrichment; no fuzzy matching without an explicit future design decision.
- Images remain illustrative only; no image is used as botanical identification or adaptation evidence.

## Current performance baseline

- Runtime 0.9.29 campaign established <10 s for a new warm location and <1.5 s for an identical repeat while preserving deterministic results.
- Identical-repeat benchmark after caching was approximately 1 s.
- Priority 5 did not intentionally change scientific ranking semantics or the scoring method version (`climaflora-score-0.6.0`).

## Next workstream — frontend and productization

Frontend should now expose Priority 5 data without weakening evidence semantics:

- vernacular name as primary display name where available, scientific name always visible
- licensed thumbnail with attribution and neutral placeholder when absent
- life-form and documented functions/usages
- clear climate/soil adaptation explanation and confidence/data-availability cues
- filters only for attributes actually supported by catalog evidence
- detailed plant view with source/provenance separation
- comparison and future saved palette/project concepts
- responsive/mobile behavior and progressive loading

Future monetization architecture should be anticipated without degrading free scientific search or biasing rankings. Paid layers should primarily add saved projects, advanced comparison, exports, multi-site/pro workflows and API/B2B capabilities. Commercial/affiliate relationships must never influence scientific ranking.