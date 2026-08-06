import unittest

from src.api.pricing_api import ElasticityRequest, ElasticityRangeRequest, estimate_elasticity, estimate_elasticity_range


class TestElasticityApi(unittest.TestCase):
    def test_estimate_elasticity_returns_negative_value(self):
        """Test that elasticity estimation returns a negative value (typical for demand)."""
        payload = ElasticityRequest(
            price=1200,
            competitor_price=1150,
            inventory=500,
            day_of_week=2,
        )

        result = estimate_elasticity(payload)
        response = result.model_dump()

        self.assertIn("price", response)
        self.assertIn("elasticity", response)
        self.assertIn("interpretation", response)

        self.assertEqual(response["price"], 1200)
        # Elasticity should typically be negative or zero for normal goods
        self.assertLessEqual(response["elasticity"], 0)
        # Interpretation should be one of the three options
        self.assertIn(
            response["interpretation"],
            [
                "Elastic (price-sensitive demand)",
                "Inelastic (price-insensitive demand)",
                "Unit elastic",
            ],
        )

    def test_estimate_elasticity_range_returns_curve(self):
        """Test that elasticity range estimation returns elasticity curve."""
        payload = ElasticityRangeRequest(
            price=1200,
            competitor_price=1150,
            inventory=500,
            day_of_week=2,
            price_points=5,
            min_price=1000,
            max_price=1400,
        )

        result = estimate_elasticity_range(payload)
        response = result.model_dump()

        self.assertIn("market_context", response)
        self.assertIn("elasticity_curve", response)

        # Check market context
        market_context = response["market_context"]
        self.assertEqual(market_context["current_price"], 1200)
        self.assertEqual(market_context["competitor_price"], 1150)

        # Check elasticity curve has correct number of points
        elasticity_curve = response["elasticity_curve"]
        self.assertEqual(len(elasticity_curve), 5)

        # Check each point has price and elasticity
        for point in elasticity_curve:
            self.assertIn("price", point)
            self.assertIn("elasticity", point)


if __name__ == "__main__":
    unittest.main()
