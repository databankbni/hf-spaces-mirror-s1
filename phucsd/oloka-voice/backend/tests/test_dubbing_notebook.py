import os
import pytest
from app.services.dubbing_notebook_builder import DubbingNotebookBuilder

def test_dubbing_notebook_builder(tmp_path):
    worker_dir = str(tmp_path / "dubbing_worker_test")
    abs_path = DubbingNotebookBuilder.ensure_worker_dir(worker_dir)
    assert os.path.exists(abs_path)

    metadata_path = DubbingNotebookBuilder.generate_metadata(abs_path, "testuser", "test-dubbing-slug", "Test Dubbing Worker")
    assert os.path.exists(metadata_path)

    req_path = DubbingNotebookBuilder.generate_requirements(abs_path)
    assert os.path.exists(req_path)
    with open(req_path, "r", encoding="utf-8") as f:
        req_content = f.read()
        assert "demucs" in req_content
        assert "omnivoice" in req_content

    worker_path = DubbingNotebookBuilder.generate_worker_code(abs_path, "https://test.oloka.net", "test_token")
    assert os.path.exists(worker_path)
    with open(worker_path, "r", encoding="utf-8") as f:
        code = f.read()
        assert "DUBBING-WORKER" in code
        assert "demucs" in code
        assert "separate_audio" in code
        assert "dub_segments" in code
