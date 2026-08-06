---
title: SWMM Analysis MCP Server
emoji: 🌧️
colorFrom: blue
colorTo: red
sdk: docker
app_port: 7860
pinned: false
short_description: Dual-surface MCP + REST EPA-SWMM analysis server.
tags:
  - mcp-server
  - stormwater
  - swmm
  - hydrology
  - agent
---

# 🌧️ SWMM Analysis MCP Server

A dual-surface **MCP + REST** server for deterministic EPA-SWMM stormwater analysis,
with a **built-in multi-provider agent**. Wraps the SWMM6 GIS Tool engine (Rev 23.2):
crash-isolated OpenSWMM simulation, result summaries, Calgary-style criteria
screening, deterministic QA/QC findings, engine-report (`.rpt`) reconciliation,
controlled scenario comparison, and Calgary SWMR draft report generation.

**All outputs are preliminary engineering screening — not professional
determinations.** Screening thresholds require confirmation by the responsible
engineer.

## Surfaces

| Surface | Endpoint | For |
|---|---|---|
| **MCP (Streamable HTTP)** | `https://<space-url>/mcp` | Claude Desktop / claude.ai, ChatGPT connectors, Gemini, Codex CLI, LangChain, n8n MCP node, Flowise, Langflow, local MCP clients |
| **REST / OpenAPI** | `POST /api/tool/{name}` · catalog `/api/tools` · schema `/openapi.json` | Custom GPT Actions, n8n HTTP nodes, webhooks, anything speaking OpenAPI |
| **Built-in agent** | `POST /api/agent` and MCP tool `agent_analyze` | One natural-language call; the server's own LLM loop plans and runs the tools |
| **Files** | `GET /files/{session_id}/{filename}` | Generated SWMR docx / audit-zip downloads |

## Tools (19)

`upload_model` → `run_simulation` → then: `get_node_results`, `get_link_results`,
`get_subcatchment_results`, `get_timeseries` (bounded series with authoritative
`time_of_peak`), `query_results` (validated JSON plans against a 34-table SQLite
store incl. the complete tokenized INP), `get_table_catalog`,
`calgary_screening`, `set_report_details` (site description, design objectives,
methodology, project metadata — see the swmr-site-details skill),
`set_report_configuration` (project-specific major routes, criteria,
classifications, drawing inventory, applicable reports and checklist overrides),
`preliminary_design_review` (deterministic findings register incl.
RPT-### reconciliation findings), `get_reconciliation`, `run_scenario` (base never
mutated; deterministic comparison), `attach_figure` (embed client-generated
PNG/JPEG figures into the audited report), `generate_report` (SWMR docx + audit
zip; APPENDIX D reproduces the model .inp and .rpt as fixed-width listings
per the Calgary checklist, with untruncated copies archived under `model/`), `list_sessions`, `close_session`, `agent_analyze`.

### Client-figure workflow (recommended)

When your LLM client plots a hydrograph or map from `get_timeseries` data,
do **not** let it rebuild the report document itself — that bypasses the
audited tables and provenance package. Instead:

1. Client generates the figure (its own sandbox / code interpreter).
2. `attach_figure(session_id, image_base64, caption, section="results")`.
3. `generate_report(...)` — the figure is embedded at the end of the matching
   Heading-1 section with a caption labelling it *client-attached,
   illustrative*, and it is archived in the audit zip under `figures/` with a
   manifest. The report itself remains the server's verified artifact.

Typical CoC flow: **upload_model → set_report_details →
set_report_configuration → run_simulation → deterministic QA/QC and Calgary
screening → generate_report**, reusing the returned `session_id`. Sessions
expire after 6 h of inactivity.

Generated Calgary-style SWMR drafts include a deterministic depth-velocity
criteria figure immediately below Table 9. It plots the tabulated 2011
Alberta/Calgary envelope, the modeled overland-route depth/velocity pairs, and
peak flow by marker colour. The figure PNG and its criterion CSV are retained
in the audit ZIP. The report discloses straight-line interpolation and the need
to verify current and project-specific requirements.

The report also generates Figure 3-1, an automated SWMM model schematic, from
the tokenized INP. It uses `[COORDINATES]` and `[VERTICES]` when available,
falls back to a stable topology layout when coordinates are incomplete, shows
subcatchment runoff routing and hydraulic-link direction, and archives both the
PNG and a generation manifest. It is a topology aid and remains subject to
drawing-to-model reconciliation.

### Legacy zero-value solver options

For dynamic-wave models, explicit zero values for `MAX_TRIALS`,
`HEAD_TOLERANCE`, and `MIN_SURFAREA` are treated as legacy/default sentinels.
The uploaded INP remains immutable. The server creates and runs a derivative
execution copy with unit-aware EPA SWMM defaults, and records every
substitution plus the SHA-256 hashes of both files. Negative or non-numeric
values remain blocking configuration errors. The report audit ZIP retains both
the original and derivative INP files whenever normalization occurs.

