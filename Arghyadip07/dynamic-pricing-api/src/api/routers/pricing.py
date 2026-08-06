from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.api.runtime import runtime
from src.services.elasticity_service import ElasticityInput
from src.services.pricing_service import PricingInput
from src.services.rl_pricing_service import RLPricingInput


router = APIRouter()


class PricingRequest(BaseModel):
    product_id: int | None = Field(default=None)
    current_price: float = Field(..., gt=0)
    competitor_price: float = Field(..., gt=0)
    inventory: int = Field(..., ge=0)
    day_of_week: int = Field(..., ge=0, le=6)
    unit_cost: float = Field(default=60.0, ge=0)
    inventory_aware: bool = Field(default=True)


class PricingResponse(BaseModel):
    optimal_price: float
    expected_demand: float
    expected_profit: float
    strategy: str = "Profit-Maximising Pricing (standard market)"


class ElasticityRequest(BaseModel):
    price: float = Field(..., gt=0)
    competitor_price: float = Field(..., gt=0)
    inventory: int = Field(..., ge=0)
    day_of_week: int = Field(..., ge=0, le=6)


class ElasticityResponse(BaseModel):
    price: float
    elasticity: float
    interpretation: str


class ElasticityRangeRequest(BaseModel):
    price: float = Field(..., gt=0)
    competitor_price: float = Field(..., gt=0)
    inventory: int = Field(..., ge=0)
    day_of_week: int = Field(..., ge=0, le=6)
    price_points: int = Field(default=5, ge=3, le=20)
    min_price: float = Field(default=50.0, gt=0)
    max_price: float = Field(default=150.0, gt=0)


class ElasticityRangeResponse(BaseModel):
    market_context: dict
    elasticity_curve: list[dict]


class RLPricingRequest(BaseModel):
    competitor_price: float = Field(..., gt=0)
    inventory: int = Field(..., ge=0)
    day_of_week: int = Field(..., ge=0, le=6)
    unit_cost: float = Field(default=60.0, ge=0)


class RLPricingResponse(BaseModel):
    rl_price: float
    expected_profit: float
    strategy: str


class RLTrainingRequest(BaseModel):
    competitor_price: float = Field(..., gt=0)
    inventory: int = Field(..., ge=0)
    day_of_week: int = Field(..., ge=0, le=6)
    unit_cost: float = Field(default=60.0, ge=0)
    num_episodes: int = Field(default=5, ge=1, le=100)


class RLTrainingResponse(BaseModel):
    episodes_completed: int
    average_reward: float
    max_reward: float
    buffer_size: int


@router.post("/calculate_optimal_price", response_model=PricingResponse)
def calculate_optimal_price(payload: PricingRequest) -> PricingResponse:
    try:
        result = runtime.pricing_service.calculate_optimal_price(
            PricingInput(
                competitor_price=payload.competitor_price,
                inventory=payload.inventory,
                day_of_week=payload.day_of_week,
                unit_cost=payload.unit_cost,
                inventory_aware=payload.inventory_aware,
            )
        )
        return PricingResponse(
            optimal_price=result["optimal_price"],
            expected_demand=result["expected_demand"],
            expected_profit=result["expected_profit"],
            strategy=result.get("strategy", "Profit-Maximising Pricing (standard market)"),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Internal error: {exc}") from exc


@router.post("/estimate_elasticity", response_model=ElasticityResponse)
def estimate_elasticity(payload: ElasticityRequest) -> ElasticityResponse:
    result = runtime.elasticity_service.estimate_elasticity(
        ElasticityInput(
            price=payload.price,
            competitor_price=payload.competitor_price,
            inventory=payload.inventory,
            day_of_week=payload.day_of_week,
        )
    )

    return ElasticityResponse(
        price=result["price"],
        elasticity=result["elasticity"],
        interpretation=result["interpretation"],
    )


@router.post("/estimate_elasticity_range", response_model=ElasticityRangeResponse)
def estimate_elasticity_range(payload: ElasticityRangeRequest) -> ElasticityRangeResponse:
    result = runtime.elasticity_service.estimate_elasticity_range(
        price=payload.price,
        competitor_price=payload.competitor_price,
        inventory=payload.inventory,
        day_of_week=payload.day_of_week,
        price_points=payload.price_points,
        price_range=(payload.min_price, payload.max_price),
    )

    return ElasticityRangeResponse(
        market_context=result["market_context"],
        elasticity_curve=result["elasticity_curve"],
    )


@router.post("/rl_pricing", response_model=RLPricingResponse)
def rl_pricing(payload: RLPricingRequest) -> RLPricingResponse:
    result = runtime.rl_pricing_service.get_rl_price(
        RLPricingInput(
            competitor_price=payload.competitor_price,
            inventory=payload.inventory,
            day_of_week=payload.day_of_week,
            unit_cost=payload.unit_cost,
        )
    )

    return RLPricingResponse(
        rl_price=result["rl_price"],
        expected_profit=result["expected_profit"],
        strategy=result["strategy"],
    )


@router.post("/rl_training", response_model=RLTrainingResponse)
def rl_training(payload: RLTrainingRequest) -> RLTrainingResponse:
    result = runtime.rl_pricing_service.train_on_experience(
        competitor_price=payload.competitor_price,
        inventory=payload.inventory,
        day_of_week=payload.day_of_week,
        unit_cost=payload.unit_cost,
        num_episodes=payload.num_episodes,
    )

    return RLTrainingResponse(
        episodes_completed=result["episodes_completed"],
        average_reward=result["average_reward"],
        max_reward=result["max_reward"],
        buffer_size=result["buffer_size"],
    )
# Trigger reload
