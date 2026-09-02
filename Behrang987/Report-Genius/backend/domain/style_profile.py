"""Per-tenant writing style profile from the reference corpus."""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

from backend.config import settings
from backend.llm import openai_client
from backend.rag.store import get_rag_store
from backend.rag.types import TIER_REFERENCE
from backend.storage import tenant_store

logger = logging.getLogger(__name__)

_lock = threading.RLock()


@dataclass
class StyleProfile:
    tone: str = "formal"
    formality_level: str = "professional"
    avg_sentence_complexity: str = "moderate"
    vocabulary_level: str = "technical"
    common_phrases: list[str] = field(
        default_factory=lambda: [
            "The main roof structure is",
            "The pitched roof covering appears to be",
            "We have assumed that no deleterious or hazardous materials",
            "Your legal adviser should",
            "SEE THE LIMITATIONS OF OUR INSPECTION ABOVE",
        ]
    )
    structural_patterns: list[str] = field(
        default_factory=lambda: [
            "Element/construction description, then condition, then advice",
            "Limitation banners and advisory legal wording where triggered",
            "First-person plural surveyor voice with measured hedging",
        ]
    )
    writing_style_summary: str = (
        "Formal UK RICS survey prose with measured technical vocabulary and professional hedging."
    )
    example_paragraphs: list[str] = field(default_factory=list)

    def to_payload(self) -> dict:
        return asdict(self)


DEFAULT_PROFILE = StyleProfile()


def _cache_path(tenant_id: str) -> Path:
    return tenant_store.tenant_root(tenant_id) / "style_profile.json"


def _sample_reference_text(tenant_id: str, max_chars: int = 4800) -> str:
    store = get_rag_store()
    parts: list[str] = []
    used = 0
    for text in store.sample_chunk_texts(tenant_id, TIER_REFERENCE, limit=60):
        if used + len(text) + 2 > max_chars:
            break
        parts.append(text)
        used += len(text) + 2
    return "\n\n".join(parts)


def _heuristic_profile(sample: str) -> StyleProfile:
    if not sample.strip():
        return DEFAULT_PROFILE
    lower = sample.lower()
    tone = "formal"
    if "recommend" in lower or "advise" in lower:
        tone = "semi-formal"
    vocab = "technical"
    if sample.count("£") + sample.count("mm") + sample.count("dpc") >= 3:
        vocab = "specialist"
    sentences = [
        s.strip() for s in sample.replace("\n", " ").split(".") if len(s.strip()) > 20
    ]
    avg_len = sum(len(s.split()) for s in sentences) / max(len(sentences), 1)
    complexity = "moderate"
    if avg_len > 22:
        complexity = "complex"
    elif avg_len < 14:
        complexity = "simple"
    examples = []
    for block in sample.split("\n\n"):
        words = block.split()
        if 40 <= len(words) <= 120:
            examples.append(block.strip())
        if len(examples) >= 2:
            break
    return StyleProfile(
        tone=tone,
        avg_sentence_complexity=complexity,
        vocabulary_level=vocab,
        writing_style_summary=(
            "Derived from uploaded past reports: measured UK surveyor voice with "
            f"{complexity} sentences and {vocab} vocabulary."
        ),
        example_paragraphs=examples,
    )


