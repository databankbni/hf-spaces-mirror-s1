# app.py - Flask REST API that serves the SuperKart sales prediction pipeline

import joblib
import pandas as pd
from flask import Flask, request, jsonify

superkart_api = Flask("superkart_api")

# Full sklearn Pipeline: ColumnTransformer (One-Hot encoding) + tuned model.
# Preprocessing travels inside the pipeline, so the API works with raw values.
model = joblib.load("SuperKartModel.joblib")

# Raw input columns the pipeline expects (stored when fitting with a DataFrame)
MODEL_COLUMNS = list(model.feature_names_in_)

@superkart_api.get('/')
def home():
    return "Welcome to the SuperKart Sales Prediction API! Use POST /v1/predict to get a sales forecast."

@superkart_api.post('/v1/predict')
def predict_sales():
    # --- Basic input validation ---
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': 'Request body must be valid JSON with Content-Type: application/json.'}), 400
    if not isinstance(data, dict):
        return jsonify({'error': 'JSON body must be an object with feature name/value pairs.'}), 400

    missing = [col for col in MODEL_COLUMNS if col not in data]
    if missing:
        return jsonify({'error': f'Missing required fields: {missing}',
                        'expected_fields': MODEL_COLUMNS}), 400

    # --- Prediction ---
    # Build a single-row DataFrame with the raw features, in the expected order.
    # The pipeline handles the One-Hot encoding internally.
    input_data = pd.DataFrame([{col: data[col] for col in MODEL_COLUMNS}])

    try:
        prediction = float(model.predict(input_data)[0])
    except Exception as exc:
        return jsonify({'error': f'Prediction failed: {exc}'}), 400

    return jsonify({'Sales': prediction})

if __name__ == '__main__':
    superkart_api.run(debug=True)
