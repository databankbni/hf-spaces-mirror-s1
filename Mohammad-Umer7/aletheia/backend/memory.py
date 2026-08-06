"""Thin async wrapper around cognee — the ONLY module that imports cognee.

Import-order constraint: .env must be loaded and storage roots set before any
cognee operation, so configs pick up Groq/fastembed and all databases land in
<repo>/data/ instead of inside site-packages.
"""
from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

load_dotenv(REPO_ROOT / ".env", override=False)

import cognee  # noqa: E402
from cognee import visualize_graph as _visualize_graph  # noqa: E402
from cognee.infrastructure.databases.graph import get_graph_engine  # noqa: E402

DATA_DIR.mkdir(parents=True, exist_ok=True)
cognee.config.system_root_directory(str(DATA_DIR / "cognee_system"))
cognee.config.data_root_directory(str(DATA_DIR / "cognee_data"))

# Groq's free tier rate-limits aggressively and cognee makes many sequential
# LLM calls per ingest, so every operation gets retry + exponential backoff.
_RETRYABLE = ("429", "rate limit", "rate_limit", "too many requests", "503", "overloaded")


async def _with_retry(op_factory, *, what: str, tries: int = 6, base_delay: float = 4.0):
    for attempt in range(1, tries + 1):
        try:
            return await op_factory()
        except Exception as exc:  # provider errors surface as varied types; match on text
            msg = str(exc).lower()
            if attempt == tries or not any(m in msg for m in _RETRYABLE):
                raise
            delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0.0, 1.5)
            print(f"  [retry] {what}: rate-limited (attempt {attempt}/{tries}), backing off {delay:.0f}s")
            await asyncio.sleep(delay)


def entry_text(entry: Any) -> str:
    """recall() returns typed pydantic entries (ResponseQAEntry etc.), not strings."""
    if isinstance(entry, str):
        return entry
    for attr in ("answer", "text", "content", "result", "value", "context"):
        v = getattr(entry, attr, None)
        if isinstance(v, str) and v.strip():
            return v
    if hasattr(entry, "model_dump"):
        try:
            return json.dumps(entry.model_dump(mode="json"), default=str)
        except Exception:
            pass
    return str(entry)


async def remember(text: str, dataset: str, *, session_id: Optional[str] = None) -> Any:
    """Ingest text into a dataset (LLM-heavy, 20-90s). Session variant via session_id."""
    return await _with_retry(
        lambda: cognee.remember(
            text, dataset_name=dataset, session_id=session_id, self_improvement=False
        ),
        what=f"remember[{dataset}]",
    )


async def recall_raw(
    question: str,
    datasets: Optional[list[str]] = None,
    *,
    session_id: Optional[str] = None,
    system_prompt: Optional[str] = None,
) -> list[Any]:
    """Raw typed recall entries — for shape inspection and answer attribution."""
    return await _with_retry(
        lambda: cognee.recall(
            question, datasets=datasets, session_id=session_id, system_prompt=system_prompt
        ),
        what="recall",
    )


async def recall(
    question: str,
    datasets: Optional[list[str]] = None,
    *,
    session_id: Optional[str] = None,
    system_prompt: Optional[str] = None,
) -> list[str]:
    """Query memory scoped to datasets. Returns normalized text results."""
    entries = await recall_raw(question, datasets, session_id=session_id, system_prompt=system_prompt)
    return [entry_text(e) for e in entries]


async def improve(dataset: str, *, session_ids: Optional[list[str]] = None) -> Any:
    """Enrich a dataset; with session_ids, bridge session memory into the permanent graph."""
    return await _with_retry(
        lambda: cognee.improve(dataset=dataset, session_ids=session_ids),
        what=f"improve[{dataset}]",
    )


async def forget_dataset(dataset: str) -> Any:
    return await _with_retry(
        lambda: cognee.forget(dataset=dataset), what=f"forget[{dataset}]"
    )


async def forget_everything() -> Any:
    return await _with_retry(
        lambda: cognee.forget(everything=True), what="forget[everything]"
    )


async def graph_data() -> tuple[list, list]:
    """Raw (nodes, edges) from the graph engine. Shapes vary — normalize downstream."""
    engine = await get_graph_engine()
    return await engine.get_graph_data()


async def write_debug_visualization(path: str, dataset: Optional[str] = None) -> str:
    """Cognee's built-in interactive HTML graph. dataset=None attempts the full graph."""
    return await _visualize_graph(path, dataset=dataset)
