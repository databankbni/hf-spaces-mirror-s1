"""
AgentDebuggerEnv — FastAPI Server
===================================
Exposes the environment as REST endpoints:
  POST /reset  — Start a fresh episode
  POST /step   — Submit one action
  GET  /state  — Full internal state
  GET  /health — Deployment health check (must return 200)
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional

from env.environment import DebuggerEnvironment
from env.models import Action
from env.tasks.registry import list_tasks

app = FastAPI(
    title="AgentDebuggerEnv",
    description="An OpenEnv-compliant debugging environment for AI agents",
    version="1.0.0",
)

# ── Mount Gradio demo at /demo ────────────────────────────────────────────────
try:
    import gradio as gr
    from demo.gradio_app import create_demo
    _gradio_demo = create_demo()
    app = gr.mount_gradio_app(app, _gradio_demo, path="/demo")
except ImportError:
    pass  # gradio not installed — API-only mode

# Single environment instance to manage the debugging lifecycle.
env = DebuggerEnvironment()


class ResetRequest(BaseModel):
    task_id: Optional[str] = "easy"


@app.get("/", include_in_schema=False)
async def root_redirect():
    return RedirectResponse(url="/demo")


@app.get("/api")
async def root():
    return {
        "name": "AgentDebuggerEnv",
        "version": "1.0.0",
        "description": (
            "An OpenEnv-compliant environment where AI agents debug broken code "
            "through iterative hypothesis-test-fix cycles. Unlike static benchmarks, "
            "agents act in a live sandbox and observe real execution output each step."
        ),
        "openenv_compliant": True,
        "domain": "software_engineering",
        "endpoints": {
            "GET  /":        "This overview",
            "GET  /health":  "Health check — returns 200 if server is live",
            "GET  /tasks":   "List all available tasks with metadata",
            "GET  /state":   "Current episode state",
            "POST /reset":   "Start a new episode. Body: {\"task_id\": \"easy\"|\"medium\"|\"hard\"}",
            "POST /step":    "Submit one action. Body: Action JSON",
        },
        "tasks": list_tasks(),
        "reward_type": "dense",
        "action_types": ["submit_fix", "query_context", "give_up"],
    }


@app.get("/tasks")
async def get_tasks():
    return {
        "tasks": [
            {
                "id": "easy",
                "name": "Single Function Off-By-One Bug",
                "difficulty": "easy",
                "max_attempts": 5,
                "max_steps": 8,
                "tests_total": 8,
                "description": (
                    "Binary search with an off-by-one termination condition. "
                    "Error message is clear and high-signal. 1-2 iterations expected."
                ),
            },
            {
                "id": "medium",
                "name": "Red Herring Authentication Bug",
                "difficulty": "medium",
                "max_attempts": 7,
                "max_steps": 15,
                "tests_total": 10,
                "description": (
                    "Authentication module where the error message points to the wrong "
                    "function. Agent must trace data flow backwards from symptom to root cause "
                    "and resist the red herring."
                ),
            },
            {
                "id": "hard",
                "name": "Concurrency Race Condition",
                "difficulty": "hard",
                "max_attempts": 10,
                "max_steps": 25,
                "tests_total": 8,
                "description": (
                    "Thread-safe counter with a race condition invisible to all sequential tests. "
                    "Agent must recognize that passing tests are insufficient proof of correctness, "
                    "design a concurrent stress test to surface the bug, then fix the atomicity issue."
                ),
            },
        ]
    }


@app.get("/health")
async def health():
    """Health check endpoint to verify server availability."""
    return {"status": "ok", "environment": "agentdebugger-env", "version": "1.0.0"}


@app.post("/reset")
async def reset(request: Optional[ResetRequest] = None):
    """Start a fresh episode. Returns initial Observation. Default to 'easy' task if body is missing."""
    try:
        task_id = request.task_id if request else "easy"
        observation = env.reset(task_id)
        return JSONResponse(content=observation, status_code=200)
    except ValueError as e:
        return JSONResponse(
            content={"error": str(e), "available_tasks": list_tasks()},
            status_code=400,
        )
    except Exception as e:
        return JSONResponse(
            content={"error": f"Internal error during reset: {str(e)}"},
            status_code=200,
        )


@app.post("/step")
async def step(action: Action):
    """Submit one action. Returns {observation, reward, done, info}. Always HTTP 200."""
    try:
        result = env.step(action)
        return JSONResponse(content=result, status_code=200)
    except Exception as e:
        # Never return 500 — all errors go in response body
        return JSONResponse(
            content={
                "observation": {},
                "reward": {
                    "step_reward": 0.0,
                    "cumulative_reward": 0.0,
                    "grader_score": 0.0,
                    "breakdown": {},
                },
                "done": False,
                "info": {"error": f"Internal error: {str(e)}"},
            },
            status_code=200,
        )


@app.get("/state")
async def get_state():
    """Return full internal environment state as a plain dict."""
    try:
        state = env.state()
        return JSONResponse(content=state, status_code=200)
    except Exception as e:
        return JSONResponse(
            content={"error": f"Internal error: {str(e)}"},
            status_code=200,
        )
