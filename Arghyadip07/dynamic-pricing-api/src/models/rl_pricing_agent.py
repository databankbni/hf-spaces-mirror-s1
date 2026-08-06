"""
Reinforcement Learning-based pricing agent for optimal price discovery.

The agent learns a pricing policy using Q-learning principles, where:
- State: market context (competitor price, inventory, day of week, etc.)
- Action: price to set (discretized)
- Reward: profit from the resulting demand
"""

from collections import deque
from dataclasses import dataclass
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from src.models.demand import build_feature_row

logger = logging.getLogger(__name__)


@dataclass
class Experience:
    """Single experience tuple for replay buffer."""

    state: dict
    action: float
    reward: float
    next_state: dict
    done: bool


class ReplayBuffer:
    """Experience replay buffer for Q-learning."""

    def __init__(self, max_size: int = 10000):
        """
        Initialize replay buffer.

        Args:
            max_size: Maximum number of experiences to store
        """
        self.buffer = deque(maxlen=max_size)

    def add(self, experience: Experience) -> None:
        """Add experience to buffer."""
        self.buffer.append(experience)

    def sample(self, batch_size: int) -> list[Experience]:
        """Sample random batch from buffer."""
        indices = np.random.choice(len(self.buffer), min(batch_size, len(self.buffer)), replace=False)
        return [self.buffer[i] for i in indices]

    def __len__(self) -> int:
        return len(self.buffer)


