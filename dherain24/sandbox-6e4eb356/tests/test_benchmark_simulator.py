import pytest
from httpx import AsyncClient
from app.simulator.engine import OutcomeSimulator
from app.benchmark.runner import run_benchmark_comparison

def test_simulator_deterministic_seeding():
    sim1 = OutcomeSimulator(seed=42)
    sim2 = OutcomeSimulator(seed=42)

    res1 = sim1.evaluate_intervention(
        amount_at_risk=25000.0,
        failure_type="insufficient_funds",
        customer_tenure_days=180,
        historical_success_rate=0.85,
        action_type="delayed_retry",
        delay_hours=36.0,
    )

    res2 = sim2.evaluate_intervention(
        amount_at_risk=25000.0,
        failure_type="insufficient_funds",
        customer_tenure_days=180,
        historical_success_rate=0.85,
        action_type="delayed_retry",
        delay_hours=36.0,
    )

    assert res1.recovered == res2.recovered
    assert res1.recovered_amount == res2.recovered_amount
    assert res1.friction_cost == res2.friction_cost

def test_expired_card_dynamics():
    sim = OutcomeSimulator(seed=42)
    # Retry on expired card is mathematically 0% effective
    res_retry = sim.evaluate_intervention(
        amount_at_risk=10000.0,
        failure_type="expired_payment_method",
        customer_tenure_days=300,
        historical_success_rate=0.90,
        action_type="delayed_retry",
        delay_hours=24.0,
    )
    assert res_retry.recovered is False

    # Payment link allows customer to update card and recover
    # Run multiple times with fixed seed to confirm positive rate
    link_sim = OutcomeSimulator(seed=42)
    link_outcomes = [
        link_sim.evaluate_intervention(
            amount_at_risk=10000.0,
            failure_type="expired_payment_method",
            customer_tenure_days=300,
            historical_success_rate=0.90,
            action_type="payment_link",
        ).recovered
        for _ in range(20)
    ]
    assert any(link_outcomes)  # At least some recover via payment link

def test_benchmark_runner_execution():
    metrics = run_benchmark_comparison(sample_size=100, seed=42)

    assert metrics.sample_size == 100
    assert metrics.seed == 42
    assert metrics.total_revenue_at_risk > 0.0
    assert metrics.policy_violations_count == 0  # Hard guardrail
    assert metrics.rri_recovered_revenue > metrics.baseline_recovered_revenue
    assert metrics.recovery_uplift_pct > 0.0
    assert metrics.rri_total_interventions < metrics.baseline_total_interventions
    assert metrics.avoided_bad_interventions_count > 0

@pytest.mark.asyncio
async def test_benchmark_api_endpoints(client: AsyncClient):
    run_res = await client.post("/api/v1/benchmark/run?sample_size=50&seed=42")
    assert run_res.status_code == 200
    data = run_res.json()
    assert data["sample_size"] == 50
    assert data["policy_violations_count"] == 0
    assert data["rri_recovered_revenue"] >= data["baseline_recovered_revenue"]

    latest_res = await client.get("/api/v1/benchmark/latest")
    assert latest_res.status_code == 200
    latest_data = latest_res.json()
    assert latest_data["sample_size"] == 50
