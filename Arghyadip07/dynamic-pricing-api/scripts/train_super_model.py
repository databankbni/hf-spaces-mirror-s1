import sys
import os
import joblib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.models.demand import train_demand_model, get_reference_row

def main():
    print("Training SUPER MODEL on combined real datasets...")
    data_path = "data/processed/super_model_data_clean.csv"
    
    if not os.path.exists(data_path):
        print(f"Error: {data_path} not found. Run ingest_super_model.py first.")
        return
        
    # Train the model
    model, metrics = train_demand_model(data_path)
    print(f"Training Complete! Metrics: {metrics}")
    
    # Save the model
    os.makedirs("artifacts", exist_ok=True)
    
    reference_row = get_reference_row(data_path)
    joblib.dump({"model": model, "reference_row": reference_row}, "artifacts/demand_model.joblib")
    
    print("Super Model deployed to artifacts/demand_model.joblib")
    
if __name__ == "__main__":
    main()
