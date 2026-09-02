"""Post-generation evaluation orchestrator (Approach 2 + optional Approach 3)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from backend.config import settings
from backend.evaluation.coverage import score_section_coverage
from backend.evaluation.faithfulness import score_section_faithfulness
from backend.evaluation.judge_llm import resolved_model
from backend.evaluation.manifest import write_evaluation_manifest
from backend.evaluation.models import (
    EvaluationResult,
    MissingFactRef,
    SectionEvalInput,
    SectionEvaluation,
    UnsupportedClaimRef,
)

if TYPE_CHECKING:
    from backend.models.report import ReportResult
    from backend.models.section import SectionNote

logger = logging.getLogger(__name__)

_UNASSIGNED = "UNASSIGNED"
_EMPTY_PROSE_MARKERS = frozenset(
    {
        "[NOT GENERATED]",
        "NOT GENERATED",
        "[EMPTY]",
    }
)


def _has_evaluable_prose(text: str | None) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    return stripped.upper() not in {m.upper() for m in _EMPTY_PROSE_MARKERS}


def _rollup_status(coverage_rate: float | None) -> str:
    if coverage_rate is None:
        return "SKIPPED"
    if coverage_rate >= settings.evaluation_coverage_pass_threshold:
        return "PASS"
    if coverage_rate >= settings.evaluation_coverage_warn_threshold:
        return "WARN"
    return "FAIL"


def build_section_eval_inputs(
    result: "ReportResult",
    *,
    by_id: dict[str, "SectionNote"] | None = None,
    baselines_by_section: dict[str, str] | None = None,
    observations_by_section: dict[str, list[str]] | None = None,
) -> list[SectionEvalInput]:
    """Build judge inputs from a generated report + optional note/baseline maps."""
    by_id = by_id or {}
    baselines_by_section = {
        k.upper(): v for k, v in (baselines_by_section or {}).items()
    }
    observations_by_section = {
        k.upper(): list(v) for k, v in (observations_by_section or {}).items()
    }

    inputs: list[SectionEvalInput] = []
    for section in result.sections:
        sid = (section.section_id or "").upper()
        if not sid or sid == _UNASSIGNED:
            continue

        observations = observations_by_section.get(sid)
        if observations is None or not observations:
            note = by_id.get(section.section_id) or by_id.get(sid)
            if note is not None:
                observations = [
                    o.strip()
                    for o in (note.raw_observations or [])
                    if o and str(o).strip()
                ]
            else:
                observations = list(observations or [])

        observations = [o for o in observations if o]
        # Only evaluate leaves that have BOTH surveyor notes and real generated
        # prose. Empty / [NOT GENERATED] shells had no notes → nothing to judge.
        if not observations or not _has_evaluable_prose(section.text):
            continue

        inputs.append(
            SectionEvalInput(
                section_id=section.section_id,
                title=section.title,
                observations=observations,
                generated_text=section.text or "",
                baseline_text=baselines_by_section.get(sid, ""),
            )
        )
    return inputs


def load_baselines_from_retrieval_manifest(
    tenant_id: str,
    report_id: str | None,
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Read baseline_text + observations from the retrieval manifest when present."""
    baselines: dict[str, str] = {}
    observations: dict[str, list[str]] = {}
    if not report_id:
        return baselines, observations
    try:
        from backend.storage import retrieval_manifest

        path = retrieval_manifest.retrieval_manifest_path(tenant_id, report_id)
        if not path.is_file():
            return baselines, observations
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        sections = data.get("sections") if isinstance(data, dict) else None
        if not isinstance(sections, dict):
            return baselines, observations
        for sid, rec in sections.items():
            if not isinstance(rec, dict):
                continue
            key = str(sid).upper()
            baselines[key] = str(rec.get("baseline_text") or "")
            obs = rec.get("observations") or []
            if isinstance(obs, list):
                observations[key] = [str(o).strip() for o in obs if str(o).strip()]
    except Exception:  # noqa: BLE001
        logger.warning(
            "Failed to load retrieval manifest for evaluation tenant=%s report=%s",
            tenant_id,
            report_id,
            exc_info=True,
        )
    return baselines, observations


async def _evaluate_one_section(
    inp: SectionEvalInput,
    *,
    coverage_enabled: bool,
    faithfulness_enabled: bool,
    semaphore: asyncio.Semaphore,
) -> SectionEvaluation:
    async with semaphore:
        if coverage_enabled:
            section_eval = await score_section_coverage(inp)
        else:
            section_eval = SectionEvaluation(
                section_id=inp.section_id,
                title=inp.title,
                observations=list(inp.observations),
                generated_text=inp.generated_text,
                baseline_text=inp.baseline_text,
            )

        if faithfulness_enabled:
            score, claims, err, faith_prompt = await score_section_faithfulness(inp)
            section_eval.faithfulness_score = score
            section_eval.unsupported_claims = claims
            if err and not section_eval.error:
                section_eval.error = err
            if faith_prompt:
                merged = dict(section_eval.prompt or {})
                merged["faithfulness"] = faith_prompt
                section_eval.prompt = merged
        return section_eval


