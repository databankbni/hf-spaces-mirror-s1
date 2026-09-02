"""Tests for Claude-written API docs <about> enrichment."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from api.knowledge.abouts import enrich_abouts_with_claude, generate_about_with_claude


def test_generate_about_with_claude_uses_model_and_cleans_output(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    class _Content:
        text = '  "Thermocycler module setup and profile commands for Flex and OT-2."  '

    class _Response:
        content = [_Content()]

    class _Messages:
        def create(self, **kwargs: Any) -> _Response:
            captured["kwargs"] = kwargs
            return _Response()

    class _Client:
        messages = _Messages()

    about = generate_about_with_claude(
        client=_Client(),  # type: ignore[arg-type]
        model="claude-sonnet-5",
        relative_path="modules/thermocycler.md",
        title="Python API: Thermocycler",
        content="# Thermocycler\n\nRun PCR profiles.",
    )
    assert about.startswith("Thermocycler")
    assert '"' not in about
    assert captured["kwargs"]["model"] == "claude-sonnet-5"
    assert "temperature" not in captured["kwargs"]


def test_enrich_abouts_with_claude_replaces_and_falls_back(tmp_path: Path, monkeypatch: Any) -> None:
    content_root = tmp_path / "docs"
    content_root.mkdir()
    (content_root / "modules").mkdir()
    (content_root / "modules" / "thermocycler.md").write_text(
        "# Thermocycler\n\nRun PCR profiles on Flex.",
        encoding="utf-8",
    )
    (content_root / "versioning.md").write_text(
        "# Versioning\n\nAPI 2.28 in robot software 9.0.0.",
        encoding="utf-8",
    )

    items = [
        {
            "relative_path": "modules/thermocycler.md",
            "title": "Thermocycler",
            "about": "fallback thermocycler",
        },
        {
            "relative_path": "versioning.md",
            "title": "Versioning",
            "about": "fallback versioning with 2.28 and 9.0.0",
        },
    ]

    def _fake_generate(**kwargs: Any) -> str:
        path = kwargs["relative_path"]
        if path == "modules/thermocycler.md":
            return "Thermocycler docs cover lid temperature and PCR profile blocks."
        raise RuntimeError("boom")

    monkeypatch.setattr("api.knowledge.abouts.generate_about_with_claude", _fake_generate)
    monkeypatch.setattr("api.knowledge.abouts.Anthropic", lambda api_key: object())

    enriched = enrich_abouts_with_claude(
        content_root,
        items,
        api_key="sk-test",
        model="claude-sonnet-5",
        max_workers=2,
    )
    by_path = {item["relative_path"]: item["about"] for item in enriched}
    assert "PCR profile" in by_path["modules/thermocycler.md"]
    assert by_path["versioning.md"] == "fallback versioning with 2.28 and 9.0.0"


def test_enrich_abouts_requires_api_key() -> None:
    try:
        enrich_abouts_with_claude(Path("."), [], api_key="")
        raised = False
    except RuntimeError as exc:
        raised = True
        assert "ANTHROPIC_API_KEY" in str(exc)
    assert raised
