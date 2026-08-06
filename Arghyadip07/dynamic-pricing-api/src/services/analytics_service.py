from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import threading
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error

from src.core.settings import settings
from src.domain.pricing import optimize_price_for_context
from src.models.demand import (
    FEATURE_COLUMNS,
    build_feature_row,
    load_or_train_model_artifact,
    train_and_save_model_artifact,
)
from src.storage import storage_backend


@dataclass
class WhatIfScenario:
    name: str
    competitor_price: float
    inventory: int
    day_of_week: int
    unit_cost: float = 60.0
    inventory_aware: bool = True


logger = logging.getLogger(__name__)


class AnalyticsService:
    def __init__(self, data_path: str | None = None, artifact_path: str | None = None):
        self.data_path = data_path or str(settings.processed_data_abspath)
        self.artifact_path = artifact_path or str(settings.model_artifact_abspath)
        self.model = None
        self.reference_row = None
        self.model_info: dict[str, Any] = {}
        self.retrain_interval_seconds = 300.0
        self.min_retrain_gap_seconds = 1800.0
        self._last_retrain_at: datetime | None = None
        self._retrain_thread: threading.Thread | None = None
        self._retrain_stop = threading.Event()

    def startup(self) -> None:
        self.model, self.reference_row, self.model_info = load_or_train_model_artifact(
            data_path=self.data_path,
            artifact_path=self.artifact_path,
        )
        self.start_auto_retrain()

    def shutdown(self) -> None:
        self.stop_auto_retrain()

    def _ensure_ready(self) -> None:
        if self.model is None or self.reference_row is None:
            self.startup()
        if self.model is None or self.reference_row is None:
            raise RuntimeError("AnalyticsService failed to initialize model artifacts")

    def _load_data(self) -> pd.DataFrame:
        """Load the processed CSV, or return a synthetic fallback with all feature columns if missing."""
        from pathlib import Path
        if Path(self.data_path).exists():
            return pd.read_csv(self.data_path)
        logger.warning("Data file not found at %s — using synthetic fallback with all feature columns.", self.data_path)
        from src.models.demand import _synthetic_training_df
        return _synthetic_training_df(n=1000)

    def performance_summary(self) -> dict:
        self._ensure_ready()
        assert self.model is not None
        df = self._load_data()
        y_true = df["demand"]
        y_pred = self.model.predict(df[FEATURE_COLUMNS])
        rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
        mae = float(mean_absolute_error(y_true, y_pred))
        mean_demand = float(np.mean(y_true))
        wape = float((mae / mean_demand) * 100) if mean_demand > 0 else 0.0

        return {
            "model_source": self.model_info.get("source", "artifact"),
            "rows_scored": len(df),
            "rmse": rmse,
            "mae": mae,
            "mape_percent": wape,  # We pass WAPE instead of MAPE so the dashboard handles it better
            "prediction_accuracy_percent": max(0.0, 100.0 - wape),
        }

    def drift_report(self, recent_fraction: float = 0.25) -> dict:
        df = self._load_data().sort_index()
        split_at = max(1, int(len(df) * (1 - recent_fraction)))
        baseline = df.iloc[:split_at]
        recent = df.iloc[split_at:]
        columns = ["price", "competitor_price", "inventory", "demand"]

        features = []
        max_score = 0.0
        for column in columns:
            base_mean = float(baseline[column].mean())
            recent_mean = float(recent[column].mean())
            denominator = max(abs(base_mean), 1.0)
            drift_score = abs(recent_mean - base_mean) / denominator
            max_score = max(max_score, drift_score)
            features.append(
                {
                    "feature": column,
                    "baseline_mean": base_mean,
                    "recent_mean": recent_mean,
                    "drift_score": drift_score,
                }
            )

        if max_score >= 0.20:
            status = "retrain_recommended"
        elif max_score >= 0.10:
            status = "watch"
        else:
            status = "stable"

        return {
            "status": status,
            "max_drift_score": max_score,
            "baseline_rows": len(baseline),
            "recent_rows": len(recent),
            "features": features,
        }

    def what_if_analysis(self, scenarios: list[WhatIfScenario]) -> dict:
        self._ensure_ready()
        assert self.model is not None
        assert self.reference_row is not None
        rows = []
        for scenario in scenarios:
            result = optimize_price_for_context(
                model=self.model,
                reference_row=self.reference_row,
                competitor_price=scenario.competitor_price,
                inventory=scenario.inventory,
                day_of_week=scenario.day_of_week,
                unit_cost=scenario.unit_cost,
                inventory_aware=scenario.inventory_aware,
            )
            opt_p = result.get("optimal_price")
            optimal_price = float(opt_p) if isinstance(opt_p, (int, float, str)) else 0.0
            exp_d = result.get("expected_demand")
            expected_demand = float(exp_d) if isinstance(exp_d, (int, float, str)) else 0.0
            exp_p = result.get("expected_profit")
            expected_profit = float(exp_p) if isinstance(exp_p, (int, float, str)) else 0.0
            
            rows.append(
                {
                    "scenario": scenario.name,
                    "competitor_price": scenario.competitor_price,
                    "inventory": scenario.inventory,
                    "day_of_week": scenario.day_of_week,
                    "optimal_price": optimal_price,
                    "expected_demand": expected_demand,
                    "expected_profit": expected_profit,
                    "expected_revenue": optimal_price * expected_demand,
                    "expected_profit_margin_percent": (
                        (expected_profit / (optimal_price * expected_demand)) * 100
                        if optimal_price * expected_demand > 0
                        else 0.0
                    ),
                }
            )
        return {"scenarios": rows}

    def start_auto_retrain(self) -> None:
        if self._retrain_thread is not None and self._retrain_thread.is_alive():
            return

        self._retrain_stop.clear()
        self._retrain_thread = threading.Thread(target=self._auto_retrain_loop, daemon=True)
        self._retrain_thread.start()

    def stop_auto_retrain(self) -> None:
        self._retrain_stop.set()
        if self._retrain_thread is not None:
            self._retrain_thread.join(timeout=2.0)
        self._retrain_thread = None

    def _auto_retrain_loop(self) -> None:
        while not self._retrain_stop.wait(self.retrain_interval_seconds):
            try:
                self.retrain_if_needed(auto=True)
            except Exception as exc:
                logger.warning("Automatic retrain check failed: %s", exc)

    def _default_analysis_rows(self) -> list[dict]:
        return [
            {"price_change": -10, "profit": 900, "inventory": 700},
            {"price_change": -5, "profit": 980, "inventory": 650},
            {"price_change": 0, "profit": 1040, "inventory": 620},
            {"price_change": 5, "profit": 1120, "inventory": 560},
            {"price_change": 10, "profit": 1080, "inventory": 520},
        ]

    def _default_analysis_scenarios(self) -> list[WhatIfScenario]:
        self._ensure_ready()
        assert self.reference_row is not None
        reference_competitor = float(self.reference_row.get("competitor_price") or 100.0)
        reference_inventory = int(max(float(self.reference_row.get("inventory") or 1.0), 0.0))
        reference_day = int(float(self.reference_row.get("day_of_week") or 2.0)) % 7

        return [
            WhatIfScenario(
                name="Base Market",
                competitor_price=reference_competitor,
                inventory=reference_inventory,
                day_of_week=reference_day,
            ),
            WhatIfScenario(
                name="Competitor Price Drop",
                competitor_price=max(1.0, reference_competitor * 0.9),
                inventory=reference_inventory,
                day_of_week=reference_day,
            ),
            WhatIfScenario(
                name="Demand Surge",
                competitor_price=reference_competitor,
                inventory=max(0, int(reference_inventory * 0.55)),
                day_of_week=5,
            ),
        ]

    def causal_effect(
        self,
        rows: list[dict],
        treatment_column: str,
        outcome_column: str,
        control_columns: list[str] | None = None,
    ) -> dict:
        if not rows:
            raise ValueError("rows must not be empty")

        control_columns = control_columns or []
        df = pd.DataFrame(rows)
        required = [treatment_column, outcome_column, *control_columns]
        missing = [column for column in required if column not in df.columns]
        if missing:
            raise ValueError(f"missing columns: {', '.join(missing)}")

        numeric = df[required].apply(pd.to_numeric, errors="coerce")
        numeric = numeric.fillna(numeric.mean())
        min_rows = 2 + len(control_columns)
        if len(numeric) < min_rows:
            raise ValueError(f"at least {min_rows} complete numeric rows are required")

        try:
            from dowhy import CausalModel  # type: ignore
            import os

            graph_str = None
            lingam_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'artifacts', 'lingam_causal_graph.dot'))
            if os.path.exists(lingam_path):
                with open(lingam_path, "r") as f:
                    graph_str = f.read()

            if graph_str:
                model = CausalModel(
                    data=numeric,
                    treatment=treatment_column,
                    outcome=outcome_column,
                    graph=graph_str,
                )
            else:
                model = CausalModel(
                    data=numeric,
                    treatment=treatment_column,
                    outcome=outcome_column,
                    common_causes=control_columns or None,
                )
            identified_estimand = model.identify_effect(proceed_when_unidentifiable=True)
            estimate = model.estimate_effect(identified_estimand, method_name="backdoor.linear_regression")
            ols_fallback = self._ols_causal_effect(
                numeric=numeric,
                treatment_column=treatment_column,
                outcome_column=outcome_column,
                control_columns=control_columns,
            )
            return {
                "treatment_column": treatment_column,
                "outcome_column": outcome_column,
                "control_columns": control_columns,
                "estimated_effect": float(estimate.value),
                "r_squared": ols_fallback["r_squared"],
                "rows_used": len(numeric),
                "method": "dowhy_backdoor_linear_regression",
            }
        except Exception:
            return self._ols_causal_effect(
                numeric=numeric,
                treatment_column=treatment_column,
                outcome_column=outcome_column,
                control_columns=control_columns,
            )

    def _ols_causal_effect(
        self,
        numeric: pd.DataFrame,
        treatment_column: str,
        outcome_column: str,
        control_columns: list[str],
    ) -> dict:
        x = numeric[[treatment_column, *control_columns]].to_numpy(dtype=float)
        x = np.column_stack([np.ones(len(x)), x])
        y = numeric[outcome_column].to_numpy(dtype=float)
        coefficients, *_ = np.linalg.lstsq(x, y, rcond=None)
        predicted = x @ coefficients
        residual_sum = float(np.sum((y - predicted) ** 2))
        total_sum = float(np.sum((y - y.mean()) ** 2))
        r_squared = 1.0 - residual_sum / total_sum if total_sum > 0 else 0.0

        return {
            "treatment_column": treatment_column,
            "outcome_column": outcome_column,
            "control_columns": control_columns,
            "estimated_effect": float(coefficients[1]),
            "r_squared": r_squared,
            "rows_used": len(numeric),
            "method": "ordinary_least_squares_with_controls",
        }

    def retrain_if_needed(
        self,
        recent_fraction: float = 0.25,
        force: bool = False,
        auto: bool = False,
    ) -> dict:
        self._ensure_ready()
        drift = self.drift_report(recent_fraction=recent_fraction)
        reason = "forced" if force else drift["status"]
        should_retrain = force or drift["status"] == "retrain_recommended"

        now = datetime.now(timezone.utc)
        if (
            should_retrain
            and self._last_retrain_at is not None
            and not force
            and (now - self._last_retrain_at).total_seconds() < self.min_retrain_gap_seconds
        ):
            return {
                "performed": False,
                "reason": "cooldown_active",
                "drift_status": drift["status"],
                "last_retrain_at": self._last_retrain_at.isoformat(),
                "auto": auto,
            }

        if not should_retrain:
            return {
                "performed": False,
                "reason": reason,
                "drift_status": drift["status"],
                "last_retrain_at": self._last_retrain_at.isoformat() if self._last_retrain_at else None,
                "auto": auto,
            }

        model, reference_row, metrics = train_and_save_model_artifact(
            data_path=self.data_path,
            artifact_path=self.artifact_path,
        )
        self.model = model
        self.reference_row = reference_row
        metrics_dict: dict[str, Any] = dict(metrics)
        metrics_dict["source"] = "retrained"
        self.model_info = metrics_dict
        self._last_retrain_at = now

        return {
            "performed": True,
            "reason": reason,
            "drift_status": drift["status"],
            "last_retrain_at": self._last_retrain_at.isoformat(),
            "metrics": metrics,
            "auto": auto,
        }

    def analysis_report(
        self,
        experiment: str = "model_vs_static_pricing",
        recent_fraction: float = 0.25,
        scenarios: list[WhatIfScenario] | None = None,
        causal_rows: list[dict] | None = None,
    ) -> dict:
        self._ensure_ready()
        scenarios = scenarios or self._default_analysis_scenarios()
        causal_rows = causal_rows or self._default_analysis_rows()

        return {
            "performance": self.performance_summary(),
            "drift": self.drift_report(recent_fraction=recent_fraction),
            "ab_summary": storage_backend.get_ab_summary(experiment),
            "what_if": self.what_if_analysis(scenarios),
            "causal_effect": self.causal_effect(
                rows=causal_rows,
                treatment_column="price_change",
                outcome_column="profit",
                control_columns=["inventory"],
            ),
        }

    def price_response_curve(
        self,
        competitor_price: float,
        inventory: int,
        day_of_week: int,
        unit_cost: float = 60.0,
        min_price: float = 50.0,
        max_price: float = 180.0,
        price_points: int = 20,
    ) -> dict:
        self._ensure_ready()
        assert self.model is not None
        assert self.reference_row is not None
        curve = []
        for price in np.linspace(min_price, max_price, price_points):
            row = build_feature_row(
                price=float(price),
                competitor_price=competitor_price,
                inventory=inventory,
                day_of_week=day_of_week,
                reference_row=self.reference_row,
            )
            demand = float(self.model.predict(row)[0])
            curve.append(
                {
                    "price": float(price),
                    "expected_demand": demand,
                    "expected_profit": (float(price) - unit_cost) * demand,
                }
            )
        return {"curve": curve}
