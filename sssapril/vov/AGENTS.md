# AGENTS.md — AgentFlow

Multi-agent group-chat creative platform. Users act as "directors" orchestrating AI agents through projects and groups.

## Architecture

Three packages, one repo:

- `agentflow/` — Python SDK (agent execution engine). Installed as editable package (`pip install -e ../agentflow`).
- `server/` — FastAPI backend. Entry: `app/main.py` (web), `app/desktop.py` (pywebview desktop).
- `client/` — React 19 + TypeScript + Vite 7 frontend.

Database is **SQLite** (not PostgreSQL). Data stored at `~/AgentFlow/data/agentflow.db` in dev; same path in packaged mode. No Docker required for development.

## Dev Commands

### Backend (server/)

```bash
cd server
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload
```

Tests: `cd server && python -m pytest tests/`

No linting or typecheck tools configured for Python.

### Frontend (client/)

```bash
cd client
npm install
npm run dev       # Vite dev server on :5173, proxies /api to :8002
npm run lint      # ESLint
npm run test      # Vitest
npm run build     # Production build (outputs to client/dist/)
```

Typecheck: `npx tsc --noEmit` (Vite plugin checker also runs on build).

### Full stack

```bash
# Windows
start.bat          # launches both servers (port 8002 + 5173)
stop.bat           # kills both

# Manual: start DB (if needed), backend, frontend in separate terminals
```

### Desktop build (PyInstaller)

```bash
build.bat          # builds client, then pyinstaller -> dist/AgentFlow/
```

Entry: `server/app/desktop.py`. Uses `pywebview` for native window.

## Key Conventions

- **npm registry**: `client/.npmrc` points to `registry.npmmirror.com` (China mirror).
- **Auto-imports**: `client/vite.config.ts` auto-imports React hooks/functions and Lucide `*Icon` components. No need to manually import these in `.tsx` files.
- **Path alias**: `@` → `client/src/` (configured in both Vite and Vitest).
- **Backend tests**: use SQLite test DB (`test_vov.db`), auto-create/drop tables per test. Fixtures in `server/tests/conftest.py`.
- **Frontend tests**: Vitest + jsdom + `@testing-library/react`. Setup at `client/src/test/setup.ts`.
- **State management**: Zustand (`client/src/store/`).
- **UI components**: shadcn/ui (Radix primitives + Tailwind).
- **API prefix**: all backend routes under `/api/v1`.
- **AgentFlow SDK**: processor-based architecture. Core files: `agentflow/agent.py`, `agentflow/processor.py`, `agentflow/specs.py`.

## Agent Tool Call Architecture

RESPONSE packets (tool results) flow through the **normal pipeline** — no special cases:

```
RESPONSE 进入 Agent._process():
  pre_process 链:
    MemoryPlugin    → 存入链历史
    AllModelPlugin  → 并行时聚合所有 RESPONSE，单个时直接通过
    ToolEventPlugin → 转发给 StreamCollector（前端实时展示 tool_result）
  ↓
  core_process → _build_messages（含所有工具结果）→ llm.chat → 最终回复
```

Plugin roles (one job each):
- **MemoryPlugin**: chain history storage
- **AllModelPlugin**: parallel tool call batching (waits for all RESPONSEs before LLM call)
- **ToolEventPlugin**: captures RESPONSE in pre_process, forwards to StreamCollector for frontend display
- **CallbackPlugin**: routes RESPONSE from tool processor back to Agent (attached to tool processors, not Agent)

**Do NOT add packet-type special cases in `_process`.** Use plugins instead.

## Gotchas

- The `agentflow/` package must be installed in editable mode (`pip install -e ../agentflow`) or the server will fail to import it.
- `requirements.txt` includes `-e ../agentflow` — run `pip install -r requirements.txt` from `server/`.
- Desktop mode (`desktop.py`) skips CORS middleware; dev mode requires it.
- SSE streaming proxy in Vite config disables buffering — don't re-enable compression on SSE endpoints.
- Windows: backend forces UTF-8 on stdout/stderr at startup (`main.py:9-15`).
