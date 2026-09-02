"""Cost event payload written to the per-tenant ledger."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class CostEvent:
    """One billable (or explicitly free) external call attributed to a tenant.

    Never store prompt/completion text, filenames beyond ``document_id``, or
    API keys in this record.
    """

    ts: str
    tenant_id: str
    provider: str  # openai | gemini | llamaparse | textract | local
    category: str  # llm | embedding | parse
    model_or_tier: str
    units: float
    unit_kind: str  # tokens | pages
    cost_usd: float
    priced: bool
    label: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    credits: float = 0.0
    pages: int = 0
    pages_source: str = ""  # pdf | api | ""
    priced_assumed: bool = False
    engine: str = ""
    report_id: str = ""
    document_id: str = ""
    section_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if not d.get("extra"):
            d.pop("extra", None)
        return d
