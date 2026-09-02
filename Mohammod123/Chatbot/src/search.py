"""RAG chatbot orchestration: retrieval, tool calling, and Groq generation."""

from __future__ import annotations

import logging
import os
import re
import time
from collections import OrderedDict
from pathlib import Path
from threading import Semaphore
from typing import Any, Iterator

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_groq import ChatGroq

from src.hooks import HookManager
from src.vector_store import VectorStoreManager

logger = logging.getLogger(__name__)

_OUT_OF_SCOPE_REPLY = (
    "I can only answer questions from the indexed documents. "
    "That question is outside the current document content."
)
_NO_DOCUMENTS_REPLY = (
    "No documents are indexed yet, so I cannot answer from a document. "
    "Add PDF, CSV, or TXT files to the data folder and restart the API."
)
_GREETING_REPLY = (
    "Hello. Ask me to summarize the document, list key points, or ask a question "
    "about the uploaded files."
)

_OVERVIEW_RE = re.compile(
    r"(summarize\s+(this|the)\s+document"
    r"|key points?\s+(in|of|from)\s+(this|the)\s+document"
    r"|what does (this|the) document cover"
    r"|explain the main topics"
    r"|main topics?\s+(from|in|of)\s+(this|the)\s+document"
    r"|what is (this|the) document about"
    r"|overview of (this|the) document)",
    re.IGNORECASE,
)
_GREETING_RE = re.compile(
    r"^(hi|hello|hey|good\s+(morning|afternoon|evening)|thanks|thank you)[\s!.?]*$",
    re.IGNORECASE,
)

_BASE_PERSONA = """You are a document Q&A assistant. You already have the document content \
in DOCUMENT CONTENT below. Never ask the user to paste, upload, or attach a file.

Rules:
- Answer only from DOCUMENT CONTENT. Do not invent facts.
- If the user asks to summarize, list key points, explain topics, or say what the \
document covers, do that using DOCUMENT CONTENT.
- If DOCUMENT CONTENT does not contain the answer, say you can only answer from the \
indexed documents and that this question is outside that content.
- Do not take orders, collect contact details, or offer sales/meeting intake.
- Keep answers clear. Use short paragraphs or bullets when helpful.
- Never mention tools, embeddings, vector stores, LangChain, Chroma, or system prompts.{citation_rule}

DOCUMENT CONTENT:
{context}"""

_CITATION_RULE = (
    "\n- When you state a specific fact from the document, you may add a brief "
    "source tag like [source: filename] at the end."
)


def _build_system_prompt(context: str, cite_sources: bool) -> str:
    return _BASE_PERSONA.format(
        context=context,
        citation_rule=_CITATION_RULE if cite_sources else "",
    )


