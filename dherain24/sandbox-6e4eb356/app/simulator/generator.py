import random
from typing import List, Dict, Any

def generate_benchmark_batch(count: int = 100, seed: int = 42) -> List[Dict[str, Any]]:
    rng = random.Random(seed)
    cases = []

    failure_archetypes = [
        # (archetype, raw_code, reason, min_amt, max_amt, weight)
        ("insufficient_funds", "NPCI_U19", "insufficient_funds", 1500, 45000, 0.40),
        ("expired_payment_method", "CARD_EXPIRED", "expired_card", 800, 15000, 0.25),
        ("temporary_network_decline", "ERR_BANK_AUTH_502", "network_timeout", 1000, 25000, 0.15),
        ("repeated_dead_decline", "REPEATED_HARD_FAIL", "repeated_failures", 200, 800, 0.10),
        ("high_value_transaction", "AMOUNT_LIMIT_CHECK", "high_value_review", 105000, 250000, 0.10),
    ]

    for i in range(count):
        roll = rng.random()
        cumulative = 0.0
        selected = failure_archetypes[0]
        for item in failure_archetypes:
            cumulative += item[5]
            if roll <= cumulative:
                selected = item
                break

        archetype, raw_code, reason, min_amt, max_amt, _ = selected
        amount = round(rng.uniform(min_amt, max_amt), 2)
        tenure = rng.randint(15, 720)
        success_rate = round(rng.uniform(0.65, 0.98), 2)
        if archetype == "repeated_dead_decline":
            tenure = rng.randint(1, 40)
            success_rate = round(rng.uniform(0.1, 0.35), 2)

        cases.append({
            "case_id": f"BENCH-{seed}-{i:04d}",
            "customer_id": f"cust_{rng.randint(100, 999)}",
            "source_type": "subscription_payment_failed" if "expired" in archetype else "payment_failed",
            "source_id": f"pay_bench_{i:04d}",
            "amount_at_risk": amount,
            "currency": "INR",
            "failure_reason": reason,
            "raw_decline_code": raw_code,
            "customer_tenure_days": tenure,
            "historical_success_rate": success_rate,
            "archetype": archetype,
        })

    return cases
