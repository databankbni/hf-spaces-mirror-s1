"""共用問答管線：口語問題 → 改寫 → hybrid 檢索 → 拒答門檻 → 圖譜擴展 →
含引用回答 → 逐句 groundedness 查核。

CLI（`cli.py`）與 Gradio 介面（`app.py`，Phase 6）共用本模組，避免兩處
各自實作、行為分岔。`retriever` 由呼叫端建構後傳入（不在本模組內建構），
因為 embedding/reranker 模型載入成本高，介面端需要在啟動時建一次、
重複使用，不能每次問答都重建。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter

from .confidence import (
    AdaptiveMode,
    GateDecision,
    GatePolicy,
    GateResult,
    build_gate_signals,
    extract_required_articles,
    grade_retrieval,
)
from .config import get_settings
from .evidence import build_evidence_plan
from .generate import LawsLookup, answer as gen_answer
from .graph_expand import RelatedArticle
from .grounding import (
    GroundingResult,
    JudgeUnavailable,
    REFUSAL_FINAL_TEXT,
    apply_grounding,
    should_refuse_before_generation,
)
from .observability import JsonlTraceWriter, QueryTrace, TokenUsage, utc_now
from .retriever import HybridRetriever, RetrievedChunk
from .rewrite import refine_query, rewrite_query
from .routing import QueryRoute, RouteResult, route_query

OLLAMA_NUM_CTX = 8192  # 鐵律：顯式傳遞，預設 4096 會靜默截斷 prompt 開頭


@dataclass
class PipelineResult:
    question: str
    rewritten_query: str
    retrieved: list[RetrievedChunk] = field(default_factory=list)
    related: list[RelatedArticle] = field(default_factory=list)
    refused: bool = False
    overview: bool = False  # 彙總型問題走結構化路由（不經 RAG，無引用可列）
    answer_text: str = ""
    grounding: GroundingResult | None = None  # 未跑 grounding 或拒答時為 None
    grounding_error: str | None = None
    route: RouteResult | None = None
    confidence_gate: GateResult | None = None
    shadow_adaptive: dict | None = None
    trace: dict | None = None

    @property
    def grounding_removed_count(self) -> int:
        return max(self.grounding.removed_count, 0) if self.grounding else 0


def make_chat_model(provider: str, settings, ollama_model: str | None = None):
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=ollama_model or settings.ollama_model,
            num_ctx=OLLAMA_NUM_CTX,
            temperature=0.2,
        )
    from langchain.chat_models import init_chat_model

    if provider == "gemini":
        return init_chat_model(
            f"google_genai:{settings.gemini_model}",
            api_key=settings.google_api_key, temperature=0.2,
        )
    if provider == "openai":
        return init_chat_model(
            f"openai:{settings.openai_model}",
            api_key=settings.openai_api_key, temperature=0.2,
        )
    raise ValueError(f"未知 provider：{provider}")


def make_rewrite_model(provider: str, settings, ollama_model: str | None = None):
    if provider == "ollama":
        return make_chat_model("ollama", settings, ollama_model)
    if provider == "gemini":
        from langchain.chat_models import init_chat_model

        return init_chat_model(
            f"google_genai:{settings.gemini_lite_model}",
            api_key=settings.google_api_key, temperature=0,
        )
    return make_chat_model("openai", settings)


@dataclass(frozen=True)
class PipelineBudget:
    max_refinements: int = 1
    max_total_tokens: int = 16_000
    max_generation_calls: int = 1

    def __post_init__(self) -> None:
        if self.max_refinements not in (0, 1):
            raise ValueError("max_refinements must be 0 or 1")
        if self.max_total_tokens <= 0:
            raise ValueError("max_total_tokens must be positive")
        if self.max_generation_calls != 1:
            raise ValueError("the bounded pipeline permits exactly one generation call")


@dataclass(frozen=True)
class ShadowAdaptiveConfig:
    """Observe Adaptive decisions while preserving the baseline control path."""

    enabled: bool = False
    execute_refinement: bool = False

    def __post_init__(self) -> None:
        if self.execute_refinement and not self.enabled:
            raise ValueError("shadow refinement requires shadow mode")


def _model_name(provider: str, settings, ollama_model: str | None) -> str:
    if provider == "ollama":
        return ollama_model or settings.ollama_model
    if provider == "gemini":
        return settings.gemini_model
    return settings.openai_model


def _retrieval_records(retrieved: list[RetrievedChunk]) -> list[dict]:
    return [
        {
            "chunk_id": chunk.chunk_id,
            "article_id": chunk.parent_id,
            "law_name": chunk.law_name,
            "pcode": chunk.pcode,
            "article_no": chunk.article_no,
            "sources": list(chunk.sources),
            "bm25_score": chunk.bm25_score,
            "bm25_rank": chunk.bm25_rank,
            "dense_score": chunk.dense_score,
            "dense_rank": chunk.dense_rank,
            "rrf_score": chunk.rrf_score,
            "rerank_score": chunk.rerank_score,
        }
        for chunk in retrieved
    ]


def _graph_records(related: list[RelatedArticle]) -> list[dict]:
    return [
        {
            "article_id": f"{item.pcode}-{item.article_no}",
            "pcode": item.pcode,
            "article_no": item.article_no,
            "via_article_id": item.via_parent_id,
        }
        for item in related
    ]


def _write_trace(
    trace: QueryTrace,
    writer: JsonlTraceWriter | bool | None,
) -> None:
    if writer is False:
        return
    selected = writer if isinstance(writer, JsonlTraceWriter) else JsonlTraceWriter()
    try:
        selected.write(trace)
    except OSError:
        # Observability must not turn an otherwise valid answer into an outage.
        pass


def run_pipeline(
    question: str,
    retriever: HybridRetriever,
    lookup: LawsLookup,
    provider: str = "ollama",
    ollama_model: str | None = None,
    use_grounding: bool = True,
    graph=None,  # networkx.DiGraph | None（None 或無邊時視同關閉）
    on_progress=None,  # Callable[[str], None] | None——呼叫端要即時顯示步驟時傳入
    adaptive_mode: AdaptiveMode | str = AdaptiveMode.CURRENT_BASELINE,
    gate_policy: GatePolicy | None = None,
    budget: PipelineBudget | None = None,
    trace_writer: JsonlTraceWriter | bool | None = None,
    request_id: str | None = None,
    run_id: str | None = None,
    shadow_adaptive: ShadowAdaptiveConfig | bool | None = None,
) -> PipelineResult:
    """Run one bounded RAG request.

    ``current_baseline`` is the compatibility default.  New confidence grading
    therefore cannot silently change the HF Space/public API before locked
    evaluation demonstrates an improvement.
    """
    mode = AdaptiveMode(adaptive_mode)
    settings = get_settings()
    if shadow_adaptive is None:
        shadow_config = ShadowAdaptiveConfig(
            enabled=settings.shadow_adaptive_enabled,
            execute_refinement=settings.shadow_adaptive_refinement,
        )
    elif isinstance(shadow_adaptive, bool):
        shadow_config = ShadowAdaptiveConfig(enabled=shadow_adaptive)
    else:
        shadow_config = shadow_adaptive
    if shadow_config.enabled and mode != AdaptiveMode.CURRENT_BASELINE:
        raise ValueError("shadow mode serves current_baseline only")
    trace = QueryTrace.start(question, request_id=request_id, run_id=run_id)
    started = perf_counter()
    try:
        return _run_pipeline_impl(
            question=question,
            retriever=retriever,
            lookup=lookup,
            provider=provider,
            ollama_model=ollama_model,
            use_grounding=use_grounding,
            graph=graph,
            on_progress=on_progress,
            adaptive_mode=mode,
            gate_policy=gate_policy or GatePolicy(),
            budget=budget or PipelineBudget(),
            trace_writer=trace_writer,
            trace=trace,
            started=started,
            shadow_adaptive=shadow_config,
        )
    except Exception as exc:
        trace.final_status = "error"
        trace.completed_at = utc_now()
        trace.latency_ms["total"] = round((perf_counter() - started) * 1000, 3)
        trace.generation["error"] = {
            "type": type(exc).__name__,
            "message": str(exc)[:500],
        }
        _write_trace(trace, trace_writer)
        raise


def _run_pipeline_impl(
    *,
    question: str,
    retriever: HybridRetriever,
    lookup: LawsLookup,
    provider: str,
    ollama_model: str | None,
    use_grounding: bool,
    graph,
    on_progress,
    adaptive_mode: AdaptiveMode,
    gate_policy: GatePolicy,
    budget: PipelineBudget,
    trace_writer: JsonlTraceWriter | bool | None,
    trace: QueryTrace,
    started: float,
    shadow_adaptive: ShadowAdaptiveConfig,
) -> PipelineResult:
    def progress(msg: str) -> None:
        if on_progress is not None:
            on_progress(msg)

    from .structured import (
        META_RESPONSE,
        answer_global_question,
        build_law_overview,
    )

    settings = get_settings()
    trace.versions["index"] = getattr(
        retriever, "index_version", trace.versions["index"]
    )
    trace.generation = {
        "provider": provider,
        "model": _model_name(provider, settings, ollama_model),
        "max_generation_calls": budget.max_generation_calls,
        "max_total_tokens": budget.max_total_tokens,
        "mode": adaptive_mode.value,
    }

    def observe(stage: str, response) -> None:
        trace.token_usage.record(stage, response)

    def record_retry() -> None:
        trace.retry_count += 1

    def finish(result: PipelineResult, status: str) -> PipelineResult:
        trace.final_status = status
        trace.completed_at = utc_now()
        trace.latency_ms["total"] = round((perf_counter() - started) * 1000, 3)
        result.trace = trace.to_dict()
        _write_trace(trace, trace_writer)
        return result

    route_started = perf_counter()
    route = route_query(question)
    trace.latency_ms["route"] = round((perf_counter() - route_started) * 1000, 3)
    trace.route = route.to_dict()

    if route.route == QueryRoute.NO_RETRIEVAL:
        progress("[router] 偵測到系統範圍 meta 問題，改走固定回答（不經檢索）")
        return finish(PipelineResult(
            question=question, rewritten_query=question,
            overview=True, answer_text=META_RESPONSE, route=route,
        ), "answered")

    if route.route == QueryRoute.STRUCTURED:
        progress("[router] 偵測到整部法規彙總問題，改走結構化目錄（不經檢索）")
        return finish(PipelineResult(
            question=question, rewritten_query=question,
            overview=True,
            answer_text=build_law_overview(route.matched_pcodes[0]),
            route=route,
        ), "answered")

    if (
        route.route == QueryRoute.GLOBAL_OR_MULTI_HOP
        and route.handler == "chapter_summary"
    ):
        progress("[router] 偵測到全局/跨章節問題，改走章節摘要（RAPTOR-lite，不經檢索）")
        global_model = make_chat_model(provider, settings, ollama_model)
        generation_started = perf_counter()
        text, removed = answer_global_question(
            question, list(route.matched_pcodes), global_model, on_response=observe
        )
        trace.latency_ms["generation"] = round(
            (perf_counter() - generation_started) * 1000, 3
        )
        trace.grounding = {
            "kind": "chapter_citation_validation",
            "removed_paragraphs": removed,
        }
        if removed:
            progress(f"[router] 章節引用驗證移除 {removed} 段（引用了未提供的章節）")
        return finish(PipelineResult(
            question=question, rewritten_query=question,
            overview=True, answer_text=text, route=route,
        ), "answered")

    progress("[1/5] Query 改寫…")
    rewrite_model = make_rewrite_model(provider, settings, ollama_model)
    rewrite_started = perf_counter()
    query = rewrite_query(question, rewrite_model, on_response=observe)
    trace.latency_ms["rewrite"] = round(
        (perf_counter() - rewrite_started) * 1000, 3
    )
    trace.rewritten_queries.append(query)

    progress("[2/5] hybrid 檢索…")
    retrieval_started = perf_counter()
    retrieved = retriever.retrieve(query)
    trace.latency_ms["retrieval_initial"] = round(
        (perf_counter() - retrieval_started) * 1000, 3
    )
    diagnostics = getattr(retriever, "last_diagnostics", None)
    diagnostic_attempts = [diagnostics.to_dict()] if diagnostics else []

    related: list[RelatedArticle] = []
    if graph is not None and retrieved:
        progress("[3/5] 法條引用圖譜一階擴展…")
        from .graph_expand import expand_related_articles

        related = expand_related_articles(retrieved, graph, lookup)
    else:
        progress("[3/5] 圖譜擴展已停用")

    result = PipelineResult(question=question, rewritten_query=query,
                            retrieved=retrieved, related=related, route=route)

    # Baseline remains bit-for-bit compatible with the old single-threshold
    # behavior. Adaptive variants use the multi-signal decision below.
    gate_route = route
    if (
        adaptive_mode != AdaptiveMode.FULL_ADAPTIVE_ROUTE
        and (
            route.route == QueryRoute.CORRECTIVE_CANDIDATE
            or (
                route.route == QueryRoute.GLOBAL_OR_MULTI_HOP
                and route.handler == "citation_graph"
            )
        )
    ):
        gate_route = RouteResult(
            QueryRoute.SINGLE_HOP,
            "adaptive-route ambiguity signal disabled for this evaluation arm",
            route.confidence,
        )
    evidence_plan = build_evidence_plan(
        question,
        gate_route,
        retrieved,
        related,
        required_articles=extract_required_articles(question),
    )
    # Rebuild once with the plan retained for trace readability.
    signals = build_gate_signals(
        question,
        retrieved,
        diagnostics,
        related,
        gate_route,
        evidence_plan=evidence_plan,
    )
    trace.evidence_requirements = evidence_plan.to_dict()
    gate: GateResult | None = None
    if adaptive_mode == AdaptiveMode.CURRENT_BASELINE:
        if shadow_adaptive.enabled:
            shadow_started = perf_counter()
            shadow_plan = build_evidence_plan(
                question,
                route,
                retrieved,
                related,
                required_articles=extract_required_articles(question),
            )
            shadow_signals = build_gate_signals(
                question,
                retrieved,
                diagnostics,
                related,
                route,
                evidence_plan=shadow_plan,
            )
            shadow_gate = grade_retrieval(
                shadow_signals, refinement_count=0, policy=gate_policy
            )
            shadow_record = {
                "served_mode": AdaptiveMode.CURRENT_BASELINE.value,
                "control_path_affected": False,
                "execution": "decision_only",
                "initial_gate": shadow_gate.to_dict(),
                "initial_evidence_requirements": shadow_plan.to_dict(),
                "refinement_executed": False,
            }
            if (
                shadow_adaptive.execute_refinement
                and shadow_gate.decision == GateDecision.REFINE_ONCE
                and budget.max_refinements >= 1
            ):
                shadow_usage = TokenUsage()

                def observe_shadow(stage: str, response) -> None:
                    shadow_usage.record(stage, response)

                shadow_refine_started = perf_counter()
                shadow_query = refine_query(
                    question,
                    query,
                    retrieved,
                    rewrite_model,
                    on_response=observe_shadow,
                )
                shadow_refine_latency = round(
                    (perf_counter() - shadow_refine_started) * 1000, 3
                )
                shadow_retrieval_started = perf_counter()
                shadow_retrieved = retriever.retrieve_multi(
                    [question, query, shadow_query], rerank_query=question
                )
                shadow_retrieval_latency = round(
                    (perf_counter() - shadow_retrieval_started) * 1000, 3
                )
                shadow_diagnostics = getattr(retriever, "last_diagnostics", None)
                shadow_related: list[RelatedArticle] = []
                if graph is not None and shadow_retrieved:
                    from .graph_expand import expand_related_articles

                    shadow_related = expand_related_articles(
                        shadow_retrieved, graph, lookup
                    )
                shadow_plan = build_evidence_plan(
                    question,
                    route,
                    shadow_retrieved,
                    shadow_related,
                    required_articles=extract_required_articles(question),
                )
                shadow_signals = build_gate_signals(
                    question,
                    shadow_retrieved,
                    shadow_diagnostics,
                    shadow_related,
                    route,
                    evidence_plan=shadow_plan,
                )
                final_shadow_gate = grade_retrieval(
                    shadow_signals, refinement_count=1, policy=gate_policy
                )
                shadow_record.update(
                    {
                        "execution": "refine_once",
                        "refinement_executed": True,
                        "refined_query": shadow_query,
                        "final_gate": final_shadow_gate.to_dict(),
                        "final_evidence_requirements": shadow_plan.to_dict(),
                        "retrieval": _retrieval_records(shadow_retrieved),
                        "graph_expansion": _graph_records(shadow_related),
                        "latency_ms": {
                            "refinement": shadow_refine_latency,
                            "retrieval": shadow_retrieval_latency,
                        },
                        "token_usage": shadow_usage.to_dict(),
                    }
                )
            shadow_record["latency_ms"] = {
                **shadow_record.get("latency_ms", {}),
                "total": round((perf_counter() - shadow_started) * 1000, 3),
            }
            trace.shadow_adaptive = shadow_record
            result.shadow_adaptive = shadow_record

        legacy_refuse = use_grounding and should_refuse_before_generation(retrieved)
        trace.confidence_gate = {
            "decision": (
                GateDecision.REFUSE.value if legacy_refuse else GateDecision.ANSWER.value
            ),
            "reason": "legacy top-1 threshold compatibility mode",
            "policy_version": "legacy-rerank-0.636",
            "signals": signals.to_dict(),
        }
        if legacy_refuse:
            progress("[4/5] 檢索分數低於拒答門檻，略過生成…")
            result.refused = True
            result.answer_text = REFUSAL_FINAL_TEXT
            trace.retrieval = _retrieval_records(retrieved)
            trace.retrieval_diagnostics = {"attempts": diagnostic_attempts}
            trace.graph_expansion = _graph_records(related)
            return finish(result, "refused")
    else:
        gate = grade_retrieval(signals, refinement_count=0, policy=gate_policy)
        result.confidence_gate = gate
        trace.confidence_gate = gate.to_dict()

        if gate.decision == GateDecision.REFINE_ONCE:
            if adaptive_mode == AdaptiveMode.CONFIDENCE_GATE_ONLY:
                progress("[gate] 證據需修正，但此評估組停用 refinement，保守拒答")
                result.refused = True
                result.answer_text = REFUSAL_FINAL_TEXT
                trace.confidence_gate["execution"] = "refinement_disabled_refuse"
                trace.retrieval = _retrieval_records(retrieved)
                trace.retrieval_diagnostics = {"attempts": diagnostic_attempts}
                trace.graph_expansion = _graph_records(related)
                return finish(result, "refused")

            if budget.max_refinements < 1:
                result.refused = True
                result.answer_text = REFUSAL_FINAL_TEXT
                trace.confidence_gate["execution"] = "refinement_budget_exhausted"
                trace.retrieval = _retrieval_records(retrieved)
                trace.retrieval_diagnostics = {"attempts": diagnostic_attempts}
                trace.graph_expansion = _graph_records(related)
                return finish(result, "refused")

            progress("[gate] 檢索信心不足，執行唯一一次 query refinement…")
            refine_started = perf_counter()
            refined = refine_query(
                question, query, retrieved, rewrite_model, on_response=observe
            )
            trace.latency_ms["refinement"] = round(
                (perf_counter() - refine_started) * 1000, 3
            )
            trace.refinement_count = 1
            trace.rewritten_queries.append(refined)

            retrieval_started = perf_counter()
            retrieved = retriever.retrieve_multi(
                [question, query, refined], rerank_query=question
            )
            trace.latency_ms["retrieval_refined"] = round(
                (perf_counter() - retrieval_started) * 1000, 3
            )
            diagnostics = getattr(retriever, "last_diagnostics", None)
            if diagnostics is not None:
                diagnostic_attempts.append(diagnostics.to_dict())
            related = []
            if graph is not None and retrieved:
                from .graph_expand import expand_related_articles

                related = expand_related_articles(retrieved, graph, lookup)
            evidence_plan = build_evidence_plan(
                question,
                gate_route,
                retrieved,
                related,
                required_articles=extract_required_articles(question),
            )
            signals = build_gate_signals(
                question,
                retrieved,
                diagnostics,
                related,
                gate_route,
                evidence_plan=evidence_plan,
            )
            trace.evidence_requirements = evidence_plan.to_dict()
            gate = grade_retrieval(
                signals, refinement_count=1, policy=gate_policy
            )
            result.rewritten_query = refined
            result.retrieved = retrieved
            result.related = related
            result.confidence_gate = gate
            trace.confidence_gate = gate.to_dict()
            trace.confidence_gate["refinement_executed"] = True

        if gate is not None and gate.decision != GateDecision.ANSWER:
            progress("[gate] 修正後證據仍不足，略過生成並拒答")
            result.refused = True
            result.answer_text = REFUSAL_FINAL_TEXT
            trace.retrieval = _retrieval_records(retrieved)
            trace.retrieval_diagnostics = {"attempts": diagnostic_attempts}
            trace.graph_expansion = _graph_records(related)
            return finish(result, "refused")

    trace.retrieval = _retrieval_records(retrieved)
    trace.retrieval_diagnostics = {"attempts": diagnostic_attempts}
    trace.graph_expansion = _graph_records(related)

    if (
        trace.token_usage.total_tokens
        and trace.token_usage.total_tokens >= budget.max_total_tokens
    ):
        progress("[budget] 生成前 token budget 已耗盡，保守拒答")
        result.refused = True
        result.answer_text = REFUSAL_FINAL_TEXT
        trace.confidence_gate["execution"] = "token_budget_exhausted"
        return finish(result, "refused")

    # 注意：result.retrieved 始終保留實際檢索結果，供 trace 與除錯。
    if result.refused:
        progress("[4/5] 檢索分數低於拒答門檻，略過生成…")
        return finish(result, "refused")

    progress("[4/5] 生成回答…")
    model = make_chat_model(provider, settings, ollama_model)
    generation_started = perf_counter()
    text = gen_answer(
        question, retrieved, lookup, model, related=related, on_response=observe
    )
    trace.latency_ms["generation"] = round(
        (perf_counter() - generation_started) * 1000, 3
    )

    if use_grounding:
        progress("[5/5] 逐句 groundedness 查核…")
        grounding_started = perf_counter()
        try:
            grounding_result = apply_grounding(
                text,
                retrieved,
                lookup,
                rewrite_model,
                related=related,
                on_response=observe,
                on_retry=record_retry,
            )
        except JudgeUnavailable as e:
            # 查核本身失敗時，寧可拒答也不放行未查核內容（信任優先於可用性）
            grounding_result = GroundingResult(text, REFUSAL_FINAL_TEXT, [], -1)
            result.grounding_error = str(e)
        trace.latency_ms["grounding"] = round(
            (perf_counter() - grounding_started) * 1000, 3
        )
        result.grounding = grounding_result
        result.answer_text = grounding_result.final_text
        trace.grounding = {
            "kind": "post_generation_sentence_grounding",
            "removed_count": grounding_result.removed_count,
            "removed_sentences": [
                verdict.sentence
                for verdict in grounding_result.verdicts
                if not verdict.supported
            ],
            "rewritten_sentences": [],
            "judge_error": result.grounding_error,
        }
    else:
        result.answer_text = text
        trace.grounding = {
            "kind": "disabled",
            "removed_count": 0,
            "removed_sentences": [],
            "rewritten_sentences": [],
        }

    return finish(result, "answered")
