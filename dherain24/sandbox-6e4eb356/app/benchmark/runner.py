from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from app.simulator.generator import generate_benchmark_batch
from app.simulator.engine import OutcomeSimulator
from app.simulator.baseline import run_baseline_policy
from app.agents.schemas import CaseContextPackage, AgentProposal
from app.agents.nim_client import generate_heuristic_proposal
from app.policies.rules import evaluate_policy, MerchantPolicy
from app.db.models import RecoveryCase

class BenchmarkMetrics(BaseModel):
    sample_size: int
    seed: int
    total_revenue_at_risk: float
    baseline_recovered_revenue: float
    rri_recovered_revenue: float
    incremental_recovery_amount: float
    recovery_uplift_pct: float
    baseline_recovery_rate_pct: float
    rri_recovery_rate_pct: float
    baseline_total_interventions: int
    rri_total_interventions: int
    intervention_reduction_pct: float
    avoided_bad_interventions_count: int
    policy_violations_count: int
    detailed_comparisons: List[Dict[str, Any]] = []

cached_benchmark_results: Optional[BenchmarkMetrics] = None

def get_cached_benchmark() -> Optional[BenchmarkMetrics]:
    global cached_benchmark_results
    return cached_benchmark_results

def run_benchmark_comparison(sample_size: int = 100, seed: int = 42) -> BenchmarkMetrics:
    global cached_benchmark_results

    cases = generate_benchmark_batch(count=sample_size, seed=seed)
    simulator_baseline = OutcomeSimulator(seed=seed)
    simulator_rri = OutcomeSimulator(seed=seed)
    policy = MerchantPolicy()

    total_at_risk = 0.0
    baseline_recovered_total = 0.0
    rri_recovered_total = 0.0
    baseline_interventions = 0
    rri_interventions = 0
    avoided_bad_interventions = 0
    policy_violations = 0

    comparisons = []

    for c in cases:
        amount = c["amount_at_risk"]
        total_at_risk += amount

        # 1. Run Baseline on case
        b_res = run_baseline_policy(c, simulator_baseline)
        baseline_interventions += b_res["interventions_count"]
        if b_res["recovered"]:
            baseline_recovered_total += amount

        # 2. Run RRI on case
        context = CaseContextPackage(
            case_id=c["case_id"],
            amount_at_risk=amount,
            currency="INR",
            failure_reason=c["failure_reason"],
            raw_decline_code=c["raw_decline_code"],
            customer_tenure_days=c["customer_tenure_days"],
            historical_success_rate=c["historical_success_rate"],
            prior_actions_count=0,
            merchant_max_retries=policy.max_retries,
        )

        proposal: AgentProposal = generate_heuristic_proposal(context)

        # Mock DB model for policy evaluation
        mock_case = RecoveryCase(
            id=c["case_id"],
            merchant_id="m_bench",
            customer_id=c["customer_id"],
            source_type=c["source_type"],
            source_id=c["source_id"],
            amount_at_risk=amount,
            failure_reason=c["failure_reason"],
        )

        policy_check = evaluate_policy(
            case=mock_case,
            proposed_action_type=proposal.action_type,
            parameters={"delay_hours": proposal.delay_hours},
            prior_actions=[],
            policy=policy,
        )

        if not policy_check.is_allowed and not policy_check.approval_required:
            policy_violations += 1

        # Simulate RRI outcome
        r_res = simulator_rri.evaluate_intervention(
            amount_at_risk=amount,
            failure_type=c["archetype"],
            customer_tenure_days=c["customer_tenure_days"],
            historical_success_rate=c["historical_success_rate"],
            action_type=proposal.action_type,
            delay_hours=proposal.delay_hours or 0.0,
            attempt_number=1,
        )

        rri_interventions += r_res.interventions_count
        if r_res.recovered:
            rri_recovered_total += amount

        # Check for avoided bad interventions:
        # Agent chose NO_ACTION, and Baseline's retries ended up failing anyway
        if proposal.action_type == "no_action" and not b_res["recovered"]:
            avoided_bad_interventions += 1

        comparisons.append({
            "case_id": c["case_id"],
            "archetype": c["archetype"],
            "amount": amount,
            "baseline": {
                "recovered": b_res["recovered"],
                "interventions": b_res["interventions_count"],
            },
            "rri": {
                "action": proposal.action_type,
                "recovered": r_res.recovered,
                "interventions": r_res.interventions_count,
                "rationale": proposal.plain_english_rationale,
            },
        })

    incremental = rri_recovered_total - baseline_recovered_total
    uplift_pct = (incremental / baseline_recovered_total * 100.0) if baseline_recovered_total > 0 else 0.0
    int_reduction = ((baseline_interventions - rri_interventions) / baseline_interventions * 100.0) if baseline_interventions > 0 else 0.0

    metrics = BenchmarkMetrics(
        sample_size=sample_size,
        seed=seed,
        total_revenue_at_risk=round(total_at_risk, 2),
        baseline_recovered_revenue=round(baseline_recovered_total, 2),
        rri_recovered_revenue=round(rri_recovered_total, 2),
        incremental_recovery_amount=round(incremental, 2),
        recovery_uplift_pct=round(uplift_pct, 1),
        baseline_recovery_rate_pct=round((baseline_recovered_total / total_at_risk * 100), 1) if total_at_risk > 0 else 0.0,
        rri_recovery_rate_pct=round((rri_recovered_total / total_at_risk * 100), 1) if total_at_risk > 0 else 0.0,
        baseline_total_interventions=baseline_interventions,
        rri_total_interventions=rri_interventions,
        intervention_reduction_pct=round(int_reduction, 1),
        avoided_bad_interventions_count=avoided_bad_interventions,
        policy_violations_count=policy_violations,
        detailed_comparisons=comparisons[:10],  # sample 10 for compact payload
    )

    cached_benchmark_results = metrics
    return metrics
