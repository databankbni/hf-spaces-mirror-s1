import importlib
import os
from pathlib import Path

import pytest


@pytest.fixture
def backend_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def test_supabase_storage_loads_env_from_backend_directory(monkeypatch, backend_dir: Path):
    monkeypatch.chdir(backend_dir.parent)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_STORAGE_BUCKET", raising=False)

    monkeypatch.syspath_prepend(str(backend_dir))

    import supabase_storage

    importlib.reload(supabase_storage)

    # Load expected values from the backend/.env file so the test does not rely on a hardcoded secret
    env_path = backend_dir / ".env"
    expected_service_key = ""
    expected_url = ""
    expected_bucket = "videos"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.strip().startswith("SUPABASE_SERVICE_ROLE_KEY"):
                # format: KEY="value" or KEY=value
                parts = line.split("=", 1)
                if len(parts) == 2:
                    expected_service_key = parts[1].strip().strip('"').strip("'")
            if line.strip().startswith("SUPABASE_URL"):
                parts = line.split("=", 1)
                if len(parts) == 2:
                    expected_url = parts[1].strip().strip('"').strip("'")
            if line.strip().startswith("SUPABASE_STORAGE_BUCKET"):
                parts = line.split("=", 1)
                if len(parts) == 2:
                    expected_bucket = parts[1].strip().strip('"').strip("'")

    assert supabase_storage.SUPABASE_URL == expected_url
    assert supabase_storage.SUPABASE_SERVICE_ROLE_KEY == expected_service_key
    assert supabase_storage.SUPABASE_STORAGE_BUCKET == expected_bucket