class RLPricingAgent:
    """Reinforcement Learning agent for dynamic pricing using Q-learning."""

    def __init__(
        self,
        demand_model,
        reference_row: pd.Series,
        price_range: tuple[float, float] | None = None,
        num_price_actions: int = 50,
        learning_rate: float = 0.01,
        discount_factor: float = 0.95,
        exploration_rate: float = 0.1,
    ):
        """
        Initialize RL pricing agent.

        Args:
            demand_model: Trained XGBoost demand model
            reference_row: Reference row with median feature values
            price_range: Optional fixed (min, max) price range. When None
                         the action space is built dynamically per market
                         context so there are no hard price boundaries.
            num_price_actions: Number of discrete price actions (default 50)
            learning_rate: Learning rate for Q-value updates
            discount_factor: Discount factor for future rewards (gamma)
            exploration_rate: Epsilon for epsilon-greedy exploration
        """
        self.demand_model = demand_model
        self.reference_row = reference_row
        self.price_range = price_range          # None = fully dynamic
        self.num_price_actions = num_price_actions
        self.learning_rate = learning_rate
        self.discount_factor = discount_factor
        self.exploration_rate = exploration_rate

        # Static action space only when price_range is explicitly provided
        self.action_space = (
            np.linspace(price_range[0], price_range[1], num_price_actions)
            if price_range is not None
            else None
        )

        # Q-table: state_hash -> {action_idx -> q_value}
        self.q_table: dict[str, dict[int, float]] = {}

        # Experience replay buffer
        self.replay_buffer = ReplayBuffer(max_size=10000)

        # Persistence metadata
        self._last_saved_at: str | None = None

    @property
    def policy_size(self) -> int:
        """Number of state entries in the Q-table."""
        return len(self.q_table)

    def _state_to_hash(self, state: dict) -> str:
        """
        Convert state dict to discrete hash for Q-table indexing.

        Discretizes continuous features for Q-learning.
        """
        # Discretize continuous features
        price_bin = int((state.get("competitor_price", 100) - 80) / 10) * 10
        inventory_bin = int((state.get("inventory", 500) - 100) / 200) * 200
        day = state.get("day_of_week", 2)
        cost_bin = int((state.get("unit_cost", 60) - 20) / 10) * 10

        return f"cp_{price_bin}_inv_{inventory_bin}_dow_{day}_cost_{cost_bin}"

    def get_q_value(self, state: dict, action_idx: int) -> float:
        """Get Q-value for state-action pair."""
        state_hash = self._state_to_hash(state)
        if state_hash not in self.q_table:
            self.q_table[state_hash] = {i: 0.0 for i in range(self.num_price_actions)}
        return self.q_table[state_hash].get(action_idx, 0.0)

    def set_q_value(self, state: dict, action_idx: int, value: float) -> None:
        """Set Q-value for state-action pair."""
        state_hash = self._state_to_hash(state)
        if state_hash not in self.q_table:
            self.q_table[state_hash] = {i: 0.0 for i in range(self.num_price_actions)}
        self.q_table[state_hash][action_idx] = value

    def get_max_q_value(self, state: dict) -> float:
        """Get maximum Q-value for a state."""
        state_hash = self._state_to_hash(state)
        if state_hash not in self.q_table:
            return 0.0
        return max(self.q_table[state_hash].values())

    def select_action(self, state: dict, training: bool = True) -> int:
        """
        Select action using epsilon-greedy policy.

        Args:
            state: Current market state
            training: If True, use exploration; if False, exploit only

        Returns:
            Action index (price index)
        """
        if training and np.random.random() < self.exploration_rate:
            # Exploration: random action
            return np.random.randint(0, self.num_price_actions)
        else:
            # Exploitation: greedy action
            state_hash = self._state_to_hash(state)
            if state_hash not in self.q_table:
                self.q_table[state_hash] = {i: 0.0 for i in range(self.num_price_actions)}

            q_values = self.q_table[state_hash]
            max_q = max(q_values.values())
            best_actions = [a for a, q in q_values.items() if q == max_q]
            return np.random.choice(best_actions)

    def calculate_reward(
        self,
        price: float,
        competitor_price: float,
        inventory: int,
        day_of_week: int,
        unit_cost: float = 60.0,
    ) -> float:
        """
        Calculate reward (profit) from a pricing action.

        Args:
            price: Price set by agent
            competitor_price: Competitor price
            inventory: Current inventory
            day_of_week: Day of week
            unit_cost: Unit cost

        Returns:
            Profit (reward), always 0 if price <= unit_cost (no selling below cost)
        """
        # Guard: never reward pricing below cost
        if price <= unit_cost:
            return 0.0

        X = build_feature_row(
            price=price,
            competitor_price=competitor_price,
            inventory=inventory,
            day_of_week=day_of_week,
            reference_row=self.reference_row,
        )
        predicted_demand = float(self.demand_model.predict(X)[0])
        # Demand physically cannot drop below 0
        predicted_demand = max(0.0, predicted_demand)
        
        profit = (price - unit_cost) * predicted_demand
        return max(0.0, profit)

    def update_q_value(self, state: dict, action_idx: int, reward: float, next_state: dict, done: bool) -> None:
        """
        Update Q-value using Q-learning update rule.

        Q(s,a) = Q(s,a) + α * (r + γ * max_a'(Q(s',a')) - Q(s,a))

        Args:
            state: Current state
            action_idx: Action taken
            reward: Reward received
            next_state: Next state
            done: Whether episode is done
        """
        current_q = self.get_q_value(state, action_idx)
        max_next_q = self.get_max_q_value(next_state) if not done else 0.0

        new_q = current_q + self.learning_rate * (reward + self.discount_factor * max_next_q - current_q)
        self.set_q_value(state, action_idx, new_q)

    def train_step(self, batch_size: int = 32) -> float | None:
        """
        Train agent on batch from replay buffer.

        Args:
            batch_size: Size of batch to train on

        Returns:
            Average loss for the batch, or None if buffer too small
        """
        if len(self.replay_buffer) < batch_size:
            return None

        batch = self.replay_buffer.sample(batch_size)
        total_loss = 0.0

        for experience in batch:
            # Experience.action stores the price value (float); we use the
            # Q-learning update directly with reward rather than re-indexing.
            # Find the closest action index in the current action space.
            if self.action_space is not None:
                action_idx = int(np.argmin(np.abs(self.action_space - experience.action)))
            else:
                action_idx = 0
            self.update_q_value(
                experience.state,
                action_idx,
                experience.reward,
                experience.next_state,
                experience.done,
            )
            total_loss += abs(experience.reward)

        return total_loss / len(batch)

    def _build_action_space(
        self,
        unit_cost: float,
        competitor_price: float,
    ) -> np.ndarray:
        """
        Build a dynamic action space from market context.

        floor   = unit_cost * 1.05  (5% above break-even to ensure positive margin)
        ceiling = min(max(competitor_price * 2.0, unit_cost * 4.0), unit_cost * 10.0)

        The ceiling cap (unit_cost * 10) prevents the agent from exploring
        wildly high prices that are far outside the demand model's training
        range, which would cause unreliable demand predictions.
        """
        if self.price_range is not None:
            return np.linspace(self.price_range[0], self.price_range[1], self.num_price_actions)
        floor = unit_cost * 1.05
        ceiling = min(
            max(competitor_price * 2.0, unit_cost * 4.0),
            unit_cost * 10.0,
        )
        if ceiling <= floor:
            ceiling = floor * 2.0
        return np.linspace(floor, ceiling, self.num_price_actions)

    def get_optimal_price(
        self,
        competitor_price: float,
        inventory: int,
        day_of_week: int,
        unit_cost: float = 60.0,
    ) -> tuple[float, float]:
        """
        Get optimal price using learned policy.

        The action space is built dynamically from unit_cost and
        competitor_price so the agent can recommend any price — not
        just prices within a fixed (50, 150) window.

        Returns:
            Tuple of (optimal_price, expected_profit)
        """
        # Build context-aware action space for this call
        # All prices in this space are guaranteed to be above unit_cost
        action_space = self._build_action_space(unit_cost, competitor_price)
        self.action_space = action_space          # keep in sync for select_action

        state = {
            "competitor_price": competitor_price,
            "inventory": inventory,
            "day_of_week": day_of_week,
            "unit_cost": unit_cost,
        }

        # Select action using greedy policy (no exploration in deployment)
        action_idx = self.select_action(state, training=False)
        price = float(action_space[action_idx])

        # Calculate expected profit from the Q-table's choice
        profit = self.calculate_reward(
            price=price,
            competitor_price=competitor_price,
            inventory=inventory,
            day_of_week=day_of_week,
            unit_cost=unit_cost,
        )

        # Smart Fallback for Untrained or Poorly-Trained States
        # If the Q-table's choice yields 0 or negligible profit (<= 1.0),
        # it means the agent hasn't converged on a good policy for this state.
        if profit <= 1.0:
            # Active evaluation: calculate reward for all actions to find the best profitable price
            best_profit = -1.0
            best_price = float(action_space[0])
            for p in action_space:
                prof = self.calculate_reward(
                    price=float(p),
                    competitor_price=competitor_price,
                    inventory=inventory,
                    day_of_week=day_of_week,
                    unit_cost=unit_cost,
                )
                if prof > best_profit:
                    best_profit = prof
                    best_price = float(p)
            
            price = best_price
            profit = max(0.0, best_profit)
        else:
            # Safety net: if Q-table picked an action that is still below unit_cost
            if price <= unit_cost:
                state_hash = self._state_to_hash(state)
                q_values = self.q_table.get(state_hash, {})
                profitable_actions = [
                    (q, idx) for idx, q in q_values.items()
                    if float(action_space[idx]) > unit_cost
                ]
                if profitable_actions:
                    best_idx = max(profitable_actions)[1]
                    price = float(action_space[best_idx])
                    profit = self.calculate_reward(
                        price=price, competitor_price=competitor_price, 
                        inventory=inventory, day_of_week=day_of_week, unit_cost=unit_cost
                    )
                else:
                    price = float(action_space[0])  # floor = unit_cost * 1.05
                    profit = self.calculate_reward(
                        price=price, competitor_price=competitor_price, 
                        inventory=inventory, day_of_week=day_of_week, unit_cost=unit_cost
                    )

        return price, profit

    def add_experience(
        self,
        state: dict,
        action_idx: int,
        reward: float,
        next_state: dict,
        done: bool = False,
    ) -> None:
        """Add experience to replay buffer."""
        # action_space may be None before first get_optimal_price call;
        # fall back to storing action_idx itself as the price value.
        if self.action_space is not None:
            action_price = float(self.action_space[action_idx])
        else:
            action_price = float(action_idx)
        experience = Experience(
            state=state,
            action=action_price,
            reward=reward,
            next_state=next_state,
            done=done,
        )
        self.replay_buffer.add(experience)

    # ------------------------------------------------------------------
    # Policy persistence
    # ------------------------------------------------------------------

    def save_policy(self, path: str | Path) -> None:
        """
        Persist the Q-table to a JSON file so the learned policy survives
        API restarts.

        Saved fields:
          - q_table: the full state→action→Q-value mapping
          - num_price_actions: needed to restore action index semantics
          - learning_rate / discount_factor / exploration_rate: hyperparams
          - replay_buffer_size: informational
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        from datetime import datetime, timezone
        saved_at = datetime.now(timezone.utc).isoformat()

        payload = {
            "saved_at": saved_at,
            "num_price_actions": self.num_price_actions,
            "learning_rate": self.learning_rate,
            "discount_factor": self.discount_factor,
            "exploration_rate": self.exploration_rate,
            "policy_size": self.policy_size,
            "replay_buffer_size": len(self.replay_buffer),
            "q_table": {
                state_hash: {str(k): v for k, v in actions.items()}
                for state_hash, actions in self.q_table.items()
            },
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)

        self._last_saved_at = saved_at
        logger.info("RL policy saved → %s  (states=%d)", path, self.policy_size)

    def load_policy(self, path: str | Path) -> bool:
        """
        Load a previously saved Q-table from JSON.

        Returns True on success, False if the file does not exist or is corrupt.
        The agent remains functional even if loading fails (starts fresh).
        """
        path = Path(path)
        if not path.exists():
            logger.info("No saved RL policy found at %s — starting fresh.", path)
            return False

        try:
            with open(path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)

            # Restore Q-table (keys are int action indices stored as strings)
            self.q_table = {
                state_hash: {int(k): float(v) for k, v in actions.items()}
                for state_hash, actions in payload.get("q_table", {}).items()
            }
            self._last_saved_at = payload.get("saved_at")
            logger.info(
                "RL policy loaded ← %s  (states=%d, saved_at=%s)",
                path, self.policy_size, self._last_saved_at,
            )
            return True
        except Exception as exc:
            logger.warning("Failed to load RL policy from %s: %s — starting fresh.", path, exc)
            self.q_table = {}
            return False
