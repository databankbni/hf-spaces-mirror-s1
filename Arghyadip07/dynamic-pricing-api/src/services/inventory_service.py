from dataclasses import dataclass
from typing import Dict

from src.core.settings import settings
from src.models.demand import load_or_train_model_artifact


@dataclass
class InventoryOptimizeInput:
    product_id: int
    current_price: float
    inventory: int
    unit_cost: float = 60.0
    competitor_price: float = 0.0


class InventoryOptimizationService:
    """Service that adjusts price recommendations based on inventory constraints.

    This is a simple heuristic: when inventory is low, favor higher margins;
    when inventory is high, nudge price down to increase turnover.
    Replace with a constrained optimizer for production use.
    """

    def __init__(self, data_path: str | None = None, artifact_path: str | None = None):
        self.data_path = data_path or str(settings.processed_data_abspath)
        self.artifact_path = artifact_path or str(settings.model_artifact_abspath)
        self.demand_model = None
        self.reference_row = None

    def startup(self):
        self.demand_model, self.reference_row, _ = load_or_train_model_artifact(
            data_path=self.data_path, artifact_path=self.artifact_path
        )

    def adjust_price_for_inventory(self, payload: InventoryOptimizeInput) -> Dict[str, float]:
        if self.demand_model is None:
            self.startup()

        inv = payload.inventory
        base = payload.current_price
        unit_cost = payload.unit_cost

        # heuristic multiplier
        if inv <= 5:
            multiplier = 1.15
        elif inv <= 20:
            multiplier = 1.05
        elif inv <= 100:
            multiplier = 1.0
        else:
            multiplier = 0.95

        adjusted_price = max(unit_cost * 1.01, base * multiplier)

        # placeholder demand estimate
        try:
            X = self.reference_row.copy()
            X["price"] = adjusted_price
            X["competitor_price"] = payload.competitor_price
            X["inventory"] = inv
            demand = float(self.demand_model.predict(X.reshape(1, -1))[0])
        except Exception:
            demand = max(0.0, inv * 0.1)

        expected_profit = (adjusted_price - unit_cost) * min(demand, inv)

        return {"adjusted_price": float(adjusted_price), "expected_demand": float(demand), "expected_profit": float(expected_profit)}
