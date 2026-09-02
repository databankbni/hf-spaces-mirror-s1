FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CLIMAFLORA_ENV=production \
    CLIMAFLORA_DEPLOYMENT_MODE=api \
    CLIMAFLORA_SERVE_FRONTEND=false \
    CLIMAFLORA_ROOT_PATH= \
    CLIMAFLORA_API_PREFIX=/api/v1 \
    CLIMAFLORA_PUBLIC_URL=https://shugoan.com/climaflora \
    CLIMAFLORA_MASTER_DB=/data/climaflora_global_plants_v2_0.sqlite \
    CLIMAFLORA_CATALOG_DB=/data/climaflora_global_plants_v2_0.sqlite \
    CLIMAFLORA_DERIVED_DB=/data/climaflora_global_plants_v2_0.sqlite \
    CLIMAFLORA_MEDIA_DB=data/climaflora_media_v1.sqlite \
    CLIMAFLORA_CLIMATE_PROVIDER=chelsa \
    CLIMAFLORA_CLIMATE_MANIFEST=data/climate_manifest.json \
    CLIMAFLORA_SOIL_PROVIDER=soilgrids_wcs \
    CLIMAFLORA_SOILGRIDS_WCS_BASE=https://maps.isric.org/mapserv \
    CLIMAFLORA_SEARCH_VECTOR_ENABLED=true \
    CLIMAFLORA_SEARCH_VECTOR_FALLBACK_ENABLED=true \
    CLIMAFLORA_SEARCH_VECTOR_CACHE_MB=192 \
    CLIMAFLORA_MASTER_BOOTSTRAP_ENABLED=true \
    CLIMAFLORA_MASTER_BOOTSTRAP_STATUS=/data/master_bootstrap_status.json \
    CLIMAFLORA_MASTER_AUDIT_PATH=/data/master_audit.json \
    CLIMAFLORA_MASTER_EXPECTED_SHA256=1683c43c6fb1e68f9b6c6c4cd7f291642feba6c37a3691c3452b319856335c32 \
    CLIMAFLORA_MASTER_EXPECTED_SQLITE_SHA256=3e80f432ebe2b4b59fed1b76549d2fc7df4e9330f1c315ae804746b616baee55 \
    CLIMAFLORA_MASTER_EXPECTED_CATALOG_VERSION=2.0.0 \
    CLIMAFLORA_MASTER_REQUIRED_TABLES=plant_taxa,wcvp_distribution,wcvp_names,plant_index,climate_envelope,soil_source_envelope,soil_source_categorical_preference,soil_envelope,soil_categorical_preference,soil_indicator_preference,soil_geographic_prior,region_soil_summary,soil_sources,soil_envelopes,soil_preferences,soil_evidence,evidence,build_metadata,climaflora_catalog_metadata,plant_vernacular_name,plant_image_asset,plant_use,plant_use_reference,plant_trait_evidence \
    CLIMAFLORA_SCIENTIFIC_BUILD_ENABLED=false \
    CLIMAFLORA_CONSOLIDATION_ENABLED=false \
    CLIMAFLORA_CONSOLIDATED_DB=/data/climaflora_global_plants_v2_0.sqlite \
    CLIMAFLORA_CONSOLIDATED_ZST=/data/climaflora_global_plants_v2_0.sqlite.zst \
    CLIMAFLORA_CONSOLIDATION_STATUS=/data/consolidation_status.json \
    CLIMAFLORA_CONSOLIDATION_MANIFEST=data/climaflora_global_plants_v1_1.manifest.json \
    CLIMAFLORA_CONSOLIDATION_ZSTD_LEVEL=10 \
    CLIMAFLORA_CONSOLIDATION_DOWNLOAD_ENABLED=false \
    CLIMAFLORA_CATALOG_ENRICHMENT_ENABLED=false \
    CLIMAFLORA_MASTER_SOURCE_URLS=https://shugoan.com/climaflora/data/climaflora_global_plants_v2_0.sqlite.zst \
    CLIMAFLORA_CORS_ORIGINS=https://shugoan.com,https://www.shugoan.com \
    CLIMAFLORA_TRUSTED_HOSTS=*.hf.space,localhost,127.0.0.1 \
    CLIMAFLORA_ALLOW_NONSCIENTIFIC_PUBLIC=false \
    GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR \
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif \
    GDAL_HTTP_MULTIRANGE=YES \
    GDAL_HTTP_MERGE_CONSECUTIVE_RANGES=YES \
    CPL_VSIL_CURL_USE_HEAD=NO

WORKDIR /srv/climaflora

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates zstd libexpat1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 --shell /usr/sbin/nologin climaflora \
    && mkdir -p /data \
    && chown -R 1000:1000 /data /srv/climaflora

COPY pyproject.toml ./
COPY app ./app
COPY frontend ./frontend
COPY data ./data
RUN pip install . && chown -R 1000:1000 /srv/climaflora

USER 1000
EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/api/v1/health', timeout=3).read()" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips=*"]
