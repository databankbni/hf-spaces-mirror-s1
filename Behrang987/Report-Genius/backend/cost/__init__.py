"""Per-tenant cost metering for LlamaParse, embeddings, and LLM calls.

Public API — prefer the recorders; ``tenant_scope`` binds attribution at
ingest / generate entry points so nested wrappers need no ``tenant_id`` arg.
"""

from __future__ import annotations

from backend.cost.models import CostEvent
from backend.cost.recorder import (
    record_embedding_cost,
    record_llm_cost,
    record_parse_cost,
    resolve_tenant_id,
    tenant_scope,
)

__all__ = [
    "CostEvent",
    "record_embedding_cost",
    "record_llm_cost",
    "record_parse_cost",
    "resolve_tenant_id",
    "tenant_scope",
]
