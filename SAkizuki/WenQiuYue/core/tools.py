"""
core/tools.py
──────────────
rag_search / web_search 工具实现，以及提供给 LLM 的 tools 定义。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.retriever import Retriever

MAX_STORED_TOOL_RESULT_BYTES = 256 * 1024


def limit_tool_result_for_history(result: str) -> str:
    """限制进入模型上下文和浏览器历史的单条工具结果，保留可诊断摘要。"""
    raw = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    encoded = raw.encode("utf-8")
    if len(encoded) <= MAX_STORED_TOOL_RESULT_BYTES:
        return raw

    found = False
    result_count = 0
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            items = data.get("results", data.get("tags", data.get("top_tags", [])))
            result_count = len(items) if isinstance(items, list) else 0
            found = bool(data.get("found", result_count > 0))
        elif isinstance(data, list):
            result_count = len(data)
            found = result_count > 0
    except Exception:
        pass

    prefix = encoded[: MAX_STORED_TOOL_RESULT_BYTES // 2].decode("utf-8", errors="ignore")
    while True:
        bounded = json.dumps({
            "truncated": True,
            "original_bytes": len(encoded),
            "stored_limit_bytes": MAX_STORED_TOOL_RESULT_BYTES,
            "found": found,
            "result_count": result_count,
            "content_prefix": prefix,
        }, ensure_ascii=False)
        if len(bounded.encode("utf-8")) <= MAX_STORED_TOOL_RESULT_BYTES or not prefix:
            return bounded
        prefix = prefix[: len(prefix) // 2]

# LLM Tool Calling 定义
WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "当博客知识库中找不到答案时，搜索互联网。仅在 rag_search 无结果后使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词",
                }
            },
            "required": ["query"],
        },
    },
}


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "rag_search",
            "description": "在秋月的博客知识库中搜索相关内容。应优先使用此工具。返回结果包含 chunk_index 字段，可用于 fetch_context 获取上下文。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词或问题",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_context",
            "description": "获取指定博客文章中某个段落的前后相邻段落，补充上下文。仅在 rag_search 命中某篇文章、但内容不完整时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "文章 URL，来自 rag_search 结果的 url 字段",
                    },
                    "chunk_index": {
                        "type": "integer",
                        "description": "目标段落的索引，来自 rag_search 结果的 chunk_index 字段",
                    },
                },
                "required": ["url", "chunk_index"],
            },
        },
    },
    WEB_SEARCH_TOOL,
]


def get_tools(include_web_search: bool = True) -> list[dict]:
    """按当前请求开关返回可暴露给模型的工具定义。"""
    if include_web_search:
        return TOOLS
    return [tool for tool in TOOLS if tool["function"].get("name") != "web_search"]


def execute_rag_search(
    query: str,
    retriever: "Retriever",
    rewrite_queries: list[str],
) -> str:
    """
    执行 RAG 检索。
    返回结果包含 chunk_index，供 LLM 按需调用 fetch_context 获取相邻段落。
    RRF 分数低于 RRF_THRESHOLD 的结果视为无效命中。
    """
    RRF_THRESHOLD = 0.01

    all_queries = list(dict.fromkeys([query] + rewrite_queries))
    results = retriever.search(all_queries, n_results=5)

    hits = [r for r in results if r.get("score", 0) > RRF_THRESHOLD]

    if not hits:
        return json.dumps({"found": False, "results": []}, ensure_ascii=False)

    formatted = []
    for r in hits:
        formatted.append({
            "content":     r["content"],
            "title":       r["title"],
            "url":         r["url"],
            "chunk_index": r.get("chunk_index", -1),
            "score":       round(r["score"], 3),
        })

    return json.dumps({"found": True, "results": formatted}, ensure_ascii=False, indent=2)


def execute_fetch_context(url: str, chunk_index: int, retriever: "Retriever") -> str:
    """
    取指定 chunk 的前后相邻段落，返回给 LLM 作为补充上下文。
    """
    chunks = retriever.fetch_adjacent(url, chunk_index)

    if not chunks:
        return json.dumps({"found": False, "results": []}, ensure_ascii=False)

    formatted = [
        {
            "content":     c["content"],
            "title":       c["title"],
            "url":         c["url"],
            "chunk_index": c["chunk_index"],
        }
        for c in chunks
    ]
    return json.dumps({"found": True, "results": formatted}, ensure_ascii=False, indent=2)


def execute_web_search(query: str, tavily_client) -> str:
    """调用 Tavily 执行网络搜索，返回格式化结果字符串。"""
    try:
        resp = tavily_client.search(
            query=query,
            max_results=5,
            search_depth="basic",
        )
        results = []
        for r in resp.get("results", []):
            results.append({
                "title":   r.get("title", ""),
                "url":     r.get("url", ""),
                "content": r.get("content", ""),
                "score":   round(r.get("score", 0), 3),
            })
        return json.dumps({"found": bool(results), "results": results}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"found": False, "error": str(e)}, ensure_ascii=False)
