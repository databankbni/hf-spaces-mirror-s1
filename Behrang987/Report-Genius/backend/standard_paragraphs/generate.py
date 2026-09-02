"""Generate subsection prose from standard paragraphs + surveyor notes."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from backend.config import settings
from backend.llm import openai_client
from backend.models.schema import TemplateSchema
from backend.pipeline.composition_output import (
    accept_narrative_section_output,
    sanitize_section_prose,
)
from backend.rag.retriever import fetch_complete_section_baselines_per_source
from backend.rag.store import get_rag_store
from backend.rag.types import TIER_REFERENCE, TIER_STANDARD_PARAGRAPHS, SearchHit
from backend.standard_paragraphs.decompose import decompose_notes_to_issues
from backend.standard_paragraphs.prompts import (
    FindingCandidateGroup,
    build_standard_paragraph_messages,
)

logger = logging.getLogger(__name__)


@dataclass
class SpRetrieveResult:
    """Outcome of SP retrieval for one subsection."""

    guidance: str = ""
    hits: list[SearchHit] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    finding_groups: list[FindingCandidateGroup] = field(default_factory=list)


def _hit_key(hit: SearchHit) -> str:
    cid = (hit.chunk_id or "").strip()
    if cid:
        return f"id:{cid}"
    return f"text:{(hit.text or '').strip().lower()}"


def _hit_rank_score(hit: SearchHit) -> float:
    return float(
        hit.fusion_score
        or hit.rerank_score
        or getattr(hit, "similarity_score", 0.0)
        or hit.score
        or 0.0
    )


def _hit_match_score(hit: SearchHit) -> float:
    """Score used for 'strong match' gating (prefer dense cosine)."""
    sim = float(getattr(hit, "similarity_score", 0.0) or 0.0)
    if sim > 0.0:
        return sim
    return float(hit.score or hit.fusion_score or hit.rerank_score or 0.0)


def _merge_hits(hits: list[SearchHit], *, cap: int) -> list[SearchHit]:
    """Dedupe by chunk id / text; keep the stronger score; sort desc; cap."""
    best: dict[str, SearchHit] = {}
    for hit in hits:
        if not (hit.text or "").strip():
            continue
        key = _hit_key(hit)
        prev = best.get(key)
        if prev is None or _hit_rank_score(hit) > _hit_rank_score(prev):
            best[key] = hit
    merged = sorted(best.values(), key=_hit_rank_score, reverse=True)
    if cap > 0:
        return merged[:cap]
    return merged


def _strong_candidates(
    hits: list[SearchHit],
    *,
    min_score: float,
    cap: int,
) -> list[SearchHit]:
    """Keep hits at/above min cosine (or fallback score), ranked, capped."""
    ranked = sorted(
        [h for h in hits if (h.text or "").strip()],
        key=_hit_rank_score,
        reverse=True,
    )
    strong = [h for h in ranked if _hit_match_score(h) >= min_score]
    if cap > 0:
        return strong[:cap]
    return strong


def _retrieve_single_query(
    tenant_id: str,
    *,
    section_ids: list[str],
    query: str,
    top_k: int,
) -> list[SearchHit]:
    store = get_rag_store()
    for sid in section_ids:
        if not sid:
            continue
        hits = store.search_section_scoped_hybrid(
            tenant_id,
            query,
            tier=TIER_STANDARD_PARAGRAPHS,
            section_id=sid,
            top_k=top_k,
        )
        if hits:
            return hits
    return []


def _fetch_all_section_sps(
    tenant_id: str,
    *,
    section_ids: list[str],
) -> list[SearchHit]:
    """Return every SP chunk for the first matching section id (document order)."""
    store = get_rag_store()
    for sid in section_ids:
        if not sid:
            continue
        hits = store.fetch_section_chunks(
            tenant_id,
            tier=TIER_STANDARD_PARAGRAPHS,
            section_id=sid,
        )
        if hits:
            return hits
    return []


def _hit_to_candidate_dict(hit: SearchHit) -> dict:
    return {
        "text": (hit.text or "").strip(),
        "score": _hit_rank_score(hit),
        "match_score": _hit_match_score(hit),
        "similarity_score": float(getattr(hit, "similarity_score", 0.0) or 0.0),
        "bm25_score": float(getattr(hit, "bm25_score", 0.0) or 0.0),
        "fusion_score": float(hit.fusion_score or 0.0),
        "rerank_score": float(hit.rerank_score or 0.0),
        "chunk_id": hit.chunk_id or "",
    }


def retrieve_standard_paragraphs(
    tenant_id: str,
    *,
    section_ids: list[str],
    observations: list[str],
    section_title: str = "",
    section_id: str = "",
    top_k: int | None = None,
    force_decompose: bool = False,
    force_decompose_llm: bool = False,
    use_all_section_sps: bool = False,
) -> SpRetrieveResult:
    """Section-scoped hybrid retrieve for SP generation.

    Decompose path: per-finding retrieve → strong-match filter → finding groups
    for the generation prompt.

    ``use_all_section_sps``: ablation that loads every SP (flat prompt groups).

    Returns :class:`SpRetrieveResult` (guidance, flat hits, findings, groups).
    """
    ids = [sid for sid in section_ids if sid]
    if not ids:
        return SpRetrieveResult()

    use_decompose = bool(settings.standard_paragraphs_decompose_notes) or force_decompose
    min_score = float(settings.standard_paragraphs_min_match_score)
    per_issue_k = (
        int(top_k)
        if top_k is not None
        else int(settings.standard_paragraphs_per_issue_top_k)
    )

    findings: list[str] = []
    if use_decompose:
        findings = decompose_notes_to_issues(
            observations,
            section_id=section_id,
            section_title=section_title,
            force_llm=force_decompose_llm,
            allow_when_disabled=force_decompose,
        )
        if not findings:
            fallback = " ".join(o for o in observations if o.strip()) or section_title
            findings = [fallback] if fallback.strip() else []

    # ── All-catalogue ablation: per-finding retrieve with no score gate ───
    # and a large Top-K; flat hits still include every section SP for audit.
    if use_all_section_sps:
        all_hits = _fetch_all_section_sps(tenant_id, section_ids=ids)
        if not findings:
            if not all_hits:
                return SpRetrieveResult()
            texts = [h.text for h in all_hits if (h.text or "").strip()]
            return SpRetrieveResult(
                guidance="\n\n".join(texts),
                hits=all_hits,
                findings=[],
                finding_groups=[
                    FindingCandidateGroup(
                        finding="(all notes)",
                        candidates=[_hit_to_candidate_dict(h) for h in all_hits],
                    )
                ],
            )
        wide_k = max(per_issue_k, len(all_hits) or per_issue_k)
        groups = []
        collected: list[SearchHit] = []
        for finding in findings:
            raw = _retrieve_single_query(
                tenant_id,
                section_ids=ids,
                query=finding,
                top_k=wide_k,
            )
            # No min-score gate for ablation — keep ranked Top wide_k / per_issue.
            strong = _strong_candidates(raw, min_score=0.0, cap=per_issue_k)
            collected.extend(strong)
            groups.append(
                FindingCandidateGroup(
                    finding=finding,
                    candidates=[_hit_to_candidate_dict(h) for h in strong],
                )
            )
        logger.info(
            "SP retrieve ALL-ablation section=%s catalogue=%d findings=%d",
            section_id or ids[0],
            len(all_hits),
            len(findings),
        )
        return SpRetrieveResult(
            guidance="\n\n".join(
                h.text for h in all_hits if (h.text or "").strip()
            ),
            hits=all_hits or _merge_hits(collected, cap=len(collected) or 1),
            findings=findings,
            finding_groups=groups,
        )

    # ── Legacy single-query (decompose off) ───────────────────────────────
    if not use_decompose:
        k = top_k if top_k is not None else int(settings.standard_paragraphs_top_k)
        query = " ".join(o for o in observations if o.strip()) or section_title
        if not query.strip():
            return SpRetrieveResult()
        hits = _retrieve_single_query(
            tenant_id, section_ids=ids, query=query, top_k=k
        )
        if not hits:
            return SpRetrieveResult()
        texts = [h.text for h in hits if (h.text or "").strip()]
        return SpRetrieveResult(
            guidance="\n\n".join(texts),
            hits=hits,
            findings=[],
            finding_groups=[],
        )

    # ── Decompose + per-finding retrieve + strong-match groups ────────────
    if not findings:
        return SpRetrieveResult()

    groups = []
    collected: list[SearchHit] = []
    for finding in findings:
        query = (finding or "").strip()
        if not query:
            continue
        raw = _retrieve_single_query(
            tenant_id, section_ids=ids, query=query, top_k=per_issue_k
        )
        strong = _strong_candidates(raw, min_score=min_score, cap=per_issue_k)
        collected.extend(strong)
        groups.append(
            FindingCandidateGroup(
                finding=finding,
                candidates=[_hit_to_candidate_dict(h) for h in strong],
            )
        )

    # Flat hits for retrieval manifest (deduped).
    merged_cap = int(settings.standard_paragraphs_merged_top_k)
    merged = _merge_hits(collected, cap=merged_cap)
    # Allow generation even when every finding is "no strong match" — prose
    # can still be written from findings alone if we have at least findings.
    if not merged and not any(g.candidates for g in groups):
        # Still return groups so the prompt can show no-match for each finding.
        logger.info(
            "SP retrieve section=%s findings=%d strong_hits=0 (min_score=%.3f)",
            section_id or ids[0],
            len(findings),
            min_score,
        )
        return SpRetrieveResult(
            guidance="",
            hits=[],
            findings=findings,
            finding_groups=groups,
        )

    texts = [h.text for h in merged if (h.text or "").strip()]
    logger.info(
        "SP retrieve section=%s findings=%d strong_hits=%d "
        "(per_finding_k=%d min_score=%.3f)",
        section_id or ids[0],
        len(findings),
        len(merged),
        per_issue_k,
        min_score,
    )
    return SpRetrieveResult(
        guidance="\n\n".join(texts),
        hits=merged,
        findings=findings,
        finding_groups=groups,
    )


def fetch_sp_style_samples(
    tenant_id: str,
    candidate_ids: list[str],
    *,
    allowed_doc_keys: frozenset[str] | None = None,
    enabled: bool | None = None,
    max_samples: int | None = None,
) -> list[str]:
    """Fetch past uploaded REFERENCE subsection texts for SP style exemplars.

    Returns full per-source subsection baselines (no char truncation). Empty when
    the feature flag is off, REFERENCE has no data, or no candidate id matches.
    Never includes source filenames.
    """
    if enabled is None:
        enabled = bool(settings.standard_paragraphs_style_samples_enabled)
    if not enabled:
        return []
    limit = (
        int(max_samples)
        if max_samples is not None
        else int(settings.standard_paragraphs_style_samples_max)
    )
    if limit <= 0:
        return []

    ids: list[str] = []
    seen: set[str] = set()
    for raw in candidate_ids or []:
        sid = (raw or "").strip()
        if not sid:
            continue
        key = sid.upper()
        if key in seen:
            continue
        seen.add(key)
        ids.append(sid)

    samples: list[str] = []
    seen_text: set[str] = set()
    for sid in ids:
        if len(samples) >= limit:
            break
        try:
            blocks = fetch_complete_section_baselines_per_source(
                tenant_id,
                paragraph_section_id=sid,
                tier=TIER_REFERENCE,
                allowed_doc_keys=allowed_doc_keys,
                max_sources=limit,
            )
        except Exception as exc:  # noqa: BLE001 - style samples must not abort SP
            logger.warning(
                "SP style-sample fetch failed section=%s (%s)", sid, exc
            )
            continue
        for block in blocks:
            text = (getattr(block, "text", None) or "").strip()
            if not text:
                continue
            norm = text.casefold()
            if norm in seen_text:
                continue
            seen_text.add(norm)
            samples.append(text)
            if len(samples) >= limit:
                break
    return samples


def generate_from_standard_paragraphs(
    *,
    tenant_id: str,
    schema: TemplateSchema,
    section_id: str,
    section_title: str,
    observations: list[str],
    candidate_ids: list[str],
    rating_value: str | None = None,
    force_decompose: bool = False,
    force_decompose_llm: bool = False,
    use_all_section_sps: bool = False,
    allowed_doc_keys: frozenset[str] | None = None,
    style_samples_enabled: bool | None = None,
) -> tuple[
    str,
    list[SearchHit],
    list[dict[str, str]] | None,
    str,
    list[str],
    dict | None,
    int,
]:
    """Retrieve SP guidance and run the dedicated standard-paragraph prompt.

    Returns
    ``(generated_text, hits, prompt_messages, retrieved_baseline,
    retrieval_issues, llm_usage, style_sample_count)``.

    ``llm_usage`` is the OpenAI response ``usage`` dict (prompt/completion/total
    tokens) when the mapping call succeeded; otherwise ``None``.

    When style samples are enabled, past REFERENCE subsection texts for the
    same leaf are injected into the prompt as style/length exemplars only.
    """
    result = retrieve_standard_paragraphs(
        tenant_id,
        section_ids=candidate_ids,
        observations=observations,
        section_title=section_title,
        section_id=section_id,
        force_decompose=force_decompose,
        force_decompose_llm=force_decompose_llm,
        use_all_section_sps=use_all_section_sps,
    )
    findings = list(result.findings)
    hits = list(result.hits)
    guidance = result.guidance
    groups = list(result.finding_groups)

    # Need either catalogue hits or finding groups (findings-only write).
    if not hits and not groups:
        return "", [], None, "", findings, None, 0

    style_samples = fetch_sp_style_samples(
        tenant_id,
        list(candidate_ids or []) + ([section_id] if section_id else []),
        allowed_doc_keys=allowed_doc_keys,
        enabled=style_samples_enabled,
    )
    if style_samples:
        logger.info(
            "SP style samples section=%s count=%d",
            section_id,
            len(style_samples),
        )

    if groups:
        messages = build_standard_paragraph_messages(
            section_id=section_id,
            section_title=section_title,
            finding_groups=groups,
            rating_value=rating_value,
            schema=schema,
            style_samples=style_samples,
        )
        # Baseline audit text: concatenate strong candidates in finding order.
        parts: list[str] = []
        for g in groups:
            for c in g.candidates:
                t = str(c.get("text") or "").strip()
                if t:
                    parts.append(t)
        guidance = "\n\n".join(parts) if parts else guidance
    else:
        retrieved_for_prompt: list[dict] = [
            {
                "text": (h.text or "").strip(),
                "score": _hit_rank_score(h),
            }
            for h in hits
            if (h.text or "").strip()
        ]
        if not retrieved_for_prompt:
            return "", [], None, "", findings, None, 0
        messages = build_standard_paragraph_messages(
            section_id=section_id,
            section_title=section_title,
            standard_paragraphs=retrieved_for_prompt,
            observations=observations,
            rating_value=rating_value,
            schema=schema,
            style_samples=style_samples,
        )

    style_sample_count = len(style_samples)

    if not openai_client.is_available():
        logger.warning("OpenAI unavailable; returning standard-paragraph guidance as-is")
        fallback = guidance or "\n\n".join(findings)
        return fallback, hits, messages, guidance, findings, None, style_sample_count

    try:
        out, llm_usage = openai_client.chat_text_with_usage(
            messages,
            model=settings.mapping_model,
            max_tokens=settings.max_tokens_mapping,
            temperature=float(settings.standard_paragraphs_temperature),
            call_label="standard_paragraph_mapping",
            reasoning_effort=(
                settings.standard_paragraphs_reasoning_effort or "none"
            ),
        )
        if llm_usage:
            logger.info(
                "SP LLM usage section=%s prompt_tokens=%s completion_tokens=%s "
                "total_tokens=%s source=%s model=%s temperature=%s max_tokens=%s "
                "style_samples=%d",
                section_id,
                llm_usage.get("prompt_tokens"),
                llm_usage.get("completion_tokens"),
                llm_usage.get("total_tokens"),
                llm_usage.get("source"),
                settings.mapping_model,
                float(settings.standard_paragraphs_temperature),
                settings.max_tokens_mapping,
                style_sample_count,
            )
        text = sanitize_section_prose((out or "").strip())
        if accept_narrative_section_output(text, observations or findings):
            return (
                text,
                hits,
                messages,
                guidance,
                findings,
                llm_usage,
                style_sample_count,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Standard-paragraph LLM mapping failed (%s)", exc)

    fallback = guidance or "\n\n".join(findings)
    return fallback, hits, messages, guidance, findings, None, style_sample_count
