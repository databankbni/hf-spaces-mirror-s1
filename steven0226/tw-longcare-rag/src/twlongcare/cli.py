"""CLI 問答：口語問題 → 改寫 → hybrid 檢索 → 拒答門檻 → 含引用回答 → 逐句查核。

用法：
    uv run python -m twlongcare.cli "阿嬤請看護政府有補助嗎" --provider ollama
    uv run python -m twlongcare.cli "問題" --provider gemini
    uv run python -m twlongcare.cli "問題" --provider openai --no-rerank
    uv run python -m twlongcare.cli "問題" --embedding bge-m3
    uv run python -m twlongcare.cli "問題" --no-grounding   # 關閉 Phase 3 查核（對照用）
    uv run python -m twlongcare.cli "問題" --no-graph       # 關閉 Phase 4 圖譜擴展（對照用）

模型分工（PLAN 分工總表）：主生成用該 provider 主模型；query 改寫與
grounding 判定在 ollama 模式用同一地端模型（零成本）、gemini 模式用
GEMINI_LITE、openai 模式維持供應商純度用 OPENAI_MODEL。

核心管線邏輯在 `pipeline.py`（Phase 6 起與 Gradio 介面共用）；本檔只負責
CLI 專屬的參數解析、逐步進度印出（stderr）與結果格式化輸出（stdout）。
"""

from __future__ import annotations

import argparse
import sys

from .config import LOGS_DIR


def main(argv: list[str] | None = None) -> None:
    # Windows legacy consoles may default to cp950, which cannot encode emoji
    # used by the existing disclaimer/progress output.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="台灣長照法規 RAG 問答（非官方服務）")
    parser.add_argument("question")
    parser.add_argument("--provider", choices=["ollama", "gemini", "openai"],
                        default="ollama")
    parser.add_argument("--ollama-model", default=None)
    parser.add_argument("--embedding", choices=["gtaide", "bge-m3"], default="gtaide")
    parser.add_argument("--dim", type=int, default=None)
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--no-contextual", action="store_true",
                        help="使用 noctx 索引（需先以 --no-contextual 建索引）")
    parser.add_argument("--no-grounding", action="store_true",
                        help="關閉 Phase 3 逐句 groundedness 查核（對照展示用）")
    parser.add_argument("--no-graph", action="store_true",
                        help="關閉 Phase 4 法條引用圖譜一階擴展（對照展示用）")
    parser.add_argument("--show-chunks", action="store_true",
                        help="顯示檢索到的 chunk 與分數（除錯用）")
    parser.add_argument(
        "--adaptive-mode",
        choices=[
            "current_baseline",
            "confidence_gate_only",
            "refinement_enabled",
            "full_adaptive_route",
        ],
        default="current_baseline",
        help="預設保留 locked baseline；只有明確指定才啟用實驗性 gate/refinement",
    )
    parser.add_argument("--max-refinements", type=int, choices=[0, 1], default=1)
    parser.add_argument("--max-total-tokens", type=int, default=16_000)
    parser.add_argument(
        "--shadow-adaptive",
        action="store_true",
        help="仍以 baseline 回答，只記錄 Adaptive gate 若啟用時的決策",
    )
    parser.add_argument(
        "--shadow-refine",
        action="store_true",
        help="shadow 命中 refine_once 時實跑一次修正；不改 baseline 回答但增加延遲",
    )
    args = parser.parse_args(argv)
    if args.shadow_refine and not args.shadow_adaptive:
        parser.error("--shadow-refine 需要同時指定 --shadow-adaptive")

    from .generate import LawsLookup
    from .graph_expand import GRAPH_PATH, load_graph
    from .grounding import log_grounding
    from .pipeline import PipelineBudget, ShadowAdaptiveConfig, run_pipeline
    from .retriever import HybridRetriever

    retriever = HybridRetriever(
        embedding_key=args.embedding,
        dim=args.dim,
        contextual=not args.no_contextual,
        use_rerank=not args.no_rerank,
    )
    lookup = LawsLookup()

    graph = None
    if not args.no_graph:
        if GRAPH_PATH.exists():
            graph = load_graph()
        else:
            print("[3/5] 圖譜檔案不存在，略過擴展（跑 scripts/build_graph.py 建立）",
                  file=sys.stderr)

    def on_progress(msg: str) -> None:
        print(msg, file=sys.stderr)

    result = run_pipeline(
        args.question, retriever, lookup,
        provider=args.provider, ollama_model=args.ollama_model,
        use_grounding=not args.no_grounding, graph=graph, on_progress=on_progress,
        adaptive_mode=args.adaptive_mode,
        budget=PipelineBudget(
            max_refinements=args.max_refinements,
            max_total_tokens=args.max_total_tokens,
        ),
        shadow_adaptive=ShadowAdaptiveConfig(
            enabled=args.shadow_adaptive,
            execute_refinement=args.shadow_refine,
        ),
    )

    if result.rewritten_query != args.question:
        print(f"    改寫：{result.rewritten_query}", file=sys.stderr)
    for c in result.retrieved:
        rs = f" rerank={c.rerank_score:.3f}" if c.rerank_score is not None else ""
        print(f"    {c.chunk_id}（{'+'.join(c.sources)}{rs}）", file=sys.stderr)
    for r in result.related:
        print(f"    +關聯條文 {r.pcode}-{r.article_no}（經 {r.via_parent_id} 引用）",
              file=sys.stderr)
    if result.grounding_error:
        print(f"    ⚠️ judge 失敗，改為拒答：{result.grounding_error}", file=sys.stderr)
    if result.grounding_removed_count > 0:
        print(f"    移除 {result.grounding_removed_count} 句不受支持的內容", file=sys.stderr)
    if result.confidence_gate is not None:
        print(
            f"    confidence gate：{result.confidence_gate.decision.value} "
            f"({result.confidence_gate.reason})",
            file=sys.stderr,
        )
    if result.shadow_adaptive is not None:
        initial = result.shadow_adaptive["initial_gate"]["decision"]
        final = result.shadow_adaptive.get("final_gate", {}).get("decision")
        suffix = f" → {final}" if final else ""
        print(
            f"    shadow adaptive：{initial}{suffix} "
            f"（baseline 回答未受影響）",
            file=sys.stderr,
        )

    if result.grounding is not None:
        log_grounding(
            LOGS_DIR / "grounding" / f"{args.provider}.jsonl",
            args.question, args.provider, result.grounding,
        )

    print("\n" + "=" * 60)
    print(result.answer_text)
    print("=" * 60)
    if not result.refused and not result.overview:
        print("\n引用條文出處：")
        seen = set()
        for c in result.retrieved:
            if c.parent_id in seen:
                continue
            seen.add(c.parent_id)
            print(f"  《{c.law_name}》第 {c.article_no} 條  {c.url}")
        if result.related:
            print("\n關聯條文（法條引用關係擴展）：")
            for r in result.related:
                print(f"  《{r.law_name}》第 {r.article_no} 條  {r.url}")
    print("\n⚠️ 本工具為非官方個人專案，僅供參考；正式資訊以衛生福利部公告與 1966 專線為準。")

    if args.show_chunks:
        print("\n[debug] 檢索 chunk 全文：")
        for c in result.retrieved:
            print(f"\n--- {c.chunk_id} ---\n{c.text}")


if __name__ == "__main__":
    main()
