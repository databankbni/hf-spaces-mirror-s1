from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO, emit
import joblib
import re
import datetime

# =====================================================================
# 1. INISIALISASI FLASK & SOCKETIO
# =====================================================================
app = Flask(__name__)
app.config['SECRET_KEY'] = 'skripsi_rahasia_123'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# =====================================================================
# 2. METADATA MODEL (dipakai dashboard & untuk menampilkan info model aktif)
#    Angka diambil dari tabel perbandingan yang sudah kamu tampilkan di web.
# =====================================================================
MODEL_META = {
    'svm': {'name': 'SVM (Support Vector Machine)', 'accuracy': '78.47%', 'precision': '86.09%', 'recall': '78.47%', 'f1': '79.65%'},
    'rf':  {'name': 'Random Forest Classifier',      'accuracy': '83.02%', 'precision': '89.56%', 'recall': '83.02%', 'f1': '84.15%'},
    'pac': {'name': 'PAC (Passive Aggressive)',       'accuracy': '78.36%', 'precision': '83.43%', 'recall': '78.36%', 'f1': '78.26%'},
}

# Model yang sedang aktif dipakai untuk memprediksi log yang masuk.
# Diubah lewat endpoint /set_model saat user memilih di dashboard.
current_model_key = 'rf'

# =====================================================================
# 2B. THRESHOLD KEPERCAYAAN PER MODEL (BARU)
#     SVM & PAC pakai decision_function -> skalanya margin, tidak dibatasi 0-1.
#     Random Forest pakai predict_proba -> skalanya probabilitas, dibatasi 0-1.
#     Karena skalanya beda, angka ambang batasnya juga tidak boleh disamakan.
#     Angka di bawah ini titik awal — sebaiknya di-tuning pakai data validasi.
# =====================================================================
CONFIDENCE_THRESHOLD = {
    'svm': 0.3,
    'pac': 0.3,
    'rf': 0.15,
}

# =====================================================================
# 3. ROUTE UNTUK HALAMAN WEB
# =====================================================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/home')
def home():
    return "Server AI Logcat Berjalan Normal!", 200

@app.route('/dashboard')
def dashboard():
    meta = MODEL_META[current_model_key]
    model_info = {
        "algorithm": meta['name'],
        "accuracy": meta['f1'],
        "key": current_model_key
    }

    recent_logs = []
    bug_stats = {
        'crash': 0, 'anr': 0, 'memory_leak': 0, 'permission_denial': 0,
        'network_error': 0, 'battery_low': 0, 'lag': 0, 'thread_error': 0,
        'media_error': 0, 'usage_stats': 0
    }

    return render_template(
        'dashboard.html',
        model_info=model_info,
        recent_logs=recent_logs,
        bug_stats=bug_stats,
        model_meta=MODEL_META,
        active_model=current_model_key
    )

@app.route('/history')
def history_page():
    return render_template('history.html')

# =====================================================================
# 4. LOAD SEMUA MODEL & VECTORIZER
#    Ketiga model pakai satu tfidf_vectorizer yang sama (fitur training sama).
# =====================================================================
MODELS = {}
tfidf = None
try:
    MODELS['svm'] = joblib.load('model_svm_logcat.pkl')
    MODELS['rf'] = joblib.load('model_rf_logcat.pkl')
    MODELS['pac'] = joblib.load('model_pac_logcat.pkl')
    tfidf = joblib.load('tfidf_vectorizer.pkl')
    print("✅ Semua model AI (SVM, RF, PAC) berhasil dimuat!")
except Exception as e:
    print(f"❌ Gagal memuat model: {e}")

# =====================================================================
# 5. ENDPOINT UNTUK MENGGANTI MODEL AKTIF (dipanggil dari dropdown dashboard)
# =====================================================================
@app.route('/set_model', methods=['POST'])
def set_model():
    global current_model_key
    data = request.json or {}
    key = data.get('model_key')

    if key not in MODELS:
        return jsonify({"status": "error", "message": "Model tidak dikenali"}), 400

    current_model_key = key

    # Beri tahu semua client dashboard yang sedang terbuka agar tampilannya sinkron
    socketio.emit('model_changed', {
        "model_key": key,
        "model_name": MODEL_META[key]['name'],
        "f1": MODEL_META[key]['f1']
    })

    return jsonify({"status": "success", "active_model": key})

