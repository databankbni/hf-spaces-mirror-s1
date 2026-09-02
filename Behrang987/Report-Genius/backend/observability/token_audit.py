"""Tiktoken-based token counting for embedder / reranker / chat-prompt audits.

Uses ``cl100k_base`` (same encoding as the app stack prompt builder). jina-
embeddings-v3 and jina-reranker-v3 use an XLM-RoBERTa tokenizer internally, so
these counts are an **audit proxy** — good for comparing relative payload size,
spotting truncation risk, and tracking regressions. They will not match the
model tokenizer exactly.

``summarize_chat_messages`` audits the full chat ``messages`` array sent to the
LLM (system rules + user turn that includes retrieved standard paragraphs).

Best-effort only: if tiktoken is missing, counts fall back to a whitespace
word estimate so retrieval never breaks.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import TypedDict

logger = logging.getLogger(__name__)

ENCODING_NAME = "cl100k_base"


class TextTokenSummary(TypedDict):
    chars: int
    tokens: int


class EmbedderFeedSummary(TextTokenSummary):
    max_seq_length: int
    would_truncate: bool


class RerankerFeedSummary(TypedDict):
    full_chars: int
    full_tokens: int
    fed_chars: int
    fed_tokens: int
    doc_chars_cap: int


@lru_cache(maxsize=1)
def _encoding():
    import tiktoken

    return tiktoken.get_encoding(ENCODING_NAME)


def count_tokens(text: str) -> int:
    """Return tiktoken token count for ``text`` (0 for empty)."""
    raw = text or ""
    if not raw.strip():
        return 0
    try:
        return len(_encoding().encode(raw))
    except Exception:  # noqa: BLE001 - audit helper must not break callers
        logger.debug("tiktoken encode failed; using word fallback", exc_info=True)
        return max(1, len(raw.split()))


def summarize_text(text: str) -> TextTokenSummary:
    raw = text or ""
    return {"chars": len(raw), "tokens": count_tokens(raw)}


class ChatMessageTokenSummary(TypedDict):
    role: str
    chars: int
    tokens: int


class ChatMessagesTokenAudit(TypedDict):
    """Tiktoken audit of a chat ``messages`` array sent to the LLM."""

    encoding: str
    message_count: int
    total_chars: int
    total_tokens: int
    by_role: dict[str, TextTokenSummary]
    messages: list[ChatMessageTokenSummary]


def summarize_chat_messages(
    messages: list[dict] | None,
) -> ChatMessagesTokenAudit:
    """Count tokens in the final chat payload (system + user + any other turns).

    Uses ``cl100k_base`` as an audit proxy for prompt size when standard
    paragraphs (and other context) are woven into the messages sent to the LLM.
    Does not include completion / max_tokens budget.
    """
    by_role: dict[str, TextTokenSummary] = {}
    per_message: list[ChatMessageTokenSummary] = []
    total_chars = 0
    total_tokens = 0

    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "unknown").strip() or "unknown"
        content = msg.get("content")
        if isinstance(content, list):
            # Vision / multi-part: count text parts only.
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(str(part.get("text") or ""))
                elif isinstance(part, str):
                    parts.append(part)
            text = "\n".join(parts)
        else:
            text = str(content or "")
        summary = summarize_text(text)
        per_message.append(
            {"role": role, "chars": summary["chars"], "tokens": summary["tokens"]}
        )
        total_chars += summary["chars"]
        total_tokens += summary["tokens"]
        existing = by_role.get(role)
        if existing is None:
            by_role[role] = {"chars": summary["chars"], "tokens": summary["tokens"]}
        else:
            by_role[role] = {
                "chars": existing["chars"] + summary["chars"],
                "tokens": existing["tokens"] + summary["tokens"],
            }

    return {
        "encoding": ENCODING_NAME,
        "message_count": len(per_message),
        "total_chars": total_chars,
        "total_tokens": total_tokens,
        "by_role": by_role,
        "messages": per_message,
    }


def summarize_embedder_feed(text: str, *, max_seq_length: int) -> EmbedderFeedSummary:
    """Summarize text as fed to the local embedder (truncated at ``max_seq_length``)."""
    base = summarize_text(text)
    cap = max(0, int(max_seq_length or 0))
    would_truncate = bool(cap and base["tokens"] > cap)
    return {
        **base,
        "max_seq_length": cap,
        "would_truncate": would_truncate,
    }


def reranker_fed_text(text: str, *, doc_chars_cap: int) -> str:
    """Text slice actually passed to jina-reranker-v3 (char cap, not token cap)."""
    cap = max(0, int(doc_chars_cap or 0))
    raw = text or ""
    return raw if not cap else raw[:cap]


def summarize_reranker_feed(text: str, *, doc_chars_cap: int) -> RerankerFeedSummary:
    """Full chunk vs char-capped payload fed to the reranker."""
    fed = reranker_fed_text(text, doc_chars_cap=doc_chars_cap)
    full = summarize_text(text)
    fed_summary = summarize_text(fed)
    return {
        "full_chars": full["chars"],
        "full_tokens": full["tokens"],
        "fed_chars": fed_summary["chars"],
        "fed_tokens": fed_summary["tokens"],
        "doc_chars_cap": int(doc_chars_cap or 0),
    }
