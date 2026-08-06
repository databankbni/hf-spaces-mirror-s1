# ---------------------------------------------------------------------------
# agent/tools/verse_search.py — Phase E2.
#
# smolagents tool: semantic search over the Gita. Given a natural-language
# question ("what does Krishna say about acting without attachment?"), it
# returns the most relevant verses by MEANING — even when the wording
# differs. The agent then reads these verses and writes a grounded answer,
# citing verse references.
#
# Dependency-injected retriever (like the smoltestagent rag_search tool) so
# unit tests don't need to open Chroma.
# ---------------------------------------------------------------------------

from typing import Any

from smolagents import Tool

from agent.retriever import VerseRetriever

_DEFAULT_K = 3


class VerseSearchTool(Tool):
    name = "verse_search"
    description = (
        "Search the Bhagavad Gita by meaning for verses relevant to a "
        "natural-language question about its teachings (duty, action, the "
        "self, devotion, etc.). Returns the most relevant verses with their "
        "references and English translation. You must read the returned "
        "verses and write the final answer yourself, citing the verse "
        "references (e.g. [BG2.47]). If the verses do not address the "
        "question, say you don't know."
    )
    inputs: dict[str, dict[str, Any]] = {
        "question": {
            "type": "string",
            "description": (
                "Natural-language question about the Bhagavad Gita's "
                "teachings, e.g. 'What does Krishna say about fear?'"
            ),
        }
    }
    output_type = "string"

    def __init__(self, retriever: VerseRetriever) -> None:
        super().__init__()
        self._retriever = retriever

    def forward(self, question: str) -> str:
        if not question.strip():
            return "error: question is empty"
        try:
            hits = self._retriever.query(question, k=_DEFAULT_K)
        except Exception as e:  # noqa: BLE001 — tool boundary
            return f"error: search failed ({type(e).__name__}: {e})"
        if not hits:
            return "no relevant verses found"
        rendered = []
        for hit in hits:
            rendered.append(f"[{hit['verse_id']}] {hit['text']}")
        return "\n\n".join(rendered)
