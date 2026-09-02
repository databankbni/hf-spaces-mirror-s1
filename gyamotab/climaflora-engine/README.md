---
title: ClimaFlora Engine
emoji: 🌿
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# ClimaFlora Engine — production 0.9.23

ClimaFlora is a standalone explainable plant-adaptation engine. The scientific/API backend runs on Hugging Face; the public frontend is deployed independently on OVH at `https://shugoan.com/climaflora/`. WordPress is not part of the application architecture.

## Canonical scientific catalog v1.6

Production consumes `climaflora_global_plants_v1_6.sqlite.zst` directly.

```text
climaflora_global_plants_v1_6.sqlite.zst
  -> download from OVH
  -> zstd decompression
  -> SQLite SHA-256 verification
  -> catalog/schema validation
  -> read-only scientific audit
  -> API ready
```

Expected decompressed SQLite SHA-256:

```text
aea9ce8577d93ff7e4350f0f8f7c36a067df3014d60a7e751ce23d046202ebdb
```

The previous canonical v1.2 object is retained for rollback and must not be deleted during normal deployments.

## Scientific evidence layers

ClimaFlora keeps evidence types distinct instead of presenting every derived value as a physiological tolerance:

1. documented agronomic requirements, currently including ECOCROP;
2. expert ecological indicators, currently EIVE M/N/R on their native 0–10 scale;
3. observational realized soil niches from sPlotOpen × SoilGrids;
4. native-range geographic soil context from WCVP/TDWG × SoilGrids.

EIVE values are never converted automatically into laboratory pH, water-content or nutrient concentrations. Geographic soil priors have `confidence='PRIOR'`, remain context-only and are never used as scoring preferences.

## Soil coverage in v1.6

- 30,075 taxa have direct, expert or observational soil preference/niche information.
- 401,523 taxa have native-range geographic soil context.
- 409,566 taxa have at least one soil-context layer, approximately 97.39% of the active catalog.
- Geographic priors are structurally separate from scored soil envelopes.

The interactive local SoilGrids profile samples pH, clay, sand, silt, CEC, coarse fragments, soil organic carbon and total nitrogen at 5–15 cm. Manual user values can override individual local properties.

## Ranking policy

Method version: `climaflora-score-0.6.0`.

Candidate discovery is bi-axis when a usable local soil profile exists: ClimaFlora takes the union of strong climate candidates and strong climate+soil candidates before exact scoring. Climate and soil scores remain separately visible.

The combined score is a navigation aid, currently 75% climate and 25% soil when both axes are sufficiently known. Conservative gates remain in force:

- a climate `RED` result cannot be rescued by a good soil score;
- a climate `UNKNOWN` result cannot be promoted above a taxon with known compatible climate solely because of soil;
- regulatory vetoes remain distinct and are deprioritized;
- EIVE and geographic priors do not enter the numerical score.

## Plant images

The API and frontend are image-ready through optional image-asset metadata (`thumbnail_url`, source, license, author and attribution URL). Images are illustrative only and are never treated as evidence of botanical identification. Missing images use a neutral placeholder and thumbnails are lazy-loaded by the frontend.

The global licensed-image enrichment pipeline is a separate catalog task; production must not hotlink arbitrary third-party images without stable provenance and license metadata.

## Tests

`.github/workflows/tests.yml` runs on relevant application/test changes and checks:

- Python compilation;
- pytest regression tests;
- critical Ruff errors;
- scientific guardrails such as non-scoring geographic priors and climate RED/UNKNOWN ranking gates;
- v1.6 repository hydration and image-contract compatibility;
- extended SoilGrids SOC/nitrogen handling.

## Operational endpoints

- `/api/v1/health`
- `/api/v1/readiness`
- `/api/v1/meta`
- `/api/v1/master/status`
- `/api/v1/master/audit`
- `/api/v1/scientific/status`
- `/api/v1/scientific/method`
- `/api/v1/climate/profile`
- `/api/v1/climate/smoke`
- `/api/v1/soil/profile`
- `/api/v1/soil/smoke`
- `/api/v1/soil/validation`
- `/api/v1/plants/search`
- `/api/v1/plants/{taxon_id}/trajectory`
- `/api/v1/recommendations`

## Deployment

GitHub is the source of truth for the code. GitHub Actions may deploy the backend to Hugging Face.

**Frontend OVH — rule:** every update of the public frontend at `https://shugoan.com/climaflora/` must be performed **manually with FileZilla**, from the canonical `frontend/` directory. No GitHub Action, SFTP workflow, automatic deployment or push-triggered mechanism may publish or modify the OVH frontend.

Scientific catalog promotion uses a separate reversible workflow so application deployments do not overwrite the `data/` directory.

No DEMO fallback is shipped in production. Missing evidence remains `UNKNOWN` rather than being fabricated.
