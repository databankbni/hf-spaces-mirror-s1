from typing import Dict, Any
from app.simulator.engine import OutcomeSimulator, SimulationResult

def run_baseline_policy(case: Dict[str, Any], simulator: OutcomeSimulator) -> Dict[str, Any]:
    """
    Standard Naive Industry Practice:
    1. Immediate retry
    2. If failed, send notification + immediate retry
    3. If still failed, give up
    """
    amount = case["amount_at_risk"]
    failure = case["archetype"]
    tenure = case["customer_tenure_days"]
    success_rate = case["historical_success_rate"]

    total_interventions = 0
    total_friction = 0.0
    recovered = False
    recovered_amount = 0.0

    # Step 1: Immediate Retry
    res1: SimulationResult = simulator.evaluate_intervention(
        amount_at_risk=amount,
        failure_type=failure,
        customer_tenure_days=tenure,
        historical_success_rate=success_rate,
        action_type="immediate_retry",
        delay_hours=0.0,
        attempt_number=1,
    )
    total_interventions += res1.interventions_count
    total_friction += res1.friction_cost

    if res1.recovered:
        return {
            "recovered": True,
            "recovered_amount": amount,
            "interventions_count": total_interventions,
            "friction_cost": total_friction,
            "actions_taken": ["immediate_retry"],
            "terminal_state": "RECOVERED",
        }

    # Step 2: Immediate second retry (blind)
    res2: SimulationResult = simulator.evaluate_intervention(
        amount_at_risk=amount,
        failure_type=failure,
        customer_tenure_days=tenure,
        historical_success_rate=success_rate,
        action_type="immediate_retry",
        delay_hours=0.5,
        attempt_number=2,
    )
    total_interventions += res2.interventions_count
    total_friction += res2.friction_cost

    if res2.recovered:
        return {
            "recovered": True,
            "recovered_amount": amount,
            "interventions_count": total_interventions,
            "friction_cost": total_friction,
            "actions_taken": ["immediate_retry", "immediate_retry_2"],
            "terminal_state": "RECOVERED",
        }

    # Failed out
    return {
        "recovered": False,
        "recovered_amount": 0.0,
        "interventions_count": total_interventions,
        "friction_cost": total_friction,
        "actions_taken": ["immediate_retry", "immediate_retry_2"],
        "terminal_state": "FAILED",
    }
