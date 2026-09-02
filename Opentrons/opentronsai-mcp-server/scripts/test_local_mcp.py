#!/usr/bin/env python3
"""Positive and negative smoke tests against a live local Gradio MCP server.

Prereq:
  make local-run
  ANTHROPIC_API_KEY set in .env (needed for generate_protocol / docs lookup)
  HUGGINGFACE_API_KEY set in .env (needed for simulate_protocol / until-simulates)

Usage:
  uv run python scripts/test_local_mcp.py
  uv run python scripts/test_local_mcp.py --base-url http://127.0.0.1:7861
  uv run python scripts/test_local_mcp.py --generate-until-simulates
  make test-local-mcp
  make test-generate-until-simulates
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "http://127.0.0.1:7860"
MCP_PATH = "/gradio_api/mcp/"
DOCS_QUERY = "thermocycler module on Flex"
DEFAULT_MAX_SIMULATE_ATTEMPTS = 3
# Queries chosen so generated <about> text should steer file selection.
# Covers modules plus instruction themes also represented in storage/docs/.
# Prefer natural-language questions over API method names.
ABOUT_GUIDED_CASES = (
    (
        "thermocycler",
        "How do I run a PCR temperature profile on the Thermocycler and control the lid heat?",
        ("modules/thermocycler.md",),
    ),
    (
        "flex stacker",
        "How do I set up a Flex Stacker and pull a plate or tip rack out of it during a protocol?",
        ("modules/flex-stacker.md",),
    ),
    (
        "liquid classes",
        "How do I transfer watery liquids on Flex using Opentrons verified liquid handling settings?",
        ("liquid-classes.md",),
    ),
    (
        "runtime parameters",
        "How do I let a technician choose sample count, a yes/no option, and upload a CSV when starting a run?",
        ("runtime-parameters/defining.md",),
    ),
    (
        "ot2 to flex",
        "What do I need to change to make my OT-2 protocol work on a Flex robot?",
        ("adapting-ot2-flex.md",),
    ),
    (
        "partial tip pickup",
        "How can a 96-channel pipette pick up only one column of tips instead of the full rack?",
        ("pipettes/partial-tip-pickup.md",),
    ),
    (
        "moving labware",
        "How does the Flex gripper move a plate from one deck slot to another in a protocol?",
        ("moving-labware.md",),
    ),
)
PROTOCOL_PROMPT = (
    "Write a minimal Flex protocol that loads a tip rack in D1, "
    "a nest_96_wellplate_200ul_flat in D2, a flex_1channel_1000 on the left, "
    "and transfers 50uL from A1 to A2. Keep it short."
)
PYTHON_FENCE_RE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


@dataclass
class CaseResult:
    name: str
    ok: bool
    detail: str


def mcp_url(base_url: str) -> str:
    return base_url.rstrip("/") + MCP_PATH


def parse_sse_json(body: str) -> Any:
    for line in body.splitlines():
        if line.startswith("data:"):
            payload = line[len("data:") :].strip()
            if payload:
                return json.loads(payload)
    raise RuntimeError(f"No SSE data payload in response:\n{body[:500]}")


def rpc_raw(
    base_url: str,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    req_id: int = 1,
    timeout: float = 180,
) -> dict[str, Any]:
    """Return the full JSON-RPC message (result or error)."""
    payload = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": method,
        "params": params or {},
    }
    request = Request(
        mcp_url(base_url),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from MCP: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(
            f"Could not reach MCP at {mcp_url(base_url)}. Is `make local-run` up?\n{exc}"
        ) from exc
    return parse_sse_json(body)


def tool_text(message: dict[str, Any]) -> str:
    result = message.get("result") or {}
    chunks: list[str] = []
    for block in result.get("content") or []:
        if block.get("type") == "text":
            chunks.append(block.get("text") or "")
    return "".join(chunks)


def run_case(name: str, fn: Callable[[], str]) -> CaseResult:
    try:
        detail = fn()
        print(f"PASS  {name}: {detail}")
        return CaseResult(name=name, ok=True, detail=detail)
    except Exception as exc:
        print(f"FAIL  {name}: {exc}")
        return CaseResult(name=name, ok=False, detail=str(exc))


def case_initialize(base_url: str) -> str:
    message = rpc_raw(
        base_url,
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test_local_mcp", "version": "0.1"},
        },
        req_id=1,
    )
    if "error" in message:
        raise RuntimeError(message["error"])
    server = (message.get("result") or {}).get("serverInfo") or {}
    name = server.get("name") or ""
    if "Opentrons" not in name:
        raise RuntimeError(f"Unexpected serverInfo: {server}")
    return f"server={name}"


def case_tools_list(base_url: str) -> str:
    message = rpc_raw(base_url, "tools/list", {}, req_id=2)
    if "error" in message:
        raise RuntimeError(message["error"])
    tools = [tool["name"] for tool in (message.get("result") or {}).get("tools", [])]
    expected = {"generate_protocol", "simulate_protocol", "get_relevant_api_docs"}
    missing = expected - set(tools)
    if missing:
        raise RuntimeError(f"Missing tools: {sorted(missing)}; got {tools}")
    return f"tools={tools}"


def case_docs_positive(base_url: str, query: str) -> str:
    message = rpc_raw(
        base_url,
        "tools/call",
        {"name": "get_relevant_api_docs", "arguments": {"query": query}},
        req_id=3,
        timeout=120,
    )
    if "error" in message:
        raise RuntimeError(message["error"])
    if (message.get("result") or {}).get("isError"):
        raise RuntimeError(tool_text(message))
    text = tool_text(message)
    if "<relevant_file_content>" not in text or "<file " not in text:
        raise RuntimeError(f"Expected file-backed docs response, got:\n{text[:400]}")
    if ".md" not in text:
        raise RuntimeError("Expected MkDocs .md paths in docs response")
    return f"files={text.count('<file ')}"


def case_docs_about_guides_query(base_url: str, query: str, expected_files: tuple[str, ...]) -> str:
    """Assert generated <about> routing selects the expected API doc file(s)."""
    message = rpc_raw(
        base_url,
        "tools/call",
        {"name": "get_relevant_api_docs", "arguments": {"query": query}},
        req_id=30,
        timeout=120,
    )
    if "error" in message:
        raise RuntimeError(message["error"])
    if (message.get("result") or {}).get("isError"):
        raise RuntimeError(tool_text(message))
    text = tool_text(message)
    missing = [path for path in expected_files if f"name='{path}'" not in text and f'name="{path}"' not in text]
    if missing:
        raise RuntimeError(
            "About-guided docs lookup missed expected file(s) "
            f"{missing} for query={query!r}. Response preview:\n{text[:600]}"
        )
    return f"matched={list(expected_files)} files={text.count('<file ')}"


def case_docs_negative_empty_query(base_url: str) -> str:
    message = rpc_raw(
        base_url,
        "tools/call",
        {"name": "get_relevant_api_docs", "arguments": {"query": ""}},
        req_id=4,
        timeout=60,
    )
    if "error" in message:
        raise RuntimeError(message["error"])
    text = tool_text(message)
    if "No query provided" not in text:
        raise RuntimeError(f"Expected empty-query error text, got:\n{text[:400]}")
    return "rejected empty query"


def case_unknown_tool_negative(base_url: str) -> str:
    message = rpc_raw(
        base_url,
        "tools/call",
        {"name": "not_a_real_tool", "arguments": {}},
        req_id=5,
        timeout=30,
    )
    if "error" in message:
        # JSON-RPC error is also acceptable for unknown tools
        return f"rpc error={message['error']}"
    result = message.get("result") or {}
    text = tool_text(message)
    if not result.get("isError") and "Unknown tool" not in text:
        raise RuntimeError(f"Expected unknown-tool failure, got:\n{message}")
    return "unknown tool rejected"


def case_generate_protocol_positive(base_url: str, prompt: str) -> str:
    message = rpc_raw(
        base_url,
        "tools/call",
        {"name": "generate_protocol", "arguments": {"message": prompt}},
        req_id=6,
        timeout=300,
    )
    if "error" in message:
        raise RuntimeError(message["error"])
    if (message.get("result") or {}).get("isError"):
        raise RuntimeError(tool_text(message))
    text = tool_text(message)
    if "Error processing message" in text or text.startswith("Error:"):
        raise RuntimeError(text[:500])
    if "def run(" not in text and "protocol_api" not in text:
        raise RuntimeError(f"Expected protocol code in response, got:\n{text[:500]}")
    return f"chars={len(text)} has_run={'def run(' in text}"


def case_generate_protocol_negative_empty(base_url: str) -> str:
    message = rpc_raw(
        base_url,
        "tools/call",
        {"name": "generate_protocol", "arguments": {"message": ""}},
        req_id=7,
        timeout=120,
    )
    if "error" in message:
        return f"rpc error={message['error']}"
    text = tool_text(message).strip()
    # Empty prompt should not return a full ready-to-run protocol scaffold.
    looks_like_full_protocol = "def run(" in text and "load_labware" in text
    if looks_like_full_protocol and len(text) > 800:
        raise RuntimeError(
            "Empty generate_protocol prompt unexpectedly returned a full protocol:\n"
            f"{text[:400]}"
        )
    return f"empty prompt handled (chars={len(text)})"


def extract_protocol_code(text: str) -> str:
    """Pull the best Python protocol candidate from a generate_protocol response."""
    fenced = [block.strip() for block in PYTHON_FENCE_RE.findall(text) if block.strip()]
    candidates = fenced or [text.strip()]

    def score(code: str) -> tuple[int, int]:
        points = 0
        if "def run(" in code:
            points += 3
        if "protocol_api" in code or "from opentrons" in code:
            points += 2
        if "load_labware" in code or "load_instrument" in code:
            points += 1
        return (points, len(code))

    best = max(candidates, key=score)
    if score(best)[0] == 0:
        raise RuntimeError(
            "Could not extract protocol code from generate_protocol response:\n"
            f"{text[:500]}"
        )
    return best


def call_generate_protocol(base_url: str, message: str, *, req_id: int) -> str:
    response = rpc_raw(
        base_url,
        "tools/call",
        {"name": "generate_protocol", "arguments": {"message": message}},
        req_id=req_id,
        timeout=300,
    )
    if "error" in response:
        raise RuntimeError(response["error"])
    if (response.get("result") or {}).get("isError"):
        raise RuntimeError(tool_text(response))
    text = tool_text(response)
    if "Error processing message" in text or text.startswith("Error:"):
        raise RuntimeError(text[:500])
    return text


def call_simulate_protocol(base_url: str, protocol: str, *, req_id: int) -> str:
    response = rpc_raw(
        base_url,
        "tools/call",
        {"name": "simulate_protocol", "arguments": {"protocol": protocol}},
        req_id=req_id,
        timeout=180,
    )
    if "error" in response:
        raise RuntimeError(response["error"])
    if (response.get("result") or {}).get("isError"):
        raise RuntimeError(tool_text(response))
    text = tool_text(response).strip()
    if not text:
        raise RuntimeError("simulate_protocol returned empty result")
    return text


def is_simulation_success(result: str) -> bool:
    return "Simulation Success" in result


def is_simulator_infra_error(result: str) -> bool:
    """True when the simulator itself is unreachable/misconfigured (do not regenerate)."""
    markers = (
        "Simulator unavailable:",
        "Simulation request failed:",
        "Simulation timed out",
        "Simulation failed:",
        "<!DOCTYPE html>",
    )
    return any(marker in result for marker in markers)


def fix_prompt(original_prompt: str, protocol: str, simulation_error: str) -> str:
    return (
        "The following Opentrons protocol failed simulation. "
        "Return a corrected complete protocol only (Python), ready to simulate.\n\n"
        f"Original request:\n{original_prompt}\n\n"
        "Failed protocol:\n"
        f"```python\n{protocol}\n```\n\n"
        f"Simulation error:\n{simulation_error}\n"
    )


def case_generate_until_simulates(
    base_url: str,
    prompt: str,
    *,
    max_attempts: int = DEFAULT_MAX_SIMULATE_ATTEMPTS,
) -> str:
    """Generate a protocol, simulate it, and regenerate from errors until success."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    last_error = ""
    message = prompt
    for attempt in range(1, max_attempts + 1):
        print(f"  attempt {attempt}/{max_attempts}: generate_protocol...")
        generated = call_generate_protocol(base_url, message, req_id=100 + attempt)
        protocol = extract_protocol_code(generated)
        print(f"  attempt {attempt}/{max_attempts}: simulate_protocol ({len(protocol)} chars)...")
        sim_result = call_simulate_protocol(base_url, protocol, req_id=200 + attempt)
        print(f"  attempt {attempt}/{max_attempts}: {sim_result[:200]}")
        if is_simulation_success(sim_result):
            return f"success on attempt {attempt}: {sim_result}"
        if is_simulator_infra_error(sim_result):
            raise RuntimeError(
                "Simulator infrastructure error (not a protocol defect); "
                "fix HUGGINGFACE_API_KEY / SIMULATOR_URL before retrying:\n"
                f"{sim_result}"
            )
        last_error = sim_result
        message = fix_prompt(prompt, protocol, sim_result)

    raise RuntimeError(
        f"Protocol did not simulate successfully after {max_attempts} attempt(s). "
        f"Last simulation result:\n{last_error}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Local MCP positive/negative smoke tests")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--query", default=DOCS_QUERY)
    parser.add_argument("--protocol-prompt", default=PROTOCOL_PROMPT)
    parser.add_argument(
        "--skip-generate",
        action="store_true",
        help="Skip generate_protocol cases (docs/tools only)",
    )
    parser.add_argument(
        "--generate-until-simulates",
        action="store_true",
        help=(
            "Only run generate→simulate loop until Simulation Success "
            "(requires ANTHROPIC_API_KEY and HUGGINGFACE_API_KEY)"
        ),
    )
    parser.add_argument(
        "--max-simulate-attempts",
        type=int,
        default=DEFAULT_MAX_SIMULATE_ATTEMPTS,
        help=f"Max generate/simulate rounds (default {DEFAULT_MAX_SIMULATE_ATTEMPTS})",
    )
    args = parser.parse_args()

    print(f"MCP URL: {mcp_url(args.base_url)}\n")

    if args.generate_until_simulates:
        cases: list[tuple[str, Callable[[], str]]] = [
            (
                "generate until simulates (positive)",
                lambda: case_generate_until_simulates(
                    args.base_url,
                    args.protocol_prompt,
                    max_attempts=args.max_simulate_attempts,
                ),
            ),
        ]
    else:
        cases = [
            ("initialize (positive)", lambda: case_initialize(args.base_url)),
            ("tools/list (positive)", lambda: case_tools_list(args.base_url)),
            ("get_relevant_api_docs (positive)", lambda: case_docs_positive(args.base_url, args.query)),
        ]
        for label, query, expected_files in ABOUT_GUIDED_CASES:
            cases.append(
                (
                    f"get_relevant_api_docs about guides {label} (positive)",
                    lambda q=query, files=expected_files: case_docs_about_guides_query(
                        args.base_url, q, files
                    ),
                )
            )
        cases.extend(
            [
                (
                    "get_relevant_api_docs empty query (negative)",
                    lambda: case_docs_negative_empty_query(args.base_url),
                ),
                ("unknown tool (negative)", lambda: case_unknown_tool_negative(args.base_url)),
            ]
        )
        if not args.skip_generate:
            cases.extend(
                [
                    (
                        "generate_protocol (positive)",
                        lambda: case_generate_protocol_positive(
                            args.base_url, args.protocol_prompt
                        ),
                    ),
                    (
                        "generate_protocol empty message (negative)",
                        lambda: case_generate_protocol_negative_empty(args.base_url),
                    ),
                ]
            )

    results = [run_case(name, fn) for name, fn in cases]
    passed = sum(1 for result in results if result.ok)
    failed = len(results) - passed
    print(f"\n{passed}/{len(results)} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
