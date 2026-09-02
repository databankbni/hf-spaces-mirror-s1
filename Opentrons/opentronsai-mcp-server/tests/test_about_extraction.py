"""Tests for cleaned API docs <about> generation from current markdown."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from api.domain.anthropic_predict import AnthropicPredict
from api.knowledge.materialize import apply_doc_templates, extract_about
from api.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[1]
API_DOCS = REPO_ROOT / "storage" / "api_docs"
STRUCT_PATH = API_DOCS / "api_docs_struct.md"
VERSIONING_PATH = API_DOCS / "docs" / "v2" / "versioning.md"


def test_extract_about_strips_mkdocs_noise() -> None:
    markdown = """## Aspirate

To draw liquid up into a pipette tip, call the aspirate method.

!!! note
    This note should not appear in the about text.

```python
pipette.aspirate(200, plate["A1"])
```

=== "Blocking"
    more tab content

You can also dispense afterward.
"""
    about = extract_about(markdown, "Python API: Liquid Control", ["Aspirate"])
    assert "!!!" not in about
    assert "```" not in about
    assert "===" not in about
    assert "pipette.aspirate(200" not in about
    assert "draw liquid" in about.lower()
    assert "Sections: Aspirate" in about


def test_extract_about_includes_current_api_version_facts() -> None:
    markdown = """## API and robot software versions

| API Version | Introduced in Robot Software |
|-------------|------------------------------|
| 2.28        | 9.0.0                        |
| 2.27        | 8.8.0                        |

You must specify apiLevel in metadata or requirements.
"""
    about = extract_about(
        markdown,
        "Python API: Versioning",
        ["API and robot software versions"],
    )
    assert "2.28" in about
    assert "9.0.0" in about
    assert "8.6.0" not in about


def test_extract_about_negative_empty_falls_back_to_title() -> None:
    about = extract_about("```python\nprint('only code')\n```", "Empty Doc", [])
    assert "Empty Doc" in about


def test_extract_about_skips_orphan_fence_and_python_snippets() -> None:
    markdown = """## Load the Magnetic Block

magnetic_block = protocol.load_module(
    module_name="magneticBlockV1", location="D1"
)
```
*New in version 2.15*
"""
    about = extract_about(markdown, "Python API: Magnetic Block", ["Load the Magnetic Block"])
    assert "```" not in about
    assert "protocol.load_module" not in about
    assert "Magnetic Block" in about


def test_apply_doc_templates_replaces_api_level_placeholders() -> None:
    source = 'requirements = {"apiLevel": "{{ apiLevel }}", "robotType": "Flex"}'
    rendered = apply_doc_templates(source, api_level="2.28", robot_stack_version="9.0.0")
    assert "{{ apiLevel }}" not in rendered
    assert '"apiLevel": "2.28"' in rendered


def test_generated_struct_abouts_reflect_current_docs_without_clutter() -> None:
    struct = STRUCT_PATH.read_text(encoding="utf-8")
    abouts = re.findall(r"<about>\n(.*?)\n</about>", struct, re.DOTALL)
    paths = re.findall(r"^### \d+\. (.+)$", struct, re.MULTILINE)
    by_path = dict(zip(paths, abouts, strict=True))

    assert "modules/thermocycler.md" in by_path
    assert "modules/flex-stacker.md" in by_path
    assert "versioning.md" in by_path
    assert "About source: claude (claude-sonnet-5)" in struct

    for about in abouts:
        assert "!!!" not in about
        assert "```" not in about
        assert "===" not in about
        assert "{{ apiLevel }}" not in about
        assert len(about) > 40

    versioning_about = by_path["versioning.md"]
    assert "2.28" in versioning_about
    assert "9.0.0" in versioning_about
    # Stale curated catalog claimed latest software was 8.6.0 / API 2.25.
    assert "latest software (8.6.0)" not in versioning_about.lower()
    assert "2.15-2.25" not in versioning_about

    assert "thermocycler" in by_path["modules/thermocycler.md"].lower()
    assert "stacker" in by_path["modules/flex-stacker.md"].lower()


def test_versioning_markdown_has_current_api_level() -> None:
    text = VERSIONING_PATH.read_text(encoding="utf-8")
    assert "| 2.28 " in text
    assert "9.0.0" in text
    assert "{{ apiLevel }}" not in text
    assert "{{ robot_stack_version }}" not in text


def test_get_relevant_api_docs_sends_struct_abouts_to_helper(monkeypatch: Any) -> None:
    predictor = AnthropicPredict(Settings(anthropic_api_key="sk-test", knowledge_version="9.0.0-k1"))
    captured: dict[str, Any] = {}

    class _Content:
        text = "<relevant_files>\nmodules/thermocycler.md\n</relevant_files>"

    class _Response:
        content = [_Content()]

    def _fake_create(**kwargs: Any) -> _Response:
        captured["kwargs"] = kwargs
        return _Response()

    monkeypatch.setattr(predictor.client.messages, "create", _fake_create)

    result = predictor.get_relevant_api_docs("How do I run a thermocycler profile on Flex?")
    assert "modules/thermocycler.md" in result

    message = captured["kwargs"]["messages"][0]
    struct_payload = message["content"][0]["source"]["data"]
    assert "modules/thermocycler.md" in struct_payload
    assert "<about>" in struct_payload
    # Ensure helper sees current versioning facts, not stale curated text.
    versioning_about = re.search(
        r"### \d+\. versioning\.md\n\n<about>\n(.*?)\n</about>",
        struct_payload,
        re.DOTALL,
    )
    assert versioning_about is not None
    assert "2.28" in versioning_about.group(1)
