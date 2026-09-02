import random
from typing import Dict, Any, Optional
from pydantic import BaseModel

class SimulationResult(BaseModel):
    recovered: bool
    recovered_amount: float
    interventions_count: int
    friction_cost: float
    time_to_recovery_hours: float
    terminal_reason: str

class OutcomeSimulator:
    def __init__(self, seed: Optional[int] = None):
        self.rng = random.Random(seed)

    def evaluate_intervention(
        self,
        amount_at_risk: float,
        failure_type: str,
        customer_tenure_days: int,
        historical_success_rate: float,
        action_type: str,
        delay_hours: float = 0.0,
        attempt_number: int = 1,
    ) -> SimulationResult:
        """
        Calibrated against empirical payment recovery benchmark distributions:
        - Insufficient funds immediate retry: <5%
        - Insufficient funds delayed retry (24-48h): ~28-35%
        - Expired card retry: 0%
        - Expired card + payment link: ~35-40%
        - NO_ACTION: 0 recovered, 0 cost, 0 friction
        """
        if action_type == "no_action":
            return SimulationResult(
                recovered=False,
                recovered_amount=0.0,
                interventions_count=0,
                friction_cost=0.0,
                time_to_recovery_hours=0.0,
                terminal_reason="Withheld action to prevent customer fatigue.",
            )

        base_probability = 0.0
        time_to_recovery = delay_hours if delay_hours > 0 else 0.5
        friction_cost = 10.0  # Base transaction overhead

        # 1. Insufficient funds dynamics
        if "insufficient" in failure_type or "funds" in failure_type or "u19" in failure_type:
            if action_type in ["delayed_retry", "schedule_retry"]:
                # Spacing retries near 24-48 hours dramatically improves balance availability
                base_probability = 0.28 if delay_hours >= 24.0 else 0.12
                # Established customer tenure adds modest probability uplift
                if customer_tenure_days > 180:
                    base_probability += 0.06
                friction_cost += 5.0
            elif action_type in ["immediate_retry", "retry"]:
                # Immediate retry on insufficient funds fails 96% of the time
                base_probability = 0.04
                friction_cost += 25.0  # High friction: hitting customer account immediately
            elif action_type == "payment_link":
                base_probability = 0.18
                friction_cost += 20.0

        # 2. Expired / Invalid payment instrument
        elif "expired" in failure_type or "invalid" in failure_type or "instrument" in failure_type:
            if action_type == "payment_link":
                # Only alternate payment links allow card update
                base_probability = 0.38
                time_to_recovery += 4.0
                friction_cost += 15.0
            else:
                # Any retry on an expired instrument is 0% effective
                base_probability = 0.0
                friction_cost += 30.0

        # 3. Temporary bank network timeout
        elif "network" in failure_type or "timeout" in failure_type or "502" in failure_type:
            if action_type in ["delayed_retry", "retry", "immediate_retry"]:
                base_probability = 0.65
                friction_cost += 5.0
            else:
                base_probability = 0.30

        # 4. High-value escalation
        elif action_type == "escalate_human":
            base_probability = 0.75  # Human white-glove outreach succeeds
            time_to_recovery += 12.0
            friction_cost = 150.0  # Higher operational cost for human time

        # Fallback default
        else:
            base_probability = 0.20

        # Attempt penalty: subsequent attempts have diminishing returns
        decay = (0.75 ** (attempt_number - 1))
        effective_probability = min(0.95, base_probability * decay)

        # Roll seeded random outcome
        roll = self.rng.random()
        recovered = roll < effective_probability

        return SimulationResult(
            recovered=recovered,
            recovered_amount=amount_at_risk if recovered else 0.0,
            interventions_count=1,
            friction_cost=friction_cost,
            time_to_recovery_hours=time_to_recovery if recovered else 0.0,
            terminal_reason="Payment captured successfully." if recovered else "Intervention failed to recover funds.",
        )
