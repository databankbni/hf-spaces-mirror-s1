"""African History Research MCP — Jina AI Search Foundation backend.

Aligned with Jina meta-prompt v13 (2026):
  - Search:  POST https://s.jina.ai/   body {"q": ..., "num": ...}
  - Reader:  POST https://r.jina.ai/   body {"url": ...}
  - Rerank:  POST https://api.jina.ai/v1/rerank      (jina-reranker-v3)
  - Embed:   POST https://api.jina.ai/v1/embeddings  (jina-embeddings-v3)
  - Classify:POST https://api.jina.ai/v1/classify

Get your Jina AI API key for free: https://jina.ai/?sui=apikey
Set it as the JINA_API_KEY environment variable (required for all endpoints).
"""

import os
import re
import requests
import gradio as gr
from typing import Literal, List, Dict

JINA_SEARCH_URL = "https://s.jina.ai/"
JINA_READER_URL = "https://r.jina.ai/"
JINA_RERANK_URL = "https://api.jina.ai/v1/rerank"
JINA_EMBED_URL = "https://api.jina.ai/v1/embeddings"
JINA_CLASSIFY_URL = "https://api.jina.ai/v1/classify"

RERANKER_MODEL = "jina-reranker-v3"          # latest multilingual reranker
EMBED_MODEL = "jina-embeddings-v3"           # supports task=retrieval.passage / classification
REQUEST_TIMEOUT = 60


def _json_headers(extra: Dict = None) -> Dict:
    api_key = os.getenv("JINA_API_KEY")
    if not api_key:
        raise RuntimeError(
            "JINA_API_KEY is not set. Get a free key at https://jina.ai/?sui=apikey"
        )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if extra:
        headers.update(extra)
    return headers


