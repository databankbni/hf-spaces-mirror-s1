from dataclasses import dataclass
from typing import Dict, List

from src.models.demand import load_or_train_model_artifact
from src.core.settings import settings


@dataclass
class MultiProductInput:
    products: List[dict]


class MultiProductService:
    """Simple multi-product pricing scaffolding.

    Expects `products` as list of dicts with `product_id`, `current_price`,
    `inventory`, `unit_cost`, and `competitor_price`.
    """

    def __init__(self, data_path: str | None = None, artifact_path: str | None = None):
        self.data_path = data_path or str(settings.processed_data_abspath)
        self.artifact_path = artifact_path or str(settings.model_artifact_abspath)
        self.demand_model = None
        self.reference_row = None

    def startup(self):
        self.demand_model, self.reference_row, _ = load_or_train_model_artifact(
            data_path=self.data_path,
            artifact_path=self.artifact_path,
        )

    def recommend_prices(self, payload: MultiProductInput) -> Dict[int, dict]:
        """Return a dict keyed by product_id with recommended price and metadata.

        This is a lightweight heuristic implementation: for each product we call
        the demand model to score expected demand across a small grid and pick
        the price that maximizes expected profit. For full production usage,
        replace with joint optimization considering cross-elasticities.
        """
        if self.demand_model is None:
            self.startup()

        results: Dict[int, dict] = {}

        for p in payload.products:
            pid = int(p.get("product_id", -1))
            base_price = float(p.get("current_price", 100.0))
            unit_cost = float(p.get("unit_cost", 60.0))
            inventory = int(p.get("inventory", 0))
            competitor_price = float(p.get("competitor_price", base_price))

            # simple grid search
            best = {"price": base_price, "expected_profit": -1.0, "expected_demand": 0.0}
            for test_price in [base_price * f for f in (0.8, 0.9, 1.0, 1.1, 1.2)]:
                # Use the demand model's predict method if available; otherwise skip
                try:
                    X = self.reference_row.copy()
                    X["price"] = test_price
                    X["competitor_price"] = competitor_price
                    X["inventory"] = inventory
                    demand = float(self.demand_model.predict(X.reshape(1, -1))[0])
                except Exception:
                    demand = max(0.0, inventory * 0.1)

                profit = (test_price - unit_cost) * min(demand, inventory)
                if profit > best["expected_profit"]:
                    best = {"price": float(test_price), "expected_profit": float(profit), "expected_demand": float(demand)}

            results[pid] = best

        return results
