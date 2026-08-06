import os

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import mean_squared_error
from sklearn.model_selection import train_test_split
from xgboost import XGBRegressor
from src.core.settings import settings
from src.features.data_generation import generate_market_data, load_real_data
from src.features.pipeline import run_feature_pipeline, save_raw_data

REAL_DATA_PROC_PATH = "data/processed/super_model_data_clean.csv"

FEATURE_COLUMNS = [
    "price",
    "competitor_price",
    "inventory",
    "day_of_week",
    "price_gap",
    "price_ratio",
    "inventory_pressure",
    "is_weekend",
    "dow_sin",
    "dow_cos",
    "demand_lag_1",
    "demand_lag_7",
    "demand_roll_mean_7",
]


def _split_features_target(df: pd.DataFrame):
    return df[FEATURE_COLUMNS], df["demand"]


def _synthetic_training_df(n: int = 5000) -> pd.DataFrame:
    """Generate a minimal synthetic dataset usable for training and reference rows."""
    rng = np.random.default_rng(42)
    price = rng.uniform(50, 200, n)
    competitor_price = price * rng.uniform(0.85, 1.15, n)
    inventory = rng.integers(50, 800, n).astype(float)
    day_of_week = rng.integers(0, 7, n).astype(float)
    price_gap = price - competitor_price
    price_ratio = price / np.maximum(competitor_price, 1.0)
    inventory_pressure = inventory / 500.0
    is_weekend = ((day_of_week == 5) | (day_of_week == 6)).astype(float)
    angle = 2 * np.pi * day_of_week / 7
    dow_sin = np.sin(angle)
    dow_cos = np.cos(angle)
    demand = np.clip(
        200 - 0.8 * price + 0.3 * competitor_price + 0.05 * inventory + 25 * is_weekend + rng.normal(0, 10, n),
        0, None
    )
    demand_lag_1 = np.roll(demand, 1)
    demand_lag_7 = np.roll(demand, 7)
    demand_roll_mean_7 = pd.Series(demand).rolling(7, min_periods=1).mean().to_numpy()
    return pd.DataFrame({
        "price": price,
        "competitor_price": competitor_price,
        "inventory": inventory,
        "day_of_week": day_of_week,
        "price_gap": price_gap,
        "price_ratio": price_ratio,
        "inventory_pressure": inventory_pressure,
        "is_weekend": is_weekend,
        "dow_sin": dow_sin,
        "dow_cos": dow_cos,
        "demand_lag_1": demand_lag_1,
        "demand_lag_7": demand_lag_7,
        "demand_roll_mean_7": demand_roll_mean_7,
        "demand": demand,
    })


def _ensure_training_data(data_path: str) -> None:
    if os.path.exists(data_path):
        return

    # Prefer real data if ingested via scripts/ingest_real_data.py
    real_df = load_real_data()
    if real_df is not None:
        raw_data_path = str(settings.raw_data_abspath)
        save_raw_data(real_df, raw_data_path)
        run_feature_pipeline(raw_data_path, data_path)
        return

    # Try synthetic pipeline via data_generation
    raw_data_path = str(settings.raw_data_abspath)
    if not os.path.exists(raw_data_path):
        raw_df = generate_market_data(seed=settings.model_random_seed)
        save_raw_data(raw_df, raw_data_path)

    try:
        run_feature_pipeline(raw_data_path, data_path)
    except Exception:
        # Last resort: write the synthetic df directly so training can proceed
        import logging
        logging.getLogger(__name__).warning(
            "Pipeline failed — writing synthetic training data to %s", data_path
        )
        os.makedirs(os.path.dirname(data_path), exist_ok=True)
        _synthetic_training_df().to_csv(data_path, index=False)


