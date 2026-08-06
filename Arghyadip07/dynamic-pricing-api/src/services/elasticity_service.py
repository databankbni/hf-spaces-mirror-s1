"""Elasticity estimation service for price sensitivity analysis."""

from dataclasses import dataclass

from src.core.settings import settings
from src.models.demand import load_or_train_model_artifact
from src.models.elasticity_model import ElasticityModel


@dataclass
class ElasticityInput:
    """Input parameters for elasticity estimation."""

    price: float
    competitor_price: float
    inventory: int
    day_of_week: int


class ElasticityService:
    """Service for estimating price elasticity of demand."""

    def __init__(self, data_path: str | None = None, artifact_path: str | None = None):
        """
        Initialize the elasticity service.

        Args:
            data_path: Path to processed data (default: from settings)
            artifact_path: Path to model artifact (default: from settings)
        """
        self.data_path = data_path or str(settings.processed_data_abspath)
        self.artifact_path = artifact_path or str(settings.model_artifact_abspath)
        self.demand_model = None
        self.reference_row = None
        self.elasticity_model = None

    def startup(self):
        """Load or train the demand model and initialize elasticity model."""
        self.demand_model, self.reference_row, _ = load_or_train_model_artifact(
            data_path=self.data_path,
            artifact_path=self.artifact_path,
        )
        self.elasticity_model = ElasticityModel(
            demand_model=self.demand_model,
            reference_row=self.reference_row,
        )

    def estimate_elasticity(self, payload: ElasticityInput) -> dict:
        """
        Estimate price elasticity of demand.

        Args:
            payload: ElasticityInput with price, competitor_price, inventory, day_of_week

        Returns:
            Dictionary with elasticity estimation results
        """
        if self.elasticity_model is None:
            self.startup()

        if self.elasticity_model is None:
            raise RuntimeError("ElasticityService failed to initialize model artifacts")

        elasticity = self.elasticity_model.estimate_elasticity(
            price=payload.price,
            competitor_price=payload.competitor_price,
            inventory=payload.inventory,
            day_of_week=payload.day_of_week,
        )

        # Interpret elasticity
        if elasticity < -1:
            elasticity_interpretation = "Elastic (price-sensitive demand)"
        elif elasticity > -1:
            elasticity_interpretation = "Inelastic (price-insensitive demand)"
        else:
            elasticity_interpretation = "Unit elastic"

        return {
            "price": payload.price,
            "elasticity": elasticity,
            "interpretation": elasticity_interpretation,
        }

    def estimate_elasticity_range(
        self,
        price: float,
        competitor_price: float,
        inventory: int,
        day_of_week: int,
        price_points: int = 5,
        price_range: tuple[float, float] = (50.0, 150.0),
    ) -> dict:
        """
        Estimate elasticity across a range of prices.

        Args:
            price: Current price
            competitor_price: Competitor price
            inventory: Current inventory level
            day_of_week: Day of week (0-6)
            price_points: Number of price points to evaluate
            price_range: Min and max price for range

        Returns:
            Dictionary with elasticity estimates across price range
        """
        if self.elasticity_model is None:
            self.startup()

        if self.elasticity_model is None:
            raise RuntimeError("ElasticityService failed to initialize model artifacts")

        elasticity_estimates = self.elasticity_model.estimate_elasticity_range(
            base_price=price,
            competitor_price=competitor_price,
            inventory=inventory,
            day_of_week=day_of_week,
            price_points=price_points,
            price_range=price_range,
        )

        return {
            "market_context": {
                "current_price": price,
                "competitor_price": competitor_price,
                "inventory": inventory,
                "day_of_week": day_of_week,
            },
            "elasticity_curve": elasticity_estimates,
        }
