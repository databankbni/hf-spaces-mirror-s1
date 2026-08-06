import unittest

from src.api.pricing_api import RLPricingRequest, RLTrainingRequest, rl_pricing, rl_training


class TestRLPricingApi(unittest.TestCase):
    def test_rl_pricing_returns_positive_values(self):
        """Test that RL pricing returns valid price and profit."""
        payload = RLPricingRequest(
            competitor_price=115,
            inventory=500,
            day_of_week=2,
            unit_cost=60,
        )

        result = rl_pricing(payload)
        response = result.model_dump()

        self.assertIn("rl_price", response)
        self.assertIn("expected_profit", response)
        self.assertIn("strategy", response)

        self.assertGreater(response["rl_price"], 0)
        # Profit can be negative in some market conditions, so just check it's a number
        self.assertIsInstance(response["expected_profit"], (int, float))
        self.assertEqual(response["strategy"], "RL Policy")

    def test_rl_pricing_price_in_reasonable_range(self):
        """Test that RL pricing is within expected range."""
        payload = RLPricingRequest(
            competitor_price=115,
            inventory=500,
            day_of_week=2,
            unit_cost=60,
        )

        result = rl_pricing(payload)
        response = result.model_dump()

        # Price should stay inside the dynamic action-space bounds.
        self.assertGreaterEqual(response["rl_price"], 60 * 1.01)
        self.assertLessEqual(response["rl_price"], max(115 * 3.0, 60 * 5.0))

    def test_rl_training_learns_from_experience(self):
        """Test that RL training processes episodes and improves learning."""
        payload = RLTrainingRequest(
            competitor_price=115,
            inventory=500,
            day_of_week=2,
            unit_cost=60,
            num_episodes=5,
        )

        result = rl_training(payload)
        response = result.model_dump()

        self.assertIn("episodes_completed", response)
        self.assertIn("average_reward", response)
        self.assertIn("max_reward", response)
        self.assertIn("buffer_size", response)

        self.assertEqual(response["episodes_completed"], 5)
        self.assertGreater(response["average_reward"], 0)
        self.assertGreater(response["max_reward"], 0)
        self.assertGreater(response["buffer_size"], 0)

    def test_rl_training_buffer_accumulates(self):
        """Test that repeated training accumulates experiences in buffer."""
        # First training
        payload1 = RLTrainingRequest(
            competitor_price=115,
            inventory=500,
            day_of_week=2,
            unit_cost=60,
            num_episodes=3,
        )
        result1 = rl_training(payload1)
        buffer_size_1 = result1.model_dump()["buffer_size"]

        # Second training
        payload2 = RLTrainingRequest(
            competitor_price=120,
            inventory=400,
            day_of_week=3,
            unit_cost=60,
            num_episodes=3,
        )
        result2 = rl_training(payload2)
        buffer_size_2 = result2.model_dump()["buffer_size"]

        # Buffer should accumulate experiences
        self.assertGreater(buffer_size_2, buffer_size_1)


if __name__ == "__main__":
    unittest.main()
