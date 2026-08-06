from dataclasses import dataclass

from src.core.settings import settings
from src.domain.pricing import optimize_price_for_context
from src.models.demand import load_or_train_model_artifact


@dataclass
class PricingInput:
    competitor_price: float
    inventory: int
    day_of_week: int
    unit_cost: float = 60.0
    inventory_aware: bool = True


class PricingService:
    def __init__(self, data_path: str | None = None, artifact_path: str | None = None):
        self.data_path = data_path or str(settings.processed_data_abspath)
        self.artifact_path = artifact_path or str(settings.model_artifact_abspath)
        self.model = None
        self.reference_row = None

    def startup(self):
        self.model, self.reference_row, _ = load_or_train_model_artifact(
            data_path=self.data_path,
            artifact_path=self.artifact_path,
        )

    def calculate_optimal_price(self, payload: PricingInput) -> dict:
        if self.model is None or self.reference_row is None:
            self.startup()
        if self.model is None or self.reference_row is None:
            raise RuntimeError("PricingService failed to initialize model artifacts")

        return optimize_price_for_context(
            model=self.model,
            reference_row=self.reference_row,
            competitor_price=payload.competitor_price,
            inventory=payload.inventory,
            day_of_week=payload.day_of_week,
            unit_cost=payload.unit_cost,
            inventory_aware=payload.inventory_aware,
        )

    def reload_model(self, model, reference_row) -> None:
        """Update the live demand model and reference row."""
        self.model = model
        self.reference_row = reference_row

