"""Plotly helpers for retrieval dashboards."""

from __future__ import annotations

from typing import Any

import plotly.express as px
import plotly.graph_objects as go

from ragkit.models import QueryResult


def retrieval_chart(result: QueryResult) -> go.Figure:
    if not result.retrieval_hits:
        fig = go.Figure()
        fig.update_layout(title="No retrieval hits", height=320)
        return fig
    fig = px.bar(
        x=[round(h.score, 3) for h in result.retrieval_hits],
        y=[f"{h.rank}. {h.chunk.doc_title[:42]}" for h in result.retrieval_hits],
        orientation="h",
        labels={"x": "Hybrid score", "y": "Source"},
        title="Hybrid retrieval ranking (BM25 + TF-IDF)",
        color=[h.chunk.layer for h in result.retrieval_hits],
    )
    fig.update_layout(height=360, yaxis={"autorange": "reversed"})
    return fig


def component_chart(result: QueryResult) -> go.Figure:
    if not result.retrieval_hits:
        fig = go.Figure()
        fig.update_layout(title="Score components", height=320)
        return fig
    hit = result.retrieval_hits[0]
    comps = hit.components or {}
    fig = px.bar(
        x=list(comps.keys()),
        y=[round(v, 3) for v in comps.values()],
        title=f"Top-hit score mix · {hit.chunk.doc_title[:40]}",
        labels={"x": "Component", "y": "Score"},
    )
    fig.update_layout(height=320, showlegend=False)
    return fig


def corpus_layer_chart(taxonomy: dict[str, Any]) -> go.Figure:
    layers = taxonomy.get("layers", {})
    fig = px.pie(
        names=list(layers.keys()) or ["none"],
        values=list(layers.values()) or [1],
        title="Indexed layers",
        hole=0.35,
    )
    fig.update_layout(height=340)
    return fig
