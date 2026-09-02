from collections import defaultdict
from math import isfinite
from statistics import fmean

from app.domain.models import (
    ClimateProfile,
    ComponentScore,
    Confidence,
    EnvelopeLimit,
    PlantImageAsset,
    PlantRecommendation,
    SoilCategoricalPreference,
    SoilCompatibility,
    SoilGeographicContext,
    SoilIndicatorPreference,
    SoilProfile,
    Status,
)
from app.version import METHOD_VERSION

GROUP_WEIGHTS = {"M": 0.30, "V": 0.20, "E": 0.35, "A": 0.15}
CONF_RANK = {Confidence.A: 4, Confidence.B: 3, Confidence.C: 2, Confidence.D: 1, Confidence.UNKNOWN: 0}


def _status_from_score(score: float) -> Status:
    if score >= 75:
        return Status.GREEN
    if score >= 40:
        return Status.ORANGE
    return Status.RED


def _score_value(value: float | None, limit: EnvelopeLimit, *, missing_text: str) -> ComponentScore:
    if value is None or not isfinite(value):
        return ComponentScore(
            variable=limit.variable,
            value=None,
            score=None,
            status=Status.UNKNOWN,
            weight=limit.weight,
            group=limit.group,
            confidence=limit.confidence,
            explanation=missing_text,
            source_ref=limit.source_ref,
        )

    lo_h, lo_o, hi_o, hi_h = limit.hard_low, limit.optimum_low, limit.optimum_high, limit.hard_high
    if lo_h is not None and value < lo_h:
        score = 0.0
        why = f"Valeur {value:g} sous la borne externe de l’enveloppe {lo_h:g}."
    elif hi_h is not None and value > hi_h:
        score = 0.0
        why = f"Valeur {value:g} au-dessus de la borne externe de l’enveloppe {hi_h:g}."
    elif lo_o is not None and value < lo_o:
        score = 50.0 if lo_h is None or lo_o == lo_h else 100.0 * (value - lo_h) / (lo_o - lo_h)
        why = f"Valeur {value:g} dans la marge basse de tolérance."
    elif hi_o is not None and value > hi_o:
        score = 50.0 if hi_h is None or hi_h == hi_o else 100.0 * (hi_h - value) / (hi_h - hi_o)
        why = f"Valeur {value:g} dans la marge haute de tolérance."
    else:
        score = 100.0
        if lo_o is None and hi_o is None and (lo_h is not None or hi_h is not None):
            why = (
                f"Valeur {value:g} dans la plage de compatibilité documentée "
                "(aucun optimum n’est inféré)."
            )
        else:
            why = f"Valeur {value:g} dans l’intervalle central documenté/estimé."

    score = max(0.0, min(100.0, score))
    return ComponentScore(
        variable=limit.variable,
        value=value,
        score=round(score, 1),
        status=_status_from_score(score),
        weight=limit.weight,
        group=limit.group,
        confidence=limit.confidence,
        explanation=why,
        source_ref=limit.source_ref,
    )


def score_limit(value: float | None, limit: EnvelopeLimit) -> ComponentScore:
    return _score_value(
        value,
        limit,
        missing_text="Donnée climatique indisponible : aucun jugement de compatibilité.",
    )


def score_soil_limit(value: float | None, limit: EnvelopeLimit) -> ComponentScore:
    return _score_value(
        value,
        limit,
        missing_text="Donnée édaphique locale indisponible : aucun jugement de compatibilité sol.",
    )


def score_soil_categorical(value: str | None, preference: SoilCategoricalPreference) -> ComponentScore:
    if value is None or not str(value).strip():
        return ComponentScore(
            variable=preference.variable,
            value=None,
            score=None,
            status=Status.UNKNOWN,
            weight=preference.weight,
            group="E",
            confidence=preference.confidence,
            explanation="Donnée édaphique catégorielle locale indisponible : aucun jugement de compatibilité sol.",
            source_ref=preference.source_ref,
        )
    normalized = str(value).strip().lower()
    optimum = {str(v).strip().lower() for v in preference.optimum_values}
    accepted = {str(v).strip().lower() for v in preference.accepted_values} | optimum
    if normalized in optimum:
        score = 100.0
        why = f"Classe {value} dans la plage optimale documentée."
    elif normalized in accepted:
        score = 65.0
        why = f"Classe {value} acceptable mais hors optimum documenté."
    else:
        score = 0.0
        why = f"Classe {value} hors des classes de sol documentées."
    return ComponentScore(
        variable=preference.variable,
        value=value,
        score=score,
        status=_status_from_score(score),
        weight=preference.weight,
        group="E",
        confidence=preference.confidence,
        explanation=why,
        source_ref=preference.source_ref,
    )


