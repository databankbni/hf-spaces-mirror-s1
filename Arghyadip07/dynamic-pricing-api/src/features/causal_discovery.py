import logging
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import zscore, skew
from sklearn.preprocessing import PowerTransformer

# Try importing causal-learn algorithms
try:
    from causallearn.search.ConstraintBased.PC import pc
    from causallearn.search.ScoreBased.GES import ges
    from causallearn.utils.GraphUtils import GraphUtils
    from causallearn.search.FCMBased import lingam
except ImportError:
    pc, ges, GraphUtils, lingam = None, None, None, None

logger = logging.getLogger(__name__)

def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Remove missing values, duplicate rows, and infinite values.
    """
    logger.info(f"Original shape before cleaning: {df.shape}")
    
    # Replace infinities with NaNs so they can be dropped
    df = df.replace([np.inf, -np.inf], np.nan)
    
    # Replace missing values with column means instead of dropping
    for col in df.columns:
        if df[col].isnull().any():
            if pd.api.types.is_numeric_dtype(df[col]):
                df[col] = df[col].fillna(df[col].mean())
    
    # Drop duplicate rows
    df = df.drop_duplicates()
    
    logger.info(f"Shape after basic cleaning: {df.shape}")
    return df

def fix_skewness(df: pd.DataFrame, threshold: float = 0.5) -> pd.DataFrame:
    """
    Check skewness of numeric columns. If absolute skewness > threshold,
    apply a Yeo-Johnson power transformation to normalize it.
    """
    df_transformed = df.copy()
    numeric_cols = df_transformed.select_dtypes(include=[np.number]).columns
    
    skewness = df_transformed[numeric_cols].apply(lambda x: skew(x.dropna()))
    highly_skewed_cols = skewness[abs(skewness) > threshold].index.tolist()
    
    if highly_skewed_cols:
        logger.info(f"Highly skewed columns detected: {highly_skewed_cols}")
        pt = PowerTransformer(method='yeo-johnson')
        # We transform only the skewed columns to keep the others intact
        df_transformed[highly_skewed_cols] = pt.fit_transform(df_transformed[highly_skewed_cols])
        logger.info("Applied Yeo-Johnson transform to highly skewed columns.")
    else:
        logger.info("No highly skewed columns detected.")
        
    return df_transformed

def remove_outliers(df: pd.DataFrame, z_threshold: float = 3.0) -> pd.DataFrame:
    """
    Removes rows where any numeric feature has a Z-score greater than the threshold.
    """
    df_clean = df.copy()
    numeric_cols = df_clean.select_dtypes(include=[np.number]).columns
    
    # Calculate absolute z-scores for numeric columns
    z_scores = np.abs(zscore(df_clean[numeric_cols]))
    
    # Keep rows where all numeric values have a z-score < z_threshold
    mask = (z_scores < z_threshold).all(axis=1)
    df_clean = df_clean[mask]
    
    removed_count = len(df) - len(df_clean)
    logger.info(f"Removed {removed_count} outliers using Z-score threshold {z_threshold}")
    
    return df_clean

def run_pc_algorithm(df: pd.DataFrame, alpha: float = 0.05) -> Any:
    """
    Run the PC (Peter-Clark) algorithm for causal discovery.
    Requires numeric data.
    """
    if pc is None:
        raise ImportError("causal-learn is not installed. Run `pip install causal-learn`.")
        
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    data_matrix = df[numeric_cols].to_numpy()
    
    logger.info(f"Running PC algorithm on {data_matrix.shape[1]} variables...")
    # By default, Fisher-z test is used for continuous data
    cg = pc(data_matrix, alpha=alpha, show_progress=False)
    labels = list(numeric_cols)
        
    return cg, labels

def run_ges_algorithm(df: pd.DataFrame) -> Any:
    """
    Run the GES (Greedy Equivalence Search) algorithm for causal discovery.
    Requires numeric data.
    """
    if ges is None:
        raise ImportError("causal-learn is not installed. Run `pip install causal-learn`.")
        
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    data_matrix = df[numeric_cols].to_numpy()
    
    logger.info(f"Running GES algorithm on {data_matrix.shape[1]} variables...")
    # Usually uses BIC score
    record = ges(data_matrix)
    cg = record['G']
    labels = list(numeric_cols)
        
    return cg, labels

def run_lingam_algorithm(df: pd.DataFrame) -> Any:
    """
    Run DirectLiNGAM algorithm for causal discovery.
    Guarantees a fully oriented Directed Acyclic Graph (DAG) under 
    linear non-Gaussian assumptions.
    Returns (adjacency_matrix, labels).
    """
    if lingam is None:
        raise ImportError("causal-learn is not installed.")
        
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    data_matrix = df[numeric_cols].to_numpy()
    
    logger.info(f"Running LiNGAM algorithm on {data_matrix.shape[1]} variables...")
    model = lingam.DirectLiNGAM()
    model.fit(data_matrix)
    
    labels = list(numeric_cols)
    return model.adjacency_matrix_, labels
