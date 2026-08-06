import os
import pandas as pd
import numpy as np

def process_kaggle_inventory():
    print("Processing Kaggle Inventory Dataset...")
    df = pd.read_csv("data/raw/kaggle_inventory/retail_store_inventory.csv")
    df['Date'] = pd.to_datetime(df['Date'])
    
    # Map to unified schema
    df_unified = pd.DataFrame()
    df_unified['price'] = df['Price']
    df_unified['demand'] = df['SalesQty']
    df_unified['competitor_price'] = df['CompetitorPrice']
    df_unified['inventory'] = df['InventoryLevel']
    df_unified['day_of_week'] = df['Date'].dt.dayofweek
    return df_unified

def process_kaggle_pricing():
    print("Processing Kaggle Pricing Signals Dataset...")
    df = pd.read_csv("data/raw/kaggle_pricing/pricing_demand_signals.csv")
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # Map to unified schema
    df_unified = pd.DataFrame()
    df_unified['price'] = df['current_price']
    df_unified['demand'] = df['demand']
    df_unified['competitor_price'] = df['comp_price']
    df_unified['inventory'] = df['stock_available']
    df_unified['day_of_week'] = df['timestamp'].dt.dayofweek
    return df_unified

def ingest_super_model_data():
    # 1. Ensure UCI data is processed
    uci_path = "data/processed/real_clean_data.csv"
    if not os.path.exists(uci_path):
        print(f"File {uci_path} not found. Ensure ingest_real_data.py has been run.")
        df_uci = pd.DataFrame()
    else:
        df_uci = pd.read_csv(uci_path)
        print(f"Loaded {len(df_uci)} rows from UCI Retail dataset.")
        
    # 2. Process Kaggle Datasets
    df_inventory = process_kaggle_inventory()
    print(f"Loaded {len(df_inventory)} rows from Kaggle Inventory dataset.")
    
    df_pricing = process_kaggle_pricing()
    print(f"Loaded {len(df_pricing)} rows from Kaggle Pricing dataset.")
    
    # 3. Combine them
    df_super = pd.concat([df_uci, df_inventory, df_pricing], ignore_index=True)
    
    # 4. Save raw super model dataset
    os.makedirs("data/raw", exist_ok=True)
    raw_output_path = "data/raw/super_model_data.csv"
    df_super.to_csv(raw_output_path, index=False)
    print(f"Successfully combined into RAW SUPER MODEL DATASET: {len(df_super)} rows -> {raw_output_path}")

    # 5. Run feature pipeline
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src.features.pipeline import run_feature_pipeline
    
    clean_output_path = "data/processed/super_model_data_clean.csv"
    print("Running feature pipeline to generate lag features and ratios...")
    run_feature_pipeline(raw_output_path, clean_output_path)
    print(f"Finished processing. Final dataset ready at: {clean_output_path}")

if __name__ == "__main__":
    ingest_super_model_data()
