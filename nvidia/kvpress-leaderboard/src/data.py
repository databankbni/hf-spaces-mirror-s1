# SPDX-FileCopyrightText: Copyright (c) 1993-2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Union

import pandas as pd
import yaml

from src.settings import METHOD_TO_PRETTY_NAME, PRETTY_NAME_TO_ADDITIONAL_INFO
from src.utils import make_dataset_clickable, make_method_clickable, make_model_clickable


logger = logging.getLogger(__name__)


@dataclass
class EvaluationConfig:
    """Dataclass to handle all the configuration for the evaluation."""

    # Core evaluation parameters
    dataset: str
    data_dir: Optional[str]
    model: str
    device: Optional[str]
    press_name: str
    compression_ratio: float
    key_channel_compression_ratio: Optional[float] = None

    # Dataset and generation parameters
    fraction: float = 1.0
    max_new_tokens: Optional[int] = None
    max_context_length: Optional[int] = None

    # Query-aware compression
    # When True, the question is included in context during compression
    query_aware: bool = False
    compress_questions: Optional[bool] = None  # Legacy field, maps to query_aware

    # Output and logging
    output_dir: str = ""
    log_level: str = "INFO"

    # Press initialization command
    press_init_command: str = ""

    # Model-specific parameters
    model_kwargs: Optional[Dict[str, Any]] = None

    # Settings
    seed: Optional[int] = None

    # Additional optional parameters for new presses
    threshold: Optional[float] = None
    needle_depth: Optional[float] = None
    compression_interval: Optional[int] = None
    target_size: Optional[int] = None
    hidden_states_buffer_size: Optional[int] = None
    fp8: bool = False
    restore_checkpoint: Optional[str] = None

    def is_query_aware(self) -> bool:
        """Check if compression is query-aware (question included during compression)."""
        # Check both the new field and the legacy field
        return self.query_aware or (self.compress_questions is True)


def _load_yaml_config(path: str | Path) -> dict:
    """Loads a YAML file. Returns an empty dict if it doesn't exist."""
    try:
        with open(path, "r") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.warning(f"Config file not found at {path}. Using only command-line arguments and defaults.")
        return {}


def load_evaluation_results(results_dir: Union[str, Path], pretty_method_names: bool = False) -> pd.DataFrame:
    """
    Load evaluation results from a dir containing subdirectories with JSON files and create a pandas DataFrame for leaderboard.
    Only allows compression ratio variations - throws error for other parameter variations.

    Parameters
    ----------
    results_dir : Union[str, Path]
        Directory containing subdirectories, each with a metrics.json file and config.yaml file.
        The subdirectory names should be in the format: dataset__data_dir__model__method__compression_ratio__<additional_params>
    pretty_method_names : bool, optional
        Whether to convert method names to pretty names, according to settings.METHOD_TO_PRETTY_NAME

    Returns
    -------
    pd.DataFrame
        DataFrame with columns: dataset, data_dir, model, method, compression_ratio, press_init_command, and all metrics from the JSON files + their average
    """
    results_dir = Path(results_dir)

    # Find all subdirectories that contain both metrics.json and config.yaml files
    results = []

    for subdir in results_dir.iterdir():
        if not subdir.is_dir():
            continue

        metrics_file = subdir / "metrics.json"
        config_file = subdir / "config.yaml"
        prediction_file = subdir / "predictions.csv"

        if not metrics_file.exists():
            logger.warning(f"No metrics.json found in {subdir.name}")
            continue

        if not config_file.exists():
            logger.warning(f"No config.yaml found in {subdir.name}")
            continue

        # Load configuration from YAML file and create EvaluationConfig object
        try:
            config_dict = _load_yaml_config(config_file)
            config = EvaluationConfig(**config_dict)
        except Exception as e:
            logger.error(f"Error loading config from {config_file}: {e}")
            continue

        # Load predictions from CSV file
        # For some presses, like DuoAttention, we need to read the predictions and infer the compression ratio from there
        # For all other presses, we can just use the compression ratio from the config.yaml file
        compression_ratio = None
        try:
            predictions = pd.read_csv(prediction_file)
            compression_ratio = predictions["compression_ratio"].mean().round(2).item()
        except Exception:
            logger.info(f"No predictions.csv found in {subdir.name}. Using compression ratio from config.yaml.")

        # Extract components from EvaluationConfig object
        try:
            dataset = config.dataset
            data_dir = config.data_dir
            model = config.model.replace("--", "/")
            method = config.press_name
            compression_ratio = compression_ratio or float(config.compression_ratio)
            query_aware = config.is_query_aware()
            press_init_command = config.press_init_command

            if config.fraction != 1.0:
                # skip if this was not a full dataset evaluation
                continue

            # We have to create a new method for this case
            # else they will be merged in the plot
            if query_aware:
                method = f"{method}_query_aware"

            # Validate required fields
            if not all([dataset, model, method]):
                logger.warning(f"Missing required fields in config for {subdir.name}. Skipping...")
                continue

        except (ValueError, TypeError, AttributeError) as e:
            logger.error(f"Could not parse config from {subdir.name}: {e}")
            continue

        # Load metrics from JSON file and compute score
        try:
            with open(metrics_file, "r") as f:
                metrics = json.load(f)
            score = round(sum(v["string_match"] for v in metrics.values()) / len(metrics), 2)
        except (json.JSONDecodeError, IOError, KeyError, ZeroDivisionError) as e:
            logger.error(f"Error loading {metrics_file}: {e}")
            continue

        # Create result entry
        result = {
            "dataset": dataset,
            "data_dir": data_dir,
            "model": model,
            "method": method,
            "compression_ratio": compression_ratio,
            "score": score,
            "query_aware": query_aware,
            "press_init_command": press_init_command,
            "filename": subdir.name,
        }

        results.append(result)

    if not results:
        raise ValueError(f"No valid results found in subdirectories of {results_dir}")

    # Create dataframe
    df = pd.DataFrame(results)
    df = df.reset_index(drop=True)

    df = df.sort_values(by="score", ascending=False)
    if pretty_method_names:
        df["method"] = df["method"].apply(lambda x: METHOD_TO_PRETTY_NAME.get(x, x))
        df["additional_info"] = df["method"].map(PRETTY_NAME_TO_ADDITIONAL_INFO)
    return df


