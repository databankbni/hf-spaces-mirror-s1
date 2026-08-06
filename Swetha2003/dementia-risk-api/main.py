from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional
import numpy as np
import pandas as pd
import joblib
import shap
import os

from huggingface_hub import hf_hub_download



app = FastAPI(
    title="Dementia Risk Predictor API",
    description="Predicts dementia risk from non-medical variables using XGBoost.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Load model and artefacts at startup
# ---------------------------------------------------------------------------
BASE_DIR     = os.path.dirname(__file__)
#MODEL_PATH   = os.path.join(BASE_DIR, "artefacts", "xgboost_tuned.pkl")
MODEL_PATH    = hf_hub_download(repo_id="Swetha2003/dementia-risk-model", filename="xgboost_tuned.pkl")
FEATURES_PATH= os.path.join(BASE_DIR, "artefacts", "feature_names.csv")
METRICS_PATH = os.path.join(BASE_DIR, "artefacts", "step6_all_models_comparison.csv")
SHAP_PATH    = os.path.join(BASE_DIR, "artefacts", "step6_shap_ranking.csv")

model        = joblib.load(MODEL_PATH)
feature_cols = pd.read_csv(FEATURES_PATH).iloc[:, 0].tolist()
metrics_df   = pd.read_csv(METRICS_PATH)
shap_ranking = pd.read_csv(SHAP_PATH)

# Pre-compute SHAP explainer once at startup
explainer = shap.TreeExplainer(model)

# NACC code mappings (for human-readable labels in responses)
RACE_MAP     = {1:"White", 2:"Black/African American", 3:"American Indian/Alaska Native",
                4:"Native Hawaiian/Pacific Islander", 5:"Asian", 50:"More than one race"}
PRIMLANG_MAP = {1:"English", 2:"Spanish", 3:"Mandarin/Cantonese", 4:"Russian",
                5:"Japanese", 6:"Other"}
MARISTAT_MAP = {1:"Married", 2:"Widowed", 3:"Divorced", 4:"Separated",
                5:"Never married", 6:"Living with partner"}
NACCLIVS_MAP = {1:"Lives alone", 2:"With spouse/partner", 3:"With relatives",
                4:"With non-relatives", 5:"Assisted living / memory care"}
RESIDENC_MAP = {1:"Single/multi-family home", 2:"Retirement community",
                3:"Assisted living", 4:"Skilled nursing facility"}
INRELTO_MAP  = {1:"Spouse/partner", 2:"Child", 3:"Sibling", 4:"Other relative",
                5:"Paid caregiver", 6:"Friend", 7:"Other"}
HANDED_MAP   = {1:"Right", 2:"Left", 3:"Ambidextrous"}

# ---------------------------------------------------------------------------
# Input schema — raw user inputs (pre-encoding)
# ---------------------------------------------------------------------------
class PredictionInput(BaseModel):
    # Demographics
    BIRTHYR:    int   = Field(..., ge=1880, le=2010, description="Birth year")
    NACCAGEB:   float = Field(..., ge=0,    le=120,  description="Age at baseline visit")
    SEX:        int   = Field(..., ge=1,    le=2,    description="1=Male, 2=Female")
    HISPANIC:   int   = Field(..., ge=0,    le=1,    description="0=No, 1=Yes")
    EDUC:       int   = Field(..., ge=0,    le=36,   description="Years of education")
    RACE:       int   = Field(..., description="Primary race (1-5, 50)")
    PRIMLANG:   int   = Field(..., description="Primary language (1-6)")
    HANDED:     int   = Field(..., description="Handedness: 1=Right, 2=Left, 3=Ambidextrous")
    # Social
    MARISTAT:   int   = Field(..., description="Marital status (1-6)")
    NACCLIVS:   int   = Field(..., description="Living situation (1-5)")
    RESIDENC:   int   = Field(..., description="Residence type (1-4)")
    INRELTO:    int   = Field(..., description="Co-participant relationship (1-7)")
    INLIVWTH:   int   = Field(..., ge=0, le=1, description="Co-participant lives with subject: 0=No, 1=Yes")
    INVISITS:   int   = Field(..., ge=1, le=7, description="In-person visit frequency (1=Daily, 6=<monthly, 7=Lives with)")
    INCALLS:    int   = Field(..., ge=1, le=7, description="Phone call frequency (1=Daily, 6=<monthly, 7=Lives with)")
    # Lifestyle / smoking
    NEVER_SMOKED: int = Field(..., ge=0, le=1, description="Never smoked: 0=No, 1=Yes")
    TOBAC30:    int   = Field(..., ge=0, le=1, description="Smoked in last 30 days: 0=No, 1=Yes")
    TOBAC100:   int   = Field(..., ge=0, le=1, description="Smoked 100+ cigarettes lifetime: 0=No, 1=Yes")
    SMOKYRS:    float = Field(..., ge=0, le=80,  description="Total years smoked")
    PACKSPER:   float = Field(..., ge=0, le=10,  description="Average packs per day")


def encode_input(data: PredictionInput) -> np.ndarray:
    """Convert raw input into the 44-column encoded feature vector the model expects."""
    # Start with a zero vector
    row = {col: 0.0 for col in feature_cols}

    # Numeric / binary features — direct assignment
    row["BIRTHYR"]      = data.BIRTHYR
    row["NACCAGEB"]     = data.NACCAGEB
    row["SEX"]          = data.SEX
    row["HISPANIC"]     = data.HISPANIC
    row["EDUC"]         = data.EDUC
    row["TOBAC30"]      = data.TOBAC30
    row["TOBAC100"]     = data.TOBAC100
    row["SMOKYRS"]      = data.SMOKYRS
    row["PACKSPER"]     = data.PACKSPER
    row["INLIVWTH"]     = data.INLIVWTH
    row["INVISITS"]     = data.INVISITS
    row["INCALLS"]      = data.INCALLS
    row["NEVER_SMOKED"] = data.NEVER_SMOKED
    row["PACK_YEARS"]   = data.SMOKYRS * data.PACKSPER

    # One-hot encoded columns (drop_first=True was used, so reference category = 1.0)
    for col_prefix, value, categories in [
        ("RACE",     data.RACE,     [2, 3, 4, 5, 50]),
        ("PRIMLANG", data.PRIMLANG, [2, 3, 4, 5, 6]),
        ("MARISTAT", data.MARISTAT, [2, 3, 4, 5, 6]),
        ("NACCLIVS", data.NACCLIVS, [2, 3, 4, 5]),
        ("RESIDENC", data.RESIDENC, [2, 3, 4]),
        ("INRELTO",  data.INRELTO,  [2, 3, 4, 5, 6, 7]),
        ("HANDED",   data.HANDED,   [2, 3]),
    ]:
        for cat in categories:
            col_name = f"{col_prefix}_{float(cat)}"
            if col_name in row:
                row[col_name] = 1.0 if value == cat else 0.0

    return np.array([row[col] for col in feature_cols]).reshape(1, -1)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    return {"message": "Dementia Risk Predictor API is running."}


@app.get("/health")
def health():
    return {"status": "ok", "model": "xgboost_tuned", "features": len(feature_cols)}


@app.post("/predict")
def predict(data: PredictionInput):
    """Return risk probability and classification for a single subject."""
    try:
        X = encode_input(data)
        prob      = float(model.predict_proba(X)[0, 1])
        label     = int(prob >= 0.397)   # optimal threshold from evaluation
        risk_pct  = round(prob * 100, 1)

        return {
            "risk_probability": prob,
            "risk_percent":     risk_pct,
            "prediction":       label,
            "risk_label":       "At Risk" if label == 1 else "Not At Risk",
            "threshold_used":   0.397,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/explain")
def explain(data: PredictionInput):
    """Return SHAP values for a single prediction."""
    try:
        X           = encode_input(data)
        shap_vals   = explainer.shap_values(X)[0]
        base_value  = float(explainer.expected_value)

        contributions = [
            {"feature": feat, "shap_value": round(float(sv), 4), "feature_value": float(X[0, i])}
            for i, (feat, sv) in enumerate(zip(feature_cols, shap_vals))
        ]
        contributions.sort(key=lambda x: abs(x["shap_value"]), reverse=True)

        return {
            "base_value":      base_value,
            "contributions":   contributions[:15],   # top 15 for display
            "all_contributions": contributions,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/metrics")
def get_metrics():
    """Return model comparison metrics for all three tuned models."""
    return metrics_df.to_dict(orient="records")


@app.get("/feature-importance")
def feature_importance():
    """Return global SHAP feature importance ranking."""
    return shap_ranking.to_dict(orient="records")