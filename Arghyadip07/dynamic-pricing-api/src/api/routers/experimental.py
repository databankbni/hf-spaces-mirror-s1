from fastapi import APIRouter
from pydantic import BaseModel

from src.api.runtime import runtime
from src.services.analytics_service import WhatIfScenario
from src.services.competitor_service import CompetitorSignal
from src.services.inventory_service import InventoryOptimizeInput
from src.services.multi_product_service import MultiProductInput
from src.storage import storage_backend


router = APIRouter()


class MultiProductRequest(BaseModel):
    products: list[dict]


class MultiProductResponse(BaseModel):
    recommendations: dict


class InventoryOptimizeRequest(BaseModel):
    product_id: int
    current_price: float
    inventory: int
    unit_cost: float = 60.0
    competitor_price: float = 0.0


class InventoryOptimizeResponse(BaseModel):
    adjusted_price: float
    expected_demand: float
    expected_profit: float


class CompetitorSignalRequest(BaseModel):
    product_id: int
    competitor_price: float
    source: str | None = None
    timestamp: str | None = None


class ABAssignRequest(BaseModel):
    experiment: str
    subject_id: str


class ABAssignResponse(BaseModel):
    experiment: str
    subject_id: str
    group: str


class ABOutcomeRequest(BaseModel):
    experiment: str
    subject_id: str
    outcome: dict


class CausalUpliftRequest(BaseModel):
    features: list[list[float]]


class CausalUpliftResponse(BaseModel):
    uplifts: list[float]


class WhatIfScenarioRequest(BaseModel):
    name: str
    competitor_price: float
    inventory: int
    day_of_week: int
    unit_cost: float = 60.0
    inventory_aware: bool = True


class WhatIfRequest(BaseModel):
    scenarios: list[WhatIfScenarioRequest]


class CausalEffectRequest(BaseModel):
    rows: list[dict]
    treatment_column: str
    outcome_column: str
    control_columns: list[str] = []


class PriceResponseCurveRequest(BaseModel):
    competitor_price: float
    inventory: int
    day_of_week: int
    unit_cost: float = 60.0
    min_price: float = 50.0
    max_price: float = 180.0
    price_points: int = 20


class AnalysisReportResponse(BaseModel):
    performance: dict
    drift: dict
    ab_summary: dict
    what_if: dict
    causal_effect: dict


class MarketContextPayload(BaseModel):
    product_id: int
    inventory: int | None = None
    unit_cost: float | None = None
    updated_at: str | None = None


@router.post("/multi_product_optimize", response_model=MultiProductResponse)
def multi_product_optimize(payload: MultiProductRequest) -> MultiProductResponse:
    recommendations = runtime.multi_product_service.recommend_prices(MultiProductInput(products=payload.products))
    return MultiProductResponse(recommendations=recommendations)


@router.post("/inventory_optimize", response_model=InventoryOptimizeResponse)
def inventory_optimize(payload: InventoryOptimizeRequest) -> InventoryOptimizeResponse:
    out = runtime.inventory_service.adjust_price_for_inventory(
        InventoryOptimizeInput(
            product_id=payload.product_id,
            current_price=payload.current_price,
            inventory=payload.inventory,
            unit_cost=payload.unit_cost,
            competitor_price=payload.competitor_price,
        )
    )
    return InventoryOptimizeResponse(
        adjusted_price=out["adjusted_price"],
        expected_demand=out["expected_demand"],
        expected_profit=out["expected_profit"],
    )


@router.post("/competitor_signal")
def competitor_signal(payload: CompetitorSignalRequest) -> dict:
    signal = CompetitorSignal(
        product_id=payload.product_id,
        competitor_price=payload.competitor_price,
        source=payload.source,
        timestamp=payload.timestamp,
    )
    return runtime.competitor_service.ingest(signal)


@router.post("/market_context")
def post_market_context(payload: MarketContextPayload) -> dict:
    """Ingest live market context (inventory, cost) from external systems."""
    from datetime import datetime, timezone
    ts = payload.updated_at or datetime.now(timezone.utc).isoformat()
    return storage_backend.upsert_market_context(
        product_id=payload.product_id,
        inventory=payload.inventory,
        unit_cost=payload.unit_cost,
        updated_at=ts,
    )


@router.post("/validation/real_world")
def validate_real_world() -> dict:
    """Evaluate the demand model against the real-world UCI Online Retail dataset."""
    return runtime.validation_service.validate_on_real_world()


@router.get("/benchmark/pricing_strategies")
def benchmark_strategies(scenarios: int = 50, seed: int = 42) -> dict:
    """Compare profit outcomes across 4 pricing strategies."""
    return runtime.benchmark_service.run_benchmark(n_scenarios=scenarios, seed=seed)


@router.post("/ab_test/assign", response_model=ABAssignResponse)
def ab_assign(payload: ABAssignRequest) -> ABAssignResponse:
    assignment = runtime.ab_test_manager.assign(payload.experiment, payload.subject_id)
    return ABAssignResponse(
        experiment=assignment.experiment,
        subject_id=assignment.subject_id,
        group=assignment.group,
    )


@router.post("/ab_test/outcome")
def ab_outcome(payload: ABOutcomeRequest) -> dict:
    return runtime.ab_test_manager.record_outcome(payload.experiment, payload.subject_id, payload.outcome)


