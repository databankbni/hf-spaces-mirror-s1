"""Schema discovery prompts from instructions v2.

Structural section order is discovered deterministically from the operator report
template; the LLM enrichment call uses :data:`DISCOVERY_SYSTEM` and
:data:`DISCOVERY_USER_TEMPLATE` to extract keywords, rating systems, and
placeholder syntax. OpenAI JSON mode is used via ``llm.openai_client``.
"""

from __future__ import annotations

from backend.prompts.prompt_few_shot_examples import DISCOVERY_COT_PROTOCOL
from backend.prompts.prompt_message_assembly import append_cot_to_system

DISCOVERY_SYSTEM = """
You are a document structure analyst. You receive the extracted text and heading
structure of a professional report template. Your task is to return a precise
machine-readable JSON schema describing the template's structure.

You must extract exactly what is present in the document. You must never add,
invent, or assume structural elements that are not explicitly present.

Specifically:
- If the template has a rating or condition system, describe it precisely using
  the exact values and format from the document. If there is no rating system,
  set "detected": false and do not describe one.
- If sections have sub-sections, reflect that hierarchy. If the structure is flat,
  say so.
- Extract keywords for each section from its label and opening sentences only.
  Do not invent keywords from general domain knowledge.
- For placeholders: identify the exact syntax used (e.g. "[...]", "{...}", "___").
  If no placeholders exist, leave the list empty.

Return ONLY a valid JSON object. No preamble, no markdown fences, no explanation.
The JSON must match this schema exactly:

{
  "report_type": string or null,
  "section_hierarchy": "flat" | "two-level" | "three-level",
  "rating_system": {
    "detected": boolean,
    "type": "numeric" | "letter" | "text" | "boolean" | null,
    "values": [{"value": string, "meaning": string or null}],
    "format_template": string or null,
    "inline_example": string or null
  },
  "placeholder_syntax": {
    "detected_formats": [string],
    "primary_format": string or null
  },
  "sections": [
    {
      "id": string,
      "label": string,
      "order": integer,
      "parent_id": string or null,
      "has_rating_field": boolean,
      "rating_inline_format": string or null,
      "keywords": [string],
      "placeholder_hints": [string]
    }
  ],
  "additional_metadata": {}
}
"""

DISCOVERY_USER_TEMPLATE = """
DOCUMENT FILENAME: {filename}

EXTRACTED HEADING STRUCTURE:
{heading_outline}

EXTRACTED FULL TEXT (first 8000 characters):
{document_text_excerpt}

Analyse this template document and return the JSON schema. No preamble. No markdown fences.
"""


def build_discovery_messages(
    *,
    filename: str,
    heading_outline: str,
    document_text_excerpt: str,
) -> list[dict[str, str]]:
    """Build messages for schema discovery / enrichment (instructions v2)."""
    user_message = DISCOVERY_USER_TEMPLATE.format(
        filename=filename,
        heading_outline=heading_outline,
        document_text_excerpt=document_text_excerpt[:8000],
    )
    return [
        {
            "role": "system",
            "content": append_cot_to_system(
                DISCOVERY_SYSTEM.strip(), DISCOVERY_COT_PROTOCOL
            ),
        },
        {"role": "user", "content": user_message.strip()},
    ]


def build_enrichment_messages(
    section_rows: list[dict[str, str]],
    sample_text: str,
    *,
    filename: str = "report_template",
) -> list[dict[str, str]]:
    """Enrich a structurally pre-discovered schema (operator PDF bundle).

    Section ids and titles are already known; the LLM adds keywords, confirms
    ratings, and detects placeholders using the v2 discovery prompt.
    """
    heading_outline = "\n".join(f"{row['id']} {row['title']}" for row in section_rows)
    return build_discovery_messages(
        filename=filename,
        heading_outline=heading_outline,
        document_text_excerpt=sample_text,
    )
