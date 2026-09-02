from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Status(StrEnum):
    GREEN = "GREEN"
    ORANGE = "ORANGE"
    RED = "RED"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Confidence(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    UNKNOWN = "UNKNOWN"


class Horizon(StrEnum):
    NOW = "NOW"
    Y2035 = "2035"
    Y2050 = "2050"
    Y2070 = "2070"
    Y2100 = "2100"


class Scenario(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ClimateUncertainty(BaseModel):
    n: int
    minimum: float | None = None
    p10: float | None = None
    p50: float | None = None
    p90: float | None = None
    maximum: float | None = None


class ClimateProfile(BaseModel):
    latitude: float
    longitude: float
    horizon: Horizon
    scenario: Scenario
    provider: str
    model: str | None = None
    period: str
    variables: dict[str, float | None]
    uncertainty: dict[str, ClimateUncertainty] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)


class SoilProfile(BaseModel):
    latitude: float
    longitude: float
    provider: str
    depth: str = "5-15cm"
    resolution_m: int | None = 250
    properties: dict[str, float | str | None] = Field(default_factory=dict)
    confidence: Confidence = Confidence.UNKNOWN
    manual_override: bool = False
    provenance: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class EnvelopeLimit(BaseModel):
    variable: str
    hard_low: float | None = None
    optimum_low: float | None = None
    optimum_high: float | None = None
    hard_high: float | None = None
    weight: float = 1.0
    group: str = "M"
    fatal: bool = False
    confidence: Confidence = Confidence.UNKNOWN
    source_ref: str | None = None


class SoilCategoricalPreference(BaseModel):
    variable: str
    optimum_values: list[str] = Field(default_factory=list)
    accepted_values: list[str] = Field(default_factory=list)
    weight: float = 1.0
    confidence: Confidence = Confidence.UNKNOWN
    source_ref: str | None = None


class SoilIndicatorPreference(BaseModel):
    """Expert ecological indicator kept on its native ordinal scale.

    EIVE M/N/R are deliberately exposed as ecological information and are not
    converted to laboratory pH, water content or nutrient concentrations.
    """

    indicator: str
    optimum: float
    niche_width: float | None = None
    source_systems: int | None = None
    scale_min: float = 0.0
    scale_max: float = 10.0
    region_scope: str = "EUROPE"
    weight: float = 1.0
    confidence: Confidence = Confidence.UNKNOWN
    source_ref: str | None = None
    method: str | None = None
    method_version: str | None = None


class SoilGeographicContext(BaseModel):
    """Native-range soil context; never a species preference by itself."""

    native_region_count: int
    covered_region_count: int
    variables: dict[str, dict[str, float | int | None]] = Field(default_factory=dict)
    confidence: str = "PRIOR"
    scoring_enabled: bool = False
    source_ref: str | None = None
    method: str | None = None
    method_version: str | None = None


class PlantImageAsset(BaseModel):
    """Illustrative media metadata. Images are never identification evidence."""

    asset_id: str | None = None
    thumbnail_url: str | None = None
    image_url: str | None = None
    source: str | None = None
    license: str | None = None
    author: str | None = None
    attribution_url: str | None = None


class ComponentScore(BaseModel):
    variable: str
    value: float | str | None
    score: float | None
    status: Status
    weight: float
    group: str
    confidence: Confidence
    explanation: str
    source_ref: str | None = None


class SoilCompatibility(BaseModel):
    score: float | None = None
    status: Status = Status.UNKNOWN
    confidence: Confidence = Confidence.UNKNOWN
    known_weight_fraction: float = 0.0
    components: list[ComponentScore] = Field(default_factory=list)
    explanation: str = "Aucune préférence édaphique sourcée disponible pour ce taxon."
    inherited_from_species: bool = False
    inherited_from_taxon_id: str | None = None
    inherited_from_scientific_name: str | None = None


class PlantRecommendation(BaseModel):
    taxon_id: str
    scientific_name: str
    common_name: str | None = None
    overall_score: float | None
    overall_status: Status
    confidence: Confidence
    known_weight_fraction: float
    regulatory_veto: bool = False
    regulatory_reason: str | None = None
    recommendation_eligible: bool = True
    functions: list[str] = Field(default_factory=list)
    components: list[ComponentScore] = Field(default_factory=list)
    soil: SoilCompatibility = Field(default_factory=SoilCompatibility)
    soil_indicators: list[SoilIndicatorPreference] = Field(default_factory=list)
    soil_geographic_context: SoilGeographicContext | None = None
    combined_score: float | None = None
    combined_status: Status = Status.UNKNOWN
    links: dict[str, str] = Field(default_factory=dict)
    image: PlantImageAsset | None = None
    explanation: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class PlantSummary(BaseModel):
    taxon_id: str
    scientific_name: str
    common_name: str | None = None
    functions: list[str] = Field(default_factory=list)
    regulatory_veto: bool = False
    links: dict[str, str] = Field(default_factory=dict)
    image: PlantImageAsset | None = None


class RecommendationResponse(BaseModel):
    climate: ClimateProfile
    soil: SoilProfile | None = None
    recommendations: list[PlantRecommendation]
    method_version: str
    evaluated_candidates: int = 0
    warnings: list[str] = Field(default_factory=list)


class TrajectoryPoint(BaseModel):
    horizon: Horizon
    climate: ClimateProfile
    result: PlantRecommendation


class TrajectoryResponse(BaseModel):
    taxon_id: str
    scientific_name: str
    scenario: Scenario
    soil: SoilProfile | None = None
    links: dict[str, str] = Field(default_factory=dict)
    image: PlantImageAsset | None = None
    points: list[TrajectoryPoint]
    method_version: str
