# n8n integration

**Option A — MCP Client Tool node (AI Agent):**
Endpoint: `https://YOUR-SPACE.hf.space/mcp` · Transport: HTTP Streamable.
The agent node auto-discovers all 16 tools.

**Option B — HTTP Request nodes (deterministic pipelines):**
1. POST `/api/tool/upload_model`   body: `{"inp_content": "={{ $binary.data.toString() }}", "filename": "model.inp"}`
2. POST `/api/tool/run_simulation` body: `{"session_id": "={{ $json.session_id }}"}`
3. POST `/api/tool/calgary_screening` → route flagged links to Slack/email.

**Option C — one node total:**
POST `/api/agent` with `{"question": "...", "provider": "groq", "inp_content": "..."}` —
the server's own agent plans the tool calls and returns answer + tool_trace.
