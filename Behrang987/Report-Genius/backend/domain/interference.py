"""Generation modes: Assist (default) and Expert (preference flags).

Assist preserves the surveyor's writing: minimum-interference weave of the
notes onto the retrieved baseline plus a writing-quality pass (grammar, flow,
de-repetition) — no new facts, auditor fully strict.

Expert is Assist plus opt-in enrichment preferences. Each enabled flag unlocks
a matching instruction block in the mapping prompt AND relaxes the matching
auditor violation type. Property-identity facts stay hard-blocked in both
modes — enrichment is allowed, invention of observations never is.

Legacy API values remain accepted: ``minimum`` → Assist, ``medium`` → Assist
(medium removed), ``maximum`` → Expert. The internal composition plumbing keeps
the historical ``InterferenceLevel`` literals ("minimum"/"maximum") as the
transport for retrieval-depth decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Literal

InterferenceLevel = Literal["minimum", "medium", "maximum"]
GenerationMode = Literal["assist", "expert"]

_MODE_ALIASES: dict[str, GenerationMode] = {
    "assist": "assist",
    "expert": "expert",
    # Legacy interference values.
    "minimum": "assist",
    "medium": "assist",  # medium removed — aliases to Assist
    "maximum": "expert",
}

_MODE_TO_INTERFERENCE: dict[GenerationMode, InterferenceLevel] = {
    "assist": "minimum",
    "expert": "maximum",
}

_SURVEY_TO_MODE: dict[int, GenerationMode] = {
    1: "assist",
    2: "assist",
    3: "expert",
}


@dataclass(frozen=True)
class ExpertPreferences:
    """Expert-mode enrichment flags. All off == Assist behaviour."""

    explain_causes: bool = False
    implications: bool = False
    maintenance_advice: bool = False
    building_regs: bool = False
    health_safety: bool = False
    planning_legal: bool = False

    @classmethod
    def from_mapping(cls, data: object) -> ExpertPreferences:
        if not isinstance(data, dict):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: bool(v) for k, v in data.items() if k in known})

    def enabled_flags(self) -> tuple[str, ...]:
        return tuple(f.name for f in fields(self) if getattr(self, f.name))

    @property
    def any_enabled(self) -> bool:
        return bool(self.enabled_flags())


# Auditor violation types each preference is allowed to relax. Property-identity
# and observation-invention types are NEVER relaxable (see HARD_VIOLATION_TYPES).
_PREFERENCE_RELAXATIONS: dict[str, frozenset[str]] = {
    "explain_causes": frozenset({"unsupported_cause"}),
    "implications": frozenset({"unsupported_cause"}),
    "maintenance_advice": frozenset(
        {"unsupported_monitoring", "invented_specialist_action"}
    ),
    "building_regs": frozenset(),
    "health_safety": frozenset(),
    "planning_legal": frozenset(),
}

# Violation types that can never be relaxed by any preference: each one asserts
# a false property-specific fact or observation (identity, materials, sides,
# measurements, defects) or ships broken output.
HARD_VIOLATION_TYPES = frozenset(
    {
        "invented_defect",
        "invented_material",
        "invented_mechanism",
        "invented_structural_relationship",
        "ungrounded_location",
        "ungrounded_specific_detail",
        "stale_historical_data",
        "placeholder_leakage",
        "fabricated_measurement",
        "incorrect_condition_rating",
    }
)


def resolve_generation_mode(
    explicit: str | None,
    survey_level: int = 3,
) -> GenerationMode:
    """Resolve the generation mode from an explicit value or RICS survey tier."""
    if explicit:
        mode = _MODE_ALIASES.get(explicit.strip().lower())
        if mode:
            return mode
    tier = max(1, min(3, int(survey_level or 3)))
    return _SURVEY_TO_MODE.get(tier, "assist")


def interference_level_for_mode(mode: GenerationMode) -> InterferenceLevel:
    """Internal composition tier carried by the mode."""
    return _MODE_TO_INTERFERENCE.get(mode, "minimum")


def relaxed_violation_types(preferences: ExpertPreferences) -> frozenset[str]:
    """Auditor violation types the enabled Expert preferences may relax."""
    relaxed: set[str] = set()
    for flag in preferences.enabled_flags():
        relaxed |= _PREFERENCE_RELAXATIONS.get(flag, frozenset())
    return frozenset(relaxed - HARD_VIOLATION_TYPES)


@dataclass(frozen=True)
class GenerationPolicy:
    """Resolved generation behaviour threaded through the section pipeline."""

    mode: GenerationMode = "assist"
    preferences: ExpertPreferences = ExpertPreferences()

    @property
    def interference_level(self) -> InterferenceLevel:
        return interference_level_for_mode(self.mode)

    @property
    def relaxed_violation_types(self) -> frozenset[str]:
        if self.mode != "expert":
            return frozenset()
        return relaxed_violation_types(self.preferences)

    @classmethod
    def resolve(
        cls,
        explicit: str | None,
        survey_level: int = 3,
        *,
        expert_preferences: object | None = None,
    ) -> GenerationPolicy:
        mode = resolve_generation_mode(explicit, survey_level)
        prefs = ExpertPreferences.from_mapping(expert_preferences)
        return cls(mode=mode, preferences=prefs)


def resolve_interference_level(
    explicit: str | None,
    survey_level: int = 3,
) -> InterferenceLevel:
    """Legacy alias: resolve the internal composition tier for a mode value.

    Accepts both new (``assist``/``expert``) and legacy
    (``minimum``/``medium``/``maximum``) values; ``medium`` aliases to Assist.
    """
    return interference_level_for_mode(resolve_generation_mode(explicit, survey_level))


def uses_llm_composition(interference_level: InterferenceLevel) -> bool:
    """Medium and maximum always target the LLM compose/expand path when available."""
    return interference_level in ("medium", "maximum")
