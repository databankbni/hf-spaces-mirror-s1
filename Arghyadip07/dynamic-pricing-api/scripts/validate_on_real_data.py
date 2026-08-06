"""
Standalone script to run validation on the UCI Online Retail dataset.
"""

import sys
import logging
import json
from pathlib import Path

# Add project root to sys.path so we can import from src
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.services.validation_service import ValidationService

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

def main():
    print("Initializing Validation Service...")
    service = ValidationService()
    service.startup()
    
    print("\nStarting Real-World Validation (UCI Online Retail dataset)...")
    print("This may take a minute to download and process.\n")
    
    try:
        result = service.validate_on_real_world()
        
        print("\n=== Validation Results ===")
        print(f"Source: {result.get('source')}")
        print(f"Dataset Name: {result.get('dataset_name')}")
        print(f"Rows Evaluated: {result.get('rows_evaluated')}")
        print("-" * 25)
        print(f"RMSE (Root Mean Squared Error): {result.get('rmse')}")
        print(f"MAE (Mean Absolute Error): {result.get('mae')}")
        print(f"MAPE (Mean Absolute Percentage Error): {result.get('mape_percent')}%")
        print(f"Prediction Accuracy: {result.get('prediction_accuracy_percent')}%")
        print("-" * 25)
        print("Note: " + result.get('note', ''))
        
        print("\nSample Predictions:")
        print(json.dumps(result.get("sample_predictions", []), indent=2))
        
    except Exception as e:
        print(f"Error during validation: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
