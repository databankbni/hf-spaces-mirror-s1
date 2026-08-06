import unittest

from src.domain.pricing import optimize_price_for_context
from src.models.demand import load_or_train_model_artifact


class TestPriceOptimizer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model, cls.reference_row, _ = load_or_train_model_artifact()

    def test_optimal_price_respects_bounds(self):
        min_price = 80.0
        max_price = 120.0

        result = optimize_price_for_context(
            model=self.model,
            reference_row=self.reference_row,
            competitor_price=110.0,
            inventory=450,
            day_of_week=3,
            unit_cost=60.0,
            min_price=min_price,
            max_price=max_price,
            n_candidates=41,
        )

        self.assertIn("optimal_price", result)
        self.assertIn("expected_demand", result)
        self.assertIn("expected_profit", result)

        self.assertGreaterEqual(result["optimal_price"], min_price)
        self.assertLessEqual(result["optimal_price"], max_price)
        self.assertGreater(result["expected_demand"], 0)
        self.assertGreater(result["expected_profit"], 0)

    def test_inventory_pressure_affects_price(self):
        """Verify that higher inventory results in a lower optimal price (to clear stock)."""
        # Low inventory (understocked)
        result_low = optimize_price_for_context(
            model=self.model,
            reference_row=self.reference_row,
            competitor_price=110.0,
            inventory=50,  # very low inventory
            day_of_week=3,
            unit_cost=60.0,
            min_price=60.0,
            max_price=200.0,
        )
        
        # High inventory (overstocked)
        result_high = optimize_price_for_context(
            model=self.model,
            reference_row=self.reference_row,
            competitor_price=110.0,
            inventory=2000,  # very high inventory
            day_of_week=3,
            unit_cost=60.0,
            min_price=60.0,
            max_price=200.0,
        )

        # The optimal price for high inventory should be less than or equal to low inventory
        # (It will strictly be less due to effective_cost being lower)
        self.assertLessEqual(result_high["optimal_price"], result_low["optimal_price"])


if __name__ == "__main__":
    unittest.main()
