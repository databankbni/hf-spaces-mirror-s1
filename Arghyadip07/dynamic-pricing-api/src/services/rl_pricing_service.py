"""RL-based pricing service for learning optimal pricing policies."""

from dataclasses import dataclass

from src.core.settings import settings
from src.models.demand import load_or_train_model_artifact
from src.models.rl_pricing_agent import RLPricingAgent


@dataclass
class RLPricingInput:
    """Input parameters for RL pricing recommendation."""

    competitor_price: float
    inventory: int
    day_of_week: int
    unit_cost: float = 60.0


class RLPricingService:
    """Service for RL-based pricing policy."""

    def __init__(self, data_path: str | None = None, artifact_path: str | None = None, rl_policy_path: str | None = None):
        """
        Initialize the RL pricing service.

        Args:
            data_path: Path to processed data (default: from settings)
            artifact_path: Path to model artifact (default: from settings)
            rl_policy_path: Path to persist/load the Q-table JSON (default: artifacts/rl_q_table.json)
        """
        self.data_path = data_path or str(settings.processed_data_abspath)
        self.artifact_path = artifact_path or str(settings.model_artifact_abspath)
        self.rl_policy_path = rl_policy_path or str(settings.project_root / "artifacts" / "rl_q_table.json")
        self.demand_model = None
        self.reference_row = None
        self.rl_agent = None

    def startup(self):
        """Load or train the demand model, initialize RL agent, and restore saved policy."""
        self.demand_model, self.reference_row, _ = load_or_train_model_artifact(
            data_path=self.data_path,
            artifact_path=self.artifact_path,
        )
        self.rl_agent = RLPricingAgent(
            demand_model=self.demand_model,
            reference_row=self.reference_row,
            learning_rate=0.05,
            exploration_rate=0.15,
        )
        # Restore previously learned policy if it exists
        self.rl_agent.load_policy(self.rl_policy_path)

    def get_rl_price(self, payload: RLPricingInput) -> dict:
        """
        Get price recommendation using RL policy.

        Args:
            payload: RLPricingInput with market context

        Returns:
            Dictionary with RL-based pricing recommendation
        """
        if self.rl_agent is None:
            self.startup()

        if self.rl_agent is None:
            raise RuntimeError("RLPricingService failed to initialize model artifacts")

        price, profit = self.rl_agent.get_optimal_price(
            competitor_price=payload.competitor_price,
            inventory=payload.inventory,
            day_of_week=payload.day_of_week,
            unit_cost=payload.unit_cost,
        )

        return {
            "rl_price": price,
            "expected_profit": profit,
            "strategy": "RL Policy",
        }

    def train_on_experience(
        self,
        competitor_price: float,
        inventory: int,
        day_of_week: int,
        unit_cost: float = 60.0,
        num_episodes: int = 5,
        save_policy: bool = True,
    ) -> dict:
        """
        Train RL agent on simulated experiences.

        Args:
            competitor_price: Competitor price
            inventory: Current inventory
            day_of_week: Day of week
            unit_cost: Unit cost
            num_episodes: Number of training episodes

        Returns:
            Training results with average rewards
        """
        if self.rl_agent is None:
            self.startup()

        if self.rl_agent is None:
            raise RuntimeError("RLPricingService failed to initialize model artifacts")

        episode_rewards = []

        for episode in range(num_episodes):
            state = {
                "competitor_price": competitor_price,
                "inventory": inventory,
                "day_of_week": day_of_week,
                "unit_cost": unit_cost,
            }

            # Agent selects action (price)
            action_space = self.rl_agent._build_action_space(unit_cost, competitor_price)
            self.rl_agent.action_space = action_space
            action_idx = self.rl_agent.select_action(state, training=True)
            price = self.rl_agent.action_space[action_idx]

            # Calculate reward
            reward = self.rl_agent.calculate_reward(
                price=price,
                competitor_price=competitor_price,
                inventory=inventory,
                day_of_week=day_of_week,
                unit_cost=unit_cost,
            )

            # Next state (simulate slight inventory depletion)
            # Safeguard against division by zero when price equals unit_cost
            margin = max(1, price - unit_cost)
            next_inventory = max(0, inventory - int(reward / margin))
            next_state = {
                "competitor_price": competitor_price,
                "inventory": next_inventory,
                "day_of_week": day_of_week,
                "unit_cost": unit_cost,
            }

            # Store experience and update Q-values
            self.rl_agent.add_experience(state, action_idx, reward, next_state, done=False)
            self.rl_agent.update_q_value(state, action_idx, reward, next_state, done=False)

            episode_rewards.append(float(reward))

        # Train on buffer
        avg_loss = self.rl_agent.train_step(batch_size=8)

        result = {
            "episodes_completed": num_episodes,
            "average_reward": sum(episode_rewards) / len(episode_rewards) if episode_rewards else 0.0,
            "max_reward": max(episode_rewards) if episode_rewards else 0.0,
            "buffer_size": len(self.rl_agent.replay_buffer),
        }

        # Persist the updated Q-table after every training run if requested
        if save_policy:
            self.rl_agent.save_policy(self.rl_policy_path)

        return result

    def save_policy(self) -> None:
        """Explicitly save the current Q-table to disk."""
        if self.rl_agent is not None:
            self.rl_agent.save_policy(self.rl_policy_path)

    def policy_info(self) -> dict:
        """Return metadata about the current policy state."""
        if self.rl_agent is None:
            return {"status": "not_initialized"}
        return {
            "policy_size": self.rl_agent.policy_size,
            "replay_buffer_size": len(self.rl_agent.replay_buffer),
            "last_saved_at": self.rl_agent._last_saved_at,
            "policy_path": self.rl_policy_path,
        }

    def reload_model(self, model, reference_row) -> None:
        """Update the live demand model and reference row."""
        self.demand_model = model
        self.reference_row = reference_row
        if self.rl_agent is not None:
            self.rl_agent.demand_model = model
            self.rl_agent.reference_row = reference_row
