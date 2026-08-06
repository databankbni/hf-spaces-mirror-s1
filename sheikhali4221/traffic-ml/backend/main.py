from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import joblib
import pandas as pd
import numpy as np
import requests
import os
import warnings
import traceback
import json
from datetime import datetime, timedelta

warnings.filterwarnings("ignore", category=UserWarning)

app = FastAPI(title="Real-Time Traffic Congestion MLOps Inference Engine v2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Model Registry ─────────────────────────────────────────────────────────────
RF_MODEL_PATH      = "traffic_rf_model.pkl"
XGB_MODEL_PATH     = "traffic_xgb_model.pkl"
XGB_REG_MODEL_PATH = "traffic_xgb_reg_model.pkl"
METRICS_FILE_PATH  = "metrics.json"

rf_model      = None
xgb_model     = None
xgb_reg_model = None

# ── CHANGE 1: Load optimal threshold saved by CT pipeline ─────────────────────
OPTIMAL_THRESHOLD = 35.0  # fallback; overwritten below if file exists
try:
    if os.path.exists("optimal_threshold.json"):
        with open("optimal_threshold.json", "r") as _f:
            OPTIMAL_THRESHOLD = float(json.load(_f).get("threshold", 35.0))
        print(f"✅ Optimal threshold loaded: {OPTIMAL_THRESHOLD:.2f}")
    else:
        print(f"⚠️  optimal_threshold.json not found — using fallback {OPTIMAL_THRESHOLD}")
except Exception as e:
    print(f"❌ Threshold load error: {e}")

try:
    if os.path.exists(RF_MODEL_PATH):
        rf_model = joblib.load(RF_MODEL_PATH)
        print("✅ Random Forest Champion loaded from registry.")
    else:
        print("⚠️  RF model not found — awaiting CT pipeline artifact.")
except Exception as e:
    print(f"❌ RF load error: {e}")

try:
    if os.path.exists(XGB_MODEL_PATH):
        xgb_model = joblib.load(XGB_MODEL_PATH)
        print("✅ XGBoost model loaded from registry.")
    else:
        print("⚠️  XGBoost model not found — will run RF-only mode.")
except Exception as e:
    print(f"❌ XGBoost load error: {e}")

try:
    if os.path.exists(XGB_REG_MODEL_PATH):
        xgb_reg_model = joblib.load(XGB_REG_MODEL_PATH)
        print("✅ XGBoost Regressor loaded from registry.")
    else:
        print("⚠️  XGBoost Regressor not found — speed drop won't be predicted.")
except Exception as e:
    print(f"❌ XGBoost Regressor load error: {e}")

# ── Config ─────────────────────────────────────────────────────────────────────
OPENWEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
TOMTOM_API_KEY      = os.getenv("TOMTOM_API_KEY")

# 🚀 LAG FEATURES INJECTED (Strictly updating columns to match training)
FEATURE_COLUMNS     = [
    'hour_sin', 'hour_cos', 'is_weekend', 'is_rush_hour',
    'humidity', 'visibility', 'temperature_c', 'wind_speed',
    'free_flow_speed_kmh', 'speed_drop_lag_1h', 'speed_drop_lag_2h'
]

# ── Schemas ───────────────────────────────────────────────────────────────────
class LocationInput(BaseModel):
    lat: float
    lng: float


# ── Helpers ───────────────────────────────────────────────────────────────────
def get_risk_score(model, features_array: np.ndarray) -> list[float]:
    if hasattr(model, "predict_proba"):
        probs = model.predict_proba(features_array)
        return [float(p[1]) * 100 for p in probs]
    preds = model.predict(features_array)
    return [float(p) * 100 for p in preds]


def ensemble_scores(rf_scores: list[float], xgb_scores: list[float],
                    rf_weight: float = 0.45, xgb_weight: float = 0.55) -> list[float]:
    return [
        rf_weight * r + xgb_weight * x
        for r, x in zip(rf_scores, xgb_scores)
    ]


def build_risk_label(risk: float) -> dict:
    if risk >= 70:
        return {"level": "CRITICAL", "color": "RED",    "badge": "🔴"}
    if risk >= 45:
        return {"level": "HIGH",     "color": "ORANGE", "badge": "🟠"}
    if risk >= 25:
        return {"level": "MODERATE", "color": "YELLOW", "badge": "🟡"}
    return     {"level": "LOW",      "color": "GREEN",  "badge": "🟢"}


# ── Hurdle Model helper ──────────────────────────────────────────────
def hurdle_speed_drop(
    congestion_scores: list[float],
    reg_model,
    features_array: np.ndarray,
    threshold: float = None,
) -> list[float]:
    thr = threshold if threshold is not None else OPTIMAL_THRESHOLD
    drops = [0.0] * len(congestion_scores)

    if reg_model is None:
        return drops

    congested_idx = [i for i, s in enumerate(congestion_scores) if s >= thr]
    if not congested_idx:
        return drops

    X_cong = features_array[congested_idx]
    preds  = reg_model.predict(X_cong)

    for rank, i in enumerate(congested_idx):
        drops[i] = max(0.0, float(preds[rank]))

    return drops


# ── Routes ─────────────────────────────────────────────────────────────────────
@app.get("/")
def health_check():
    return {
        "status": "Active",
        "rf_model_loaded":      rf_model      is not None,
        "xgb_model_loaded":     xgb_model     is not None,
        "xgb_reg_model_loaded": xgb_reg_model is not None,
        "ensemble_mode":        rf_model is not None and xgb_model is not None,
        "optimal_threshold":    OPTIMAL_THRESHOLD,
        "message": "Traffic MLOps Inference Engine v2.0 — RF + XGBoost Ensemble + Hurdle Regression"
    }


@app.get("/models")
def model_info():
    models = []
    if rf_model:
        models.append({
            "name":   "Random Forest Classifier",
            "id":     "rf_v1",
            "type":   "ensemble_tree",
            "status": "champion",
            "weight": 0.45
        })
    if xgb_model:
        models.append({
            "name":   "XGBoost Classifier",
            "id":     "xgb_v1",
            "type":   "gradient_boosting",
            "status": "production",
            "weight": 0.55
        })
    if xgb_reg_model:
        models.append({
            "name":   "XGBoost Regressor (Speed Drop — Hurdle)",
            "id":     "xgb_reg_v1",
            "type":   "gradient_boosting_regression",
            "status": "production"
        })
    return {
        "models":          models,
        "ensemble_active": len(models) >= 2,
        "feature_columns": FEATURE_COLUMNS,
        "threshold":       OPTIMAL_THRESHOLD,
    }


@app.post("/predict")
def predict_traffic(location: LocationInput):
    global rf_model, xgb_model, xgb_reg_model

    if not rf_model:
        try:
            rf_model = joblib.load(RF_MODEL_PATH)
        except Exception:
            raise HTTPException(
                status_code=500,
                detail="RF model artifact missing. Run CT pipeline first."
            )

    if not OPENWEATHER_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="WEATHER_API_KEY environment variable is not set."
        )

    try:
        # ── Weather fetch ────────────────────────────────────────────────────
        forecast_url = (
            f"https://api.openweathermap.org/data/2.5/forecast"
            f"?lat={location.lat}&lon={location.lng}"
            f"&appid={OPENWEATHER_API_KEY}&units=metric"
        )
        weather_res = requests.get(forecast_url, timeout=10)
        if weather_res.status_code != 200:
            raise Exception(f"OpenWeather API error {weather_res.status_code}")

        weather_data = weather_res.json()
        weather_list = weather_data["list"]
        api_offset   = weather_data.get("city", {}).get("timezone", 0)
        base_time    = datetime.utcnow() + timedelta(seconds=api_offset)
        city_name    = weather_data.get("city", {}).get("name", "Unknown")

        # ── TomTom free-flow speed ────────────────────────────────────────────
        real_free_flow = 65.0
        if TOMTOM_API_KEY:
            try:
                tomtom_url = (
                    f"https://api.tomtom.com/traffic/services/4/flowSegmentData"
                    f"/absolute/10/json?point={location.lat},{location.lng}"
                    f"&key={TOMTOM_API_KEY}"
                )
                tt_res = requests.get(tomtom_url, timeout=5)
                if tt_res.status_code == 200:
                    tt_data = tt_res.json()
                    real_free_flow = float(
                        tt_data["flowSegmentData"]["freeFlowSpeed"]
                    )
            except Exception as e:
                print(f"⚠️ TomTom API failed, using fallback speed. Error: {e}")

        # ── Feature matrix & Recursive Auto-Regression (24 hours) ────────────
        parsed_hours  = []
        forecast_24h  = []
        
        final_scores  = []
        rf_scores     = []
        xgb_scores    = []
        speed_drops   = []
        
        # 🚀 Initialize Lags for Hour 0 (Start with 0.0 or real-time drop if available)
        current_lag_1h = 0.0
        current_lag_2h = 0.0

        for i in range(24):
            future_time = base_time + timedelta(hours=i)
            target_ts   = future_time.timestamp()
            closest     = min(weather_list, key=lambda x: abs(x["dt"] - target_ts))
            parsed_hours.append((future_time, closest))

            current_hour_scalar = float(future_time.hour)
            hour_sin = float(np.sin(2 * np.pi * current_hour_scalar / 24.0))
            hour_cos = float(np.cos(2 * np.pi * current_hour_scalar / 24.0))

            current_features = [
                hour_sin,
                hour_cos,
                int(future_time.weekday() >= 5),
                int((7 <= future_time.hour <= 9) or (17 <= future_time.hour <= 19)),
                float(closest["main"]["humidity"]),
                float(closest.get("visibility", 10000)),
                float(closest["main"]["temp"]),
                float(closest.get("wind", {}).get("speed", 0) * 3.6),
                float(real_free_flow),
                float(current_lag_1h),  # 🚀 Auto-Regressive Lag 1 (Pichla Ghanta)
                float(current_lag_2h)   # 🚀 Auto-Regressive Lag 2 (2 Ghante Pehle)
            ]

            X_row = pd.DataFrame([current_features], columns=FEATURE_COLUMNS).values

            # ── 1. Classification (Row by Row) ─────────────────────────────────
            rf_score = get_risk_score(rf_model, X_row)[0]
            rf_scores.append(rf_score)

            if xgb_model:
                xgb_score = get_risk_score(xgb_model, X_row)[0]
                xgb_scores.append(xgb_score)
                final_score = ensemble_scores([rf_score], [xgb_score])[0]
                model_used  = "ensemble"
            else:
                xgb_score = 0.0
                xgb_scores.append(0.0)
                final_score = rf_score
                model_used  = "random_forest"
            
            final_scores.append(final_score)

            # ── 2. Hurdle Regression (Row by Row) ──────────────────────────────
            if xgb_reg_model and final_score >= OPTIMAL_THRESHOLD:
                drop_val = float(xgb_reg_model.predict(X_row)[0])
                drop_val = max(0.0, drop_val)
            else:
                drop_val = 0.0
            
            speed_drops.append(drop_val)

            # ── 3. Build Forecast Dict ─────────────────────────────────────────
            risk       = round(final_score, 1)
            label      = build_risk_label(risk)
            pred_speed = max(0.0, float(real_free_flow) - drop_val)

            forecast_24h.append({
                "time":                  future_time.strftime("%H:00"),
                "risk_percent":          risk,
                "risk":                  risk,
                "status":                label["color"],
                "ui_color_code":         label["color"],
                "level":                 label["level"],
                "badge":                 label["badge"],
                "temp":                  round(closest["main"]["temp"], 1),
                "current_temp":          round(closest["main"]["temp"], 1),
                "humidity":              closest["main"]["humidity"],
                "rf_score":              round(rf_score, 1),
                "xgb_score":             round(xgb_score, 1) if xgb_model else None,
                "speed_drop_kmh":        round(drop_val, 1),
                "predicted_speed_kmh":   round(pred_speed, 1),
            })

            # 🚀 4. RECURSIVE UPDATE FOR NEXT HOUR
            # Pichle ghante ka data aur peechay shift hoga, aur is ghante ki prediction Naya Lag ban jayegi!
            current_lag_2h = current_lag_1h
            current_lag_1h = drop_val

        # Variables mapped for the current prediction block below
        current_risk       = round(final_scores[0], 1)
        current_label      = build_risk_label(current_risk)
        current_weather    = parsed_hours[0][1]
        wind_speed         = round(
            current_weather.get("wind", {}).get("speed", 0) * 3.6, 1
        )
        current_drop       = float(speed_drops[0])
        current_pred_speed = max(0.0, float(real_free_flow) - current_drop)

        # ── Dynamic metrics read ──────────────────────────────────────────────
        try:
            with open(METRICS_FILE_PATH, "r") as f:
                perf_payload = json.load(f)
        except Exception as e:
            print(f"⚠️ Metrics JSON read error: {e}")
            perf_payload = None

        return {
            "current_prediction": {
                "current_risk":          current_risk,
                "prediction_code":       1 if current_risk >= OPTIMAL_THRESHOLD else 0,
                "status":                f"{current_label['badge']} {current_label['level']} ({current_risk:.1f}%)",
                "ui_color_code":         current_label["color"],
                "level":                 current_label["level"],
                "temp":                  round(current_weather["main"]["temp"], 1),
                "current_temp":          round(current_weather["main"]["temp"], 1),
                "feels_like":            round(
                    current_weather["main"].get(
                        "feels_like", current_weather["main"]["temp"]
                    ), 1
                ),
                "humidity":              current_weather["main"]["humidity"],
                "wind_speed_kmh":        wind_speed,
                "city_name":             city_name,
                "weather_desc":          current_weather.get(
                    "weather", [{}]
                )[0].get("description", "").title(),
                "free_flow_speed_kmh":   round(float(real_free_flow), 1),
                "speed_drop_kmh":        round(current_drop, 1),
                "predicted_speed_kmh":   round(current_pred_speed, 1),
            },
            "forecast_24h":    forecast_24h,
            "model_metadata":  {
                "model_used":        model_used,
                "ensemble":          xgb_model is not None,
                "regression_active": xgb_reg_model is not None,
                "hurdle_model":      True,
                "optimal_threshold": OPTIMAL_THRESHOLD,
                "rf_weight":         0.45 if xgb_model else 1.0,
                "xgb_weight":        0.55 if xgb_model else 0.0,
                "features":          FEATURE_COLUMNS,
            },
            "model_performance": perf_payload,
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"🚨 PIPELINE ERROR:\n{traceback.format_exc()}")
        raise HTTPException(status_code=400, detail=str(e))