from fastapi import APIRouter, Query

from src.api.runtime import runtime


router = APIRouter()


@router.post("/agent/start")
def agent_start() -> dict:
    if runtime.pricing_agent.is_running:
        return {"status": "already_running", "message": "Agent is already running."}
    runtime.pricing_agent.start()
    return {"status": "started", "message": "Autonomous pricing agent started."}


@router.post("/agent/stop")
def agent_stop() -> dict:
    if not runtime.pricing_agent.is_running:
        return {"status": "already_stopped", "message": "Agent is not running."}
    runtime.pricing_agent.stop()
    return {"status": "stopped", "message": "Autonomous pricing agent stopped."}


@router.get("/agent/status")
def agent_status() -> dict:
    return runtime.pricing_agent.get_status()


@router.get("/agent/history")
def agent_history(limit: int = Query(default=50, ge=1, le=500)) -> list[dict]:
    return runtime.pricing_agent.get_history(limit=limit)


@router.post("/agent/interval")
def agent_set_interval(seconds: float = Query(..., ge=5, le=3600)) -> dict:
    runtime.pricing_agent.set_interval(seconds)
    return {"status": "updated", "interval_seconds": runtime.pricing_agent.interval_seconds}


@router.get("/agent/policy_info")
def agent_policy_info() -> dict:
    """Return RL Q-table persistence metadata: size, last save time, file path."""
    return runtime.rl_pricing_service.policy_info()