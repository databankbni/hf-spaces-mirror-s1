"""Generate the drift-prone reference docs from the code that owns them.

Two things in the documentation pack rot the moment code changes: the ~1,500-line
configuration surface (``backend/config.py``) and the live prompt text
(``backend/prompts/``). Rather than hand-maintain them, this script regenerates:

* ``docs/reference/configuration.md`` — every ``Settings`` field, grouped by the
  ``# ── group ──`` banners in ``config.py``, with env var, type, default, docs.
* ``docs/reference/prompts.md`` — every live prompt constant and ``build_*``
  builder under ``backend/prompts/``.

Determinism matters: the output must not depend on the host or the clock, because
``backend/tests/test_docs_freshness.py`` regenerates and diffs against the
committed files in CI. So: no timestamps, and host-specific ``default_factory``
values (e.g. ``data_dir`` → ``~/.rics_v2``) render as ``(per-host default)``.

Usage::

    python -m backend.scripts.gen_docs        # write the files
    python -m backend.scripts.gen_docs --check # exit 1 if they would change
"""

from __future__ import annotations

import importlib
import inspect
import re
import sys
from pathlib import Path

from pydantic import AliasChoices
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

from backend.config import REPO_ROOT, Settings

CONFIG_DOC_REL = "docs/reference/configuration.md"
PROMPTS_DOC_REL = "docs/reference/prompts.md"

_GENERATED_BANNER = (
    "<!-- GENERATED FILE — do not edit by hand. "
    "Run `python -m backend.scripts.gen_docs` after changing the source. -->"
)

# ── configuration.md ─────────────────────────────────────────────────────────

# A group banner in config.py, e.g. ``# ── LLM (OpenAI / Gemini) ──────``.
_GROUP_RE = re.compile(r"^\s*#\s*[─=-]{2,}\s*(.+?)\s*[─=-]{2,}\s*$")
# A top-level field declaration inside the Settings class (exactly 4-space indent).
_FIELD_RE = re.compile(r"^ {4}([a-z_][a-z0-9_]*)\s*:\s*[^=]+=")


def _config_groups() -> list[tuple[str, list[str]]]:
    """Ordered (group_label, [field_name, ...]) parsed from config.py source.

    Field order follows declaration order; grouping follows the ``# ── ── ──``
    banners. Fields declared before any banner land in an "Ungrouped" bucket.
    """
    source = Path(inspect.getfile(Settings)).read_text(encoding="utf-8")
    fields = Settings.model_fields
    groups: list[tuple[str, list[str]]] = []
    label = "Ungrouped"
    bucket: list[str] = []
    for line in source.splitlines():
        banner = _GROUP_RE.match(line)
        if banner:
            if bucket:
                groups.append((label, bucket))
            label = banner.group(1).strip()
            bucket = []
            continue
        m = _FIELD_RE.match(line)
        if m and m.group(1) in fields:
            bucket.append(m.group(1))
    if bucket:
        groups.append((label, bucket))
    return groups


def _env_names(name: str, field: FieldInfo) -> str:
    """Environment variable name(s) an operator sets for this field."""
    alias = field.validation_alias
    uppers: list[str] = []
    if isinstance(alias, AliasChoices):
        uppers = [c for c in alias.choices if isinstance(c, str) and c.isupper()]
    elif isinstance(alias, str) and alias.isupper():
        uppers = [alias]
    if not uppers:
        uppers = [name.upper()]
    return " / ".join(dict.fromkeys(uppers))


def _type_name(field: FieldInfo) -> str:
    ann = field.annotation
    name = getattr(ann, "__name__", None) or str(ann).replace("typing.", "")
    # Union types render as "bool | None"; escape the pipe so it does not break
    # the markdown table column.
    return name.replace("|", r"\|")


def _default_repr(field: FieldInfo) -> str:
    if field.default_factory is not None:
        return "`[]`" if field.default_factory is list else "(per-host default)"
    d = field.default
    if d is PydanticUndefined:
        return "(required)"
    if isinstance(d, str):
        return '`""`' if d == "" else f"`{d}`"
    return f"`{d}`"


def _one_line(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).replace("|", r"\|").strip()


