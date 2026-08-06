import random
from typing import Dict, Tuple, Any


class CapacityPricingEnv:
    """A minimal capacity-aware pricing environment.

    Observations (dict): {
        'base_demand': float,
        'capacity': float,
        'unit_cost': float,
        'last_price': float,
    }

    Action: a single price (float)

    Reward: revenue - production_cost - overtime_penalty
    """

    def __init__(self, base_demand: float = 100.0, capacity: float = 80.0, unit_cost: float = 60.0):
        self.base_demand = float(base_demand)
        self.capacity = float(capacity)
        self.unit_cost = float(unit_cost)
        self.timestep = 0
        self.last_price = float(unit_cost)

    def reset(self) -> Dict[str, float]:
        self.timestep = 0
        self.last_price = float(self.unit_cost)
        return self._obs()

    def _obs(self) -> Dict[str, float]:
        return {
            "base_demand": self.base_demand,
            "capacity": self.capacity,
            "unit_cost": self.unit_cost,
            "last_price": self.last_price,
        }

    def sample_action(self) -> float:
        """Return a sample price between 80% and 150% of unit cost."""
        return round(random.uniform(0.8 * self.unit_cost, 1.5 * self.unit_cost), 2)

    def step(self, price: float) -> Tuple[Dict[str, float], float, bool, Dict[str, Any]]:
        """Apply price action and return (obs, reward, done, info)."""
        self.timestep += 1
        self.last_price = float(price)

        # Simple price elasticity model: demand falls linearly above unit cost
        # elasticity_factor controls sensitivity
        elasticity_factor = 0.02
        demand_multiplier = max(0.0, 1.0 - elasticity_factor * (price - self.unit_cost))
        stochastic = random.uniform(0.9, 1.1)
        demand = max(0.0, self.base_demand * demand_multiplier * stochastic)

        produced = min(demand, self.capacity)
        overtime = max(0.0, demand - self.capacity)

        revenue = produced * price
        production_cost = produced * self.unit_cost
        overtime_cost = overtime * self.unit_cost * 1.5  # premium for overtime

        # Penalty term to discourage excessive overtime / late fulfillment
        overtime_penalty = overtime * 10.0

        reward = revenue - production_cost - overtime_cost - overtime_penalty

        obs = self._obs()
        done = False
        info = {
            "demand": demand,
            "produced": produced,
            "overtime": overtime,
            "revenue": revenue,
            "production_cost": production_cost,
        }
        return obs, reward, done, info


if __name__ == "__main__":
    # quick interactive demo
    env = CapacityPricingEnv()
    print("Reset:", env.reset())
    for _ in range(5):
        a = env.sample_action()
        obs, reward, done, info = env.step(a)
        print(f"price={a} reward={reward:.2f} info={info}")
