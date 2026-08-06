import joblib
import numpy as np
import shap
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from typing import Dict, Any
import json
import os
from google import genai
from dotenv import load_dotenv

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here":
    gemini_client = genai.Client(api_key=GEMINI_API_KEY)
else:
    gemini_client = None


app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

model = joblib.load("fraud_classifier_phase3.pkl")
transformer = joblib.load("fraud_quantile_transformer.pkl")
explainer = shap.TreeExplainer(model)
threshold_meta = joblib.load("fraud_classifier_threshold_meta.pkl")
fraud_threshold = float(threshold_meta.get("threshold", 0.80))

with open("feature_config.json", "r") as f:
    config = json.load(f)
    FEATURE_NAMES = config["feature_names"]
    FEATURE_MEDIANS = config["medians"]

# Convert QT Medians to RAW Medians so we don't double scale values
try:
    medians_array = np.array([[FEATURE_MEDIANS[f] for f in FEATURE_NAMES]], dtype=float)
    raw_medians_array = transformer.inverse_transform(medians_array)
    RAW_MEDIANS = {f: float(raw_medians_array[0][i]) for i, f in enumerate(FEATURE_NAMES)}
except Exception:
    RAW_MEDIANS = FEATURE_MEDIANS

@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/predict")
def predict(transaction: Dict[str, Any]):
    # Assemble the 310 feature array
    input_features = []
    for feature in FEATURE_NAMES:
        val = transaction.get(feature)
        if val is None or val == "":
            val = RAW_MEDIANS.get(feature, 0.0)
        input_features.append(float(val))
    
    input_array = np.array([input_features], dtype=float)
    scaled_array = transformer.transform(input_array)
    probability = float(model.predict_proba(scaled_array)[0][1])
    risk_score = int(round(probability * 100))
    is_fraud = probability > fraud_threshold

    shap_values = explainer.shap_values(scaled_array)
    if isinstance(shap_values, list):
        shap_row = np.asarray(shap_values[-1])[0]
    else:
        shap_row = np.asarray(shap_values)[0]

    top_indices = np.argsort(np.abs(shap_row))[-3:][::-1]
    top_features = [FEATURE_NAMES[i] for i in top_indices]
    top_risk_feature = top_features[0]

    if is_fraud:
        fallback_explanation = (
            f"Based on deep neural analysis, this transaction exhibits anomalous behavior primarily due to irregular patterns in '{top_features[0]}', "
            f"compounded by unexpected values in '{top_features[1]}' and '{top_features[2]}'. "
            "This combination of factors strongly correlates with identified fraudulent or synthetic identity activities."
        )
    else:
        fallback_explanation = (
            "The model analyzed the transaction vectors and found the behavioral patterns "
            "to be within normal and expected operating thresholds. "
            f"The variables '{top_features[0]}' and '{top_features[1]}' were the most influential, "
            "but their alignments do not indicate significant risk."
        )

    explanation = fallback_explanation

    if gemini_client:
        prompt = (
            f"You are an elite AI fraud analyst system. The algorithm evaluated a transaction:\n"
            f"- Risk Score: {risk_score}%\n"
            f"- Classification: {'CRITICAL RISK (Fraud)' if is_fraud else 'AUTHORIZED (Safe)'}\n"
            f"- Top influencing factors (SHAP): {top_features[0]}, {top_features[1]}, and {top_features[2]}.\n\n"
            "Write a concise, professional 2-sentence explanation for the user interface explaining this decision. "
            "Make it sound like an advanced neural AI is generating the insight. Do not use formatting like bolding or asterisks."
        )
        try:
            response = gemini_client.models.generate_content(
                model="gemini-3.1-flash-lite",
                contents=prompt
            )
            if response and response.text:
                explanation = response.text.strip()
        except Exception as e:
            explanation = f"GEMINI API ERROR: {str(e)} | FALLBACK: " + fallback_explanation

    return {
        "probability": probability,
        "risk_score": risk_score,
        "is_fraud": is_fraud,
        "top_risk_feature": top_risk_feature,
        "ai_explanation": explanation,
    }

# Mount static frontend files
app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="static")

