from fastapi import FastAPI
from pydantic import BaseModel, Field
import numpy as np
import pandas as pd
import joblib
import os

app = FastAPI(
    title="Worker Health AI",
    description="Worker health risk prediction API for ESP32",
    version="1.0.0"
)

MODEL_PATH = "worker_health_model.pkl"
ENCODER_PATH = "label_encoder.pkl"
FEATURE_PATH = "feature_columns.pkl"

ACTIVITY_INTENSITY = {
    "idle_monitoring": 0.20,
    "walking": 0.50,
    "carrying_tools": 0.70,
    "heavy_lifting": 0.90,
    "climbing": 0.85,
    "hammer_drilling": 0.95,
    "grinding": 0.80,
    "gas_inspection": 0.60,
    "confined_space": 0.90,
    "emergency_escape": 1.00,
    "rest_break": 0.10
}

class SensorData(BaseModel):
    worker_type: str
    activity: str
    environment: str

    HR: float = Field(..., ge=30, le=220)
    HRV: float = Field(..., ge=1, le=150)
    SpO2: float = Field(..., ge=50, le=100)
    body_temp: float = Field(..., ge=30, le=45)

    env_temp: float = Field(..., ge=-20, le=70)
    humidity: float = Field(..., ge=0, le=100)

    MQ2: float = Field(..., ge=0)
    MQ5: float = Field(..., ge=0)
    MQ135: float = Field(..., ge=0)

    acc_mag: float = Field(..., ge=0)
    gyro_mag: float = Field(..., ge=0)

def load_artifacts():
    for path in (MODEL_PATH, ENCODER_PATH, FEATURE_PATH):
        if not os.path.exists(path):
            raise FileNotFoundError(f"{path} not found")

    return (
        joblib.load(MODEL_PATH),
        joblib.load(ENCODER_PATH),
        joblib.load(FEATURE_PATH)
    )

model, label_encoder, feature_columns = load_artifacts()

def calculate_body_temperature_effect(body_temp):
    if body_temp <= 37.0:
        return 0.0
    elif body_temp <= 38.0:
        return body_temp - 37.0
    return 1.0 + (body_temp - 38.0) * 1.5

def build_features(data):
    HR = float(data["HR"])
    HRV = float(data["HRV"])
    SpO2 = float(data["SpO2"])
    body_temp = float(data["body_temp"])
    env_temp = float(data["env_temp"])
    humidity = float(data["humidity"])
    MQ2 = float(data["MQ2"])
    MQ5 = float(data["MQ5"])
    MQ135 = float(data["MQ135"])
    acc_mag = float(data["acc_mag"])
    gyro_mag = float(data["gyro_mag"])

    worker_type = data["worker_type"]
    activity = data["activity"]
    environment = data["environment"]

    intensity = ACTIVITY_INTENSITY.get(activity, 0.50)

    motion_index = 0.6 * acc_mag + 0.4 * gyro_mag
    motion_stress = motion_index / 20.0

    cardiac_stress = max(0.0, (HR - 70.0) / 70.0)

    oxygen_risk = max(0.0, (98.0 - SpO2) / 10.0)

    fatigue_effect = intensity * 0.05
    fatigue_index = np.clip(
        fatigue_effect + (100.0 - HRV) / 100.0,
        0.0,
        1.0
    )

    gas_from_mq2 = MQ2 / 800.0
    gas_from_mq5 = MQ5 / 900.0
    gas_from_mq135 = (
        MQ135 - (env_temp - 28.0) * 10.0
    ) / 750.0

    gas_level = np.clip(
        np.mean([gas_from_mq2, gas_from_mq5, gas_from_mq135]),
        0.0,
        1.0
    )

    temp_stress = abs(env_temp - 28.0) / 10.0

    environmental_stress = 0.6 * gas_level + 0.4 * temp_stress

    heat_stress = env_temp / 40.0
    body_temp_effect = calculate_body_temperature_effect(body_temp)
    heat_stress += 0.25 * body_temp_effect

    base_activity_stress = 0.4 * intensity + 0.3 * intensity ** 2

    estimated_variation = (
        0.015 * cardiac_stress
        + 0.010 * fatigue_index
        + 0.010 * motion_stress
    )

    activity_stress = base_activity_stress + estimated_variation

    risk_score_raw = (
        0.28 * cardiac_stress
        + 0.22 * oxygen_risk
        + 0.18 * fatigue_index
        + 0.15 * environmental_stress
        + 0.10 * activity_stress
        + 0.07 * motion_stress
        + 0.10 * body_temp_effect
    )

    return {
        "HR": HR, "HRV": HRV, "SpO2": SpO2,
        "body_temp": body_temp,
        "env_temp": env_temp, "humidity": humidity,
        "MQ2": MQ2, "MQ5": MQ5, "MQ135": MQ135,
        "acc_mag": acc_mag, "gyro_mag": gyro_mag,
        "worker_type": worker_type,
        "activity": activity,
        "environment": environment,
        "motion_index": motion_index,
        "motion_stress": motion_stress,
        "cardiac_stress": cardiac_stress,
        "oxygen_risk": oxygen_risk,
        "fatigue_index": fatigue_index,
        "heat_stress": heat_stress,
        "body_temp_effect": body_temp_effect,
        "environmental_stress": environmental_stress,
        "activity_stress": activity_stress,
        "risk_score_raw": risk_score_raw
    }

