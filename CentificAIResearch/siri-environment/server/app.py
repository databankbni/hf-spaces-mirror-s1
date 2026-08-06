"""
FastAPI app for the PersonalAssistantBench RL Environment (OpenEnv).

Endpoints (provided by OpenEnv create_app when available):
    - POST /reset, POST /step, GET /state, GET /schema, WS /ws

Custom:
    - GET  /            — minimal demo UI
    - GET  /health
    - GET  /api/tasks, GET /api/tasks/{task_id}
    - GET  /api/golden, GET /api/golden/{task_id} — the real Apple on-device
      Foundation Model (~3B, iOS 26.4) runs (10/14 PASS), converted to rollout format.
    - POST /api/reset, POST /api/step — stateful pair for the UI / platform
      runner (shared env instance across calls).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi.responses import HTMLResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from personalassistantbench_env.models import PersonalAssistantBenchAction, PersonalAssistantBenchObservation

from .personalassistantbench_environment import PersonalAssistantBenchEnvironment
from .tasks import TASKS, get_task

_ROOT = Path(__file__).resolve().parents[1]
_GOLDEN_PATH = _ROOT / "data" / "golden" / "personalassistantbench_golden_rollouts.json"

try:
    from openenv.core.env_server.http_server import create_app

    app = create_app(
        PersonalAssistantBenchEnvironment,
        PersonalAssistantBenchAction,
        PersonalAssistantBenchObservation,
        env_name="personalassistantbench_env",
        max_concurrent_envs=1,
    )
except Exception:  # pragma: no cover — plain FastAPI fallback (same routes)
    from fastapi import FastAPI

    app = FastAPI(title="PersonalAssistantBench RL Environment")

    _fallback_env: Optional[PersonalAssistantBenchEnvironment] = None

    def _fenv() -> PersonalAssistantBenchEnvironment:
        global _fallback_env
        if _fallback_env is None:
            _fallback_env = PersonalAssistantBenchEnvironment()
        return _fallback_env

    @app.post("/reset")
    async def reset(request: Request):
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        obs = _fenv().reset(task_id=body.get("task_id"), seed=body.get("seed"))
        return JSONResponse(content={"observation": json.loads(obs.model_dump_json())})

    @app.post("/step")
    async def step(request: Request):
        body = await request.json()
        raw = body.get("action", body)
        obs = _fenv().step(PersonalAssistantBenchAction(**raw))
        return JSONResponse(content={"observation": json.loads(obs.model_dump_json())})

    @app.get("/state")
    async def state():
        return JSONResponse(content=json.loads(_fenv().state.model_dump_json()))


_ui_env: Optional[PersonalAssistantBenchEnvironment] = None


def _get_ui_env() -> PersonalAssistantBenchEnvironment:
    global _ui_env
    if _ui_env is None:
        _ui_env = PersonalAssistantBenchEnvironment()
    return _ui_env


_UI_HTML_PATH = _ROOT / "ui" / "index.html"


def _golden() -> dict:
    try:
        with open(_GOLDEN_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return {"rollouts": []}


def _ui_html() -> str:
    if _UI_HTML_PATH.exists():
        return _UI_HTML_PATH.read_text(encoding="utf-8")
    rows = "".join(
        f"<tr><td><code>{t.id}</code></td><td>{t.family}</td>"
        f"<td>{t.summary}</td><td>{len(t.prompts)}</td></tr>"
        for t in TASKS
    )
    return f"""<!doctype html>
