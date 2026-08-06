"""Built-in agent: an LLM tool-use loop over the SWMM tool registry.

For platforms that are not MCP clients (plain REST callers, n8n HTTP nodes,
Custom GPT Actions, simple webhooks), this provides a single "ask the agent"
endpoint. MCP-native clients (Claude Desktop/web, Gemini, LangChain,
Flowise, Langflow) should normally drive the tools directly instead — their
own model is the agent.

Providers (two wire dialects, both via httpx, no SDK dependencies):
  anthropic  -> Anthropic Messages API (ANTHROPIC_API_KEY)
  openai     -> OpenAI chat completions (OPENAI_API_KEY)
  gemini     -> Gemini OpenAI-compatible endpoint (GEMINI_API_KEY)
  groq       -> Groq OpenAI-compatible endpoint (GROQ_API_KEY)
  mistral    -> Mistral OpenAI-compatible endpoint (MISTRAL_API_KEY)
  local      -> any OpenAI-compatible server (Ollama, LM Studio, vLLM) via
                base_url; api_key optional

Keys come from environment (HF Space secrets) or per-request overrides.
Every response includes the full tool-call audit trail.
"""
from __future__ import annotations

import inspect
import json
import os
import time
from typing import Any

import httpx

from tools import TOOL_REGISTRY

MAX_STEPS = 8
TOOL_RESULT_CHAR_LIMIT = 14000

SYSTEM_PROMPT = """You are a stormwater modelling analysis agent operating deterministic SWMM tools.

Rules of practice:
- Work from tool results only; never invent numbers. If output is unavailable, say so — do not report zero.
- Distinguish SCREENING results from CRITERIA: thresholds (e.g. Calgary 3.0/4.0 m/s velocity screens) require confirmation by the responsible engineer; say "screens above/below" not "fails/passes" unless a criterion is confirmed.
- Typical workflow: upload_model -> run_simulation -> targeted result/screening tools. Reuse an existing session_id when the user provides one.
- If the rpt_reconciliation verdict flags links, note that .rpt values are authoritative for those links.
- State clearly that outputs are preliminary engineering screening, not a professional determination.
Answer concisely with the key numbers and their provenance (which tool produced them)."""

PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "anthropic": {"dialect": "anthropic", "base_url": "https://api.anthropic.com",
                  "env": "ANTHROPIC_API_KEY", "default_model": "claude-sonnet-4-5"},
    "openai": {"dialect": "openai", "base_url": "https://api.openai.com/v1",
               "env": "OPENAI_API_KEY", "default_model": "gpt-4o"},
    "gemini": {"dialect": "openai", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
               "env": "GEMINI_API_KEY", "default_model": "gemini-2.0-flash"},
    "groq": {"dialect": "openai", "base_url": "https://api.groq.com/openai/v1",
             "env": "GROQ_API_KEY", "default_model": "llama-3.3-70b-versatile"},
    "mistral": {"dialect": "openai", "base_url": "https://api.mistral.ai/v1",
                "env": "MISTRAL_API_KEY", "default_model": "mistral-large-latest"},
    "local": {"dialect": "openai", "base_url": os.environ.get("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1"),
              "env": "LOCAL_LLM_API_KEY", "default_model": os.environ.get("LOCAL_LLM_MODEL", "llama3.1")},
}

# Tools the agent may call. upload_model is included so callers can pass INP
# content inline; generate_report excluded by default (large side effects)
# unless allow_report=True.
AGENT_TOOLS_DEFAULT = [
    "upload_model", "run_simulation", "list_sessions", "get_node_results",
    "get_link_results", "get_subcatchment_results", "get_timeseries",
    "query_results", "get_table_catalog", "calgary_screening",
    "preliminary_design_review", "get_reconciliation", "run_scenario",
    "set_report_details", "set_report_configuration",
]

_JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean",
               dict: "object", list: "array"}


def _tool_schemas(names: list[str]) -> list[dict[str, Any]]:
    schemas = []
    for name in names:
        fn = TOOL_REGISTRY.get(name)
        if fn is None:
            continue
        sig = inspect.signature(fn)
        props, required = {}, []
        for pname, param in sig.parameters.items():
            ann = param.annotation
            jtype = "string"
            for py, js in _JSON_TYPES.items():
                if ann is py:
                    jtype = js
                    break
            if ann in (dict | str | None, dict | str):
                jtype = "object"
            props[pname] = {"type": jtype}
            if param.default is inspect.Parameter.empty:
                required.append(pname)
        schemas.append({"name": name,
                        "description": (fn.__doc__ or name).strip()[:900],
                        "input_schema": {"type": "object", "properties": props, "required": required}})
    return schemas


def _execute(name: str, arguments: dict[str, Any]) -> str:
    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        return json.dumps({"error": f"unknown tool {name}"})
    try:
        result = fn(**(arguments or {}))
        text = json.dumps(result, default=str)
    except Exception as exc:  # deterministic error surface for the model
        text = json.dumps({"error": f"{type(exc).__name__}: {exc}"})
    if len(text) > TOOL_RESULT_CHAR_LIMIT:
        text = text[:TOOL_RESULT_CHAR_LIMIT] + '... (truncated — request a smaller limit or use query_results)"}'
    return text


