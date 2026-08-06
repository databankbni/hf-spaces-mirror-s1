import os
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]


class ServerSettingsTest(unittest.TestCase):
    def test_port_environment_variable_matches_hosted_container_defaults(self):
        get_server_settings = _load_server_settings_factory()

        with patch.dict(
            os.environ,
            {
                "PORT": "7860",
                "SUPERAGI_HOST": "0.0.0.0",
                "SUPERAGI_CHAT_DB": "/data/chat.sqlite3"
            },
            clear=True
        ):
            settings = get_server_settings()

        self.assertEqual(settings.host, "0.0.0.0")
        self.assertEqual(settings.port, 7860)
        self.assertEqual(str(settings.database_path), "/data/chat.sqlite3")

    def test_superagi_port_overrides_generic_port(self):
        get_server_settings = _load_server_settings_factory()

        with patch.dict(
            os.environ,
            {
                "PORT": "7860",
                "SUPERAGI_PORT": "5001"
            },
            clear=True
        ):
            settings = get_server_settings()

        self.assertEqual(settings.port, 5001)


class HuggingFaceDeploymentFilesTest(unittest.TestCase):
    def test_dockerfile_runs_production_backend_on_hugging_face_port(self):
        dockerfile = _read_required_file(REPO_ROOT / "Dockerfile")

        self.assertIn("PYTHONPATH=/app/python_backend", dockerfile)
        self.assertIn("pip install --no-cache-dir -r python_backend/requirements.txt", dockerfile)
        self.assertIn("EXPOSE 7860", dockerfile)
        self.assertIn('CMD ["python", "-m", "superagi_backend.production"]', dockerfile)

    def test_hugging_face_space_readme_declares_docker_sdk(self):
        readme = _read_required_file(REPO_ROOT / "huggingface.README.md")

        self.assertIn("sdk: docker", readme)
        self.assertIn("app_port: 7860", readme)
        self.assertIn("SuperAGI Chat API", readme)

    def test_makefile_has_local_container_workflow(self):
        makefile = _read_required_file(REPO_ROOT / "Makefile")

        self.assertIn("docker-build:", makefile)
        self.assertIn("docker-run:", makefile)
        self.assertIn("docker-test:", makefile)
        self.assertIn("-p 7860:7860", makefile)

    def test_backend_requirements_include_production_server(self):
        requirements = _read_required_file(REPO_ROOT / "python_backend" / "requirements.txt")

        self.assertIn("waitress", requirements)

    def test_dockerfile_installs_superagi_model_dependencies_by_default(self):
        dockerfile = _read_required_file(REPO_ROOT / "Dockerfile")

        self.assertIn("ARG INSTALL_SUPERAGI_DEPS=true", dockerfile)

    def test_supabase_heartbeat_workflow_keeps_free_database_active(self):
        workflow = _read_required_file(
            REPO_ROOT / ".github" / "workflows" / "keep-supabase-awake.yml"
        )

        self.assertIn("cron:", workflow)
        self.assertIn("SUPABASE_URL", workflow)
        self.assertIn("SUPABASE_SERVICE_ROLE_KEY", workflow)
        self.assertIn("/rest/v1/chat_sessions?select=session_id&limit=1", workflow)


def _load_server_settings_factory():
    module_path = REPO_ROOT / "python_backend" / "superagi_backend" / "server_config.py"
    if not module_path.exists():
        raise AssertionError("superagi_backend.server_config must exist")

    from superagi_backend.server_config import get_server_settings

    return get_server_settings


def _read_required_file(path):
    if not path.exists():
        raise AssertionError(f"{path.relative_to(REPO_ROOT)} must exist")
    return path.read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
