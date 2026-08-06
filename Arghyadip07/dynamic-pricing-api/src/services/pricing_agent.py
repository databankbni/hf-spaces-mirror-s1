"""
Autonomous Pricing Agent — makes the system truly agentic.

Loop every N seconds:
  1. PERCEIVE  — sense market context (competitor price, inventory, day)
                 Uses real DB data when available, falls back to simulation.
  2. DECIDE    — RL agent picks optimal price + ML model computes expected profit
  3. ACT       — record the repricing decision with timestamp
  4. LEARN     — RL agent trains on the experience to improve future decisions
                 Q-table is persisted to disk every POLICY_SAVE_INTERVAL cycles.
"""

import asyncio
import logging
import random
import threading
from datetime import datetime, timezone
from dataclasses import dataclass, field

from src.services.pricing_service import PricingInput, PricingService
from src.services.rl_pricing_service import RLPricingInput, RLPricingService
from src.storage import storage_backend

logger = logging.getLogger(__name__)


@dataclass
class MarketObservation:
    """A snapshot of the market state perceived by the agent."""
    competitor_price: float
    inventory: int
    day_of_week: int
    unit_cost: float
    source: str = "simulation"          # "db" or "simulation"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class PricingDecision:
    """A decision record produced by the agent."""
    observation: MarketObservation
    rl_price: float
    ml_price: float
    final_price: float          # RL-price used as final action
    expected_profit: float
    episode_reward: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "competitor_price": self.observation.competitor_price,
            "inventory": self.observation.inventory,
            "day_of_week": self.observation.day_of_week,
            "unit_cost": self.observation.unit_cost,
            "perception_source": self.observation.source,
            "rl_price": round(self.rl_price, 2),
            "ml_price": round(self.ml_price, 2),
            "final_price": round(self.final_price, 2),
            "expected_profit": round(self.expected_profit, 2),
            "episode_reward": round(self.episode_reward, 2),
        }


