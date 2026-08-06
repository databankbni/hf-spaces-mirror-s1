import unittest

from fastapi.testclient import TestClient

from src.api.pricing_api import app


client = TestClient(app)


class TestAnalyticsApi(unittest.TestCase):
    def test_monitoring_performance_returns_model_metrics(self):
        response = client.get("/monitoring/performance")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertGreater(data["rows_scored"], 0)
        self.assertGreaterEqual(data["rmse"], 0)
        self.assertGreaterEqual(data["mae"], 0)
        self.assertGreaterEqual(data["prediction_accuracy_percent"], 0)
        self.assertLessEqual(data["prediction_accuracy_percent"], 100)


    def test_monitoring_drift_returns_feature_report(self):
        response = client.get("/monitoring/drift")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn(data["status"], {"stable", "watch", "retrain_recommended"})
        self.assertGreater(data["recent_rows"], 0)
        self.assertTrue(data["features"])


    def test_what_if_analysis_returns_scenario_recommendations(self):
        response = client.post(
            "/what_if/analyze",
            json={
                "scenarios": [
                    {
                        "name": "base",
                        "competitor_price": 115,
                        "inventory": 500,
                        "day_of_week": 2,
                        "unit_cost": 60,
                    },
                    {
                        "name": "competitor_drop",
                        "competitor_price": 100,
                        "inventory": 500,
                        "day_of_week": 2,
                        "unit_cost": 60,
                    },
                ]
            },
        )

        self.assertEqual(response.status_code, 200)
        scenarios = response.json()["scenarios"]
        self.assertEqual(len(scenarios), 2)
        self.assertGreater(scenarios[0]["optimal_price"], 0)
        self.assertGreater(scenarios[0]["expected_profit"], 0)


    def test_causal_effect_estimate_returns_treatment_effect(self):
        response = client.post(
            "/causal_effect/estimate",
            json={
                "rows": [
                    {"price_change": -10, "profit": 900, "inventory": 700},
                    {"price_change": -5, "profit": 980, "inventory": 650},
                    {"price_change": 0, "profit": 1040, "inventory": 620},
                    {"price_change": 5, "profit": 1120, "inventory": 560},
                    {"price_change": 10, "profit": 1080, "inventory": 520},
                ],
                "treatment_column": "price_change",
                "outcome_column": "profit",
                "control_columns": ["inventory"],
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn(data["method"], {"ordinary_least_squares_with_controls", "dowhy_backdoor_linear_regression"})
        self.assertEqual(data["rows_used"], 5)
        self.assertIn("estimated_effect", data)


    def test_monitoring_error_rate_returns_window_stats(self):
        _ = client.get("/health")
        response = client.get("/monitoring/error_rate")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("total_requests", data)
        self.assertIn("total_errors", data)
        self.assertIn("error_rate_percent", data)
        self.assertIn("series", data)


    def test_monitoring_retrain_check_returns_retrain_state(self):
        response = client.post("/monitoring/retrain_check")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("performed", data)
        self.assertIn("reason", data)
        self.assertIn("drift_status", data)


    def test_price_response_curve_returns_requested_points(self):
        response = client.post(
            "/price_response_curve",
            json={
                "competitor_price": 115,
                "inventory": 500,
                "day_of_week": 2,
                "unit_cost": 60,
                "min_price": 80,
                "max_price": 140,
                "price_points": 6,
            },
        )

        self.assertEqual(response.status_code, 200)
        curve = response.json()["curve"]
        self.assertEqual(len(curve), 6)
        self.assertEqual(curve[0]["price"], 80)
        self.assertEqual(curve[-1]["price"], 140)


    def test_analysis_report_returns_all_sections(self):
        response = client.get("/analysis/report")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(set(data.keys()), {"performance", "drift", "ab_summary", "what_if", "causal_effect"})
        self.assertGreater(data["performance"]["rows_scored"], 0)
        self.assertTrue(data["drift"]["features"])
        self.assertTrue(data["what_if"]["scenarios"])
        self.assertIn("estimated_effect", data["causal_effect"])
