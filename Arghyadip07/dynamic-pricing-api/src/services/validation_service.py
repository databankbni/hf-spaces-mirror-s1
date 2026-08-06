"""
Validation Service — evaluate the demand model on real-world datasets.

Uses the UCI Online Retail dataset (public domain) as the primary real-world
reference. The dataset is adapted to our feature schema:
  - UnitPrice       → price
  - Quantity        → demand  (clipped to ≥ 1)
  - competitor_price → price ± 5% gaussian noise (industry standard proxy)
  - inventory       → rolling 7-day quantity sum (demand proxy)
  - day_of_week     → derived from InvoiceDate
  - demand_lag_*    → computed by feature pipeline

Falls back to a holdout split of the synthetic dataset when the real dataset
is not available (e.g. no internet access on HuggingFace).
"""

import io
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error

from src.core.settings import settings
from src.models.demand import (
    FEATURE_COLUMNS,
    build_feature_row,
    load_or_train_model_artifact,
)

logger = logging.getLogger(__name__)

_UCI_RETAIL_URL = (
    "https://archive.ics.uci.edu/ml/machine-learning-databases/"
    "00352/Online%20Retail.xlsx"
)


class ValidationService:
    """Evaluate the demand model against both synthetic holdout and real-world data."""

    def __init__(self, data_path: str | None = None, artifact_path: str | None = None):
        self.data_path = data_path or str(settings.processed_data_abspath)
        self.artifact_path = artifact_path or str(settings.model_artifact_abspath)
        self.model = None
        self.reference_row = None

    def startup(self) -> None:
        self.model, self.reference_row, _ = load_or_train_model_artifact(
            data_path=self.data_path,
            artifact_path=self.artifact_path,
        )

    def _ensure_ready(self) -> None:
        if self.model is None or self.reference_row is None:
            self.startup()

    # ------------------------------------------------------------------
    # Public validation methods
    # ------------------------------------------------------------------

    def validate_on_synthetic_holdout(self, holdout_fraction: float = 0.20) -> dict[str, Any]:
        """
        Evaluate on the last `holdout_fraction` of the synthetic processed dataset.
        This gives a reproducible baseline that always works.
        """
        self._ensure_ready()
        df = pd.read_csv(self.data_path)
        split = max(1, int(len(df) * (1 - holdout_fraction)))
        holdout = df.iloc[split:].copy()

        return self._score(holdout, dataset_name="synthetic_holdout")

    def validate_on_csv(self, csv_path: str | Path, dataset_name: str = "custom") -> dict[str, Any]:
        """
        Evaluate on any user-supplied CSV that already matches our feature schema
        (must contain all FEATURE_COLUMNS + 'demand').
        """
        self._ensure_ready()
        df = pd.read_csv(csv_path)
        missing = [c for c in FEATURE_COLUMNS + ["demand"] if c not in df.columns]
        if missing:
            raise ValueError(f"CSV is missing required columns: {missing}")
        return self._score(df, dataset_name=dataset_name)

    def validate_on_real_world(self) -> dict[str, Any]:
        """
        Evaluate on the UCI Online Retail dataset.

        Steps:
          1. Try to download UCI Excel file
          2. Adapt columns to our feature schema
          3. Score the model on the adapted data
          4. If download fails, fall back to synthetic holdout with a note
        """
        self._ensure_ready()
        try:
            df_adapted = self._load_uci_retail()
            result = self._score(df_adapted, dataset_name="uci_online_retail")
            result["source"] = "uci_online_retail"
            result["note"] = (
                "UCI Online Retail dataset (541K UK e-commerce transactions, 2010-2011). "
                "competitor_price approximated as price ± 5% gaussian noise."
            )
            return result
        except Exception as exc:
            logger.warning("UCI dataset unavailable (%s) — falling back to synthetic holdout.", exc)
            result = self.validate_on_synthetic_holdout()
            result["source"] = "synthetic_holdout_fallback"
            result["note"] = (
                f"Real-world dataset unavailable ({exc}). "
                "Showing synthetic holdout results instead."
            )
            return result

    # ------------------------------------------------------------------
    # UCI dataset adapter
    # ------------------------------------------------------------------

    def _load_uci_retail(self) -> pd.DataFrame:
        """Download and adapt the UCI Online Retail dataset to our feature schema."""
        import urllib.request

        logger.info("Downloading UCI Online Retail dataset …")
        with urllib.request.urlopen(_UCI_RETAIL_URL, timeout=30) as resp:
            raw = resp.read()

        df = pd.read_excel(io.BytesIO(raw), engine="openpyxl")

        # Basic cleaning
        # Keep rows but ensure no nulls by filling with means later. InvoiceDate is a datetime, so we must drop it if missing.
        df = df.dropna(subset=["InvoiceDate"])
        df = df[(df["UnitPrice"].fillna(1.0) > 0)]
        df = df[(df["Quantity"].fillna(1.0) > 0)]
        df = df.copy()

        # Map to our schema
        df["price"] = df["UnitPrice"].astype(float)
        df["demand"] = df["Quantity"].clip(lower=1).astype(float)
        df["day_of_week"] = pd.to_datetime(df["InvoiceDate"]).dt.dayofweek

        # Synthesize competitor_price as price ± 5% noise (standard proxy)
        rng = np.random.default_rng(42)
        noise = rng.normal(0, 0.05, len(df))
        df["competitor_price"] = (df["price"] * (1 + noise)).clip(lower=0.01)

        # Inventory proxy: rolling 7-row quantity sum per StockCode
        df = df.sort_values("InvoiceDate")
        df["inventory"] = (
            df.groupby("StockCode")["Quantity"]
            .transform(lambda x: x.shift(1).rolling(7, min_periods=1).sum())
            .fillna(50)
            .clip(lower=1)
            .astype(int)
        )

        # Derived features (match feature engineering pipeline)
        df["price_gap"] = df["price"] - df["competitor_price"]
        df["price_ratio"] = (df["price"] / df["competitor_price"].replace(0, np.nan)).fillna(1.0)
        df["inventory_pressure"] = df["inventory"] / df["inventory"].max().clip(lower=1)
        df["is_weekend"] = df["day_of_week"].isin([5, 6]).astype(int)
        angle = 2 * np.pi * df["day_of_week"] / 7
        df["dow_sin"] = np.sin(angle)
        df["dow_cos"] = np.cos(angle)

        median_demand = df["demand"].median()
        df["demand_lag_1"] = df["demand"].shift(1).fillna(median_demand)
        df["demand_lag_7"] = df["demand"].shift(7).fillna(median_demand)
        df["demand_roll_mean_7"] = df["demand"].rolling(7, min_periods=1).mean()

        for col in FEATURE_COLUMNS:
            if df[col].isnull().any():
                df[col] = df[col].fillna(df[col].mean())
        logger.info("UCI dataset adapted: %d rows ready for scoring.", len(df))
        return df

    # ------------------------------------------------------------------
    # Scoring helper
    # ------------------------------------------------------------------

    def _score(self, df: pd.DataFrame, dataset_name: str) -> dict[str, Any]:
        """Score the demand model on a DataFrame and return evaluation metrics."""
        df = df[FEATURE_COLUMNS + ["demand"]].copy()
        for col in df.columns:
            if df[col].isnull().any():
                df[col] = df[col].fillna(df[col].mean())
        if len(df) == 0:
            return {"error": "No valid rows to score", "dataset_name": dataset_name}

        X = df[FEATURE_COLUMNS]
        y_true = df["demand"].to_numpy(dtype=float)
        assert self.model is not None, "Model must be loaded before scoring"
        y_pred = self.model.predict(X).astype(float)

        rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
        mae = float(mean_absolute_error(y_true, y_pred))
        mape = float(
            np.mean(np.abs((y_true - y_pred) / np.maximum(np.abs(y_true), 1))) * 100
        )

        # Sample predictions (first 5 rows for inspection)
        sample = []
        for i in range(min(5, len(df))):
            sample.append({
                "actual_demand": round(float(y_true[i]), 2),
                "predicted_demand": round(float(y_pred[i]), 2),
                "error": round(float(y_pred[i] - y_true[i]), 2),
            })

        return {
            "dataset_name": dataset_name,
            "rows_evaluated": len(df),
            "rmse": round(rmse, 4),
            "mae": round(mae, 4),
            "mape_percent": round(mape, 2),
            "prediction_accuracy_percent": round(max(0.0, 100.0 - mape), 2),
            "sample_predictions": sample,
        }
