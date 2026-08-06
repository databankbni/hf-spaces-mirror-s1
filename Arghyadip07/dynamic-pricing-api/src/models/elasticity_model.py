"""
Elasticity estimation module for price sensitivity analysis.

Price elasticity of demand measures how sensitive demand is to price changes.
Elasticity = (% change in demand) / (% change in price)

Interpretation:
- Elasticity < -1: Elastic (demand is price-sensitive)
- -1 < Elasticity < 0: Inelastic (demand is not price-sensitive)
- Elasticity = -1: Unit elastic
"""

import numpy as np
import pandas as pd

from src.models.demand import build_feature_row


class ElasticityModel:
    """Estimates price elasticity of demand using a trained demand model."""

    def __init__(self, demand_model, reference_row: pd.Series):
        """
        Initialize the elasticity model.

        Args:
            demand_model: Trained XGBoost model predicting demand
            reference_row: Reference row with median feature values
        """
        self.demand_model = demand_model
        self.reference_row = reference_row

    def estimate_elasticity(
        self,
        price: float,
        competitor_price: float,
        inventory: int,
        day_of_week: int,
        price_delta: float = 5.0,
    ) -> float:
        """
        Estimate price elasticity of demand at a given price point.

        The elasticity is estimated using finite differences:
        elasticity ≈ (demand2 - demand1) / (price2 - price1) * (price1 / demand1)

        Args:
            price: Base price at which to estimate elasticity
            competitor_price: Competitor price
            inventory: Current inventory level
            day_of_week: Day of week (0-6)
            price_delta: Price change for finite difference calculation (default: 5.0)

        Returns:
            Price elasticity of demand (typically negative)
        """
        # Get demand at base price
        X1 = build_feature_row(
            price=float(price),
            competitor_price=float(competitor_price),
            inventory=int(inventory),
            day_of_week=int(day_of_week),
            reference_row=self.reference_row,
        )
        demand1 = float(self.demand_model.predict(X1)[0])

        # Get demand at slightly higher price
        X2 = build_feature_row(
            price=float(price + price_delta),
            competitor_price=float(competitor_price),
            inventory=int(inventory),
            day_of_week=int(day_of_week),
            reference_row=self.reference_row,
        )
        demand2 = float(self.demand_model.predict(X2)[0])

        # Calculate elasticity using finite difference
        if demand1 <= 0 or abs(price_delta) < 1e-6:
            return 0.0

        elasticity = ((demand2 - demand1) / price_delta) * (price / demand1)
        return float(elasticity)

    def estimate_elasticity_range(
        self,
        base_price: float,
        competitor_price: float,
        inventory: int,
        day_of_week: int,
        price_points: int = 5,
        price_range: tuple[float, float] = (50.0, 150.0),
    ) -> list[dict]:
        """
        Estimate elasticity across a range of price points.

        Args:
            base_price: Base price for reference
            competitor_price: Competitor price
            inventory: Current inventory level
            day_of_week: Day of week (0-6)
            price_points: Number of price points to evaluate
            price_range: Min and max price for the range

        Returns:
            List of dicts with price and elasticity values
        """
        results = []
        for price in np.linspace(price_range[0], price_range[1], price_points):
            elasticity = self.estimate_elasticity(
                price=float(price),
                competitor_price=float(competitor_price),
                inventory=int(inventory),
                day_of_week=int(day_of_week),
            )
            results.append({
                "price": float(price),
                "elasticity": elasticity,
            })
        return results