def _llm_profile(sample: str) -> StyleProfile | None:
    if not openai_client.is_available() or len(sample) < 200:
        return None
    prompt = f"""Analyse this UK RICS survey sample and return JSON with keys:
tone, formality_level, avg_sentence_complexity, vocabulary_level,
common_phrases (array), structural_patterns (array), writing_style_summary,
example_paragraphs (array of verbatim short extracts).

SAMPLE:
{sample[:4000]}"""
    from backend.prompts.prompt_few_shot_examples import STYLE_COT_PROTOCOL
    from backend.prompts.prompt_message_assembly import append_cot_to_system

    try:
        raw = openai_client.chat_json(
            [
                {
                    "role": "system",
                    "content": append_cot_to_system(
                        "You analyse UK RICS report writing style. Output JSON only.",
                        STYLE_COT_PROTOCOL,
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            model=settings.mapping_model,
            max_tokens=800,
        )
        return StyleProfile(
            tone=str(raw.get("tone") or "formal"),
            formality_level=str(raw.get("formality_level") or "professional"),
            avg_sentence_complexity=str(
                raw.get("avg_sentence_complexity") or "moderate"
            ),
            vocabulary_level=str(raw.get("vocabulary_level") or "technical"),
            common_phrases=list(
                raw.get("common_phrases") or DEFAULT_PROFILE.common_phrases
            ),
            structural_patterns=list(
                raw.get("structural_patterns") or DEFAULT_PROFILE.structural_patterns
            ),
            writing_style_summary=str(
                raw.get("writing_style_summary")
                or DEFAULT_PROFILE.writing_style_summary
            ),
            example_paragraphs=list(raw.get("example_paragraphs") or []),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM style profile failed (%s) — using heuristics", exc)
        return None


def get_style_profile(tenant_id: str, *, force_refresh: bool = False) -> StyleProfile:
    with _lock:
        path = _cache_path(tenant_id)
        if not force_refresh and path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return StyleProfile(**data)
            except Exception:  # noqa: BLE001
                pass

        sample = _sample_reference_text(tenant_id)
        profile = _llm_profile(sample) or _heuristic_profile(sample)
        path.write_text(json.dumps(profile.to_payload(), indent=2), encoding="utf-8")
        return profile


def invalidate_style_profile(tenant_id: str) -> None:
    path = _cache_path(tenant_id)
    if path.is_file():
        path.unlink(missing_ok=True)


# ── Same-subsection style exemplars + mapping-prompt injection ────────────────

_EXEMPLAR_MAX_CHARS = 1400
_EXEMPLAR_MIN_CHARS = 120


def get_style_exemplars(
    tenant_id: str,
    section_id: str,
    *,
    limit: int = 2,
) -> list[str]:
    """Verbatim same-subsection paragraphs from the user's own past reports.

    The user's own writing for this exact subsection is the strongest style
    signal available. Returned text is already PII-scrubbed at ingest.
    """
    from backend.domain.section_scope import storage_section_id

    sid = storage_section_id(section_id)
    if not sid or limit <= 0:
        return []
    store = get_rag_store()
    exemplars: list[str] = []
    for hit in store.fetch_section_chunks(
        tenant_id, tier=TIER_REFERENCE, section_id=sid
    ):
        text = (hit.text or "").strip()
        if len(text) < _EXEMPLAR_MIN_CHARS:
            continue
        if len(text) > _EXEMPLAR_MAX_CHARS:
            text = text[:_EXEMPLAR_MAX_CHARS].rsplit(".", 1)[0].strip() + "."
        if text not in exemplars:
            exemplars.append(text)
        if len(exemplars) >= limit:
            break
    return exemplars


_STYLE_BLOCK_TEMPLATE = """
<USER_STYLE_PROFILE>
Writing-voice profile mined from THIS user's own past reports. Match the VOICE,
never the facts.
- Tone: {tone}; formality: {formality}; sentence complexity: {complexity}; vocabulary: {vocab}
- Preferred phrases (use naturally where they fit): {phrases}
- Structural habits: {patterns}
- Summary: {summary}
</USER_STYLE_PROFILE>
"""

_SCAFFOLD_STYLE_CUES_TEMPLATE = """
<PRIMARY_SCAFFOLD_STYLE_CUES>
Voice cues extracted from PAST REPORT 1 (PRIMARY STYLE SCAFFOLD) for THIS section.
Match these habits; do not copy other-property facts from the scaffolds.
- Typical openings: {openings}
- Hedging / advisory markers present: {hedging}
- Condition-rating placement habit: {rating_placement}
- Limitation / banner habit: {limitation_habit}
- Person / voice: {person_voice}
</PRIMARY_SCAFFOLD_STYLE_CUES>
"""

# Searched for in an uploaded scaffold's own prose to locate its rating line, so
# the wording must match the report text rather than come from the schema.
_RATING_LINE_PHRASE = "condition rating"  # rics-literal-ok

_HEDGING_MARKERS = (
    "appears to",
    "appear to",
    "believed to",
    "assumed",
    "likely",
    "may ",
    "could ",
    "cannot confirm",
    "should be",
    "your legal adviser",
    "your solicitor",
    "we would recommend",
    "further enquiries",
)


def build_scaffold_style_cues(primary_scaffold: str) -> str:
    """Short voice cues from the best-matching past-report scaffold for this call.

    Complements the mined tenant profile with openings / hedging / rating placement
    taken from the actual PRIMARY STYLE SCAFFOLD in the user message.
    """
    text = (primary_scaffold or "").strip()
    if len(text) < 80:
        return ""

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    openings: list[str] = []
    for para in paragraphs[:6]:
        # Skip pure banner / heading lines for openings list, but keep them for habits.
        first_line = para.split("\n", 1)[0].strip()
        if first_line.startswith("**") and first_line.endswith("**"):
            continue
        if first_line.upper().startswith("SEE THE LIMITATIONS"):
            continue
        words = first_line.split()
        if len(words) < 4:
            continue
        clip = " ".join(words[:12])
        if len(first_line.split()) > 12:
            clip += "…"
        openings.append(f'"{clip}"')
        if len(openings) >= 4:
            break

    lower = text.lower()
    hedging = [m.strip() for m in _HEDGING_MARKERS if m in lower][:8]
    # Searching the firm's own scaffold prose to learn where they place the rating,
    # so the phrase must match their document text verbatim.
    if "condition rating" in lower:  # rics-literal-ok
        rating_idx = lower.find("condition rating")  # rics-literal-ok
        rating_placement = (
            "near the start of the section"
            if rating_idx < max(120, len(text) // 5)
            else "later in the section / after findings"
        )
    else:
        rating_placement = (
            "no Condition Rating line in this scaffold"  # rics-literal-ok
        )

    if "see the limitations of our inspection" in lower:
        limitation_habit = "uses SEE THE LIMITATIONS / inspection-limitation banners"
    elif "limitation" in lower or "could not be inspected" in lower:
        limitation_habit = "states inspection limitations in prose"
    else:
        limitation_habit = "no strong limitation-banner habit in this scaffold"

    we_count = len(re.findall(r"\bwe\b", lower))
    it_noted = lower.count("it is noted") + lower.count("it was noted")
    if we_count >= 3 and we_count > it_noted:
        person_voice = "first-person plural surveyor voice (we / your adviser)"
    elif it_noted >= 2:
        person_voice = "impersonal 'it is/was noted' habit in this scaffold"
    else:
        person_voice = "mixed / descriptive survey prose"

    return _SCAFFOLD_STYLE_CUES_TEMPLATE.format(
        openings="; ".join(openings) or "—",
        hedging="; ".join(f'"{h}"' for h in hedging) or "—",
        rating_placement=rating_placement,
        limitation_habit=limitation_habit,
        person_voice=person_voice,
    ).strip()


def build_style_prompt_block(tenant_id: str, section_id: str) -> str:
    """Abstract writing-voice profile for the mapping system prompt.

    Returns empty string when disabled or unavailable. Verbatim same-subsection
    past-report paragraphs are intentionally NOT injected here — they already
    appear once as INPUT 1 scaffolds in the user message. Duplicating them as
    ``<STYLE_EXEMPLARS>`` wasted context and biased the model toward copying
    the truncated exemplar instead of using the full multi-report scaffolds.
    ``section_id`` is retained for call-site compatibility.
    """
    _ = section_id
    if not settings.style_injection_enabled or not tenant_id:
        return ""
    try:
        profile = get_style_profile(tenant_id)
    except Exception as exc:  # noqa: BLE001 — style must never break mapping
        logger.warning("Style profile unavailable for %s (%s)", tenant_id, exc)
        profile = DEFAULT_PROFILE

    return _STYLE_BLOCK_TEMPLATE.format(
        tone=profile.tone,
        formality=profile.formality_level,
        complexity=profile.avg_sentence_complexity,
        vocab=profile.vocabulary_level,
        phrases="; ".join(f'"{p}"' for p in profile.common_phrases[:8]) or "—",
        patterns="; ".join(profile.structural_patterns[:4]) or "—",
        summary=profile.writing_style_summary,
    ).strip()