def _aggregate_confidence(components: list[ComponentScore]) -> Confidence:
    known = [c for c in components if c.score is not None and c.confidence != Confidence.UNKNOWN]
    if not known:
        return Confidence.UNKNOWN
    mean_rank = fmean(CONF_RANK[c.confidence] for c in known)
    if mean_rank >= 3.5:
        return Confidence.A
    if mean_rank >= 2.5:
        return Confidence.B
    if mean_rank >= 1.5:
        return Confidence.C
    return Confidence.D


def _aggregate_climate(components: list[ComponentScore]) -> float | None:
    grouped: dict[str, list[ComponentScore]] = defaultdict(list)
    for component in components:
        if component.score is not None:
            grouped[component.group].append(component)
    group_scores: dict[str, float] = {}
    for group, values in grouped.items():
        denom = sum(v.weight for v in values) or 1.0
        group_scores[group] = sum((v.score or 0.0) * v.weight for v in values) / denom
    available_group_weight = sum(GROUP_WEIGHTS.get(group, 0.0) for group in group_scores)
    if not available_group_weight:
        return None
    return sum(group_scores[group] * GROUP_WEIGHTS[group] for group in group_scores) / available_group_weight


def score_soil(
    soil: SoilProfile | None,
    limits: list[EnvelopeLimit],
    categorical_preferences: list[SoilCategoricalPreference] | None = None,
    *,
    min_known_weight: float = 0.50,
    min_known_components: int = 2,
) -> SoilCompatibility:
    categorical_preferences = categorical_preferences or []
    if not limits and not categorical_preferences:
        return SoilCompatibility(
            explanation=(
                "Aucune préférence édaphique sourcée n’est disponible pour ce taxon. "
                "ClimaFlora affiche le sol local et les contextes documentaires éventuels, "
                "mais conserve la compatibilité sol à UNKNOWN."
            )
        )
    if soil is None:
        return SoilCompatibility(explanation="Profil de sol local indisponible : compatibilité sol UNKNOWN.")

    numeric_properties: dict[str, float | None] = {}
    for key, value in soil.properties.items():
        numeric_properties[key] = float(value) if isinstance(value, (int, float)) else None
    components = [score_soil_limit(numeric_properties.get(limit.variable), limit) for limit in limits]
    components.extend(
        score_soil_categorical(
            str(soil.properties.get(pref.variable)) if soil.properties.get(pref.variable) is not None else None,
            pref,
        )
        for pref in categorical_preferences
    )
    total_weight = sum(max(0.0, c.weight) for c in components) or 1.0
    known_weight = sum(c.weight for c in components if c.score is not None)
    known_fraction = known_weight / total_weight
    known = [c for c in components if c.score is not None]
    overall = (
        sum((c.score or 0.0) * c.weight for c in known) / (sum(c.weight for c in known) or 1.0)
        if known
        else None
    )
    if overall is None or known_fraction < min_known_weight or len(known) < min_known_components:
        status = Status.UNKNOWN
        explanation = (
            f"Données édaphiques insuffisantes : {len(known)} critère(s) local(aux) exploitable(s), "
            "compatibilité sol conservée à UNKNOWN."
        )
    else:
        status = _status_from_score(overall)
        explanation = (
            f"Compatibilité sol calculée à partir de {len(known)} critères et "
            f"{known_fraction:.0%} du poids édaphique sourcé."
        )
    return SoilCompatibility(
        score=round(overall, 1) if overall is not None else None,
        status=status,
        confidence=_aggregate_confidence(components),
        known_weight_fraction=round(known_fraction, 3),
        components=components,
        explanation=explanation,
    )


