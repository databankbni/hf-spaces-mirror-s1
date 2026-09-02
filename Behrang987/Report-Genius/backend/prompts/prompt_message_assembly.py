"""Assemble LLM message arrays with literature few-shot and CoT protocols."""

from __future__ import annotations

from backend.config import settings
from backend.prompts.prompt_few_shot_examples import FewShotTurn

__all__ = [
    "append_cot_to_system",
    "inject_few_shot_turns",
    "task_user_message",
    "apply_dynamic_literature",
]

_EXHIBIT_FENCE_HEAD = (
    "\n\n<LITERATURE_REFERENCE_EXHIBITS>\n"
    "The following are authoritative RICS surveyor phrasing references retrieved "
    "for this task from the operator literature corpus. They describe OTHER "
    "properties. Use them ONLY to calibrate tone, structure, and professional "
    "register. You MUST NOT import any fact, figure, measurement, date, name, "
    "address, or recommendation from them into your output unless it is "
    "independently supported by the live inputs.\n"
)
_EXHIBIT_FENCE_TAIL = "</LITERATURE_REFERENCE_EXHIBITS>"


def append_cot_to_system(system_content: str, cot_block: str) -> str:
    """Append a CoT protocol block to the system prompt when enabled."""
    if not settings.prompt_chain_of_thought_enabled:
        return system_content
    block = (cot_block or "").strip()
    if not block:
        return system_content
    return f"{system_content.strip()}\n\n{block}"


def inject_few_shot_turns(
    messages: list[dict[str, str]],
    examples: tuple[FewShotTurn, ...] | list[FewShotTurn],
) -> list[dict[str, str]]:
    """Insert user/assistant demonstration turns after the system message.

    The final user message in ``messages`` is treated as the live task.
    """
    if not settings.prompt_literature_few_shot_enabled or not examples:
        return messages
    if not messages or messages[0].get("role") != "system":
        return messages
    out: list[dict[str, str]] = [messages[0]]
    for ex in examples:
        out.append({"role": "user", "content": ex.user.strip()})
        out.append({"role": "assistant", "content": ex.assistant.strip()})
    out.extend(messages[1:])
    return out


def task_user_message(messages: list[dict[str, str]]) -> dict[str, str]:
    """Return the last user message — the live task after any few-shot prefix."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return msg
    raise ValueError("No user message in prompt array")


def _exhibits_block(exhibits: list[str]) -> str:
    items = "\n\n".join(
        f"[Exhibit {i + 1}]\n{e.strip()}" for i, e in enumerate(exhibits) if e.strip()
    )
    if not items:
        return ""
    return f"{_EXHIBIT_FENCE_HEAD}\n{items}\n{_EXHIBIT_FENCE_TAIL}"


def apply_dynamic_literature(
    messages: list[dict[str, str]], *, query: str
) -> list[dict[str, str]]:
    """Augment a prompt with task-relevant literature exemplars (live retrieval).

    Reference exhibits are appended (fenced) to the system message; mined
    draft->edited pairs are inserted as demonstration turns after the system
    message, before any static few-shot and the live task. Gated by
    ``prompt_dynamic_literature_enabled``; a no-op when nothing is retrieved so
    the live user turn always stays last.
    """
    if not settings.prompt_dynamic_literature_enabled:
        return messages
    if not messages or messages[0].get("role") != "system":
        return messages

    # Imported lazily: literature_corpus pulls in embeddings/doc extraction which
    # must not be a hard import dependency of every prompt module.
    from backend.domain.literature_corpus import fetch_exemplars

    selection = fetch_exemplars(query)
    if selection.empty:
        return messages

    out = list(messages)
    block = _exhibits_block(selection.exhibits)
    if block:
        out[0] = {**out[0], "content": out[0]["content"].rstrip() + block}

    if selection.pairs:
        head = [out[0]]
        demos: list[dict[str, str]] = []
        for ex in selection.pairs:
            demos.append({"role": "user", "content": ex.user.strip()})
            demos.append({"role": "assistant", "content": ex.assistant.strip()})
        out = head + demos + out[1:]
    return out
