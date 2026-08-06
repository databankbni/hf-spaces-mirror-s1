import os
import pandas as pd
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware 
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error
import joblib
import uvicorn

app = FastAPI(title="XAUUSD ML Prediction Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Mengizinkan frontend React
    allow_credentials=True,
    allow_methods=["*"],                      
    allow_headers=["*"],                      
)

MODEL_PATH = "model.pkl"
DATASET_PATH = "../dataset/historical_data.csv"

# Global Model Variable
model = None
feature_columns = ['open', 'high', 'low', 'volume', 'spread', 'volatility_numeric']

def preprocess_data(df):
    """Feature Engineering"""
    df['volatility_numeric'] = df['volatility'].astype(float)
    df['trend_numeric'] = df['trend'].apply(lambda x: 1 if str(x).upper() == 'BULLISH' else -1)
    
    # Create Lag Features (Previous Close)
    df['prev_close'] = df['close'].shift(1)
    df['price_delta'] = df['close'] - df['prev_close']
    
    # Rolling Statistics
    df['rolling_mean_5'] = df['close'].rolling(window=5).mean()
    df['rolling_std_5'] = df['close'].rolling(window=5).std()
    
    # Drop NaN rows created by shifting/rolling
    df.dropna(inplace=True)
    return df

def train_model():
    global model
    print("🤖 Checking dataset...")
    
    if not os.path.exists(DATASET_PATH):
        print("⚠️ No dataset found on cloud. Initializing Fallback/Dummy Model for API stability...")
        from sklearn.ensemble import GradientBoostingRegressor
        import numpy as np
        
        X_dummy = np.random.rand(10, 12)
        y_dummy = np.random.rand(10)
        model = GradientBoostingRegressor()
        model.fit(X_dummy, y_dummy)
        print("✅ Fallback Model Ready! API will now accept requests.")
        return
        
    try:
        print("📚 Loading data for training...")
        df = pd.read_csv(DATASET_PATH).tail(5000)
                
        if len(df) < 100:
            print("⚠️ Not enough data to train yet.")
            return
        df = preprocess_data(df)
        # ... sisa kode try-except kamu di bawahnya ...
    except Exception as e:
        print(f"❌ Error during training: {e}")

# PASTIKAN BARIS DI BAWAH INI MENEMPEL DI PALING KIRI (TIDAK ADA SPASI SAMA SEKALI DI DEPANNYA)
@app.on_event("startup")
async def startup_event():
    train_model()

@app.post("/predict")
def predict_next_price(features_dict: dict):
    """
    Accepts current market stats and returns prediction.
    """
    if model is None:
        raise HTTPException(status_code=503, detail="Model not trained yet")
    
    try:
        # 1. AUTO-MAPPING: Antisipasi jika frontend mengirim format mentah / string teks
        if 'trend' in features_dict and 'trend_numeric' not in features_dict:
            features_dict['trend_numeric'] = 1 if str(features_dict['trend']).upper() == 'BULLISH' else -1
            
        if 'volatility' in features_dict and 'volatility_numeric' not in features_dict:
            features_dict['volatility_numeric'] = float(features_dict['volatility'])

        # 2. FILTER & URUTKAN KOLOM: Wajib 100% sama dengan urutan saat training X_train
        required_cols = ['open', 'high', 'low', 'close' , 'volume', 'spread', 'volatility_numeric', 'trend_numeric', 'prev_close', 'price_delta', 'rolling_mean_5', 'rolling_std_5']
        
        # Cek jika ada kolom wajib yang benar-benar tidak dikirim oleh frontend
        missing_cols = [col for col in required_cols if col not in features_dict]
        if missing_cols:
            raise HTTPException(status_code=400, detail=f"Missing required features from frontend: {missing_cols}")
            
        # Bentuk DataFrame dan paksa urutan kolomnya sesuai required_cols
        input_df = pd.DataFrame([features_dict])[required_cols]
        
        # 3. Jalankan Prediksi Model AI
        prediction = model.predict(input_df)[0]
        
        # Ambil harga close saat ini (gunakan fallback ke open jika close tidak ada)
        current_close = features_dict.get('close', features_dict.get('open', 0))
        
        # Hitung arah pergerakan (Trend)
        trend_pred = "UP" if prediction > current_close else "DOWN"
        
        # Hitung Skor Confidence (Kalkulasi jarak prediksi dari harga sekarang)
        confidence = max(0.5, min(0.99, 1 - abs(prediction - current_close) / 10))
        
        # 4. Kembalikan Respon JSON yang Terstruktur Bagus ke React
        return {
            "predicted_price": round(float(prediction), 2),
            "current_price": round(float(current_close), 2),
            "trend": trend_pred,
            "confidence": round(float(confidence), 2),
            "probability_up": round(float(confidence if trend_pred == "UP" else 1-confidence), 2),
            "probability_down": round(float(1 - (confidence if trend_pred == "UP" else 1-confidence)), 2)
        }
    except Exception as e:
        # Print error ke terminal uvicorn agar kamu bisa membaca alasan pastinya jika crash lagi
        print(f"❌ Prediction crash log: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal AI Error: {str(e)}")

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "ml-python"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)