def _aggregate(sections: list[SectionEvaluation]) -> EvaluationResult:
    missing_refs: list[MissingFactRef] = []
    unsupported_refs: list[UnsupportedClaimRef] = []
    faith_scores: list[float] = []
    covered_atoms = 0
    weighted = 0.0
    judged = 0

    for sec in sections:
        for j in sec.note_judgments:
            judged += 1
            if j.status == "covered":
                covered_atoms += 1
                weighted += 1.0
            elif j.status == "partial":
                weighted += 0.5
        for fact in sec.missing_facts:
            missing_refs.append(MissingFactRef(section_id=sec.section_id, fact=fact))
        for claim in sec.unsupported_claims:
            unsupported_refs.append(
                UnsupportedClaimRef(section_id=sec.section_id, claim=claim)
            )
        if sec.faithfulness_score is not None:
            faith_scores.append(sec.faithfulness_score)

    coverage_rate = (weighted / judged) if judged else None
    faithfulness_score = (
        sum(faith_scores) / len(faith_scores) if faith_scores else None
    )
    errored = sum(1 for sec in sections if sec.error)
    rollup_error = (
        f"{errored}_of_{len(sections)}_sections_errored" if errored else None
    )

    return EvaluationResult(
        enabled=True,
        status=_rollup_status(coverage_rate),  # type: ignore[arg-type]
        coverage_rate=coverage_rate,
        faithfulness_score=faithfulness_score,
        total_note_atoms=judged,
        covered_note_atoms=covered_atoms,
        missing_facts=missing_refs,
        unsupported_claims=unsupported_refs,
        sections=sections,
        coverage_enabled=settings.evaluation_llm_coverage,
        faithfulness_enabled=settings.evaluation_llm_faithfulness,
        model=resolved_model(),
        error=rollup_error,
    )


async def evaluate_report(
    result: "ReportResult",
    *,
    report_id: str | None = None,
    by_id: dict[str, "SectionNote"] | None = None,
    section_inputs: list[SectionEvalInput] | None = None,
) -> EvaluationResult | None:
    """Run advisory LLM evaluation after report assembly.

    Returns ``None`` when evaluation is disabled. Never raises — failures become
    a SKIPPED/error result so generation is not blocked.
    """
    if not settings.evaluation_enabled:
        return None

    try:
        baselines, manifest_obs = load_baselines_from_retrieval_manifest(
            result.tenant_id, report_id
        )
        inputs = section_inputs or build_section_eval_inputs(
            result,
            by_id=by_id,
            baselines_by_section=baselines,
            observations_by_section=manifest_obs or None,
        )

        coverage_on = bool(settings.evaluation_llm_coverage)
        faithfulness_on = bool(settings.evaluation_llm_faithfulness)

        if not coverage_on and not faithfulness_on:
            empty = EvaluationResult(
                enabled=True,
                status="SKIPPED",
                coverage_enabled=False,
                faithfulness_enabled=False,
                model=resolved_model(),
                error="coverage_and_faithfulness_disabled",
            )
            if report_id:
                write_evaluation_manifest(result.tenant_id, report_id, empty)
            return empty

        if not inputs:
            empty = EvaluationResult(
                enabled=True,
                status="SKIPPED",
                coverage_enabled=coverage_on,
                faithfulness_enabled=faithfulness_on,
                model=resolved_model(),
                error="no_sections_with_notes",
            )
            if report_id:
                write_evaluation_manifest(result.tenant_id, report_id, empty)
            return empty

        limit = max(1, int(settings.evaluation_concurrency))
        semaphore = asyncio.Semaphore(limit)
        section_evals = await asyncio.gather(
            *[
                _evaluate_one_section(
                    inp,
                    coverage_enabled=coverage_on,
                    faithfulness_enabled=faithfulness_on,
                    semaphore=semaphore,
                )
                for inp in inputs
            ]
        )
        aggregated = _aggregate(list(section_evals))
        if report_id:
            write_evaluation_manifest(result.tenant_id, report_id, aggregated)
        return aggregated
    except Exception as exc:  # noqa: BLE001 — advisory only
        logger.exception("evaluate_report failed report=%s", report_id)
        failed = EvaluationResult(
            enabled=True,
            status="SKIPPED",
            coverage_enabled=settings.evaluation_llm_coverage,
            faithfulness_enabled=settings.evaluation_llm_faithfulness,
            model=resolved_model(),
            error=str(exc),
        )
        if report_id:
            write_evaluation_manifest(result.tenant_id, report_id, failed)
        return failed
