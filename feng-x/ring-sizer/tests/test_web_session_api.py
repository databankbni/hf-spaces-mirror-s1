import json
import unittest
import uuid
from unittest.mock import patch

from web_demo.app import app


def raw_multi(index):
    return {
        "fail_reason": None,
        "handedness": "Right",
        "overall_best_size": 8,
        "overall_range_min": 7,
        "overall_range_max": 9,
        "fingers_measured": 3,
        "fingers_succeeded": 3,
        "per_finger": {
            "index": {
                "status": "ok", "diameter_cm": index, "confidence": 0.61,
                "best_match": 8, "range": [7, 8], "fail_reason": None,
            },
            "middle": {
                "status": "ok", "diameter_cm": 1.90, "confidence": 0.62,
                "best_match": 9, "range": [8, 9], "fail_reason": None,
            },
            "ring": {
                "status": "ok", "diameter_cm": 1.70, "confidence": 0.60,
                "best_match": 7, "range": [6, 7], "fail_reason": None,
            },
        },
    }


class WebSessionApiTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()
        self.session_id = str(uuid.uuid4())

    def post_default(self, state=None):
        data = {
            "kol_email": "user@example.com",
            "ring_model": "gen",
            "mode": "multi",
            "session_id": self.session_id,
        }
        if state is not None:
            data["session_state"] = json.dumps(state)
        return self.client.post("/api/measure-default", data=data)

    @patch("web_demo.app._save_json")
    @patch("web_demo.app._persist_measurement_async")
    @patch("web_demo.app.image_sha256", side_effect=["a" * 64, "b" * 64])
    @patch("web_demo.app.measure_multi_finger")
    def test_two_shots_return_median_and_persist_raw_plus_snapshot(
        self, measure_mock, _hash_mock, persist_mock, _save_mock
    ):
        measure_mock.side_effect = [raw_multi(1.70), raw_multi(1.90)]

        first_response = self.post_default()
        self.assertEqual(first_response.status_code, 200)
        first = first_response.get_json()
        self.assertEqual(
            first["session_recommendation"]["per_finger"]["index"]["diameter_cm"],
            1.70,
        )

        second_response = self.post_default(first["session_state"])
        self.assertEqual(second_response.status_code, 200)
        second = second_response.get_json()
        self.assertEqual(second["result"]["per_finger"]["index"]["diameter_cm"], 1.90)
        self.assertEqual(
            second["session_recommendation"]["per_finger"]["index"]["diameter_cm"],
            1.80,
        )
        self.assertEqual(
            second["session_recommendation"]["per_finger"]["index"]["sample_count"],
            2,
        )
        self.assertEqual(
            second["session_recommendation"]["per_finger"]["index"][
                "decision_diameter_mm"
            ],
            18.0,
        )

        second_record = persist_mock.call_args_list[1].kwargs["record"]
        self.assertEqual(second_record["per_finger"]["index"]["diameter_cm"], 1.90)
        self.assertEqual(
            second_record["session_recommendation"]["per_finger"]["index"]["diameter_cm"],
            1.80,
        )
        self.assertEqual(
            second_record["session_recommendation"]["per_finger"]["index"][
                "decision_diameter_mm"
            ],
            18.0,
        )
        self.assertEqual(second_record["session_attempt_index"], 2)

    @patch("web_demo.app._save_json")
    @patch("web_demo.app._persist_measurement_async")
    @patch("web_demo.app.measure_multi_finger", return_value=raw_multi(1.80))
    def test_old_client_without_session_fields_keeps_single_shot_contract(
        self, _measure_mock, _persist_mock, _save_mock
    ):
        response = self.client.post(
            "/api/measure-default",
            data={"kol_email": "user@example.com", "ring_model": "gen", "mode": "multi"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertIsNone(body["session_state"])
        self.assertIsNone(body["session_recommendation"])
        self.assertEqual(body["result"]["per_finger"]["index"]["diameter_cm"], 1.80)


if __name__ == "__main__":
    unittest.main()
