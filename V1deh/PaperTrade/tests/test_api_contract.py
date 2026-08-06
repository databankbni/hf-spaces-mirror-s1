import time
import unittest
from unittest.mock import patch

from app import app as flask_app
import app as _app_module
from app import _classify_watchlist_warning


class ApiContractTests(unittest.TestCase):
    def setUp(self):
        self.client = flask_app.test_client()

    @patch("app.predict_stock_v2")
    def test_predict_response_contract_includes_trade_plan_fields(self, mock_predict):
        mock_predict.return_value = {
            "ticker": "RELIANCE.NS",
            "company": "Reliance Industries",
            "timeframe": "3D",
            "price": 2500.0,
            "direction": "BULLISH",
            "confidence": "HIGH",
            "ret_lo": 1.2,
            "ret_hi": 2.4,
            "midpoint": 1.8,
            "target_price_lo": 2530.0,
            "target_price_hi": 2560.0,
            "expected_target_price": 2545.0,
            "expected_entry_price": 2500.0,
            "trade_plan": {
                "expected_entry_price": 2500.0,
                "expected_target_price": 2545.0,
                "target_price_lo": 2530.0,
                "target_price_hi": 2560.0,
                "stop_loss": 2460.0,
                "risk_reward": 2.0,
                "holding_timeframe": "3D",
            },
            "risk": {
                "stop_loss": 2460.0,
                "stop_loss_pct": 1.6,
                "min_target": 2580.0,
                "actual_rr": 2.0,
            },
        }

        resp = self.client.post(
            "/api/predict",
            json={"stocks": ["RELIANCE.NS"], "timeframe": "3D"},
        )

        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertIn("predictions", payload)
        self.assertEqual(len(payload["predictions"]), 1)

        pred = payload["predictions"][0]
        self.assertIn("timeframe", pred)
        self.assertIn("expected_entry_price", pred)
        self.assertIn("expected_target_price", pred)
        self.assertIn("target_price_lo", pred)
        self.assertIn("target_price_hi", pred)
        self.assertIn("trade_plan", pred)

        trade_plan = pred["trade_plan"]
        self.assertIn("expected_entry_price", trade_plan)
        self.assertIn("expected_target_price", trade_plan)
        self.assertIn("target_price_lo", trade_plan)
        self.assertIn("target_price_hi", trade_plan)
        self.assertIn("holding_timeframe", trade_plan)

    def setUp(self):
        self.client = flask_app.test_client()
        # Clear top5 cache so tests start from a known state
        _app_module._TOP5_CACHE.clear()

    def test_top5_response_contract_includes_timeframe_target_fields(self):
        tf_data = {
            "expected_return_range": "+1.2% to +2.4%",
            "midpoint": 1.8,
            "ret_lo": 1.2,
            "ret_hi": 2.4,
            "expected_entry_price": 2500.0,
            "expected_target_price": 2545.0,
            "target_price_lo": 2530.0,
            "target_price_hi": 2560.0,
            "direction": "BULLISH",
            "confidence": "HIGH",
            "no_trade_reason": None,
            "signal_count": 0,
            "ai_forecast": {"direction": "BULLISH", "confidence": "HIGH"},
        }
        mock_result = {
            "generated_at": "2026-06-21 12:00",
            "market": {},
            "picks": [
                {
                    "ticker": "RELIANCE.NS",
                    "company": "Reliance Industries",
                    "price": 2500.0,
                    "direction": "BULLISH",
                    "confidence": "HIGH",
                    "signals": {},
                    "signal_count": 0,
                    "timeframes": {
                        "1D": dict(tf_data),
                        "3D": dict(tf_data),
                        "5D": dict(tf_data),
                    },
                }
            ],
        }
        # Inject directly into cache so the endpoint serves it without kicking off background compute
        _app_module._TOP5_CACHE["top5"] = {
            "ts": time.time(),
            "result": mock_result,
            "archived": True,
        }

        resp = self.client.get("/api/top5")

        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertIn("picks", payload)
        self.assertEqual(len(payload["picks"]), 1)

        pick = payload["picks"][0]
        self.assertEqual(pick.get("signals"), {})
        self.assertEqual(pick.get("signal_count"), 0)
        self.assertIn("timeframes", pick)
        for tf in ("1D", "3D", "5D"):
            self.assertIn(tf, pick["timeframes"])
            tfd = pick["timeframes"][tf]
            self.assertIn("expected_entry_price", tfd)
            self.assertIn("expected_target_price", tfd)
            self.assertIn("target_price_lo", tfd)
            self.assertIn("target_price_hi", tfd)
            self.assertEqual(tfd.get("signal_count"), 0)
            self.assertIn("ai_forecast", tfd)

    def test_classify_watchlist_warning_for_missing_label_keyerror(self):
        msg = _classify_watchlist_warning("'label'")
        self.assertIn("Prediction processing error", msg)

    def test_classify_watchlist_warning_for_market_data_error(self):
        raw = "All data sources failed for SCI.NS"
        msg = _classify_watchlist_warning(raw)
        self.assertEqual(msg, f"Market data unavailable: {raw}")


if __name__ == "__main__":
    unittest.main()