def _post_json(url: str, payload: Dict, extra_headers: Dict = None) -> Dict:
    resp = requests.post(
        url, headers=_json_headers(extra_headers), json=payload, timeout=REQUEST_TIMEOUT
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Core primitives
# ---------------------------------------------------------------------------

def search(
    input_query: str,
    max_results: int = 5,
    site: str = "",
    with_content: bool = False,
) -> List[Dict]:
    """
    Perform a web search using the Jina Search API (POST s.jina.ai).

    Args:
        input_query: The query to search for.
        max_results: The maximum number of results to return. Defaults to 5.
        site: Optional domain to restrict the search to (uses the X-Site header,
            e.g. "archive.org").
        with_content: If True, include the full page content of each result
            (slower and much more token-hungry). Defaults to False (SERP only).

    Returns:
        A list of dictionaries with "title", "link", "snippet", and optionally "content".
    """
    payload: Dict = {"q": input_query}
    if max_results:
        payload["num"] = int(max_results)

    extra = {"X-Engine": "direct"}
    if not with_content:
        extra["X-Respond-With"] = "no-content"
    if site:
        extra["X-Site"] = site

    data = _post_json(JINA_SEARCH_URL, payload, extra)
    results = data.get("data", []) if isinstance(data, dict) else []

    items = []
    for r in results[:max_results]:
        item = {
            "title": str(r.get("title") or ""),
            "link": str(r.get("url") or ""),
            "snippet": str(r.get("description") or ""),
        }
        if with_content and r.get("content"):
            item["content"] = str(r["content"])[:4000]
        if item["link"] or item["title"] or item["snippet"]:
            items.append(item)
    return items


def read_historical_source(url: str, target_selector: str = "") -> str:
    """
    Extract clean markdown from a historical source URL (Wikipedia, archive.org, etc.)
    using the Jina Reader API (POST r.jina.ai).

    Args:
        url: The full URL of the historical source page to read.
        target_selector: Optional CSS selector to focus extraction on specific
            elements (e.g. "article", "#content", ".mw-parser-output").
            NOTE: this must be a CSS selector, not a keyword.

    Returns:
        Clean markdown text extracted from the page (capped to avoid oversized responses).
    """
    extra = {"X-Return-Format": "markdown", "X-Engine": "direct"}
    if target_selector:
        extra["X-Target-Selector"] = target_selector

    data = _post_json(JINA_READER_URL, {"url": url}, extra)
    content = ""
    if isinstance(data, dict):
        content = (data.get("data") or {}).get("content", "") or ""
    return content[:8000]  # cap to stay within MCP response token limits


def rerank_documents(
    query: str,
    documents: List[str],
    top_n: int = 5,
    model: str = RERANKER_MODEL,
) -> List[Dict]:
    """
    Rerank a list of text documents/snippets against a query using the Jina Reranker API.

    Args:
        query: The research question or query to rank documents against.
        documents: List of raw text passages/snippets to rerank.
        top_n: Number of top-ranked documents to return. Defaults to 5.
        model: Jina reranker model name. Defaults to jina-reranker-v3.

    Returns:
        A list of dictionaries with "index" (original position), "score" (relevance
        score 0-1), and "text", sorted by descending relevance.
    """
    if not documents:
        return []
    payload = {
        "model": model,
        "query": query,
        "documents": documents,
        "top_n": min(top_n, len(documents)),
        "return_documents": True,
    }
    data = _post_json(JINA_RERANK_URL, payload)

    out = []
    for r in data.get("results", []):
        idx = r.get("index")
        doc = r.get("document")
        if isinstance(doc, dict):
            text = doc.get("text", "")
        elif isinstance(doc, str):
            text = doc
        else:
            text = documents[idx] if idx is not None and idx < len(documents) else ""
        out.append({
            "index": idx,
            "score": r.get("relevance_score", 0),
            "text": text,
        })
    return out


def embed_texts(
    texts: List[str],
    model: str = EMBED_MODEL,
    task: str = "retrieval.passage",
) -> List[List[float]]:
    """
    Generate dense vector embeddings for a list of texts using the Jina Embeddings API.

    Args:
        texts: List of text strings to embed.
        model: Jina embedding model name. Defaults to jina-embeddings-v3.
        task: Embedding task type, e.g. "retrieval.passage" or "retrieval.query".

    Returns:
        A list of embedding vectors, one per input text, in input order.
    """
    if not texts:
        return []
    payload = {"model": model, "task": task, "input": texts, "truncate": True}
    data = _post_json(JINA_EMBED_URL, payload)
    items = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
    return [item["embedding"] for item in items]


def classify_relevance(
    texts: List[str],
    labels: List[str] = None,
) -> List[Dict]:
    """
    Zero-shot classify text snippets into user-defined labels using the Jina Classify API.

    Args:
        texts: List of text snippets to classify.
        labels: Label strings to classify each text into. Defaults to a generic
            historical-source taxonomy.

    Returns:
        A list of dictionaries with "text", "predicted_label", and "score".
    """
    if not texts:
        return []
    if not labels:
        labels = ["primary source", "secondary analysis", "oral tradition",
                  "colonial record", "irrelevant"]
    payload = {"model": EMBED_MODEL, "input": texts, "labels": labels}
    data = _post_json(JINA_CLASSIFY_URL, payload)

    out = []
    for i, item in enumerate(data.get("data", [])):
        out.append({
            "text": texts[i][:200],
            "predicted_label": item.get("prediction", ""),
            "score": item.get("score", 0),
        })
    return out


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def deduplicate_snippets(snippets: List[str], similarity_threshold: float = 0.9) -> List[str]:
    """
    Remove semantically duplicate snippets using Jina embeddings + cosine similarity.

    Args:
        snippets: List of raw text snippets, possibly containing near-duplicates.
        similarity_threshold: Cosine similarity above which two snippets are
            considered duplicates. Defaults to 0.9.

    Returns:
        A deduplicated list of snippets, preserving first-occurrence order.
    """
    if len(snippets) <= 1:
        return snippets
    vectors = embed_texts(snippets, task="retrieval.passage")
    kept_texts, kept_vectors = [], []
    for text, vec in zip(snippets, vectors):
        if not any(_cosine_similarity(vec, kv) >= similarity_threshold for kv in kept_vectors):
            kept_texts.append(text)
            kept_vectors.append(vec)
    return kept_texts


# ---------------------------------------------------------------------------
# Intelligent African history research tools (search + rerank combined)
# ---------------------------------------------------------------------------

def _rerank_search_results(query: str, raw_results: List[Dict], top_n: int) -> List[Dict]:
    """Shared helper: rerank raw SERP results against the original query."""
    docs = [f"{r['title']}. {r['snippet']}" for r in raw_results]
    reranked = rerank_documents(query, docs, top_n=top_n)
    output = []
    for r in reranked:
        idx = r["index"]
        if idx is not None and idx < len(raw_results):
            src = raw_results[idx]
            output.append({
                "title": src["title"],
                "link": src["link"],
                "snippet": src["snippet"],
                "relevance_score": round(r["score"], 4),
            })
    return output


def search_african_history(
    query: str,
    region: str = "",
    period: str = "",
    max_results: int = 5,
    rerank_pool: int = 15,
) -> List[Dict]:
    """
    Intelligent African history search: fetches a larger pool of raw results scoped
    by region/period, then reranks them by semantic relevance to the original query.

    Args:
        query: Core research question or topic (e.g. "trans-Saharan trade routes").
        region: Optional region filter (e.g. "West Africa", "Great Lakes", "Sahel").
        period: Optional period filter (e.g. "pre-colonial", "1400-1600", "medieval").
        max_results: Final number of top reranked results to return. Defaults to 5.
        rerank_pool: Number of raw candidates to fetch before reranking. Defaults to 15.

    Returns:
        A list of dicts with "title", "link", "snippet", "relevance_score".
    """
    scoped_query = " ".join(p for p in [query, region, period, "African history"] if p)
    raw_results = search(scoped_query, max_results=rerank_pool)
    if not raw_results:
        return []
    return _rerank_search_results(query, raw_results, max_results)


def search_academic_papers(
    topic: str,
    source: Literal["arxiv", "ssrn", "semantic_scholar"] = "arxiv",
    max_results: int = 8,
    rerank_pool: int = 20,
) -> List[Dict]:
    """
    Intelligent academic paper search on African history topics, scoped to a single
    academic domain via the X-Site header, then semantically reranked.

    Args:
        topic: Research topic to search for (e.g. "Kingdom of Kush archaeology").
        source: Which academic source to scope the search to.
        max_results: Final number of top reranked results to return. Defaults to 8.
        rerank_pool: Number of raw candidates to fetch before reranking. Defaults to 20.

    Returns:
        A list of dicts with "title", "link", "snippet", "relevance_score".
    """
    site = {
        "arxiv": "arxiv.org",
        "ssrn": "ssrn.com",
        "semantic_scholar": "semanticscholar.org",
    }[source]
    raw_results = search(f"{topic} Africa history", max_results=rerank_pool, site=site)
    if not raw_results:
        return []
    return _rerank_search_results(topic, raw_results, max_results)


def fetch_archive_document(
    search_terms: str,
    doc_type: Literal["text", "audio", "image"] = "text",
    max_results: int = 5,
    rerank_pool: int = 15,
) -> List[Dict]:
    """
    Intelligent Internet Archive search for African historical documents, manuscripts,
    oral histories, and colonial-era records. Reranks candidates by relevance before
    enriching top text results with extracted page content.

    Args:
        search_terms: Keywords describing the document or topic to find.
        doc_type: Type of archive material to search for ("text", "audio", "image").
        max_results: Final number of top reranked results to return. Defaults to 5.
        rerank_pool: Number of raw candidates to fetch before reranking. Defaults to 15.

    Returns:
        A list of dicts with "title", "link", "snippet", "relevance_score",
        and optionally "extracted_text" for text documents.
    """
    raw_results = search(
        f"{search_terms} Africa {doc_type}", max_results=rerank_pool, site="archive.org"
    )
    if not raw_results:
        return []

    ranked = _rerank_search_results(search_terms, raw_results, max_results)
    for src in ranked:
        if src.get("link") and doc_type == "text":
            try:
                src["extracted_text"] = read_historical_source(src["link"])[:2000]
            except Exception:
                src["extracted_text"] = ""
    return ranked


def deep_research_query(
    query: str,
    region: str = "",
    period: str = "",
    max_results: int = 8,
    rerank_pool: int = 25,
) -> List[Dict]:
    """
    Combined intelligent research pipeline: searches broadly, deduplicates near-identical
    snippets via embeddings, reranks the remainder against the query, and classifies each
    surviving result by historical source type.

    Args:
        query: Core research question or topic.
        region: Optional region filter (e.g. "West Africa", "Horn of Africa").
        period: Optional period filter (e.g. "pre-colonial", "19th century").
        max_results: Final number of top results to return. Defaults to 8.
        rerank_pool: Number of raw candidates to fetch before dedup/rerank. Defaults to 25.

    Returns:
        A list of dicts with "title", "link", "snippet", "relevance_score",
        and "source_type", sorted by descending relevance.
    """
    scoped_query = " ".join(p for p in [query, region, period] if p)
    raw_results = search(scoped_query, max_results=rerank_pool)
    if not raw_results:
        return []

    snippet_map = {f"{r['title']}. {r['snippet']}": r for r in raw_results}
    unique_docs = deduplicate_snippets(list(snippet_map.keys()), similarity_threshold=0.92)

    reranked = rerank_documents(query, unique_docs, top_n=max_results)

    top_texts = [r["text"] for r in reranked]
    classifications = classify_relevance(top_texts) if top_texts else []
    label_map = {c["text"][:200]: c["predicted_label"] for c in classifications}

    output = []
    for r in reranked:
        doc_text = r["text"]
        src = snippet_map.get(doc_text)
        if not src:
            continue
        output.append({
            "title": src["title"],
            "link": src["link"],
            "snippet": src["snippet"],
            "relevance_score": round(r["score"], 4),
            "source_type": label_map.get(doc_text[:200], "unclassified"),
        })
    return output


def build_historical_timeline(raw_events: str, topic: str = "") -> List[Dict]:
    """
    Parse and sort historical events by year from free-text input.

    Args:
        raw_events: Newline-separated event descriptions, each containing a year
            (supports BCE/BC/CE/AD suffixes, e.g. "1450 CE: fall of Mali empire").
        topic: Optional topic label for context (not used in sorting).

    Returns:
        A list of dicts with "year" and "event", sorted chronologically ascending.
    """
    lines = [l.strip() for l in raw_events.strip().splitlines() if l.strip()]
    timeline = []
    for line in lines:
        match = re.search(r"(\d{1,4})\s*(BCE|BC|CE|AD)?", line, re.IGNORECASE)
        if match:
            year = int(match.group(1))
            era = (match.group(2) or "CE").upper()
            sort_key = -year if era in ("BCE", "BC") else year
            timeline.append({"year": f"{year} {era}", "sort_key": sort_key, "event": line})
    timeline.sort(key=lambda x: x["sort_key"])
    return [{"year": t["year"], "event": t["event"]} for t in timeline]


# ---------------------------------------------------------------------------
# Gradio wrappers for textbox-based tools (must be defined BEFORE the Interfaces:
# reassigning `interface.fn` after construction does NOT rewire Gradio events)
# ---------------------------------------------------------------------------

def rerank_documents_ui(query: str, documents_block: str, top_n: int) -> List[Dict]:
    """
    Rerank newline-separated text passages against a query using the Jina Reranker API.

    Args:
        query: The query to rank documents against.
        documents_block: Documents to rerank, one per line.
        top_n: Number of top-ranked documents to return.

    Returns:
        A list of dicts with "index", "score", and "text", sorted by relevance.
    """
    docs = [d.strip() for d in documents_block.strip().splitlines() if d.strip()]
    return rerank_documents(query, docs, top_n=top_n)


def classify_relevance_ui(texts_block: str, labels_block: str) -> List[Dict]:
    """
    Classify newline-separated text snippets into comma-separated labels using
    Jina zero-shot classification.

    Args:
        texts_block: Text snippets to classify, one per line.
        labels_block: Comma-separated list of labels.

    Returns:
        A list of dicts with "text", "predicted_label", and "score".
    """
    texts = [t.strip() for t in texts_block.strip().splitlines() if t.strip()]
    labels = [l.strip() for l in labels_block.split(",") if l.strip()]
    return classify_relevance(texts, labels)


# ---------------------------------------------------------------------------
# Gradio interfaces (each becomes an MCP tool)
# ---------------------------------------------------------------------------

search_tab = gr.Interface(
    fn=search,
    inputs=[
        gr.Textbox(value="Ahly SC of Egypt matches.", label="Search query"),
        gr.Slider(minimum=1, maximum=20, value=5, step=1, label="Max results"),
        gr.Textbox(value="", label="Restrict to site (optional, e.g. archive.org)"),
        gr.Checkbox(value=False, label="Include full page content"),
    ],
    outputs=gr.JSON(label="Search results"),
    title="Web Searcher",
    description="Web search using the Jina Search API (POST s.jina.ai).",
)

read_source_tab = gr.Interface(
    fn=read_historical_source,
    inputs=[
        gr.Textbox(value="https://en.wikipedia.org/wiki/Mali_Empire", label="Source URL"),
        gr.Textbox(value="", label="CSS target selector (optional, e.g. #content)"),
    ],
    outputs=gr.Textbox(label="Extracted content", lines=20),
    title="Read Historical Source",
    description="Extract clean markdown from a URL via Jina Reader (POST r.jina.ai).",
)

african_history_tab = gr.Interface(
    fn=search_african_history,
    inputs=[
        gr.Textbox(value="trans-Saharan trade routes", label="Query"),
        gr.Textbox(value="West Africa", label="Region (optional)"),
        gr.Textbox(value="medieval", label="Period (optional)"),
        gr.Slider(minimum=1, maximum=20, value=5, step=1, label="Max results"),
        gr.Slider(minimum=5, maximum=40, value=15, step=1, label="Rerank pool size"),
    ],
    outputs=gr.JSON(label="Reranked results"),
    title="Search African History (Reranked)",
    description="Region/period-scoped search, reranked with jina-reranker-v3.",
)

academic_tab = gr.Interface(
    fn=search_academic_papers,
    inputs=[
        gr.Textbox(value="Kingdom of Kush archaeology", label="Topic"),
        gr.Dropdown(choices=["arxiv", "ssrn", "semantic_scholar"], value="arxiv", label="Source"),
        gr.Slider(minimum=1, maximum=20, value=8, step=1, label="Max results"),
        gr.Slider(minimum=5, maximum=40, value=20, step=1, label="Rerank pool size"),
    ],
    outputs=gr.JSON(label="Reranked results"),
    title="Search Academic Papers (Reranked)",
    description="Domain-scoped academic search (X-Site header), reranked by relevance.",
)

archive_tab = gr.Interface(
    fn=fetch_archive_document,
    inputs=[
        gr.Textbox(value="oral history Great Zimbabwe", label="Search terms"),
        gr.Dropdown(choices=["text", "audio", "image"], value="text", label="Document type"),
        gr.Slider(minimum=1, maximum=20, value=5, step=1, label="Max results"),
        gr.Slider(minimum=5, maximum=40, value=15, step=1, label="Rerank pool size"),
    ],
    outputs=gr.JSON(label="Reranked results"),
    title="Fetch Archive Document (Reranked)",
    description="Internet Archive search (X-Site: archive.org), reranked, with text extraction.",
)

deep_research_tab = gr.Interface(
    fn=deep_research_query,
    inputs=[
        gr.Textbox(value="role of women in Ashanti political leadership", label="Query"),
        gr.Textbox(value="", label="Region (optional)"),
        gr.Textbox(value="", label="Period (optional)"),
        gr.Slider(minimum=1, maximum=20, value=8, step=1, label="Max results"),
        gr.Slider(minimum=5, maximum=50, value=25, step=1, label="Rerank pool size"),
    ],
    outputs=gr.JSON(label="Deep research results"),
    title="Deep Research (Dedup + Rerank + Classify)",
    description="Search → dedup via embeddings → rerank → classify by source type.",
)

rerank_tab = gr.Interface(
    fn=rerank_documents_ui,
    inputs=[
        gr.Textbox(value="Mansa Musa pilgrimage to Mecca", label="Query"),
        gr.Textbox(
            value="In 1324, Mansa Musa traveled to Mecca.\nThe pilgrimage disrupted gold prices in Cairo.\nUnrelated text about football.",
            label="Documents (one per line)",
            lines=6,
        ),
        gr.Slider(minimum=1, maximum=20, value=5, step=1, label="Top N"),
    ],
    outputs=gr.JSON(label="Reranked results"),
    title="Rerank Documents",
    description="Standalone reranker: sort text passages by relevance to a query.",
)

classify_tab = gr.Interface(
    fn=classify_relevance_ui,
    inputs=[
        gr.Textbox(
            value="Oral account passed down by griots.\nColonial administrative report from 1902.",
            label="Texts (one per line)",
            lines=6,
        ),
        gr.Textbox(
            value="primary source, secondary analysis, oral tradition, colonial record, irrelevant",
            label="Labels (comma-separated)",
        ),
    ],
    outputs=gr.JSON(label="Classification results"),
    title="Classify Source Type",
    description="Tag text snippets by historical source type (zero-shot classification).",
)

timeline_tab = gr.Interface(
    fn=build_historical_timeline,
    inputs=[
        gr.Textbox(
            value="1235 CE: Founding of the Mali Empire\n1324 CE: Mansa Musa pilgrimage to Mecca\n1468 CE: Fall of Timbuktu to Songhai",
            label="Raw events (one per line)",
            lines=8,
        ),
        gr.Textbox(value="", label="Topic (optional, for reference)"),
    ],
    outputs=gr.JSON(label="Sorted timeline"),
    title="Build Historical Timeline",
    description="Parse free-text event notes and sort them chronologically.",
)

demo = gr.TabbedInterface(
    [
        search_tab,
        read_source_tab,
        african_history_tab,
        academic_tab,
        archive_tab,
        deep_research_tab,
        rerank_tab,
        classify_tab,
        timeline_tab,
    ],
    tab_names=[
        "Web Search",
        "Read Source",
        "African History",
        "Academic Papers",
        "Archive Documents",
        "Deep Research",
        "Rerank",
        "Classify Source",
        "Timeline Builder",
    ],
    title="African History Research MCP",
)

if __name__ == "__main__":
    demo.launch(mcp_server=True)