"""Smoke test for the DoWhy causal model."""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import json

from src.models.causal_uplift import CausalUpliftModel

print("=" * 60)
print("DoWhy Causal Analysis Smoke Test")
print("=" * 60)

rng = np.random.default_rng(42)
n = 1000

competitor_price = rng.uniform(70, 130, n)
inventory        = rng.integers(20, 300, n).astype(float)
day_of_week      = rng.integers(0, 7, n).astype(float)

price = (
    competitor_price * 0.95
    + (1 - inventory / 300) * 10
    + day_of_week * 1.5
    + rng.normal(0, 5, n)
).clip(50, 200)

# True causal effect: -2.5 demand per unit price increase
demand = (
    500
    - 2.5 * price
    + 1.8 * competitor_price
    + 0.3 * inventory
    + 10 * (day_of_week > 4).astype(float)
    + rng.normal(0, 20, n)
).clip(0)

df = pd.DataFrame({
    "price": price, "demand": demand,
    "competitor_price": competitor_price,
    "inventory": inventory, "day_of_week": day_of_week,
})

print(f"\nDataset: {len(df)} rows")
print(f"Price range: {df.price.min():.1f} – {df.price.max():.1f}")
print(f"Demand range: {df.demand.min():.1f} – {df.demand.max():.1f}")
print("\nFitting causal model (true ATE should be close to -2.5)...")

model = CausalUpliftModel()
result = model.fit(df)

print(f"\n✅ ATE Estimated: {result['ate']}")
print(f"   Interpretation: {result['ate_interpretation']}")
print(f"\n📊 Refutation Results:")
for r in result["refutations"]:
    status = "✅ PASS" if r["passed"] else ("⚠️ FAIL" if r["passed"] is False else "❓ N/A")
    print(f"\n  [{status}] {r['refuter']}")
    print(f"   Original ATE: {r['original_ate']}  →  New ATE: {r['new_ate']}")
    print(f"   {r['interpretation']}")

print(f"\n🔐 All refutations passed: {result['all_refutations_passed']}")
print("\n✅ Smoke test complete.")
