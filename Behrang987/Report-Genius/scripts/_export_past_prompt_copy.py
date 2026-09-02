"""Export live Past Reports prompts to docs/past_reports_prompt_live_copy.md."""
from __future__ import annotations

from pathlib import Path

from backend.prompts.past_report_mapping_prompt import (
    PAST_REPORT_MAPPING_SYSTEM,
    PAST_REPORT_MAPPING_USER_TEMPLATE,
)

OUT = Path(__file__).resolve().parents[1] / "docs" / "past_reports_prompt_live_copy.md"


def main() -> None:
    body = f"""# Past Reports prompt — live copy

Exact text currently used by the live Past Reports generation path
(`backend/prompts/past_report_mapping_prompt.py`).

Copy from the fenced blocks below.

---

## SYSTEM PROMPT

```text
{PAST_REPORT_MAPPING_SYSTEM.strip()}
```

---

## USER PROMPT

Placeholders:
- `{{section_id}}` — e.g. D2
- `{{section_label}}` — e.g. Roof coverings
- `{{rating_line}}` — optional rating hint (may be empty)
- `{{past_report_scaffolds}}` — rendered past-report blocks
- `{{observations_bulleted}}` — inspection notes as `* ...` lines

```text
{PAST_REPORT_MAPPING_USER_TEMPLATE.strip()}
```
"""
    OUT.write_text(body, encoding="utf-8")
    print(f"wrote {OUT} ({len(body)} chars)")


if __name__ == "__main__":
    main()
