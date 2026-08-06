import logging
import os

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

REAL_DATA_RAW_PATH = "data/raw/real_market_data.csv"


def load_real_data(path: str = REAL_DATA_RAW_PATH) -> pd.DataFrame | None:
    """
    Load real market data if it has been ingested via scripts/ingest_real_data.py.
    Returns None if the file does not exist (falls back to synthetic).
    """
    if not os.path.exists(path):
        return None
    logger.info("Loading real market data from %s …", path)
    df = pd.read_csv(path)
    required = ["price", "demand", "competitor_price", "inventory", "day_of_week"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        logger.warning("Real data missing columns %s — falling back to synthetic.", missing)
        return None
    logger.info("Real data loaded: %d rows.", len(df))
    return df


def generate_market_data(n_samples: int = 50000, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    price = rng.uniform(40, 1100, n_samples)
    competitor_price = price * rng.uniform(0.85, 1.15, n_samples)
    inventory = rng.integers(100, 1000, n_samples)
    day_of_week = rng.integers(0, 7, n_samples)

    demand = (
        1000
        - 0.5 * price
        + 0.2 * (competitor_price - price)
        + 0.1 * inventory
        + 20 * np.sin(day_of_week)
        + rng.normal(0, 30, n_samples)
    )
    demand = np.clip(demand, 0, None)

    return pd.DataFrame(
        {
            "price": price,
            "competitor_price": competitor_price,
            "inventory": inventory,
            "day_of_week": day_of_week,
            "demand": demand,
        }
    )