def train_demand_model(data_path: str = "data/processed/super_model_data_clean.csv"):
    _ensure_training_data(data_path)
    df = pd.read_csv(data_path)
    X, y = _split_features_target(df)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=settings.model_test_size, random_state=settings.model_random_seed
    )

    model = XGBRegressor(
        n_estimators=settings.xgb_n_estimators,
        learning_rate=settings.xgb_learning_rate,
        max_depth=settings.xgb_max_depth,
        subsample=settings.xgb_subsample,
        colsample_bytree=settings.xgb_colsample_bytree,
        random_state=settings.model_random_seed,
    )
    model.fit(X_train, y_train)

    rmse = np.sqrt(mean_squared_error(y_test, model.predict(X_test)))
    metrics = {"rmse": float(rmse), "n_train": int(len(X_train)), "n_test": int(len(X_test))}
    return model, metrics


def get_reference_row(data_path: str = "data/processed/super_model_data_clean.csv") -> pd.Series:
    if os.path.exists(data_path):
        df = pd.read_csv(data_path)
    else:
        import logging
        logging.getLogger(__name__).warning(
            "Data file not found at %s — using synthetic reference row.", data_path
        )
        df = _synthetic_training_df()
    return df[FEATURE_COLUMNS].median(numeric_only=True)


def build_feature_row(
    price: float,
    competitor_price: float,
    inventory: int,
    day_of_week: int,
    reference_row: pd.Series,
) -> pd.DataFrame:
    is_weekend = int(day_of_week in [5, 6])
    inventory_pressure = inventory / max(float(reference_row["inventory"]), 1.0)
    angle = 2 * np.pi * day_of_week / 7

    row = {
        "price": price,
        "competitor_price": competitor_price,
        "inventory": inventory,
        "day_of_week": day_of_week,
        "price_gap": price - competitor_price,
        "price_ratio": price / competitor_price if competitor_price != 0 else 1.0,
        "inventory_pressure": inventory_pressure,
        "is_weekend": is_weekend,
        "dow_sin": float(np.sin(angle)),
        "dow_cos": float(np.cos(angle)),
        "demand_lag_1": float(reference_row["demand_lag_1"]),
        "demand_lag_7": float(reference_row["demand_lag_7"]),
        "demand_roll_mean_7": float(reference_row["demand_roll_mean_7"]),
    }

    return pd.DataFrame([row], columns=FEATURE_COLUMNS)


def save_model_artifact(
    model,
    reference_row: pd.Series,
    artifact_path: str = "artifacts/demand_model.joblib",
) -> None:
    artifact_dir = os.path.dirname(artifact_path)
    if artifact_dir:
        os.makedirs(artifact_dir, exist_ok=True)

    joblib.dump(
        {"model": model, "reference_row": reference_row, "feature_columns": FEATURE_COLUMNS},
        artifact_path,
    )


def load_model_artifact(artifact_path: str = "artifacts/demand_model.joblib"):
    if not os.path.exists(artifact_path):
        return None, None
    artifact = joblib.load(artifact_path)
    return artifact.get("model"), artifact.get("reference_row")


def train_and_save_model_artifact(
    data_path: str = "data/processed/super_model_data_clean.csv",
    artifact_path: str = "artifacts/demand_model.joblib",
):
    model, metrics = train_demand_model(data_path=data_path)
    reference_row = get_reference_row(data_path=data_path)
    save_model_artifact(model=model, reference_row=reference_row, artifact_path=artifact_path)
    return model, reference_row, metrics


def load_or_train_model_artifact(
    data_path: str = "data/processed/super_model_data_clean.csv",
    artifact_path: str = "artifacts/demand_model.joblib",
):
    model, reference_row = load_model_artifact(artifact_path=artifact_path)
    if model is not None and reference_row is not None:
        return model, reference_row, {"source": "artifact"}

    model, reference_row, metrics = train_and_save_model_artifact(
        data_path=data_path,
        artifact_path=artifact_path,
    )
    metrics["source"] = "trained"  # type: ignore[assignment]
    return model, reference_row, metrics
