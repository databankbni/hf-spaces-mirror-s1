from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routers.api import router
from app.routers.enrichment import router as enrichment_router
from app.routers.search import router as search_router
from app.routers.billing import router as billing_router
from app.routers.sostagora_auth import router as sostagora_auth_router
from app.services.bootstrap import get_master_bootstrap
from app.services.catalog_enrichment import get_catalog_enrichment
from app.services.funnel_metadata import warm_funnel_metadata
from app.services.search_runtime_sidecar import warm_search_runtime_sidecar
from app.services.search_vector import load_climate_runtime_matrix
from app.services.search_vector_navigation import load_navigation_runtime_matrix
from app.version import APP_VERSION

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.master_bootstrap_enabled:
        get_master_bootstrap(
            settings.master_db,
            settings.master_bootstrap_status,
            settings.master_audit_path,
            settings.master_source_url_list,
            settings.master_expected_sha256,
            settings.master_required_table_list,
            settings.master_expected_catalog_version,
            settings.master_expected_sqlite_sha256,
        ).start()
    if settings.catalog_enrichment_enabled:
        get_catalog_enrichment(
            settings.master_db,
            settings.catalog_db,
            settings.catalog_snapshot_zst,
            settings.catalog_enrichment_seed,
            settings.catalog_enrichment_status,
            settings.master_bootstrap_status,
            settings.catalog_enrichment_zstd_level,
        ).start()

    # Type/function navigation metadata is static for one immutable catalog.
    # Build its compact indexed sidecar before the service reports startup
    # complete whenever the production catalog is already present. This moves
    # the expensive 420k-taxon classification scan out of the first user query.
    catalog_path = Path(settings.catalog_db)
    if catalog_path.exists():
        try:
            sidecar = warm_funnel_metadata(catalog_path)
            logger.info("ClimaFlora funnel metadata warm: %s", sidecar)
        except Exception:  # noqa: BLE001 - optimization must never block API availability
            logger.exception("Unable to prewarm ClimaFlora funnel metadata")

        # The v0.10 wide sidecar and NumPy/navigation matrices are more expensive
        # to materialize than a normal filter operation. Prewarm them only when
        # the guarded vector runtime is explicitly enabled, so no production
        # startup behavior changes before rollout.
        if settings.search_vector_enabled:
            try:
                runtime_sidecar = warm_search_runtime_sidecar(catalog_path)
                climate_matrix = load_climate_runtime_matrix(catalog_path)
                navigation_matrix = load_navigation_runtime_matrix(catalog_path)
                logger.info(
                    "ClimaFlora v0.10 runtime warm: %s taxa=%s navigation=%s",
                    runtime_sidecar,
                    climate_matrix.size,
                    navigation_matrix.size,
                )
            except Exception:  # noqa: BLE001 - SQL fallback remains available
                logger.exception("Unable to prewarm ClimaFlora v0.10 vector runtime")
    yield


app = FastAPI(
    title="ClimaFlora API",
    version=APP_VERSION,
    description="Explainable plant suitability across present and future climate horizons.",
    root_path=settings.normalized_root_path,
    lifespan=lifespan,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_host_list)
app.add_middleware(GZipMiddleware, minimum_size=800)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Accept", "Authorization", "Content-Type", "Stripe-Signature"],
    max_age=86400,
)
app.include_router(router, prefix=settings.api_prefix)
app.include_router(enrichment_router, prefix=settings.api_prefix)
app.include_router(search_router, prefix=settings.api_prefix)
app.include_router(billing_router, prefix=settings.api_prefix)
app.include_router(sostagora_auth_router, prefix=settings.api_prefix)

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
if settings.serve_frontend:
    app.mount("/static", StaticFiles(directory=FRONTEND / "static"), name="static")

    @app.get("/", include_in_schema=False)
    def frontend():
        return FileResponse(FRONTEND / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/a-propos.html", include_in_schema=False)
    def frontend_about():
        return FileResponse(FRONTEND / "a-propos.html", headers={"Cache-Control": "no-cache"})

    @app.get("/methodologie.html", include_in_schema=False)
    def frontend_methodology():
        return FileResponse(FRONTEND / "methodologie.html", headers={"Cache-Control": "no-cache"})

    @app.get("/tarifs.html", include_in_schema=False)
    def frontend_pricing():
        return FileResponse(FRONTEND / "tarifs.html", headers={"Cache-Control": "no-cache"})
else:
    @app.get("/", include_in_schema=False)
    def service_root():
        return {
            "service": "climaflora-api",
            "version": APP_VERSION,
            "deployment_mode": settings.deployment_mode,
            "public_app": settings.public_url,
            "health": f"{settings.api_prefix}/health",
        }