## Connecting from each platform

Replace `SPACE` with this Space's direct URL, e.g.
`https://username-swmm-mcp.hf.space` (use the *direct* subdomain, not the
huggingface.co page URL).

### Claude (claude.ai web / desktop, remote connector)
Settings → Connectors → Add custom connector → URL: `SPACE/mcp`.

### Claude Desktop (mcp-remote bridge, or any stdio-only client)
```json
{
  "mcpServers": {
    "swmm-analysis": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "SPACE/mcp"]
    }
  }
}
```

### ChatGPT
Settings → Connectors → Create → MCP server URL: `SPACE/mcp` (Developer mode).
Alternatively build a **Custom GPT** with Actions: import the schema from
`SPACE/openapi.json` — the REST surface is designed for this.

### Gemini CLI
```json
// ~/.gemini/settings.json
{ "mcpServers": { "swmm-analysis": { "httpUrl": "SPACE/mcp" } } }
```

### Codex CLI
```toml
# ~/.codex/config.toml
[mcp_servers.swmm-analysis]
url = "SPACE/mcp"
```

### n8n
- **MCP Client Tool node**: endpoint `SPACE/mcp`, transport *HTTP Streamable*.
- Or plain **HTTP Request** nodes against `POST SPACE/api/tool/{name}`.
- Or one-shot: `POST SPACE/api/agent` with `{"question": "...", "provider": "gemini"}`.

### Flowise / Langflow
Add the **Custom MCP** (Flowise) / **MCP Tools** (Langflow) component with a
Streamable-HTTP config pointing at `SPACE/mcp`; the tool list auto-populates.

### LangChain / LangGraph
```python
from langchain_mcp_adapters.client import MultiServerMCPClient
client = MultiServerMCPClient({
    "swmm": {"url": "SPACE/mcp", "transport": "streamable_http"}
})
tools = await client.get_tools()   # bind to any model
```

### Local LLMs (Ollama, LM Studio, vLLM)
Two options:
1. Point any local MCP-capable client (e.g. LM Studio, mcp-use) at `SPACE/mcp`.
2. Reverse: let the **server's agent** use your local model —
   `POST /api/agent` with `{"provider": "local", "base_url": "http://host:11434/v1", "model": "llama3.1", "question": "..."}`.

## Built-in agent

`POST /api/agent` body:
```json
{
  "question": "Upload this model, run it, and screen velocities against Calgary criteria.",
  "provider": "anthropic",
  "inp_content": "<.inp text or base64>",
  "session_id": "optional-existing-session",
  "allow_report": false
}
```
Providers: `anthropic`, `openai`, `gemini`, `groq`, `mistral`, `local`
(OpenAI-compatible `base_url`). Keys come from **Space secrets**
(`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`,
`MISTRAL_API_KEY`) or a per-request `api_key`. Every response includes the
complete `tool_trace` audit trail (tool, arguments, elapsed time, result
preview) — the agent may only report numbers that came from tools.

> If your platform is already an MCP client, prefer driving the tools directly:
> your model is the agent, and it sees full (not previewed) tool results.

## Architecture notes

- **Crash isolation**: the native OpenSWMM engine runs only in a one-shot
  subprocess in its own venv (`/opt/swmm-venv`); a segfaulting model cannot
  take down the server.
- **Single source of truth**: MCP, REST, and the agent all dispatch to the
  same typed registry (`tools.py`), so behaviour is identical per platform.
- **Result integrity**: every simulation is cross-checked against the
  engine's own `.rpt` (velocity/flow/depth/continuity); disagreements surface
  as `RPT-###` findings and the verdict is embedded in report manifests.
- **HF Spaces specifics baked in**: DNS-rebinding protection disabled for the
  Spaces proxy, MCP session-manager lifespan wired into FastAPI, stateless
  HTTP + JSON responses for maximum connector compatibility.
- **Sessions**: process-local with TTL sweep; Space restarts clear state
  (persistent storage is not required for the workflow).

## Security

No authentication is enabled by default — anyone with the URL can run models
and (if Space secrets are set) spend your LLM keys via `/api/agent`. For
non-demo use, set the Space to private, or front it with an auth proxy, and
prefer per-request `api_key` over Space secrets.

## Local development

```bash
pip install -r requirements.txt
python -m venv /opt/swmm-venv && /opt/swmm-venv/bin/pip install -r worker-requirements.txt
SWMM_WORKER_PYTHON=/opt/swmm-venv/bin/python uvicorn server:app --port 7860
```

Free and non-commercial, for the water-engineering community.