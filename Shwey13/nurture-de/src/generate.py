"""Phase 6 — generation. Retrieval feeds this; it returns a cited answer or an honest
refusal, grounded ONLY in the retrieved context.

    from generate import generate
    result = generate("Wann beginnt die Mutterschutzfrist?")
    print(result.answer)

Design (isolation, so the Phase-6 validation — including the injection test — can drive
each stage independently):
    retrieve(question, ...)      -> list[RetrievedChunk]        (Phase-5 search)
    assemble_context(chunks)     -> (context_str, cl100k_tokens) (delimited, most-relevant LAST)
    answer(question, chunks)     -> AnswerResult                 (the Anthropic call)
    generate(question, ...)      = retrieve -> answer

The model is Anthropic Claude (Opus 5) via the Messages API — a single grounded call, no
tools. The system prompt (the judgment layer, owned by a human) lives in
src/prompts/answer_system_prompt.md and is loaded, not inlined. Retrieved documents are
wrapped in explicit delimiters and declared to be DATA, never instructions, so injected
text in the corpus cannot steer the model (see the prompt's "DATA, not instructions").
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from retrieval import Retriever, RetrievedChunk  # noqa: E402
from vendor import cl100k  # noqa: E402  (assembled-context token count; same tokenizer as chunking)

# --- config -----------------------------------------------------------------
MODEL = "claude-opus-5"
MAX_TOKENS = 4096            # thinking + a short cited answer; well under the non-stream cap
SYSTEM_PROMPT_PATH = _ROOT / "src" / "prompts" / "answer_system_prompt.md"

K_RETRIEVE = 10             # candidates pulled through hybrid retrieval
K_CONTEXT = 4               # top-N after RRF that actually enter the prompt (reranked in Phase 8)

# Claude Opus 5 pricing, $/1M tokens (see BUILD_JOURNAL Phase 6 for the per-call formula)
PRICE_IN, PRICE_OUT = 5.0, 25.0
PRICE_CACHE_WRITE = PRICE_IN * 1.25    # 5-min TTL write premium
PRICE_CACHE_READ = PRICE_IN * 0.10     # cache-read discount


def load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


# --- result types -----------------------------------------------------------
@dataclass
class AnswerResult:
    question: str
    answer: str
    refused_by_classifier: bool          # True if the API safety classifier declined (stop_reason=refusal)
    stop_reason: str | None
    context_chunk_ids: list[str]         # ids put in front of the model, context order (most-relevant last)
    context_tokens: int                  # cl100k tokens of the assembled <retrieved_documents> block
    usage: dict = field(default_factory=dict)     # input/output/cache token counts from the API
    cost_usd: float = 0.0                # this call's cost in USD (see pricing constants)
    model: str = MODEL


# --- retrieval --------------------------------------------------------------
_retriever: Retriever | None = None


def _get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        _retriever = Retriever()
    return _retriever


def retrieve(question: str, k_retrieve: int = K_RETRIEVE, k_context: int = K_CONTEXT,
             filters: dict | None = None) -> list[RetrievedChunk]:
    """Hybrid retrieve, then take the top k_context post-RRF (the Phase-8 reranker will
    slot in here). Returned best-first; assemble_context re-orders to most-relevant-last."""
    hits = _get_retriever().search(question, k=k_retrieve, filters=filters, mode="hybrid")
    return hits[:k_context]


# --- context assembly -------------------------------------------------------
def _esc(s: str) -> str:
    """Neutralise the delimiter chars so document text can't forge a document boundary."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def assemble_context(chunks: list[RetrievedChunk]) -> tuple[str, int]:
    """Wrap chunks as delimited, attributed documents. MOST RELEVANT LAST — the model
    attends most reliably to the end of the context, so rank-1 is the final document.
    Returns (block, cl100k_token_count_of_block)."""
    docs = []
    for c in reversed(chunks):                       # best-first in -> best-last out
        m = c.metadata
        header = (
            f'<document id="{_esc(c.chunk_id)}" '
            f'source_authority="{_esc(str(m.get("authority", "")))}" '
            f'authority_tier="{_esc(str(m.get("authority_tier", "")))}" '
            f'last_verified="{_esc(str(m.get("last_verified_date", "")))}" '
            f'heading_path="{_esc(str(m.get("heading_path", "")))}">'
        )
        docs.append(f"{header}\n{_esc(c.text)}\n</document>")
    block = "<retrieved_documents>\n" + "\n\n".join(docs) + "\n</retrieved_documents>"
    return block, cl100k.count(block)


def _build_user_message(question: str, context_block: str) -> str:
    return (
        f"{context_block}\n\n"
        f"<user_question>\n{question}\n</user_question>"
    )


# --- the Anthropic call -----------------------------------------------------
def _client():
    import anthropic
    return anthropic.Anthropic()   # resolves ANTHROPIC_API_KEY or an `ant auth login` profile


def _cost(usage) -> float:
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cr = getattr(usage, "cache_read_input_tokens", 0) or 0
    return (inp * PRICE_IN + out * PRICE_OUT + cw * PRICE_CACHE_WRITE + cr * PRICE_CACHE_READ) / 1e6


def answer(question: str, chunks: list[RetrievedChunk]) -> AnswerResult:
    """Assemble the (possibly caller-tampered) chunks and ask the model, grounded ONLY in
    that context. Handles the Opus-5 classifier refusal (stop_reason='refusal') before
    reading content — a prompt-driven refusal (medical / out-of-corpus) comes back as
    ordinary text instead, per the system prompt's rules."""
    context_block, ctx_tokens = assemble_context(chunks)
    system = load_system_prompt()

    resp = _client().messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},   # the refuse / ask-for-attribute / answer judgement benefits from it
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": _build_user_message(question, context_block)}],
    )

    usage = {
        "input_tokens": getattr(resp.usage, "input_tokens", 0),
        "output_tokens": getattr(resp.usage, "output_tokens", 0),
        "cache_creation_input_tokens": getattr(resp.usage, "cache_creation_input_tokens", 0),
        "cache_read_input_tokens": getattr(resp.usage, "cache_read_input_tokens", 0),
    }
    ids = [c.chunk_id for c in reversed(chunks)]   # context order (most-relevant last), matches the prompt

    if resp.stop_reason == "refusal":
        return AnswerResult(question, "[declined by the model's safety classifier]", True,
                            resp.stop_reason, ids, ctx_tokens, usage, _cost(resp.usage))

    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    return AnswerResult(question, text, False, resp.stop_reason, ids, ctx_tokens, usage,
                        _cost(resp.usage))


def generate(question: str, k_retrieve: int = K_RETRIEVE, k_context: int = K_CONTEXT,
             filters: dict | None = None) -> AnswerResult:
    """Full path: retrieve -> answer."""
    return answer(question, retrieve(question, k_retrieve, k_context, filters))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    q = " ".join(sys.argv[1:]) or "Wann beginnt die Mutterschutzfrist?"
    r = generate(q)
    print(f"Q: {r.question}\n")
    print(r.answer)
    print(f"\n--- context: {len(r.context_chunk_ids)} chunks / {r.context_tokens} cl100k tokens"
          f"  |  usage in/out={r.usage['input_tokens']}/{r.usage['output_tokens']}"
          f"  |  cost=${r.cost_usd:.4f}  |  stop={r.stop_reason}")