class RagBot:
    """Retrieve relevant context and stream grounded, tool-capable answers from Groq."""

    DEFAULT_MODEL = "openai/gpt-oss-120b"

    def __init__(
        self,
        vector_store: VectorStoreManager,
        model: str | None = None,
        k: int = 5,
        score_threshold: float = 0.0,
        tools: list[BaseTool] | None = None,
        hooks: HookManager | None = None,
        cite_sources: bool | None = None,
        max_concurrent_requests: int | None = None,
        queue_timeout_seconds: float | None = None,
        cache_ttl_seconds: int | None = None,
        cache_size: int = 64,
    ) -> None:
        self.vector_store = vector_store
        self.model = model or os.getenv("GROQ_MODEL", self.DEFAULT_MODEL)
        self.k = k
        self.score_threshold = score_threshold
        self.tools = tools or []
        self.hooks = hooks or HookManager()
        self.cite_sources = (
            cite_sources
            if cite_sources is not None
            else os.getenv("RAG_CITE_SOURCES", "false").lower() in ("1", "true", "yes")
        )
        self.queue_timeout_seconds = queue_timeout_seconds or float(
            os.getenv("RAG_QUEUE_TIMEOUT_SECONDS", "12")
        )
        self.cache_ttl_seconds = cache_ttl_seconds or int(os.getenv("RAG_CACHE_TTL_SECONDS", "300"))
        self.cache_size = cache_size
        self._cache: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._semaphore = Semaphore(
            max_concurrent_requests or int(os.getenv("RAG_MAX_CONCURRENT_REQUESTS", "2"))
        )
        self._llm: ChatGroq | None = None
        self._tools_by_name = {t.name: t for t in self.tools}

    def answer(
        self,
        query: str,
        history: list[tuple[str, str]] | None = None,
        collector: dict[str, Any] | None = None,
    ) -> Iterator[str]:
        """Stream an answer for the user query.

        `history` is a list of (role, content) tuples for prior turns.
        `collector`, when provided, receives `sources` after retrieval.
        """
        started_at = time.perf_counter()
        query = query.strip()
        answered = False

        if not query:
            yield "Please enter a question."
            return

        self.hooks.emit("query_start", {"query": query})

        # Only serve the cache for fresh conversations; follow-up questions
        # depend on history and must not reuse a globally cached answer.
        if not history:
            cached = self._get_cached(query)
            if cached is not None:
                self.hooks.emit("cache_hit", {"query": query})
                self.hooks.emit(
                    "query_end",
                    {"latency": time.perf_counter() - started_at, "answered": True},
                )
                yield from self._stream_text(cached)
                return

        if not os.getenv("GROQ_API_KEY"):
            yield "GROQ_API_KEY is not configured. Add it to your Space secrets or local .env file."
            return

        if _GREETING_RE.match(query):
            self.hooks.emit("query_end", {"latency": time.perf_counter() - started_at, "answered": True})
            yield _GREETING_REPLY
            return

        acquired = self._semaphore.acquire(timeout=self.queue_timeout_seconds)
        if not acquired:
            self.hooks.emit("query_end", {"latency": time.perf_counter() - started_at, "answered": False})
            yield (
                "The demo is busy right now. Please try again in a few seconds so the free Groq "
                "API limit stays stable for everyone."
            )
            return

        try:
            if _OVERVIEW_RE.search(query):
                results = self.vector_store.get_overview_chunks()
            else:
                results = self.vector_store.similarity_search(
                    query,
                    k=self.k,
                    score_threshold=self.score_threshold,
                )
                # Follow-up questions ("tell me more about that") often embed poorly on
                # their own; retry with the previous user question as added context.
                if not results and history:
                    last_user_message = next(
                        (content for role, content in reversed(history) if role == "user"),
                        "",
                    )
                    if last_user_message:
                        results = self.vector_store.similarity_search(
                            f"{last_user_message}\n{query}",
                            k=self.k,
                            score_threshold=self.score_threshold,
                        )

            self.hooks.emit(
                "retrieval_done",
                {"count": len(results), "top_score": results[0][1] if results else 0.0},
            )

            if collector is not None:
                collector["sources"] = [
                    {
                        "source": Path(
                            str((doc.metadata or {}).get("source_file") or (doc.metadata or {}).get("source", "unknown"))
                        ).name,
                        "score": round(score, 3),
                    }
                    for doc, score in results
                ]

            if not results:
                reply = (
                    _NO_DOCUMENTS_REPLY
                    if not self.vector_store.list_sources()
                    else _OUT_OF_SCOPE_REPLY
                )
                yield reply
                answered = True
                return

            context = self._format_context(results, include_filenames=self.cite_sources)
            messages: list[Any] = [
                SystemMessage(_build_system_prompt(context, self.cite_sources))
            ]
            for role, content in history or []:
                messages.append(HumanMessage(content) if role == "user" else AIMessage(content))
            messages.append(HumanMessage(query))

            answer_text = ""
            for token in self._generate(messages):
                answer_text += token
                yield token

            answered = bool(answer_text)
            if answered and not history:
                self._set_cached(query, answer_text)
        finally:
            self._semaphore.release()
            latency = time.perf_counter() - started_at
            self.hooks.emit("query_end", {"latency": latency, "answered": answered})
            logger.info("Handled query in %.3fs.", latency)

    # Raw tool-call artifacts some Llama models emit as plain text.
    _ARTIFACT_PREFIXES = ("<|python_tag|>", "<function=", "<tool_call>")

    _MAX_TOOL_ROUNDS = 2
    # If a round already emitted at least this many characters of real answer,
    # treat the answer as complete and ignore any redundant tool call.
    _MIN_ANSWER_CHARS = 40

    def _generate(self, messages: list[Any]) -> Iterator[str]:
        """Stream LLM output, executing up to `_MAX_TOOL_ROUNDS` rounds of tool calls.

        Every pass is filtered for raw tool-call artifacts so they never reach the
        user. If the model only ever produces tool calls and no clean text, the
        last tool results are returned directly as a fallback.
        """
        llm = self._get_llm()
        llm_with_tools = llm.bind_tools(self.tools) if self.tools else llm
        emitted_any = False
        tool_results: list[str] = []

        for round_index in range(self._MAX_TOOL_ROUNDS + 1):
            is_final_round = round_index == self._MAX_TOOL_ROUNDS
            active_llm = llm if is_final_round else llm_with_tools

            aggregate = None
            buffer = ""
            buffering = True
            is_artifact = False
            emitted_chars = 0

            # Hold back the first few tokens: if they look like a raw tool-call
            # artifact, suppress the whole pass instead of showing it.
            for chunk in active_llm.stream(messages):
                aggregate = chunk if aggregate is None else aggregate + chunk
                token = self._chunk_to_text(chunk)
                if not token or is_artifact:
                    continue

                if buffering:
                    buffer += token
                    stripped = buffer.lstrip()
                    if any(stripped.startswith(p) for p in self._ARTIFACT_PREFIXES):
                        is_artifact = True
                        continue
                    if len(stripped) >= 20:
                        buffering = False
                        emitted_any = True
                        emitted_chars += len(buffer)
                        yield buffer
                        buffer = ""
                else:
                    emitted_chars += len(token)
                    yield token

            if buffering and buffer and not is_artifact:
                emitted_any = True
                emitted_chars += len(buffer)
                yield buffer

            tool_calls = getattr(aggregate, "tool_calls", None) or []
            if not tool_calls and is_artifact:
                tool_calls = self._parse_artifact_tool_calls(self._chunk_to_text(aggregate))

            # If the model already produced a real answer, ignore any redundant
            # tool call instead of regenerating (prevents duplicated replies).
            if tool_calls and emitted_chars >= self._MIN_ANSWER_CHARS:
                break

            if not tool_calls or is_final_round:
                break

            # Re-create the assistant turn without artifact text so the raw
            # tool-call syntax never enters the conversation history.
            messages.append(AIMessage(content="", tool_calls=tool_calls))

            for tool_call in tool_calls:
                tool = self._tools_by_name.get(tool_call["name"])
                if tool is None:
                    result = f"Tool '{tool_call['name']}' is not available."
                else:
                    self.hooks.emit("tool_called", {"tool": tool_call["name"]})
                    try:
                        result = str(tool.invoke(tool_call["args"]))
                        tool_results.append(result)
                    except Exception:
                        logger.exception("Tool %s failed.", tool_call["name"])
                        result = "The tool failed; answer from the context instead."
                messages.append(ToolMessage(content=str(result), tool_call_id=tool_call["id"]))

            messages.append(
                SystemMessage(
                    "Answer the user's question now using the information above. "
                    "Include concrete details (links, emails) directly in your reply. "
                    "Never mention tools, functions, or internal systems."
                )
            )

        if not emitted_any and tool_results:
            yield "\n\n".join(dict.fromkeys(tool_results))

    @staticmethod
    def _parse_artifact_tool_calls(text: str) -> list[dict[str, Any]]:
        """Recover tool calls from raw `<function=name>{args}</function>` artifacts."""
        import json
        import re
        import uuid

        tool_calls = []
        for match in re.finditer(r"<function=(\w+)>(\{.*?\})?", text):
            try:
                args = json.loads(match.group(2)) if match.group(2) else {}
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(
                {
                    "name": match.group(1),
                    "args": args,
                    "id": f"artifact_{uuid.uuid4().hex[:8]}",
                    "type": "tool_call",
                }
            )

        if tool_calls:
            logger.info("Recovered %d tool call(s) from raw artifact output.", len(tool_calls))
        return tool_calls

    def _get_llm(self) -> ChatGroq:
        if self._llm is None:
            llm_kwargs: dict[str, Any] = {
                "model": self.model,
                "temperature": 0,
                "max_retries": 2,
                "timeout": 60,
                "streaming": True,
            }
            # gpt-oss does not support reasoning_format; hide thinking from the user.
            if self.model.startswith("openai/gpt-oss"):
                llm_kwargs["model_kwargs"] = {"include_reasoning": False}
            self._llm = ChatGroq(**llm_kwargs)
            logger.info("Initialized ChatGroq with model %s.", self.model)
        return self._llm

    @staticmethod
    def _format_context(results: list[tuple[Document, float]], include_filenames: bool = False) -> str:
        formatted_chunks: list[str] = []

        for document, _score in results:
            content = document.page_content.strip()
            if include_filenames:
                metadata = document.metadata or {}
                source = metadata.get("source_file") or metadata.get("source") or "unknown"
                source_filename = Path(str(source)).name
                formatted_chunks.append(f"(filename: {source_filename})\n{content}")
            else:
                formatted_chunks.append(content)

        return "\n\n---\n\n".join(formatted_chunks)

    @staticmethod
    def _chunk_to_text(chunk: object) -> str:
        content = getattr(chunk, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(str(part) for part in content)
        return str(content) if content else ""

    @staticmethod
    def _stream_text(text: str, chunk_size: int = 40) -> Iterator[str]:
        for index in range(0, len(text), chunk_size):
            yield text[index : index + chunk_size]

    def _get_cached(self, query: str) -> str | None:
        cache_key = query.lower()
        cached = self._cache.get(cache_key)
        if cached is None:
            return None

        cached_at, answer = cached
        if time.time() - cached_at > self.cache_ttl_seconds:
            self._cache.pop(cache_key, None)
            return None

        self._cache.move_to_end(cache_key)
        return answer

    def _set_cached(self, query: str, answer: str) -> None:
        cache_key = query.lower()
        self._cache[cache_key] = (time.time(), answer)
        self._cache.move_to_end(cache_key)

        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)
