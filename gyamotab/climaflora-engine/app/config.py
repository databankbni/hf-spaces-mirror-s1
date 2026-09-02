import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CLIMAFLORA_", extra="ignore")

    env: str = "production"
    deployment_mode: str = "api"  # combined | api
    serve_frontend: bool = False
    root_path: str = ""
    api_prefix: str = "/api/v1"
    public_url: str = "https://shugoan.com/climaflora"
    master_db: str = "/data/climaflora_global_plants_v2_0.sqlite"  # canonical scientific catalog
    catalog_db: str = "/data/climaflora_global_plants_v2_0.sqlite"  # direct alias to canonical master
    derived_db: str = "/data/climaflora_global_plants_v2_0.sqlite"  # legacy alias
    media_db: str = "/data/climaflora_global_plants_v2_0.sqlite"  # integrated descriptive media fallback
    climate_provider: str = "chelsa"
    climate_manifest: str = "data/climate_manifest.json"
    min_known_weight: float = 0.50
    candidate_pool_limit: int = 1000
    soil_provider: str = "soilgrids_wcs"
    soilgrids_wcs_base: str = "https://maps.isric.org/mapserv"
    # v0.10 vector search remains opt-in until full API/production validation.
    search_vector_enabled: bool = False
    search_vector_fallback_enabled: bool = True
    cors_origins: str = (
        "https://shugoan.com,https://www.shugoan.com,"
        "http://localhost:8080,http://127.0.0.1:8080,"
        "http://localhost:8000,http://127.0.0.1:8000"
    )
    trusted_hosts: str = "shugoan.com,www.shugoan.com,*.hf.space,localhost,127.0.0.1,testserver"
    map_tile_url: str = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    map_attribution: str = "&copy; OpenStreetMap contributors"
    map_max_zoom: int = 19
    allow_nonscientific_public: bool = False
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    sostagora_wordpress_exchange_url: str = (
        "https://shugoan.com/wp-json/climaflora/v1/sostagora/exchange"
    )
    sostagora_redirect_url: str = "https://shugoan.com/climaflora/?sostagora=success"
    stripe_restricted_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_plus_monthly: str = ""
    stripe_price_plus_yearly: str = ""
    stripe_price_pro_monthly: str = ""
    stripe_price_pro_yearly: str = ""
    stripe_customer_portal_configuration: str = ""
    billing_enabled: bool = False
    billing_success_url: str = "https://shugoan.com/climaflora/tarifs.html?checkout=success"
    billing_cancel_url: str = "https://shugoan.com/climaflora/tarifs.html?checkout=cancel"
    master_bootstrap_enabled: bool = True
    master_bootstrap_status: str = "/data/master_bootstrap_status.json"
    master_audit_path: str = "/data/master_audit.json"
    scientific_build_enabled: bool = False
    scientific_build_status: str = "/data/scientific_build_status.json"
    consolidation_enabled: bool = False
    consolidated_db: str = "/data/climaflora_global_plants_v2_0.sqlite"
    consolidated_zst: str = "/data/climaflora_global_plants_v2_0.sqlite.zst"
    consolidation_status: str = "/data/consolidation_status.json"
    consolidation_manifest: str = "data/climaflora_global_plants_v1_1.manifest.json"
    consolidation_zstd_level: int = 10
    consolidation_download_enabled: bool = False
    tdwg_geojson_path: str = "/data/tdwg_level3.geojson"
    tdwg_geojson_urls: str = (
        "https://raw.githubusercontent.com/tdwg/wgsrpd/master/geojson/level3.geojson,"
        "https://cdn.jsdelivr.net/gh/tdwg/wgsrpd@master/geojson/level3.geojson"
    )
    tdwg_region_sample_points: int = 9
    scientific_min_coverage: float = 0.50
    master_source_urls: str = (
        "https://shugoan.com/climaflora/data/climaflora_global_plants_v2_0.sqlite.zst"
    )
    master_expected_sha256: str = "1683c43c6fb1e68f9b6c6c4cd7f291642feba6c37a3691c3452b319856335c32"
    master_expected_sqlite_sha256: str = "3e80f432ebe2b4b59fed1b76549d2fc7df4e9330f1c315ae804746b616baee55"
    master_expected_catalog_version: str = "2.0.0"
    catalog_enrichment_enabled: bool = False
    catalog_enrichment_seed: str = "data/ecocrop_soil_seed.json"
    catalog_enrichment_status: str = "/data/catalog_enrichment_status.json"
    catalog_snapshot_zst: str = "/data/climaflora_global_plants_v2_0.sqlite.zst"
    catalog_enrichment_zstd_level: int = 10
    master_required_tables: str = (
        "plant_taxa,wcvp_distribution,wcvp_names,plant_index,climate_envelope,soil_source_envelope,soil_source_categorical_preference,soil_envelope,soil_categorical_preference,soil_indicator_preference,soil_geographic_prior,region_soil_summary,soil_sources,soil_envelopes,soil_preferences,soil_evidence,evidence,build_metadata,climaflora_catalog_metadata,plant_vernacular_name,plant_image_asset,plant_use,plant_use_reference,plant_trait_evidence"
    )

    @property
    def master_source_url_list(self) -> list[str]:
        return [x.strip() for x in self.master_source_urls.split(",") if x.strip()]

    @property
    def master_required_table_list(self) -> list[str]:
        return [x.strip() for x in self.master_required_tables.split(",") if x.strip()]

    @property
    def tdwg_geojson_url_list(self) -> list[str]:
        return [x.strip() for x in self.tdwg_geojson_urls.split(",") if x.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]

    @property
    def trusted_host_list(self) -> list[str]:
        values = [x.strip() for x in self.trusted_hosts.split(",") if x.strip()]
        space_host = os.getenv("SPACE_HOST", "").strip()
        if space_host and space_host not in values:
            values.append(space_host)
        return values

    @property
    def normalized_root_path(self) -> str:
        value = self.root_path.strip()
        if not value or value == "/":
            return ""
        return "/" + value.strip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