def score_plant(
    *,
    taxon_id: str,
    scientific_name: str,
    common_name: str | None,
    functions: list[str],
    limits: list[EnvelopeLimit],
    climate: ClimateProfile,
    soil: SoilProfile | None = None,
    soil_limits: list[EnvelopeLimit] | None = None,
    soil_categorical_preferences: list[SoilCategoricalPreference] | None = None,
    soil_indicators: list[SoilIndicatorPreference] | None = None,
    soil_geographic_context: SoilGeographicContext | None = None,
    soil_inheritance: dict[str, str] | None = None,
    regulatory_veto: bool = False,
    regulatory_reason: str | None = None,
    evidence: list[dict] | None = None,
    links: dict[str, str] | None = None,
    image: PlantImageAsset | None = None,
    min_known_weight: float = 0.50,
) -> PlantRecommendation:
    components = [score_limit(climate.variables.get(limit.variable), limit) for limit in limits]
    total_weight = sum(max(0.0, c.weight) for c in components) or 1.0
    known_weight = sum(c.weight for c in components if c.score is not None)
    known_fraction = known_weight / total_weight

    fatal_red = any(
        component.status == Status.RED and limit.fatal
        for component, limit in zip(components, limits, strict=True)
    )
    overall = _aggregate_climate(components)

    if fatal_red:
        status = Status.RED
    elif known_fraction < min_known_weight or overall is None:
        status = Status.UNKNOWN
    else:
        status = _status_from_score(overall)

    confidence = _aggregate_confidence(components)
    if fatal_red:
        explanation = "Au moins une limite physiologique critique est dépassée."
    elif status == Status.UNKNOWN:
        explanation = "Données insuffisantes : ClimaFlora conserve l'état UNKNOWN au lieu d'inférer une compatibilité."
    else:
        explanation = (
            f"Compatibilité climatique calculée à partir de {known_fraction:.0%} "
            "du poids de critères disponibles."
        )
    if regulatory_veto:
        explanation += " Un veto réglementaire/biologique distinct empêche toutefois d'en faire une recommandation."

    soil_result = score_soil(
        soil,
        soil_limits or [],
        soil_categorical_preferences or [],
        min_known_weight=min_known_weight,
    )
    if soil_inheritance and (soil_result.components or soil_result.score is not None):
        soil_result.inherited_from_species = True
        soil_result.inherited_from_taxon_id = soil_inheritance.get("taxon_id")
        soil_result.inherited_from_scientific_name = soil_inheritance.get("scientific_name")
    if overall is None:
        combined = soil_result.score
    elif soil_result.score is None or soil_result.status == Status.UNKNOWN:
        combined = overall
    else:
        # Navigation blend only. Climate and soil remain visible as independent axes.
        combined = 0.75 * overall + 0.25 * soil_result.score

    # A combined navigation score must never hide missing or clearly unsuitable climate.
    if status == Status.RED:
        combined_status = Status.RED
    elif status == Status.UNKNOWN:
        combined_status = Status.UNKNOWN
    else:
        combined_status = _status_from_score(combined) if combined is not None else Status.UNKNOWN

    # Expert EIVE indicators and native-range geographic priors are context only.
    geographic_context = soil_geographic_context.model_copy(deep=True) if soil_geographic_context else None
    if geographic_context is not None:
        geographic_context.scoring_enabled = False

    return PlantRecommendation(
        taxon_id=taxon_id,
        scientific_name=scientific_name,
        common_name=common_name,
        overall_score=round(overall, 1) if overall is not None else None,
        overall_status=status,
        confidence=confidence,
        known_weight_fraction=round(known_fraction, 3),
        regulatory_veto=regulatory_veto,
        regulatory_reason=regulatory_reason,
        recommendation_eligible=not regulatory_veto,
        functions=functions,
        components=components,
        soil=soil_result,
        soil_indicators=soil_indicators or [],
        soil_geographic_context=geographic_context,
        combined_score=round(combined, 1) if combined is not None else None,
        combined_status=combined_status,
        links=links or {},
        image=image,
        explanation=explanation,
        evidence=evidence or [],
    )
