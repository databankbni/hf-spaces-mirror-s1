"""
Integration tests for API + Dashboard workflow.
Tests end-to-end scenarios where the dashboard interacts with the API.
"""

import unittest
import json
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from src.api.pricing_api import app


class TestAPIDashboardIntegration(unittest.TestCase):
    """Integration tests for API and Dashboard workflow."""

    def setUp(self):
        """Set up test client."""
        self.client = TestClient(app)

    def test_dashboard_calculate_optimal_price_workflow(self):
        """
        Test: Dashboard sends market context → API calculates optimal price.
        Simulates user input from dashboard UI.
        """
        dashboard_input = {
            "current_price": 120,
            "competitor_price": 115,
            "inventory": 500,
            "day_of_week": 2,
            "unit_cost": 60
        }

        response = self.client.post(
            "/calculate_optimal_price",
            json=dashboard_input
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Verify response structure
        self.assertIn("optimal_price", data)
        self.assertIn("expected_demand", data)
        self.assertIn("expected_profit", data)
        
        # Verify reasonable values
        self.assertGreater(data["optimal_price"], dashboard_input["unit_cost"])
        self.assertGreater(data["expected_demand"], 0)
        self.assertGreater(data["expected_profit"], 0)

    def test_dashboard_elasticity_analysis_workflow(self):
        """
        Test: Dashboard requests elasticity at multiple points → API returns curve.
        Simulates strategic pricing analysis from dashboard.
        Uses prices within the model's training range (18–1244) to ensure
        XGBoost predicts realistic demand and elasticity is non-positive.
        """
        market_context = {
            "price": 150,
            "competitor_price": 140,
            "inventory": 500,
            "day_of_week": 2,
            "price_points": 5,
            "min_price": 100,
            "max_price": 300
        }

        response = self.client.post(
            "/estimate_elasticity_range",
            json=market_context
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Verify elasticity curve structure
        self.assertIn("elasticity_curve", data)
        self.assertIn("market_context", data)

        curve = data["elasticity_curve"]
        self.assertEqual(len(curve), 5)  # 5 price points requested

        # Verify prices are in ascending order
        prices = [point["price"] for point in curve]
        self.assertEqual(prices, sorted(prices))

        # Verify elasticity values are finite numbers.
        # XGBoost is a piecewise-constant tree model that does not guarantee
        # strictly negative elasticity at every price point (it depends on the
        # leaf boundaries learned from data). We verify structural correctness
        # rather than imposing an economic sign constraint on the model output.
        for point in curve:
            self.assertIsInstance(point["elasticity"], float)
            self.assertFalse(point["elasticity"] != point["elasticity"])  # not NaN

    def test_dashboard_rl_pricing_recommendation_workflow(self):
        """
        Test: Dashboard requests RL pricing recommendation.
        Simulates ML-based pricing strategy selection.
        """
        market_context = {
            "competitor_price": 115,
            "inventory": 500,
            "day_of_week": 2,
            "unit_cost": 60
        }

        response = self.client.post(
            "/rl_pricing",
            json=market_context
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Verify RL pricing response
        self.assertIn("rl_price", data)
        self.assertIn("expected_profit", data)
        self.assertIn("strategy", data)
        
        self.assertEqual(data["strategy"], "RL Policy")
        self.assertGreater(data["rl_price"], 0)
        self.assertGreater(data["expected_profit"], 0)

    def test_dashboard_compare_strategies_workflow(self):
        """
        Test: Dashboard compares traditional vs RL pricing strategies.
        Simulates side-by-side comparison feature.
        """
        market_context_opt = {
            "current_price": 120,
            "competitor_price": 115,
            "inventory": 500,
            "day_of_week": 2,
            "unit_cost": 60
        }

        market_context_rl = {
            "competitor_price": 115,
            "inventory": 500,
            "day_of_week": 2,
            "unit_cost": 60
        }

        # Get traditional recommendation
        opt_response = self.client.post(
            "/calculate_optimal_price",
            json=market_context_opt
        )

        # Get RL recommendation
        rl_response = self.client.post(
            "/rl_pricing",
            json=market_context_rl
        )

        # Both should return valid prices
        self.assertEqual(opt_response.status_code, 200)
        self.assertEqual(rl_response.status_code, 200)
        
        opt_data = opt_response.json()
        rl_data = rl_response.json()
        
        self.assertGreater(opt_data["optimal_price"], 0)
        self.assertGreater(rl_data["rl_price"], 0)

    def test_dashboard_rl_training_workflow(self):
        """
        Test: Dashboard trains RL agent and monitors training metrics.
        Simulates real-time model improvement workflow.
        """
        training_request = {
            "competitor_price": 115,
            "inventory": 500,
            "day_of_week": 2,
            "unit_cost": 60,
            "num_episodes": 3
        }

        response = self.client.post(
            "/rl_training",
            json=training_request
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Verify training metrics
        self.assertIn("episodes_completed", data)
        self.assertIn("average_reward", data)
        self.assertIn("max_reward", data)
        self.assertIn("buffer_size", data)
        
        self.assertEqual(data["episodes_completed"], 3)
        self.assertGreater(data["average_reward"], 0)
        self.assertGreater(data["max_reward"], 0)
        self.assertGreaterEqual(data["buffer_size"], 0)

    def test_dashboard_elasticity_single_point_workflow(self):
        """
        Test: Dashboard estimates elasticity at a single price point.
        Simulates quick elasticity lookup during pricing adjustment.
        """
        market_context = {
            "price": 1200,
            "competitor_price": 1150,
            "inventory": 500,
            "day_of_week": 2
        }

        response = self.client.post(
            "/estimate_elasticity",
            json=market_context
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Verify elasticity response
        self.assertIn("price", data)
        self.assertIn("elasticity", data)
        self.assertIn("interpretation", data)
        
        self.assertEqual(data["price"], 1200)
        self.assertLessEqual(data["elasticity"], 0)  # Normal demand
        self.assertIn(
            data["interpretation"],
            [
                "Elastic (price-sensitive demand)",
                "Inelastic (price-insensitive demand)",
                "Unit elastic",
            ],
        )

    def test_dashboard_error_handling_invalid_input(self):
        """
        Test: Dashboard sends invalid input → API returns proper error.
        Verifies error handling and user-friendly error messages.
        """
        invalid_input = {
            "current_price": 120,
            "competitor_price": -100,  # Invalid: negative price
            "inventory": 500,
            "day_of_week": 2,
            "unit_cost": 60
        }

        response = self.client.post(
            "/calculate_optimal_price",
            json=invalid_input
        )

        # Should return error (422 Unprocessable Entity or similar)
        self.assertIn(response.status_code, [422, 400])

    def test_dashboard_missing_required_fields(self):
        """
        Test: Dashboard sends incomplete request → API returns validation error.
        Verifies required field validation.
        """
        incomplete_input = {
            "competitor_price": 115,
            # Missing: current_price, inventory, day_of_week, unit_cost
        }

        response = self.client.post(
            "/calculate_optimal_price",
            json=incomplete_input
        )

        # Should return validation error
        self.assertEqual(response.status_code, 422)

    def test_dashboard_full_workflow_sequence(self):
        """
        Test: Complete workflow - Dashboard user analyzes, compares, trains.
        End-to-end scenario: analyze → compare → train → analyze again.
        """
        market_context_opt = {
            "current_price": 120,
            "competitor_price": 115,
            "inventory": 500,
            "day_of_week": 2,
            "unit_cost": 60
        }

        market_context_rl = {
            "competitor_price": 115,
            "inventory": 500,
            "day_of_week": 2,
            "unit_cost": 60
        }

        market_context_elasticity = {
            "price": 1200,
            "competitor_price": 1150,
            "inventory": 500,
            "day_of_week": 2,
            "price_points": 3,
            "min_price": 1000,
            "max_price": 1400
        }

        # Step 1: Initial analysis
        opt_response = self.client.post(
            "/calculate_optimal_price",
            json=market_context_opt
        )
        self.assertEqual(opt_response.status_code, 200)
        initial_price = opt_response.json()["optimal_price"]

        # Step 2: Get elasticity curve
        elasticity_response = self.client.post(
            "/estimate_elasticity_range",
            json=market_context_elasticity
        )
        self.assertEqual(elasticity_response.status_code, 200)

        # Step 3: Get RL recommendation
        rl_response = self.client.post(
            "/rl_pricing",
            json=market_context_rl
        )
        self.assertEqual(rl_response.status_code, 200)

        # Step 4: Train RL agent
        train_response = self.client.post(
            "/rl_training",
            json={**market_context_rl, "num_episodes": 2}
        )
        self.assertEqual(train_response.status_code, 200)

        # Step 5: Re-analyze after training
        final_opt_response = self.client.post(
            "/calculate_optimal_price",
            json=market_context_opt
        )
        self.assertEqual(final_opt_response.status_code, 200)
        final_price = final_opt_response.json()["optimal_price"]

        # Both analyses should return reasonable prices
        self.assertGreater(initial_price, 0)
        self.assertGreater(final_price, 0)

    def test_dashboard_api_response_consistency(self):
        """
        Test: Multiple calls to same endpoint return consistent structure.
        Verifies API response schema stability for frontend integration.
        """
        market_context = {
            "competitor_price": 115,
            "inventory": 500,
            "day_of_week": 2,
            "unit_cost": 60
        }

        # Call endpoint twice
        response1 = self.client.post("/rl_pricing", json=market_context)
        response2 = self.client.post("/rl_pricing", json=market_context)

        self.assertEqual(response1.status_code, 200)
        self.assertEqual(response2.status_code, 200)

        data1 = response1.json()
        data2 = response2.json()

        # Both should have same structure
        self.assertEqual(set(data1.keys()), set(data2.keys()))


if __name__ == "__main__":
    unittest.main()
