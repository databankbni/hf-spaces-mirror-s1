"""Example runner for the capacity-aware pricing environment.

This script ensures the project root is on `sys.path` so it can be
executed directly with `python scripts/run_capacity_sim.py`.
"""
import sys
from pathlib import Path


def _ensure_project_root_on_path() -> None:
    project_root = Path(__file__).resolve().parents[1]
    project_root_str = str(project_root)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)


_ensure_project_root_on_path()

from src.experiments.simulators.capacity_env import CapacityPricingEnv


def run_demo(steps: int = 10):
    env = CapacityPricingEnv()
    obs = env.reset()
    print("Initial obs:", obs)
    total_reward = 0.0
    for t in range(steps):
        price = env.sample_action()
        obs, reward, done, info = env.step(price)
        total_reward += reward
        print(f"t={t} price={price} reward={reward:.2f} info={info}")
    print(f"Total reward after {steps} steps: {total_reward:.2f}")


if __name__ == "__main__":
    run_demo(steps=10)