class LLMClient:
    """Minimal two-dialect chat client. `transport` is injectable for tests."""

    def __init__(self, provider: str, model: str | None = None, api_key: str | None = None,
                 base_url: str | None = None, transport: Any | None = None):
        preset = PROVIDER_PRESETS.get(provider)
        if preset is None:
            raise ValueError(f"Unknown provider '{provider}'. Choose from {sorted(PROVIDER_PRESETS)}.")
        self.provider = provider
        self.dialect = preset["dialect"]
        self.base_url = (base_url or preset["base_url"]).rstrip("/")
        self.model = model or preset["default_model"]
        self.api_key = api_key or os.environ.get(preset["env"], "")
        if not self.api_key and provider != "local":
            raise ValueError(
                f"No API key for provider '{provider}'. Set the {preset['env']} Space secret "
                "or pass api_key in the request.")
        self._transport = transport

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        if self._transport is not None:
            return self._transport(self, messages, tools)
        if self.dialect == "anthropic":
            return self._chat_anthropic(messages, tools)
        return self._chat_openai(messages, tools)

    def _chat_anthropic(self, messages: list[dict], tools: list[dict]) -> dict:
        resp = httpx.post(
            f"{self.base_url}/v1/messages",
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
            json={"model": self.model, "max_tokens": 2000, "system": SYSTEM_PROMPT,
                  "messages": messages, "tools": tools},
            timeout=120.0)
        resp.raise_for_status()
        data = resp.json()
        calls = [{"id": b["id"], "name": b["name"], "arguments": b["input"]}
                 for b in data.get("content", []) if b.get("type") == "tool_use"]
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        return {"text": text, "tool_calls": calls, "raw_content": data.get("content", []),
                "stop": data.get("stop_reason")}

    def _chat_openai(self, messages: list[dict], tools: list[dict]) -> dict:
        oai_tools = [{"type": "function",
                      "function": {"name": t["name"], "description": t["description"],
                                   "parameters": t["input_schema"]}} for t in tools]
        oai_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        resp = httpx.post(f"{self.base_url}/chat/completions", headers=headers,
                          json={"model": self.model, "messages": oai_messages,
                                "tools": oai_tools or None}, timeout=120.0)
        resp.raise_for_status()
        msg = resp.json()["choices"][0]["message"]
        calls = [{"id": c["id"], "name": c["function"]["name"],
                  "arguments": json.loads(c["function"]["arguments"] or "{}")}
                 for c in (msg.get("tool_calls") or [])]
        return {"text": msg.get("content") or "", "tool_calls": calls,
                "raw_message": msg, "stop": "tool_use" if calls else "end"}


def run_agent(question: str, provider: str = "anthropic", model: str | None = None,
              api_key: str | None = None, base_url: str | None = None,
              session_id: str | None = None, inp_content: str | None = None,
              allow_report: bool = False, max_steps: int = MAX_STEPS,
              transport: Any | None = None) -> dict:
    """Run the tool-use loop and return {answer, tool_trace, steps, provider}."""
    client = LLMClient(provider, model, api_key, base_url, transport)
    tool_names = list(AGENT_TOOLS_DEFAULT) + (["generate_report", "close_session"] if allow_report else [])
    tools = _tool_schemas(tool_names)

    user_text = question
    if session_id:
        user_text += f"\n\n(Existing session_id: {session_id})"
    if inp_content:
        user_text += "\n\nA SWMM .inp model is provided below — upload it first.\n<inp_file>\n" + inp_content[:400000] + "\n</inp_file>"

    trace: list[dict[str, Any]] = []
    if client.dialect == "anthropic":
        messages: list[dict] = [{"role": "user", "content": user_text}]
        for step in range(max_steps):
            reply = client.chat(messages, tools)
            if not reply["tool_calls"]:
                return {"answer": reply["text"], "tool_trace": trace, "steps": step + 1,
                        "provider": provider, "model": client.model}
            messages.append({"role": "assistant", "content": reply["raw_content"]})
            results_content = []
            for call in reply["tool_calls"]:
                t0 = time.time()
                output = _execute(call["name"], call["arguments"])
                trace.append({"tool": call["name"], "arguments": call["arguments"],
                              "elapsed_s": round(time.time() - t0, 2),
                              "result_preview": output[:400]})
                results_content.append({"type": "tool_result", "tool_use_id": call["id"],
                                        "content": output})
            messages.append({"role": "user", "content": results_content})
    else:
        messages = [{"role": "user", "content": user_text}]
        for step in range(max_steps):
            reply = client.chat(messages, tools)
            if not reply["tool_calls"]:
                return {"answer": reply["text"], "tool_trace": trace, "steps": step + 1,
                        "provider": provider, "model": client.model}
            messages.append(reply["raw_message"])
            for call in reply["tool_calls"]:
                t0 = time.time()
                output = _execute(call["name"], call["arguments"])
                trace.append({"tool": call["name"], "arguments": call["arguments"],
                              "elapsed_s": round(time.time() - t0, 2),
                              "result_preview": output[:400]})
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": output})

    return {"answer": "Agent reached the maximum number of steps without a final answer. "
                      "Partial evidence is in tool_trace.",
            "tool_trace": trace, "steps": max_steps, "provider": provider, "model": client.model}
