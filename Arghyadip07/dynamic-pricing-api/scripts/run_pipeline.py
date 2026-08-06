from src.features.data_generation import generate_market_data
from src.features.pipeline import run_feature_pipeline, save_raw_data


if __name__ == "__main__":
    raw_df = generate_market_data()
    save_raw_data(raw_df, "data/raw/market_data.csv")
    run_feature_pipeline("data/raw/market_data.csv", "data/processed/clean_market_data.csv")
    print("Pipeline completed: raw and processed datasets generated.")
