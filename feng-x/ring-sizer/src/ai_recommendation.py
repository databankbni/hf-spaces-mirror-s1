"""AI-powered ring size explanation using OpenAI.

Size selection is handled by deterministic logic in ring_size.py.
This module only generates a human-friendly explanation for the recommendation.
"""

import os
import logging
from typing import Dict, Optional

from src.ring_size import RING_MODELS, DEFAULT_RING_MODEL

logger = logging.getLogger(__name__)

_MODEL_LABELS = {"gen": "Gen1/Gen2", "air": "Air"}


def _build_size_table_text(ring_model: str = DEFAULT_RING_MODEL) -> str:
    chart = RING_MODELS.get(ring_model, RING_MODELS[DEFAULT_RING_MODEL])
    return "\n".join(
        f"  Size {size}: inner diameter {diameter_mm:.1f} mm"
        for size, diameter_mm in sorted(chart.items())
    )


_SYSTEM_PROMPT_TEMPLATE = """You are a sizing explanation assistant for Femometer Smart Ring ({model_label}).

You are given measured finger widths and a pre-computed ring size recommendation.
Your ONLY job is to explain WHY the recommended size is a good fit, in 1-2 concise sentences.

Do NOT suggest a different size. The size decision has already been made by the system.

Guidelines:
- Mention which finger(s) would fit best at this size
- Include specific diameter when first referencing a size, e.g. "Size 8 (18.6mm)"
- Priority context: index finger fit is slightly preferred over middle, then ring
- Keep it concise and actionable

Ring Size Chart ({model_label}):
{size_table}

Respond in plain text (1-2 sentences). Do NOT use JSON or markdown.
"""


def ai_explain_recommendation(
    finger_widths: Dict[str, Optional[float]],
    recommended_size: int,
    range_min: int,
    range_max: int,
    ring_model: str = DEFAULT_RING_MODEL,
) -> Optional[str]:
    """Call OpenAI to explain an already-computed ring size recommendation.

    Args:
        finger_widths: Dict mapping finger name to diameter in cm (or None if failed).
            Example: {"index": 1.93, "middle": 1.84, "ring": 1.93}
        recommended_size: The deterministic best-match size from ring_size.py.
        range_min: Lower bound of recommended size range.
        range_max: Upper bound of recommended size range.
        ring_model: Which ring model chart to reference.

    Returns:
        A plain-text explanation string, or None if the API call fails.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY not set, skipping AI explanation")
        return None

    model_label = _MODEL_LABELS.get(ring_model, ring_model)
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        model_label=model_label,
        size_table=_build_size_table_text(ring_model),
    )

    # Build user message with measurements and pre-computed recommendation
    lines = ["Measured finger outer diameters:"]
    for finger, width in finger_widths.items():
        if width is not None:
            lines.append(f"  {finger.capitalize()}: {width:.2f} cm ({width * 10:.1f} mm)")
        else:
            lines.append(f"  {finger.capitalize()}: measurement failed")
    lines.append("")
    lines.append(f"Recommended size: {recommended_size} (range {range_min}\u2013{range_max})")
    lines.append("")
    lines.append("Explain why this size is a good fit.")
    user_msg = "\n".join(lines)

    try:
        import openai

        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-5.4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.3,
            max_completion_tokens=200,
        )

        content = response.choices[0].message.content.strip()
        if not content:
            logger.warning("AI returned empty explanation")
            return None

        return content

    except Exception as e:
        logger.error("AI explanation failed: %s", e)
        return None
