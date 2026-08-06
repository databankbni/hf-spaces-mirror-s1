"""SWMM Analysis MCP Server — dual-surface deployment for Hugging Face Spaces.

Surfaces
--------
1. MCP (Streamable HTTP) at /mcp
   For MCP-native clients: Claude Desktop & claude.ai custom connectors,
   Gemini CLI/clients, ChatGPT connectors, LangChain MCP adapters, n8n MCP
   Client node, Flowise/Langflow MCP tools, Codex CLI. Stateless HTTP +
   JSON responses for maximum client compatibility; DNS-rebinding
   protection disabled (required behind the HF Spaces proxy).

2. REST/OpenAPI at /api/*  (schema at /openapi.json)
   Every registry tool as POST /api/tool/{name}; used by Custom GPT
   Actions, n8n HTTP Request nodes, plain webhooks, and anything that
   speaks OpenAPI rather than MCP.

3. Built-in agent at POST /api/agent (also MCP tool `agent_analyze`)
   A multi-provider LLM tool-loop over the same registry, for callers that
   want one natural-language endpoint (see agent.py).

4. GET /files/{session_id}/{filename} — generated report downloads.

Both surfaces dispatch to the same registry in tools.py, so behaviour is
identical on every platform.
"""
from __future__ import annotations

import contextlib
import inspect
import json
import os
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

import agent as agent_module
from sessions import SESSION_ROOT, STORE
from tools import TOOL_REGISTRY

SERVER_NAME = "swmm-analysis"
SERVER_VERSION = "1.0.4 (engine Rev 23.2; generic CoC workflow Rev 28)"

