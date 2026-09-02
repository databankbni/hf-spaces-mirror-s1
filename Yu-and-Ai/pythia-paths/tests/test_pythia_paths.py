import hashlib
import json
import re
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "dataset"
EVIDENCE_PATH = DATASET / "data" / "evidence.jsonl"
CONTEXT_PATH = DATASET / "data" / "published-piqa-context.jsonl"
EVIDENCE_SCHEMA_PATH = DATASET / "schema" / "evidence.schema.json"
CONTEXT_SCHEMA_PATH = DATASET / "schema" / "published-report-context.schema.json"
PROPOSAL_SCHEMA_PATH = DATASET / "schema" / "review-proposal.schema.json"
SOURCE_MANIFEST_PATH = DATASET / "source-manifest.json"
RELEASE_LOCK_PATH = DATASET / "release-lock.json"
SPACE_MANIFEST_PATH = ROOT / "space-manifest.json"
APP_PATH = ROOT / "app.js"
STYLE_PATH = ROOT / "styles.css"

DETAILED_STEPS = [0, 1000, 73000, 143000]
CONTEXT_STEPS = [
    0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1000, 3000,
    13000, 23000, 33000, 43000, 53000, 63000, 73000, 83000,
    93000, 103000, 113000, 123000, 133000, 143000,
]
FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
FULL_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def load_json(path):
    return json.loads(path.read_text())


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PythiaPathsEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = load_jsonl(EVIDENCE_PATH)
        cls.context = load_jsonl(CONTEXT_PATH)
        cls.evidence_schema = load_json(EVIDENCE_SCHEMA_PATH)
        cls.context_schema = load_json(CONTEXT_SCHEMA_PATH)
        cls.proposal_schema = load_json(PROPOSAL_SCHEMA_PATH)
        cls.source_manifest = load_json(SOURCE_MANIFEST_PATH)
        cls.release_lock = load_json(RELEASE_LOCK_PATH)
        cls.space_manifest = load_json(SPACE_MANIFEST_PATH)

    def test_json_schemas_and_every_data_instance_validate(self):
        checker = FormatChecker()
        for schema in (self.evidence_schema, self.context_schema, self.proposal_schema):
            Draft202012Validator.check_schema(schema)
            self.assertFalse(schema["additionalProperties"])
            self.assertNotIn("example.invalid", schema["$id"])

        evidence_validator = Draft202012Validator(self.evidence_schema, format_checker=checker)
        context_validator = Draft202012Validator(self.context_schema, format_checker=checker)
        for row in self.rows:
            self.assertEqual(list(evidence_validator.iter_errors(row)), [])
        for row in self.context:
            self.assertEqual(list(context_validator.iter_errors(row)), [])

    def test_detailed_and_context_frames_are_exact_and_ordered(self):
        self.assertEqual([row["subject"]["step"] for row in self.rows], DETAILED_STEPS)
        self.assertEqual([row["step"] for row in self.context], CONTEXT_STEPS)
        self.assertEqual(len({row["evidence_id"] for row in self.rows}), 4)
        self.assertEqual(len({row["context_id"] for row in self.context}), 27)

    def test_context_contains_all_published_reports_but_not_missing_checkpoints(self):
        detailed = [row["step"] for row in self.context if row["detailed_receipt_in_this_release"]]
        self.assertEqual(detailed, DETAILED_STEPS)
        for row in self.context:
            self.assertEqual(row["declared_ref"], f'step{row["step"]}')
            self.assertEqual(row["tokens_seen"], row["step"] * 2_097_152)
            self.assertEqual(row["tokens_seen_status"], "derived")
            self.assertEqual(row["source_commit"], "a19eecb807ec2c79a39ebf18108816e6ffffc1d5")
            self.assertTrue(FULL_COMMIT.fullmatch(row["source_blob_sha1"]))
            self.assertTrue(row["source_path"].endswith(f'{row["declared_ref"]}.json'))
            self.assertIsNone(row["evaluated_model_commit"])
            self.assertIsNone(row["evaluated_artifact_digest"])
            self.assertEqual(row["comparison_status"], "not_proven")
            self.assertFalse(row["carried_action_authority"])

    def test_mutable_refs_are_separate_from_observed_targets(self):
        for row in self.rows:
            subject = row["subject"]
            self.assertRegex(subject["declared_ref"], r"^step[0-9]+$")
            self.assertNotIn(subject["declared_ref"], {"main", "latest"})
            self.assertTrue(FULL_COMMIT.fullmatch(subject["observed_branch_target_commit"]))
            self.assertIn("branch_target_observed_at", subject)
            self.assertNotIn("resolved_commit", subject)

    def test_tokens_are_labelled_and_reproducibly_derived(self):
        for row in self.rows:
            tokens = row["subject"]["tokens_seen"]
            self.assertEqual(tokens["status"], "derived")
            self.assertEqual(tokens["method"], "step * 2097152")
            self.assertEqual(tokens["source_repo"], "EleutherAI/pythia-70m-deduped")
            self.assertEqual(tokens["value"], row["subject"]["step"] * 2_097_152)

    def test_artifacts_are_metadata_only_and_not_bound_to_evaluations(self):
        for row in self.rows:
            artifact = row["artifact"]
            self.assertTrue(FULL_SHA256.fullmatch(artifact["reported_lfs_oid"]))
            self.assertEqual(artifact["retrieval_status"], "metadata_only")
            self.assertEqual(artifact["execution_status"], "not_run")
            self.assertEqual(artifact["relationship_to_evaluation"], "not_proven")

    def test_metric_sources_are_pinned_but_identity_and_comparison_are_not_promoted(self):
        for row in self.rows:
            observation = row["metric_observation"]
            self.assertEqual(observation["source_commit"], "a19eecb807ec2c79a39ebf18108816e6ffffc1d5")
            self.assertTrue(FULL_COMMIT.fullmatch(observation["source_blob_sha1"]))
            self.assertEqual(observation["comparison_status"], "not_proven")
            self.assertEqual(observation["metric_to_observed_branch_artifact_binding"], "not_proven")
            self.assertIsNone(observation["evaluated_model_commit"])
            self.assertIsNone(observation["evaluated_artifact_digest"])
            self.assertIsNone(observation["harness_revision"])
            self.assertIsNone(observation["sample_count"])

    def test_selection_receipt_distinguishes_visualized_reports_from_detail(self):
        for row in self.rows:
            selection = row["selection"]
            self.assertEqual(selection["model_checkpoint_frame_count"], 154)
            self.assertEqual(selection["published_evaluation_report_frame_count"], 27)
            self.assertEqual(selection["visualized_report_count"], 27)
            self.assertEqual(selection["visualization_scope"], "all-reports-in-pinned-directory")
            self.assertEqual(selection["detailed_receipt_steps"], DETAILED_STEPS)
            self.assertEqual(selection["published_report_without_detailed_receipt_count"], 23)
            self.assertEqual(selection["checkpoint_without_published_report_count"], 127)
            self.assertEqual(selection["detail_selection_method"], "illustrative-hand-selection")
            self.assertFalse(selection["detail_selected_before_outcomes_seen"])
            self.assertEqual(selection["detail_representativeness"], "not_claimed")
            self.assertEqual(selection["task_sampling_frame"], "87-common-reported-tasks")
            self.assertEqual(selection["included_task_metric"], "piqa.acc_norm")
            self.assertEqual(selection["omitted_task_count"], 86)
            self.assertFalse(selection["task_selected_before_outcomes_seen"])

    def test_context_and_detailed_receipts_agree_exactly(self):
        context_by_step = {row["step"]: row for row in self.context}
        for row in self.rows:
            context = context_by_step[row["subject"]["step"]]
            observation = row["metric_observation"]
            self.assertTrue(context["detailed_receipt_in_this_release"])
            self.assertEqual(context["tokens_seen"], row["subject"]["tokens_seen"]["value"])
            self.assertEqual(context["value"], observation["value"])
            self.assertEqual(context["stderr"], observation["stderr"])
            self.assertEqual(context["source_path"], observation["source_path"])
            self.assertEqual(context["source_blob_sha1"], observation["source_blob_sha1"])

    def test_authority_scope_is_local_and_external_status_is_unknown(self):
        for row in self.rows:
            authority = row["authority"]
            self.assertFalse(authority["carried_by_this_record"])
            self.assertFalse(authority["established_by_this_view"])
            self.assertEqual(authority["external_authority_status"], "not_checked")

    def test_resume_gaps_and_replay_boundary_are_never_silent(self):
        required = {
            "optimizer_state_for_exact_resume",
            "scheduler_state_for_exact_resume",
            "dataloader_cursor_for_exact_resume",
            "rng_state_for_exact_resume",
            "gradient_scaler_applicability",
            "data_order_index_for_exact_resume",
            "software_environment_for_exact_resume",
            "distributed_state_completeness",
        }
        for row in self.rows:
            self.assertTrue(required.issubset(row["unknowns"]))
            self.assertEqual(row["claims"]["resume_file_completeness"], "not_proven")
            self.assertEqual(row["claims"]["resume_replay_equivalence"], "not_tested")

    def test_bundle_digests_bytes_and_counts_are_bound_everywhere(self):
        evidence_digest = digest(EVIDENCE_PATH)
        context_digest = digest(CONTEXT_PATH)
        lock_digest = digest(RELEASE_LOCK_PATH)
        source_digest = digest(SOURCE_MANIFEST_PATH)
        app = APP_PATH.read_text()

        for manifest in (self.source_manifest, self.release_lock):
            self.assertEqual(manifest["evidence_bundle"]["sha256"], evidence_digest)
            self.assertEqual(manifest["evidence_bundle"]["bytes"], len(EVIDENCE_PATH.read_bytes()))
            self.assertEqual(manifest["evidence_bundle"]["records"], 4)
            self.assertEqual(manifest["context_bundle"]["sha256"], context_digest)
            self.assertEqual(manifest["context_bundle"]["bytes"], len(CONTEXT_PATH.read_bytes()))
            self.assertEqual(manifest["context_bundle"]["records"], 27)

        self.assertEqual(self.source_manifest["release_lock"]["sha256"], lock_digest)
        self.assertEqual(self.space_manifest["evidence_bundle"]["sha256"], evidence_digest)
        self.assertEqual(self.space_manifest["context_bundle"]["sha256"], context_digest)
        self.assertEqual(self.space_manifest["release_lock"]["sha256"], lock_digest)
        self.assertEqual(self.space_manifest["source_manifest"]["sha256"], source_digest)
        self.assertIn(f'EXPECTED_EVIDENCE_SHA256 = "{evidence_digest}"', app)
        self.assertIn(f'EXPECTED_CONTEXT_SHA256 = "{context_digest}"', app)
        self.assertIn(f'EXPECTED_RELEASE_LOCK_SHA256 = "{lock_digest}"', app)

    def test_release_lock_matches_every_detailed_field(self):
        locked = {record["evidence_id"]: record for record in self.release_lock["records"]}
        self.assertEqual(set(locked), {row["evidence_id"] for row in self.rows})
        for row in self.rows:
            expected = locked[row["evidence_id"]]
            subject = row["subject"]
            artifact = row["artifact"]
            metric = row["metric_observation"]
            actual = {
                "evidence_id": row["evidence_id"],
                "declared_ref": subject["declared_ref"],
                "step": subject["step"],
                "observed_branch_target_commit": subject["observed_branch_target_commit"],
                "reported_lfs_oid": artifact["reported_lfs_oid"],
                "evaluation_source_path": metric["source_path"],
                "evaluation_blob_sha1": metric["source_blob_sha1"],
                "reported_model_args": metric["reported_run_config"]["model_args"],
                "reported_batch_size": metric["reported_run_config"]["batch_size"],
                "reported_device": metric["reported_run_config"]["device"],
                "reported_value": metric["value"],
                "reported_stderr": metric["stderr"],
                "reported_artifact_bytes": artifact["bytes"],
            }
            self.assertEqual(actual, expected)
            self.assertEqual(row["source_reviewed_at"], self.release_lock["source_reviewed_at"])
            self.assertEqual(subject["branch_target_observed_at"], self.release_lock["source_reviewed_at"])

        shared = self.release_lock["shared"]
        self.assertEqual(shared["evaluation_source_repo"], "EleutherAI/pythia")
        self.assertEqual(shared["training_source_repo"], "EleutherAI/pythia")
        self.assertEqual(shared["training_source_commit"], "a19eecb807ec2c79a39ebf18108816e6ffffc1d5")
        self.assertEqual(shared["token_derivation_source_repo"], "EleutherAI/pythia-70m-deduped")
        self.assertEqual(shared["token_derivation_source_path"], "README.md")
        self.assertIsNone(shared["evaluated_model_commit"])
        self.assertIsNone(shared["evaluated_artifact_digest"])
        self.assertEqual(shared["metric_to_observed_branch_artifact_binding"], "not_proven")
        self.assertFalse(self.release_lock["authentication"]["publisher_authenticated"])
        self.assertFalse(self.release_lock["authentication"]["provenance_authenticated"])

    def test_source_manifest_matches_receipts_and_does_not_overclaim(self):
        manifest_by_ref = {record["ref"]: record for record in self.source_manifest["records"]}
        for row in self.rows:
            source = manifest_by_ref[row["subject"]["declared_ref"]]
            self.assertEqual(source["observed_branch_target_commit"], row["subject"]["observed_branch_target_commit"])
            self.assertEqual(source["observed_branch_artifact_reported_lfs_oid"], row["artifact"]["reported_lfs_oid"])
            self.assertEqual(source["evaluation_blob_sha1"], row["metric_observation"]["source_blob_sha1"])
            self.assertIsNone(source["evaluated_model_commit"])
            self.assertEqual(source["metric_to_observed_branch_artifact_binding"], "not_proven")
        self.assertEqual(self.source_manifest["refresh_policy"], "manual-review-required")
        self.assertFalse(self.source_manifest["append_only_enforced"])
        self.assertFalse(self.source_manifest["authentication"]["publisher_authenticated"])

    def test_proposal_schema_records_expiry_and_revalidation_requirements(self):
        properties = self.proposal_schema["properties"]
        required = set(self.proposal_schema["required"])
        self.assertTrue({"expires_at", "not_an_authorization", "revalidate_evidence_before_review"}.issubset(required))
        self.assertTrue(properties["not_an_authorization"]["const"])
        self.assertTrue(properties["revalidate_evidence_before_review"]["const"])
        self.assertIn("consumer must reject", properties["expires_at"]["$comment"].lower())
        self.assertEqual(properties["evidence_bundle_sha256"]["const"], digest(EVIDENCE_PATH))
        self.assertEqual(properties["context_bundle_sha256"]["const"], digest(CONTEXT_PATH))
        self.assertEqual(properties["source_manifest_sha256"]["const"], digest(SOURCE_MANIFEST_PATH))
        self.assertEqual(properties["release_lock_sha256"]["const"], digest(RELEASE_LOCK_PATH))
        self.assertEqual(set(properties["evidence_ids"]["items"]["enum"]), {row["evidence_id"] for row in self.rows})
        self.assertEqual(properties["requested_effects"]["maxItems"], 0)
        authority = properties["authority"]["properties"]
        self.assertFalse(authority["carried_by_this_document"]["const"])
        self.assertFalse(authority["established_by_this_document"]["const"])
        self.assertEqual(authority["external_authority_status"]["const"], "not_checked")
        review_kinds = set(properties["review_kind"]["enum"])
        self.assertTrue(review_kinds.isdisjoint({"resume", "train", "publish", "deploy", "download_weights"}))
        self.assertNotIn("prepare_resume_review", review_kinds)
        self.assertFalse(properties["output"]["properties"]["model_or_training_effect"]["const"])

    def test_space_has_no_forms_third_party_runtime_or_interactive_svg(self):
        html = (ROOT / "index.html").read_text()
        app = APP_PATH.read_text()
        self.assertNotIn("<form", html.lower())
        self.assertIn("connect-src 'self'", html)
        self.assertNotRegex(html, r'<script[^>]+src="https?://')
        self.assertNotRegex(html, r'<link[^>]+href="https?://')
        self.assertNotIn("polyline", app)
        self.assertNotIn('svgElement("path"', app)
        self.assertNotIn("chart-hit", app)
        self.assertNotIn('role: "button"', app)
        self.assertIn('credentials: "omit"', app)
        self.assertNotIn('credentials: "same-origin"', app)
        self.assertIn("const y = (value) => margin.top + (1 - value) * innerHeight;", app)
        self.assertIn("logarithmic horizontal spacing", html)
        self.assertIn('id="context-table-body"', html)
        self.assertIn('id="snapshot-status"', html)
        self.assertIn("formatReviewedAt(lock.source_reviewed_at)", app)
        self.assertNotIn("8 Aug 2026 at 10:24 UTC", html)

    def test_focus_indicators_are_not_removed(self):
        styles = STYLE_PATH.read_text()
        self.assertIn("outline: 3px solid var(--indigo);", styles)
        self.assertNotIn("outline: none", styles)

    def test_space_manifest_scopes_runtime_claims(self):
        runtime = self.space_manifest["runtime"]
        self.assertTrue(runtime["same_origin_evidence_request"])
        self.assertTrue(runtime["same_origin_context_request"])
        self.assertTrue(runtime["same_origin_release_lock_request"])
        self.assertEqual(runtime["fetch_credentials_mode"], "omit")
        self.assertFalse(runtime["automatic_cross_origin_request_by_app"])
        self.assertFalse(runtime["persistent_write_requested_by_app"])
        self.assertFalse(runtime["model_or_training_action_requested"])
        self.assertEqual(runtime["source_navigation"], "user-initiated-only")

    def test_publication_target_pins_the_verified_dataset_commit(self):
        target = self.space_manifest["publication_target"]
        self.assertEqual(target["space_repo_id"], "Yu-and-Ai/pythia-paths")
        self.assertEqual(target["dataset_repo_id"], "Yu-and-Ai/pythia-paths-evidence")
        self.assertEqual(target["dataset_commit"], "62158de98be1f515917a409a4d1efdae413c7427")
        self.assertTrue(target["dataset_commit_publicly_verified"])
        self.assertEqual(target["space_commit_binding"], "provided-by-host-repository")
        html = (ROOT / "index.html").read_text()
        self.assertIn(target["dataset_commit"], html)

    def test_space_manifest_binds_every_release_asset_except_itself(self):
        ignored_parts = {"__pycache__", ".git"}
        actual_files = {
            str(path.relative_to(ROOT))
            for path in ROOT.rglob("*")
            if path.is_file()
            and path != SPACE_MANIFEST_PATH
            and not ignored_parts.intersection(path.parts)
            and path.suffix != ".pyc"
        }
        locked = {asset["path"]: asset for asset in self.space_manifest["assets"]}
        self.assertEqual(set(locked), actual_files)
        for relative, receipt in locked.items():
            path = ROOT / relative
            self.assertEqual(receipt["sha256"], digest(path))
            self.assertEqual(receipt["bytes"], len(path.read_bytes()))
        self.assertFalse(self.space_manifest["authentication"]["publisher_authenticated"])
        self.assertFalse(self.space_manifest["authentication"]["manifest_self_authenticates_publisher"])

    def test_dataset_checksum_file_covers_every_other_dataset_file(self):
        checksum_path = DATASET / "SHA256SUMS"
        entries = {}
        for line in checksum_path.read_text().splitlines():
            checksum, relative = line.split("  ", 1)
            entries[relative] = checksum
        expected = {
            str(path.relative_to(DATASET))
            for path in DATASET.rglob("*")
            if path.is_file() and path != checksum_path
        }
        self.assertEqual(set(entries), expected)
        for relative, expected_digest in entries.items():
            self.assertEqual(expected_digest, digest(DATASET / relative))


if __name__ == "__main__":
    unittest.main()
