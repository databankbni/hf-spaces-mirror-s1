import unittest

from src.api.pricing_api import PricingRequest, calculate_optimal_price


class TestPricingApi(unittest.TestCase):
    def test_calculate_optimal_price_returns_positive_values(self):
        payload = PricingRequest(
            product_id=101,
            current_price=120,
            competitor_price=115,
            inventory=500,
            day_of_week=2,
            unit_cost=60,
        )

        result = calculate_optimal_price(payload)
        response = result.model_dump()

        self.assertIn("optimal_price", response)
        self.assertIn("expected_demand", response)
        self.assertIn("expected_profit", response)

        self.assertGreater(response["optimal_price"], 0)
        self.assertGreater(response["expected_demand"], 0)
        self.assertGreater(response["expected_profit"], 0)


if __name__ == "__main__":
    unittest.main()
