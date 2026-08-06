"""Phase 4：法條引用圖譜一階擴展（GraphRAG-lite）。

擴展時機：rerank 之後，對 final top-5（依 parent_id 去重）做一階
outgoing 擴展——找出這些條文「引用出去」的關聯條文，併入生成 context，
標註「關聯條文」。上限 +5、去重、不重跑 rerank。

評估用途（Phase 5）：擴展節點與直接檢索結果分開記錄，不計入 retrieval
precision 分母——`RelatedArticle` 與 `RetrievedChunk` 是不同型別，
呼叫端天然不會混記。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import networkx as nx

from .config import DATA_DIR
from .retriever import RetrievedChunk

GRAPH_PATH = DATA_DIR / "law_graph.json"
EXPANSION_CAP = 5


@dataclass
class RelatedArticle:
    """圖譜擴展帶入的關聯條文（非直接檢索結果）。"""

    law_name: str
    pcode: str
    article_no: str
    content: str
    url: str
    via_parent_id: str  # 是 top-5 裡哪一條的引用帶進來的


def load_graph(path=GRAPH_PATH) -> nx.DiGraph:
    data = json.loads(path.read_text(encoding="utf-8"))
    g = nx.DiGraph()
    for n in data["nodes"]:
        g.add_node(n["id"], **n)
    for e in data["edges"]:
        g.add_edge(e["source"], e["target"], provenance=e["provenance"])
    return g


def expand_related_articles(
    top: list[RetrievedChunk], graph: nx.DiGraph, lookup, cap: int = EXPANSION_CAP
) -> list[RelatedArticle]:
    """對 top（通常是 top-5）做一階 outgoing 擴展，回傳關聯條文清單（保序、去重、全域上限 cap）。"""
    seen_parents = {c.parent_id for c in top}
    related: list[RelatedArticle] = []
    for c in top:
        if c.parent_id not in graph:
            continue
        for target in graph.successors(c.parent_id):
            if target in seen_parents:
                continue
            node = graph.nodes[target]
            record = lookup.full_article(node["pcode"], node["article_no"])
            if not record:
                continue
            seen_parents.add(target)
            related.append(RelatedArticle(
                law_name=node["law_name"],
                pcode=node["pcode"],
                article_no=node["article_no"],
                content=record["content"],
                url=(
                    f"https://law.moj.gov.tw/LawClass/LawSingle.aspx"
                    f"?pcode={node['pcode']}&flno={node['article_no']}"
                ),
                via_parent_id=c.parent_id,
            ))
            if len(related) >= cap:
                return related
    return related