def apply_clickable_transformations(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply clickable transformations to the dataframe columns.
    This should be called after filtering to make certain columns clickable.
    """
    transformed_df = df.copy()

    # Apply clickable transformations
    if "model" in transformed_df.columns:
        transformed_df["model"] = transformed_df["model"].apply(make_model_clickable)

    if "dataset" in transformed_df.columns:
        transformed_df["dataset"] = transformed_df["dataset"].apply(make_dataset_clickable)

    if "method" in transformed_df.columns:
        # Apply method clickable transformation with press_init_command as tooltip
        if "press_init_command" in transformed_df.columns:
            transformed_df["method"] = transformed_df.apply(
                lambda row: make_method_clickable(row["method"], row["press_init_command"]), axis=1
            )
        else:
            transformed_df["method"] = transformed_df["method"].apply(make_method_clickable)
    return transformed_df


def filter_dataframe(
    df: pd.DataFrame,
    search_query: str = None,
    compression_ratio_min: float = 0.0,
    compression_ratio_max: float = 1.0,
    selected_datasets: list[str] = None,
    selected_models: list[str] = None,
    selected_methods: list[str] = None,
    selected_columns: list[str] = None,
    apply_clickable: bool = False,
) -> pd.DataFrame:
    """
    Filter the dataframe according to the search query, compression ratio range, selected datasets, selected models, selected methods, and selected columns.

    Parameters
    ----------
    df : pd.DataFrame
        Input dataframe
    search_query : str, optional
        Search query to filter rows
    compression_ratio_min : float, optional
        Minimum compression ratio
    compression_ratio_max : float, optional
        Maximum compression ratio
    selected_datasets : list[str], optional
        List of datasets to include
    selected_models : list[str], optional
        List of models to include
    selected_methods : list[str], optional
        List of methods to include
    selected_columns : list[str], optional
        List of columns to include in output
    apply_clickable : bool, optional
        Whether to apply clickable transformations to model, dataset, and method columns
    """
    filtered_df = df.copy()

    # Search filter
    if search_query:
        search_terms = search_query.lower().split()
        for term in search_terms:
            mask = filtered_df.astype(str).apply(lambda x: x.str.lower().str.contains(term, na=False)).any(axis=1)
            filtered_df = filtered_df[mask]

    # Compression ratio filter
    filtered_df = filtered_df[
        (filtered_df["compression_ratio"] >= compression_ratio_min) & (filtered_df["compression_ratio"] <= compression_ratio_max)
    ]

    # Dataset filter
    if selected_datasets is not None:
        filtered_df = filtered_df[filtered_df["dataset"].isin(selected_datasets)]

    # Model filter
    if selected_models is not None:
        filtered_df = filtered_df[filtered_df["model"].isin(selected_models)]

    # Method filter
    if selected_methods is not None:
        filtered_df = filtered_df[filtered_df["method"].isin(selected_methods)]

    # Apply clickable transformations if requested (before column selection)
    if apply_clickable:
        filtered_df = apply_clickable_transformations(filtered_df)

    # Column selection (after applying clickable transformations)
    if selected_columns is not None:
        filtered_df = filtered_df[selected_columns]

    return filtered_df
