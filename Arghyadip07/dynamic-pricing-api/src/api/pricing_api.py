from contextlib import asynccontextmanager
import logging
import time
import traceback

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.api.routers.agent import agent_history, agent_set_interval, agent_start, agent_status, agent_stop
from src.api.routers.admin import admin_ab_outcomes, admin_ab_summary, admin_competitor_signals
from src.api.routers.experimental import (
    ABAssignRequest,
    ABAssignResponse,
    ABOutcomeRequest,
    CausalUpliftRequest,
    CausalUpliftResponse,
    CompetitorSignalRequest,
    InventoryOptimizeRequest,
    InventoryOptimizeResponse,
    MultiProductRequest,
    MultiProductResponse,
    ab_assign,
    ab_outcome,
    causal_uplift_estimate,
    competitor_signal,
    inventory_optimize,
    multi_product_optimize,
)
from src.api.routers.pricing import (
    ElasticityRangeRequest,
    ElasticityRangeResponse,
    ElasticityRequest,
    ElasticityResponse,
    PricingRequest,
    PricingResponse,
    RLPricingRequest,
    RLPricingResponse,
    RLTrainingRequest,
    RLTrainingResponse,
    calculate_optimal_price,
    estimate_elasticity,
    estimate_elasticity_range,
    rl_pricing,
    rl_training,
)
from src.api.runtime import runtime
from src.api.routers.agent import router as agent_router
from src.api.routers.admin import router as admin_router
from src.api.routers.experimental import router as experimental_router
from src.api.routers.pricing import router as pricing_router
from src.core.settings import settings

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown lifecycle."""
    try:
        logger.info(f"Starting API with settings: host={settings.api_host}, port={settings.api_port}")
        logger.info(f"Model artifact path: {settings.model_artifact_abspath}")
        logger.info(f"Data path: {settings.processed_data_abspath}")

        logger.info("Initializing application services...")
        runtime.startup()
        logger.info("✓ Application services initialized successfully")
    except Exception as exc:
        logger.error(f"✗ Startup error: {type(exc).__name__}: {str(exc)}", exc_info=True)
        raise

    yield

    runtime.shutdown()
    logger.info("✓ Pricing agent stopped")


app = FastAPI(title="Dynamic Pricing API", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def request_metrics_middleware(request: Request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
        runtime.monitoring_service.record(
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )
        return response
    except Exception:
        runtime.monitoring_service.record(
            method=request.method,
            path=request.url.path,
            status_code=500,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )
        raise


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch all unhandled exceptions and return as JSON."""
    error_trace = traceback.format_exc()
    logger.error(f"Unhandled exception: {type(exc).__name__}: {str(exc)}\n{error_trace}")
    return JSONResponse(
        status_code=500,
        content={
            "error": type(exc).__name__,
            "message": str(exc),
            "path": request.url.path,
            "method": request.method,
        },
    )


@app.get("/")
def home() -> dict[str, str]:
    return {"message": "Dynamic Pricing API is running"}


@app.get("/health")
def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "api": "Dynamic Pricing API v1.0.0"}


app.include_router(pricing_router)
app.include_router(experimental_router)
app.include_router(admin_router)
app.include_router(agent_router)