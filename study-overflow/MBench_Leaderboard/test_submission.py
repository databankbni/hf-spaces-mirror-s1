import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import app
from scripts.validate_submission import validate_submission_json


VALID_SUBMISSION = {
    "model_name": "ExampleWorldModel",
    "model_link": "https://example.com/model",
    "model_type": "text-conditioned",
    "total_m_score": 52.46,
}


class SubmissionZipTests(unittest.TestCase):
    def test_reads_root_submission_json(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = Path(tmp_dir) / "submission.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr(
                    "leaderboard_submission.json",
                    json.dumps(VALID_SUBMISSION),
                )
                archive.writestr(
                    "verification/entity/summary.json",
                    json.dumps({"score": 1}),
                )

            self.assertEqual(
                app.read_submission_json_from_zip(zip_path),
                VALID_SUBMISSION,
            )

    def test_rejects_zip_without_root_submission_json(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = Path(tmp_dir) / "submission.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr(
                    "verification/entity/summary.json",
                    json.dumps(VALID_SUBMISSION),
                )

            with self.assertRaisesRegex(
                ValueError,
                "leaderboard_submission.json at the root",
            ):
                app.read_submission_json_from_zip(zip_path)

    def test_upload_commits_only_pending_json_and_zip(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            local_root = Path(tmp_dir)
            pending_dir = local_root / "submissions" / "pending"
            pending_dir.mkdir(parents=True)
            json_path = pending_dir / "submission.json"
            zip_path = pending_dir / "submission.zip"
            json_path.write_text("{}", encoding="utf-8")
            zip_path.write_bytes(b"zip")

            with (
                patch.object(app, "LOCAL_LEADERBOARD_PATH", local_root),
                patch("app.HfApi") as api_class,
            ):
                app.upload_pending_submission(
                    "test-token",
                    "ExampleWorldModel",
                    json_path,
                    zip_path,
                )

            kwargs = api_class.return_value.create_commit.call_args.kwargs
            self.assertEqual(
                kwargs["repo_id"],
                "PeanutUp/membench_leaderboard_submission",
            )
            self.assertEqual(kwargs["repo_type"], "dataset")
            self.assertEqual(
                [operation.path_in_repo for operation in kwargs["operations"]],
                [
                    "submissions/pending/submission.json",
                    "submissions/pending/submission.zip",
                ],
            )

    def test_rejects_out_of_range_score(self):
        submission = {**VALID_SUBMISSION, "total_m_score": 100.01}
        valid, message = validate_submission_json(submission)
        self.assertFalse(valid)
        self.assertIn("between 0 and 100", message)


if __name__ == "__main__":
    unittest.main()
