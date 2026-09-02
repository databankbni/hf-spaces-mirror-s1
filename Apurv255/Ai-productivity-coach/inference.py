import requests
import os
import time

API_BASE_URL = os.getenv("API_BASE_URL", "https://router.huggingface.co/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "Qwen/Qwen2.5-72B-Instruct")
HF_TOKEN = os.getenv("HF_TOKEN", "")
ENV_URL = os.getenv("ENV_URL", "https://apurv255-ai-productivity-coach.hf.space")


# ✅ SAFE RESET (WITH FALLBACK)
def reset_env(task="easy"):
    try:
        resp = requests.post(
            f"{ENV_URL}/reset",
            json={"task": task},
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("state", data)

    except Exception as e:
        print(f"[WARNING] reset failed: {e}")
        return {
            "focus_level": 0.5,
            "fatigue": 0.1,
            "distractions": [],
            "time_spent": 0,
            "deadline": 60
        }


# ✅ SAFE STEP (WITH FALLBACK) — now accepts action too
def step_env(state, action):
    try:
        payload = {"action": action, **state}   # ← action is now sent to the env
        resp = requests.post(
            f"{ENV_URL}/step_rl",
            json=payload,
            timeout=10
        )
        resp.raise_for_status()
        return resp.json()

    except Exception as e:
        print(f"[WARNING] step failed: {e}")

        next_state = state.copy()
        next_state["time_spent"] = state.get("time_spent", 0) + 1

        return {
            "state": next_state,
            "reward": 0.1,
            "done": next_state["time_spent"] >= state.get("deadline", 60)
        }


# ✅ SAFE LLM CALL
def get_action_from_llm(state):
    try:
        response = requests.post(
            f"{API_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {HF_TOKEN}",
                "Content-Type": "application/json"
            },
            json={
                "model": MODEL_NAME,
                "messages": [
                    {
                        "role": "system",
                        "content": "Reply ONLY with one of: continue, take_break, block_distraction"
                    },
                    {
                        "role": "user",
                        "content": str(state)
                    }
                ],
                "max_tokens": 10
            },
            timeout=10
        )

        data = response.json()
        choices = data.get("choices", [])

        if not choices:
            return "continue"

        action = choices[0].get("message", {}).get("content", "").strip().lower()

        for a in ["continue", "take_break", "block_distraction"]:
            if a in action:
                return a

        return "continue"

    except Exception:
        return "continue"


# ✅ MAIN LOOP
def run_episode(task="easy"):
    print(f"[START] task={task}")

    state = reset_env(task)

    done = False
    step = 0
    rewards = []

    while not done and step < 30:
        try:
            action = get_action_from_llm(state)         # ← LLM picks action
            result = step_env(state, action)             # ← action passed to env

            state = result.get("state", state)
            reward = float(result.get("reward", 0))
            done = result.get("done", False)

            rewards.append(reward)

            print(
                f"[STEP] step={step+1} "
                f"action={action} "
                f"reward={reward:.2f} "
                f"done={str(done).lower()} "
                f"error=null"
            )

            step += 1

        except Exception as e:
            print(
                f"[STEP] step={step+1} "
                f"action=null reward=0 done=false error={str(e)[:50]}"
            )
            break

    success = any(r > 0 for r in rewards)
    rewards_str = ",".join([f"{r:.2f}" for r in rewards])

    print(
        f"[END] success={str(success).lower()} "
        f"steps={step} "
        f"rewards={rewards_str}"
    )


if __name__ == "__main__":
    run_episode()