def render_configuration_md() -> str:
    fields = Settings.model_fields
    lines = [
        "# Reference — Configuration",
        "",
        _GENERATED_BANNER,
        "",
        "> **Generated** from [backend/config.py](../../backend/config.py) by "
        "[backend/scripts/gen_docs.py](../../backend/scripts/gen_docs.py). "
        "Do not hand-edit. The narrative lives in "
        "[10 — Deployment & configuration](../10-deployment-and-configuration.md).",
        "",
        "Every setting is overridable via an environment variable (prefix-free, "
        "case-insensitive) or the repo-root `.env`. `config.py` defaults are the "
        "source of truth; `.env.example` is a curated sample and may differ. "
        "`(per-host default)` marks values computed at runtime (e.g. the data dir "
        "under the current user's home).",
        "",
    ]
    for label, names in _config_groups():
        lines.append(f"## {label}")
        lines.append("")
        lines.append("| Env var | Type | Default | Description |")
        lines.append("|---------|------|---------|-------------|")
        for name in names:
            f = fields[name]
            lines.append(
                f"| `{_env_names(name, f)}` | {_type_name(f)} | "
                f"{_default_repr(f)} | {_one_line(f.description)} |"
            )
        lines.append("")
    return "\n".join(lines).strip() + "\n"


# ── prompts.md ───────────────────────────────────────────────────────────────

# Fixed, ordered so output is stable. Each is a module under backend/prompts/.
_PROMPT_MODULES: tuple[str, ...] = (
    "discovery_prompt",
    "mapping_prompt",
    "past_report_mapping_prompt",
    "grounding_prompt",
    "repair_prompt",
    "vision_prompt",
    "notes_expander_prompt",
    "notes_guidance",
    "minimum_weave_prompt",
    "medium_expand_prompt",
    "maximum_compose_prompt",
    "prompt_few_shot_examples",
    "prompt_message_assembly",
)


def _prompt_entries(module_name: str) -> list[tuple[str, str]]:
    """(display_name, markdown_body) for public prompt constants + build_* funcs."""
    mod = importlib.import_module(f"backend.prompts.{module_name}")
    entries: list[tuple[str, str]] = []
    for name, obj in sorted(vars(mod).items()):
        if name.startswith("_"):
            continue
        if isinstance(obj, str) and len(obj.strip()) > 40:
            entries.append((name, f"```text\n{obj.strip()}\n```"))
        elif callable(obj) and name.startswith("build_"):
            try:
                src = inspect.getsource(obj).strip()
            except (OSError, TypeError):
                continue
            entries.append((f"{name}()", f"```python\n{src}\n```"))
    return entries


def render_prompts_md() -> str:
    lines = [
        "# Reference — Live AI prompts",
        "",
        _GENERATED_BANNER,
        "",
        "> **Generated** from [backend/prompts/](../../backend/prompts/) by "
        "[backend/scripts/gen_docs.py](../../backend/scripts/gen_docs.py). "
        "Do not hand-edit — change the prompt module and regenerate. The narrative "
        "(which stage calls what, the model matrix, the assembly layer) lives in "
        "[07 — Prompts & models](../07-prompts-and-models.md).",
        "",
        "Each section is one prompt module: its public prompt strings and its "
        "`build_*` assembler functions, verbatim from the source.",
        "",
    ]
    for module_name in _PROMPT_MODULES:
        entries = _prompt_entries(module_name)
        if not entries:
            continue
        lines.extend([f"## `{module_name}`", ""])
        for name, body in entries:
            lines.extend([f"### `{name}`", "", body, ""])
    return "\n".join(lines).strip() + "\n"


# ── driver ───────────────────────────────────────────────────────────────────


def render_all() -> dict[str, str]:
    """Map of repo-relative doc path → generated content (no disk writes)."""
    return {
        CONFIG_DOC_REL: render_configuration_md(),
        PROMPTS_DOC_REL: render_prompts_md(),
    }


def write_all() -> list[Path]:
    written: list[Path] = []
    for rel, content in render_all().items():
        target = REPO_ROOT / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        # Force LF so regeneration on Windows and Linux (CI) is byte-identical.
        target.write_text(content, encoding="utf-8", newline="\n")
        written.append(target)
    return written


def _check() -> int:
    stale: list[str] = []
    for rel, content in render_all().items():
        target = REPO_ROOT / rel
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        if current != content:
            stale.append(rel)
    if stale:
        print("Stale reference docs (run `python -m backend.scripts.gen_docs`):")
        for rel in stale:
            print(f"  - {rel}")
        return 1
    print("Reference docs are fresh.")
    return 0


if __name__ == "__main__":
    if "--check" in sys.argv[1:]:
        raise SystemExit(_check())
    for path in write_all():
        print(f"Wrote {path}")
