import os
import pickle
import base64
import io

import pandas as pd
import numpy as np
import tensorflow as tf
from tensorflow.keras.models import load_model
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from flask import Flask, request, jsonify, send_from_directory, render_template

app = Flask(__name__, static_folder='.', static_url_path='')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, 'model', 'save_model', 'model_klasifikasi_kemiskinan.keras')
SCALER_PATH = os.path.join(BASE_DIR, 'model', 'save_model', 'scaler.pkl')
DATASET_PATH = os.path.join(BASE_DIR, 'Model', 'Klasifikasi_Kemiskinan.csv')

model = None
scaler = None
df = None

def load_ml_assets():
    global model, scaler, df
    if os.path.exists(MODEL_PATH) and os.path.exists(SCALER_PATH):
        model = load_model(MODEL_PATH)
        with open(SCALER_PATH, 'rb') as f:
            scaler = pickle.load(f)
    if os.path.exists(DATASET_PATH):
        df = pd.read_csv(DATASET_PATH)

load_ml_assets()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/predict', methods=['POST'])
def predict():
    if model is None or scaler is None:
        return jsonify({'error': 'Model atau scaler belum dimuat'}), 500

    data = request.json
    try:
        input_data = np.array([[
            data['p0'],
            data['lama_sekolah'],
            data['pengeluaran'],
            data['ipm'],
            data['uhh'],
            data['sanitasi'],
            data['air_minum'],
            data['tpt'],
            data['tpak'],
            data['pdrb']
        ]])
        
        input_scaled = scaler.transform(input_data)
        prob = model.predict(input_scaled)[0][0]
        prediction = int(prob > 0.5)
        
        return jsonify({
            'prediction': prediction,
            'probability': float(prob)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/plot', methods=['POST'])
def plot_komparatif():
    if df is None:
        return jsonify({'error': 'Dataset tidak ditemukan'}), 500
        
    data = request.json
    feature = data.get('feature')
    current_value = float(data.get('current_value'))
    
    features_list = {
        "Persentase Penduduk Miskin (P0)": "Persentase Penduduk Miskin (P0) Menurut Kabupaten/Kota (Persen)",
        "Pengeluaran per Kapita": "Pengeluaran per Kapita Disesuaikan (Ribu Rupiah/Orang/Tahun)",
        "Indeks Pembangunan Manusia (IPM)": "Indeks Pembangunan Manusia",
        "Umur Harapan Hidup (UHH)": "Umur Harapan Hidup (Tahun)"
    }
    
    if feature not in features_list:
        return jsonify({'error': 'Fitur tidak valid'}), 400
        
    selected_feat_col = features_list[feature]
    
    fig, ax = plt.subplots(figsize=(10, 3.8))
    sns.kdeplot(data=df, x=selected_feat_col, fill=True, color="#334155", alpha=0.15, linewidth=2.0, ax=ax)
    ax.axvline(current_value, color="#e0473f", linestyle="--", linewidth=1.5, label="Nilai Input Anda")
    
    fig.patch.set_facecolor('none')
    ax.set_facecolor('none')
    ax.tick_params(colors='#64748b', labelsize=8)
    ax.spines['bottom'].set_color('#cbd5e1')
    ax.spines['left'].set_color('#cbd5e1')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.grid(True, linestyle=":", alpha=0.3, color="#cbd5e1")
    
    ax.set_title(f"Posisi Input Anda pada Distribusi {feature} Nasional", color="#0f172a", fontsize=10, fontweight='bold', pad=15, family='sans-serif')
    ax.set_xlabel(feature, color="#475569", fontsize=8, family='sans-serif')
    ax.set_ylabel("Kerapatan (Density)", color="#475569", fontsize=8, family='sans-serif')
    ax.legend(facecolor="#ffffff", edgecolor="#cbd5e1", labelcolor="#475569", fontsize=8)
    
    # Save to buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', transparent=True, dpi=120)
    plt.close(fig)
    buf.seek(0)
    
    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    return jsonify({'image': img_base64})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=True, host='0.0.0.0', port=port)
