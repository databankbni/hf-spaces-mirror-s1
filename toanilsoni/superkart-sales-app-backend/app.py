
import numpy as np
import joblib
import pandas as pd
from flask import Flask, request, jsonify
from flask_cors import CORS  # Import CORS

# Initialize Flask app and enable CORS for all origins
superkart_api = Flask(__name__)
CORS(superkart_api)

# Load trained pipeline
model = joblib.load("best_model_pipeline.joblib")

@superkart_api.get('/')
def home():
    return jsonify({"status": "active", "message": "Welcome to the Superkart Sales Prediction API!"}), 200

@superkart_api.post('/v1/predict')
def predict_sales():
    try:
        # Get JSON payload
        data = request.get_json(force=True)

        # Construct single-row DataFrame matching the exact feature names expected by your pipeline
        sample = {
            'Product_Weight': [float(data.get('Product_Weight', 0))],
            'Product_Sugar_Content': [str(data.get('Product_Sugar_Content', ''))],
            'Product_Allocated_Area': [float(data.get('Product_Allocated_Area', 0))],
            'Product_MRP': [float(data.get('Product_MRP', 0))],
            'Store_Size': [str(data.get('Store_Size', ''))],
            'Store_Location_City_Type': [str(data.get('Store_Location_City_Type', ''))],
            'Store_Type': [str(data.get('Store_Type', ''))],
            'Product_Id_char': [str(data.get('Product_Id_char', ''))],
            'Store_Age_Years': [int(data.get('Store_Age_Years', 0))],
            'Product_Type_Category': [str(data.get('Product_Type_Category', ''))]
        }

        input_df = pd.DataFrame(sample)

        # Run model prediction
        prediction = model.predict(input_df)[0]

        return jsonify({'Sales': float(prediction)}), 200

    except Exception as e:
        # Return exact exception text so frontend or logs can see it
        return jsonify({'error': str(e)}), 400

if __name__ == '__main__':
    superkart_api.run(host='0.0.0.0', port=7860)
