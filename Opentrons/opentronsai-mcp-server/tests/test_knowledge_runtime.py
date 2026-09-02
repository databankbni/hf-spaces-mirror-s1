"""Offline tests for committed knowledge runtime loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from api.knowledge.cache import is_runtime_ready, load_knowledge_runtime, runtime_paths_for

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_load_knowledge_runtime_positive() -> None:
    paths = load_knowledge_runtime(version="9.0.0-k1", repo_root=REPO_ROOT)
    assert paths.version == "9.0.0-k1"
    assert paths.version_marker.read_text(encoding="utf-8").strip() == "9.0.0-k1"
    assert paths.api_docs_struct.is_file()
    assert any(paths.ai_docs_path.glob("*.md"))
    assert (paths.api_docs_content_root / "modules" / "thermocycler.md").is_file()
    assert is_runtime_ready(paths, "9.0.0-k1")


def test_load_knowledge_runtime_wrong_version_negative() -> None:
    with pytest.raises(RuntimeError, match="wrong version|missing"):
        load_knowledge_runtime(version="0.0.0-missing", repo_root=REPO_ROOT)


def test_runtime_paths_layout() -> None:
    paths = runtime_paths_for(version="9.0.0-k1", repo_root=REPO_ROOT)
    assert paths.ai_docs_path == REPO_ROOT / "storage" / "docs"
    assert paths.api_docs_content_root == REPO_ROOT / "storage" / "api_docs" / "docs" / "v2"
    assert paths.api_docs_struct.name == "api_docs_struct.md"


def test_storage_contains_only_synced_runtime_docs() -> None:
    """Committed storage must not retain pre-knowledge leftovers."""
    storage = REPO_ROOT / "storage"
    docs = storage / "docs"
    api_docs = storage / "api_docs"

    assert not (docs / "pd").exists()
    assert not (api_docs / "scripts").exists()
    assert not (api_docs / "api_docs_struct_about.md").exists()
    assert not (api_docs / "api_docs_struct_v2.25.md").exists()
    assert not list(docs.rglob("*.rst"))
    assert not list(api_docs.rglob("*.rst"))
    assert not list(api_docs.rglob("*.py"))

    # AI guides are top-level markdown only (no nested leftover trees).
    assert all(path.is_file() and path.suffix == ".md" for path in docs.iterdir())

    # api_docs tree is markers + generated struct + MkDocs v2 pages.
    allowed_api_top = {
        ".api-level",
        ".knowledge-version",
        "api_docs_struct.md",
        "docs",
    }
    assert {path.name for path in api_docs.iterdir()} == allowed_api_top
    assert (api_docs / "docs" / "v2").is_dir()
    assert all(path.suffix == ".md" for path in (api_docs / "docs" / "v2").rglob("*") if path.is_file())
