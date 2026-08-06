from typing import Dict, List
import re

MIN_RERANK_SCORE = 1.0


def format_citation(chunk: Dict) -> str:
    """Create a readable citation label for a retrieved chunk."""
    return f"{chunk['paper_title']}, page {chunk['page_number']}"


def has_enough_evidence(chunks: List[Dict], min_score: float = MIN_RERANK_SCORE) -> bool:
    """Decide whether retrieved evidence is strong enough to answer."""
    if not chunks:
        return False

    best_score = chunks[0].get("rerank_score", chunks[0].get("search_score", 0.0))
    return best_score >= min_score


def write_evidence_summary(chunks: List[Dict], max_chunks: int = 3) -> str:
    """
    Create a simple grounded answer from retrieved evidence.

    This is intentionally extractive for the first version. It avoids pretending
    to know more than the retrieved paper text supports.
    """
    selected_chunks = chunks[:max_chunks]

    summary_parts = []

    for chunk in selected_chunks:
        citation = format_citation(chunk)
        text = chunk["text"].strip()

        if len(text) > 700:
            text = text[:700].rsplit(" ", 1)[0] + "..."

        summary_parts.append(f"According to {citation}, {text}")

    return "\n\n".join(summary_parts)


def answer_from_evidence(
    query: str,
    chunks: List[Dict],
    min_score: float = MIN_RERANK_SCORE,
    max_chunks: int = 3,
) -> Dict:
    """
    Produce a citation-grounded answer from retrieved and reranked chunks.
    """
    if not has_enough_evidence(chunks, min_score=min_score):
        return {
            "query": query,
            "answer": (
                "I do not have enough strong evidence from the selected papers "
                "to answer this question reliably."
            ),
            "citations": [],
            "evidence_used": [],
            "confidence": "low",
        }

    selected_chunks = chunks[:max_chunks]

    citations = []
    for chunk in selected_chunks:
        citation = {
            "paper_title": chunk["paper_title"],
            "page_number": chunk["page_number"],
            "chunk_id": chunk["chunk_id"],
            "citation": format_citation(chunk),
        }
        citations.append(citation)

    return {
        "query": query,
        "answer": write_brief_answer(query, selected_chunks),
        "citations": citations,
        "evidence_used": selected_chunks,
        "confidence": "medium",
    }

def format_answer_for_display(answer: Dict) -> str:
    """Format a grounded answer for notebook or app display."""
    lines = []

    lines.append("Answer")
    lines.append(answer["answer"])

    if answer["citations"]:
        lines.append("")
        lines.append("Citations")

        seen = set()
        for citation in answer["citations"]:
            citation_text = citation["citation"]

            if citation_text in seen:
                continue

            seen.add(citation_text)
            lines.append(f"- {citation_text}")

    lines.append("")
    lines.append(f"Confidence: {answer['confidence']}")

    return "\n".join(lines)

def evidence_strength(chunks: List[Dict]) -> str:
    """Estimate how strong the retrieved evidence is."""
    if not chunks:
        return "weak"

    best_score = chunks[0].get("rerank_score", chunks[0].get("search_score", 0.0))

    if best_score >= 3.0:
        return "strong"

    if best_score >= 1.0:
        return "moderate"

    return "weak"

STOPWORDS = {
    "what", "why", "how", "does", "do", "is", "are", "the", "a", "an", "in",
    "on", "of", "to", "for", "and", "or", "with", "it", "this", "that"
}


def split_sentences(text: str) -> List[str]:
    """Split text into readable sentences."""
    return [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", text) if sentence.strip()]


def query_terms(query: str) -> set[str]:
    """Extract useful query terms for lightweight extractive answering."""
    words = re.findall(r"[a-zA-Z][a-zA-Z\-]+", query.lower())
    return {word for word in words if word not in STOPWORDS and len(word) > 2}


def sentence_relevance(sentence: str, terms: set[str]) -> int:
    """Score a sentence by query-term overlap."""
    sentence_lower = sentence.lower()
    return sum(1 for term in terms if term in sentence_lower)


def write_brief_answer(query: str, chunks: List[Dict], max_sentences: int = 4) -> str:
    """Write a concise answer using only retrieved evidence."""
    terms = query_terms(query)
    candidates = []

    for chunk in chunks[:4]:
        citation = format_citation(chunk)

        for sentence in split_sentences(chunk["text"]):
            score = sentence_relevance(sentence, terms)

            if score > 0:
                candidates.append(
                    {
                        "sentence": sentence,
                        "score": score,
                        "citation": citation,
                    }
                )

    if not candidates:
        return write_evidence_summary(chunks, max_chunks=2)

    candidates.sort(key=lambda item: item["score"], reverse=True)

    selected = []
    seen = set()

    for candidate in candidates:
        sentence = candidate["sentence"]

        if sentence in seen:
            continue

        seen.add(sentence)
        selected.append(f"{sentence} ({candidate['citation']})")

        if len(selected) >= max_sentences:
            break

    return " ".join(selected)