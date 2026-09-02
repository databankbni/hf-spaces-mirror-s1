# Hugging Face Space variables — production 0.9.39

The Dockerfile embeds these production defaults. The application version changes independently from the catalog version; the production scientific catalog is v1.9.0.

```text
CLIMAFLORA_ENV=production
CLIMAFLORA_DEPLOYMENT_MODE=api
CLIMAFLORA_SERVE_FRONTEND=false
CLIMAFLORA_ROOT_PATH=
CLIMAFLORA_PUBLIC_URL=https://shugoan.com/climaflora
CLIMAFLORA_MASTER_DB=/data/climaflora_global_plants_v1_9.sqlite
CLIMAFLORA_CATALOG_DB=/data/climaflora_global_plants_v1_9.sqlite
CLIMAFLORA_DERIVED_DB=/data/climaflora_global_plants_v1_9.sqlite
CLIMAFLORA_MASTER_BOOTSTRAP_ENABLED=true
CLIMAFLORA_MASTER_SOURCE_URLS=https://shugoan.com/climaflora/data/climaflora_global_plants_v1_9.sqlite.zst
CLIMAFLORA_MASTER_EXPECTED_SHA256=5851572bd48dea34d3b69e16a78126d1ac149c907e5db8fa7af1bc36812779dc
CLIMAFLORA_MASTER_EXPECTED_SQLITE_SHA256=d3c50da95584ad24cf69fce6965c0102f773cf90f4a5fed21a607ef4fdb5b33c
CLIMAFLORA_MASTER_EXPECTED_CATALOG_VERSION=1.9.0
CLIMAFLORA_MASTER_REQUIRED_TABLES=plant_taxa,wcvp_distribution,wcvp_names,plant_index,climate_envelope,soil_source_envelope,soil_source_categorical_preference,soil_envelope,soil_categorical_preference,soil_indicator_preference,soil_geographic_prior,region_soil_summary,soil_sources,soil_envelopes,soil_preferences,soil_evidence,evidence,build_metadata,climaflora_catalog_metadata,plant_vernacular_name,plant_image_asset,plant_use,plant_use_reference,plant_trait_evidence
CLIMAFLORA_CATALOG_ENRICHMENT_ENABLED=false
CLIMAFLORA_CLIMATE_PROVIDER=chelsa
CLIMAFLORA_CLIMATE_MANIFEST=data/climate_manifest.json
CLIMAFLORA_SOIL_PROVIDER=soilgrids_wcs
CLIMAFLORA_SOILGRIDS_WCS_BASE=https://maps.isric.org/mapserv
CLIMAFLORA_SCIENTIFIC_BUILD_ENABLED=false
CLIMAFLORA_CONSOLIDATION_ENABLED=false
CLIMAFLORA_CORS_ORIGINS=https://shugoan.com,https://www.shugoan.com
CLIMAFLORA_TRUSTED_HOSTS=*.hf.space
CLIMAFLORA_ALLOW_NONSCIENTIFIC_PUBLIC=false
```

Runtime v0.9.20+ samples the local SoilGrids profile for pH, clay, sand, silt, CEC, coarse fragments, soil organic carbon and nitrogen. EIVE indicators and native-range geographic priors are read from the catalog as context; geographic priors are never admitted into the scoring path. v1.7 adds sourced vernacular names and licensed media metadata; v1.8 adds sourced useful-plant functions and life-form evidence; v1.9 consolidates the edaphic evidence, enforces the minimum occurrence sample threshold, repairs legacy ECOCROP categorical parsing and preserves auditable source data without changing the climate scoring method.

Rollback remains possible to retained v1.8, v1.7, v1.6 or v1.2 catalog objects. These rollback objects remain on OVH and must not be deleted during normal deployments.
