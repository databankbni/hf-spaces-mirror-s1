"""Vision analysis of selected section photos (max 2) for report generation."""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from pathlib import Path

from backend.config import settings
from backend.llm import openai_client
from backend.prompts.vision_prompt import build_vision_messages
from backend.storage import photo_store

logger = logging.getLogger(__name__)

_VISION_MAX_ATTEMPTS = 2


@dataclass
class VisionSectionResult:
    observations: list[str]
    limitations: list[str]
    ok: bool
    error: str = ""
    photos_analyzed: int = 0


def _data_url(path: Path, content_type: str) -> str:
    raw = path.read_bytes()
    b64 = base64.standard_b64encode(raw).decode("ascii")
    return f"data:{content_type};base64,{b64}"


def _dedupe_observations(lines: list[str], *, max_items: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = line.lower().strip()[:200]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(line.strip().rstrip(".").strip() + ".")
        if len(out) >= max_items:
            break
    return out


def analyze_section_photos(
    image_paths: list[tuple[Path, str]],
    *,
    section_label: str,
) -> VisionSectionResult:
    """Analyze up to two selected photos with engineer-grade vision prompts."""
    if not image_paths:
        return VisionSectionResult([], [], ok=True)

    if not settings.section_photo_vision_enabled:
        return VisionSectionResult(
            [],
            [],
            ok=False,
            error="Section photo vision is disabled.",
        )

    if not openai_client.is_available():
        return VisionSectionResult(
            [],
            [],
            ok=False,
            error="OpenAI API key not configured for vision analysis.",
        )

    images: list[dict] = []
    for path, ct in image_paths[: settings.max_section_photos_for_ai]:
        try:
            images.append(
                {
                    "type": "image_url",
                    "image_url": {"url": _data_url(path, ct), "detail": "high"},
                }
            )
        except OSError as exc:
            logger.warning("Could not read photo %s: %s", path, exc)

    if not images:
        return VisionSectionResult(
            [],
            [],
            ok=False,
            error="Selected photos could not be read from storage.",
        )

    messages = build_vision_messages(
        section_label=section_label,
        image_count=len(images),
        max_obs=min(10, settings.vision_max_observations),
    )
    user_content: list[dict] = [{"type": "text", "text": messages[-1]["content"]}]
    user_content.extend(images)
    messages[-1] = {"role": "user", "content": user_content}

    last_error = ""
    for attempt in range(_VISION_MAX_ATTEMPTS):
        try:
            data = openai_client.chat_vision_json(
                messages,
                model=settings.vision_model,
                max_tokens=settings.vision_max_tokens,
                call_label="vision",
            )
            raw_obs = data.get("observations")
            if raw_obs is None:
                return VisionSectionResult(
                    [],
                    [],
                    ok=False,
                    error="Vision response missing 'observations' key.",
                )
            if not isinstance(raw_obs, list):
                return VisionSectionResult(
                    [],
                    [],
                    ok=False,
                    error="Vision 'observations' is not a list.",
                )
            limitations = [
                str(x).strip()
                for x in (data.get("limitations") or [])
                if str(x).strip()
            ]
            clean = _dedupe_observations(
                [str(o).strip() for o in raw_obs if str(o).strip()],
                max_items=settings.vision_max_observations,
            )
            logger.info(
                "Vision OK for %s: %d observations from %d photo(s)",
                section_label,
                len(clean),
                len(images),
            )
            return VisionSectionResult(
                clean,
                limitations,
                ok=True,
                photos_analyzed=len(images),
            )
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            logger.warning(
                "Vision attempt %d/%d failed for %s: %s",
                attempt + 1,
                _VISION_MAX_ATTEMPTS,
                section_label,
                exc,
            )

    return VisionSectionResult(
        [],
        [],
        ok=False,
        error=last_error or "Vision analysis failed after retries.",
        photos_analyzed=0,
    )


def vision_observations_for_section(
    tenant_id: str,
    draft_id: str | None,
    section_id: str,
    section_label: str,
) -> tuple[list[str], str | None]:
    """Load selected photos for a draft section and return (observations, user_note)."""
    if not draft_id:
        return [], None

    all_photos = photo_store.list_section_photos(tenant_id, draft_id, section_id)
    if not all_photos:
        return [], None

    selected = [p for p in all_photos if p.selected_for_ai]
    if not selected:
        max_ai = settings.max_section_photos_for_ai
        return [], (
            f"{len(all_photos)} photo(s) uploaded but none selected for AI analysis. "
            f"Select up to {max_ai} photo(s) before generating."
        )

    paths = photo_store.selected_photo_paths(tenant_id, draft_id, section_id)
    result = analyze_section_photos(paths, section_label=section_label)

    if result.ok:
        note: str | None = None
        if result.limitations:
            note = "Photo limitations: " + " ".join(result.limitations[:2])
        if not result.observations and not note:
            note = "Selected photos did not yield usable observations; section is text-led."
        return list(result.observations), note

    return [], (
        f"Photo analysis unavailable ({result.error}). "
        "Section generated from notes and past-report text only."
    )
