import os

import pandas as pd

from src.features.feature_engineering import create_features, remove_global_outliers

def save_raw_data(df: pd.DataFrame, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)


def load_raw_data(path: str) -> pd.DataFrame:
    return pd.read_csv(path)


def save_processed_data(df: pd.DataFrame, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)


def run_feature_pipeline(input_path: str, output_path: str) -> pd.DataFrame:
    raw_df = load_raw_data(input_path)
    feature_df = create_features(raw_df)
    feature_df = remove_global_outliers(feature_df, threshold=3.0)
    save_processed_data(feature_df, output_path)
    return feature_df