@router.post("/causal_uplift/estimate", response_model=CausalUpliftResponse)
def causal_uplift_estimate(payload: CausalUpliftRequest) -> CausalUpliftResponse:
    try:
        uplifts = runtime.causal_uplift_model.estimate_uplift(payload.features)
    except Exception:
        uplifts = [0.0 for _ in payload.features]
    return CausalUpliftResponse(uplifts=uplifts)


@router.post("/causal/discover")
def causal_discover() -> dict:
    import subprocess
    import os
    try:
        # Run the causal discovery script using subprocess, with reduced sample size to avoid HF throttling
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'scripts', 'run_causal_discovery.py'))
        subprocess.run(["python", script_path, "--sample_size", "500"], check=True)
        return {"status": "success", "message": "Causal discovery completed and graph generated."}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "message": f"Causal discovery script failed: {e}"}

@router.post("/causal/fit")
def causal_fit(n_samples: int = 2000, seed: int = 42) -> dict:
    """
    Fit the DoWhy causal model on synthetic pricing data and run 3 refutation tests.

    - n_samples: number of rows of synthetic data to generate (200-10000)
    - seed: random seed for reproducibility

    Returns:
      - ate: Average Treatment Effect of price on demand
      - ate_interpretation: plain English explanation
      - refutations: results of 3 validation tests (placebo / random cause / subset)
      - all_refutations_passed: True if all 3 refutations are reassuring
      - causal_graph: the DOT-language DAG used
    """
    import numpy as np
    import pandas as pd

    n_samples = max(200, min(10000, n_samples))
    rng = np.random.default_rng(seed)

    # Generate synthetic pricing data with realistic causal structure
    competitor_price = rng.uniform(70, 130, n_samples)
    inventory        = rng.integers(20, 300, n_samples).astype(float)
    day_of_week      = rng.integers(0, 7, n_samples).astype(float)

    # Price is influenced by competitor price and inventory (confounders)
    price = (
        competitor_price * 0.95
        + (1 - inventory / 300) * 10
        + day_of_week * 1.5
        + rng.normal(0, 5, n_samples)
    ).clip(50, 200)

    # Demand is causally reduced by price, boosted by low competitor price and high inventory
    demand = (
        500
        - 2.5 * price
        + 1.8 * competitor_price
        + 0.3 * inventory
        + 10 * (day_of_week > 4).astype(float)
        + rng.normal(0, 20, n_samples)
    ).clip(0)

    df = pd.DataFrame({
        "price":            price,
        "demand":           demand,
        "competitor_price": competitor_price,
        "inventory":        inventory,
        "day_of_week":      day_of_week,
    })

    return runtime.causal_uplift_model.fit(df)


@router.get("/causal/summary")
def causal_summary() -> dict:
    """Return the full causal analysis summary including ATE and refutation results."""
    return runtime.causal_uplift_model.get_summary()


@router.get("/monitoring/performance")
def monitoring_performance() -> dict:
    return runtime.analytics_service.performance_summary()


@router.get("/monitoring/drift")
def monitoring_drift(recent_fraction: float = 0.25) -> dict:
    return runtime.analytics_service.drift_report(recent_fraction=recent_fraction)


@router.get("/monitoring/error_rate")
def monitoring_error_rate(window_seconds: int = 300, bucket_seconds: int = 60) -> dict:
    return runtime.monitoring_service.error_rate_report(
        window_seconds=window_seconds,
        bucket_seconds=bucket_seconds,
    )


@router.post("/monitoring/retrain_check")
def monitoring_retrain_check(recent_fraction: float = 0.25, force: bool = False) -> dict:
    return runtime.analytics_service.retrain_if_needed(
        recent_fraction=recent_fraction,
        force=force,
    )


@router.post("/what_if/analyze")
def what_if_analyze(payload: WhatIfRequest) -> dict:
    scenarios = [
        WhatIfScenario(
            name=item.name,
            competitor_price=item.competitor_price,
            inventory=item.inventory,
            day_of_week=item.day_of_week,
            unit_cost=item.unit_cost,
            inventory_aware=item.inventory_aware,
        )
        for item in payload.scenarios
    ]
    return runtime.analytics_service.what_if_analysis(scenarios)


@router.post("/causal_effect/estimate")
def causal_effect_estimate(payload: CausalEffectRequest) -> dict:
    return runtime.analytics_service.causal_effect(
        rows=payload.rows,
        treatment_column=payload.treatment_column,
        outcome_column=payload.outcome_column,
        control_columns=payload.control_columns,
    )


@router.post("/price_response_curve")
def price_response_curve(payload: PriceResponseCurveRequest) -> dict:
    return runtime.analytics_service.price_response_curve(
        competitor_price=payload.competitor_price,
        inventory=payload.inventory,
        day_of_week=payload.day_of_week,
        unit_cost=payload.unit_cost,
        min_price=payload.min_price,
        max_price=payload.max_price,
        price_points=payload.price_points,
    )


@router.get("/analysis/report", response_model=AnalysisReportResponse)
def analysis_report(experiment: str = "model_vs_static_pricing", recent_fraction: float = 0.25) -> AnalysisReportResponse:
    return AnalysisReportResponse(
        **runtime.analytics_service.analysis_report(
            experiment=experiment,
            recent_fraction=recent_fraction,
        )
    )
