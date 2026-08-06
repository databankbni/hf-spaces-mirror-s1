"""In-app "Ask Claude" chat — the tool-use loop over the read-only MCP tools.

This is the pure logic half of the T4.1b chat sidebar (spec:
``docs/prompts/chat-sidebar.md``). It holds **no Streamlit** so the tool-dispatch
loop is unit-testable with a mocked Anthropic client; the thin UI wiring lives in
``views/chat.py``.

Design:
  - The tools are the *exact same* read-only functions the MCP server registers
    (``mcp/tools.py``). We reuse them directly rather than reimplement any query,
    and we derive the Anthropic tool schemas from the same pydantic input models,
    so the chat and the MCP server can never drift.
  - ``mcp/`` is not a Python package (no ``__init__.py``) and the name ``mcp`` is
    owned by the installed MCP SDK, so we put ``mcp/`` on ``sys.path`` and import
    ``tools`` directly — the same primary import path the MCP entrypoints use.
  - The MCP tool functions call ``connect_ro()`` (from ``mcp/db.py``) with no
    args, which resolves the DB via ``FINDASH_DB_PATH`` first. We set that env var
    to the dashboard's already-resolved ``db_path`` so the tools read the exact
    same DB the app is serving — no re-resolution / HF round-trip.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import sys
import typing
from pathlib import Path
from typing import Any, Callable, Optional

# --- Reuse the MCP server's tool functions + pydantic models -----------------
# Put the (non-package) mcp/ dir on sys.path so `import tools` resolves to
# mcp/tools.py (NOT the installed `mcp` SDK). This mirrors mcp/server.py's own
# primary import path. Also ensure the repo root is importable for tools.py's
# `from lib...`/`from scripts...` imports (it is, when the app runs from root).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_MCP_DIR = _REPO_ROOT / "mcp"
for _p in (str(_REPO_ROOT), str(_MCP_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import tools as _mcp_tools  # noqa: E402  (mcp/tools.py — see sys.path setup above)


# --- Constants (cost control per the spec) -----------------------------------
# The spec picks the current Sonnet tier for this tool-use Q&A surface
# (cost/latency), explicitly rather than the app-wide Opus default.
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 8000          # non-streaming answer ceiling (well under HTTP timeout)
MAX_TURNS = 20             # per-session user turns (UI enforces; constant lives here)
MAX_TOOL_ITERATIONS = 8    # tool-use loops within a single user turn

SYSTEM_PROMPT = """\
You are the in-app research assistant for the Reportal dashboard, which covers \
Georgian companies' annual financial statements.

DATA & SOURCES
- Company financials originate from reportal.ge filings. Insurers are instead \
sourced from the Georgian insurance regulator (insurance.gov.ge) 12-month \
returns. All monetary values are in Georgian Lari (GEL), stated in ABSOLUTE GEL \
(not thousands/millions).
- Headline metrics come from a precomputed panel: Revenue, GrossProfit, EBITDA, \
EBIT, NetProfit, margins (GrossMargin / EBITDAMargin / NetMargin, expressed as \
fractions where 0.138 = 13.8%), balance-sheet aggregates (TotalAssets, \
TotalEquity, TotalDebt, NetDebt), return ratios (ROE, ROA, ROIC, \
NetDebtToEBITDA, AssetTurnover), and ~30 growth/CAGR columns (e.g. Revenue_YoY, \
EBITDA_3yrCAGR, in decimal form). Banks and insurers have EBITDA/EBIT null by \
design.
- "GDP penetration" (a sector's aggregate revenue as a share of Georgia's \
nominal GDP) is a differentiated metric available via \
get_sector_aggregate(gdp_penetration=true) and get_macro_gdp.

