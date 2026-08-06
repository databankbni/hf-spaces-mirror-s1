import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from superagi_backend.runner import (
    DEFAULT_MODEL,
    MODEL_OPTIONS,
    ModelRouter,
    RunPodModelRunner,
    SuperAGICheckpointRunner,
    build_prompt,
    create_model_runner_from_env,
)


class RunnerConfigurationTest(unittest.TestCase):
    def test_default_model_is_newest_superagi_option(self):
        self.assertEqual(MODEL_OPTIONS, ("SuperAGI 0.2",))
        self.assertEqual(DEFAULT_MODEL, "SuperAGI 0.2")

    def test_model_router_resolves_supported_aliases(self):
        runner = RecordingRunner("routed reply")
        router = ModelRouter(
            runners={"SuperAGI 0.2": runner},
            default_model="SuperAGI 0.2",
            aliases={"SuperAGI 0.1": "SuperAGI 0.2"},
            model_options=("SuperAGI 0.1", "SuperAGI 0.2"),
        )

        reply = router.generate(prompt="User: hello\nAGI:", model="SuperAGI 0.1")

        self.assertEqual(reply, "routed reply")
        self.assertEqual(router.resolve_model("SuperAGI 0.1"), "SuperAGI 0.2")
        self.assertEqual(
            runner.calls,
            [{"prompt": "User: hello\nAGI:", "model": "SuperAGI 0.2"}],
        )
        self.assertEqual(router.describe()["model"], "SuperAGI 0.2")
        self.assertEqual(router.describe()["models"][0]["served_by"], "SuperAGI 0.2")

    def test_create_runner_uses_bundled_old_03_checkpoint_as_public_superagi_02(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo_path = root / "vendor" / "SuperAGI"
            checkpoint_path = root / "models" / "superagi" / "superagi-0.3.pt"
            (repo_path / "src").mkdir(parents=True)
            checkpoint_path.parent.mkdir(parents=True)
            checkpoint_path.write_bytes(b"checkpoint")

            with patch.dict(os.environ, {}, clear=True), patch(
                "superagi_backend.runner.BUNDLED_SUPERAGI_REPO_PATH",
                repo_path,
            ), patch(
                "superagi_backend.runner.BUNDLED_MODEL_CHECKPOINT_PATHS",
                {
                    "SuperAGI 0.2": checkpoint_path,
                },
            ):
                runner = create_model_runner_from_env()

        self.assertIsInstance(runner, ModelRouter)
        self.assertIsInstance(runner.runners["SuperAGI 0.2"], SuperAGICheckpointRunner)
        self.assertEqual(runner.resolve_model("SuperAGI 0.2"), "SuperAGI 0.2")
        self.assertEqual(runner.runners["SuperAGI 0.2"].repo_path, repo_path)
        self.assertEqual(runner.runners["SuperAGI 0.2"].checkpoint_path, checkpoint_path)

    def test_create_runner_routes_superagi_02_to_own_checkpoint_when_configured(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo_path = root / "SuperAGI"
            checkpoint_path = root / "superagi-0.2.pt"
            (repo_path / "src").mkdir(parents=True)
            checkpoint_path.write_bytes(b"checkpoint")

            with patch.dict(
                os.environ,
                {
                    "SUPERAGI_0_2_REPO_PATH": str(repo_path),
                    "SUPERAGI_0_2_CHECKPOINT_PATH": str(checkpoint_path),
                },
                clear=True,
            ), patch(
                "superagi_backend.runner.BUNDLED_SUPERAGI_REPO_PATH",
                root / "missing" / "repo",
            ), patch(
                "superagi_backend.runner.BUNDLED_MODEL_CHECKPOINT_PATHS",
                {},
            ):
                runner = create_model_runner_from_env()

        self.assertIsInstance(runner, ModelRouter)
        self.assertEqual(runner.resolve_model("SuperAGI 0.2"), "SuperAGI 0.2")
        self.assertIsInstance(runner.runners["SuperAGI 0.2"], SuperAGICheckpointRunner)
        self.assertEqual(runner.runners["SuperAGI 0.2"].checkpoint_path, checkpoint_path)

    def test_create_runner_keeps_generation_defaults_for_public_superagi_02(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo_path = root / "vendor" / "SuperAGI"
            checkpoint_03_path = root / "models" / "superagi" / "superagi-0.3.pt"
            (repo_path / "src").mkdir(parents=True)
            checkpoint_03_path.parent.mkdir(parents=True)
            checkpoint_03_path.write_bytes(b"checkpoint-03")

            with patch.dict(os.environ, {}, clear=True), patch(
                "superagi_backend.runner.BUNDLED_SUPERAGI_REPO_PATH",
                repo_path,
            ), patch(
                "superagi_backend.runner.BUNDLED_MODEL_CHECKPOINT_PATHS",
                {
                    "SuperAGI 0.2": checkpoint_03_path,
                },
            ):
                runner = create_model_runner_from_env()

        self.assertIsInstance(runner, ModelRouter)
        self.assertEqual(runner.resolve_model("SuperAGI 0.2"), "SuperAGI 0.2")
        self.assertIsInstance(runner.runners["SuperAGI 0.2"], SuperAGICheckpointRunner)
        self.assertEqual(runner.runners["SuperAGI 0.2"].checkpoint_path, checkpoint_03_path)
        self.assertEqual(runner.runners["SuperAGI 0.2"].max_new_tokens, 120)
        self.assertEqual(runner.runners["SuperAGI 0.2"].temperature, 0.5)
        self.assertEqual(runner.runners["SuperAGI 0.2"].top_k, 20)
        self.assertEqual(runner.runners["SuperAGI 0.2"].repetition_penalty, 1.25)
        self.assertEqual(runner.runners["SuperAGI 0.2"].repetition_window, 128)
        self.assertEqual(runner.runners["SuperAGI 0.2"].device, "auto")

    def test_create_runner_accepts_legacy_superagi_03_env_for_shifted_superagi_02(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo_path = root / "SuperAGI"
            checkpoint_path = root / "superagi-0.3.pt"
            (repo_path / "src").mkdir(parents=True)
            checkpoint_path.write_bytes(b"checkpoint")

            with patch.dict(
                os.environ,
                {
                    "SUPERAGI_0_3_REPO_PATH": str(repo_path),
                    "SUPERAGI_0_3_CHECKPOINT_PATH": str(checkpoint_path),
                },
                clear=True,
            ), patch(
                "superagi_backend.runner.BUNDLED_SUPERAGI_REPO_PATH",
                root / "missing" / "repo",
            ), patch(
                "superagi_backend.runner.BUNDLED_MODEL_CHECKPOINT_PATHS",
                {},
            ):
                runner = create_model_runner_from_env()

        self.assertIsInstance(runner, ModelRouter)
        self.assertEqual(runner.resolve_model("SuperAGI 0.2"), "SuperAGI 0.2")
        self.assertIsInstance(runner.runners["SuperAGI 0.2"], SuperAGICheckpointRunner)
        self.assertEqual(runner.runners["SuperAGI 0.2"].repo_path, repo_path)
        self.assertEqual(runner.runners["SuperAGI 0.2"].checkpoint_path, checkpoint_path)

    def test_create_runner_uses_runpod_when_endpoint_and_api_key_are_configured(self):
        with patch.dict(
            os.environ,
            {
                "RUNPOD_ENDPOINT_ID": "endpoint-123",
                "RUNPOD_API_KEY": "secret-key",
            },
            clear=True,
        ):
            runner = create_model_runner_from_env()

        self.assertIsInstance(runner, ModelRouter)
        self.assertEqual(runner.resolve_model("SuperAGI 0.2"), "SuperAGI 0.2")
        self.assertIsInstance(runner.runners["SuperAGI 0.2"], RunPodModelRunner)
        self.assertEqual(runner.runners["SuperAGI 0.2"].endpoint_id, "endpoint-123")

    def test_build_prompt_uses_sft_chat_labels(self):
        prompt = build_prompt(
            [
                {"role": "visitor", "text": "Hello"},
                {"role": "assistant", "text": "Hi"},
                {"role": "visitor", "text": "What can you do?"},
            ]
        )

        self.assertEqual(prompt, "User: Hello\nAGI: Hi\nUser: What can you do?\nAGI:")


class RunPodModelRunnerTest(unittest.TestCase):
    def test_generate_sends_runsync_request_with_generation_parameters(self):
        requests = []

        def fake_urlopen(request, timeout):
            requests.append({"request": request, "timeout": timeout})
            return FakeHttpResponse({"output": {"text": "RunPod reply"}})

        runner = RunPodModelRunner(
            endpoint_id="endpoint-123",
            api_key="secret-key",
            base_url="https://api.runpod.test/v2",
            timeout_seconds=42,
            max_new_tokens=120,
            temperature=0.5,
            top_k=20,
            repetition_penalty=1.25,
            repetition_window=128,
        )

        with patch("superagi_backend.runner.urllib.request.urlopen", fake_urlopen):
            reply = runner.generate(prompt="User: Hello\nAGI:", model="SuperAGI 0.2")

        self.assertEqual(reply, "RunPod reply")
        self.assertEqual(requests[0]["timeout"], 42)
        self.assertEqual(
            requests[0]["request"].full_url,
            "https://api.runpod.test/v2/endpoint-123/runsync",
        )
        self.assertEqual(requests[0]["request"].get_method(), "POST")
        self.assertEqual(requests[0]["request"].headers["Authorization"], "Bearer secret-key")
        self.assertEqual(requests[0]["request"].headers["Content-type"], "application/json")
        self.assertEqual(
            json.loads(requests[0]["request"].data.decode("utf-8")),
            {
                    "input": {
                    "prompt": "User: Hello\nAGI:",
                    "model": "SuperAGI 0.2",
                    "max_new_tokens": 120,
                    "temperature": 0.5,
                    "top_k": 20,
                    "repetition_penalty": 1.25,
                    "repetition_window": 128,
                }
            },
        )

    def test_generate_accepts_string_output(self):
        runner = RunPodModelRunner(
            endpoint_id="endpoint-123",
            api_key="secret-key",
            base_url="https://api.runpod.test/v2",
        )

        with patch(
            "superagi_backend.runner.urllib.request.urlopen",
            lambda _request, timeout: FakeHttpResponse({"output": "plain reply"}),
        ):
            reply = runner.generate(prompt="User: Hello\nAGI:", model="SuperAGI 0.2")

        self.assertEqual(reply, "plain reply")

    def test_generate_raises_for_runpod_error_response(self):
        runner = RunPodModelRunner(
            endpoint_id="endpoint-123",
            api_key="secret-key",
            base_url="https://api.runpod.test/v2",
        )

        with patch(
            "superagi_backend.runner.urllib.request.urlopen",
            lambda _request, timeout: FakeHttpResponse({"status": "FAILED", "error": "worker failed"}),
        ):
            with self.assertRaises(RuntimeError) as context:
                runner.generate(prompt="User: Hello\nAGI:", model="SuperAGI 0.2")

        self.assertIn("worker failed", str(context.exception))

    def test_generate_raises_for_runpod_worker_output_error(self):
        runner = RunPodModelRunner(
            endpoint_id="endpoint-123",
            api_key="secret-key",
            base_url="https://api.runpod.test/v2",
        )

        with patch(
            "superagi_backend.runner.urllib.request.urlopen",
            lambda _request, timeout: FakeHttpResponse({"output": {"error": "prompt missing"}}),
        ):
            with self.assertRaises(RuntimeError) as context:
                runner.generate(prompt="User: Hello\nAGI:", model="SuperAGI 0.2")

        self.assertIn("prompt missing", str(context.exception))

    def test_describe_does_not_expose_api_key(self):
        runner = RunPodModelRunner(
            endpoint_id="endpoint-123",
            api_key="secret-key",
            base_url="https://api.runpod.test/v2",
            timeout_seconds=42,
        )

        description = runner.describe()

        self.assertEqual(description["runner"], "runpod-serverless")
        self.assertEqual(description["endpoint_id"], "endpoint-123")
        self.assertEqual(description["timeout_seconds"], 42)
        self.assertNotIn("api_key", description)
        self.assertNotIn("secret-key", str(description))


class RecordingRunner:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def generate(self, *, prompt, model):
        self.calls.append({"prompt": prompt, "model": model})
        return self.replies.pop(0)

    def describe(self):
        return {
            "model": "SuperAGI 0.2",
            "runner": "recording",
            "ready": True,
        }


class FakeHttpResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, _exception_type, _exception, _traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
