"""
Benchmark Service — evaluates the business impact of pricing strategies.

Simulates market scenarios and compares 4 pricing strategies:
1. Static (Cost+30%)
2. Competitor Follow (Match competitor price)
3. ML Optimal (Maximize expected profit via XGBoost)
4. RL Policy (Q-learning agent)

Returns a quantitative comparison proving the value of the AI approaches
over static baselines.
"""

import logging
import random
from typing import Any

from src.services.pricing_service import PricingInput, PricingService
from src.services.rl_pricing_service import RLPricingInput, RLPricingService
from src.models.demand import build_feature_row

logger = logging.getLogger(__name__)


class BenchmarkService:
    def __init__(self, pricing_service: PricingService, rl_pricing_service: RLPricingService):
        self.pricing_service = pricing_service
        self.rl_pricing_service = rl_pricing_service

    def run_benchmark(self, n_scenarios: int = 50, seed: int = 42) -> dict[str, Any]:
        """
        Run a benchmark comparing 4 pricing strategies across N simulated market scenarios.
        """
        rng = random.Random(seed)
        
        results = {
            "static_cost_plus": {"total_profit": 0.0, "total_demand": 0.0, "total_revenue": 0.0},
            "competitor_follow": {"total_profit": 0.0, "total_demand": 0.0, "total_revenue": 0.0},
            "ml_optimal": {"total_profit": 0.0, "total_demand": 0.0, "total_revenue": 0.0},
            "rl_policy": {"total_profit": 0.0, "total_demand": 0.0, "total_revenue": 0.0},
        }

        # Ensure models are ready
        if self.pricing_service.model is None:
            self.pricing_service.startup()
        if self.rl_pricing_service.rl_agent is None:
            self.rl_pricing_service.startup()

        for _ in range(n_scenarios):
            # Generate random market scenario
            unit_cost = round(rng.uniform(40.0, 80.0), 2)
            competitor_price = round(unit_cost * rng.uniform(1.1, 1.8), 2)
            inventory = rng.randint(20, 300)
            day_of_week = rng.randint(0, 6)

            # --- Strategy 1: Static (Cost+30%) ---
            price_static = round(unit_cost * 1.30, 2)
            metrics_static = self._evaluate_price(price_static, competitor_price, inventory, day_of_week, unit_cost)
            
            # --- Strategy 2: Competitor Follow ---
            price_follow = competitor_price
            metrics_follow = self._evaluate_price(price_follow, competitor_price, inventory, day_of_week, unit_cost)

            # --- Strategy 3: ML Optimal ---
            ml_result = self.pricing_service.calculate_optimal_price(PricingInput(
                competitor_price=competitor_price,
                inventory=inventory,
                day_of_week=day_of_week,
                unit_cost=unit_cost,
            ))
            price_ml = ml_result["optimal_price"]
            metrics_ml = self._evaluate_price(price_ml, competitor_price, inventory, day_of_week, unit_cost)

            # --- Strategy 4: RL Policy ---
            rl_result = self.rl_pricing_service.get_rl_price(RLPricingInput(
                competitor_price=competitor_price,
                inventory=inventory,
                day_of_week=day_of_week,
                unit_cost=unit_cost,
            ))
            price_rl = rl_result["rl_price"]
            metrics_rl = self._evaluate_price(price_rl, competitor_price, inventory, day_of_week, unit_cost)

            # Accumulate results
            self._accumulate(results["static_cost_plus"], metrics_static)
            self._accumulate(results["competitor_follow"], metrics_follow)
            self._accumulate(results["ml_optimal"], metrics_ml)
            self._accumulate(results["rl_policy"], metrics_rl)

        # Compute summary metrics and lift
        base_profit = results["static_cost_plus"]["total_profit"]
        
        summary = {}
        for strategy, metrics in results.items():
            profit = metrics["total_profit"]
            lift = ((profit - base_profit) / base_profit * 100.0) if base_profit > 0 else 0.0
            
            summary[strategy] = {
                "total_profit": round(profit, 2),
                "total_revenue": round(metrics["total_revenue"], 2),
                "total_demand": round(metrics["total_demand"], 2),
                "avg_profit_per_unit": round(profit / metrics["total_demand"], 2) if metrics["total_demand"] > 0 else 0.0,
                "profit_improvement_vs_static_pct": round(lift, 2),
            }

        best_strategy = max(summary.items(), key=lambda x: x[1]["total_profit"])
        
        return {
            "scenarios_evaluated": n_scenarios,
            "strategies": summary,
            "headline": f"{best_strategy[0].replace('_', ' ').title()} pricing improves profit by {summary[best_strategy[0]]['profit_improvement_vs_static_pct']}% compared to static cost-plus pricing.",
        }

    def _evaluate_price(self, price: float, competitor_price: float, inventory: int, day_of_week: int, unit_cost: float) -> dict[str, float]:
        """Use the ML model to predict demand and profit for a specific price."""
        # Using build_feature_row to get demand at a specific price point
        assert self.pricing_service.reference_row is not None, "Model must be loaded before evaluation"
        features = build_feature_row(price, competitor_price, inventory, day_of_week, self.pricing_service.reference_row)
        assert self.pricing_service.model is not None, "Model must be loaded before evaluation"
        expected_demand = float(self.pricing_service.model.predict(features)[0])
        expected_demand = max(0.0, expected_demand)
        
        expected_profit = expected_demand * (price - unit_cost)
        expected_revenue = expected_demand * price
        
        return {
            "demand": expected_demand,
            "profit": expected_profit,
            "revenue": expected_revenue
        }

    def _accumulate(self, dest: dict, metrics: dict) -> None:
        dest["total_profit"] += metrics["profit"]
        dest["total_demand"] += metrics["demand"]
        dest["total_revenue"] += metrics["revenue"]