# =====================================================================
# 6. FUNGSI PREPROCESSING (SINKRON DENGAN DATASET TRAINING)
# =====================================================================
def clean_text(text):
    text = str(text).lower()
    text = re.sub(r'\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\.\d{3}\s+\d+\s+\d+\s+[a-z]\s+', ' ', text)
    text = re.sub(r'\b\d+\b', ' ', text)
    text = re.sub(r'[^a-z._\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()

# =====================================================================
# 7. FUNGSI REKOMENDASI (10 KELAS)
#    Tiap kategori sekarang 4 poin terpisah per baris (bukan 1 kalimat
#    panjang), supaya feedback lebih banyak & lebih mudah dibaca di web.
# =====================================================================
def get_recommendation(label):
    recommendations = {
        'crash': [
            "1. Aplikasi berhenti mendadak (Force Close) akibat exception yang tidak tertangani.",
            "2. Periksa baris Stacktrace pada kode Java/Kotlin untuk menemukan akar masalah.",
            "3. Lakukan pengecekan variabel untuk menghindari NullPointerException.",
            "4. Bungkus kode berisiko dengan try-catch agar aplikasi tidak force close total."
        ],
        'anr': [
            "1. Terdeteksi proses berat yang memblokir Main Thread (Application Not Responding).",
            "2. Pindahkan operasi berat ke Background Thread.",
            "3. Gunakan Kotlin Coroutines atau RxJava untuk tugas yang bersifat asinkron.",
            "4. Hindari memanggil operasi database/network langsung dari Main Thread."
        ],
        'memory_leak': [
            "1. Terjadi kebocoran memori (berisiko OutOfMemoryError).",
            "2. Pastikan Context, Bitmap, atau database cursor sudah ditutup (close) setelah digunakan.",
            "3. Hindari referensi objek statis yang tidak perlu.",
            "4. Gunakan applicationContext, bukan Activity context, untuk objek berumur panjang."
        ],
        'permission_denial': [
            "1. Akses ditolak oleh sistem (SecurityException).",
            "2. Pastikan Anda telah menambahkan deklarasi <uses-permission> yang tepat di AndroidManifest.xml.",
            "3. Tangani juga request permission pada saat runtime.",
            "4. Cek status izin dengan ContextCompat.checkSelfPermission() sebelum menjalankan fitur terkait."
        ],
        'network_error': [
            "1. Kegagalan interaksi jaringan (IOException).",
            "2. Periksa koneksi internet perangkat dan ketersediaan server.",
            "3. Pastikan aplikasi memiliki izin akses internet di manifest.",
            "4. Terapkan retry mechanism atau tampilkan pesan error yang informatif ke pengguna."
        ],
        'battery_low': [
            "1. Peringatan status baterai perangkat sangat rendah.",
            "2. Sistem Android otomatis membatasi performa CPU dan background task.",
            "3. Tunda proses sinkronisasi data yang berat.",
            "4. Uji perilaku aplikasi secara khusus di bawah Battery Saver Mode."
        ],
        'lag': [
            "1. Terdeteksi penurunan frame rate pada antarmuka.",
            "2. Kurangi proses rendering UI yang kompleks.",
            "3. Optimasi memori gambar dan hindari iterasi berat di dalam fungsi onDraw().",
            "4. Gunakan RecyclerView dengan ViewHolder pattern untuk list yang panjang."
        ],
        'thread_error': [
            "1. Masalah sinkronisasi pada proses latar belakang.",
            "2. Dilarang memperbarui elemen UI langsung dari background thread.",
            "3. Gunakan runOnUiThread() atau Handler.",
            "4. Untuk Coroutines, pastikan update UI dijalankan di withContext(Dispatchers.Main)."
        ],
        'media_error': [
            "1. Kesalahan saat mengakses aset multimedia (Audio/Video).",
            "2. Pastikan format codec didukung secara native oleh Android.",
            "3. Periksa apakah file media rusak (corrupt) atau path tidak ditemukan.",
            "4. Sediakan fallback/placeholder jika file media gagal dimuat."
        ],
        'usage_stats': [
            "1. Rekaman log informasi penggunaan sistem standar.",
            "2. Tidak ada tindakan perbaikan kritis yang diperlukan.",
            "3. Log ini murni indikator aktivitas operasional perangkat.",
            "4. Fokuskan perhatian pada kategori lain yang memang mengindikasikan error."
        ],
        'uncertain': [
            "1. Model AI ragu-ragu (Confidence rendah) dalam mengklasifikasikan log ini.",
            "2. Kemungkinan besar ini adalah log sistem normal, bukan error aplikasi.",
            "3. Cek manual isi log lengkap jika diperlukan untuk memastikan."
        ]
    }

    points = recommendations.get(label)
    if not points:
        return "Analisis manual diperlukan untuk log ini."

    return "\n".join(points)

# =====================================================================
# 7B. FUNGSI EKSTRAKSI PESAN INTI (untuk tampilan, BUKAN untuk klasifikasi)
#     Tujuannya: dari 10 baris konteks yang dikirim plugin, ambil cuma
#     baris exception yang paling relevan, mirip yang plugin tampilkan
#     (mis. "java.lang.NullPointerException: Attempt to invoke...").
# =====================================================================
def extract_main_line(raw_log):
    if not raw_log:
        return raw_log

    # Pola nama exception/error khas Java/Kotlin, contoh:
    # java.lang.NullPointerException, java.io.IOException, OutOfMemoryError, dst.
    # Diikuti pesan detail (kalau ada) sampai ketemu tag log berikutnya (E/, W/, dst).
    pattern = r'(?:[a-zA-Z_$][\w$]*\.)*[A-Z][\w$]*(?:Exception|Error)\w*(?:\s*:\s*[^\n]*?)?(?=\s+[EWIDV]/|\n|$)'
    matches = re.findall(pattern, raw_log)

    if matches:
        # Ambil kemunculan TERAKHIR: pada stacktrace Android, baris paling
        # akhir/dalam biasanya berisi exception paling spesifik (akar masalah).
        return matches[-1].strip()

    # Fallback: kalau tidak ada pola Exception/Error, cari baris dengan kata kunci umum
    keywords = ['FATAL', 'ANR', 'denied', 'failed', 'leak', 'timeout']
    for line in reversed(raw_log.split('\n')):
        if any(k.lower() in line.lower() for k in keywords):
            return line.strip()

    # Fallback terakhir: potong biar tidak kepanjangan
    return raw_log.strip()[:200]

# =====================================================================
# 8. ENDPOINT API PREDIKSI DENGAN CONFIDENCE THRESHOLD + PILIHAN MODEL
# =====================================================================
@app.route('/predict', methods=['POST'])
def predict():
    data = request.json
    raw_log = data.get('log_text', '')

    if not raw_log:
        return jsonify({"status": "error", "message": "Log kosong"}), 400

    # Model bisa dikirim manual per-request (mis. dari plugin), kalau tidak
    # ada, pakai model yang lagi aktif dipilih di dashboard web.
    model_key = data.get('model_key', current_model_key)
    if model_key not in MODELS:
        model_key = current_model_key
    model = MODELS[model_key]

    # 1. Cleaning sesuai training
    cleaned = clean_text(raw_log)

    # 2. Vectorization
    vector = tfidf.transform([cleaned])

    # 3. Prediksi Awal
    prediction = str(model.predict(vector)[0])
    prediksi_final = prediction

    # 4. Terapkan Confidence Threshold (Ambang Keyakinan)
    #    SVM & PAC punya decision_function, Random Forest tidak -> pakai predict_proba.
    THRESHOLD = CONFIDENCE_THRESHOLD.get(model_key, 0.15)  # BARU: threshold sesuai model_key, bukan angka tetap

    if hasattr(model, 'decision_function'):
        scores = model.decision_function(vector)[0]
        if len(scores) > 1:
            sorted_scores = sorted(scores)
            confidence = sorted_scores[-1] - sorted_scores[-2]
            if confidence < THRESHOLD:
                prediksi_final = "uncertain"
    elif hasattr(model, 'predict_proba'):
        proba = model.predict_proba(vector)[0]
        if len(proba) > 1:
            sorted_proba = sorted(proba)
            confidence = sorted_proba[-1] - sorted_proba[-2]
            if confidence < THRESHOLD:
                prediksi_final = "uncertain"

    if prediksi_final == "uncertain":
        return jsonify({
            "status": "ignored",
            "category": "uncertain",
            "model_used": model_key,
            "threshold_used": THRESHOLD,  # BARU: opsional, memudahkan debugging
            "message": "Keyakinan AI rendah, log tidak dikirim ke dashboard"
        }), 200

    solusi = get_recommendation(prediksi_final)

    # =================================================================
    # FITUR: MENDETEKSI LOKASI FILE & BARIS KODE (TANPA RETRAIN)
    # =================================================================
    match_lokasi = re.search(r'\(([^)]+\.(?:kt|java):\d+)\)', raw_log)
    if match_lokasi:
        lokasi_file = match_lokasi.group(1)
        solusi = f"{solusi} \n\n💡 Cek baris kode ini: {lokasi_file}"
    # =================================================================

    waktu_sekarang = datetime.datetime.now()

    pesan_ringkas = extract_main_line(raw_log)

    payload_web = {
        "id": str(int(waktu_sekarang.timestamp() * 1000)),
        "waktu_str": data.get('timestamp', waktu_sekarang.strftime('%Y-%m-%d %H:%M:%S')),
        "package_name": data.get('package_name', 'Android App'),
        "prediksi_kategori": prediksi_final,
        "solusi_ai": solusi,
        "raw_logcat": pesan_ringkas,
        "raw_logcat_full": raw_log,
        "model_used": model_key
    }

    socketio.emit('new_exception', payload_web)

    return jsonify({
        "status": "success",
        "category": prediksi_final,
        "recommendation": solusi,
        "model_used": model_key
    })

# =====================================================================
# 9. JALANKAN SERVER
# =====================================================================
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=7860, allow_unsafe_werkzeug=True)