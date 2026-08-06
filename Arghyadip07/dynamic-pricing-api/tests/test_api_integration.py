import unittest

from fastapi.testclient import TestClient

from src.api.pricing_api import app


class TestPricingApiIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_root_health_endpoint(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"message": "Dynamic Pricing API is running"})

    def test_calculate_optimal_price_endpoint(self):
        payload = {
            "product_id": 101,
            "current_price": 120.0,
            "competitor_price": 115.0,
            "inventory": 500,
            "day_of_week": 2,
            "unit_cost": 60.0,
        }

        response = self.client.post("/calculate_optimal_price", json=payload)
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertIn("optimal_price", body)
        self.assertIn("expected_demand", body)
        self.assertIn("expected_profit", body)
        self.assertGreater(body["optimal_price"], 0)
        self.assertGreater(body["expected_demand"], 0)
        self.assertGreater(body["expected_profit"], 0)

    def test_calculate_optimal_price_validation(self):
        payload = {
            "product_id": 101,
            "current_price": -10.0,
            "competitor_price": 115.0,
            "inventory": 500,
            "day_of_week": 2,
            "unit_cost": 60.0,
        }

        response = self.client.post("/calculate_optimal_price", json=payload)

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
