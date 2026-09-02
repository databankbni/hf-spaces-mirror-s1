from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional

from app.env import ProductivityEnv
from app.models import Action
from app.agent import FocusAgent

import uvicorn
import os
import math


# --------------------------------------------------
# APP INITIALIZATION
# --------------------------------------------------

app = FastAPI(title="AI Productivity Coach")

env = ProductivityEnv()
agent = FocusAgent()


# --------------------------------------------------
# REQUEST MODELS
# --------------------------------------------------

class ResetRequest(BaseModel):
    task_type: str = "easy"


class StepRequest(BaseModel):
    action: str
    target: Optional[str] = None


class AdviceRequest(BaseModel):
    focus_level: float = 0.5
    fatigue: float = 0.1
    distractions: List[str] = []
    time_spent: int = 0
    deadline: int = 60


# --------------------------------------------------
# HEALTH CHECK
# --------------------------------------------------

@app.get("/health")
def health():
    return {
        "status": "ok"
    }


# --------------------------------------------------
# RESET ENVIRONMENT
# --------------------------------------------------

@app.post("/reset")
def reset(body: ResetRequest):

    try:

        state = env.reset(
            task_type=body.task_type
        )

        return {
            "state": state.dict()
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# --------------------------------------------------
# MANUAL RL STEP
# --------------------------------------------------

@app.post("/step_rl")
def step_rl(body: StepRequest):

    action = Action(
        action=body.action,
        target=body.target
    )

    try:

        next_obs, reward, done, _ = env.step(
            action
        )

    except Exception as e:

        raise HTTPException(
            status_code=400,
            detail=str(e)
        )

    return {
        "state": next_obs.dict(),
        "reward": reward.value,
        "done": done
    }


# --------------------------------------------------
# AI PRODUCTIVITY ADVICE
# --------------------------------------------------

@app.post("/step")
def step_advice(body: AdviceRequest):
    """
    Uses the trained Q-learning agent to select
    an action based on the current productivity state.
    """

    # -----------------------------------------------
    # BUILD CURRENT STATE
    # -----------------------------------------------

    state = {
        "focus_level": body.focus_level,
        "fatigue": body.fatigue,
        "distractions": body.distractions,
        "time_spent": body.time_spent,
        "deadline": max(body.deadline, 1)
    }


    try:

        # -------------------------------------------
        # GET ACTION FROM Q-LEARNING POLICY
        # -------------------------------------------

        action, agent_reason = agent.decide(
            state,
            training=False
        )

        action_type = action.action


        # -------------------------------------------
        # GET LEARNED Q-VALUES
        # -------------------------------------------

        q_values = agent.get_q_values(
            state
        )

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Agent error: {str(e)}"
        )


    # --------------------------------------------------
    # GENERATE USER-FRIENDLY ADVICE
    # --------------------------------------------------

    if action_type == "take_break":

        advice = (
            f"Your fatigue is currently "
            f"{body.fatigue:.2f}. "
            "The learned policy recommends "
            "taking a short 5–10 minute break "
            "to restore your focus."
        )


    elif action_type == "block_distraction":

        if body.distractions:

            target = body.distractions[0]

        else:

            target = (
                action.target
                or "your distractions"
            )

        advice = (
            f'"{target}" is affecting your focus. '
            "The learned policy recommends "
            "blocking this distraction."
        )


    else:

        advice = (
            f"Your focus is currently "
            f"{body.focus_level:.2f}. "
            "The learned policy recommends "
            "continuing with the task."
        )


    # --------------------------------------------------
    # Q-VALUE BASED CONFIDENCE
    # --------------------------------------------------

    confidence = 0.0

    if q_values:

        # Make sure all three actions are present
        ordered_values = [
            float(
                q_values.get(
                    action_name,
                    0.0
                )
            )
            for action_name in agent.actions
        ]

        # Stable softmax
        max_q = max(
            ordered_values
        )

        exp_values = [
            math.exp(
                q_value - max_q
            )
            for q_value in ordered_values
        ]

        total_exp = sum(
            exp_values
        )

        if total_exp > 0:

            probabilities = [
                value / total_exp
                for value in exp_values
            ]

            selected_index = (
                agent.actions.index(
                    action_type
                )
            )

            confidence = probabilities[
                selected_index
            ]


    # -----------------------------------------------
    # FALLBACK
    # -----------------------------------------------

    else:

        # No learned Q-values available
        confidence = 0.0


    # Keep value between 0 and 1
    confidence = max(
        0.0,
        min(
            1.0,
            confidence
        )
    )


    # --------------------------------------------------
    # RESPONSE
    # --------------------------------------------------

    return {

        "advice": advice,

        # Selected action
        "suggested_action": action_type,
        "action": action_type,

        # Q-learning explanation
        "reason": agent_reason,

        # Current state
        "current_focus": body.focus_level,
        "current_fatigue": body.fatigue,

        # Q-learning based confidence
        "confidence": round(
            confidence,
            2
        ),

        # Expose Q-values for transparency/debugging
        "q_values": q_values
    }


# --------------------------------------------------
# SCORE
# --------------------------------------------------

@app.get("/score")
def score():

    try:

        return agent.get_score(env)

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Scoring error: {str(e)}"
        )


# --------------------------------------------------
# SERVE FRONTEND
# --------------------------------------------------

APP_DIR = os.path.dirname(
    os.path.abspath(__file__)
)


app.mount(
    "/static",
    StaticFiles(
        directory=APP_DIR
    ),
    name="static"
)


@app.get("/")
def root():

    index_file = os.path.join(
        APP_DIR,
        "index.html"
    )

    if os.path.exists(index_file):

        return FileResponse(
            index_file
        )

    return {
        "message":
        "AI Productivity Coach API is running!"
    }


# --------------------------------------------------
# RUN SERVER
# --------------------------------------------------

if __name__ == "__main__":

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=7860
    )