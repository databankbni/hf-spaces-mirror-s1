"""
OR Knowledge Copilot — retrieve similar formulations, solver traces, and executable templates.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import gradio as gr
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from domain.corpus import PRODUCT, SYNONYMS, router  # noqa: E402
from ragkit.audit import QueryAuditStore  # noqa: E402
from ragkit.pipeline import RAGPipeline  # noqa: E402
from ragkit.visualization import component_chart, corpus_layer_chart, retrieval_chart  # noqa: E402

pipe = RAGPipeline(
    chunks_path=ROOT / "dataset" / "chunks.jsonl",
    model_path=ROOT / "model" / "hybrid_index.joblib",
    synonyms=SYNONYMS,
    product=PRODUCT,
    router=router,
    abstain_threshold=0.16,
)
audit = QueryAuditStore()

SAMPLE_QUESTIONS = [
    "What vehicle capacity is used in the NetHorizon last-mile CVRPTW?",
    "Which solver should I use for NetHorizon 50-customer time windows?",
    "What makespan did CP-SAT reach on Line-B FJSSP versus the 312 minute bound?",
    "What is the holding cost and setup cost in DC-14 lot sizing?",
    "How should Pyomo represent SKU-NH442 lot sizing at DC-14?",
    "What spinning reserve does GridWest unit commitment enforce?",
]
DOMAIN_FILTERS = ["all", "Routing", "Scheduling", "Inventory", "Portfolio", "Facility Location", "Energy", "Packing", "Assignment"]
SOLVER_FILTERS = ["all", "ortools", "cp_sat", "highs", "mip"]
CUSTOM_CSS = ".gradio-container { max-width: 1480px !important; }"


def _citations_df(result) -> pd.DataFrame:
    rows = [
        {
            "#": c.index,
            "Document": c.doc_title,
            "Layer": c.layer,
            "Section": c.section,
            "Page": c.page,
            "Score": f"{c.relevance_score:.0%}",
            "Excerpt": c.excerpt,
        }
        for c in result.citations
    ]
    return pd.DataFrame(rows)


def _hits_df(result) -> pd.DataFrame:
    rows = [
        {
            "Rank": h.rank,
            "Score": round(h.score, 3),
            "Document": h.chunk.doc_title,
            "Layer": h.chunk.layer,
            "Domain": h.chunk.metadata.get("domain", ""),
            "Solver": h.chunk.metadata.get("solver", ""),
        }
        for h in result.retrieval_hits
    ]
    return pd.DataFrame(rows)


def _banner(result) -> str:
    if result.abstained:
        return f"### Abstained · confidence {result.confidence:.0%}\nNo citation-backed answer. The copilot will not invent a formulation."
    icon = {"high": "High", "medium": "Medium", "low": "Low"}.get(result.confidence_level.value, "")
    return (
        f"### {icon} confidence {result.confidence:.0%} · route `{result.route}` · "
        f"{len(result.citations)} citations"
    )


def _dashboard() -> str:
    s = audit.stats()
    summary_path = ROOT / "assets" / "demo" / "summary.json"
    extra = ""
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        extra = (
            f"| Indexed documents | **{summary.get('n_documents', 0)}** |\n"
            f"| Chunks | **{summary.get('n_chunks', 0)}** |\n"
        )
    return (
        "### Retrieval control room\n\n"
        "| Metric | Value |\n|---|---|\n"
        f"{extra}"
        f"| Backend | **{pipe.index.embedder.backend}** |\n"
        f"| Session queries | **{s['total_queries']}** |\n"
        f"| Avg confidence | **{s['avg_confidence']:.0%}** |\n"
        f"| Abstained | **{s['abstained']}** |\n"
    )


def ask(question: str, domain: str, solver: str):
    if not question.strip():
        return "", "", pd.DataFrame(), pd.DataFrame(), None, None, _dashboard()
    filters = {}
    if domain != "all":
        filters["domain"] = domain
    if solver != "all":
        filters["solver"] = solver
    result = pipe.ask(question, filters=filters or None)
    audit.record(result, actor="planner", role="or_engineer")
    return (
        _banner(result),
        result.answer,
        _citations_df(result),
        _hits_df(result),
        retrieval_chart(result),
        component_chart(result),
        _dashboard(),
    )


def load_overview():
    tax_path = ROOT / "assets" / "demo" / "taxonomy.json"
    taxonomy = json.loads(tax_path.read_text(encoding="utf-8")) if tax_path.exists() else {}
    eval_path = ROOT / "dataset" / "eval_results.json"
    ev = json.loads(eval_path.read_text(encoding="utf-8")) if eval_path.exists() else {}
    md = (
        f"## {PRODUCT}\n\n"
        "Ask for a **similar instance**, a **mathematical formulation**, **Pyomo/MiniZinc**, or a **solver trace**. "
        "Every sentence is extractive and cited. If the corpus does not contain the fact, the copilot abstains.\n\n"
        f"- Documents: **{taxonomy.get('n_documents', 0)}**\n"
        f"- Chunks: **{taxonomy.get('n_chunks', 0)}**\n"
        f"- Doc hit rate: **{ev.get('doc_hit_rate', 0):.0%}**\n"
        f"- Keyword coverage: **{ev.get('keyword_hit_rate', 0):.0%}**\n"
        f"- Abstain rate (out of scope): **{ev.get('abstain_rate', 0):.0%}**\n"
    )
    return md, corpus_layer_chart(taxonomy), _dashboard()


def corpus_table():
    rows = [
        {
            "ID": c.doc_id,
            "Title": c.doc_title,
            "Layer": c.layer,
            "Domain": c.metadata.get("domain", ""),
            "Solver": c.metadata.get("solver", ""),
            "Page": c.page,
        }
        for c in pipe.index.chunks
    ]
    return pd.DataFrame(rows)


with gr.Blocks(title=PRODUCT, css=CUSTOM_CSS, theme=gr.themes.Soft()) as demo:
    gr.Markdown(
        f"# {PRODUCT}\n"
        "Multi-layer operations-research retrieval: natural language, math, Pyomo, MiniZinc, "
        "solver output, and explanation — with mandatory citations and abstention."
    )
    with gr.Tabs():
        with gr.Tab("Ask"):
            q = gr.Textbox(label="Question", lines=3, value=SAMPLE_QUESTIONS[0])
            with gr.Row():
                domain = gr.Dropdown(DOMAIN_FILTERS, value="all", label="Domain filter")
                solver = gr.Dropdown(SOLVER_FILTERS, value="all", label="Solver filter")
            examples = gr.Examples([[s] for s in SAMPLE_QUESTIONS], inputs=[q])
            btn = gr.Button("Retrieve", variant="primary")
            banner = gr.Markdown()
            answer = gr.Markdown(label="Cited answer")
            with gr.Row():
                cites = gr.Dataframe(label="Citations")
                hits = gr.Dataframe(label="Ranked chunks")
            with gr.Row():
                rank_plot = gr.Plot()
                mix_plot = gr.Plot()
            dash = gr.Markdown()
            btn.click(ask, inputs=[q, domain, solver], outputs=[banner, answer, cites, hits, rank_plot, mix_plot, dash])
        with gr.Tab("Overview"):
            ov = gr.Markdown()
            layer_plot = gr.Plot()
            dash2 = gr.Markdown()
            demo.load(load_overview, outputs=[ov, layer_plot, dash2])
        with gr.Tab("Corpus"):
            table = gr.Dataframe()
            demo.load(corpus_table, outputs=[table])
        with gr.Tab("Audit"):
            audit_df = gr.Dataframe(label="Query audit log")
            refresh = gr.Button("Refresh log")
            refresh.click(lambda: pd.DataFrame(audit.rows()), outputs=[audit_df])

    gr.Markdown(
        "Not a substitute for a solver run. Verify generated code against your instance data. "
        "Dataset: [or-knowledge-copilot-corpus](https://huggingface.co/datasets/alirezaaminzadeh/or-knowledge-copilot-corpus) · "
        "Index: [or-knowledge-copilot-retriever](https://huggingface.co/alirezaaminzadeh/or-knowledge-copilot-retriever)"
    )

if __name__ == "__main__":
    demo.launch()
