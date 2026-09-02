import unittest
import uuid

from src.session_recommendation import image_sha256, update_session_recommendation


def multi_result(*, handedness="Right", index=1.80, middle=1.90, ring=1.70):
    values = {"index": index, "middle": middle, "ring": ring}
    per_finger = {}
    for finger, value in values.items():
        if value is None:
            per_finger[finger] = {
                "status": "failed",
                "diameter_cm": None,
                "best_match": None,
                "range": None,
                "fail_reason": "finger_isolation_failed",
            }
        else:
            per_finger[finger] = {
                "status": "ok",
                "diameter_cm": value,
                "best_match": 8,
                "range": [7, 8],
                "fail_reason": None,
            }
    return {
        "fail_reason": None,
        "handedness": handedness,
        "per_finger": per_finger,
        "fingers_measured": 3,
        "fingers_succeeded": sum(v is not None for v in values.values()),
    }


class SessionRecommendationTests(unittest.TestCase):
    def setUp(self):
        self.session_id = str(uuid.uuid4())

    def update(self, state, result, image, **kwargs):
        return update_session_recommendation(
            state,
            session_id=self.session_id,
            ring_model=kwargs.get("ring_model", "gen"),
            run_id=kwargs.get("run_id", image),
            image_digest=image_sha256(image.encode()),
            result=result,
            mode=kwargs.get("mode", "multi"),
            finger_index=kwargs.get("finger_index", "index"),
        )

    def test_first_shot_matches_its_diameter(self):
        state, rec = self.update(None, multi_result(index=1.80), "one")
        self.assertEqual(state["attempt_count"], 1)
        self.assertEqual(rec["per_finger"]["index"]["diameter_cm"], 1.80)
        self.assertEqual(rec["per_finger"]["index"]["sample_count"], 1)

    def test_even_and_odd_medians_are_computed_before_size_lookup(self):
        state, _ = self.update(None, multi_result(index=1.70), "one")
        state, rec = self.update(state, multi_result(index=1.90), "two")
        self.assertEqual(rec["per_finger"]["index"]["diameter_cm"], 1.80)
        self.assertEqual(rec["per_finger"]["index"]["sample_count"], 2)
        state, rec = self.update(state, multi_result(index=1.80), "three")
        self.assertEqual(rec["per_finger"]["index"]["diameter_cm"], 1.80)
        self.assertEqual(rec["per_finger"]["index"]["sample_count"], 3)

    def test_size_lookup_rounds_median_to_tenth_mm_and_prefers_smaller_tie(self):
        state, _ = self.update(
            None,
            multi_result(index=1.7784),
            "one",
            ring_model="air",
        )
        _, rec = self.update(
            state,
            multi_result(index=1.7837),
            "two",
            ring_model="air",
        )
        index = rec["per_finger"]["index"]
        self.assertEqual(index["diameter_cm"], 1.78105)
        self.assertEqual(index["decision_diameter_mm"], 17.8)
        self.assertEqual(index["best_match"], 7)

    def test_nearby_medians_on_both_sides_share_the_same_air_decision(self):
        _, above = self.update(
            None,
            multi_result(index=1.7807),
            "above",
            ring_model="air",
        )
        self.session_id = str(uuid.uuid4())
        _, below = self.update(
            None,
            multi_result(index=1.7795),
            "below",
            ring_model="air",
        )
        for rec in (above, below):
            index = rec["per_finger"]["index"]
            self.assertEqual(index["decision_diameter_mm"], 17.8)
            self.assertEqual(index["best_match"], 7)

    def test_partial_failure_only_skips_that_finger(self):
        state, rec = self.update(None, multi_result(index=1.80, middle=None), "one")
        self.assertEqual(rec["per_finger"]["index"]["sample_count"], 1)
        self.assertEqual(rec["per_finger"]["middle"]["status"], "failed")
        self.assertEqual(rec["per_finger"]["middle"]["sample_count"], 0)

    def test_duplicate_image_is_not_counted_twice(self):
        state, _ = self.update(None, multi_result(index=1.80), "same")
        state, rec = self.update(state, multi_result(index=1.80), "same")
        self.assertEqual(state["attempt_count"], 2)
        self.assertEqual(len(state["shots"]), 1)
        self.assertTrue(rec["duplicate_image"])
        self.assertEqual(rec["per_finger"]["index"]["sample_count"], 1)

    def test_hands_are_partitioned(self):
        state, _ = self.update(None, multi_result(handedness="Right", index=1.80), "right")
        state, rec = self.update(state, multi_result(handedness="Left", index=2.00), "left")
        self.assertEqual(rec["handedness"], "Left")
        self.assertEqual(rec["per_finger"]["index"]["diameter_cm"], 2.00)
        self.assertEqual(rec["per_finger"]["index"]["sample_count"], 1)

    def test_total_failure_increments_attempt_without_stale_recommendation(self):
        state, _ = self.update(None, multi_result(index=1.80), "one")
        failed = {"fail_reason": "card_not_detected", "per_finger": {}}
        state, rec = self.update(state, failed, "two")
        self.assertEqual(state["attempt_count"], 2)
        self.assertEqual(len(state["shots"]), 1)
        self.assertIsNone(rec)

    def test_single_mode_uses_same_aggregator(self):
        first = {
            "fail_reason": None,
            "handedness": "Right",
            "finger_outer_diameter_cm": 1.70,
        }
        second = {**first, "finger_outer_diameter_cm": 1.90}
        state, _ = self.update(None, first, "one", mode="single")
        _, rec = self.update(state, second, "two", mode="single")
        self.assertEqual(rec["finger_outer_diameter_cm"], 1.80)
        self.assertEqual(rec["per_finger"]["index"]["sample_count"], 2)

    def test_mismatched_or_malformed_state_starts_fresh(self):
        malformed = {
            "version": 1,
            "session_id": str(uuid.uuid4()),
            "ring_model": "gen",
            "attempt_count": 999,
            "shots": [{"diameter_cm": "hacked"}],
        }
        state, rec = self.update(malformed, multi_result(index=1.80), "one")
        self.assertEqual(state["attempt_count"], 1)
        self.assertEqual(len(state["shots"]), 1)
        self.assertEqual(rec["per_finger"]["index"]["sample_count"], 1)


if __name__ == "__main__":
    unittest.main()
