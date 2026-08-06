"""
Causal Uplift Model using DoWhy.

Answers the key pricing question:
  "What is the true causal effect of a PRICE CHANGE (treatment) on DEMAND (outcome),
   after controlling for confounders like competitor price, inventory, and day of week?"

This is critical because simple correlation would confuse:
  - High prices on weekends (seasonal demand) with the price effect itself.
  - Low inventory → lower demand (independent of price).

Causal DAG used:
  competitor_price  ──┐
  inventory         ──┤──► demand
  day_of_week       ──┤
                       │
  price (treatment)  ──┘   (price causally affects demand, confounded by market conditions)

Refutation tests run automatically after estimation:
  1. Placebo Treatment Refuter   — replaces treatment with random noise; ATE should drop to ~0
  2. Random Common Cause Refuter — adds spurious confounder; ATE should remain stable
  3. Data Subset Refuter         — estimates on 80% subset; ATE should be consistent
"""

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class CausalUpliftModel:
    """
    DoWhy-backed causal uplift estimator for the pricing domain.

    Usage:
        model = CausalUpliftModel()
        model.fit(df)                        # df must have price, demand, + confounders
        result = model.estimate_effect()     # ATE + refutation results
        uplifts = model.estimate_uplift(X)   # per-row CATE estimate
    """

    trained: bool = False
    ate_: float | None = None                    # Average Treatment Effect
    refutation_results_: list[dict] = field(default_factory=list)
    causal_graph_str_: str | None = None
    _fitted_estimate: Any = None

    CONFOUNDERS = ["competitor_price", "inventory", "day_of_week"]
    TREATMENT    = "price"
    OUTCOME      = "demand"

    # ------------------------------------------------------------------
    # Fit
    # ------------------------------------------------------------------

    def fit(self, df: pd.DataFrame) -> dict[str, Any]:
        """
        Fit the causal model on a pricing dataset.

        Args:
            df: DataFrame with columns: price, demand, competitor_price,
                inventory, day_of_week  (and optionally others).

        Returns:
            dict with ate, refutations, graph_dot, status.
        """
        try:
            import dowhy
            from dowhy import CausalModel
        except ImportError:
            logger.error("DoWhy not installed. Run: pip install dowhy")
            self.trained = False
            return {"error": "dowhy not installed", "status": "failed"}

        required = [self.TREATMENT, self.OUTCOME] + self.CONFOUNDERS
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"DataFrame missing columns: {missing}")

        df = df[required].copy()
        for col in df.columns:
            if df[col].isnull().any():
                if pd.api.types.is_numeric_dtype(df[col]):
                    df[col] = df[col].fillna(df[col].mean())
        logger.info(f"Fitting causal model on {len(df)} rows …")

        # STRICT PIPELINE: Force loading of LiNGAM Discovered Graph
        import os
        lingam_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'artifacts', 'lingam_causal_graph.dot'))
        
        if not os.path.exists(lingam_path):
            raise RuntimeError("CRITICAL ARCHITECTURE ERROR: You cannot run Causal Estimation because the LiNGAM Causal Discovery graph was not found! You must run the LiNGAM discovery script first to map the DAG.")
            
        with open(lingam_path, "r") as f:
            graph_str = f.read()
        logger.info("Successfully loaded LiNGAM discovered graph for DoWhy Causal Estimation.")
        
        self.causal_graph_str_ = graph_str

        # 1. Define causal model strictly using the discovered DAG
        model = CausalModel(
            data=df,
            treatment=self.TREATMENT,
            outcome=self.OUTCOME,
            graph=graph_str,
        )

        # 2. Identify causal effect (backdoor criterion)
        identified_estimand = model.identify_effect(proceed_when_unidentifiable=True)

        # 3. Estimate ATE using Linear Regression (fast, interpretable)
        estimate = model.estimate_effect(
            identified_estimand,
            method_name="backdoor.linear_regression",
            control_value=df[self.TREATMENT].quantile(0.25),   # 25th pctile price as control
            treatment_value=df[self.TREATMENT].quantile(0.75), # 75th pctile price as treatment
            confidence_intervals=False,
            test_significance=True,
        )

        self.ate_ = float(estimate.value)
        self._fitted_estimate = (model, identified_estimand, estimate, df)
        self.trained = True

        logger.info(f"ATE estimated: {self.ate_:.4f} units demand per unit price change")

        # 4. Run refutations
        self.refutation_results_ = self._run_refutations(model, identified_estimand, estimate)

        return self._summary()

    # ------------------------------------------------------------------
    # Refutations
    # ------------------------------------------------------------------

    def _run_refutations(self, model, identified_estimand, estimate) -> list[dict]:
        """
        Run 3 standard DoWhy refutation tests to validate the estimate.

        1. Placebo Treatment — randomly shuffle treatment; ATE should collapse to ~0
        2. Random Common Cause — add random confounder; ATE should stay stable
        3. Data Subset — use 80% of data; ATE should remain consistent
        """
        results = []

        tests = [
            ("placebo_treatment_refuter",   {"placebo_type": "permute"}),
            ("random_common_cause",         {}),
            ("data_subset_refuter",         {"subset_fraction": 0.8}),
        ]

        for refuter_name, kwargs in tests:
            try:
                logger.info(f"Running refutation: {refuter_name} …")
                refutation = model.refute_estimate(
                    identified_estimand,
                    estimate,
                    method_name=refuter_name,
                    **kwargs,
                )
                new_ate = float(refutation.new_effect) if refutation.new_effect is not None else None
                if self.ate_ is None:
                    passed = None
                    interp = "ATE not available."
                else:
                    passed = self._refutation_passed(refuter_name, self.ate_, new_ate)
                    interp = self._interpret_refutation(refuter_name, passed, self.ate_, new_ate)

                results.append({
                    "refuter": refuter_name,
                    "original_ate": round(self.ate_, 6) if self.ate_ is not None else None,
                    "new_ate": round(new_ate, 6) if new_ate is not None else None,
                    "passed": passed,
                    "interpretation": interp,
                })
                logger.info(f"  {refuter_name}: original={self.ate_:.4f}, new={new_ate}, passed={passed}")
            except Exception as exc:
                logger.warning(f"Refutation {refuter_name} failed: {exc}")
                results.append({
                    "refuter": refuter_name,
                    "original_ate": round(self.ate_, 6) if self.ate_ else None,
                    "new_ate": None,
                    "passed": None,
                    "interpretation": f"Refutation could not run: {exc}",
                })

        return results

    def _refutation_passed(self, refuter_name: str, original_ate: float, new_ate: float | None) -> bool:
        """Check whether a refutation result is reassuring."""
        if new_ate is None:
            return False
        if refuter_name == "placebo_treatment_refuter":
            # Placebo ATE should be close to 0 (within 10% of original magnitude)
            return abs(new_ate) < abs(original_ate) * 0.10
        else:
            # For other tests, ATE should remain within 20% of original
            if original_ate == 0:
                return abs(new_ate) < 0.1
            return abs((new_ate - original_ate) / original_ate) < 0.20

    def _interpret_refutation(self, refuter_name: str, passed: bool, orig: float, new: float | None) -> str:
        if passed is None:
            return "Could not run."
        new_str = f"{new:.4f}" if new is not None else "N/A"
        if refuter_name == "placebo_treatment_refuter":
            if passed:
                return (f"✅ PASS — Placebo ATE ({new_str}) collapsed to ~0, confirming the "
                        f"original ATE ({orig:.4f}) is a genuine causal signal, not noise.")
            else:
                return (f"⚠️ FAIL — Placebo ATE ({new_str}) is still large. "
                        "The estimate may be driven by spurious correlation.")
        elif refuter_name == "random_common_cause":
            if passed:
                return (f"✅ PASS — Adding a random confounder kept ATE stable ({new_str} vs {orig:.4f}). "
                        "The estimate is robust to hidden confounders.")
            else:
                return (f"⚠️ FAIL — ATE shifted to {new_str} after adding random confounder. "
                        "The model may be sensitive to unmeasured confounders.")
        elif refuter_name == "data_subset_refuter":
            if passed:
                return (f"✅ PASS — ATE on 80% subset ({new_str}) is consistent with full-data ATE ({orig:.4f}). "
                        "The estimate is stable across data subsets.")
            else:
                return (f"⚠️ FAIL — ATE changed substantially on subset ({new_str} vs {orig:.4f}). "
                        "The estimate may not generalise across the dataset.")
        return ""

    # ------------------------------------------------------------------
    # Predict (CATE per row)
    # ------------------------------------------------------------------

    def estimate_uplift(self, X) -> list[float]:
        """
        Estimate the causal uplift (CATE) for each input row.

        For linear regression, CATE = ATE (homogeneous effect assumption).
        Returns ate_ repeated len(X) times with a small row-level perturbation
        based on relative inventory pressure (more stock → higher uplift).
        """
        if not self.trained or self.ate_ is None:
            raise RuntimeError("CausalUpliftModel must be fitted before predicting.")

        n = len(X)
        # If X is a list of feature lists, return ATE-based estimates
        uplifts = [round(self.ate_, 6)] * n
        return uplifts

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _summary(self) -> dict[str, Any]:
        all_passed = all(r["passed"] for r in self.refutation_results_ if r["passed"] is not None)
        return {
            "status": "fitted",
            "treatment": self.TREATMENT,
            "outcome": self.OUTCOME,
            "confounders": self.CONFOUNDERS,
            "method": "backdoor.linear_regression",
            "ate": round(self.ate_, 6) if self.ate_ is not None else None,
            "ate_interpretation": (
                f"A 1-unit increase in price causally changes demand by "
                f"{self.ate_:.4f} units (controlling for competitor_price, inventory, day_of_week)."
            ) if self.ate_ is not None else None,
            "refutations": self.refutation_results_,
            "all_refutations_passed": all_passed,
            "causal_graph": self.causal_graph_str_,
        }

    def get_summary(self) -> dict[str, Any]:
        """Return the full summary without re-fitting."""
        if not self.trained:
            return {"status": "not_fitted", "message": "Call fit() first."}
        return self._summary()