HOW TO WORK
- Every company is keyed by a 9-digit IdCode. Turn a name into its IdCode with \
search_companies FIRST. Company names are frequently Georgian — use \
get_company_profile for a plain-English description of what a company does.
- Use the tools to fetch real figures. NEVER invent or estimate numbers. If the \
tools return no data for something, say it is "not in the data" rather than \
guessing.
- Always cite the IdCode and the fiscal year(s) behind any figure you report.
- Honour the data-quality notes the tools return (unit-rescale overrides): if a \
value was ingest-corrected or flagged suspect, surface that caveat instead of \
narrating it as raw fact.
- Be concise and analyst-oriented. Show GEL with thousands separators and render \
fraction metrics as percentages. Prefer a small table for multi-year or \
multi-company answers.
"""


# --- Tool registry derived from mcp/tools.py ---------------------------------

def _build_registry() -> list[tuple[str, Callable, Optional[type]]]:
    """(name, async_fn, input_model|None) for every registered MCP tool.

    Reads ``mcp/tools.py::_TOOLS`` (the same table both MCP entrypoints register)
    so the chat's tool set and ordering can never drift from the server's. The
    single pydantic param model is resolved via ``get_type_hints`` because
    tools.py uses ``from __future__ import annotations`` (annotations are strings).
    """
    registry: list[tuple[str, Callable, Optional[type]]] = []
    for fn, name, _title in _mcp_tools._TOOLS:
        params = list(inspect.signature(fn).parameters)
        model: Optional[type] = None
        if params:
            try:
                hints = typing.get_type_hints(fn)
            except Exception:  # noqa: BLE001 - be defensive; fall back below
                hints = {}
            model = hints.get(params[0])
        registry.append((name, fn, model))
    return registry


_REGISTRY = _build_registry()
_FN_BY_NAME: dict[str, Callable] = {name: fn for name, fn, _ in _REGISTRY}
_MODEL_BY_NAME: dict[str, Optional[type]] = {name: model for name, _, model in _REGISTRY}

_EMPTY_SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}


def anthropic_tools() -> list[dict[str, Any]]:
    """Build the Anthropic ``tools=`` list from the MCP tool registry.

    Each tool's description is the source function's docstring; the input schema
    is the pydantic model's JSON schema (rich field descriptions + constraints
    included), or an empty-object schema for the no-arg tools.
    """
    out: list[dict[str, Any]] = []
    for name, fn, model in _REGISTRY:
        description = inspect.getdoc(fn) or ""
        if model is not None:
            schema = model.model_json_schema()
            schema.setdefault("type", "object")
            schema.setdefault("additionalProperties", False)
            input_schema = schema
        else:
            input_schema = dict(_EMPTY_SCHEMA)
        out.append({
            "name": name,
            "description": description,
            "input_schema": input_schema,
        })
    return out


def _run_async(coro: Any) -> Any:
    """Run one tool coroutine to completion from Streamlit's sync context."""
    return asyncio.run(coro)


def dispatch_tool(name: str, tool_input: dict[str, Any] | None) -> str:
    """Execute one MCP tool by name and return its JSON-string result.

    Reconstructs the pydantic input model from ``tool_input`` (Claude's tool-call
    arguments) and awaits the async tool function. Errors are returned as a JSON
    ``{"error": ...}`` payload (never raised) so the loop can feed them back to
    the model as an ``is_error`` tool result and let it recover.
    """
    fn = _FN_BY_NAME.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool '{name}'"}, ensure_ascii=False)
    model = _MODEL_BY_NAME.get(name)
    try:
        if model is not None:
            params = model(**(tool_input or {}))
            return _run_async(fn(params))
        return _run_async(fn())
    except Exception as e:  # noqa: BLE001 - surface to the model, don't crash the app
        return json.dumps(
            {"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False
        )


# --- The turn loop -----------------------------------------------------------

def _make_client(api_key: str):
    import anthropic

    return anthropic.Anthropic(api_key=api_key)


def run_chat_turn(
    history: list[dict[str, str]],
    user_message: str,
    *,
    api_key: str,
    db_path: str,
    client: Any = None,
    model: str = MODEL,
    max_tool_iterations: int = MAX_TOOL_ITERATIONS,
) -> tuple[str, list[str]]:
    """Run one assistant turn (with tool use) and return (answer_text, tool_names).

    ``history`` is the prior display history — a list of ``{"role", "content"}``
    dicts with plain-text content (user questions + prior assistant answers). The
    per-turn tool-use blocks are kept only in the local message list, not
    persisted into ``history`` (v1: prior tool outputs don't carry across turns —
    the assistant's own summaries provide the continuity, which keeps cost down).

    ``client`` is injectable so tests can pass a fake Anthropic client (the loop
    must be testable without hitting the API).
    """
    # Point the MCP tools at the dashboard's already-resolved DB (no HF re-check).
    os.environ["FINDASH_DB_PATH"] = db_path

    if client is None:
        client = _make_client(api_key)

    messages: list[dict[str, Any]] = [
        {"role": h["role"], "content": h["content"]} for h in history
    ]
    messages.append({"role": "user", "content": user_message})

    tools = anthropic_tools()
    tool_names: list[str] = []
    answer = ""

    for _ in range(max_tool_iterations):
        resp = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        )
        # Preserve the assistant's full content (text + tool_use blocks) for the
        # next request — required for tool-use continuity.
        messages.append({"role": "assistant", "content": resp.content})

        text = "".join(
            getattr(b, "text", "") for b in resp.content
            if getattr(b, "type", None) == "text"
        ).strip()
        if text:
            answer = text

        tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        if getattr(resp, "stop_reason", None) != "tool_use" or not tool_uses:
            return answer, tool_names

        tool_results = []
        for tu in tool_uses:
            result = dispatch_tool(tu.name, tu.input)
            tool_names.append(tu.name)
            is_error = result.lstrip().startswith('{"error"')
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": result,
                "is_error": is_error,
            })
        messages.append({"role": "user", "content": tool_results})

    # Ran out of tool-use iterations without a natural stop.
    if not answer:
        answer = (
            "I reached the tool-use limit for this question before I could finish. "
            "Try narrowing it (a specific company, sector, or year)."
        )
    return answer, tool_names
