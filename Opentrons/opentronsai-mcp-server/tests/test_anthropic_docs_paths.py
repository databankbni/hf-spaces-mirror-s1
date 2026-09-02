"""Unit tests for MkDocs path resolution used by get_relevant_api_docs."""

from __future__ import annotations

from pathlib import Path

import pytest

from api.domain.anthropic_predict import AnthropicPredict
from api.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def predictor(monkeypatch: pytest.MonkeyPatch) -> AnthropicPredict:
    # Avoid requiring a real Anthropic key for path wiring tests.
    settings = Settings(anthropic_api_key="sk-test", knowledge_version="9.0.0-k1")
    return AnthropicPredict(settings)


def test_api_doc_resolve_positive_mkdocs_path(predictor: AnthropicPredict) -> None:
    path = predictor._api_doc_resolve_path("modules/thermocycler.md")
    assert path is not None
    assert path.is_file()
    assert path.name == "thermocycler.md"


def test_api_doc_resolve_positive_legacy_prefix(predictor: AnthropicPredict) -> None:
    path = predictor._api_doc_resolve_path("docs/v2/modules/thermocycler.md")
    assert path is not None
    assert path.is_file()


def test_api_doc_resolve_negative_rst_rejected(predictor: AnthropicPredict) -> None:
    assert predictor._api_doc_resolve_path("modules/thermocycler.rst") is None


def test_parse_and_load_docs_positive(predictor: AnthropicPredict) -> None:
    xml = predictor._parse_and_load_docs(
        "<relevant_files>\nmodules/thermocycler.md,\npipettes/loading.md\n</relevant_files>"
    )
    assert xml.count("<file ") == 2
    assert "thermocycler.md" in xml
    assert "loading.md" in xml


def test_parse_and_load_docs_negative_missing_tags(predictor: AnthropicPredict) -> None:
    xml = predictor._parse_and_load_docs("no relevant files here")
    assert xml == "<relevant_file_content>\n</relevant_file_content>"