# ---------------------------------------------------------------------------
# MCP surface
# ---------------------------------------------------------------------------
# Known HF-Spaces deployment fixes, learned the hard way on prior servers:
#   1. TransportSecuritySettings(enable_dns_rebinding_protection=False):
#      the Spaces proxy rewrites Host headers and rebinding protection
#      rejects every request without this.
#   2. The MCP session manager lifespan MUST be wired into the outer FastAPI
#      app (dropping it silently breaks streamable HTTP after startup).
#   3. README.md needs its YAML front-matter header or the Space won't build.
mcp = FastMCP(
    SERVER_NAME,
    instructions=(
        "Deterministic EPA-SWMM stormwater analysis: upload a .inp model, run the "
        "crash-isolated simulation, then query results, Calgary-style screening, "
        "QA/QC findings, engine-report reconciliation, controlled scenarios, and "
        "SWMR draft reports. Typical flow: upload_model -> run_simulation -> "
        "analysis tools with the returned session_id. All outputs are preliminary "
        "engineering screening, not professional determinations."
    ),
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

for _name, _fn in TOOL_REGISTRY.items():
    mcp.tool()(_fn)


@mcp.tool()
def agent_analyze(question: str, provider: str = "anthropic", model: str = "",
                  session_id: str = "", api_key: str = "", base_url: str = "") -> dict:
    """Ask the built-in agent a natural-language question; it plans and runs the
    SWMM tools itself and returns an answer plus a full tool audit trail.
    Providers: anthropic, openai, gemini, groq, mistral, local (keys via Space
    secrets or api_key argument). MCP clients normally drive tools directly —
    use this when you want server-side orchestration."""
    return agent_module.run_agent(
        question=question, provider=provider, model=model or None,
        api_key=api_key or None, base_url=base_url or None,
        session_id=session_id or None)


mcp_app = mcp.streamable_http_app()

# ---------------------------------------------------------------------------
# FastAPI app with the MCP lifespan wired in (fix #2)
# ---------------------------------------------------------------------------

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(mcp.session_manager.run())
        yield


app = FastAPI(
    title="SWMM Analysis MCP Server",
    version=SERVER_VERSION,
    description="Dual-surface (MCP + REST) EPA-SWMM analysis server with a built-in multi-provider agent. "
                "MCP endpoint: /mcp. Engine: OpenSWMM in a crash-isolated worker, Calgary screening, "
                "deterministic QA/QC, .rpt reconciliation, scenarios, SWMR reporting.",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# REST surface — one endpoint per tool, plus a generic dispatcher
# ---------------------------------------------------------------------------

def _tool_meta(name: str, fn) -> dict:
    sig = inspect.signature(fn)
    return {
        "name": name,
        "description": (fn.__doc__ or "").strip(),
        "parameters": {
            p: {"required": prm.default is inspect.Parameter.empty,
                "default": None if prm.default is inspect.Parameter.empty else prm.default}
            for p, prm in sig.parameters.items()
        },
        "rest": f"POST /api/tool/{name}",
    }


@app.get("/api/tools")
def rest_list_tools() -> dict:
    """List all tools with parameter metadata (machine-readable)."""
    return {"server": SERVER_NAME, "version": SERVER_VERSION,
            "tools": [_tool_meta(n, f) for n, f in TOOL_REGISTRY.items()]}


@app.post("/api/tool/{tool_name}")
def rest_call_tool(tool_name: str, payload: dict = Body(default={})) -> JSONResponse:
    """Invoke any registry tool. Body = the tool's keyword arguments as JSON."""
    fn = TOOL_REGISTRY.get(tool_name)
    if fn is None:
        raise HTTPException(404, f"Unknown tool '{tool_name}'. See /api/tools.")
    try:
        result = fn(**(payload or {}))
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"{type(exc).__name__}: {exc}")
    return JSONResponse(json.loads(json.dumps(result, default=str)))


@app.post("/api/agent")
def rest_agent(payload: dict = Body(...)) -> JSONResponse:
    """Built-in agent endpoint.

    Body: {"question": str, "provider": "anthropic|openai|gemini|groq|mistral|local",
           "model": str?, "api_key": str?, "base_url": str?, "session_id": str?,
           "inp_content": str?, "allow_report": bool?}
    """
    question = payload.get("question", "").strip()
    if not question:
        raise HTTPException(400, "'question' is required.")
    try:
        result = agent_module.run_agent(
            question=question,
            provider=payload.get("provider", "anthropic"),
            model=payload.get("model") or None,
            api_key=payload.get("api_key") or None,
            base_url=payload.get("base_url") or None,
            session_id=payload.get("session_id") or None,
            inp_content=payload.get("inp_content") or None,
            allow_report=bool(payload.get("allow_report", False)),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Agent/provider error: {type(exc).__name__}: {exc}")
    return JSONResponse(json.loads(json.dumps(result, default=str)))


@app.get("/files/{session_id}/{filename}")
def serve_file(session_id: str, filename: str) -> FileResponse:
    """Download generated report artifacts."""
    safe_session = Path(session_id).name
    safe_file = Path(filename).name
    path = (SESSION_ROOT / safe_session / "outputs" / safe_file).resolve()
    if not str(path).startswith(str(SESSION_ROOT.resolve())) or not path.exists():
        raise HTTPException(404, "File not found (sessions expire; regenerate the report).")
    return FileResponse(path, filename=safe_file)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "server": SERVER_NAME, "version": SERVER_VERSION,
            "tools": len(TOOL_REGISTRY) + 1, "sessions": len(STORE.list()),
            "mcp_endpoint": "/mcp", "openapi": "/openapi.json"}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    tool_rows = "".join(
        f"<tr><td><code>{n}</code></td><td>{(f.__doc__ or '').strip().splitlines()[0]}</td></tr>"
        for n, f in TOOL_REGISTRY.items())
    return f"""<!doctype html><html><head><title>SWMM Analysis MCP Server</title>
<style>body{{font-family:system-ui;max-width:900px;margin:2rem auto;padding:0 1rem;color:#222}}
code{{background:#f2f2f2;padding:1px 5px;border-radius:4px}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ddd;padding:6px 10px;text-align:left;font-size:14px}}h1{{color:#0a4d8c}}</style></head>
<body><h1>🌧️ SWMM Analysis MCP Server</h1>
<p>Deterministic EPA-SWMM stormwater analysis (engine Rev 23.2) with dual MCP + REST surfaces
and a built-in multi-provider agent. All results are preliminary engineering screening.</p>
<ul>
<li><b>MCP endpoint (Streamable HTTP):</b> <code>&lt;this-space-url&gt;/mcp</code></li>
<li><b>REST:</b> <code>POST /api/tool/{{name}}</code> — catalog at <a href="/api/tools">/api/tools</a>,
schema at <a href="/openapi.json">/openapi.json</a></li>
<li><b>Agent:</b> <code>POST /api/agent</code> (anthropic · openai · gemini · groq · mistral · local)</li>
<li><b>Health:</b> <a href="/health">/health</a></li>
</ul>
<h3>Tools ({len(TOOL_REGISTRY) + 1})</h3><table><tr><th>Tool</th><th>Purpose</th></tr>{tool_rows}
<tr><td><code>agent_analyze</code></td><td>Server-side agent loop over all tools (MCP + REST).</td></tr></table>
<p>Typical flow: <code>upload_model</code> → <code>run_simulation</code> → analysis tools with the returned
<code>session_id</code>. See the README for per-platform connection instructions.</p></body></html>"""


# Mount MCP last so explicit routes take priority.
app.mount("/", mcp_app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "7860")))