def preprocess(features):
    df = pd.DataFrame([features])

    df = pd.get_dummies(
        df,
        columns=["worker_type", "activity", "environment"],
        drop_first=True
    )

    return df.reindex(
        columns=feature_columns,
        fill_value=0
    )

def get_risk_level(alert_level):
    # Keep GREEN/YELLOW/RED exactly as the model encoder returns them.
    # risk_level is the human-readable LOW/MEDIUM/HIGH equivalent.
    normalized = alert_level.upper()

    if normalized == "GREEN":
        return "LOW"
    elif normalized == "YELLOW":
        return "MEDIUM"
    return "HIGH"

def predict_worker(sensor_data):
    features = build_features(sensor_data)
    X = preprocess(features)

    prediction = model.predict(X)[0]

    alert_level = (
        label_encoder
        .inverse_transform([prediction])[0]
        .upper()
    )

    raw_risk = features["risk_score_raw"]

    risk_score = np.clip(
        raw_risk * 100.0,
        0.0,
        100.0
    )

    risk_level = get_risk_level(alert_level)

    return {
        "alert_level": alert_level,
        "risk_score": round(float(risk_score), 2),
        "risk_level": risk_level,

        "HR": round(features["HR"], 2),
        "HRV": round(features["HRV"], 2),
        "SpO2": round(features["SpO2"], 2),
        "body_temp": round(features["body_temp"], 2),
        "env_temp": round(features["env_temp"], 2),
        "humidity": round(features["humidity"], 2),
        "MQ2": round(features["MQ2"], 2),
        "MQ5": round(features["MQ5"], 2),
        "MQ135": round(features["MQ135"], 2),
        "acc_mag": round(features["acc_mag"], 2),
        "gyro_mag": round(features["gyro_mag"], 2),

        "cardiac_stress": round(features["cardiac_stress"], 3),
        "oxygen_risk": round(features["oxygen_risk"], 3),
        "fatigue_index": round(features["fatigue_index"], 3),
        "heat_stress": round(features["heat_stress"], 3),
        "body_temp_effect": round(features["body_temp_effect"], 3),
        "environmental_stress": round(features["environmental_stress"], 3),
        "activity_stress": round(features["activity_stress"], 3),
        "motion_index": round(features["motion_index"], 3),
        "motion_stress": round(features["motion_stress"], 3)
    }

@app.get("/")
def home():
    return {
        "status": "online",
        "service": "Worker Health AI",
        "model": type(model).__name__,
        "features": len(feature_columns),
        "message": "Worker Health AI API is running"
    }

@app.get("/health")
def health():
    return {
        "status": "healthy",
        "model_loaded": True,
        "model": type(model).__name__,
        "number_of_features": len(feature_columns)
    }

@app.post("/predict")
def predict(sensor: SensorData):
    return predict_worker(sensor.model_dump())
