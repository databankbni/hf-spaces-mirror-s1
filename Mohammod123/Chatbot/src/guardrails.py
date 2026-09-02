"""Input and output guardrails for the customer-facing chatbot."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class GuardrailVerdict:
    allowed: bool
    reason: str = ""
    user_message: str = ""


class Guardrails:
    """Lightweight, dependency-free guardrails.

    Input: blocks empty/oversized queries and common prompt-injection attempts.
    Output: redacts anything that looks like an API key or secret.
    """

    MAX_QUERY_CHARS = 2000

    _INJECTION_PATTERNS = [
        r"ignore\s+(all|any|the|previous|prior|above)\s+(instructions|prompts|rules)",
        r"disregard\s+(all|any|the|previous|prior|above)\s+(instructions|prompts|rules)",
        r"reveal\s+(your|the)\s+(system\s+prompt|instructions|rules)",
        r"(show|print|repeat)\s+(your|the)\s+system\s+prompt",
        r"you\s+are\s+now\s+(?!answering)",
        r"pretend\s+(to\s+be|you\s+are)",
        r"jailbreak",
        r"developer\s+mode",
        r"\bDAN\s+mode\b",
    ]

    _SECRET_PATTERNS = [
        r"gsk_[A-Za-z0-9]{16,}",          # Groq API keys
        r"sk-[A-Za-z0-9\-_]{16,}",        # OpenAI-style keys
        r"hf_[A-Za-z0-9]{16,}",           # Hugging Face tokens
        r"(?i)api[_\s-]?key\s*[:=]\s*\S+",
    ]

    # Strip anything that reveals backend / tool / RAG internals.
    _INTERNAL_LEAK_PATTERNS = [
        r"list_knowledge_base_documents",
        r"get_contact_and_ordering_info",
        r"<\|python_tag\|>.*?(?:</function>|$)",
        r"<function=\w+>.*?(?:</function>|$)",
        r"</function>",
        r"\busing the [\w_]+ function\b",
        r"search our knowledge base using[^.!\n]*[.!]?",
        r"\btool_call\b",
        r"\bLangChain\b",
        r"\bChroma(?:DB)?\b",
        r"\bvector store\b",
        r"\bRAG pipeline\b",
        r"\bembedding(?:s)? model\b",
        r"\bsystem prompt\b",
        r"\bKNOWLEDGE section\b",
    ]

    def __init__(self) -> None:
        self._injection_re = [re.compile(p, re.IGNORECASE) for p in self._INJECTION_PATTERNS]
        self._secret_re = [re.compile(p) for p in self._SECRET_PATTERNS]
        self._internal_leak_re = [
            re.compile(p, re.IGNORECASE | re.DOTALL) for p in self._INTERNAL_LEAK_PATTERNS
        ]

    def check_input(self, query: str) -> GuardrailVerdict:
        """Validate the user query before it reaches retrieval/LLM."""
        stripped = query.strip()

        if not stripped:
            return GuardrailVerdict(
                allowed=False,
                reason="empty_query",
                user_message="Please type a question so I can help you.",
            )

        if len(stripped) > self.MAX_QUERY_CHARS:
            return GuardrailVerdict(
                allowed=False,
                reason="query_too_long",
                user_message=(
                    f"Your message is too long (max {self.MAX_QUERY_CHARS} characters). "
                    "Please shorten it and try again."
                ),
            )

        for pattern in self._injection_re:
            if pattern.search(stripped):
                logger.warning("Guardrails blocked query (pattern: %s).", pattern.pattern)
                return GuardrailVerdict(
                    allowed=False,
                    reason="prompt_injection",
                    user_message=(
                        "I can only help with questions about AllOfTech and its services. "
                        "How can I assist you with that?"
                    ),
                )

        return GuardrailVerdict(allowed=True)

    def sanitize_output(self, text: str) -> str:
        """Redact secrets and strip internal backend/tool leaks from model output."""
        for pattern in self._internal_leak_re:
            text = pattern.sub("", text)

        for pattern in self._secret_re:
            text = pattern.sub("[REDACTED]", text)

        # Collapse awkward gaps left after stripping internal phrases, but do
        # not strip leading/trailing whitespace here. Streaming responses are
        # delivered in small chunks, and stripping each chunk glues words
        # together in the frontend.
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text