<html><head><meta charset='utf-8'><title>PersonalAssistantBench RL Env</title>
<style>body{{font-family:system-ui;max-width:960px;margin:40px auto;padding:0 16px;color:#111}}
table{{width:100%;border-collapse:collapse;margin-top:16px}}th,td{{border:1px solid #ddd;padding:8px;text-align:left}}
code{{background:#f5f5f5;padding:2px 6px;border-radius:4px}}
.muted{{color:#666;font-size:14px}}
</style></head><body>
<h1>PersonalAssistantBench RL Environment</h1>
<p>An iOS-assistant RL environment ported from <b>PersonalAssistantBench</b> — 14 tasks over a
simulated iPhone (Reminders, Calendar, Contacts, Messages, personal data, web).
The agent gets the same <b>11 tools + respond</b> and the same neutral
instructions the Apple on-device Foundation Model (~3B, iOS 26.4) was given; rubrics are the
benchmark's original programmatic checks (no LLM judge).</p>
<p class='muted'>Endpoints: <code>POST /reset</code>, <code>POST /step</code>,
<code>GET /state</code>, <code>GET /api/tasks</code>, <code>GET /api/golden</code>.</p>
<h2>Tasks ({len(TASKS)})</h2>
<table><thead><tr><th>task_id</th><th>family</th><th>summary</th><th>turns</th></tr></thead>
<tbody>{rows}</tbody></table>
<h2>Reward</h2>
<p>Per step: valid tool +0.02 · malformed −0.10 · forbidden tool −0.30.
Terminal facets: process_required 0.30 · process_restraint 0.30 ·
outcome_state 0.20 · outcome_answer 0.20. <code>terminal_pass</code> is the
strict PersonalAssistantBench PASS verdict.</p>
<p class='muted'>Golden runs: the Apple on-device Foundation Model (~3B, iOS 26.4
simulator) scored 10 / 14 on these tasks.</p>
</body></html>"""


class _UIMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        p = request.url.path
        if p in ("/", "/ui", "/web") or p.startswith("/web/"):
            return HTMLResponse(content=_ui_html())
        return await call_next(request)


app.add_middleware(_UIMiddleware)


@app.get("/health")
async def health():
    return {"status": "ok", "n_tasks": len(TASKS)}


@app.get("/api/tasks")
async def list_tasks():
    return JSONResponse(content=[
        {
            "task_id": t.id,
            "family": t.family,
            "summary": t.summary,
            "seed_note": t.seed_note,
            "n_prompts": len(t.prompts),
            "prompts": t.prompts,
            "required_tools": t.rubric.required_tools,
            "forbidden_tools": t.rubric.forbidden_tools,
            "answer_all": t.rubric.answer_all,
            "trajectory_all": t.rubric.trajectory_all,
            "trajectory_none": t.rubric.trajectory_none,
            "reminders_count": t.rubric.reminders_count,
        }
        for t in TASKS
    ])


@app.get("/api/tasks/{task_id}")
async def get_task_route(task_id: str):
    t = get_task(task_id)
    if not t:
        return JSONResponse(content={"error": f"task '{task_id}' not found"}, status_code=404)
    return JSONResponse(content={
        "task_id": t.id,
        "family": t.family,
        "summary": t.summary,
        "prompts": t.prompts,
        "rubric": {
            "required_tools": t.rubric.required_tools,
            "forbidden_tools": t.rubric.forbidden_tools,
            "answer_all": t.rubric.answer_all,
            "trajectory_all": t.rubric.trajectory_all,
            "trajectory_none": t.rubric.trajectory_none,
            "reminders_count": t.rubric.reminders_count,
        },
    })


@app.get("/api/golden")
async def golden_all():
    return JSONResponse(content=_golden())


@app.get("/api/golden/{task_id}")
async def golden_one(task_id: str):
    data = _golden()
    hits = [r for r in data.get("rollouts", []) if r.get("task_id") == task_id]
    if not hits:
        return JSONResponse(content={"error": f"no golden run for '{task_id}'"}, status_code=404)
    return JSONResponse(content=hits[0])


@app.get("/api/world")
async def api_world():
    """Live snapshot of the simulated iPhone (the stateful UI env's world)."""
    env = _get_ui_env()
    w = env.world
    s = env.state
    return JSONResponse(content={
        "task_id": s.task_id,
        "status": s.status.value,
        "step_count": s.step_count,
        "reminders": list(w.reminders),
        "events": [
            {"title": t, "start": dt.isoformat(), "label": None}
            for t, dt in w.events
        ],
        "contacts": list(w.contacts),
        "message_draft": w.message_draft,
        "page_text": w.page_text,
        "personal_corpus": [
            {"source": d.source, "date": d.date, "title": d.title, "body": d.body}
            for d in w.personal_corpus
        ],
    })


@app.post("/api/reset")
async def api_reset(request: Request):
    """Stateful reset for the UI / runner — shared env across /api/step calls."""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    env = _get_ui_env()
    obs = env.reset(task_id=body.get("task_id"), seed=body.get("seed"))
    return JSONResponse(content={"observation": json.loads(obs.model_dump_json())})


@app.post("/api/step")
async def api_step(request: Request):
    """Stateful step for the UI / runner — uses the shared env instance."""
    body = await request.json()
    raw = body.get("action", body)
    action = PersonalAssistantBenchAction(**raw)
    env = _get_ui_env()
    obs = env.step(action)
    return JSONResponse(content={"observation": json.loads(obs.model_dump_json())})