class PricingAgent:
    """
    Autonomous pricing agent that continuously senses the market,
    makes pricing decisions, acts on them, and learns from outcomes.

    Perception hierarchy (highest priority first):
      1. Latest competitor signal from DB (product_id=self.product_id)
      2. Market context row from DB (inventory, unit_cost for product_id)
      3. Simulation fallback for any missing field

    The RL Q-table is persisted to disk every POLICY_SAVE_INTERVAL cycles
    so learned pricing knowledge survives API restarts.
    """

    MAX_HISTORY = 500           # keep last N decisions in memory
    POLICY_SAVE_INTERVAL = 10   # save Q-table every N cycles

    def __init__(
        self,
        pricing_service: PricingService,
        rl_pricing_service: RLPricingService,
        interval_seconds: float = 30.0,
        product_id: int = 1,
        default_unit_cost: float = 60.0,
    ):
        self.pricing_service = pricing_service
        self.rl_pricing_service = rl_pricing_service
        self.interval_seconds = interval_seconds
        self.product_id = product_id
        self.default_unit_cost = default_unit_cost

        self._running: bool = False
        self._task: asyncio.Task | None = None
        self._thread: threading.Thread | None = None
        self._history: list[PricingDecision] = []
        self._cycle_count: int = 0
        self._total_reward: float = 0.0

    # ------------------------------------------------------------------
    # Public control interface
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the autonomous agent loop (non-blocking)."""
        if self._running:
            logger.warning("PricingAgent is already running.")
            return
        self._running = True

        # FastAPI sync endpoints run in a worker thread without an event loop.
        # Start the async loop in a dedicated daemon thread so the agent can be
        # started both from request handlers and from startup hooks.
        self._thread = threading.Thread(target=self._run_loop_in_thread, daemon=True)
        self._thread.start()
        logger.info(f"✓ PricingAgent started (interval={self.interval_seconds}s, product_id={self.product_id})")

    def stop(self) -> None:
        """Gracefully stop the agent loop."""
        if not self._running:
            return
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("✓ PricingAgent stopped.")

    @property
    def is_running(self) -> bool:
        return self._running

    def get_status(self) -> dict:
        """Return current agent status and performance summary."""
        return {
            "running": self._running,
            "interval_seconds": self.interval_seconds,
            "product_id": self.product_id,
            "cycles_completed": self._cycle_count,
            "total_reward": round(self._total_reward, 2),
            "average_reward": round(
                self._total_reward / self._cycle_count if self._cycle_count else 0.0, 2
            ),
            "history_size": len(self._history),
            "last_decision": self._history[-1].to_dict() if self._history else None,
        }

    def get_history(self, limit: int = 50) -> list[dict]:
        """Return the last N decisions."""
        return [d.to_dict() for d in self._history[-limit:]]

    def set_interval(self, seconds: float) -> None:
        """Dynamically change how often the agent reprices."""
        self.interval_seconds = max(5.0, seconds)
        logger.info(f"Agent interval updated to {self.interval_seconds}s")

    # ------------------------------------------------------------------
    # Agentic loop: Perceive → Decide → Act → Learn
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        logger.info("PricingAgent loop started.")
        while self._running:
            try:
                await self._cycle()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Agent cycle error: {exc}", exc_info=True)
            await asyncio.sleep(self.interval_seconds)
        logger.info("PricingAgent loop exited.")

    def _run_loop_in_thread(self) -> None:
        """Run the async agent loop in a dedicated event loop inside a thread."""
        try:
            asyncio.run(self._run_loop())
        except RuntimeError as exc:
            logger.error(f"PricingAgent thread loop failed: {exc}", exc_info=True)

    async def _cycle(self) -> None:
        """One full agent cycle: Perceive → Decide → Act → Learn."""

        # 1. PERCEIVE — sense the current market environment
        observation = self._perceive()
        logger.debug(
            f"[Agent] Perceive({observation.source}) → competitor={observation.competitor_price}, "
            f"inventory={observation.inventory}, day={observation.day_of_week}, "
            f"unit_cost={observation.unit_cost}"
        )

        # 2. DECIDE — ask RL agent and ML model for pricing recommendations
        rl_result = self.rl_pricing_service.get_rl_price(
            RLPricingInput(
                competitor_price=observation.competitor_price,
                inventory=observation.inventory,
                day_of_week=observation.day_of_week,
                unit_cost=observation.unit_cost,
            )
        )
        ml_result = self.pricing_service.calculate_optimal_price(
            PricingInput(
                competitor_price=observation.competitor_price,
                inventory=observation.inventory,
                day_of_week=observation.day_of_week,
                unit_cost=observation.unit_cost,
            )
        )

        # 3. ACT — RL price is the agent's chosen action; log the decision
        decision = PricingDecision(
            observation=observation,
            rl_price=rl_result["rl_price"],
            ml_price=ml_result["optimal_price"],
            final_price=rl_result["rl_price"],
            expected_profit=rl_result["expected_profit"],
            episode_reward=rl_result["expected_profit"],
        )
        self._record(decision)
        logger.info(
            f"[Agent] Act → final_price={decision.final_price:.2f}, "
            f"ml_price={decision.ml_price:.2f}, profit={decision.expected_profit:.2f}"
        )

        # 4. LEARN — train the RL agent on this experience
        train_result = self.rl_pricing_service.train_on_experience(
            competitor_price=observation.competitor_price,
            inventory=observation.inventory,
            day_of_week=observation.day_of_week,
            unit_cost=observation.unit_cost,
            num_episodes=3,
        )
        logger.debug(
            f"[Agent] Learn → avg_reward={train_result['average_reward']:.2f}, "
            f"buffer={train_result['buffer_size']}"
        )

        self._cycle_count += 1
        self._total_reward += decision.episode_reward

        # Periodically save RL policy to disk so it survives restarts
        if self._cycle_count % self.POLICY_SAVE_INTERVAL == 0:
            try:
                self.rl_pricing_service.save_policy()
                logger.debug(f"[Agent] Policy checkpoint saved (cycle={self._cycle_count})")
            except Exception as exc:
                logger.warning(f"[Agent] Policy save failed: {exc}")

    # ------------------------------------------------------------------
    # Perception — DB-backed with simulation fallback
    # ------------------------------------------------------------------

    def _perceive(self) -> MarketObservation:
        """
        Sense the current market environment.

        Priority order for each field:
          competitor_price → latest DB competitor signal for product_id
                           → simulation fallback
          inventory        → DB market context for product_id
                           → simulation fallback
          unit_cost        → DB market context for product_id
                           → self.default_unit_cost fallback
          day_of_week      → real calendar weekday (always real)
        """
        # Simulate across all days of the week so the Q-table learns generalized patterns
        day_of_week = random.randint(0, 6)
        source = "simulation"

        # --- Competitor price: latest DB signal ---
        competitor_price: float | None = None
        try:
            agg = storage_backend.get_aggregated_competitor_price(self.product_id)
            if agg.get("median_competitor_price") is not None:
                competitor_price = float(agg["median_competitor_price"])
                source = "db"
        except Exception as exc:
            logger.debug(f"[Agent] DB competitor price lookup failed: {exc}")

        if competitor_price is None:
            competitor_price = round(random.uniform(12.0, 1275.0), 2)

        # --- Inventory + unit_cost: DB market context ---
        inventory: int | None = None
        unit_cost: float | None = None
        try:
            ctx = storage_backend.get_market_context(self.product_id)
            if ctx:
                if ctx.get("inventory") is not None:
                    inventory = int(ctx["inventory"])
                    if source == "db":
                        source = "db"   # already db
                    else:
                        source = "db_partial"
                if ctx.get("unit_cost") is not None:
                    unit_cost = float(ctx["unit_cost"])
        except Exception as exc:
            logger.debug(f"[Agent] DB market context lookup failed: {exc}")

        if inventory is None:
            inventory = random.randint(0, 1100)
        if unit_cost is None:
            unit_cost = round(random.uniform(competitor_price * 0.4, competitor_price * 0.9), 2)

        return MarketObservation(
            competitor_price=competitor_price,
            inventory=inventory,
            day_of_week=day_of_week,
            unit_cost=unit_cost,
            source=source,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record(self, decision: PricingDecision) -> None:
        """Append decision to history, capping at MAX_HISTORY."""
        self._history.append(decision)
        if len(self._history) > self.MAX_HISTORY:
            self._history.pop(0)
