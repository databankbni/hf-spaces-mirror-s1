# backend/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch

app = FastAPI(title="SARA IndoBERT Two-Stage Multi-Label API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Jalur kedua model lokal kamu
MAIN_MODEL_PATH = "./model_indobert_sara"
EXT_MODEL_PATH = "./model_indobert_ext"

try:
    print("⏳ Sedang memuat kedua model lokal IndoBERT...")
    
    # 2. Ambil tokenizer & model utama menggunakan variabel yang sudah pasti ada
    tokenizer = AutoTokenizer.from_pretrained(MAIN_MODEL_PATH, local_files_only=True)
    model_main = AutoModelForSequenceClassification.from_pretrained(MAIN_MODEL_PATH, local_files_only=True)
    model_main.eval()
    
    # 3. Ambil model ekstensi 10 dimensi dari foldernya sendiri
    model_ext = AutoModelForSequenceClassification.from_pretrained(EXT_MODEL_PATH, local_files_only=True)
    model_ext.eval()
    
    print("✅ Kedua Model Lokal Berhasil Dimuat Sempurna!")
except Exception as e:
    print(f"❌ Gagal memuat model lokal: {e}")

class TextRequest(BaseModel):
    text: str

@app.post("/api/predict")
def predict_sara(request: TextRequest):
    if not request.text.strip():
        return {"status": "error", "message": "Teks tidak boleh kosong"}
    
    # Tokenisasi Teks (MAX_LEN = 24 sesuai konfigurasi notebook)
    inputs = tokenizer(request.text, return_tensors="pt", truncation=True, max_length=24, padding="max_length")
    
    # --- TAHAP 3: Prediksi Utama (HS & Abusive) ---
    with torch.no_grad():
        outputs_main = model_main(**inputs)
    probs_main = torch.sigmoid(outputs_main.logits)[0]
    
    prob_hs = probs_main[0].item()
    prob_ab = probs_main[1].item()
    
    hs = 1 if prob_hs >= 0.5 else 0
    ab = 1 if prob_ab >= 0.5 else 0
    
    # Interpretasi kombinasi label seperti di notebook
    if hs == 0 and ab == 0:
        kategori = "Normal"
        deskripsi = "Tidak ada ujaran kebencian, tidak kasar"
    elif hs == 0 and ab == 1:
        kategori = "Kasar Saja"
        deskripsi = "Bahasa kasar, tapi bukan ujaran kebencian"
    elif hs == 1 and ab == 0:
        kategori = "HS Halus"
        deskripsi = "Ujaran kebencian tapi bahasa halus"
    else:
        kategori = "HS Kasar"
        deskripsi = "Ujaran kebencian dengan bahasa kasar"
        
    # --- TAHAP 4: Jalankan Prediksi 10 Dimensi jika HS == 1 ---
    dimensions_result = None
    if hs == 1:
        with torch.no_grad():
            outputs_ext = model_ext(**inputs)
        probs_ext = torch.sigmoid(outputs_ext.logits)[0].tolist()
        
        # Urutan label sesuai struktur EXT_COLS di notebook kamu
        labels_order = [
            'HS_Individual', 'HS_Group',
            'HS_Religion', 'HS_Race', 'HS_Physical', 'HS_Gender', 'HS_Other',
            'HS_Weak', 'HS_Moderate', 'HS_Strong'
        ]
        
        dimensions_result = {labels_order[i]: {"confidence": probs_ext[i], "status": 1 if probs_ext[i] >= 0.5 else 0} for i in range(10)}

    return {
        "status": "success",
        "text": request.text,
        "category": kategori,
        "description": deskripsi,
        "main_metrics": {
            "hate_speech": {"status": hs, "confidence": prob_hs},
            "abusive": {"status": ab, "confidence": prob_ab}
        },
        "dimensions": dimensions_result
    }