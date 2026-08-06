import numpy as np
import pandas as pd

from src.models.demand import build_feature_row


def optimize_price_for_context(
    model,
    reference_row: pd.Series,
    competitor_price: float,
    inventory: int,
    day_of_week: int,
    unit_cost: float = 60.0,
    min_price: float | None = None,
    max_price: float | None = None,
    n_candidates: int = 200,
    inventory_aware: bool = True,
):
    """
    Find the profit-maximising price with no fixed boundaries.

    If min_price / max_price are not supplied the range is derived from
    market context:
      - floor : unit_cost * 1.01  (just above break-even)
      - ceiling: competitor_price * 3.0  (generous upside headroom)

    n_candidates controls resolution; 200 gives fine granularity across
    any range width.
    """
    # Dynamic, context-aware price floor and ceiling
    floor = min_price if min_price is not None else unit_cost * 1.01
    ceiling = max_price if max_price is not None else max(competitor_price * 1.5, unit_cost * 2.0)

    # Guarantee at least a tiny range so linspace never degenerates
    if ceiling <= floor:
        ceiling = floor * 2.0

    # Calculate how overstocked or understocked we are relative to median
    median_inventory = max(float(reference_row["inventory"]), 1.0)
    inventory_ratio = inventory / median_inventory
    
    effective_cost = unit_cost
    clearance_weight = 0.0
    typical_margin = max(10.0, float(competitor_price) - unit_cost)

    if inventory_aware:
        # 1. Understock logic: artificially raise effective cost to protect margin
        if inventory_ratio < 1.0:
            inventory_sensitivity = 0.50 
            effective_cost = min(unit_cost * 1.5, unit_cost * (1.0 + inventory_sensitivity * (1.0 - inventory_ratio)))
            
        # 2. Overstock logic: blend profit objective with pure volume objective
        # This forcefully liquidates stock even if the demand curve is highly inelastic
        if inventory_ratio > 1.0:
            # weight scales from 0 to 1 as inventory hits 3x median
            clearance_weight = min(1.0, (inventory_ratio - 1.0) / 2.0)

    best_price = None
    best_demand = None
    best_profit = -np.inf
    best_objective = -np.inf

    demands = []
    prices = np.linspace(floor, ceiling, n_candidates)
    
    # 1. Gather raw piece-wise constant predictions
    for price in prices:
        X = build_feature_row(
            price=float(price),
            competitor_price=competitor_price,
            inventory=inventory,
            day_of_week=day_of_week,
            reference_row=reference_row,
        )
        demands.append(max(0.0001, float(model.predict(X)[0])))
        
    # 2. Smooth predictions using a moving average window (removes XGBoost step-function artifacts)
    # This prevents "sticky" optimal prices without distorting the actual demand scale.
    window = max(3, n_candidates // 15)
    kernel = np.ones(window) / window
    # Pad the edges so the demand doesn't drop off at the boundaries
    padded_demands = np.pad(demands, (window // 2, window // 2), mode='edge')
    smooth_demands = np.convolve(padded_demands, kernel, mode='valid')
    
    # 3. Evaluate the objective function over the smooth curve
    for price, predicted_demand in zip(prices, smooth_demands):
        # Base profit objective (protects margin)
        base_profit = (float(price) - effective_cost) * predicted_demand
        
        # Pure volume objective (liquidates stock)
        volume_reward = predicted_demand * typical_margin
        
        # Blended objective
        objective_value = (1.0 - clearance_weight) * base_profit + clearance_weight * volume_reward

        if objective_value > best_objective:
            best_price = float(price)
            best_demand = predicted_demand
            best_profit = (float(price) - unit_cost) * predicted_demand # store real profit
            best_objective = objective_value

    if inventory_aware:
        if clearance_weight >= 0.5:
            strategy = "Clearance Pricing (high inventory — maximise volume)"
        elif clearance_weight > 0:
            strategy = "Blended Pricing (moderate overstock — balance margin & volume)"
        elif inventory_ratio < 0.5:
            strategy = "Scarcity Pricing (low inventory — protect margin)"
        else:
            strategy = "Profit-Maximising Pricing (standard market)"
    else:
        strategy = "Strict Profit Maximization (inventory ignored)"

    return {
        "optimal_price": best_price,
        "expected_demand": best_demand,
        "expected_profit": best_profit,
        "strategy": strategy,
        "search_range": {"min": round(floor, 2), "max": round(ceiling, 2)},
    }
